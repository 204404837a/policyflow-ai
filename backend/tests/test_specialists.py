from __future__ import annotations

from datetime import date, timedelta

from app.agents.claims import ClaimsAgent
from app.agents.kyc import KYCAgent
from app.agents.policy_rag import PolicyAgent
from app.db.models import Member
from app.schemas.agents import PolicyOutput
from app.services.rag_service import Clause, RagService

# ---- KYC -----------------------------------------------------------------


class FakeMembers:
    def __init__(self, member: Member | None) -> None:
        self._m = member

    async def lookup(self, member_id=None, policy_number=None, name=None):  # noqa: ANN001, ANN201
        return self._m


def _member(**kw: object) -> Member:
    base: dict = dict(
        member_id="PT_1",
        name="John Johnson X.",
        id_display_name="John Johnson X.",
        policy_number="MED-GLD-1",
        policy_type="GOLD",
        id_expiry_date=date.today() + timedelta(days=365),
    )
    base.update(kw)
    return Member(**base)


async def test_kyc_clean_pass() -> None:
    agent = KYCAgent(FakeMembers(_member()))
    out = await agent.run(
        {"member_id": "PT_1", "policy_number": "MED-GLD-1", "name": "John Johnson X."}
    )
    assert out.kyc_passed
    assert out.member_found
    assert out.flags == []


async def test_kyc_expired_id() -> None:
    agent = KYCAgent(FakeMembers(_member(id_expiry_date=date.today() - timedelta(days=5))))
    out = await agent.run({"member_id": "PT_1", "name": "John Johnson X."})
    assert out.id_expired
    assert "EXPIRED_ID" in out.flags
    assert not out.kyc_passed


async def test_kyc_name_mismatch() -> None:
    agent = KYCAgent(FakeMembers(_member(name="John Johnson X.")))
    out = await agent.run({"member_id": "PT_1", "name": "Jonathan Smith"})
    assert "NAME_MISMATCH" in out.flags
    assert not out.kyc_passed


async def test_kyc_member_not_found() -> None:
    agent = KYCAgent(FakeMembers(None))
    out = await agent.run({"member_id": "PTX"})
    assert not out.member_found
    assert "MEMBER_NOT_FOUND" in out.flags


# ---- Claims --------------------------------------------------------------


async def test_claims_valid() -> None:
    out = await ClaimsAgent().run(
        {
            "member_id": "PT_1",
            "claim_amount": "$1,200.00",
            "icd_codes": "E11.9",
            "cpt_codes": "99213",
            "provider_npi": "1234567890",
            "service_date": "2025-06-01",
            "patient_name": "John",
        }
    )
    assert out.schema_valid
    assert out.validation_errors == []
    assert out.extracted_fields.claim_amount == 1200.0


async def test_claims_missing_fields() -> None:
    out = await ClaimsAgent().run({"icd_codes": "E11.9", "cpt_codes": "99213"})
    assert not out.schema_valid
    assert any("NPI" in e for e in out.validation_errors)


async def test_claims_invalid_formats() -> None:
    out = await ClaimsAgent().run(
        {
            "icd_codes": "XX",
            "cpt_codes": "12",
            "provider_npi": "12",
            "claim_amount": "-5",
            "service_date": "2025-01-01",
        }
    )
    assert not out.schema_valid


# ---- Policy-RAG ----------------------------------------------------------


class FakeRag:
    def __init__(self, clauses: list[Clause]) -> None:
        self._c = clauses

    async def retrieve(self, cpt, icd, text):  # noqa: ANN001, ANN201
        return self._c


class FakeLLM:
    def __init__(self, out: object) -> None:
        self._out = out

    async def chat(self, alias: str, **kw: object) -> object:
        return self._out


async def test_policy_covered_fills_clause_guardrail() -> None:
    clauses = [
        Clause(text="Procedure 99213 covered at 80%", section="Outpatient", plan="GOLD", score=0.9)
    ]
    llm_out = PolicyOutput(
        covered=True, coverage_percentage=80, policy_clause="", exclusions=[], confidence=0.9
    )
    agent = PolicyAgent(FakeRag(clauses), FakeLLM(llm_out))
    res = await agent.check(["99213"], ["E11.9"], "office visit")
    assert res.covered
    assert res.policy_clause  # guardrail backfilled from the retrieved clause


async def test_policy_no_clause_not_covered() -> None:
    agent = PolicyAgent(FakeRag([]), FakeLLM(None))
    res = await agent.check(["00000"], [], "unknown procedure")
    assert not res.covered
    assert res.exclusions


def test_rerank_prioritizes_code_hits() -> None:
    c1 = Clause(text="general terms", section="A", plan="GOLD", score=0.9)
    c2 = Clause(text="CPT 99213 covered", section="B", plan="GOLD", score=0.1)
    ranked = RagService._rerank([c1, c2], ["99213"])
    assert ranked[0] is c2

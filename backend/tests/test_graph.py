from __future__ import annotations

from app.agents.graph import build_pipeline
from app.agents.orchestrator import make_decision
from app.agents.state import PipelineDeps
from app.schemas.agents import (
    ClaimsExtractedFields,
    ClaimsOutput,
    ClassifierOutput,
    FraudOutput,
    KYCOutput,
    PolicyOutput,
)
from app.schemas.documents import DocumentContent
from app.schemas.enums import DocumentType
from app.services.image_forensics import ImageForensics
from langgraph.checkpoint.memory import MemorySaver


class FakeStorage:
    async def get(self, key: str) -> bytes:
        return b"img"


class FakeClassifier:
    def __init__(self, mapping: dict) -> None:
        self._m = mapping

    async def classify(self, data, *, image_mime="image/png", case_id=None, document_id=None):  # noqa: ANN001, ANN201
        dt, conf = self._m[document_id]
        return ClassifierOutput(doc_type=dt, confidence=conf)


class FakePreprocessor:
    def __init__(self, mapping: dict) -> None:
        self._m = mapping

    async def run(self, dt, data, *, mime="image/png", case_id=None, document_id=None):  # noqa: ANN001, ANN201
        return DocumentContent(fields=self._m.get(document_id, {}))


class FakeKYC:
    def __init__(self, out: KYCOutput) -> None:
        self._out = out

    async def run(self, identity, *, case_id=None):  # noqa: ANN001, ANN201
        return self._out


class FakeClaims:
    async def run(self, fields, *, case_id=None):  # noqa: ANN001, ANN201
        return ClaimsOutput(
            extracted_fields=ClaimsExtractedFields(), schema_valid=True, confidence=0.9
        )


class FakePolicy:
    async def check(self, cpt, icd, text, *, case_id=None):  # noqa: ANN001, ANN201
        return PolicyOutput(covered=True, policy_clause="covered", confidence=0.9)


class FakeFraud:
    def __init__(self, score: float) -> None:
        self._score = score

    async def run(self, ctx, *, case_id=None):  # noqa: ANN001, ANN201
        return FraudOutput(fraud_score=self._score, confidence=0.9)


def _deps(classify_map: dict, fraud_score: float, kyc: KYCOutput | None = None) -> PipelineDeps:
    pre_map = {
        "id1": {"full_name": "John X."},
        "clm1": {
            "member_id": "PT_1",
            "policy_number": "MED-GLD-1",
            "claim_amount": "1200",
            "icd_codes": "E11.9",
            "cpt_codes": "99213",
            "provider_npi": "1234567890",
            "service_date": "2025-06-01",
            "provider_name": "Dr Smith",
        },
    }
    return PipelineDeps(  # type: ignore[arg-type]
        classifier=FakeClassifier(classify_map),
        preprocessor=FakePreprocessor(pre_map),
        kyc=FakeKYC(kyc or KYCOutput(kyc_passed=True, member_found=True, confidence=0.9)),
        claims=FakeClaims(),
        policy=FakePolicy(),
        fraud=FakeFraud(fraud_score),
        storage=FakeStorage(),
        forensics=ImageForensics(),
        orchestrator=make_decision,
    )


_DOCS = [
    {"doc_id": "id1", "storage_key": "raw/c/id1.png", "mime": "image/png"},
    {"doc_id": "clm1", "storage_key": "raw/c/clm1.png", "mime": "image/png"},
]
_GOOD_MAP = {"id1": (DocumentType.ID_DOCUMENT, 0.97), "clm1": (DocumentType.CLAIM_FORM, 0.95)}


async def _invoke(deps: PipelineDeps, thread: str) -> dict:
    graph = build_pipeline(deps, MemorySaver())
    return await graph.ainvoke(
        {"case_id": "c1", "documents": [dict(d) for d in _DOCS], "retry_count": 0},
        config={"configurable": {"thread_id": thread}},
    )


async def test_approve_path() -> None:
    final = await _invoke(_deps(_GOOD_MAP, fraud_score=0.0), "t-approve")
    assert final["decision"] == "APPROVE"
    assert final["current_stage"] == "DECIDED"
    # parallel fan-in accumulated via operator.add reducer
    for ev in ("kyc", "claims", "policy", "fraud"):
        assert ev in final["agent_events"]


async def test_escalate_path_interrupts_before_human() -> None:
    final = await _invoke(_deps(_GOOD_MAP, fraud_score=0.5), "t-escalate")
    assert final["decision"] == "ESCALATE"
    # interrupt_before await_human → node not executed
    assert final["current_stage"] == "DECIDED"


async def test_unknown_routes_to_human_queue() -> None:
    bad_map = {"id1": (DocumentType.UNKNOWN, 0.4), "clm1": (DocumentType.CLAIM_FORM, 0.95)}
    final = await _invoke(_deps(bad_map, fraud_score=0.0), "t-unknown")
    assert final.get("needs_human") is True
    assert final.get("decision") is None  # bailed before specialists/decision
    assert final["current_stage"] == "CLASSIFIED"

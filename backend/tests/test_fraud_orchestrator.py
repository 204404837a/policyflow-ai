from __future__ import annotations

from datetime import date

from app.agents.orchestrator import make_decision
from app.db.models import ClaimHistory
from app.schemas.agents import (
    ClaimsExtractedFields,
    ClaimsOutput,
    FraudOutput,
    KYCOutput,
    PolicyOutput,
)
from app.schemas.enums import Decision, RiskLevel
from app.services.fraud_service import (
    FraudSignals,
    date_conflict,
    proc_diag_mismatch,
    readmission,
    score_case,
    structuring,
)

# ---- fraud signals -------------------------------------------------------


def test_score_clean_is_low() -> None:
    out = score_case(FraudSignals())
    assert out.fraud_score == 0.0
    assert out.risk_level is RiskLevel.LOW
    assert out.anomalies == []


def test_any_signal_escalates() -> None:
    for field in (
        "duplicate_claim",
        "readmission_30d",
        "date_conflict",
        "proc_diag_mismatch",
        "structuring",
        "name_mismatch",
    ):
        out = score_case(FraudSignals(**{field: True}))
        assert out.fraud_score >= 0.3, field
        assert field in out.anomalies


def test_structuring_band() -> None:
    assert structuring(9500.0)
    assert not structuring(8000.0)
    assert not structuring(None)


def test_proc_diag_mismatch() -> None:
    assert proc_diag_mismatch(["59400"], ["E11.9"])  # maternity proc, non-maternity dx
    assert not proc_diag_mismatch(["59400"], ["O80"])  # maternity proc + maternity dx
    assert not proc_diag_mismatch(["99213"], ["E11.9"])  # no maternity proc


def test_date_conflict_and_readmission() -> None:
    assert date_conflict("2025-06-10", "2025-06-05")  # service after discharge
    assert not date_conflict("2025-06-01", "2025-06-05")
    hist = [ClaimHistory(member_id="X", claim_date=date(2025, 6, 1), claim_amount=10)]
    assert readmission("2025-06-20", hist)  # within 30d
    assert not readmission("2025-09-01", hist)


# ---- orchestrator truth table --------------------------------------------


def _kyc(passed=True, conf=0.9):  # noqa: ANN001, ANN202
    return KYCOutput(kyc_passed=passed, member_found=True, confidence=conf)


def _claims(valid=True, conf=0.9):  # noqa: ANN001, ANN202
    return ClaimsOutput(
        extracted_fields=ClaimsExtractedFields(), schema_valid=valid, confidence=conf
    )


def _policy(covered=True, conf=0.9):  # noqa: ANN001, ANN202
    return PolicyOutput(covered=covered, policy_clause="x", confidence=conf)


def _fraud(score=0.0, conf=0.9):  # noqa: ANN001, ANN202
    return FraudOutput(fraud_score=score, confidence=conf)


def test_approve_all_good() -> None:
    d = make_decision(_kyc(), _claims(), _policy(), _fraud(0.0))
    assert d.decision is Decision.APPROVE


def test_reject_precedence_over_fraud() -> None:
    # not covered AND high fraud → REJECT wins (checked first)
    d = make_decision(_kyc(), _claims(), _policy(covered=False), _fraud(0.9))
    assert d.decision is Decision.REJECT


def test_escalate_fraud_boundary() -> None:
    at = make_decision(_kyc(), _claims(), _policy(), _fraud(0.30))
    below = make_decision(_kyc(), _claims(), _policy(), _fraud(0.29))
    assert at.decision is Decision.ESCALATE
    assert below.decision is Decision.APPROVE


def test_escalate_confidence_boundary() -> None:
    low = make_decision(_kyc(conf=0.59), _claims(), _policy(), _fraud())
    ok = make_decision(_kyc(conf=0.60), _claims(), _policy(), _fraud())
    assert low.decision is Decision.ESCALATE
    assert ok.decision is Decision.APPROVE

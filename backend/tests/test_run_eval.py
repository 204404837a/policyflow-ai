"""Tests for the per-stage scorer (eval/run_eval.py).

Uses a tiny hand-built metadata + PredictionSet — no LLM/DB — to lock the
scoring math, the case-fold, and the two hard gates (Decision ≥60%, overall
≥70%).
"""

from __future__ import annotations

from app.schemas.enums import Decision, DocumentType
from eval.predictions import (
    CasePrediction,
    DocPrediction,
    PredictionSet,
    RetrievalPrediction,
)
from eval.run_eval import group_cases, restrict_to_captured, score

# --- ground truth: 2 clusters -----------------------------------------------
# C_001: clean claim + id  -> APPROVE.  C_002: claim with expired_id -> REJECT.
RECORDS: list[dict] = [
    {
        "doc_id": "claim_1",
        "category": "claim_forms",
        "case_cluster_id": "C_001",
        "fraud_label": False,
        "edge_flags": [],
    },
    {
        "doc_id": "id_1",
        "category": "id_documents",
        "case_cluster_id": "C_001",
        "fraud_label": False,
        "edge_flags": [],
    },
    {
        "doc_id": "claim_2",
        "category": "claim_forms",
        "case_cluster_id": "C_002",
        "fraud_label": False,
        "edge_flags": ["missing_fields"],
    },
    {
        "doc_id": "id_2",
        "category": "id_documents",
        "case_cluster_id": "C_002",
        "fraud_label": False,
        "edge_flags": ["expired_id"],
    },
]

_ALL_FIELDS = ["icd_codes", "cpt_codes", "provider_npi", "claim_amount", "service_date"]


def _perfect_predictions() -> PredictionSet:
    return PredictionSet(
        documents=[
            DocPrediction(
                doc_id="claim_1",
                predicted_type=DocumentType.CLAIM_FORM,
                confidence=0.95,
                present_fields=_ALL_FIELDS,
            ),
            DocPrediction(
                doc_id="id_1",
                predicted_type=DocumentType.ID_DOCUMENT,
                confidence=0.95,
                present_fields=[],
            ),
            DocPrediction(
                doc_id="claim_2",
                predicted_type=DocumentType.CLAIM_FORM,
                confidence=0.9,
                present_fields=["icd_codes"],
            ),  # incomplete
            DocPrediction(
                doc_id="id_2",
                predicted_type=DocumentType.ID_DOCUMENT,
                confidence=0.9,
                present_fields=[],
            ),
        ],
        cases=[
            CasePrediction(
                case_id="C_001",
                kyc_flags=[],
                fraud_score=0.0,
                decision=Decision.APPROVE,
                decision_confidence=0.9,
            ),
            CasePrediction(
                case_id="C_002",
                kyc_flags=["expired_id"],
                fraud_score=0.0,
                decision=Decision.REJECT,
                decision_confidence=0.8,
            ),
        ],
        retrieval=[
            RetrievalPrediction(
                cpt_code="59400", retrieved=["m1", "m2", "x"], relevant=["m1", "m2"]
            ),
        ],
    )


def test_group_cases() -> None:
    cases = group_cases(RECORDS)
    assert set(cases) == {"C_001", "C_002"}
    assert len(cases["C_001"]) == 2


def test_restrict_to_captured_keeps_only_captured_cases() -> None:
    preds = PredictionSet(
        cases=[
            CasePrediction(
                case_id="C_001",
                kyc_flags=[],
                fraud_score=0.0,
                decision=Decision.APPROVE,
                decision_confidence=0.9,
            )
        ]
    )
    kept = restrict_to_captured(preds, RECORDS)
    assert {r["doc_id"] for r in kept} == {"claim_1", "id_1"}  # C_002 excluded
    # A sampled run of only C_001 should now score a clean decision (no C_002 penalty).
    assert score(preds, kept).decision_accuracy == 1.0
    # Nothing captured → empty set (no phantom score over default-ESCALATE preds).
    assert restrict_to_captured(PredictionSet(), RECORDS) == []
    empty = score(PredictionSet(), restrict_to_captured(PredictionSet(), RECORDS))
    assert empty.decision_accuracy == 0.0 and empty.captured_cases == 0


def test_perfect_predictions_pass_all_gates() -> None:
    report = score(_perfect_predictions(), RECORDS)
    assert report.classification_accuracy == 1.0
    assert report.extraction_accuracy == 1.0  # complete/incomplete both matched
    assert report.decision_accuracy == 1.0
    assert report.kyc is not None and report.kyc.recall == 1.0
    assert report.decision_gate_passed
    assert report.overall_gate_passed
    assert report.passed


def test_retrieval_relevance_scored() -> None:
    report = score(_perfect_predictions(), RECORDS)
    # 2 of top-3 relevant.
    assert report.retrieval_relevance_at_k == 2 / 3
    assert report.retrieval_mrr == 1.0


def test_wrong_decisions_fail_the_gate() -> None:
    preds = _perfect_predictions()
    for c in preds.cases:
        c.decision = Decision.APPROVE  # C_002 should be REJECT
    report = score(preds, RECORDS)
    assert report.decision_accuracy == 0.5
    assert not report.decision_gate_passed
    assert not report.passed


def test_missing_predictions_scored_as_miss() -> None:
    # Empty capture: every doc a miss, every case defaults to ESCALATE.
    report = score(PredictionSet(), RECORDS)
    assert report.classification_accuracy == 0.0
    # C_001 gold APPROVE, C_002 gold REJECT; both defaulted to ESCALATE → 0%.
    assert report.decision_accuracy == 0.0
    assert any("no prediction" in n for n in report.notes)


def test_missing_claim_field_lowers_extraction() -> None:
    preds = _perfect_predictions()
    # claim_1 is gold-complete (no missing_fields) but predict it incomplete.
    for d in preds.documents:
        if d.doc_id == "claim_1":
            d.present_fields = ["icd_codes"]
    report = score(preds, RECORDS)
    assert report.extraction_accuracy == 0.5  # 1 of 2 claim docs now disagree

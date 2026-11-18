"""Tests for the decision-calibration report (eval/calibration.py)."""

from __future__ import annotations

from app.schemas.enums import Decision
from eval.calibration import decision_calibration, format_calibration
from eval.predictions import CasePrediction, PredictionSet

# C_001 gold APPROVE, C_002 gold REJECT.
RECORDS: list[dict] = [
    {
        "doc_id": "a",
        "category": "claim_forms",
        "case_cluster_id": "C_001",
        "fraud_label": False,
        "edge_flags": [],
    },
    {
        "doc_id": "b",
        "category": "id_documents",
        "case_cluster_id": "C_002",
        "fraud_label": False,
        "edge_flags": ["expired_id"],
    },
]


def test_calibration_counts_correct_and_incorrect() -> None:
    preds = PredictionSet(
        cases=[
            # right, high confidence
            CasePrediction(
                case_id="C_001", fraud_score=0.0, decision=Decision.APPROVE, decision_confidence=0.9
            ),
            # wrong, also high confidence -> hurts calibration
            CasePrediction(
                case_id="C_002", fraud_score=0.0, decision=Decision.APPROVE, decision_confidence=0.9
            ),
        ]
    )
    report = decision_calibration(preds, RECORDS)
    assert report.sample_count == 2
    # Both at 0.9 confidence, 50% actually correct -> ECE = 0.4.
    assert report.ece == 0.4
    assert "ECE=0.400" in format_calibration(report)


def test_calibration_skips_missing_predictions() -> None:
    report = decision_calibration(PredictionSet(), RECORDS)
    assert report.sample_count == 0
    assert report.ece == 0.0

"""Unit tests for the pure eval scoring primitives + decision oracle.

No LLM, no DB — these lock down the definition of "correct" for the graded
metrics (esp. the 25%-weighted Decision Correctness gate).
"""

from __future__ import annotations

import pytest
from app.schemas.enums import Decision
from eval.label_map import derive_case_decision, derive_decision
from eval.metrics import (
    accuracy,
    confusion_matrix,
    expected_calibration_error,
    mean_reciprocal_rank,
    precision_recall_f1,
    reciprocal_rank,
    relevance_at_k,
)


# --- decision oracle (per-record) -------------------------------------------
def test_derive_decision_fraud_escalates() -> None:
    assert derive_decision({"fraud_label": True, "edge_flags": []}) is Decision.ESCALATE


def test_derive_decision_hard_flag_rejects() -> None:
    assert derive_decision({"edge_flags": ["expired_id"]}) is Decision.REJECT
    assert derive_decision({"edge_flags": ["missing_fields"]}) is Decision.REJECT


def test_derive_decision_soft_flag_escalates() -> None:
    assert derive_decision({"edge_flags": ["expiring_soon_id"]}) is Decision.ESCALATE
    assert derive_decision({"blur_simulated": True}) is Decision.ESCALATE


def test_derive_decision_clean_approves() -> None:
    assert derive_decision({"edge_flags": ["has_supporting_docs"]}) is Decision.APPROVE


def test_derive_decision_explicit_wins() -> None:
    assert derive_decision({"expected_decision": "ESCALATE"}) is Decision.ESCALATE


def test_fraud_and_reject_flag_rejects() -> None:
    # Fraud escalates first in per-record precedence (§6.3), before hard flags.
    rec = {"fraud_label": True, "edge_flags": ["expired_id"]}
    assert derive_decision(rec) is Decision.ESCALATE


# --- decision oracle (case fold) --------------------------------------------
def test_case_inherits_most_severe() -> None:
    clean = {"edge_flags": []}
    reject = {"edge_flags": ["expired_id"]}
    escalate = {"fraud_label": True}
    assert derive_case_decision([clean, escalate]) is Decision.ESCALATE
    assert derive_case_decision([clean, escalate, reject]) is Decision.REJECT
    assert derive_case_decision([clean, clean]) is Decision.APPROVE


def test_empty_case_escalates() -> None:
    assert derive_case_decision([]) is Decision.ESCALATE


# --- accuracy / confusion ----------------------------------------------------
def test_accuracy() -> None:
    assert accuracy(["a", "b", "c"], ["a", "b", "x"]) == pytest.approx(2 / 3)
    assert accuracy([], []) == 0.0


def test_accuracy_length_mismatch() -> None:
    with pytest.raises(ValueError):
        accuracy(["a"], ["a", "b"])


def test_confusion_matrix() -> None:
    m = confusion_matrix(["a", "b", "a"], ["a", "b", "b"])
    assert m[("a", "a")] == 1  # gold a, predicted a
    assert m[("b", "a")] == 1  # gold b, predicted a (a miss)


# --- precision / recall / f1 -------------------------------------------------
def test_prf_perfect() -> None:
    prf = precision_recall_f1([True, False, True], [True, False, True])
    assert prf.precision == 1.0 and prf.recall == 1.0 and prf.f1 == 1.0


def test_prf_mixed() -> None:
    # 1 tp, 1 fp, 1 fn
    prf = precision_recall_f1([True, True, False], [True, False, True])
    assert prf.tp == 1 and prf.fp == 1 and prf.fn == 1
    assert prf.precision == pytest.approx(0.5)
    assert prf.recall == pytest.approx(0.5)
    assert prf.f1 == pytest.approx(0.5)


def test_prf_silent_detector_on_clean_set_is_perfect() -> None:
    prf = precision_recall_f1([False, False], [False, False])
    assert prf.precision == 1.0 and prf.recall == 1.0


def test_prf_silent_detector_on_dirty_set_has_zero_recall() -> None:
    prf = precision_recall_f1([False, False], [True, False])
    assert prf.recall == 0.0


# --- retrieval ---------------------------------------------------------------
def test_relevance_at_k() -> None:
    assert relevance_at_k(["a", "b", "c"], {"a", "c"}, k=2) == pytest.approx(0.5)
    assert relevance_at_k(["a", "b", "c"], {"a", "c"}, k=3) == pytest.approx(2 / 3)


def test_relevance_at_k_invalid() -> None:
    with pytest.raises(ValueError):
        relevance_at_k(["a"], {"a"}, k=0)


def test_reciprocal_and_mean_reciprocal_rank() -> None:
    assert reciprocal_rank(["x", "a", "b"], {"a"}) == pytest.approx(0.5)
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0
    mrr = mean_reciprocal_rank([["a", "b"], ["x", "a"]], [{"a"}, {"a"}])
    assert mrr == pytest.approx((1.0 + 0.5) / 2)


# --- calibration (ECE) -------------------------------------------------------
def test_ece_perfectly_calibrated_is_zero() -> None:
    # Within a single bin: mean confidence == observed accuracy.
    conf = [0.95, 0.95, 0.95, 0.95]
    correct = [True, True, True, False]  # 0.75 acc vs 0.95 conf -> gap 0.2
    assert expected_calibration_error(conf, correct, n_bins=10) == pytest.approx(0.2)


def test_ece_matched_confidence_and_accuracy() -> None:
    conf = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
    correct = [True] * 9 + [False]  # 0.9 acc == 0.9 conf
    assert expected_calibration_error(conf, correct) == pytest.approx(0.0, abs=1e-9)


def test_ece_empty() -> None:
    assert expected_calibration_error([], []) == 0.0

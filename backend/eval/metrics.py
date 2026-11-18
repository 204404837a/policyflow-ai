"""Pure scoring primitives for the per-stage eval harness (docs/EVAL_PLAN.md).

Deliberately dependency-free (stdlib only) so the scorer is trivially
unit-testable with no LLM, no numpy, no sklearn — every function is a pure
`(predictions, ground_truth) -> number` mapping. Each stage in `run_eval.py`
picks the lens that fits it (see module docstring guidance):
  * accuracy         — Classification, Decision (one right label per item)
  * precision/recall — Fraud, KYC flags (rare-positive detection)
  * relevance@k/MRR  — Retrieval (ranked list quality)
  * ECE              — Calibration (are confidence numbers trustworthy?)
"""

from __future__ import annotations

from collections.abc import Container, Hashable, Sequence
from dataclasses import dataclass


def _require_same_length(a: Sequence[object], b: Sequence[object]) -> None:
    if len(a) != len(b):
        raise ValueError(f"length mismatch: {len(a)} vs {len(b)}")


def accuracy(predicted: Sequence[Hashable], gold: Sequence[Hashable]) -> float:
    """Fraction of items where prediction == ground truth. Empty → 0.0."""
    _require_same_length(predicted, gold)
    if not gold:
        return 0.0
    hits = sum(1 for p, g in zip(predicted, gold, strict=True) if p == g)
    return hits / len(gold)


def confusion_matrix(
    predicted: Sequence[Hashable], gold: Sequence[Hashable]
) -> dict[tuple[Hashable, Hashable], int]:
    """Sparse (gold, predicted) -> count. Useful for a classification report."""
    _require_same_length(predicted, gold)
    matrix: dict[tuple[Hashable, Hashable], int] = {}
    for p, g in zip(predicted, gold, strict=True):
        matrix[(g, p)] = matrix.get((g, p), 0) + 1
    return matrix


@dataclass(frozen=True)
class PRF:
    """Precision / recall / F1 for one binary detection problem."""

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int


def precision_recall_f1(predicted: Sequence[bool], gold: Sequence[bool]) -> PRF:
    """Binary P/R/F1 over aligned truth arrays (True == positive/flagged).

    Convention when a denominator is zero (no positives predicted or present):
    the metric is 1.0 iff there was nothing to find AND nothing was raised,
    else 0.0 — so a silent detector on a clean set scores perfectly, but on a
    dirty set scores zero recall.
    """
    _require_same_length(predicted, gold)
    tp = sum(1 for p, g in zip(predicted, gold, strict=True) if p and g)
    fp = sum(1 for p, g in zip(predicted, gold, strict=True) if p and not g)
    fn = sum(1 for p, g in zip(predicted, gold, strict=True) if not p and g)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return PRF(precision, recall, f1, tp, fp, fn)


def relevance_at_k(retrieved: Sequence[Hashable], relevant: Container[Hashable], k: int) -> float:
    """Precision@k: of the top-k retrieved items, the fraction that are relevant."""
    if k <= 0:
        raise ValueError("k must be positive")
    top = retrieved[:k]
    if not top:
        return 0.0
    hits = sum(1 for item in top if item in relevant)
    return hits / len(top)


def reciprocal_rank(retrieved: Sequence[Hashable], relevant: Container[Hashable]) -> float:
    """1/rank of the first relevant item (1-indexed); 0.0 if none retrieved."""
    for idx, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / idx
    return 0.0


def mean_reciprocal_rank(
    retrievals: Sequence[Sequence[Hashable]], relevants: Sequence[Container[Hashable]]
) -> float:
    """MRR across multiple queries."""
    _require_same_length(retrievals, relevants)
    if not retrievals:
        return 0.0
    total = sum(reciprocal_rank(r, rel) for r, rel in zip(retrievals, relevants, strict=True))
    return total / len(retrievals)


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    avg_confidence: float
    accuracy: float


def calibration_bins(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> list[CalibrationBin]:
    """Bucket predictions into equal-width confidence bins → reliability curve.

    Each populated bin reports its mean predicted confidence vs its observed
    accuracy; the gap between the two is what ECE integrates.
    """
    _require_same_length(confidences, correct)
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    width = 1.0 / n_bins
    bins: list[CalibrationBin] = []
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        # Last bin is closed on the right so confidence==1.0 lands somewhere.
        members = [
            (c, ok)
            for c, ok in zip(confidences, correct, strict=True)
            if (lo <= c < hi) or (i == n_bins - 1 and c == hi)
        ]
        if not members:
            continue
        conf = sum(c for c, _ in members) / len(members)
        acc = sum(1 for _, ok in members if ok) / len(members)
        bins.append(CalibrationBin(lo, hi, len(members), conf, acc))
    return bins


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> float:
    """ECE: sample-weighted average |avg_confidence − accuracy| across bins.

    0.0 == perfectly calibrated. Answers "can the guardrails trust the
    confidence they gate on (conf<0.6 → ESCALATE)?"
    """
    _require_same_length(confidences, correct)
    total = len(confidences)
    if not total:
        return 0.0
    bins = calibration_bins(confidences, correct, n_bins)
    return sum((b.count / total) * abs(b.avg_confidence - b.accuracy) for b in bins)

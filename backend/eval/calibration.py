"""Calibration report (bonus — PRD §6.2, D13).

Are the pipeline's *decision confidences* trustworthy? For each case we pair the
decision's confidence with whether that decision matched the label-map oracle,
then bin them into a reliability curve + a single ECE number. A well-calibrated
pipeline lets the `conf<0.6 → ESCALATE` guardrail mean what it says.

Pure consumer of `eval.metrics` + the same ground truth as `run_eval` — no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.label_map import derive_case_decision
from eval.metrics import CalibrationBin, calibration_bins, expected_calibration_error
from eval.predictions import PredictionSet
from eval.run_eval import group_cases


@dataclass
class CalibrationReport:
    ece: float
    bins: list[CalibrationBin]
    sample_count: int


def decision_calibration(
    predictions: PredictionSet, records: list[dict], n_bins: int = 10
) -> CalibrationReport:
    """Reliability of per-case decision confidence vs oracle correctness."""
    case_by_id = {c.case_id: c for c in predictions.cases}
    confidences: list[float] = []
    correct: list[bool] = []
    for key, recs in group_cases(records).items():
        cp = case_by_id.get(key)
        if cp is None:  # no prediction → nothing to calibrate
            continue
        confidences.append(cp.decision_confidence)
        correct.append(cp.decision == derive_case_decision(recs))
    return CalibrationReport(
        ece=expected_calibration_error(confidences, correct, n_bins),
        bins=calibration_bins(confidences, correct, n_bins),
        sample_count=len(confidences),
    )


def format_calibration(report: CalibrationReport) -> str:
    lines = [
        "",
        f"Decision calibration (n={report.sample_count})  ECE={report.ece:.3f}",
        f"{'confidence bin':>16}  {'n':>4}  {'avg_conf':>8}  {'accuracy':>8}",
    ]
    for b in report.bins:
        lines.append(
            f"  [{b.lower:.1f},{b.upper:.1f})".rjust(16)
            + f"  {b.count:>4}  {b.avg_confidence:>8.2f}  {b.accuracy:>8.2f}"
        )
    lines.append("")
    return "\n".join(lines)

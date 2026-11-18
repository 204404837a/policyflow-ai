"""Per-stage eval runner (docs/EVAL_PLAN.md §3, PRD §6).

Scores a captured `PredictionSet` against `dataset/metadata.json`, prints a
per-stage report + the rubric-weighted grade, and **hard-gates** Decision
Correctness ≥ 60% and overall ≥ 70%. The scorer (`score`) is a pure function of
(predictions, ground-truth records) so it is unit-testable with no LLM/DB.

    python -m eval.run_eval                 # score dataset/predictions.json
    python -m eval.run_eval --from x.json   # score a specific capture
    python -m eval.run_eval --live          # run the graph over the dataset,
                                            # write predictions.json, then score
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.enums import Decision, DocumentType

from eval.config import (
    CATEGORY_TO_TYPE,
    DECISION_GATE,
    EXPECTED_CLAIM_FIELDS,
    FRAUD_POSITIVE_THRESHOLD,
    GRADE_WEIGHTS,
    KYC_FLAG_UNIVERSE,
    OVERALL_GATE,
    RETRIEVAL_SPOTCHECK_K,
)
from eval.label_map import derive_case_decision
from eval.metrics import (
    PRF,
    accuracy,
    mean_reciprocal_rank,
    precision_recall_f1,
    relevance_at_k,
)
from eval.predictions import PredictionSet

_CLAIM_CATEGORY = "claim_forms"
_MISSING = DocumentType.UNKNOWN  # sentinel for an unpredicted document


# --------------------------------------------------------------------------- #
# Ground truth
# --------------------------------------------------------------------------- #
def _case_key(record: dict) -> str:
    """Cluster id groups a bundle; unknowns (no cluster) are singleton cases."""
    return str(record.get("case_cluster_id") or record["doc_id"])


def group_cases(records: list[dict]) -> dict[str, list[dict]]:
    cases: dict[str, list[dict]] = {}
    for r in records:
        cases.setdefault(_case_key(r), []).append(r)
    return cases


def restrict_to_captured(predictions: PredictionSet, records: list[dict]) -> list[dict]:
    """Keep only the metadata records whose case was actually captured.

    Scoring a partial capture against the full dataset penalizes every case that
    was never run (missing docs → miss, missing cases → default ESCALATE). When
    a run sampled only some cases, grade it against those cases alone so the
    numbers reflect what actually ran (whole bundles are captured together).

    When NOTHING was captured (e.g. a retrieval-only run, or a pipeline run whose
    every case 429-skipped), return an empty set — grading zero predictions
    against the full dataset would otherwise manufacture a phantom score (default
    ESCALATE happening to match the ~40% of labels that are ESCALATE). Empty →
    the pipeline tracks score 0.0 and `captured_cases == 0` flags the run.
    """
    captured = {c.case_id for c in predictions.cases}
    return [r for r in records if _case_key(r) in captured]


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class EvalReport:
    classification_accuracy: float = 0.0
    extraction_accuracy: float = 0.0
    retrieval_relevance_at_k: float = 0.0
    retrieval_mrr: float = 0.0
    decision_accuracy: float = 0.0
    kyc: PRF | None = None
    fraud: PRF | None = None
    weighted_grade: float = 0.0
    captured_cases: int = 0
    skipped_cases: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def decision_gate_passed(self) -> bool:
        return self.decision_accuracy >= DECISION_GATE

    @property
    def overall_gate_passed(self) -> bool:
        return self.weighted_grade >= OVERALL_GATE

    @property
    def passed(self) -> bool:
        # Nothing captured is a failed run, not a silent pass over an empty set.
        return self.captured_cases > 0 and self.decision_gate_passed and self.overall_gate_passed


# --------------------------------------------------------------------------- #
# Scoring (pure)
# --------------------------------------------------------------------------- #
def report_to_dict(report: EvalReport, source: str) -> dict:
    """Serialize an EvalReport to the API's EvalMetrics shape (single source)."""

    def _prf(prf: PRF | None) -> dict | None:
        return {"precision": prf.precision, "recall": prf.recall, "f1": prf.f1} if prf else None

    return {
        "classification_accuracy": report.classification_accuracy,
        "extraction_accuracy": report.extraction_accuracy,
        "retrieval_relevance_at_k": report.retrieval_relevance_at_k,
        "retrieval_mrr": report.retrieval_mrr,
        "decision_accuracy": report.decision_accuracy,
        "kyc": _prf(report.kyc),
        "fraud": _prf(report.fraud),
        "weighted_grade": report.weighted_grade,
        "captured_cases": report.captured_cases,
        "skipped_cases": report.skipped_cases,
        "decision_gate_passed": report.decision_gate_passed,
        "overall_gate_passed": report.overall_gate_passed,
        "passed": report.passed,
        "notes": report.notes,
        "source": source,
    }


def score(predictions: PredictionSet, records: list[dict]) -> EvalReport:
    report = EvalReport()
    doc_by_id = {d.doc_id: d for d in predictions.documents}
    case_by_id = {c.case_id: c for c in predictions.cases}

    # --- Classification: predicted type vs category-derived type ------------
    cls_pred: list[DocumentType] = []
    cls_gold: list[DocumentType] = []
    for r in records:
        gold = CATEGORY_TO_TYPE.get(r.get("category", ""), DocumentType.UNKNOWN)
        pred = doc_by_id[r["doc_id"]].predicted_type if r["doc_id"] in doc_by_id else _MISSING
        cls_pred.append(pred)
        cls_gold.append(gold)
    report.classification_accuracy = accuracy(cls_pred, cls_gold)
    missing_docs = sum(1 for r in records if r["doc_id"] not in doc_by_id)
    if missing_docs:
        report.notes.append(f"{missing_docs} document(s) had no prediction (scored as miss)")

    # --- Extraction: completeness agreement over claim forms ----------------
    ext_pred: list[bool] = []
    ext_gold: list[bool] = []
    for r in records:
        if r.get("category") != _CLAIM_CATEGORY:
            continue
        expected_complete = "missing_fields" not in (r.get("edge_flags") or [])
        dp = doc_by_id.get(r["doc_id"])
        predicted_complete = dp is not None and set(EXPECTED_CLAIM_FIELDS).issubset(
            set(dp.present_fields)
        )
        ext_pred.append(predicted_complete)
        ext_gold.append(expected_complete)
    report.extraction_accuracy = accuracy(ext_pred, ext_gold) if ext_gold else 0.0

    # --- Retrieval spot-check ----------------------------------------------
    if predictions.retrieval:
        rels = [set(rp.relevant) for rp in predictions.retrieval]
        retr = [rp.retrieved for rp in predictions.retrieval]
        report.retrieval_relevance_at_k = sum(
            relevance_at_k(r, rel, RETRIEVAL_SPOTCHECK_K) for r, rel in zip(retr, rels, strict=True)
        ) / len(retr)
        report.retrieval_mrr = mean_reciprocal_rank(retr, rels)
    else:
        report.notes.append("no retrieval spot-check in capture (retrieval scored 0)")

    # --- Per-case: KYC flags, fraud, decision -------------------------------
    cases = group_cases(records)
    kyc_pred: list[bool] = []
    kyc_gold: list[bool] = []
    fraud_pred: list[bool] = []
    fraud_gold: list[bool] = []
    dec_pred: list[Decision] = []
    dec_gold: list[Decision] = []
    for key, recs in cases.items():
        cp = case_by_id.get(key)
        # KYC: one binary point per (case, flag-type)
        gold_flags = {f for rec in recs for f in (rec.get("edge_flags") or [])}
        pred_flags = set(cp.kyc_flags) if cp else set()
        for flag in KYC_FLAG_UNIVERSE:
            kyc_gold.append(flag in gold_flags)
            kyc_pred.append(flag in pred_flags)
        # Fraud
        fraud_gold.append(any(rec.get("fraud_label") for rec in recs))
        fraud_pred.append(cp is not None and cp.fraud_score >= FRAUD_POSITIVE_THRESHOLD)
        # Decision (the 25% gate)
        dec_gold.append(derive_case_decision(recs))
        dec_pred.append(cp.decision if cp else Decision.ESCALATE)

    report.kyc = precision_recall_f1(kyc_pred, kyc_gold)
    report.fraud = precision_recall_f1(fraud_pred, fraud_gold)
    report.decision_accuracy = accuracy(dec_pred, dec_gold)
    missing_cases = sum(1 for key in cases if key not in case_by_id)
    if missing_cases:
        report.notes.append(f"{missing_cases} case(s) had no prediction (scored as ESCALATE)")

    report.captured_cases = len(predictions.cases)
    report.skipped_cases = len(predictions.skipped)
    if report.captured_cases == 0:
        report.notes.append(
            "no cases captured — the run produced zero predictions "
            "(check LLM gateway / rate limits); scores are not meaningful"
        )
    elif report.skipped_cases:
        report.notes.append(
            f"{report.skipped_cases} case-bundle(s) skipped mid-run (e.g. rate limit / LLM error)"
        )

    # --- Rubric-weighted grade (renormalised over auto-scored tracks) -------
    stage_scores = {
        "classification": report.classification_accuracy,
        "extraction": report.extraction_accuracy,
        "retrieval": report.retrieval_relevance_at_k,
        "decision": report.decision_accuracy,
    }
    total_w = sum(GRADE_WEIGHTS.values())
    report.weighted_grade = sum(GRADE_WEIGHTS[k] * v for k, v in stage_scores.items()) / total_w
    return report


# --------------------------------------------------------------------------- #
# Reporting / CLI
# --------------------------------------------------------------------------- #
def _fmt_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def format_report(report: EvalReport) -> str:
    lines = ["", "PolicyFlow AI — Per-stage Eval", "=" * 40]
    lines.append(f"Classification accuracy   {_fmt_pct(report.classification_accuracy)}")
    lines.append(f"Extraction completeness   {_fmt_pct(report.extraction_accuracy)}")
    lines.append(
        f"Retrieval relevance@{RETRIEVAL_SPOTCHECK_K}     "
        f"{_fmt_pct(report.retrieval_relevance_at_k)}  (MRR {report.retrieval_mrr:.2f})"
    )
    if report.kyc:
        lines.append(
            f"KYC flags  P/R/F1          "
            f"{report.kyc.precision:.2f}/{report.kyc.recall:.2f}/{report.kyc.f1:.2f}"
        )
    if report.fraud:
        lines.append(
            f"Fraud      P/R/F1          "
            f"{report.fraud.precision:.2f}/{report.fraud.recall:.2f}/{report.fraud.f1:.2f}"
        )
    lines.append(f"Decision correctness      {_fmt_pct(report.decision_accuracy)}  (gate ≥60%)")
    lines.append("-" * 40)
    lines.append(f"Weighted grade            {_fmt_pct(report.weighted_grade)}  (gate ≥70%)")
    dec = "PASS" if report.decision_gate_passed else "FAIL"
    ovr = "PASS" if report.overall_gate_passed else "FAIL"
    lines.append(f"Decision gate: {dec}   Overall gate: {ovr}")
    lines.append(f"Captured cases: {report.captured_cases}   Skipped: {report.skipped_cases}")
    for note in report.notes:
        lines.append(f"  · {note}")
    lines.append("")
    return "\n".join(lines)


def _default_predictions_path() -> Path:
    # dataset/ sits at repo root, two levels up from backend/eval/.
    return Path(__file__).resolve().parents[2] / "dataset" / "predictions.json"


def capture_path() -> Path:
    """Writable location for the live-run predictions capture.

    Honors `settings.eval_capture_path` (set in containers where dataset/ is
    read-only); falls back to the repo dataset/ for host/offline use.
    """
    from app.core.config import settings

    return Path(settings.eval_capture_path) if settings.eval_capture_path else (
        _default_predictions_path()
    )


def _default_metadata_path() -> Path:
    return Path(__file__).resolve().parents[2] / "dataset" / "metadata.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PolicyFlow per-stage eval")
    parser.add_argument("--from", dest="from_path", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--live", action="store_true", help="run the graph, then score")
    args = parser.parse_args(argv)

    import json

    metadata_path = args.metadata or _default_metadata_path()
    records = json.loads(metadata_path.read_text())
    predictions_path = args.from_path or _default_predictions_path()

    if args.live:
        import asyncio

        from eval.collect import collect_live  # lazy: heavy infra imports

        predictions = asyncio.run(collect_live(records))
        predictions.save(predictions_path)
        print(f"wrote predictions → {predictions_path}")
    else:
        if not predictions_path.exists():
            print(
                f"no predictions at {predictions_path}; run `python -m eval.run_eval --live` "
                "against the live stack to generate one.",
                file=sys.stderr,
            )
            return 2
        predictions = PredictionSet.load(predictions_path)

    report = score(predictions, records)
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

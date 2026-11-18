"""Eval-harness config — single source for grade weights & thresholds.

EVAL_PLAN.md mandates thresholds live in shared config, not scattered. App
*runtime* thresholds stay in `app.core.constants`; this module holds only the
*grading* rubric (PRD §6.1) and per-stage targets (PRD §6.2). The fraud
decision boundary is imported from the app so eval and runtime never drift.
"""

from __future__ import annotations

from app.core.constants import FRAUD_ESCALATE_THRESHOLD
from app.schemas.enums import DocumentType

# --- dataset category → predicted DocumentType (classification ground truth) --
CATEGORY_TO_TYPE: dict[str, DocumentType] = {
    "claim_forms": DocumentType.CLAIM_FORM,
    "id_documents": DocumentType.ID_DOCUMENT,
    "discharge_summaries": DocumentType.DISCHARGE_SUMMARY,
    "prescriptions": DocumentType.PRESCRIPTION,
    "policy_amendments": DocumentType.POLICY_AMENDMENT,
    "unknown": DocumentType.UNKNOWN,
}

# --- rubric weights that the harness can auto-score (PRD §6.1) ---------------
# UI (10%) and Code quality (10%) are graded manually and excluded from the
# automated weighted grade; the overall gate renormalizes over these four.
GRADE_WEIGHTS: dict[str, float] = {
    "classification": 0.20,
    "extraction": 0.20,
    "retrieval": 0.15,
    "decision": 0.25,
}

# --- per-stage targets (PRD §6.2 / EVAL_PLAN §3) -----------------------------
CLASSIFICATION_TARGET: float = 0.90
EXTRACTION_TARGET: float = 0.85
RETRIEVAL_TARGET: float = 0.60  # mean relevance@3 spot-check pass line
KYC_PR_TARGET: float = 0.80
FRAUD_F1_TARGET: float = 0.60

# --- hard gates --------------------------------------------------------------
DECISION_GATE: float = 0.60  # PRD §6.1 — Decision Correctness ≥ 60% (hard)
OVERALL_GATE: float = 0.70  # weighted sum ≥ 70%

# --- fraud: predicted-positive boundary (reuse runtime constant) -------------
FRAUD_POSITIVE_THRESHOLD: float = FRAUD_ESCALATE_THRESHOLD

# --- fields a complete claim form must carry (extraction completeness proxy) --
EXPECTED_CLAIM_FIELDS: tuple[str, ...] = (
    "icd_codes",
    "cpt_codes",
    "provider_npi",
    "claim_amount",
    "service_date",
)

# --- KYC flag universe scored vs metadata edge_flags -------------------------
KYC_FLAG_UNIVERSE: tuple[str, ...] = (
    "expired_id",
    "expiring_soon_id",
    "tampered_id",
    "name_mismatch",
)
RETRIEVAL_SPOTCHECK_K: int = 3

# --- retrieval spot-check probes (GOLDEN_SET §"Retrieval spot-check") --------
# 5 known CPT codes → the plan whose clauses should dominate the top-k. Relevance
# is scored as a plan-match proxy at capture time (see eval/collect.py). Tune the
# expected plan to the ingested policy PDFs. plan ∈ {"GOLD","SILVER"}.
RETRIEVAL_PROBES: tuple[tuple[str, str], ...] = (
    ("59400", "GOLD"),  # routine obstetric care
    ("99213", "GOLD"),  # office/outpatient visit
    ("70450", "SILVER"),  # CT head/brain
    ("29881", "SILVER"),  # knee arthroscopy
    ("80053", "GOLD"),  # comprehensive metabolic panel
)

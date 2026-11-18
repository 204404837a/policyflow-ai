"""The decision oracle — derives the *expected* decision from dataset metadata.

`metadata.json` carries an explicit `expected_decision` only for UNKNOWN docs;
for everything else we derive it from `fraud_label` + `edge_flags` + `blur_simulated`
(PRD §6.3). Precedence mirrors the Orchestrator: REJECT > ESCALATE > APPROVE.

This function defines "correct" for the 25%-weighted Decision Correctness metric,
so it is deliberately small, explicit, and unit-tested.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.enums import Decision

# Case-fold severity: a bundle inherits its most severe member decision.
# Mirrors the Orchestrator precedence REJECT > ESCALATE > APPROVE.
_SEVERITY: dict[Decision, int] = {
    Decision.APPROVE: 0,
    Decision.ESCALATE: 1,
    Decision.REJECT: 2,
}

# Edge flags that make a claim invalid/uncovered → REJECT.
REJECT_FLAGS: frozenset[str] = frozenset(
    {"uncovered_procedure", "expired_id", "missing_fields", "tampered_id"}
)
# Edge flags that only lower confidence (not hard failures) → ESCALATE.
ESCALATE_FLAGS: frozenset[str] = frozenset({"expiring_soon_id"})


def derive_decision(record: dict) -> Decision:
    """Expected decision for a single metadata record."""
    # 1. UNKNOWN / OOD docs carry an explicit label.
    explicit = record.get("expected_decision")
    if explicit:
        return Decision(explicit)

    flags = set(record.get("edge_flags") or [])

    # 2. Fraud always escalates for human review.
    if record.get("fraud_label"):
        return Decision.ESCALATE

    # 3. Hard failures → REJECT (checked before soft signals).
    if flags & REJECT_FLAGS:
        return Decision.REJECT

    # 4. Low-confidence signals → ESCALATE.
    if (flags & ESCALATE_FLAGS) or record.get("blur_simulated"):
        return Decision.ESCALATE

    # 5. Clean → APPROVE.
    return Decision.APPROVE


def derive_case_decision(records: Iterable[dict]) -> Decision:
    """Expected decision for a *case* (patient-episode bundle).

    A case is graded, not individual docs (the pipeline decides per case). The
    bundle inherits its most severe member decision — one expired ID or fraud
    signal condemns the whole case — matching the Orchestrator's fail-closed
    precedence. Empty bundles cannot be approved on no evidence → ESCALATE.
    """
    decisions = [derive_decision(r) for r in records]
    if not decisions:
        return Decision.ESCALATE
    return max(decisions, key=lambda d: _SEVERITY[d])

"""Orchestrator — the weighted decision rule (pure function, not an LLM).

APPROVE  ⇔ kyc_passed ∧ schema_valid ∧ covered ∧ fraud_score < 0.3
REJECT   ⇔ ¬kyc_passed ∨ ¬covered ∨ ¬schema_valid
ESCALATE ⇔ fraud_score ≥ 0.3 ∨ min(agent confidence) < 0.6

REJECT conditions are evaluated first; then ESCALATE; else APPROVE. Boundary
behaviour (fraud=0.3, conf=0.6) is pinned by a truth-table test.
"""

from __future__ import annotations

from app.core.constants import FRAUD_ESCALATE_THRESHOLD, MIN_AGENT_CONFIDENCE
from app.schemas.agents import (
    ClaimsOutput,
    FraudOutput,
    KYCOutput,
    OrchestratorOutput,
    PolicyOutput,
)
from app.schemas.enums import Decision

_REJECT_CONFIDENCE = 0.85
_ESCALATE_CONFIDENCE = 0.7


def _summaries(
    kyc: KYCOutput, claims: ClaimsOutput, policy: PolicyOutput, fraud: FraudOutput
) -> dict[str, dict]:
    return {
        "kyc": kyc.model_dump(),
        "claims": claims.model_dump(),
        "policy": policy.model_dump(),
        "fraud": fraud.model_dump(),
    }


def make_decision(
    kyc: KYCOutput,
    claims: ClaimsOutput,
    policy: PolicyOutput,
    fraud: FraudOutput,
) -> OrchestratorOutput:
    summaries = _summaries(kyc, claims, policy, fraud)

    # --- REJECT (checked first) ---
    reasons: list[str] = []
    if not kyc.kyc_passed:
        reasons.append(f"KYC failed: {kyc.flags}")
    if not claims.schema_valid:
        reasons.append(f"claim schema invalid: {claims.validation_errors}")
    if not policy.covered:
        reasons.append(f"procedure not covered; exclusions: {policy.exclusions}")
    if reasons:
        return OrchestratorOutput(
            decision=Decision.REJECT,
            confidence=_REJECT_CONFIDENCE,
            justification="; ".join(reasons),
            agent_summaries=summaries,
        )

    # --- ESCALATE ---
    escalate: list[str] = []
    if fraud.fraud_score >= FRAUD_ESCALATE_THRESHOLD:
        escalate.append(f"fraud_score={fraud.fraud_score:.2f} ({fraud.anomalies})")
    low_conf = {
        name: agent.confidence
        for name, agent in (("KYC", kyc), ("Claims", claims), ("Policy", policy), ("Fraud", fraud))
        if agent.confidence < MIN_AGENT_CONFIDENCE
    }
    if low_conf:
        escalate.append(f"low confidence: {low_conf}")
    if escalate:
        return OrchestratorOutput(
            decision=Decision.ESCALATE,
            confidence=_ESCALATE_CONFIDENCE,
            justification="; ".join(escalate),
            agent_summaries=summaries,
        )

    # --- APPROVE ---
    return OrchestratorOutput(
        decision=Decision.APPROVE,
        confidence=min(kyc.confidence, claims.confidence, policy.confidence),
        justification="KYC passed, claim valid, procedure covered, low fraud risk.",
        agent_summaries=summaries,
    )

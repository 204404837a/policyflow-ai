# GUARDRAILS.md — Must-Never-Do & Mandatory Behaviors

Turns the PRD's behavioral boundaries into hard, testable rules. Enforced summary: `.claude/rules/claims-safety.md`. Fail-closed by default: **when unsure, ESCALATE**.

## Must NEVER
| # | Boundary | Test |
|---|---|---|
| G1 | Never auto-APPROVE when `fraud_score ≥ 0.3` or any agent `confidence < 0.6`. | Orchestrator truth-table unit test at the 0.3/0.6 boundaries. |
| G2 | Never finalize an ESCALATED case without a human override. | Only the override handler transitions ESCALATED→final; grep confirms. |
| G3 | Never mark coverage `covered=true` without a cited retrieved clause. | `PolicyOutput.covered ⇒ policy_clause not empty` assertion. |
| G4 | Never APPROVE when KYC fails (`member_found=false`/`id_expired`/`tamper_suspected`). | KYC-gate unit test. |
| G5 | Never fabricate extracted values; illegible ⇒ error/low-confidence. | Golden cases with blurry/missing-field docs expect REJECT/ESCALATE. |
| G6 | Never exceed 3 self-correction retries. | Bounded-retry test. |
| G7 | Never expose or log raw PII (see [DATA_HANDLING.md](./DATA_HANDLING.md)). | Redaction test. |
| G8 | Never call a model provider directly (only via LiteLLM aliases). | Import-scan test. |

## Must ALWAYS
- Persist `decision, confidence, justification, agent_summaries` + an `audit_events` row for every case and every agent step.
- Record all fraud anomalies even when the final decision differs.
- Audit human overrides (actor, original→new decision, reason, ts) and lock the case (append ⇒ `409`).
- Treat the derived label map ([PRD.md §6.3](./PRD.md)) as the decision-correctness oracle; gate ≥ **60%**.

## Disclaimers (UI)
Decisions are **AI-assisted, human-reviewable**. Escalated and low-confidence cases require ops review before any reimbursement action. The UI must show the confidence and justification alongside every automated decision.

Source boundaries: [PRD.md](./PRD.md) (NFRs, scope), [LLD.md](./LLD.md) (state machine, error/fallback).

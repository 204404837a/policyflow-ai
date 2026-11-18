# PROMPTS.md — Versioned Agent Prompts

Per-component prompt templates, versioned. Prompts live in code at `backend/app/llm/prompts/`; this doc is the design registry. Each targets a **LiteLLM alias** and returns a **Pydantic model** ([LLD.md §3](./LLD.md)). Structured output is enforced via the model schema, not prose.

> **Rules:** no PII in system prompts beyond the document under review; never instruct the model to *decide* eligibility on its own where a rule exists (the Orchestrator rule is code, not a prompt). Keep prompts declarative; put thresholds in code. Version on any change (`v1`, `v2`, …) and note it in the phase journal.

| Component | Alias | Version | Intent | Returns |
|---|---|---|---|---|
| **Classifier** | `vision` | v1 | Identify document type from the image; abstain (UNKNOWN) when unsure. | `ClassifierOutput` |
| **Preprocessor** | `vision` | v1 | Extract type-specific fields + raw_text + boxes into a normalized shape. | `DocumentContent` |
| **KYC** | `reasoning` | v1 | Compare extracted identity to the member record; list discrepancies/flags. | `KYCOutput` |
| **Claims** | `reasoning` | v1 | Extract ICD-10/CPT/NPI/amount/date; report schema validation errors. | `ClaimsOutput` |
| **Policy-RAG** | `reasoning` | v1 | Given retrieved clauses + procedure codes, judge coverage and cite the clause. | `PolicyOutput` |
| **Fraud** | `reasoning` | v1 | Given claim + history + sibling docs, enumerate anomalies and score risk. | `FraudOutput` |
| **Orchestrator justification** | `reasoning` | v1 | *Explain* the rule-decided outcome in plain language (decision itself is code). | text → `justification` |

## Template anatomy (every prompt)
1. **Role + task** (one sentence).
2. **Inputs** (the document/`DocumentContent`/retrieved clauses — no extra PII).
3. **Output contract** — "return JSON matching this schema" (schema injected from the Pydantic model).
4. **Abstention/uncertainty rule** — when unsure, lower confidence / add to `validation_errors` / choose UNKNOWN; **never fabricate** (`claims-safety.md`).

## Guardrails inside prompts
- Classifier & Preprocessor: "If the image is illegible or not one of the known types, set low confidence / UNKNOWN — do not guess."
- Policy-RAG: "Only mark covered if a retrieved clause supports it; cite `policy_section`."
- Fraud: "Report every anomaly you see, even minor; do not infer intent."

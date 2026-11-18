# EVAL_PLAN.md — Quality Tracks & Thresholds

Four tracks (all in scope). Thresholds live in **shared config** (`eval/config` / `core/constants`), not scattered. Ground truth: `dataset/metadata.json` + derived label map ([PRD.md §6.3](./PRD.md)). Grading rubric: [PRD.md §6.1](./PRD.md).

## Track order in CI (fail-closed)
1. **Security red-team** — runs **first**, fails the build fast ([SECURITY_REDTEAM.md](./SECURITY_REDTEAM.md)).
2. **Unit** → 3. **Integration** → 4. **Eval (metric-based)**.

## 1. Unit
Per-agent with **mocked LiteLLM**; orchestrator **truth-table** at boundaries (`fraud=0.3`, `conf=0.6`); bounded-retry cap; redaction/masking; PolicyOutput covered⇒clause invariant. Tool: `pytest`. Gate: all pass, `ruff`+`mypy` clean.

## 2. Integration
`docker compose up` → `alembic upgrade head` → ingest both policy PDFs → push a dataset subset through `POST /api/cases` → assert persisted `agent_outputs`, audit rows, WebSocket status, and override→resume flow. Gate: E2E green on a fresh stack.

## 3. Eval (metric-based) — per stage vs ground truth
| Stage | Metric | Threshold (rubric weight) |
|---|---|---|
| Classification | accuracy | ≥ 90% (20%) |
| Extraction | field completeness/accuracy | ≥ 85% (20%) |
| Retrieval | relevance@k / MRR | spot-check pass (15%) |
| KYC flags | precision/recall vs `edge_flags` | report + ≥0.8 P/R target |
| Fraud | precision/recall/F1 vs `fraud_label` | report + F1 target |
| **Decision** | accuracy vs label map | **≥ 60% (hard gate, 25%)** |
| Calibration | reliability curve / ECE | report (bonus) |
Runner: `eval/run_eval.py` → weighted grade; **asserts Decision Correctness ≥ 60%** and overall ≥ 70%. Cases from [GOLDEN_SET.md](./GOLDEN_SET.md).

### 3a. Live runs from the Admin dashboard
The offline runner (`run_eval.py`) is the source of truth; the Admin **Evaluation** dashboard drives the same scorer live over the dataset (`POST /api/eval/run` → worker → capture at `EVAL_CAPTURE_PATH`, polled via `/api/eval/jobs/{id}`). Two run **groups** reflect the graph's coupling:
- **pipeline** — classification/extraction/decision/KYC/fraud come from one graph pass, so they run together (`limit` samples N case-bundles).
- **retrieval** — the standalone RAG spot-check (no vision calls); cheap, safe to run on its own.

Operational guarantees: one run at a time (`/api/eval/run` → **409** if another is in flight; `EvalRunRegistry` in Redis), refresh-safe (`/api/eval/status` lets a reloaded page resume polling), and honest empties — a run whose cases all fail (e.g. 429-skipped) reports `captured_cases=0`/`skipped_cases` and scores 0 rather than a phantom pass. Batch runs are throttled (`LLM_MIN_INTERVAL_S`) to respect free-tier tokens/min; see [DEPLOY.md](./DEPLOY.md).

## 4. Security red-team
Adversarial matrix in [SECURITY_REDTEAM.md](./SECURITY_REDTEAM.md): prompt-injection via document content, override authz/state, file-upload abuse, PII leakage. Gate: zero criticals; runs first.

## Mapping to NFRs (PRD §4)
Latency P95<120s → integration timing report · zero hardcoded secrets → secret-scan (red-team) · provider-agnostic → import-scan · bounded autonomy → retry test · PII → redaction test.

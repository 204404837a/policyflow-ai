# PolicyFlow AI — Low-Level Design (LLD)
### Contracts · Schemas · APIs · Repo Structure
**Status:** Approved-for-build · **Last updated:** 2026-08-02 · Prev: [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md)

---

## 1. Repository Structure

```
policyflow-ai/
├── docker-compose.yml            # api, worker, litellm, postgres, qdrant, minio, redis, frontend
├── .env.example
├── litellm-config.yaml           # model_list: vision/reasoning/embeddings + router/fallbacks/cache
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                  # migrations
│   └── app/
│       ├── main.py               # FastAPI factory, middleware, CORS, routers
│       ├── core/
│       │   ├── config.py         # pydantic-settings (all env)
│       │   ├── logging.py        # structured JSON logger
│       │   └── security.py       # magic-byte validation, file-size guard, PII mask
│       ├── db/
│       │   ├── models.py         # SQLAlchemy ORM (cases, documents, members, claim_history, agent_outputs, llm_calls, audit_events)
│       │   ├── session.py        # async engine + session factory
│       │   └── seed.py           # members + claim_history from dataset/members.json
│       ├── schemas/              # Pydantic v2 contracts (§3)
│       │   ├── enums.py
│       │   ├── documents.py      # DocumentContent
│       │   ├── agents.py         # *Output models
│       │   └── api.py            # request/response models
│       ├── llm/
│       │   ├── client.py         # LiteLLM wrapper: acompletion(alias=...), aembed(); tenacity retry + circuit breaker
│       │   └── prompts/          # per-agent prompt templates
│       ├── ingestion/
│       │   ├── storage.py        # MinIO client (put/get/presign)
│       │   ├── docling_loader.py # DocumentConverter + HybridChunker + TableFormer
│       │   ├── vision_extract.py # image → DocumentContent (vision alias)
│       │   └── ocr.py            # Tesseract fallback
│       ├── agents/
│       │   ├── state.py          # PipelineState TypedDict (+ reducers)
│       │   ├── graph.py          # StateGraph wiring, conditional edges, checkpointer
│       │   ├── classifier.py
│       │   ├── preprocessor.py
│       │   ├── kyc.py            # + ELA tamper (bonus)
│       │   ├── claims.py
│       │   ├── policy_rag.py
│       │   ├── fraud.py
│       │   └── orchestrator.py   # pure decision rule
│       ├── services/
│       │   ├── rag_service.py    # Qdrant ingest + hybrid retrieve + rerank
│       │   ├── member_service.py # member lookup for KYC
│       │   ├── fraud_service.py  # claim_history queries + statistical baselines
│       │   └── report_service.py # PDF case report (bonus)
│       ├── api/
│       │   ├── auth.py           # POST /api/auth/login, GET /api/auth/me
│       │   ├── deps.py           # get_current_user, require_role(*roles) — RBAC gates
│       │   ├── admin.py          # /api/admin/{users,members(+bulk)}, DELETE /api/cases, /api/eval/{metrics,status,run,jobs} (ADMIN)
│       │   ├── upload.py         # POST /api/cases (EMPLOYER; 1..N files), POST /api/cases/{id}/documents (append)
│       │   ├── cases.py          # GET /api/cases (scoped + ?q= search), /api/cases/{id}
│       │   ├── review.py         # POST /api/cases/{id}/override (REVIEWER)
│       │   ├── policies.py       # POST /api/policies/ingest (ADMIN)
│       │   ├── files.py          # GET /api/files/{key}
│       │   └── websocket.py      # WS /ws/cases/{id}
│       └── worker/
│           ├── celery_app.py
│           └── tasks.py          # run_pipeline(case_id) · run_eval(limit) · run_retrieval_eval() -> graph/scoring
│       # services/eval_registry.py — Redis-backed active-run registry (one live eval at a time)
├── eval/
│   ├── label_map.py              # derived decision oracle (fraud_label + edge_flags)
│   ├── run_eval.py               # offline + --live scoring vs metadata.json (captured/skipped aware)
│   ├── collect.py                # live collectors: collect_live (full graph) · collect_retrieval_only
│   ├── predictions.py            # PredictionSet capture (documents/cases/retrieval/skipped)
│   ├── metrics.py                # accuracy, P/R/F1, relevance@k, ECE
│   └── calibration.py            # reliability curve (bonus)
├── frontend/                     # Next.js (App Router) — dashboard, case detail, review, audit, WS
├── scripts/                      # EXISTING generators (run, do not rewrite) + members.json export
├── dataset/                      # generated output
└── docs/                         # PRD, HLD, DATABASE_SCHEMA, LLD, task
```

---

## 2. LiteLLM Client & Config

`litellm-config.yaml` (proxy):
```yaml
model_list:
  - model_name: vision
    # qwen3.6-27b is the multimodal model currently on the account; reasoning_effort:none
    # sends the token budget to the structured output (and cuts free-tier TPM pressure).
    litellm_params: { model: groq/qwen/qwen3.6-27b, api_key: os.environ/GROQ_API_KEY, extra_body: { reasoning_effort: none } }
  - model_name: reasoning
    litellm_params: { model: groq/llama-3.3-70b-versatile, api_key: os.environ/GROQ_API_KEY }
  - model_name: embeddings
    litellm_params: { model: huggingface/BAAI/bge-large-en-v1.5, api_key: os.environ/HUGGINGFACE_API_KEY, api_base: https://router.huggingface.co/hf-inference/models/BAAI/bge-large-en-v1.5/pipeline/feature-extraction }
router_settings: { num_retries: 3, timeout: 90, fallbacks: [{ vision: ["reasoning"] }] }
litellm_settings: { cache: true, success_callback: ["langsmith"], turn_off_message_logging: true }
```
`llm/client.py` exposes `await chat(alias, messages, image=None, response_model=None)` and `await embed(texts)`, wrapped in tenacity (exp backoff + jitter) and a circuit breaker; every call writes an `llm_calls` row. Resilience specifics (all env-tuned, single-source in `core/constants`):
- **Process-wide pacer** — `_throttle()` serializes call *starts* and spaces them by `LLM_MIN_INTERVAL_S` so the graph's parallel fan-out stays under the free-tier tokens/min limit (batch eval runs the worker at a higher interval; see [DEPLOY.md](./DEPLOY.md)).
- **Rate-limit aware** — a `429` raises a typed `LLMUnavailableError` that carries the provider's rate-limit **detail** (which limit: requests/min vs tokens/min vs daily) and any `Retry-After`; the client honors `Retry-After` (capped at `LLM_RETRY_MAX_S`, so a daily-cap 429 fails fast instead of parking the worker) and logs the detail rather than an opaque failure.
- **Retryable set** — `{408,409,429,500,502,503,504}` retried up to `LLM_MAX_ATTEMPTS`; other `4xx` surface immediately.

---

## 3. Pydantic v2 Contracts

```python
# enums.py
class DocumentType(str, Enum):
    CLAIM_FORM="CLAIM_FORM"; ID_DOCUMENT="ID_DOCUMENT"; DISCHARGE_SUMMARY="DISCHARGE_SUMMARY"
    PRESCRIPTION="PRESCRIPTION"; POLICY_AMENDMENT="POLICY_AMENDMENT"; UNKNOWN="UNKNOWN"
class Decision(str, Enum): APPROVE="APPROVE"; REJECT="REJECT"; ESCALATE="ESCALATE"
class RiskLevel(str, Enum): LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"

# documents.py
class BoundingBox(BaseModel): field: str; text: str; x: int; y: int; w: int; h: int
class DocumentContent(BaseModel):
    raw_text: str
    fields: dict[str, str | float | None] = {}
    bounding_boxes: list[BoundingBox] = []
    tables: list[list[list[str]]] = []
    source_type: str                      # image|pdf
    parser_used: str                      # DOCLING|VISION_LLM|TESSERACT
    ingest_confidence: float

# agents.py
class ClassifierOutput(BaseModel):
    doc_type: DocumentType; confidence: float; routing_tags: list[str]
class KYCOutput(BaseModel):
    kyc_passed: bool; member_found: bool; member_id: str | None = None
    id_valid: bool; id_expired: bool; tamper_suspected: bool = False
    flags: list[str] = []; confidence: float
class ClaimsExtractedFields(BaseModel):
    patient_name: str | None=None; member_id: str | None=None; claim_amount: float | None=None
    icd_codes: list[str]=[]; cpt_codes: list[str]=[]; provider_npi: str | None=None
    service_date: str | None=None; provider_name: str | None=None
class ClaimsOutput(BaseModel):
    extracted_fields: ClaimsExtractedFields; schema_valid: bool
    validation_errors: list[str]=[]; confidence: float
class PolicyOutput(BaseModel):
    covered: bool; coverage_percentage: float | None=None
    policy_clause: str | None=None; policy_section: str | None=None
    exclusions: list[str]=[]; confidence: float
class FraudOutput(BaseModel):
    fraud_score: float; anomalies: list[str]=[]; risk_level: RiskLevel
    claim_history_count: int=0; confidence: float
class OrchestratorOutput(BaseModel):
    decision: Decision; confidence: float; justification: str
    agent_summaries: dict[str, dict]
```

---

## 4. LangGraph State & Reducers

```python
import operator
from typing import Annotated, TypedDict, Optional

class PipelineState(TypedDict):
    case_id: str
    documents: list[dict]                 # per-doc: {doc_id, storage_key, mime, doc_type?, content?}
    # parallel fan-in accumulation
    agent_outputs: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]
    # per-agent results (case-level after aggregation)
    kyc_result: Optional[dict]
    claims_result: Optional[dict]
    policy_result: Optional[dict]
    fraud_result: Optional[dict]
    decision: Optional[str]
    decision_confidence: Optional[float]
    decision_justification: Optional[str]
    agent_summaries: Optional[dict]
    retry_count: int                      # bounded retry (<=3)
    current_stage: str
```
`graph.py`: conditional edge after `classifier` (`UNKNOWN`/conf<0.6 → human queue else preprocess); fan-out `preprocess → {kyc, claims, policy}`; fan-in `→ fraud → orchestrator`. Compiled with a **Postgres checkpointer**, `recursion_limit` bounding retries; `interrupt_before=["human_override"]` for HITL.

---

## 5. Orchestrator Decision (pure rule)

```python
def make_decision(kyc, claims, policy, fraud) -> OrchestratorOutput:
    reasons = []
    if not kyc.kyc_passed:      reasons.append(f"KYC failed: {kyc.flags}")
    if not claims.schema_valid: reasons.append(f"Schema invalid: {claims.validation_errors}")
    if not policy.covered:      reasons.append(f"Not covered; exclusions: {policy.exclusions}")
    if reasons:
        return OrchestratorOutput(decision=Decision.REJECT, confidence=0.85,
                                  justification="; ".join(reasons), agent_summaries=_summ(...))
    esc = []
    if fraud.fraud_score >= 0.3: esc.append(f"fraud_score={fraud.fraud_score:.2f}")
    for name, a in [("KYC",kyc),("Claims",claims),("Policy",policy),("Fraud",fraud)]:
        if a.confidence < 0.6:   esc.append(f"{name} low confidence={a.confidence:.2f}")
    if esc:
        return OrchestratorOutput(decision=Decision.ESCALATE, confidence=0.7,
                                  justification="; ".join(esc), agent_summaries=_summ(...))
    return OrchestratorOutput(decision=Decision.APPROVE,
                              confidence=min(kyc.confidence, claims.confidence, policy.confidence),
                              justification="KYC passed, claim valid, covered, low fraud risk.",
                              agent_summaries=_summ(...))
```
Boundary behavior (`fraud=0.3`, `conf=0.6`) is pinned by a truth-table unit test.

---

## 6. API Contracts

All routes except `/api/auth/login` require a `Authorization: Bearer <jwt>` header. The **Role** column is the `require_role` gate; ✱ = ownership-scoped (employers see only `submitted_by = me`).

| Method | Path | Role | Request | Response |
|---|---|---|---|---|
| POST | `/api/auth/login` | public | `{username, password}` | `200 {access_token, token_type, username, role}` (err 401) |
| GET | `/api/auth/me` | any | — | `200 {id, username, role, email, ...}` |
| POST | `/api/cases` | EMPLOYER | multipart: `files[]` — **1..N files** (one upload = one case); stamps `submitted_by` | `202 {case_id, status:"RECEIVED", documents:[...]}` |
| POST | `/api/cases/{id}/documents` | EMPLOYER✱ | multipart: `files[]` — append; re-runs Fraud + Orchestrator | `202 {case_id, added:[...], status:"PROCESSING"}` (409 if locked) |
| GET | `/api/cases` | any✱ | `?status=&q=&page=&limit=` (employer scoped; reviewer/admin all) | `200 {cases:[{case_id,status,decision,patient_name,submitted_by,...}], total, page, limit}` |
| GET | `/api/cases/{id}` | any✱ | — | `200 {case, documents[], agent_outputs[], audit_events[]}` (403 if not owner) |
| POST | `/api/cases/{id}/override` | REVIEWER | `{decision:"APPROVE\|REJECT", reason}` (reviewer id from token) | `200 {case_id, original_decision, override_decision, override_by, override_at}` (400 if not ESCALATED) |
| GET | `/api/cases/{id}/report` | any✱ | — | `200 application/pdf` |
| GET | `/api/files/{key}` | any | — | `200 image/*` inline, `nosniff` |
| POST | `/api/policies/ingest` | ADMIN | multipart: `file` (pdf), `plan:"GOLD\|SILVER"` | `200 {plan, chunks_created, collection}` |
| POST | `/api/admin/users` | ADMIN | `{username, password, role, email?, ...}` | `201 {id, username, role, ...}` (409 if exists) |
| GET | `/api/admin/users` | ADMIN | — | `200 {users:[...], total}` |
| POST | `/api/admin/members` | ADMIN | `MemberCreate` | `201 {member_id (full), name, policy_number, ...}` (409 if exists) |
| GET | `/api/admin/members` | ADMIN | `?page=&limit=` | `200 {members:[{member_id (masked), ...}], total}` |
| POST | `/api/admin/members/bulk` | ADMIN | `[MemberCreate, ...]` (upsert by member_id) | `200 {created, updated, errors[]}` |
| DELETE | `/api/cases` | ADMIN | — (reset submitted claims; keeps members/users/policy vectors) | `200 {cases, documents, files, checkpoints}` (deleted counts) |
| GET | `/api/eval/metrics` | ADMIN | — | `200 EvalMetrics` (scores last capture; 404 if none) |
| GET | `/api/eval/status` | ADMIN | — (is a run in flight? for resume-on-refresh) | `200 {running, task_id?, scope?, state?}` |
| POST | `/api/eval/run` | ADMIN | `{scope:"pipeline\|retrieval", limit?}` | `202 {task_id, scope, status}` (**409 if a run is already in flight**) |
| GET | `/api/eval/jobs/{task_id}` | ADMIN | — (poll a live run) | `200 {task_id, state, scope?, metrics?, error?}` |
| WS | `/ws/cases/{id}` | any | — | stream `{type:"agent_update"\|"decision", agent, status, confidence, ts}` |

Errors: `400` unsupported type / bad state · `401` missing/invalid token · `403` wrong role / not owner · `404` not found · `409` conflict (locked case / duplicate) · `413` >10MB.

---

## 7. Service Interfaces

```python
class RagService:
    async def ingest_policy(self, pdf_path: str, plan: str) -> int          # -> chunks upserted
    async def retrieve(self, cpt: list[str], icd: list[str], text: str, k: int=8) -> list[Clause]  # hybrid + rerank -> top-3

class UserService:                                                            # RBAC (Phase 9)
    async def authenticate(self, username: str, password: str) -> User | None  # bcrypt verify + ACTIVE check
    async def get_by_username(self, username: str) -> User | None
    async def create(self, *, username, password, role, email=None, ...) -> User  # 409 if exists / 400 bad role
    async def list_users(self) -> list[User]

class MemberService:
    async def lookup(self, member_id: str | None, policy_number: str | None, name: str | None) -> Member | None
    async def create(self, data: dict) -> Member                               # admin add (409 if exists)
    async def list_members(self, page: int, limit: int) -> tuple[list[Member], int]
    async def upsert_many(self, rows: list[dict]) -> tuple[int, int, list[str]] # bulk (created, updated, errors)

# core/auth.py: hash_password / verify_password (passlib bcrypt);
#   create_access_token(username, role) / decode_access_token (python-jose HS256, JWT_SECRET+JWT_EXPIRY_MIN from env)
# api/deps.py: get_current_user (decode Bearer → User) · require_role(*roles) (401/403 dependency factory)

class EvalRunRegistry:                                                          # Redis-backed (Phase 9d)
    async def set_active(self, task_id: str, scope: str) -> None                # record the single in-flight run (TTL self-heals)
    async def get_active(self) -> dict | None                                   # {task_id, scope} or None
    async def clear(self) -> None
    # One live run at a time: /run 409s while active; /status resumes a refreshed page;
    # is_active_state(celery_state) marks PENDING/RECEIVED/STARTED/RETRY as still running.

class FraudService:
    async def history(self, member_id: str) -> list[ClaimHistory]
    def score(self, claim: ClaimsExtractedFields, history: list, siblings: list[dict]) -> FraudOutput
    # signals: duplicate_claim, readmission_30d, date_conflict, proc_diag_mismatch, amount_under_10k (structuring), name_mismatch
```

---

## 8. Cross-cutting Patterns

- **Bounded retry (≤3):** Claims/Preprocessor re-attempt on `schema_valid=False`; increment `retry_count`; on exhaustion → escalate (never silent-fail).
- **HITL:** ESCALATE persists a checkpoint; `/override` resumes the graph thread; every step writes `audit_events`.
- **Resilience:** all LLM calls via `llm/client.py` (tenacity retry + circuit breaker); config from env only.
- **Security:** magic-byte validation, UUID/derived storage keys, parameterized ORM, PII masking in list views, scoped CORS, `nosniff` on file serving.
- **Observability:** JSON logs (`DEBUG..CRITICAL`); `llm_calls` per call; LangSmith traces per graph run.

---

## 9. Eval Harness (`eval/`)
- `label_map.py` — derived decision oracle (PRD §6.3).
- `metrics.py` — pure scoring primitives (accuracy, precision/recall/F1, relevance@k/MRR, ECE); stdlib-only, no LLM.
- `predictions.py` — `PredictionSet` capture (documents/cases/retrieval + **`skipped`** case ids), save/load JSON.
- `collect.py` — **live collector**: `collect_live(records)` drives the real graph over each case bundle (per-case try/except → skipped, not fatal); `collect_retrieval_only()` runs just the cheap RAG spot-check (no vision calls).
- `run_eval.py` — loads `metadata.json`; **offline** scores a capture, or **`--live`** runs the graph then scores. `restrict_to_captured` grades only what actually ran (empty when nothing captured → no phantom score); report carries `captured_cases`/`skipped_cases`; asserts **Decision Correctness ≥60%** and overall ≥70%.
- `calibration.py` — reliability curve + ECE (bonus).

**Live runs from the Admin UI** (`/api/eval/*`, worker tasks `run_eval` / `run_retrieval_eval`) share one capture at `EVAL_CAPTURE_PATH` (a volume shared by api+worker). Two **groups** map to the graph's coupling: *pipeline* (classification/extraction/decision/kyc/fraud — one graph pass) and *retrieval* (standalone). `EvalRunRegistry` enforces one run at a time and lets a refreshed page resume; `EvalMetrics` surfaces `captured_cases`/`skipped_cases` so a 0-capture (all-429) run reads as broken, not as a passing empty board.

---

## 10. Bonus Hooks (multi-language deferred)
| Bonus | Where |
|---|---|
| Confidence calibration | `eval/calibration.py` |
| WebSocket streaming | `api/websocket.py` + LangGraph `astream_events` |
| ELA tamper detection | `agents/kyc.py` (Pillow error-level analysis; validate vs 3 tampered IDs) |
| PDF audit export | `services/report_service.py` + `GET /cases/{id}/report` |
| LangSmith tracing | env `LANGCHAIN_TRACING_V2=true` + LiteLLM `success_callback` |

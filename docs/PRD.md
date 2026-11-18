# PolicyFlow AI — Product Requirements Document (PRD)
### PolicyFlow Demo Multi-Agent Document Intake Platform
**Status:** Approved-for-build · **Owner:** ML/Platform Eng · **Last updated:** 2026-08-02

> Doc set: **PRD** (this) → [HLD.md](./HLD.md) → [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) → [LLD.md](./LLD.md). Task tracker: [task.md](./task.md).

---

## 1. Vision & Value Proposition

PolicyFlow Demo's 120-person review team processes ~85,000 monthly document submissions at **$18.4M/yr**, a **4.2-day** average cycle time, a **12% re-processing rate**, and **3 active KYC regulatory audits**. Manual classification is the bottleneck: slow, error-prone, non-auditable.

**PolicyFlow AI** automates classification → extraction → verification → coverage → fraud → decision with a multi-agent pipeline that issues **Approve / Reject / Escalate** in minutes, with a full per-agent evidence trail for compliance.

**Targeted outcomes:** cycle time 4.2 days → <5 min · ~70% overhead reduction · re-processing driven down via schema validation at intake · audit-ready decision trace for the open KYC audits.

### Personas → RBAC roles
The system authenticates every user (JWT) and gates each surface by one of three
roles. Each persona maps to a role and its dedicated portal.

| Persona | RBAC role | Pain today | PolicyFlow portal |
|---|---|---|---|
| Employer / claim submitter | **EMPLOYER** | Manual submission, no visibility | Submit widget + **My Claims** (own claims only, search) |
| Claims Operator / Ops Reviewer (HITL) | **REVIEWER** | 60%+ time on triage; escalations manual | **Review Queue** (reason shown) + override, All Claims, policy docs, audit |
| Fraud Analyst | **REVIEWER** | No real-time cross-referencing | Fraud panel + risk score on case detail |
| Compliance Officer / VP Operations | **ADMIN** | No audit trail, no user/data control | **Admin Console**: users, KYC members, all claims, eval dashboard, audit |

---

## 2. Scope

### Epics (In-Scope MVP)
| Epic | Description |
|---|---|
| E1 — Ingestion (UI + API) | **UI upload widget (single or multiple files) is the primary path**; FastAPI multipart, magic-byte validation, MinIO storage, `case_id`, Celery dispatch. One upload (1..N files) = one case; append supported |
| E2 — Classification | Vision-LLM classifier → 6 doc types + UNKNOWN routing |
| E3 — Preprocessing | Type-specific extraction (Docling for PDF / Vision LLM for image / Tesseract fallback) → `DocumentContent` |
| E4 — Specialist Agents | KYC (vs member DB), Claims (schema-validated extraction), Policy RAG (coverage) — parallel |
| E5 — Fraud Detection | Anomaly scoring vs claim history + cross-document signals |
| E6 — Decision Orchestration | Weighted Approve/Reject/Escalate via LangGraph aggregation |
| E7 — HITL | Async escalate → review queue → human override → resume (checkpointed) |
| E8 — Case Management UI | Next.js **three role-gated portals** (Employer / Reviewer / Admin), case detail, review queue, audit log |
| E9 — Dataset | 155 synthetic docs + 2 policy PDFs + `metadata.json` (via existing `scripts/`) |
| E10 — Per-stage Evals | Scored metric at every agent boundary + weighted grade; live admin eval dashboard |
| E11 — Auth & RBAC | JWT login (bcrypt + HS256), three roles (ADMIN/REVIEWER/EMPLOYER), `require_role` gates + ownership scoping, admin-managed users and KYC members |

### Functional requirements (E11 — auth & RBAC)
- **FR-A1 (auth):** every API call and portal page requires a valid JWT; login returns an access token carrying `sub` + `role`. Accounts are admin-provisioned (roles never self-chosen).
- **FR-A2 (employer):** submit claims (stamped `submitted_by`) and see/search **only own** claims.
- **FR-A3 (reviewer):** see/search **all** claims; a pending queue of ESCALATED/AWAITING_HUMAN cases with the escalation reason; override/finalize (locks the case); policy-docs + audit access.
- **FR-A4 (admin):** manage app users (create + assign role) and KYC members (add + bulk upload); read all claims; live eval-metrics dashboard. Admins cannot submit claims.

### Out-of-Scope (this pass)
Real email/fax ingestion · **external SSO/OAuth federation** (local JWT + RBAC is in-scope, E11) · K8s autoscaling · real claims-system integration · **multi-language OCR (deferred)** · production HIPAA certification.

### Explicitly Removed After Review (were chatbot-shaped, don't fit a batch pipeline)
- ❌ **Intent classification** — `doc_type` already routes; no ambiguous utterance to interpret.
- ❌ **Session management / conversational memory** — replaced by the **case = patient-episode bundle** + the **claim-history** store.
- ❌ **"Multi-turn (5)" dialogue** — reframed as **bounded retry (≤3)** on failed extraction/validation.

---

## 3. Functional Requirements (FR)

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Accept **single or multiple** file uploads (JPEG/PNG/PDF/TIFF) from the **UI upload widget** or API, with magic-byte validation | P0 |
| FR-02 | **One upload (1..N files) = one case bundle**; generate a `case_id`; each file becomes a `document` in that case | P0 |
| FR-02b | Append documents to an existing case; **re-run affected agents** (Fraud + Orchestrator re-evaluate with the new doc) | P1 |
| FR-03 | Store raw docs in MinIO (UUID keys); publish job to Redis/Celery | P0 |
| FR-04 | Classify each doc into 6 types + UNKNOWN, with confidence | P0 |
| FR-05 | Route UNKNOWN / confidence <0.6 to the human review queue | P0 |
| FR-06 | Type-specific preprocessing → normalized `DocumentContent {fields, raw_text, bounding_boxes}` | P0 |
| FR-07 | KYC: validate member ID / DOB / policy number vs **member DB**; check ID expiry; ELA tamper flag | P0 |
| FR-08 | Claims: extract ICD-10, CPT, NPI, amount, service date; validate schema | P0 |
| FR-09 | Policy RAG: Docling-ingest policy PDFs → Qdrant; retrieve clauses by CPT/ICD | P0 |
| FR-10 | Fraud: score 0.0–1.0 vs **claim history** + cross-document signals; risk level | P0 |
| FR-11 | Orchestrator: weighted APPROVE / REJECT / ESCALATE with justification | P0 |
| FR-12 | Dashboard: case list with status badges + filtering | P0 |
| FR-13 | Case detail: document viewer + collapsible per-agent panels + decision panel | P0 |
| FR-14 | Human override on escalated cases; resume pipeline from checkpoint | P0 |
| FR-15 | Timestamped audit log of every agent action + human override | P0 |
| FR-16 | Bounded retry (≤3) on extraction/validation failure before escalating | P1 |
| FR-17 | WebSocket real-time agent status to UI | P1 (bonus) |
| FR-18 | Download Case Report (PDF) of all agent outputs | P1 (bonus) |

---

## 4. Non-Functional Requirements (NFR)

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | File size limit | 10 MB/file |
| NFR-02 | Supported formats | JPEG/PNG/PDF/TIFF (magic-byte validated) |
| NFR-03 | End-to-end latency | P95 < 120s/case (LLM-dependent) |
| NFR-04 | Statelessness | FastAPI + Celery hold no state; horizontal-scalable |
| NFR-05 | Config | 100% env-driven; **zero hardcoded secrets** |
| NFR-06 | Typed contracts | Pydantic v2 at every agent boundary |
| NFR-07 | Resilience | tenacity retry (exp backoff + jitter) + circuit breaker on all LLM calls |
| NFR-08 | Observability | Structured JSON logs; `llm_calls` token/latency; LangSmith traces |
| NFR-09 | Provider-agnostic | All LLM access via LiteLLM aliases (`vision`/`reasoning`/`embeddings`) |
| NFR-10 | Bounded autonomy | Agent self-correction capped at 3 turns; LangGraph `recursion_limit` set |
| NFR-11 | Security | UUID filenames, `nosniff`, parameterized ORM, PII masking in UI, scoped CORS |

---

## 5. Locked Decisions

| # | Decision | Choice |
|---|---|---|
| D1 | LLM gateway | **LiteLLM** as a standalone **Proxy container** |
| D2 | Models | **Groq** — `qwen/qwen3.6-27b` (vision; behind the `vision` alias), `llama-3.3-70b-versatile` (reasoning) |
| D3 | Embeddings | **`BAAI/bge-large-en-v1.5` via Hugging Face Inference API** (1024-d) |
| D4 | Ingestion order | **Classify → Preprocess** (Option 2) |
| D5 | Infra | **Cloud-ready:** Postgres · Qdrant · MinIO · Redis+Celery · docker-compose |
| D6 | Case scope | **Patient-episode bundle** (dataset `case_cluster_id`) |
| D7 | HITL | **Async escalate → override**, persisted via LangGraph **checkpointer** |
| D8 | Memory | **Case bundle** (short-term) + **`claim_history` table** (long-term, fraud) — no conversational layer |
| D9 | Retry | Bounded **≤3** on extraction/validation failure |
| D10 | Decision labels | **Derived label map** from `fraud_label` + `edge_flags` (metadata has no `expected_decision`) |
| D11 | RAG | Docling **HybridChunker + TableFormer** → bge-large → Qdrant **hybrid (dense+keyword) + cross-encoder rerank** |
| D12 | Dataset | **Run existing `scripts/`** (do not rewrite); emit an additive `members.json` for KYC seed |
| D13 | Bonus | Calibration, WS streaming, ELA tamper, PDF export, LangSmith ✅ · Multi-language ⏸ |

---

## 6. Evaluation & Success Metrics

### 6.1 Assignment grading rubric (the gate)
| Criteria | Weight | Measurement |
|---|---|---|
| Classification accuracy | 20% | predicted `doc_type` vs `metadata.category` |
| Extraction completeness | 20% | field-level presence/accuracy vs cluster fields |
| Policy retrieval quality | 15% | relevance@k vs known CPT→section map (+ spot-check) |
| **Decision correctness** | **25%** | final decision vs **derived label map** |
| UI functionality | 10% | dashboard loads, detail renders, override works E2E |
| Code quality | 10% | typed contracts, no secrets, clean separation, security checklist |
| **Overall pass** | **≥70%** | weighted sum, with **Decision Correctness ≥60% (hard gate)** |

### 6.2 Per-stage evals (beyond the rubric — for debugging & confidence)
| Stage | Metric | Ground truth |
|---|---|---|
| Classification | accuracy + confusion matrix | `metadata.category` |
| Extraction | field completeness + accuracy | cluster ICD/CPT/NPI/amount/date |
| Retrieval | relevance@k, MRR | known CPT→section map |
| KYC | precision/recall of flags | `edge_flags` (expired/tampered/expiring) |
| Fraud | precision/recall/F1 | `fraud_label`, `fraud_reason` |
| Decision | accuracy (≥60% gate) | derived label map |
| Calibration | reliability curve / ECE | decision correctness vs confidence |

### 6.3 Derived decision label map (oracle for the 25% metric)
- `fraud_label == True` → **ESCALATE**
- `edge_flags ∩ {uncovered_procedure, expired_id}` and not fraud → **REJECT**
- `edge_flags ∩ {missing_fields, tampered_id}` → **REJECT**
- `edge_flags ∩ {expiring_soon_id, blur_simulated}` only → **ESCALATE**
- `dataset/unknown/*` → **ESCALATE**
- otherwise → **APPROVE**

---

## 7. Risks & Mitigations
| Risk | Pri | Mitigation |
|---|---|---|
| `metadata.json` lacks `expected_decision` | P0 | Derived label map (§6.3); verify at dataset bootstrap |
| Member-DB seed mismatches doc field formats → KYC always fails | P0 | Seed **from dataset** (`members.json`), never invent IDs |
| Cross-doc fraud needs multiple docs together | P0 | Case = patient bundle (D6) + `claim_history` persistence |
| LLM extraction drift on blurry/tampered scans | P1 | OCR fallback + schema validation + bounded retry → escalate |
| bge-large HF API latency/rate limits | P2 | LiteLLM cache; TEI container fallback documented |
| Retrieval precision (15%) | P2 | Hybrid + rerank + richer CPT/ICD query |

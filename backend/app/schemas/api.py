"""API request/response contracts (docs/LLD.md §6)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import EvalScope


class StoredDoc(BaseModel):
    doc_id: str
    storage_key: str
    original_filename: str
    mime_type: str
    file_size_bytes: int


class DocumentSummary(BaseModel):
    doc_id: str
    doc_type: str | None = None
    original_filename: str
    storage_key: str
    mime_type: str
    classify_confidence: float | None = None


class CaseCreatedResponse(BaseModel):
    case_id: str
    status: str
    documents: list[DocumentSummary]


class AppendResponse(BaseModel):
    case_id: str
    status: str
    added: list[DocumentSummary]


class CaseListItem(BaseModel):
    case_id: str
    status: str
    decision: str | None = None
    decision_confidence: float | None = None
    member_id: str | None = None  # masked in list view
    patient_name: str | None = None
    submitted_by: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CaseList(BaseModel):
    cases: list[CaseListItem]
    total: int
    page: int
    limit: int


class AgentOutputItem(BaseModel):
    agent: str
    output: dict
    confidence: float | None = None
    created_at: datetime


class AuditItem(BaseModel):
    actor: str
    event_type: str
    details: dict | None = None
    confidence: float | None = None
    ts: datetime


class CaseDetail(BaseModel):
    case_id: str
    cluster_id: str | None = None
    member_id: str | None = None  # full value in detail view
    patient_name: str | None = None
    submitted_by: str | None = None
    status: str
    decision: str | None = None
    decision_confidence: float | None = None
    decision_justification: str | None = None
    override_decision: str | None = None
    override_by: str | None = None
    override_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentSummary] = Field(default_factory=list)
    agent_outputs: list[AgentOutputItem] = Field(default_factory=list)
    audit_events: list[AuditItem] = Field(default_factory=list)


class OverrideRequest(BaseModel):
    decision: str  # APPROVE | REJECT
    reviewer: str | None = None  # ignored — reviewer identity comes from the token
    reason: str


class OverrideResponse(BaseModel):
    case_id: str
    original_decision: str | None
    override_decision: str
    override_by: str
    override_at: datetime


class PolicyIngestResponse(BaseModel):
    plan: str
    chunks_created: int
    collection: str


class PolicyIngestAccepted(BaseModel):
    """202 response — ingestion runs in the worker (Docling is slow)."""

    task_id: str
    status: str = "PROCESSING"
    plan: str
    storage_key: str


class PolicyJobStatus(BaseModel):
    task_id: str
    state: str  # PENDING | STARTED | SUCCESS | FAILURE
    chunks_created: int | None = None
    error: str | None = None


class PolicyDocItem(BaseModel):
    """One ingested policy (aggregated from its RAG chunks; one per plan)."""

    plan: str
    chunk_count: int
    section_count: int
    sections: list[str] = Field(default_factory=list)  # sample of section headings


class PolicyDocList(BaseModel):
    policies: list[PolicyDocItem]
    total: int


# ---- Auth / users (Phase 9 — RBAC) ----------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — scheme name, not a secret
    username: str
    role: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    role: str  # Role value — validated in the service
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    status: str
    created_at: datetime


class UserList(BaseModel):
    users: list[UserOut]
    total: int


# ---- Admin: KYC members (Phase 9d) ----------------------------------------
class MemberCreate(BaseModel):
    member_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    id_display_name: str | None = None  # defaults to `name` when omitted
    policy_number: str = Field(min_length=1, max_length=32)
    policy_type: str  # GOLD | SILVER
    date_of_birth: str | None = None  # ISO date
    gender: str | None = None
    group_number: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    id_type: str | None = None
    id_expiry_date: str | None = None  # ISO date
    provider_npi: str | None = None


class MemberOut(BaseModel):
    member_id: str  # masked in list view, full in detail
    name: str
    policy_number: str
    policy_type: str
    date_of_birth: str | None = None
    id_expiry_date: str | None = None
    city: str | None = None
    state: str | None = None


class MemberList(BaseModel):
    members: list[MemberOut]
    total: int


class BulkMembersResult(BaseModel):
    created: int
    updated: int
    errors: list[str] = Field(default_factory=list)


class ClearCasesResult(BaseModel):
    cases: int
    documents: int
    files_removed: int
    files_failed: int
    checkpoints_cleared: bool


# ---- Admin: live eval metrics (Phase 9d, reuses Phase 7 harness) ----------
class PRFOut(BaseModel):
    precision: float
    recall: float
    f1: float


class EvalMetrics(BaseModel):
    classification_accuracy: float
    extraction_accuracy: float
    retrieval_relevance_at_k: float
    retrieval_mrr: float
    decision_accuracy: float
    kyc: PRFOut | None = None
    fraud: PRFOut | None = None
    weighted_grade: float
    captured_cases: int = 0  # case-bundles that actually ran through the graph
    skipped_cases: int = 0  # bundles dropped mid-run (rate limit / LLM error)
    decision_gate_passed: bool
    overall_gate_passed: bool
    passed: bool
    notes: list[str] = Field(default_factory=list)
    source: str  # where the scored predictions came from


class EvalRunRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1)  # sample N case-bundles (None = all)
    scope: EvalScope = EvalScope.PIPELINE  # which track-group to run


class EvalRunAccepted(BaseModel):
    task_id: str
    scope: EvalScope
    status: str = "RUNNING"


class EvalJobStatus(BaseModel):
    task_id: str
    state: str  # PENDING | STARTED | SUCCESS | FAILURE
    scope: EvalScope | None = None
    metrics: EvalMetrics | None = None
    error: str | None = None


class EvalRunStatus(BaseModel):
    """Current live-run state, so a refreshed page can resume instead of losing
    track of an in-flight run (or double-triggering one)."""

    running: bool
    task_id: str | None = None
    scope: EvalScope | None = None
    state: str | None = None  # Celery state of the active task, when running

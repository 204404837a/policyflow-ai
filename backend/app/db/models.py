"""SQLAlchemy 2.0 ORM models — the relational source of truth.

Schema reference: docs/DATABASE_SCHEMA.md. Enums are stored as their string
`.value`; JSON blobs use Postgres JSONB. All access is async (asyncpg).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Member(Base):
    """KYC source of truth — one per patient (seeded from dataset/members.json)."""

    __tablename__ = "members"

    member_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # = patient_id
    name: Mapped[str] = mapped_column(String(120))  # true name
    id_display_name: Mapped[str] = mapped_column(String(120))  # name shown on ID doc
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True)
    policy_number: Mapped[str] = mapped_column(String(32), index=True)
    policy_type: Mapped[str] = mapped_column(String(8))  # GOLD | SILVER
    group_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    id_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    id_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider_npi: Mapped[str | None] = mapped_column(String(15), nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)

    claim_history: Mapped[list[ClaimHistory]] = relationship(back_populates="member")
    cases: Mapped[list[Case]] = relationship(back_populates="member")


class ClaimHistory(Base):
    """Prior claims per member — the Fraud agent's long-term baseline store."""

    __tablename__ = "claim_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    claim_date: Mapped[date] = mapped_column(Date)
    claim_amount: Mapped[float] = mapped_column(Float)
    icd_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cpt_code: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)
    provider_npi: Mapped[str | None] = mapped_column(String(15), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="APPROVED")
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    member: Mapped[Member] = relationship(back_populates="claim_history")


class User(Base):
    """Application user with an RBAC role (admin / reviewer / employer).

    Distinct from `members` (the KYC patient records): a `User` is a login
    account; a `Member` is a patient whose identity claims are validated against.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)  # Role value
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    submitted_cases: Mapped[list[Case]] = relationship(back_populates="submitter")


class Case(Base):
    """One patient-episode bundle (1 upload = 1 case)."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    cluster_id: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    member_id: Mapped[str | None] = mapped_column(ForeignKey("members.member_id"), nullable=True)
    # Employer (uploader) who submitted this case; scopes employer visibility.
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    patient_name: Mapped[str | None] = mapped_column(String(120), nullable=True)  # for list/search
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED", index=True)
    decision: Mapped[str | None] = mapped_column(String(12), nullable=True)
    decision_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    override_decision: Mapped[str | None] = mapped_column(String(12), nullable=True)
    override_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    member: Mapped[Member | None] = relationship(back_populates="cases")
    submitter: Mapped[User | None] = relationship(back_populates="submitted_cases")
    documents: Mapped[list[Document]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    agent_outputs: Mapped[list[AgentOutput]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        """Human-finalized cases are locked (append → 409)."""
        return self.override_decision is not None


class Document(Base):
    """One uploaded file within a case."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    parser_used: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # DocumentContent
    classify_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge_flags_observed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    case: Mapped[Case] = relationship(back_populates="documents")


class AgentOutput(Base):
    """Normalized per-agent output (one row per agent run, per doc or case)."""

    __tablename__ = "agent_outputs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String(20), index=True)
    output: Mapped[dict] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    turn: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    case: Mapped[Case] = relationship(back_populates="agent_outputs")


class LLMCall(Base):
    """Per-LiteLLM-call observability (tokens / latency / model)."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cases.id"), index=True, nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    alias: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditEvent(Base):
    """Immutable timestamped trace of every agent step + human action."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    actor: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    case: Mapped[Case] = relationship(back_populates="audit_events")

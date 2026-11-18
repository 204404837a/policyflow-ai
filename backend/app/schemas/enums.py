"""Canonical enums — single source for ORM models and Pydantic contracts.

Stored in the DB as their string `.value` (String columns), validated at the
application layer. See docs/DATA_DICTIONARY.md.
"""

from __future__ import annotations

from enum import StrEnum


class EvalScope(StrEnum):
    """Which eval group a live run drives.

    The 5 pipeline tracks (classification/extraction/decision/kyc/fraud) all come
    from one graph pass, so they run together as PIPELINE. RETRIEVAL is the cheap
    standalone RAG spot-check (no vision calls) and runs on its own.
    """

    PIPELINE = "pipeline"
    RETRIEVAL = "retrieval"


class DocumentType(StrEnum):
    CLAIM_FORM = "CLAIM_FORM"
    ID_DOCUMENT = "ID_DOCUMENT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    PRESCRIPTION = "PRESCRIPTION"
    POLICY_AMENDMENT = "POLICY_AMENDMENT"
    UNKNOWN = "UNKNOWN"


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class Role(StrEnum):
    """Application user roles (RBAC). Admin manages users + members; employer
    submits claims and sees only their own; reviewer works the review queue."""

    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    EMPLOYER = "EMPLOYER"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CaseStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    AWAITING_HUMAN = "AWAITING_HUMAN"


class AgentName(StrEnum):
    CLASSIFIER = "CLASSIFIER"
    PREPROCESSOR = "PREPROCESSOR"
    KYC = "KYC"
    CLAIMS = "CLAIMS"
    POLICY = "POLICY"
    FRAUD = "FRAUD"
    ORCHESTRATOR = "ORCHESTRATOR"
    HUMAN = "HUMAN"


class ParserUsed(StrEnum):
    DOCLING = "DOCLING"
    VISION_LLM = "VISION_LLM"
    TESSERACT = "TESSERACT"


class SourceType(StrEnum):
    IMAGE = "image"
    PDF = "pdf"


class PolicyType(StrEnum):
    GOLD = "GOLD"
    SILVER = "SILVER"


class AuditEventType(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY = "RETRY"
    OVERRIDE = "OVERRIDE"

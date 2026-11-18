"""Case persistence — maps ORM ↔ API response models.

Endpoints depend on the `CaseRepository` protocol; the SQL impl is injected in
production and a fake in tests, so the API layer needs no live DB to test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.security import mask_value
from app.db.models import AgentOutput, AuditEvent, Case, Document
from app.schemas.api import (
    AgentOutputItem,
    AppendResponse,
    AuditItem,
    CaseCreatedResponse,
    CaseDetail,
    CaseList,
    CaseListItem,
    DocumentSummary,
    OverrideResponse,
    StoredDoc,
)
from app.schemas.enums import AuditEventType, CaseStatus, Decision

_OVERRIDE_STATUS = {
    Decision.APPROVE.value: CaseStatus.APPROVED.value,
    Decision.REJECT.value: CaseStatus.REJECTED.value,
}


class CaseRepository(Protocol):
    async def create_case(
        self,
        case_id: str,
        cluster_id: str | None,
        docs: list[StoredDoc],
        submitted_by: str | None = None,
    ) -> CaseCreatedResponse: ...
    async def append_documents(self, case_id: str, docs: list[StoredDoc]) -> AppendResponse: ...
    async def list_cases(
        self,
        status: str | None,
        page: int,
        limit: int,
        submitted_by: str | None = None,
        q: str | None = None,
    ) -> CaseList: ...
    async def get_detail(self, case_id: str) -> CaseDetail: ...
    async def apply_override(
        self, case_id: str, decision: str, reviewer: str, reason: str
    ) -> OverrideResponse: ...


def _list_filters(status: str | None, submitted_by: str | None, q: str | None) -> list[Any]:
    """Build the WHERE clauses for a case list (status + ownership + search)."""
    clauses: list[Any] = []
    if status:
        clauses.append(Case.status == status)
    if submitted_by:
        clauses.append(Case.submitted_by == uuid.UUID(submitted_by))
    if q:
        like = f"%{q}%"
        clauses.append(
            or_(
                Case.patient_name.ilike(like),
                Case.status.ilike(like),
                cast(Case.id, String).ilike(like),
            )
        )
    return clauses


def _doc_summary(d: Document) -> DocumentSummary:
    return DocumentSummary(
        doc_id=d.doc_id or str(d.id),
        doc_type=d.doc_type,
        original_filename=d.original_filename,
        storage_key=d.storage_key,
        mime_type=d.mime_type,
        classify_confidence=d.classify_confidence,
    )


def _new_document(case_id: uuid.UUID, sd: StoredDoc) -> Document:
    return Document(
        case_id=case_id,
        doc_id=sd.doc_id,
        original_filename=sd.original_filename,
        storage_key=sd.storage_key,
        mime_type=sd.mime_type,
        file_size_bytes=sd.file_size_bytes,
    )


class SqlCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get(self, case_id: str) -> Case:
        try:
            cid = uuid.UUID(case_id)
        except ValueError as exc:
            raise NotFoundError(f"case {case_id} not found") from exc
        case = await self._session.get(Case, cid)
        if case is None:
            raise NotFoundError(f"case {case_id} not found")
        return case

    async def create_case(
        self,
        case_id: str,
        cluster_id: str | None,
        docs: list[StoredDoc],
        submitted_by: str | None = None,
    ) -> CaseCreatedResponse:
        cid = uuid.UUID(case_id)
        case = Case(
            id=cid,
            cluster_id=cluster_id,
            status=CaseStatus.RECEIVED.value,
            submitted_by=uuid.UUID(submitted_by) if submitted_by else None,
        )
        self._session.add(case)
        documents = [_new_document(cid, sd) for sd in docs]
        self._session.add_all(documents)
        await self._session.commit()
        return CaseCreatedResponse(
            case_id=case_id,
            status=CaseStatus.RECEIVED.value,
            documents=[_doc_summary(d) for d in documents],
        )

    async def append_documents(self, case_id: str, docs: list[StoredDoc]) -> AppendResponse:
        case = await self._get(case_id)
        if case.override_decision is not None:
            raise ConflictError(f"case {case_id} is finalized (locked)")
        documents = [_new_document(case.id, sd) for sd in docs]
        self._session.add_all(documents)
        case.status = CaseStatus.PROCESSING.value
        await self._session.commit()
        return AppendResponse(
            case_id=case_id,
            status=CaseStatus.PROCESSING.value,
            added=[_doc_summary(d) for d in documents],
        )

    async def list_cases(
        self,
        status: str | None,
        page: int,
        limit: int,
        submitted_by: str | None = None,
        q: str | None = None,
    ) -> CaseList:
        stmt = select(Case)
        count_stmt = select(func.count()).select_from(Case)
        for clause in _list_filters(status, submitted_by, q):
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)
        total = int(await self._session.scalar(count_stmt) or 0)
        stmt = stmt.order_by(Case.created_at.desc()).offset((page - 1) * limit).limit(limit)
        rows = list(await self._session.scalars(stmt))
        cases = [
            CaseListItem(
                case_id=str(c.id),
                status=c.status,
                decision=c.decision,
                decision_confidence=c.decision_confidence,
                member_id=mask_value("member_id", c.member_id),
                patient_name=c.patient_name,
                submitted_by=str(c.submitted_by) if c.submitted_by else None,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in rows
        ]
        return CaseList(cases=cases, total=total, page=page, limit=limit)

    async def get_detail(self, case_id: str) -> CaseDetail:
        case = await self._get(case_id)
        docs = list(
            await self._session.scalars(select(Document).where(Document.case_id == case.id))
        )
        outputs = list(
            await self._session.scalars(
                select(AgentOutput)
                .where(AgentOutput.case_id == case.id)
                .order_by(AgentOutput.created_at)
            )
        )
        audits = list(
            await self._session.scalars(
                select(AuditEvent).where(AuditEvent.case_id == case.id).order_by(AuditEvent.ts)
            )
        )
        return CaseDetail(
            case_id=str(case.id),
            cluster_id=case.cluster_id,
            member_id=case.member_id,
            patient_name=case.patient_name,
            submitted_by=str(case.submitted_by) if case.submitted_by else None,
            status=case.status,
            decision=case.decision,
            decision_confidence=case.decision_confidence,
            decision_justification=case.decision_justification,
            override_decision=case.override_decision,
            override_by=case.override_by,
            override_reason=case.override_reason,
            created_at=case.created_at,
            updated_at=case.updated_at,
            documents=[_doc_summary(d) for d in docs],
            agent_outputs=[
                AgentOutputItem(
                    agent=o.agent,
                    output=o.output,
                    confidence=o.confidence,
                    created_at=o.created_at,
                )
                for o in outputs
            ],
            audit_events=[
                AuditItem(
                    actor=a.actor,
                    event_type=a.event_type,
                    details=a.details,
                    confidence=a.confidence,
                    ts=a.ts,
                )
                for a in audits
            ],
        )

    async def apply_override(
        self, case_id: str, decision: str, reviewer: str, reason: str
    ) -> OverrideResponse:
        if decision not in _OVERRIDE_STATUS:
            raise BadRequestError("override decision must be APPROVE or REJECT")
        case = await self._get(case_id)
        if case.status not in (CaseStatus.ESCALATED.value, CaseStatus.AWAITING_HUMAN.value):
            raise BadRequestError(f"case {case_id} is not awaiting review")

        original = case.decision
        now = datetime.now(UTC).replace(tzinfo=None)
        case.override_decision = decision
        case.override_by = reviewer
        case.override_reason = reason
        case.override_at = now
        case.status = _OVERRIDE_STATUS[decision]
        self._session.add(
            AuditEvent(
                case_id=case.id,
                actor="HUMAN",
                event_type=AuditEventType.OVERRIDE.value,
                details={"from": original, "to": decision, "reviewer": reviewer, "reason": reason},
            )
        )
        await self._session.commit()
        return OverrideResponse(
            case_id=case_id,
            original_decision=original,
            override_decision=decision,
            override_by=reviewer,
            override_at=now,
        )

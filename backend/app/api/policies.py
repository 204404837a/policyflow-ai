"""Policy PDF ingestion into the RAG vector store.

Ingestion is offloaded to the Celery worker: Docling PDF parsing takes minutes,
which would blow the request/proxy timeout. The endpoint stores the PDF, enqueues
the job, and returns `202` with a `task_id`; the client polls the status route.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_dispatcher, get_rag_service, get_storage, require_role
from app.core.errors import BadRequestError
from app.db.models import User
from app.ingestion.storage import ObjectStorage
from app.schemas.api import (
    PolicyDocItem,
    PolicyDocList,
    PolicyIngestAccepted,
    PolicyJobStatus,
)
from app.schemas.enums import PolicyType, Role
from app.services.dispatcher import Dispatcher
from app.services.rag_service import RagService

router = APIRouter(prefix="/api", tags=["policies"])


@router.get("/policies", response_model=PolicyDocList)
async def list_policies(
    rag: RagService = Depends(get_rag_service),
    user: User = Depends(require_role(Role.ADMIN.value, Role.REVIEWER.value)),
) -> PolicyDocList:
    """List ingested policy documents (one per plan) — ADMIN + REVIEWER."""
    rows = await rag.list_policies()
    return PolicyDocList(policies=[PolicyDocItem(**r) for r in rows], total=len(rows))


@router.post("/policies/ingest", response_model=PolicyIngestAccepted, status_code=202)
async def ingest_policy(
    file: UploadFile = File(...),
    plan: str = Form(...),
    storage: ObjectStorage = Depends(get_storage),
    dispatcher: Dispatcher = Depends(get_dispatcher),
    user: User = Depends(require_role(Role.ADMIN.value)),
) -> PolicyIngestAccepted:
    if plan not in (PolicyType.GOLD.value, PolicyType.SILVER.value):
        raise BadRequestError("plan must be GOLD or SILVER")
    data = await file.read()
    key = f"policies/{uuid.uuid4()}.pdf"
    await storage.put(key, data, "application/pdf")
    task_id = dispatcher.dispatch_policy(key, plan, file.filename or "policy.pdf")
    return PolicyIngestAccepted(task_id=task_id, plan=plan, storage_key=key)


@router.get("/policies/jobs/{task_id}", response_model=PolicyJobStatus)
async def policy_job_status(
    task_id: str,
    user: User = Depends(require_role(Role.ADMIN.value)),
) -> PolicyJobStatus:
    from app.worker.celery_app import celery_app  # lazy

    res = celery_app.AsyncResult(task_id)
    state = str(res.state)
    if state == "SUCCESS":
        return PolicyJobStatus(task_id=task_id, state=state, chunks_created=int(res.result))
    if state == "FAILURE":
        return PolicyJobStatus(task_id=task_id, state=state, error=str(res.result))
    return PolicyJobStatus(task_id=task_id, state=state)

"""Ingestion API — upload (1..N files → one case) + append documents."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_dispatcher, get_repo, get_storage, require_role
from app.core.errors import ForbiddenError
from app.core.security import validate_upload
from app.db.models import User
from app.ingestion.storage import ObjectStorage, ext_for_mime
from app.schemas.api import AppendResponse, CaseCreatedResponse, StoredDoc
from app.schemas.enums import Role
from app.services.case_repository import CaseRepository
from app.services.dispatcher import Dispatcher

router = APIRouter(prefix="/api", tags=["cases"])


async def _store_files(
    files: list[UploadFile], storage: ObjectStorage, case_id: str
) -> list[StoredDoc]:
    stored: list[StoredDoc] = []
    for f in files:
        data = await f.read()
        mime = validate_upload(f.filename or "upload", data)  # 400/413 on invalid
        doc_id = uuid.uuid4().hex
        key = ObjectStorage.key(case_id, doc_id, ext_for_mime(mime))
        await storage.put(key, data, mime)
        stored.append(
            StoredDoc(
                doc_id=doc_id,
                storage_key=key,
                original_filename=f.filename or "upload",
                mime_type=mime,
                file_size_bytes=len(data),
            )
        )
    return stored


@router.post("/cases", status_code=202, response_model=CaseCreatedResponse)
async def create_case(
    files: list[UploadFile] = File(...),
    cluster_id: str | None = Form(default=None),
    repo: CaseRepository = Depends(get_repo),
    storage: ObjectStorage = Depends(get_storage),
    dispatcher: Dispatcher = Depends(get_dispatcher),
    user: User = Depends(require_role(Role.EMPLOYER.value)),
) -> CaseCreatedResponse:
    case_id = str(uuid.uuid4())
    stored = await _store_files(files, storage, case_id)
    response = await repo.create_case(case_id, cluster_id, stored, submitted_by=str(user.id))
    dispatcher.dispatch(case_id)
    return response


@router.post("/cases/{case_id}/documents", status_code=202, response_model=AppendResponse)
async def append_documents(
    case_id: str,
    files: list[UploadFile] = File(...),
    repo: CaseRepository = Depends(get_repo),
    storage: ObjectStorage = Depends(get_storage),
    dispatcher: Dispatcher = Depends(get_dispatcher),
    user: User = Depends(require_role(Role.EMPLOYER.value)),
) -> AppendResponse:
    detail = await repo.get_detail(case_id)  # 404 if missing
    if detail.submitted_by != str(user.id):
        raise ForbiddenError("not your case")
    stored = await _store_files(files, storage, case_id)
    response = await repo.append_documents(case_id, stored)  # 404/409
    dispatcher.dispatch(case_id)
    return response

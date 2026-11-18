"""Read-only document serving (inline, nosniff)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import get_storage
from app.core.errors import NotFoundError
from app.ingestion.storage import ObjectStorage, StorageError

router = APIRouter(prefix="/api", tags=["files"])

_MEDIA = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "pdf": "application/pdf",
}


@router.get("/files/{key:path}")
async def get_file(key: str, storage: ObjectStorage = Depends(get_storage)) -> Response:
    try:
        data = await storage.get(key)
    except StorageError as exc:
        raise NotFoundError(f"file {key} not found") from exc
    ext = key.rsplit(".", 1)[-1].lower()
    return Response(
        content=data,
        media_type=_MEDIA.get(ext, "application/octet-stream"),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )

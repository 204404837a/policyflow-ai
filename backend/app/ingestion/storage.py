"""MinIO (S3-compatible) object storage for raw documents.

Keys: `raw/{case_id}/{doc_id}.{ext}`. The MinIO SDK is synchronous, so blocking
calls are offloaded to a thread (`asyncio.to_thread`) to stay non-blocking. The
client is injectable for testing (DI); a real one is built lazily from settings.
"""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.core.constants import PRESIGN_EXPIRES_S

_EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/tiff": "tiff",
    "application/pdf": "pdf",
}


class StorageError(RuntimeError):
    """Raised when an object-storage operation fails."""


def ext_for_mime(mime: str) -> str:
    return _EXT_BY_MIME.get(mime, "bin")


class ObjectStorage:
    def __init__(self, client: Any | None = None, bucket: str | None = None) -> None:
        self._client = client
        self._bucket = bucket or settings.minio_bucket

    def _client_or_build(self) -> Any:
        if self._client is None:
            from minio import Minio  # lazy import (keeps module import light)

            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    @staticmethod
    def key(case_id: str, doc_id: str, ext: str) -> str:
        return f"raw/{case_id}/{doc_id}.{ext}"

    def _ensure_bucket(self, client: Any) -> None:
        if not client.bucket_exists(self._bucket):
            client.make_bucket(self._bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        def _op() -> str:
            client = self._client_or_build()
            self._ensure_bucket(client)
            client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return key

        return await self._run(_op, f"put {key}")

    async def get(self, key: str) -> bytes:
        def _op() -> bytes:
            client = self._client_or_build()
            resp = client.get_object(self._bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await self._run(_op, f"get {key}")

    async def presign_get(self, key: str, expires_s: int = PRESIGN_EXPIRES_S) -> str:
        def _op() -> str:
            client = self._client_or_build()
            return client.presigned_get_object(
                self._bucket, key, expires=timedelta(seconds=expires_s)
            )

        return await self._run(_op, f"presign {key}")

    async def remove(self, key: str) -> None:
        """Delete one object. Tolerant of an already-absent key (idempotent)."""

        def _op() -> None:
            client = self._client_or_build()
            client.remove_object(self._bucket, key)

        await self._run(_op, f"remove {key}")

    @staticmethod
    async def _run(op: Any, what: str) -> Any:
        """Run a blocking storage op off-thread; wrap failures as StorageError."""
        try:
            return await asyncio.to_thread(op)
        except Exception as exc:
            # Network/SDK boundary: MinIO S3Error/urllib3 errors aren't a fixed
            # hierarchy, so wrap any failure into a typed StorageError.
            raise StorageError(f"object storage {what} failed: {exc}") from exc

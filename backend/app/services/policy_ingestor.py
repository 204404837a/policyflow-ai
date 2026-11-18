"""Policy PDF ingestion — Docling chunk → RAG upsert (injectable)."""

from __future__ import annotations

from typing import Protocol

from app.ingestion.docling_loader import DoclingLoader
from app.services.rag_service import RagService


class PolicyIngestor(Protocol):
    async def ingest(self, data: bytes, plan: str, filename: str) -> int: ...


class DefaultPolicyIngestor:
    def __init__(self, rag: RagService, docling: DoclingLoader | None = None) -> None:
        self._rag = rag
        self._docling = docling or DoclingLoader()

    async def ingest(self, data: bytes, plan: str, filename: str) -> int:
        chunks = await self._docling.chunks(data, filename=filename)
        return await self._rag.ingest_policy(chunks, plan)

"""Policy RAG over Qdrant — ingest policy chunks, retrieve clauses by codes.

Write path (ingest) and read path (retrieve) are the *only* places that touch
the vector DB (docs/HLD.md §5). Dense search + a lexical rerank (code overlap);
a cross-encoder reranker is a documented later upgrade (EXTENSIONS.md).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import settings
from app.core.constants import (
    EMBEDDING_DIM,
    QDRANT_POINT_ID_MODULO,
    RETRIEVAL_RERANK_KEEP,
    RETRIEVAL_TOP_K,
)
from app.ingestion.docling_loader import PolicyChunk
from app.llm.client import LLMClient


@dataclass
class Clause:
    text: str
    section: str
    plan: str
    score: float


class RagService:
    def __init__(self, client: LLMClient, qdrant: Any, collection: str | None = None) -> None:
        self._llm = client
        self._q = qdrant
        self._collection = collection or settings.qdrant_collection

    async def ensure_collection(self, size: int = EMBEDDING_DIM) -> None:
        def _op() -> None:
            if not self._q.collection_exists(self._collection):
                self._q.create_collection(
                    self._collection,
                    vectors_config=VectorParams(size=size, distance=Distance.COSINE),
                )

        await asyncio.to_thread(_op)

    async def ingest_policy(self, chunks: list[PolicyChunk], plan: str) -> int:
        if not chunks:
            return 0
        vectors = await self._llm.embed([c.text for c in chunks])
        await self.ensure_collection(size=len(vectors[0]))
        points = [
            PointStruct(
                id=abs(hash((plan, c.section, c.chunk_index))) % QDRANT_POINT_ID_MODULO,
                vector=vec,
                payload={
                    "plan": plan,
                    "section": c.section,
                    "clause_text": c.text,
                    "chunk_index": c.chunk_index,
                },
            )
            for c, vec in zip(chunks, vectors, strict=True)
        ]

        def _op() -> None:
            self._q.upsert(self._collection, points)

        await asyncio.to_thread(_op)
        return len(points)

    async def list_policies(self) -> list[dict[str, Any]]:
        """Aggregate ingested chunks by plan → one summary row per policy doc."""

        def _op() -> list[dict[str, Any]]:
            if not self._q.collection_exists(self._collection):
                return []
            agg: dict[str, dict[str, Any]] = {}
            offset: Any = None
            while True:
                points, offset = self._q.scroll(
                    collection_name=self._collection,
                    limit=256,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for p in points:
                    payload = p.payload or {}
                    plan = str(payload.get("plan", "UNKNOWN"))
                    section = str(payload.get("section", "")).strip()
                    entry = agg.setdefault(plan, {"chunks": 0, "sections": set()})
                    entry["chunks"] += 1
                    if section:
                        entry["sections"].add(section)
                if offset is None:
                    break
            return [
                {
                    "plan": plan,
                    "chunk_count": e["chunks"],
                    "section_count": len(e["sections"]),
                    "sections": sorted(e["sections"])[:12],
                }
                for plan, e in sorted(agg.items())
            ]

        return await asyncio.to_thread(_op)

    async def retrieve(
        self,
        cpt: list[str],
        icd: list[str],
        text: str,
        *,
        k: int = RETRIEVAL_TOP_K,
    ) -> list[Clause]:
        query = " ".join([*cpt, *icd, text]).strip()
        vector = (await self._llm.embed([query]))[0]

        def _op() -> list[Any]:
            # qdrant-client ≥1.12 replaced `.search()` with `.query_points()`.
            return self._q.query_points(
                collection_name=self._collection, query=vector, limit=k, with_payload=True
            ).points

        hits = await asyncio.to_thread(_op)
        clauses = [
            Clause(
                text=h.payload.get("clause_text", ""),
                section=h.payload.get("section", ""),
                plan=h.payload.get("plan", ""),
                score=float(getattr(h, "score", 0.0)),
            )
            for h in hits
        ]
        return self._rerank(clauses, [*cpt, *icd])[:RETRIEVAL_RERANK_KEEP]

    @staticmethod
    def _rerank(clauses: list[Clause], codes: list[str]) -> list[Clause]:
        def code_hits(c: Clause) -> int:
            return sum(1 for code in codes if code and code in c.text)

        return sorted(clauses, key=lambda c: (code_hits(c), c.score), reverse=True)

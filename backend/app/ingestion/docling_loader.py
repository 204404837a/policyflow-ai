"""Docling PDF ingestion — parse to DocumentContent and chunk for RAG.

Docling is heavy and is lazy-imported so module import (and unit tests) do not
require it. Used for policy PDFs (RAG, Phase 3) and any PDF documents.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass

from app.core.constants import INGEST_CONFIDENCE_DOCLING
from app.schemas.documents import DocumentContent
from app.schemas.enums import ParserUsed, SourceType


@dataclass
class PolicyChunk:
    """One retrievable policy clause chunk (→ Qdrant in Phase 3)."""

    text: str
    section: str
    chunk_index: int


class DoclingLoader:
    """Wraps Docling's DocumentConverter + HybridChunker (+ TableFormer)."""

    async def load(self, data: bytes, *, filename: str = "document.pdf") -> DocumentContent:
        """Parse a PDF's bytes into normalized DocumentContent."""
        return await asyncio.to_thread(self._load_sync, data, filename)

    async def chunks(self, data: bytes, *, filename: str = "policy.pdf") -> list[PolicyChunk]:
        """Section-aware chunks for policy RAG ingestion."""
        return await asyncio.to_thread(self._chunks_sync, data, filename)

    # -- sync internals (run in a thread) ----------------------------------

    @staticmethod
    def _convert(data: bytes, filename: str):  # type: ignore[no-untyped-def]
        from docling.document_converter import DocumentConverter  # lazy

        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            return DocumentConverter().convert(tmp.name).document

    def _load_sync(self, data: bytes, filename: str) -> DocumentContent:
        doc = self._convert(data, filename)
        text = doc.export_to_markdown()
        return DocumentContent(
            raw_text=text,
            source_type=SourceType.PDF,
            parser_used=ParserUsed.DOCLING,
            page_count=getattr(doc, "num_pages", lambda: 1)()
            if callable(getattr(doc, "num_pages", None))
            else 1,
            ingest_confidence=INGEST_CONFIDENCE_DOCLING if text.strip() else 0.0,
        )

    def _chunks_sync(self, data: bytes, filename: str) -> list[PolicyChunk]:
        # HierarchicalChunker splits by document structure (headings/sections)
        # and — unlike HybridChunker — needs no tokenizer, so it does NOT pull
        # the `all-MiniLM-L6-v2` model from HF. Same chunk interface (.text,
        # .meta.headings). Embeddings still go through LiteLLM → HF bge-large.
        from docling.chunking import HierarchicalChunker  # lazy

        doc = self._convert(data, filename)
        chunker = HierarchicalChunker(always_emit_headings=True)
        out: list[PolicyChunk] = []
        for i, chunk in enumerate(chunker.chunk(doc)):
            headings = getattr(getattr(chunk, "meta", None), "headings", None) or []
            section = headings[0] if headings else "General"
            out.append(PolicyChunk(text=chunk.text, section=str(section), chunk_index=i))
        return out

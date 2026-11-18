"""Preprocessor agent — type-specific extraction → DocumentContent.

Routing: PDF → Docling; image → vision LLM; empty/failed → Tesseract fallback.
Bounded retry (≤ MAX_RETRIES) on empty extractions before giving up, after
which the caller escalates (never silent-fail; code-quality §7, claims-safety).
"""

from __future__ import annotations

from app.core.constants import MAX_RETRIES
from app.core.logging import get_logger
from app.ingestion import vision_extract
from app.ingestion.docling_loader import DoclingLoader
from app.ingestion.ocr import OCRUnavailableError, ocr_text
from app.llm.client import LLMClient
from app.schemas.documents import DocumentContent
from app.schemas.enums import DocumentType

logger = get_logger(__name__)


class PreprocessError(RuntimeError):
    """Extraction failed after retries + fallback — caller should ESCALATE."""


def _is_empty(content: DocumentContent) -> bool:
    return not content.raw_text.strip() and not content.fields


class PreprocessorAgent:
    def __init__(
        self,
        client: LLMClient,
        docling: DoclingLoader | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._client = client
        self._docling = docling or DoclingLoader()
        self._max_retries = max_retries

    async def run(
        self,
        doc_type: DocumentType,
        data: bytes,
        *,
        mime: str,
        case_id: str | None = None,
        document_id: str | None = None,
    ) -> DocumentContent:
        if mime == "application/pdf":
            content = await self._docling.load(data, filename=f"{document_id or 'doc'}.pdf")
            if not _is_empty(content):
                return content
            return await self._fallback_ocr(data)

        # image path — bounded retry on empty vision extraction
        for attempt in range(1, self._max_retries + 1):
            content = await vision_extract.extract_image(
                self._client,
                data,
                doc_type,
                image_mime=mime,
                case_id=case_id,
                document_id=document_id,
            )
            if not _is_empty(content):
                return content
            logger.warning("empty_extraction_retry", extra={"attempt": attempt})

        return await self._fallback_ocr(data)

    async def _fallback_ocr(self, data: bytes) -> DocumentContent:
        try:
            content = await ocr_text(data)
        except OCRUnavailableError as exc:
            raise PreprocessError("extraction empty and OCR unavailable") from exc
        if _is_empty(content):
            raise PreprocessError("extraction empty after OCR fallback")
        return content

"""Tesseract OCR fallback (pure-text extraction).

Lazy-imports pytesseract/PIL and degrades gracefully when the `tesseract`
binary is absent — the pipeline routes to human review rather than crash.
"""

from __future__ import annotations

import asyncio
import io

from app.core.constants import INGEST_CONFIDENCE_OCR
from app.schemas.documents import DocumentContent
from app.schemas.enums import ParserUsed, SourceType


class OCRUnavailableError(RuntimeError):
    """Raised when Tesseract (binary or wrapper) is not available."""


async def ocr_text(image: bytes) -> DocumentContent:
    def _op() -> DocumentContent:
        try:
            import pytesseract  # lazy
            from PIL import Image  # lazy
        except ImportError as exc:  # pragma: no cover
            raise OCRUnavailableError("pytesseract/Pillow not installed") from exc
        try:
            text = pytesseract.image_to_string(Image.open(io.BytesIO(image)))
        except (OSError, ValueError, RuntimeError) as exc:
            # TesseractNotFoundError → OSError; TesseractError → RuntimeError.
            raise OCRUnavailableError(str(exc)) from exc
        return DocumentContent(
            raw_text=text.strip(),
            source_type=SourceType.IMAGE,
            parser_used=ParserUsed.TESSERACT,
            ingest_confidence=INGEST_CONFIDENCE_OCR if text.strip() else 0.0,
        )

    return await asyncio.to_thread(_op)

"""Image → DocumentContent via the `vision` LiteLLM alias."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.constants import INGEST_CONFIDENCE_VISION, VISION_ALIAS
from app.llm.client import LLMClient
from app.llm.prompts import PREPROCESSOR_SYSTEM, preprocessor_user
from app.schemas.documents import DocumentContent
from app.schemas.enums import DocumentType, ParserUsed, SourceType


class _VisionExtraction(BaseModel):
    """Compact structured payload the vision model returns."""

    raw_text: str = ""
    # icd_codes/cpt_codes arrive as lists; scalars for other fields.
    fields: dict[str, str | float | int | list[str] | None] = Field(default_factory=dict)


async def extract_image(
    client: LLMClient,
    image: bytes,
    doc_type: DocumentType,
    *,
    image_mime: str = "image/png",
    case_id: str | None = None,
    document_id: str | None = None,
) -> DocumentContent:
    """Run type-specific structured extraction on a scanned image."""
    result = await client.chat(
        VISION_ALIAS,
        system=PREPROCESSOR_SYSTEM,
        user=preprocessor_user(doc_type),
        image=image,
        image_mime=image_mime,
        response_model=_VisionExtraction,
        case_id=case_id,
        document_id=document_id,
    )
    assert isinstance(result, _VisionExtraction)
    has_content = bool(result.raw_text.strip() or result.fields)
    return DocumentContent(
        raw_text=result.raw_text.strip(),
        fields=result.fields,
        source_type=SourceType.IMAGE,
        parser_used=ParserUsed.VISION_LLM,
        ingest_confidence=INGEST_CONFIDENCE_VISION if has_content else 0.0,
    )

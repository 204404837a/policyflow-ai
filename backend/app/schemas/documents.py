"""Normalized document content — the one shape every downstream agent consumes.

Produced by the ingestion layer (Docling / vision LLM / Tesseract). See
docs/LLD.md §3 and docs/DATA_DICTIONARY.md.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.enums import ParserUsed, SourceType


class BoundingBox(BaseModel):
    field: str
    text: str
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


class DocumentContent(BaseModel):
    raw_text: str = ""
    # Multi-value fields (icd_codes, cpt_codes) come back as lists; scalars for
    # names/ids/amounts/dates.
    fields: dict[str, str | float | int | list[str] | None] = Field(default_factory=dict)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    tables: list[list[list[str]]] = Field(default_factory=list)
    source_type: SourceType = SourceType.IMAGE
    parser_used: ParserUsed = ParserUsed.VISION_LLM
    page_count: int = 1
    ingest_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

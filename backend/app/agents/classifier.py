"""Classifier agent — vision classification of a document image.

Low-confidence or UNKNOWN documents are flagged for the human review queue
(guardrail G-route; see docs/GUARDRAILS.md, HLD.md §2).
"""

from __future__ import annotations

from app.core.constants import MIN_AGENT_CONFIDENCE, VISION_ALIAS
from app.llm.client import LLMClient
from app.llm.prompts import CLASSIFIER_SYSTEM, CLASSIFIER_USER
from app.schemas.agents import ClassifierOutput
from app.schemas.enums import DocumentType


class ClassifierAgent:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def classify(
        self,
        image: bytes,
        *,
        image_mime: str = "image/png",
        case_id: str | None = None,
        document_id: str | None = None,
    ) -> ClassifierOutput:
        result = await self._client.chat(
            VISION_ALIAS,
            system=CLASSIFIER_SYSTEM,
            user=CLASSIFIER_USER,
            image=image,
            image_mime=image_mime,
            response_model=ClassifierOutput,
            case_id=case_id,
            document_id=document_id,
        )
        assert isinstance(result, ClassifierOutput)
        return result


def needs_human_review(output: ClassifierOutput) -> bool:
    """UNKNOWN or below the confidence floor → human queue."""
    return output.doc_type is DocumentType.UNKNOWN or output.confidence < MIN_AGENT_CONFIDENCE

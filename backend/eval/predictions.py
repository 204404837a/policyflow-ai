"""Prediction capture contracts (Pydantic v2) — the interface between a
pipeline run and the scorer.

A `--live` run of `run_eval.py` produces a `PredictionSet`; the scorer consumes
it offline. Keeping this a typed, serialisable contract means the graded
Decision≥60% assertion runs deterministically off a committed capture with no
LLM in the loop. PII discipline: predictions store *presence* and *type/score*
signals, never raw member/claim field values.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.enums import Decision, DocumentType
from pydantic import BaseModel, Field


class DocPrediction(BaseModel):
    """Per-document classifier + extraction signals."""

    doc_id: str
    predicted_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    # Which of EXPECTED_CLAIM_FIELDS the extractor populated (claim docs only).
    present_fields: list[str] = Field(default_factory=list)


class CasePrediction(BaseModel):
    """Per-case (patient bundle) KYC / fraud / decision signals."""

    case_id: str  # case_cluster_id, or doc_id for singleton (unknown) docs
    kyc_flags: list[str] = Field(default_factory=list)
    fraud_score: float = Field(ge=0.0, le=1.0)
    decision: Decision
    decision_confidence: float = Field(ge=0.0, le=1.0)


class RetrievalPrediction(BaseModel):
    """One policy-RAG spot-check: retrieved clause ids vs the relevant set."""

    cpt_code: str
    retrieved: list[str] = Field(default_factory=list)
    relevant: list[str] = Field(default_factory=list)


class PredictionSet(BaseModel):
    documents: list[DocPrediction] = Field(default_factory=list)
    cases: list[CasePrediction] = Field(default_factory=list)
    retrieval: list[RetrievalPrediction] = Field(default_factory=list)
    # Case-bundles that failed mid-run (e.g. 429/LLM error) and were skipped
    # rather than captured. Kept so the scorer/UI can distinguish "nothing ran"
    # from "everything passed" instead of showing a misleadingly empty board.
    skipped: list[str] = Field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: Path) -> PredictionSet:
        return cls.model_validate(json.loads(path.read_text()))

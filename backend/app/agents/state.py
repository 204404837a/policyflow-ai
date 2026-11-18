"""LangGraph pipeline state + injected dependencies.

Parallel fan-in (KYC/Claims/Policy) accumulates into `agent_events` via the
`operator.add` reducer; each specialist also writes its own result key. Bytes
never live in state — nodes fetch them from `storage` by key.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, TypedDict

from app.agents.claims import ClaimsAgent
from app.agents.classifier import ClassifierAgent
from app.agents.fraud import FraudAgent
from app.agents.kyc import KYCAgent
from app.agents.policy_rag import PolicyAgent
from app.agents.preprocessor import PreprocessorAgent
from app.ingestion.storage import ObjectStorage
from app.schemas.agents import OrchestratorOutput
from app.services.image_forensics import ImageForensics


class PipelineState(TypedDict, total=False):
    case_id: str
    documents: list[dict]  # {doc_id, storage_key, mime, doc_type?, content?}
    agent_events: Annotated[list[str], operator.add]  # parallel fan-in reducer
    needs_human: bool
    identity: dict
    claim_fields: dict
    procedure: dict
    fraud_context: dict
    kyc: dict
    claims: dict
    policy: dict
    fraud: dict
    decision: str
    decision_confidence: float
    decision_justification: str
    agent_summaries: dict
    retry_count: int
    current_stage: str


@dataclass
class PipelineDeps:
    classifier: ClassifierAgent
    preprocessor: PreprocessorAgent
    kyc: KYCAgent
    claims: ClaimsAgent
    policy: PolicyAgent
    fraud: FraudAgent
    storage: ObjectStorage
    forensics: ImageForensics
    orchestrator: Callable[..., OrchestratorOutput]

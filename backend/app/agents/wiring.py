"""Construct PipelineDeps from infrastructure handles (used by the worker)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.claims import ClaimsAgent
from app.agents.classifier import ClassifierAgent
from app.agents.fraud import FraudAgent
from app.agents.kyc import KYCAgent
from app.agents.orchestrator import make_decision
from app.agents.policy_rag import PolicyAgent
from app.agents.preprocessor import PreprocessorAgent
from app.agents.state import PipelineDeps
from app.ingestion.storage import ObjectStorage
from app.llm.client import LLMClient
from app.services.fraud_service import FraudService
from app.services.image_forensics import ImageForensics
from app.services.member_service import MemberService
from app.services.rag_service import RagService


def build_deps(
    session: AsyncSession, llm: LLMClient, storage: ObjectStorage, qdrant: Any
) -> PipelineDeps:
    return PipelineDeps(
        classifier=ClassifierAgent(llm),
        preprocessor=PreprocessorAgent(llm),
        kyc=KYCAgent(MemberService(session)),
        claims=ClaimsAgent(),
        policy=PolicyAgent(RagService(llm, qdrant), llm),
        fraud=FraudAgent(FraudService(session)),
        storage=storage,
        forensics=ImageForensics(),
        orchestrator=make_decision,
    )

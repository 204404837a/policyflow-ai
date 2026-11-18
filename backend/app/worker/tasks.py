"""Pipeline dispatch task — load a case's documents, run the graph, persist.

Runtime infra (Postgres checkpointer, Qdrant, live LLM) is exercised in Phase 5
integration; the pieces are lazy-constructed here.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.agents.graph import build_pipeline
from app.agents.wiring import build_deps
from app.core.config import settings
from app.core.constants import GRAPH_RECURSION_LIMIT
from app.core.logging import get_logger
from app.db.models import AgentOutput, AuditEvent, Case, Document, LLMCall
from app.ingestion.storage import ObjectStorage
from app.llm.client import LLMCallRecord, LLMClient
from app.schemas.enums import AuditEventType, CaseStatus, Decision
from app.worker.celery_app import celery_app

logger = get_logger(__name__)

_DECISION_STATUS = {
    Decision.APPROVE.value: CaseStatus.APPROVED.value,
    Decision.REJECT.value: CaseStatus.REJECTED.value,
    Decision.ESCALATE.value: CaseStatus.ESCALATED.value,
}


def _qdrant() -> Any:
    from qdrant_client import QdrantClient  # lazy

    return QdrantClient(url=settings.qdrant_url)


def _checkpointer() -> Any:
    """Async Postgres checkpointer context manager (psycopg conn string)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # lazy

    conn = settings.database_url.replace("+asyncpg", "")
    return AsyncPostgresSaver.from_conn_string(conn)


async def _persist(session: Any, case: Case, final: dict, llm_records: list[LLMCallRecord]) -> None:
    for agent in ("kyc", "claims", "policy", "fraud"):
        payload = final.get(agent)
        if payload is not None:
            session.add(
                AgentOutput(
                    case_id=case.id,
                    agent=agent.upper(),
                    output=payload,
                    confidence=payload.get("confidence"),
                )
            )
    case.status = _DECISION_STATUS.get(final.get("decision", ""), CaseStatus.ESCALATED.value)
    case.decision = final.get("decision")
    case.decision_confidence = final.get("decision_confidence")
    case.decision_justification = final.get("decision_justification")
    # Store the KYC-*resolved* member id (which exists in `members`), never the
    # raw extracted value — the latter may not match a member and would violate
    # the cases.member_id FK. Left null when KYC found no member.
    kyc = final.get("kyc") or {}
    if kyc.get("member_found") and kyc.get("member_id"):
        case.member_id = kyc["member_id"]
    identity = final.get("identity") or {}
    case.patient_name = identity.get("name") or (final.get("claim_fields") or {}).get(
        "patient_name"
    )

    session.add(
        AuditEvent(
            case_id=case.id,
            actor="ORCHESTRATOR",
            event_type=AuditEventType.COMPLETED.value,
            details={"decision": case.decision, "stage": final.get("current_stage")},
            confidence=case.decision_confidence,
        )
    )
    for rec in llm_records:
        session.add(
            LLMCall(
                case_id=case.id,
                alias=rec.alias,
                model=rec.model,
                prompt_tokens=rec.prompt_tokens,
                completion_tokens=rec.completion_tokens,
                total_tokens=rec.total_tokens,
                latency_ms=rec.latency_ms,
            )
        )


async def _run(case_id: str) -> str:
    llm_records: list[LLMCallRecord] = []

    async def on_call(rec: LLMCallRecord) -> None:
        llm_records.append(rec)

    # Celery runs each task in a fresh event loop (asyncio.run). asyncpg
    # connections are loop-bound, so the module-level app engine can't be
    # reused here — build a task-local engine (NullPool) inside this loop and
    # dispose it when done.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            case = await session.get(Case, uuid.UUID(case_id))
            if case is None:
                raise ValueError(f"case {case_id} not found")
            doc_rows = list(
                await session.scalars(select(Document).where(Document.case_id == case.id))
            )
            documents = [
                {"doc_id": d.doc_id or str(d.id), "storage_key": d.storage_key, "mime": d.mime_type}
                for d in doc_rows
            ]

            llm = LLMClient(on_call=on_call)
            deps = build_deps(session, llm, ObjectStorage(), _qdrant())
            case.status = CaseStatus.PROCESSING.value
            await session.flush()

            async with _checkpointer() as cp:
                await cp.setup()
                graph = build_pipeline(deps, cp)
                final = await graph.ainvoke(
                    {"case_id": case_id, "documents": documents, "retry_count": 0},
                    config={
                        "configurable": {"thread_id": case_id},
                        "recursion_limit": GRAPH_RECURSION_LIMIT,
                    },
                )

            await _persist(session, case, final, llm_records)
            await session.commit()
            await llm.aclose()
            logger.info(
                "pipeline_done", extra={"case_id": case_id, "decision": final.get("decision")}
            )
            return str(final.get("decision", CaseStatus.ESCALATED.value))
    finally:
        await engine.dispose()


@celery_app.task(name="run_pipeline")
def run_pipeline(case_id: str) -> str:
    return asyncio.run(_run(case_id))


async def _ingest_policy(storage_key: str, plan: str, filename: str) -> int:
    """Fetch the stored PDF, parse+chunk (Docling) and upsert to Qdrant."""
    from app.services.policy_ingestor import DefaultPolicyIngestor
    from app.services.rag_service import RagService

    data = await ObjectStorage().get(storage_key)
    ingestor = DefaultPolicyIngestor(RagService(LLMClient(), _qdrant()))
    chunks = await ingestor.ingest(data, plan, filename)
    logger.info("policy_ingested", extra={"plan": plan, "chunks": chunks, "key": storage_key})
    return chunks


@celery_app.task(name="ingest_policy")
def ingest_policy(storage_key: str, plan: str, filename: str) -> int:
    return asyncio.run(_ingest_policy(storage_key, plan, filename))


def _eval_records(limit: int | None) -> list[dict]:
    """Load metadata records, optionally sampling the first `limit` case-bundles."""
    import json

    # Reuse the eval module's canonical dataset paths (same as the offline CLI).
    from eval.run_eval import _default_metadata_path, group_cases

    records: list[dict] = json.loads(_default_metadata_path().read_text())
    if limit:  # keep bundles whole — sample by case, not by row
        sampled = list(group_cases(records).values())[:limit]
        records = [r for group in sampled for r in group]
    return records


def _score_and_save(predictions: Any, records: list[dict]) -> dict[str, Any]:
    from eval.run_eval import (
        capture_path,
        group_cases,
        report_to_dict,
        restrict_to_captured,
        score,
    )

    out = capture_path()  # writable location shared with the API (GET /metrics)
    out.parent.mkdir(parents=True, exist_ok=True)
    predictions.save(out)
    # Grade only the captured cases (consistent with GET /metrics); a bundle
    # skipped on a 429 shouldn't be counted as a wrong decision.
    scored = restrict_to_captured(predictions, records)
    report = score(predictions, scored)
    report.notes.append(f"scored over {len(predictions.cases)}/{len(group_cases(records))} case(s)")
    logger.info(
        "eval_run_done",
        extra={"captured": len(predictions.cases), "decision_acc": report.decision_accuracy},
    )
    return report_to_dict(report, source="live-run")


async def _run_eval(limit: int | None) -> dict[str, Any]:
    """Drive the live graph over the dataset, save the capture, and score it."""
    from eval.collect import collect_live  # lazy: heavy infra imports

    records = await asyncio.to_thread(_eval_records, limit)
    predictions = await collect_live(records)
    return await asyncio.to_thread(_score_and_save, predictions, records)


@celery_app.task(name="run_eval")
def run_eval(limit: int | None = None) -> dict[str, Any]:
    return asyncio.run(_run_eval(limit))


async def _run_retrieval_eval() -> dict[str, Any]:
    """Refresh only the retrieval track: run the RAG spot-check, merge it into
    the existing capture (preserving pipeline predictions), and re-score."""
    from eval.collect import collect_retrieval_only
    from eval.predictions import PredictionSet
    from eval.run_eval import capture_path

    retrieval = await collect_retrieval_only()
    out = capture_path()
    # Preserve whatever the last pipeline run captured; only swap retrieval.
    predictions = PredictionSet.load(out) if out.exists() else PredictionSet()
    predictions.retrieval = list(retrieval)
    records = await asyncio.to_thread(_eval_records, None)
    return await asyncio.to_thread(_score_and_save, predictions, records)


@celery_app.task(name="run_retrieval_eval")
def run_retrieval_eval() -> dict[str, Any]:
    return asyncio.run(_run_retrieval_eval())

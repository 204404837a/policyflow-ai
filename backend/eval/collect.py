"""Live prediction collector — drives the real graph over the dataset.

Integration-only: requires the full stack (Postgres seeded with members,
Qdrant with ingested policies, MinIO, LiteLLM→Groq/HF) exactly like the worker.
It is *not* unit-tested — the pure scorer in `run_eval.py` is. Invoked via
`python -m eval.run_eval --live`; the resulting `PredictionSet` is committed and
scored offline thereafter.

PII discipline: uploads image bytes to MinIO (the designated store) and records
only presence/type/score signals into predictions — never raw field values.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.core.constants import GRAPH_RECURSION_LIMIT
from app.core.logging import get_logger
from app.schemas.enums import Decision, DocumentType

from eval.config import EXPECTED_CLAIM_FIELDS, RETRIEVAL_PROBES, RETRIEVAL_SPOTCHECK_K
from eval.predictions import (
    CasePrediction,
    DocPrediction,
    PredictionSet,
    RetrievalPrediction,
)
from eval.run_eval import group_cases

logger = get_logger(__name__)

# claim-form field aliases → the canonical name used in EXPECTED_CLAIM_FIELDS
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "icd_codes": ("icd_codes", "icd_code"),
    "cpt_codes": ("cpt_codes", "cpt_code"),
    "provider_npi": ("provider_npi",),
    "claim_amount": ("claim_amount", "amount"),
    "service_date": ("service_date", "date"),
}


def _present(fields: dict, canonical: str) -> bool:
    for alias in _FIELD_ALIASES[canonical]:
        val = fields.get(alias)
        if val not in (None, "", [], {}):
            return True
    return False


def _resolve_doc_path(file_path: str) -> Path:
    """Resolve a metadata `file_path` to an existing file.

    metadata.json stores absolute host paths (which exist when the offline CLI
    runs on the host). In a container the dataset lives elsewhere, so remap the
    portion after `dataset/` onto the local dataset root.
    """
    p = Path(file_path)
    if p.exists():
        return p
    from eval.run_eval import _default_metadata_path

    root = _default_metadata_path().parent
    parts = p.parts
    if "dataset" in parts:
        rel = Path(*parts[parts.index("dataset") + 1 :])
        if (root / rel).exists():
            return root / rel
    return root / p.name  # last resort: match by filename


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".pdf": "application/pdf",
    }.get(ext, "image/png")


async def collect_live(records: list[dict]) -> PredictionSet:
    """Run every case bundle through the graph and capture predictions."""
    # Lazy heavy imports so `run_eval` (offline scoring) needs none of this.
    from app.agents.graph import build_pipeline
    from app.agents.wiring import build_deps
    from app.core.config import settings
    from app.ingestion.storage import ObjectStorage
    from app.llm.client import LLMClient
    from app.services.rag_service import RagService
    from langgraph.checkpoint.memory import MemorySaver
    from qdrant_client import QdrantClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    predictions = PredictionSet()
    storage = ObjectStorage()
    qdrant = QdrantClient(url=settings.qdrant_url)

    # Celery runs each task in a fresh event loop; asyncpg connections are
    # loop-bound, so build a task-local engine here rather than reusing the
    # module-level SessionFactory (mirrors worker/tasks.py::_run).
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            llm = LLMClient()
            deps = build_deps(session, llm, storage, qdrant)
            graph = build_pipeline(deps, MemorySaver())

            cases = group_cases(records)
            for i, (case_key, recs) in enumerate(cases.items()):
                # Per-case resilience: a rate-limited (429) or otherwise failing
                # bundle is skipped and logged rather than aborting the whole
                # run — the scorer grades only the cases that were captured.
                try:
                    documents = []
                    for r in recs:
                        path = _resolve_doc_path(r["file_path"])
                        key = f"eval/{case_key}/{r['doc_id']}{path.suffix}"
                        data = await asyncio.to_thread(path.read_bytes)
                        await storage.put(key, data, _content_type(path))
                        documents.append(
                            {"doc_id": r["doc_id"], "storage_key": key, "mime": _content_type(path)}
                        )

                    final: dict[str, Any] = await graph.ainvoke(
                        {"case_id": case_key, "documents": documents, "retry_count": 0},
                        config={
                            "configurable": {"thread_id": case_key},
                            "recursion_limit": GRAPH_RECURSION_LIMIT,
                        },
                    )
                    _absorb_case(predictions, case_key, final)
                except Exception as exc:  # noqa: BLE001 — batch eval: skip + continue
                    predictions.skipped.append(case_key)
                    logger.warning("eval_case_skipped", extra={"case": case_key, "error": str(exc)})

                # Throttle between bundles to respect the gateway rate limit.
                if settings.eval_case_delay_s and i < len(cases) - 1:
                    await asyncio.sleep(settings.eval_case_delay_s)

            predictions.retrieval = await _retrieval_spotcheck(RagService(llm, qdrant))
            await llm.aclose()
    finally:
        await engine.dispose()

    logger.info(
        "eval_collect_done",
        extra={"cases": len(predictions.cases), "documents": len(predictions.documents)},
    )
    return predictions


def _absorb_case(predictions: PredictionSet, case_key: str, final: dict) -> None:
    for d in final.get("documents", []):
        fields = (d.get("content") or {}).get("fields") or {}
        predictions.documents.append(
            DocPrediction(
                doc_id=d["doc_id"],
                predicted_type=DocumentType(d.get("doc_type", DocumentType.UNKNOWN.value)),
                confidence=float(d.get("classify_confidence", 0.0)),
                present_fields=[f for f in EXPECTED_CLAIM_FIELDS if _present(fields, f)],
            )
        )
    kyc = final.get("kyc") or {}
    fraud = final.get("fraud") or {}
    predictions.cases.append(
        CasePrediction(
            case_id=case_key,
            kyc_flags=_kyc_flags(kyc),
            fraud_score=float(fraud.get("fraud_score", 0.0)),
            decision=Decision(final.get("decision") or Decision.ESCALATE.value),
            decision_confidence=float(final.get("decision_confidence", 0.0)),
        )
    )


def _kyc_flags(kyc: dict) -> list[str]:
    """Map the KYC agent's UPPERCASE flags/booleans → metadata edge-flag vocab.

    The pipeline emits `EXPIRED_ID` / `NAME_MISMATCH` / `tamper_suspected`; the
    eval scorer compares against lowercase `expired_id` / `name_mismatch` /
    `tampered_id`. Deriving from the typed booleans avoids a vocabulary drift
    that would otherwise score KYC recall at zero.
    """
    flags: list[str] = []
    if kyc.get("id_expired"):
        flags.append("expired_id")
    if kyc.get("tamper_suspected"):
        flags.append("tampered_id")
    if "NAME_MISMATCH" in (kyc.get("flags") or []):
        flags.append("name_mismatch")
    return flags


async def collect_retrieval_only() -> list[RetrievalPrediction]:
    """Run just the RAG spot-check — no graph pass, no vision calls.

    Used by the standalone "Run retrieval" action: it needs only the LLM client
    (for query embeddings) and Qdrant, so it stays cheap and won't 429 on the
    vision rate limit the way a full pipeline run does.
    """
    from app.core.config import settings
    from app.llm.client import LLMClient
    from app.services.rag_service import RagService
    from qdrant_client import QdrantClient

    llm = LLMClient()
    qdrant = QdrantClient(url=settings.qdrant_url)
    try:
        return await _retrieval_spotcheck(RagService(llm, qdrant))
    finally:
        await llm.aclose()


async def _retrieval_spotcheck(rag: Any) -> list[RetrievalPrediction]:
    """For each probe CPT, retrieve top-k and mark same-plan clauses relevant."""
    out: list[RetrievalPrediction] = []
    for cpt, expected_plan in RETRIEVAL_PROBES:
        try:
            clauses = await rag.retrieve([cpt], [], "", k=RETRIEVAL_SPOTCHECK_K)
        except Exception:  # noqa: BLE001 — spot-check is best-effort, non-fatal
            logger.warning("retrieval_spotcheck_failed", extra={"cpt_probe": "***"})
            continue
        retrieved = [c.section for c in clauses]
        relevant = [c.section for c in clauses if c.plan == expected_plan]
        out.append(RetrievalPrediction(cpt_code=cpt, retrieved=retrieved, relevant=relevant))
    return out

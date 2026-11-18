"""Reset ingested claims data to a freshly-built state.

Removes everything produced by submitting/processing claims — `cases` and their
`documents`, `agent_outputs`, `llm_calls`, `audit_events`, the uploaded files in
MinIO, and the LangGraph checkpoints keyed per case — while **preserving** what a
fresh build already provides: seeded `members` + `claim_history`, `users` (the
bootstrap admin and any accounts), and the Qdrant policy-clause vectors.

Deletes run in FK-safe child→parent order (the child FKs declare no DB-level
`ON DELETE CASCADE`, and a bulk statement wouldn't trigger the ORM relationship
cascade anyway). File purge and checkpoint clearing are best-effort so a wiped DB
is never left half-done by an unreachable MinIO.

Run (inside the stack): `uv run python -m app.db.clear_cases`
Keep the uploaded files:   `uv run python -m app.db.clear_cases --keep-files`
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import configure_logging, get_logger
from app.db.models import AgentOutput, AuditEvent, Case, Document, LLMCall
from app.db.session import SessionFactory
from app.ingestion.storage import ObjectStorage, StorageError

logger = get_logger(__name__)

# LangGraph AsyncPostgresSaver tables (one row set per case thread). The
# `checkpoint_migrations` table is schema-versioning — leave it in place.
_CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


@dataclass
class ClearResult:
    cases: int
    documents: int
    files_removed: int
    files_failed: int
    checkpoints_cleared: bool


async def _clear_checkpoints(session: AsyncSession) -> bool:
    """Best-effort delete of LangGraph checkpoint rows (tables may not exist)."""
    cleared = False
    for table in _CHECKPOINT_TABLES:
        exists = await session.scalar(select(func.to_regclass(f"public.{table}")))
        if exists is None:
            continue
        await session.execute(text(f'DELETE FROM "{table}"'))  # noqa: S608 — fixed allowlist
        cleared = True
    return cleared


async def clear_cases(*, purge_files: bool = True, clear_checkpoints: bool = True) -> ClearResult:
    async with SessionFactory() as session:
        # Capture object keys before the rows go, so MinIO can be purged after.
        storage_keys: list[str] = list(await session.scalars(select(Document.storage_key)))
        n_docs = len(storage_keys)
        n_cases = int(await session.scalar(select(func.count()).select_from(Case)) or 0)

        # Child → parent (agent_outputs/llm_calls reference documents & cases).
        for model in (AgentOutput, LLMCall, AuditEvent, Document, Case):
            await session.execute(delete(model))

        checkpoints_cleared = await _clear_checkpoints(session) if clear_checkpoints else False
        await session.commit()

    removed = failed = 0
    if purge_files and storage_keys:
        storage = ObjectStorage()
        for key in storage_keys:
            try:
                await storage.remove(key)
                removed += 1
            except StorageError as exc:
                failed += 1
                logger.warning(
                    "clear_cases_file_remove_failed", extra={"key": key, "error": str(exc)}
                )

    result = ClearResult(
        cases=n_cases,
        documents=n_docs,
        files_removed=removed,
        files_failed=failed,
        checkpoints_cleared=checkpoints_cleared,
    )
    logger.info("clear_cases_done", extra=vars(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset ingested claims data to a fresh state")
    parser.add_argument(
        "--keep-files", action="store_true", help="leave MinIO objects in place (DB only)"
    )
    parser.add_argument(
        "--keep-checkpoints", action="store_true", help="leave LangGraph checkpoints in place"
    )
    args = parser.parse_args()

    configure_logging()
    result = asyncio.run(
        clear_cases(purge_files=not args.keep_files, clear_checkpoints=not args.keep_checkpoints)
    )
    print(
        f"Cleared {result.cases} case(s), {result.documents} document(s); "
        f"files removed={result.files_removed} failed={result.files_failed}; "
        f"checkpoints_cleared={result.checkpoints_cleared}."
    )


if __name__ == "__main__":
    main()

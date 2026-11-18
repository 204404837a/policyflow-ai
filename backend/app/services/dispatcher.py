"""Pipeline dispatch — enqueue the Celery task (injectable for tests)."""

from __future__ import annotations

from typing import Protocol


class Dispatcher(Protocol):
    def dispatch(self, case_id: str) -> None: ...

    def dispatch_policy(self, storage_key: str, plan: str, filename: str) -> str: ...

    def dispatch_eval(self, limit: int | None, scope: str) -> str: ...


class CeleryDispatcher:
    def dispatch(self, case_id: str) -> None:
        from app.worker.tasks import run_pipeline  # lazy — avoid celery import at API import

        run_pipeline.delay(case_id)

    def dispatch_policy(self, storage_key: str, plan: str, filename: str) -> str:
        """Enqueue policy ingestion; returns the Celery task id for status polling."""
        from app.worker.tasks import ingest_policy  # lazy

        return str(ingest_policy.delay(storage_key, plan, filename).id)

    def dispatch_eval(self, limit: int | None, scope: str) -> str:
        """Enqueue a live eval run; returns the Celery task id for status polling.

        `scope` selects the track-group: "pipeline" drives the full graph pass
        (the 5 coupled tracks); "retrieval" runs only the cheap RAG spot-check.
        """
        from app.worker.tasks import run_eval, run_retrieval_eval  # lazy

        if scope == "retrieval":
            return str(run_retrieval_eval.delay().id)
        return str(run_eval.delay(limit).id)

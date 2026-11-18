"""Celery application — broker/result backend on Redis."""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "policyflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
)

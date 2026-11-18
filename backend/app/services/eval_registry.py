"""Active eval-run registry (Redis-backed).

A single live eval run may be in flight at a time. We record which Celery task
is the "current" run so that:
  * a refreshed dashboard can rediscover an in-flight run and resume polling
    instead of showing an idle board, and
  * a second "Run" click is rejected (409) rather than launching a duplicate,
    concurrent pass over the (rate-limited) dataset.

State lives in Redis (shared across the api replicas + surviving a page reload),
under a short TTL so a crashed run self-heals rather than wedging the button.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis

from app.core.config import settings

_KEY = "policyflow:eval:active_run"
# Long enough to outlast a slow, throttled full run; short enough that a crash
# frees the button on its own.
_TTL_S = 4 * 60 * 60

# Celery states in which the task is still active (not yet resolved).
_ACTIVE_STATES = frozenset({"PENDING", "RECEIVED", "STARTED", "RETRY"})


class EvalRunRegistry:
    """Records/queries the single active eval run. Constructor-injected so it can
    be swapped for a fake in tests (no real Redis needed)."""

    def __init__(self, redis: aioredis.Redis | None = None) -> None:
        self._redis = redis or aioredis.from_url(settings.redis_url, decode_responses=True)

    async def set_active(self, task_id: str, scope: str) -> None:
        await self._redis.set(_KEY, json.dumps({"task_id": task_id, "scope": scope}), ex=_TTL_S)

    async def get_active(self) -> dict[str, str] | None:
        raw = await self._redis.get(_KEY)
        return json.loads(raw) if raw else None

    async def clear(self) -> None:
        await self._redis.delete(_KEY)


def is_active_state(celery_state: str) -> bool:
    """True while a Celery task is unresolved (queued/running/retrying)."""
    return celery_state in _ACTIVE_STATES

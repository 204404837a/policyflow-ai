"""Provider-agnostic LLM access via the LiteLLM proxy.

App code calls this client with a **logical alias** (`vision` / `reasoning` /
`embeddings`) — never a provider SDK or model id (enforced: code-quality §2).
The proxy (OpenAI-compatible) handles routing/fallbacks; here we add tenacity
retry (exp backoff + jitter), a small circuit breaker, and per-call usage
capture routed to an injected `on_call` callback (→ `llm_calls`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import settings
from app.core.constants import (
    BREAKER_FAIL_MAX,
    BREAKER_RESET_S,
    ERROR_TEXT_SNIPPET,
    HTTP_TIMEOUT_S,
    LLM_MAX_ATTEMPTS,
    LLM_RETRY_INITIAL_S,
    LLM_RETRY_MAX_S,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

# Process-wide call pacer: serializes LLM call starts and spaces them by
# settings.llm_min_interval_s so bursts (e.g. the graph's parallel agent
# fan-out) stay under a free-tier tokens/min limit. Shared across all
# LLMClient instances in the process; a no-op when the interval is 0.
_rate_lock = asyncio.Lock()
_last_call_monotonic = 0.0


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delta-seconds form) into a float, if present."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form is not emitted by Groq; ignore it


async def _throttle() -> None:
    interval = settings.llm_min_interval_s
    if interval <= 0:
        return
    global _last_call_monotonic
    async with _rate_lock:
        wait = _last_call_monotonic + interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_monotonic = time.monotonic()


class LLMError(RuntimeError):
    """Base class for LLM-gateway failures."""


class LLMUnavailableError(LLMError):
    """The gateway/model could not serve the request (after retries).

    Carries the gateway status and (for 429s) the provider's rate-limit detail
    and Retry-After hint, so failures are diagnosable in the logs instead of an
    opaque "llm_call_failed" — the 429 body says whether it's requests/min,
    tokens/min, or a daily cap. Rate-limit bodies carry no PII (safe to log).
    """

    def __init__(
        self, message: str, *, status: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class CircuitOpenError(LLMUnavailableError):
    """Requests are short-circuited while the breaker is open."""


@dataclass
class LLMCallRecord:
    """One gateway call's observability record (→ `llm_calls`)."""

    alias: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    case_id: str | None = None
    document_id: str | None = None


OnCall = Callable[[LLMCallRecord], Awaitable[None]]


@dataclass
class CircuitBreaker:
    """Minimal breaker: opens after `fail_max` consecutive failures."""

    fail_max: int = BREAKER_FAIL_MAX
    reset_after_s: float = BREAKER_RESET_S
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    def check(self) -> None:
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at < self.reset_after_s:
            raise CircuitOpenError("LLM circuit breaker is open")
        self._opened_at = None  # cooldown elapsed → half-open (allow a try)

    def on_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.fail_max:
            self._opened_at = time.monotonic()


class LLMClient:
    """Thin async client over the LiteLLM proxy."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        on_call: OnCall | None = None,
        http: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        max_attempts: int = LLM_MAX_ATTEMPTS,
    ) -> None:
        self._base_url = (base_url or settings.litellm_base_url).rstrip("/")
        self._api_key = api_key or settings.litellm_master_key
        self._on_call = on_call
        self._http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        self._breaker = breaker or CircuitBreaker()
        self._max_attempts = max_attempts

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- public API --------------------------------------------------------

    async def chat(
        self,
        alias: str,
        *,
        user: str,
        system: str | None = None,
        image: bytes | None = None,
        image_mime: str = "image/png",
        response_model: type[TModel] | None = None,
        temperature: float = 0.0,
        case_id: str | None = None,
        document_id: str | None = None,
    ) -> TModel | str:
        """Call a chat alias. Returns a validated `response_model` or raw text."""
        messages = self._build_messages(system, user, image, image_mime, response_model)
        body: dict[str, Any] = {
            "model": alias,
            "messages": messages,
            "temperature": temperature,
        }
        if response_model is not None:
            body["response_format"] = {"type": "json_object"}

        data = await self._request("/chat/completions", body, alias, case_id, document_id)
        content: str = data["choices"][0]["message"]["content"]
        if response_model is None:
            return content
        try:
            return response_model.model_validate_json(content)
        except ValueError:
            # tolerate models that wrap JSON in prose/fences
            return response_model.model_validate(json.loads(_extract_json(content)))

    async def embed(
        self,
        texts: list[str],
        *,
        alias: str = "embeddings",
        case_id: str | None = None,
    ) -> list[list[float]]:
        body = {"model": alias, "input": texts}
        data = await self._request("/embeddings", body, alias, case_id, None)
        return [item["embedding"] for item in data["data"]]

    # -- internals ---------------------------------------------------------

    def _build_messages(
        self,
        system: str | None,
        user: str,
        image: bytes | None,
        image_mime: str,
        response_model: type[BaseModel] | None,
    ) -> list[dict[str, Any]]:
        sys_text = system or ""
        if response_model is not None:
            schema = json.dumps(response_model.model_json_schema())
            sys_text = (
                f"{sys_text}\nReturn ONLY a JSON object matching this schema:\n{schema}"
            ).strip()
        messages: list[dict[str, Any]] = []
        if sys_text:
            messages.append({"role": "system", "content": sys_text})
        if image is not None:
            b64 = base64.b64encode(image).decode()
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{image_mime};base64,{b64}"},
                        },
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user})
        return messages

    async def _request(
        self,
        path: str,
        body: dict[str, Any],
        alias: str,
        case_id: str | None,
        document_id: str | None,
    ) -> dict[str, Any]:
        self._breaker.check()
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        started = time.monotonic()
        try:
            data = await self._post_with_retry(path, body, headers)
        except Exception as exc:
            # Any failure trips the breaker; surface a typed error to the caller.
            self._breaker.on_failure()
            # Include the gateway's own message (e.g. the 429 rate-limit detail:
            # requests/min vs tokens/min vs daily cap) so failures are actionable.
            logger.warning(
                "llm_call_failed",
                extra={"alias": alias, "error": type(exc).__name__, "detail": str(exc)},
            )
            raise
        self._breaker.on_success()

        latency_ms = (time.monotonic() - started) * 1000
        await self._record(data, alias, latency_ms, case_id, document_id)
        return data

    async def _post_with_retry(
        self, path: str, body: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=LLM_RETRY_INITIAL_S, max=LLM_RETRY_MAX_S),
            retry=retry_if_exception_type((httpx.TransportError, LLMUnavailableError)),
            reraise=True,
        ):
            with attempt:
                await _throttle()  # pace call starts (incl. retries) under the rate limit
                resp = await self._http.post(url, json=body, headers=headers)
                if resp.status_code in _RETRYABLE_STATUS:
                    retry_after = _parse_retry_after(resp.headers.get("retry-after"))
                    detail = resp.text[:ERROR_TEXT_SNIPPET] if resp.status_code == 429 else ""
                    # Groq tells us exactly how long to wait; honor it so a
                    # per-minute limit clears instead of blind exp-backoff. Cap the
                    # honored wait: a daily-cap 429 (retry-after in hours) must fail
                    # fast, not park the worker — it can't clear within the run.
                    if retry_after and retry_after <= LLM_RETRY_MAX_S:
                        await asyncio.sleep(retry_after)
                    raise LLMUnavailableError(
                        f"gateway {resp.status_code}{f': {detail}' if detail else ''}",
                        status=resp.status_code,
                        retry_after=retry_after,
                    )
                if resp.status_code >= 400:
                    snippet = resp.text[:ERROR_TEXT_SNIPPET]
                    raise LLMError(f"gateway {resp.status_code}: {snippet}")
                return resp.json()
        raise LLMUnavailableError("unreachable")  # pragma: no cover

    async def _record(
        self,
        data: dict[str, Any],
        alias: str,
        latency_ms: float,
        case_id: str | None,
        document_id: str | None,
    ) -> None:
        if self._on_call is None:
            return
        usage = data.get("usage", {}) or {}
        await self._on_call(
            LLMCallRecord(
                alias=alias,
                model=str(data.get("model", alias)),
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
                latency_ms=latency_ms,
                case_id=case_id,
                document_id=document_id,
            )
        )


def _extract_json(text: str) -> str:
    """Best-effort: pull the outermost JSON object out of a text blob."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError("no JSON object found in model response")
    return text[start : end + 1]

from __future__ import annotations

from unittest import mock

import httpx
import pytest
from app.llm.client import (
    CircuitBreaker,
    CircuitOpenError,
    LLMClient,
    LLMUnavailableError,
)
from pydantic import BaseModel


class Out(BaseModel):
    label: str
    score: float


class FakeResp:
    def __init__(
        self, status: int, payload: dict, text: str = "", headers: dict | None = None
    ) -> None:
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


class FakeHTTP:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, url, json=None, headers=None):  # noqa: ANN001
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self) -> None:
        pass


def _chat(content: str, usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "model": "groq/x",
        "usage": usage or {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }


async def test_chat_structured_and_records() -> None:
    records = []

    async def on_call(r):  # noqa: ANN001, ANN202
        records.append(r)

    http = FakeHTTP([FakeResp(200, _chat('{"label":"A","score":0.9}'))])
    client = LLMClient(base_url="http://x", api_key="k", on_call=on_call, http=http)
    out = await client.chat("reasoning", user="hi", response_model=Out)
    assert isinstance(out, Out)
    assert out.label == "A"
    assert records[0].total_tokens == 12
    assert records[0].alias == "reasoning"


async def test_chat_tolerates_fenced_json() -> None:
    http = FakeHTTP([FakeResp(200, _chat('```json\n{"label":"B","score":0.1}\n```'))])
    client = LLMClient(base_url="http://x", http=http)
    out = await client.chat("reasoning", user="hi", response_model=Out)
    assert isinstance(out, Out)
    assert out.label == "B"


async def test_retry_then_success() -> None:
    http = FakeHTTP([FakeResp(503, {}), FakeResp(200, _chat("hello"))])
    client = LLMClient(base_url="http://x", http=http)
    txt = await client.chat("reasoning", user="hi")
    assert txt == "hello"
    assert http.calls == 2


async def test_transport_error_is_retried() -> None:
    http = FakeHTTP([httpx.TransportError("boom"), FakeResp(200, _chat("ok"))])
    client = LLMClient(base_url="http://x", http=http)
    assert await client.chat("reasoning", user="hi") == "ok"


async def test_circuit_opens_after_failures() -> None:
    breaker = CircuitBreaker(fail_max=1, reset_after_s=100)
    http = FakeHTTP([FakeResp(503, {}), FakeResp(503, {})])
    client = LLMClient(base_url="http://x", http=http, breaker=breaker, max_attempts=1)
    with pytest.raises(LLMUnavailableError):
        await client.chat("reasoning", user="hi")
    with pytest.raises(CircuitOpenError):
        await client.chat("reasoning", user="hi")


async def test_429_surfaces_ratelimit_detail_and_honors_retry_after() -> None:
    body = '{"error":{"message":"Rate limit reached: Limit 8000 TPM","type":"tokens"}}'
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    http = FakeHTTP([FakeResp(429, {}, text=body, headers={"retry-after": "2"})])
    client = LLMClient(base_url="http://x", http=http, max_attempts=1)
    with mock.patch("app.llm.client.asyncio.sleep", fake_sleep):
        with pytest.raises(LLMUnavailableError) as ei:
            await client.chat("vision", user="hi")
    err = ei.value
    assert err.status == 429
    assert err.retry_after == 2.0
    assert "Rate limit reached" in str(err)  # provider detail is diagnosable
    assert 2.0 in slept  # honored Retry-After


async def test_embed() -> None:
    payload = {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
    http = FakeHTTP([FakeResp(200, payload)])
    client = LLMClient(base_url="http://x", http=http)
    vecs = await client.embed(["a", "b"])
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]

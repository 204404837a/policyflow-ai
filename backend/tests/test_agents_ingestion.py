from __future__ import annotations

import app.agents.preprocessor as pp
import pytest
from app.agents.classifier import ClassifierAgent, needs_human_review
from app.agents.preprocessor import PreprocessError, PreprocessorAgent
from app.ingestion.ocr import OCRUnavailableError
from app.ingestion.storage import ObjectStorage, ext_for_mime
from app.schemas.agents import ClassifierOutput
from app.schemas.documents import DocumentContent
from app.schemas.enums import DocumentType


class FakeClient:
    def __init__(self, out: object) -> None:
        self._out = out

    async def chat(self, alias: str, **kw: object) -> object:
        return self._out


# ---- classifier ----------------------------------------------------------


async def test_classify_returns_output() -> None:
    out = ClassifierOutput(
        doc_type=DocumentType.CLAIM_FORM, confidence=0.95, routing_tags=["claims"]
    )
    agent = ClassifierAgent(FakeClient(out))  # type: ignore[arg-type]
    res = await agent.classify(b"img")
    assert res.doc_type is DocumentType.CLAIM_FORM
    assert needs_human_review(res) is False


def test_needs_human_review_flags() -> None:
    assert needs_human_review(ClassifierOutput(doc_type=DocumentType.UNKNOWN, confidence=0.99))
    assert needs_human_review(ClassifierOutput(doc_type=DocumentType.CLAIM_FORM, confidence=0.5))


# ---- preprocessor --------------------------------------------------------


async def test_preprocessor_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake_extract(client, data, doc_type, **kw):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] < 2:
            return DocumentContent(raw_text="", fields={})
        return DocumentContent(raw_text="hello", fields={"a": "b"})

    monkeypatch.setattr(pp.vision_extract, "extract_image", fake_extract)
    agent = PreprocessorAgent(client=object())  # type: ignore[arg-type]
    out = await agent.run(DocumentType.CLAIM_FORM, b"img", mime="image/png")
    assert out.raw_text == "hello"
    assert calls["n"] == 2


async def test_preprocessor_escalates_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_extract(client, data, doc_type, **kw):  # noqa: ANN001, ANN202
        return DocumentContent(raw_text="", fields={})

    async def bad_ocr(data):  # noqa: ANN001, ANN202
        raise OCRUnavailableError("no tesseract")

    monkeypatch.setattr(pp.vision_extract, "extract_image", empty_extract)
    monkeypatch.setattr(pp, "ocr_text", bad_ocr)
    agent = PreprocessorAgent(client=object(), max_retries=2)  # type: ignore[arg-type]
    with pytest.raises(PreprocessError):
        await agent.run(DocumentType.CLAIM_FORM, b"img", mime="image/png")


# ---- storage -------------------------------------------------------------


class FakeMinio:
    def __init__(self) -> None:
        self.puts: list = []
        self.buckets = {"policyflow"}

    def bucket_exists(self, b: str) -> bool:
        return b in self.buckets

    def make_bucket(self, b: str) -> None:
        self.buckets.add(b)

    def put_object(self, bucket, key, stream, length, content_type):  # noqa: ANN001, ANN201
        self.puts.append((bucket, key, length, content_type))

    def get_object(self, bucket, key):  # noqa: ANN001, ANN201
        class R:
            def read(self_inner) -> bytes:  # noqa: ANN001
                return b"data"

            def close(self_inner) -> None:  # noqa: ANN001
                pass

            def release_conn(self_inner) -> None:  # noqa: ANN001
                pass

        return R()

    def presigned_get_object(self, bucket, key, expires):  # noqa: ANN001, ANN201
        return f"http://minio/{key}"


async def test_storage_put_get_presign() -> None:
    m = FakeMinio()
    s = ObjectStorage(client=m, bucket="policyflow")
    key = ObjectStorage.key("c1", "d1", "png")
    assert key == "raw/c1/d1.png"
    await s.put(key, b"xyz", "image/png")
    assert m.puts[0][1] == key
    assert m.puts[0][2] == 3
    assert await s.get(key) == b"data"
    assert (await s.presign_get(key)).endswith(key)


def test_ext_for_mime() -> None:
    assert ext_for_mime("image/png") == "png"
    assert ext_for_mime("application/pdf") == "pdf"
    assert ext_for_mime("image/tiff") == "tiff"

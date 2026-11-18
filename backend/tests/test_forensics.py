"""ELA tamper-detection tests (services/image_forensics.py) + KYC wiring.

Synthesises clean vs spliced images in-memory (no dataset dependency) and
asserts the error-level score separates them, then checks the KYC agent turns
an upstream `tamper_suspected` signal into a fail-closed flag.
"""

from __future__ import annotations

import io

import pytest
from app.agents.kyc import KYCAgent
from app.services.image_forensics import ForensicsError, ImageForensics
from PIL import Image
from tests.test_specialists import FakeMembers, _member


def _noise_image(seed: int = 1) -> Image.Image:
    # Deterministic pseudo-photo content so JPEG has real error to measure.
    img = Image.new("RGB", (128, 128))
    px = img.load()
    assert px is not None
    v = seed
    for y in range(128):
        for x in range(128):
            v = (v * 1103515245 + 12345) & 0x7FFFFFFF
            px[x, y] = (v & 255, (v >> 8) & 255, (v >> 16) & 255)
    return img


def _jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_ela_score_in_unit_range() -> None:
    score = ImageForensics().ela_score(_jpeg_bytes(_noise_image(), quality=90))
    assert 0.0 <= score <= 1.0


def test_tampered_region_scores_higher_than_clean() -> None:
    forensics = ImageForensics()
    base = _noise_image(seed=7)
    clean_bytes = _jpeg_bytes(base, quality=50)

    # Splice a pristine (never-JPEG-50) high-contrast patch onto the base.
    tampered = Image.open(io.BytesIO(clean_bytes)).convert("RGB")
    patch = _noise_image(seed=99).crop((0, 0, 48, 48))
    tampered.paste(patch, (40, 40))

    clean_score = forensics.ela_score(clean_bytes)
    tampered_score = forensics.ela_score(_png_bytes(tampered))
    assert tampered_score > clean_score


def test_undecodable_input_raises() -> None:
    with pytest.raises(ForensicsError):
        ImageForensics().ela_score(b"definitely not an image")


def test_threshold_gates_is_tampered() -> None:
    # A forensics instance with threshold 0.0 flags everything; 1.1 flags nothing.
    data = _jpeg_bytes(_noise_image(), quality=80)
    assert ImageForensics(threshold=0.0).is_tampered(data) is True
    assert ImageForensics(threshold=1.1).is_tampered(data) is False


async def test_kyc_tamper_signal_blocks_approve() -> None:
    agent = KYCAgent(FakeMembers(_member()))
    out = await agent.run(
        {
            "member_id": "PT_1",
            "policy_number": "MED-GLD-1",
            "name": "John Johnson X.",
            "tamper_suspected": True,
        }
    )
    assert out.tamper_suspected is True
    assert "TAMPER_SUSPECTED" in out.flags
    assert out.id_valid is False
    assert out.kyc_passed is False

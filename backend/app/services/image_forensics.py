"""Image forensics — Error Level Analysis (ELA) tamper detection.

A genuine JPEG photo recompresses with roughly uniform error; a spliced/edited
region carries a different compression history and recompresses with a *different*
error level. ELA resaves at a known quality, diffs against the original, and reads
a robust high-percentile of the per-pixel error. A localized spike ⇒ tampering.

Heuristic and fail-closed by design: a high score *raises suspicion* (→ KYC
`tamper_suspected` → ESCALATE/REJECT), but ELA never *clears* an ID — absence of a
spike is not proof of authenticity. Pure/injectable (SRP, code-quality §5).
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, UnidentifiedImageError

from app.core.constants import (
    ELA_JPEG_QUALITY,
    ELA_TAMPER_PERCENTILE,
    ELA_TAMPER_THRESHOLD,
)


class ForensicsError(ValueError):
    """The input could not be decoded as an image for analysis."""


class ImageForensics:
    def __init__(
        self,
        *,
        quality: int = ELA_JPEG_QUALITY,
        percentile: float = ELA_TAMPER_PERCENTILE,
        threshold: float = ELA_TAMPER_THRESHOLD,
    ) -> None:
        self._quality = quality
        self._percentile = percentile
        self._threshold = threshold

    def ela_score(self, data: bytes) -> float:
        """Normalized (0–1) high-percentile recompression error for an image.

        Raises `ForensicsError` if `data` is not a decodable image.
        """
        try:
            original = Image.open(io.BytesIO(data)).convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise ForensicsError("input is not a decodable image") from exc

        buffer = io.BytesIO()
        original.save(buffer, format="JPEG", quality=self._quality)
        buffer.seek(0)
        recompressed = Image.open(buffer).convert("RGB")

        diff = ImageChops.difference(original, recompressed).convert("L")
        return self._high_percentile_error(diff)

    def is_tampered(self, data: bytes) -> bool:
        """True if the ELA score clears the tamper threshold."""
        return self.ela_score(data) >= self._threshold

    def _high_percentile_error(self, diff: Image.Image) -> float:
        """The error value at `percentile` of the pixel distribution, in 0–1.

        Robust to single-pixel outliers (unlike a raw max) but sensitive to a
        sizeable tampered region.
        """
        histogram = diff.histogram()  # 256 bins over the grayscale error
        total = sum(histogram)
        if total == 0:
            return 0.0
        allowed_above = total * (1.0 - self._percentile)
        running = 0
        for level in range(255, -1, -1):
            running += histogram[level]
            if running >= allowed_above:
                return level / 255.0
        return 0.0

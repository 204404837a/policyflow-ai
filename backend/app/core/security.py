"""Upload validation + PII masking (edge-of-system controls).

- Magic-byte validation (via `filetype`, no libmagic system dep).
- File-size guard.
- Masking helpers for logs + UI list views (docs/DATA_HANDLING.md).
"""

from __future__ import annotations

from typing import Any

import filetype

from app.core.constants import ALLOWED_MIME_TYPES, MAX_FILE_BYTES, SENSITIVE_FIELDS


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails type/size validation."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_upload(filename: str, data: bytes) -> str:
    """Validate an uploaded file by magic bytes and size.

    Args:
        filename: original client filename (advisory only — not trusted).
        data: raw file bytes.

    Returns:
        The detected MIME type.

    Raises:
        UploadValidationError: on size overflow (413) or disallowed type (400).
    """
    if len(data) > MAX_FILE_BYTES:
        raise UploadValidationError(
            f"File exceeds maximum of {MAX_FILE_BYTES // (1024 * 1024)} MB.",
            status_code=413,
        )
    kind = filetype.guess(data)
    mime = kind.mime if kind else None
    if mime not in ALLOWED_MIME_TYPES:
        raise UploadValidationError(
            f"Unsupported file type {mime!r}. Allowed: JPEG, PNG, PDF, TIFF."
        )
    return mime


# ---- PII masking ---------------------------------------------------------


def mask_value(key: str, value: Any) -> Any:
    """Mask a single value if its key is sensitive; otherwise return as-is."""
    if value is None or key.lower() not in SENSITIVE_FIELDS:
        return value
    s = str(value)
    if key.lower() in {"member_id", "patient_id"}:
        return f"{s[:3]}***{s[-2:]}" if len(s) > 5 else "***"
    if key.lower() in {"dob", "date_of_birth"}:
        return "****"
    if key.lower() == "ssn":
        return "***-**-####"
    # generic: keep first char, redact the rest
    return f"{s[:1]}***" if s else "***"


def mask_pii(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of `payload` with sensitive fields masked.

    Use for structured log `extra` and UI list serializers. Full values are
    revealed only in the authorized case-detail view.
    """
    return {k: mask_value(k, v) for k, v in payload.items()}

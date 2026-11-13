from __future__ import annotations

import mimetypes
import re
import unicodedata

from app.config import Settings

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
MAX_NAME_LENGTH = 120


class UploadValidationError(ValueError):
    """Raised for invalid filenames, extensions or sizes."""


def sanitize_filename(filename: str) -> str:
    name = unicodedata.normalize("NFKC", filename or "").strip()
    name = name.replace("\\", "/").split("/")[-1]  # strip any path components
    name = _SAFE_CHARS.sub("_", name).lstrip("._")
    if not name:
        raise UploadValidationError("Filename is empty after sanitization")
    return name[:MAX_NAME_LENGTH]


def validate_upload(filename: str, size: int, settings: Settings) -> str:
    """Validate and normalize an upload; returns the sanitized filename."""
    if not filename or not filename.strip():
        raise UploadValidationError("A file is required")
    if size <= 0:
        raise UploadValidationError("Uploaded file is empty")
    if size > settings.max_upload_bytes:
        raise UploadValidationError(
            f"File exceeds the {settings.max_upload_mb} MB upload limit"
        )
    name = sanitize_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not ext or ext not in settings.allowed_ext_set:
        raise UploadValidationError(
            f"File type '.{ext}' is not allowed. Allowed: {', '.join(sorted(settings.allowed_ext_set))}"
        )
    return name


def guess_mimetype(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"

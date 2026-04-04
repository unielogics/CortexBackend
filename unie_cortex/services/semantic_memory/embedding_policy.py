"""Truncate, redact, and hash text before embedding."""

from __future__ import annotations

import hashlib
import re

_ZIP_US = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def redact_basic_pii(text: str) -> str:
    """Best-effort redaction before sending text to an external embedding API."""
    s = _ZIP_US.sub("[ZIP]", text)
    s = _EMAIL.sub("[EMAIL]", s)
    return s


_TRUNC_SUFFIX = "\n...[truncated]"


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    sl = len(_TRUNC_SUFFIX)
    if max_chars <= sl:
        return text[:max_chars]
    return text[: max_chars - sl] + _TRUNC_SUFFIX


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

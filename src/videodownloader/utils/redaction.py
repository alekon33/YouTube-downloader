"""Redaction helpers used before technical text is logged or displayed."""

from __future__ import annotations

import re

_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.IGNORECASE)
_COOKIE_FLAG = re.compile(r"(--cookies(?:-from-browser)?\s+)(\S+)", re.IGNORECASE)


def redact_sensitive_text(text: str) -> str:
    """Remove query strings and cookie locations from diagnostic text."""

    text = _URL_QUERY.sub(r"\1?[redacted]", text)
    return _COOKIE_FLAG.sub(r"\1[redacted]", text)

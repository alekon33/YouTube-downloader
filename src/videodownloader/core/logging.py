"""Application logging with rotation and basic secret redaction."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from videodownloader.utils.redaction import redact_sensitive_text


class SensitiveDataFilter(logging.Filter):
    """Remove common URL query parameters and cookie paths from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact_sensitive_text(message)
        record.args = ()
        return True


def configure_logging(logs_dir: Path) -> Path:
    """Configure a bounded UTF-8 application log and return its path."""

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "videodownloader.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    return log_path

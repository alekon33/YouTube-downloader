"""Scheduling policy for external-tool update checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from videodownloader.models import AppSettings


def update_check_due(settings: AppSettings, now: datetime | None = None) -> bool:
    """Rate-limit automatic checks while allowing the first one immediately."""

    if not settings.check_tool_updates:
        return False
    current = now or datetime.now(UTC)
    if not settings.last_yt_dlp_check:
        return True
    try:
        last_check = datetime.fromisoformat(settings.last_yt_dlp_check)
        if last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=UTC)
    except ValueError:
        return True
    return current - last_check >= timedelta(hours=settings.update_check_interval_hours)

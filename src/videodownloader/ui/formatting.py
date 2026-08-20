"""Localized formatting helpers for metadata and download telemetry."""

from __future__ import annotations


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "Длительность неизвестна"
    hours, remainder = divmod(seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "Б" else f"{int(size)} {unit}"
        size /= 1024
    return "—"


def format_eta(seconds: int | None) -> str:
    if seconds is None:
        return "осталось —"
    minutes, remaining_seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"осталось {hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"осталось {minutes:02d}:{remaining_seconds:02d}"


"""Conversion of yt-dlp JSON into stable application models."""

from __future__ import annotations

from typing import Any

from videodownloader.core.exceptions import MetadataError
from videodownloader.models import MediaItem, MediaKind


def parse_metadata(payload: dict[str, Any], source_url: str) -> MediaItem:
    """Normalize yt-dlp's extractor-specific JSON into a compact domain model."""

    title = str(payload.get("title") or payload.get("fulltitle") or "Без названия")
    raw_entries = payload.get("entries")
    is_playlist = payload.get("_type") in {"playlist", "multi_video"} or isinstance(
        raw_entries, list
    )
    if is_playlist:
        entries = tuple(
            _parse_entry(entry, source_url)
            for entry in (raw_entries or [])
            if isinstance(entry, dict)
        )
        count = _as_int(payload.get("playlist_count")) or _as_int(payload.get("n_entries"))
        if count is None and entries:
            count = len(entries)
        return MediaItem(
            source_url=source_url,
            title=title,
            kind=MediaKind.PLAYLIST,
            media_id=_optional_string(payload.get("id")),
            item_count=count,
            extractor=_optional_string(payload.get("extractor_key") or payload.get("extractor")),
            entries=entries,
        )
    return _parse_video(payload, source_url)


def _parse_entry(payload: dict[str, Any], fallback_url: str) -> MediaItem:
    entry_url = str(payload.get("webpage_url") or payload.get("url") or fallback_url)
    return _parse_video(payload, entry_url)


def _parse_video(payload: dict[str, Any], source_url: str) -> MediaItem:
    title = str(payload.get("title") or payload.get("fulltitle") or "Без названия")
    heights: set[int] = set()
    estimated_sizes: list[int] = []
    formats = payload.get("formats") or []
    if not isinstance(formats, list):
        raise MetadataError("Не удалось прочитать форматы видео.", "formats is not a list")
    for media_format in formats:
        if not isinstance(media_format, dict):
            continue
        height = _as_int(media_format.get("height"))
        if height:
            heights.add(height)
        size = _as_int(media_format.get("filesize")) or _as_int(
            media_format.get("filesize_approx")
        )
        if size:
            estimated_sizes.append(size)
    direct_size = _as_int(payload.get("filesize")) or _as_int(payload.get("filesize_approx"))
    return MediaItem(
        source_url=source_url,
        title=title,
        kind=MediaKind.VIDEO,
        media_id=_optional_string(payload.get("id")),
        duration_seconds=_as_int(payload.get("duration")),
        available_heights=tuple(sorted(heights, reverse=True)),
        estimated_bytes=direct_size or (max(estimated_sizes) if estimated_sizes else None),
        extractor=_optional_string(payload.get("extractor_key") or payload.get("extractor")),
    )


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None

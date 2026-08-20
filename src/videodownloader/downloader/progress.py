"""Parser for the machine-readable progress templates emitted by yt-dlp."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videodownloader.models import DownloadProgress, DownloadStage


class ProgressParser:
    """Convert stable marker lines into progress snapshots."""

    def __init__(self) -> None:
        self.final_path: Path | None = None
        self._last_filename: str | None = None
        self._last_playlist_index: int | None = None
        self._stream_number = 0

    def parse(self, line: str) -> DownloadProgress | None:
        line = line.strip()
        marker_position = line.find("VDP_")
        if marker_position < 0:
            return None
        fields = line[marker_position:].split("\t")
        marker = fields[0]
        if marker == "VDP_PROGRESS" and len(fields) >= 10:
            return self._parse_download(fields)
        if marker == "VDP_POSTPROCESS":
            index = _integer(fields, 2)
            count = _integer(fields, 3)
            return DownloadProgress(
                stage=DownloadStage.POST_PROCESSING,
                percent=100,
                overall_percent=_overall_percent(index, count, 100),
                playlist_index=index,
                playlist_count=count,
                message=_string(fields, 4) or "Объединение дорожек",
            )
        if marker == "VDP_FINISHED" and len(fields) >= 2:
            filename = _string(fields, 1)
            if filename:
                self.final_path = Path(filename)
            index = _integer(fields, 2)
            count = _integer(fields, 3)
            return DownloadProgress(
                stage=DownloadStage.COMPLETED,
                percent=100,
                overall_percent=_overall_percent(index, count, 100) or 100,
                playlist_index=index,
                playlist_count=count,
                filename=filename,
            )
        return None

    def _parse_download(self, fields: list[str]) -> DownloadProgress:
        downloaded = _integer(fields, 2)
        total = _integer(fields, 3) or _integer(fields, 4)
        speed = _float(fields, 5)
        eta = _integer(fields, 6)
        index = _integer(fields, 7)
        count = _integer(fields, 8)
        filename = _string(fields, 9)
        if index is not None and index != self._last_playlist_index:
            self._stream_number = 0
            self._last_filename = None
            self._last_playlist_index = index
        if filename and filename != self._last_filename:
            self._stream_number += 1
            self._last_filename = filename
        percent = None
        if downloaded is not None and total:
            percent = min(100.0, downloaded / total * 100)
        stage = DownloadStage.AUDIO if self._stream_number > 1 else DownloadStage.VIDEO
        return DownloadProgress(
            stage=stage,
            percent=percent,
            overall_percent=_overall_percent(index, count, percent),
            downloaded_bytes=downloaded,
            total_bytes=total,
            speed_bytes_per_second=speed,
            eta_seconds=eta,
            playlist_index=index,
            playlist_count=count,
            filename=filename,
        )


def _json_value(raw: str) -> Any:
    if raw in {"", "NA", "null", "None"}:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _integer(fields: list[str], index: int) -> int | None:
    if index >= len(fields):
        return None
    value = _json_value(fields[index])
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _float(fields: list[str], index: int) -> float | None:
    if index >= len(fields):
        return None
    value = _json_value(fields[index])
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _string(fields: list[str], index: int) -> str | None:
    if index >= len(fields):
        return None
    value = _json_value(fields[index])
    return str(value) if value is not None else None


def _overall_percent(index: int | None, count: int | None, percent: float | None) -> float | None:
    if index is None or count is None or count <= 0 or percent is None:
        return percent
    return min(100.0, ((index - 1) + percent / 100) / count * 100)

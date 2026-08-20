"""Safe subprocess boundary for the standalone yt-dlp executable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from videodownloader.core.exceptions import MetadataError, ToolUnavailableError
from videodownloader.downloader.metadata import parse_metadata
from videodownloader.models import MediaItem


class YtDlpService:
    """Analyze media through a standalone yt-dlp child process."""

    def __init__(self, executable: Path, ffmpeg_directory: Path) -> None:
        self.executable = executable
        self.ffmpeg_directory = ffmpeg_directory

    def analysis_arguments(self, url: str) -> list[str]:
        self._validate_url(url)
        return [
            str(self.executable),
            "--ignore-config",
            "--no-warnings",
            "--dump-single-json",
            "--skip-download",
            "--ffmpeg-location",
            str(self.ffmpeg_directory),
            "--",
            url,
        ]

    def analyze(self, url: str, timeout_seconds: int = 120) -> MediaItem:
        if not self.executable.is_file():
            raise ToolUnavailableError(
                "Компонент yt-dlp не найден.", f"Missing executable: {self.executable}"
            )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                self.analysis_arguments(url),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
                shell=False,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as error:
            raise MetadataError(
                "Анализ ссылки занял слишком много времени.", str(error)
            ) from error
        except OSError as error:
            raise MetadataError(
                "Не удалось запустить компонент анализа.", str(error)
            ) from error
        if result.returncode != 0:
            raise MetadataError(
                "Не удалось получить информацию о видео.",
                result.stderr.strip() or f"yt-dlp exited with code {result.returncode}",
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise MetadataError(
                "yt-dlp вернул некорректные данные.", str(error)
            ) from error
        if not isinstance(payload, dict):
            raise MetadataError("Не удалось прочитать данные видео.", "JSON root is not an object")
        return parse_metadata(payload, url)

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MetadataError(
                "Введите корректную ссылку, начинающуюся с http:// или https://.",
                "Invalid media URL",
            )


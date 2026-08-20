"""Safe subprocess boundary for the standalone yt-dlp executable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from videodownloader.core.exceptions import MetadataError, ToolUnavailableError
from videodownloader.downloader.arguments import browser_cookie_arguments
from videodownloader.downloader.metadata import parse_metadata
from videodownloader.models import CookieBrowser, MediaItem
from videodownloader.utils.redaction import redact_sensitive_text


class YtDlpService:
    """Analyze media through a standalone yt-dlp child process."""

    def __init__(
        self,
        executable: Path,
        ffmpeg_directory: Path,
        javascript_runtime: Path | None = None,
        cookie_browser: CookieBrowser | None = None,
    ) -> None:
        self.executable = executable
        self.ffmpeg_directory = ffmpeg_directory
        self.javascript_runtime = javascript_runtime
        self.cookie_browser = cookie_browser

    def analysis_arguments(self, url: str) -> list[str]:
        self._validate_url(url)
        arguments = [
            str(self.executable),
            "--ignore-config",
            "--no-warnings",
            "--dump-single-json",
            "--skip-download",
            "--flat-playlist",
            "--no-playlist",
            "--ffmpeg-location",
            str(self.ffmpeg_directory),
        ]
        if self.javascript_runtime is not None:
            arguments.extend(
                [
                    "--js-runtimes",
                    f"deno:{self.javascript_runtime}",
                    "--remote-components",
                    "ejs:github",
                ]
            )
        arguments.extend(browser_cookie_arguments(self.cookie_browser))
        arguments.extend(["--", url])
        return arguments

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
            detail = redact_sensitive_text(
                result.stderr.strip() or f"yt-dlp exited with code {result.returncode}"
            )
            raise MetadataError(
                _friendly_metadata_error(detail, self.cookie_browser),
                detail,
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


def _friendly_metadata_error(
    detail: str, cookie_browser: CookieBrowser | None
) -> str:
    lowered = detail.casefold()
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        if cookie_browser is None:
            return (
                "YouTube запросил подтверждение. Выберите браузер, в котором выполнен "
                "вход в YouTube, в поле «Авторизация YouTube» и повторите анализ."
            )
        return (
            f"YouTube не принял авторизацию из {cookie_browser.label}. Убедитесь, что в "
            "этом браузере выполнен вход в YouTube, и повторите анализ."
        )
    if (
        "cookie" in lowered
        and any(token in lowered for token in ("could not copy", "permission denied"))
    ) or any(token in lowered for token in ("failed to decrypt", "dpapi", "v20")):
        return (
            "Не удалось прочитать cookies выбранного браузера. Закройте браузер и "
            "повторите попытку либо попробуйте Mozilla Firefox."
        )
    return "Не удалось получить информацию о видео."

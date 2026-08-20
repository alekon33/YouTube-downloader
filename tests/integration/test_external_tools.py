"""Opt-in smoke tests for real standalone tools and a maintainer-owned URL."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from videodownloader.downloader import DownloadExecutor, YtDlpService
from videodownloader.models import Container, DownloadJob, DownloadOptions, Quality

pytestmark = pytest.mark.integration


def required_executable(variable: str) -> Path:
    """Return a configured executable or skip the integration suite safely."""

    raw_path = os.environ.get(variable)
    if not raw_path:
        pytest.skip(f"Set {variable} to run external-tool integration tests")
    path = Path(raw_path)
    if not path.is_file():
        pytest.fail(f"{variable} does not point to a file: {path}")
    return path


def required_url() -> str:
    """Require an explicitly selected, legally downloadable test resource."""

    url = os.environ.get("VIDEODOWNLOADER_INTEGRATION_URL")
    if not url:
        pytest.skip("Set VIDEODOWNLOADER_INTEGRATION_URL to a maintainer-owned media URL")
    return url


def test_standalone_tools_report_versions() -> None:
    yt_dlp = required_executable("VIDEODOWNLOADER_YTDLP")
    ffmpeg_dir = Path(os.environ.get("VIDEODOWNLOADER_FFMPEG_DIR", ""))
    ffmpeg = ffmpeg_dir / "ffmpeg.exe"
    if not ffmpeg.is_file():
        pytest.skip("Set VIDEODOWNLOADER_FFMPEG_DIR to a directory containing ffmpeg.exe")

    yt_result = subprocess.run(
        [str(yt_dlp), "--version"], capture_output=True, text=True, check=False, timeout=15
    )
    ffmpeg_result = subprocess.run(
        [str(ffmpeg), "-version"], capture_output=True, text=True, check=False, timeout=15
    )

    assert yt_result.returncode == 0
    assert yt_result.stdout.strip()
    assert ffmpeg_result.returncode == 0
    assert ffmpeg_result.stdout.startswith("ffmpeg version ")


def test_real_url_can_be_analyzed() -> None:
    yt_dlp = required_executable("VIDEODOWNLOADER_YTDLP")
    ffmpeg_dir = Path(os.environ.get("VIDEODOWNLOADER_FFMPEG_DIR", yt_dlp.parent))

    media = YtDlpService(yt_dlp, ffmpeg_dir).analyze(required_url())

    assert media.title
    assert media.source_url.startswith(("http://", "https://"))


def test_real_media_can_be_downloaded(tmp_path: Path) -> None:
    yt_dlp = required_executable("VIDEODOWNLOADER_YTDLP")
    ffmpeg_dir = Path(os.environ.get("VIDEODOWNLOADER_FFMPEG_DIR", ""))
    if not (ffmpeg_dir / "ffmpeg.exe").is_file():
        pytest.skip("Set VIDEODOWNLOADER_FFMPEG_DIR to a directory containing ffmpeg.exe")
    service = YtDlpService(yt_dlp, ffmpeg_dir)
    media = service.analyze(required_url())
    job = DownloadJob(
        media=media,
        options=DownloadOptions(
            destination=tmp_path,
            quality=Quality.LOW_360,
            container=Container.MP4,
        ),
    )
    events = []

    result = DownloadExecutor(yt_dlp, ffmpeg_dir).execute(job, events.append)

    assert result is not None
    assert result.is_file()
    assert events

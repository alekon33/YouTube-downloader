from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from videodownloader.models import AppSettings
from videodownloader.services.tool_updates import update_check_due
from videodownloader.tools.releases import YtDlpReleaseClient, parse_latest_release


def test_parse_official_release_asset() -> None:
    asset, page = parse_latest_release(
        {
            "tag_name": "2026.08.19",
            "html_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19",
            "assets": [
                {
                    "name": "yt-dlp.exe",
                    "browser_download_url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.exe",
                    "digest": f"sha256:{'a' * 64}",
                }
            ],
        }
    )

    assert asset.version == "2026.08.19"
    assert asset.sha256 == "a" * 64
    assert page.endswith("2026.08.19")


def test_update_comparison_handles_date_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = YtDlpReleaseClient()
    asset, page = parse_latest_release(
        {
            "tag_name": "2026.08.19",
            "html_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19",
            "assets": [
                {
                    "name": "yt-dlp.exe",
                    "browser_download_url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.exe",
                    "digest": f"sha256:{'b' * 64}",
                }
            ],
        }
    )
    monkeypatch.setattr(client, "latest_asset", lambda: (asset, page))

    assert client.check("2026.08.18") is not None
    assert client.check("2026.08.19") is None


def test_update_check_is_rate_limited() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    recent = now - timedelta(hours=2)
    settings = AppSettings(destination=Path("downloads"), last_yt_dlp_check=recent.isoformat())

    assert not update_check_due(settings, now)

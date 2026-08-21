"""Persistent application settings model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from videodownloader.models.download import Container, CookieBrowser, Quality


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Settings persisted outside the installation directory."""

    destination: Path
    quality: Quality = Quality.FHD_1080
    container: Container = Container.MP4
    audio_only: bool = False
    cookie_browser: CookieBrowser | None = None
    create_playlist_folder: bool = True
    number_playlist_items: bool = True
    use_download_archive: bool = True
    check_tool_updates: bool = True
    update_check_interval_hours: int = 24
    last_yt_dlp_check: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["destination"] = str(self.destination)
        data["quality"] = self.quality.value
        data["container"] = self.container.value
        data["cookie_browser"] = (
            self.cookie_browser.value if self.cookie_browser is not None else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_destination: Path) -> AppSettings:
        """Load known values while safely ignoring settings from newer versions."""

        interval = int(data.get("update_check_interval_hours", 24))
        raw_cookie_browser = data.get("cookie_browser")
        raw_audio_only = data.get("audio_only", False)
        try:
            cookie_browser = (
                CookieBrowser(raw_cookie_browser) if isinstance(raw_cookie_browser, str) else None
            )
        except ValueError:
            cookie_browser = None
        return cls(
            destination=Path(data.get("destination") or default_destination),
            quality=Quality(data.get("quality", Quality.FHD_1080.value)),
            container=Container(data.get("container", Container.MP4.value)),
            audio_only=raw_audio_only if isinstance(raw_audio_only, bool) else False,
            cookie_browser=cookie_browser,
            create_playlist_folder=bool(data.get("create_playlist_folder", True)),
            number_playlist_items=bool(data.get("number_playlist_items", True)),
            use_download_archive=bool(data.get("use_download_archive", True)),
            check_tool_updates=bool(data.get("check_tool_updates", True)),
            update_check_interval_hours=max(1, interval),
            last_yt_dlp_check=data.get("last_yt_dlp_check"),
        )

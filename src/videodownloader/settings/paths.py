"""Windows-friendly application data paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    """All writable paths used by the application."""

    data_dir: Path
    config_dir: Path
    logs_dir: Path
    tools_dir: Path
    downloads_dir: Path

    @classmethod
    def discover(cls) -> AppPaths:
        """Resolve per-user paths without relying on the executable location."""

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            data_dir = Path(local_app_data) / "VideoDownloader"
            downloads_dir = Path.home() / "Downloads"
        else:
            data_dir = Path.home() / ".local" / "share" / "VideoDownloader"
            downloads_dir = Path.home() / "Downloads"
        return cls.from_data_dir(data_dir, downloads_dir)

    @classmethod
    def from_data_dir(cls, data_dir: Path, downloads_dir: Path | None = None) -> AppPaths:
        """Create paths rooted at an explicit directory, primarily for tests."""

        return cls(
            data_dir=data_dir,
            config_dir=data_dir / "config",
            logs_dir=data_dir / "logs",
            tools_dir=data_dir / "tools",
            downloads_dir=downloads_dir or data_dir / "downloads",
        )

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.config_dir, self.logs_dir, self.tools_dir):
            directory.mkdir(parents=True, exist_ok=True)


"""Atomic JSON persistence for application settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from videodownloader.models.settings import AppSettings
from videodownloader.settings.paths import AppPaths


class SettingsService:
    """Load and save user settings without writing beside the executable."""

    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths
        self._settings_path = paths.config_dir / "settings.json"

    @property
    def settings_path(self) -> Path:
        return self._settings_path

    def defaults(self) -> AppSettings:
        return AppSettings(destination=self._paths.downloads_dir)

    def load(self) -> AppSettings:
        if not self._settings_path.exists():
            return self.defaults()
        try:
            payload: Any = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return self.defaults()
            return AppSettings.from_dict(payload, self._paths.downloads_dir)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self.defaults()

    def save(self, settings: AppSettings) -> None:
        self._paths.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_suffix(".json.tmp")
        serialized = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
        temporary.write_text(serialized + "\n", encoding="utf-8")
        os.replace(temporary, self._settings_path)


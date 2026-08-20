"""Application composition root."""

from __future__ import annotations

from videodownloader.core.logging import configure_logging
from videodownloader.settings import AppPaths, SettingsService


def bootstrap_services() -> tuple[AppPaths, SettingsService]:
    """Create foundational services shared by CLI-free application entry points."""

    paths = AppPaths.discover()
    paths.ensure_directories()
    configure_logging(paths.logs_dir)
    return paths, SettingsService(paths)


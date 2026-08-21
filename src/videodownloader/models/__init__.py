"""Typed domain models shared by services and the user interface."""

from videodownloader.models.download import (
    Container,
    CookieBrowser,
    DownloadJob,
    DownloadOptions,
    DownloadProgress,
    DownloadStage,
    JobState,
    MediaItem,
    MediaKind,
    PlaylistJob,
    Quality,
)
from videodownloader.models.playlist import (
    PlaylistInterval,
    normalize_playlist_intervals,
    parse_playlist_intervals,
)
from videodownloader.models.settings import AppSettings

__all__ = [
    "AppSettings",
    "Container",
    "CookieBrowser",
    "DownloadJob",
    "DownloadOptions",
    "DownloadProgress",
    "DownloadStage",
    "JobState",
    "MediaItem",
    "MediaKind",
    "PlaylistInterval",
    "PlaylistJob",
    "Quality",
    "normalize_playlist_intervals",
    "parse_playlist_intervals",
]

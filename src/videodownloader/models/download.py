"""Domain models for media analysis and download jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4


class Quality(StrEnum):
    """Maximum video quality selected by the user."""

    BEST = "best"
    UHD_2160 = "2160"
    QHD_1440 = "1440"
    FHD_1080 = "1080"
    HD_720 = "720"
    SD_480 = "480"
    LOW_360 = "360"

    @property
    def label(self) -> str:
        return "Best" if self is Quality.BEST else f"{self.value}p"


class Container(StrEnum):
    """Preferred final media container."""

    MP4 = "mp4"
    MKV = "mkv"


class CookieBrowser(StrEnum):
    """Browsers whose authenticated cookies yt-dlp can read on demand."""

    FIREFOX = "firefox"
    EDGE = "edge"
    CHROME = "chrome"
    BRAVE = "brave"
    VIVALDI = "vivaldi"
    OPERA = "opera"
    CHROMIUM = "chromium"

    @property
    def label(self) -> str:
        return {
            CookieBrowser.FIREFOX: "Mozilla Firefox",
            CookieBrowser.EDGE: "Microsoft Edge",
            CookieBrowser.CHROME: "Google Chrome",
            CookieBrowser.BRAVE: "Brave",
            CookieBrowser.VIVALDI: "Vivaldi",
            CookieBrowser.OPERA: "Opera",
            CookieBrowser.CHROMIUM: "Chromium",
        }[self]


class MediaKind(StrEnum):
    """Kind of media object returned by yt-dlp."""

    VIDEO = "video"
    PLAYLIST = "playlist"


class JobState(StrEnum):
    """High-level application state for a job."""

    IDLE = "idle"
    ANALYZING = "analyzing"
    READY = "ready"
    DOWNLOADING = "downloading"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DownloadStage(StrEnum):
    """Detailed stage shown while a download is active."""

    ANALYZING = "analyzing"
    VIDEO = "video"
    AUDIO = "audio"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class MediaItem:
    """Metadata about one video or a playlist."""

    source_url: str
    title: str
    kind: MediaKind
    media_id: str | None = None
    duration_seconds: int | None = None
    item_count: int | None = None
    available_heights: tuple[int, ...] = ()
    estimated_bytes: int | None = None
    extractor: str | None = None
    entries: tuple[MediaItem, ...] = ()

    @property
    def is_playlist(self) -> bool:
        return self.kind is MediaKind.PLAYLIST


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    """User-controlled options from which yt-dlp arguments are built."""

    destination: Path
    quality: Quality = Quality.FHD_1080
    container: Container = Container.MP4
    cookie_browser: CookieBrowser | None = None
    playlist_start: int | None = None
    playlist_end: int | None = None
    create_playlist_folder: bool = True
    number_playlist_items: bool = True
    use_download_archive: bool = True

    def __post_init__(self) -> None:
        if self.playlist_start is not None and self.playlist_start < 1:
            raise ValueError("Начало диапазона должно быть не меньше 1.")
        if self.playlist_end is not None and self.playlist_end < 1:
            raise ValueError("Конец диапазона должен быть не меньше 1.")
        if (
            self.playlist_start is not None
            and self.playlist_end is not None
            and self.playlist_start > self.playlist_end
        ):
            raise ValueError("Начало диапазона не может быть больше конца.")


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    """A stable snapshot whose playlist fields refer to the selected download queue."""

    stage: DownloadStage
    percent: float | None = None
    overall_percent: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed_bytes_per_second: float | None = None
    eta_seconds: int | None = None
    playlist_index: int | None = None
    playlist_count: int | None = None
    filename: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.percent is not None and not 0 <= self.percent <= 100:
            raise ValueError("Progress percentage must be between 0 and 100.")
        if self.overall_percent is not None and not 0 <= self.overall_percent <= 100:
            raise ValueError("Overall percentage must be between 0 and 100.")


@dataclass(slots=True)
class DownloadJob:
    """Mutable lifecycle state for a single media download."""

    media: MediaItem
    options: DownloadOptions
    job_id: UUID = field(default_factory=uuid4)
    state: JobState = JobState.READY
    error_detail: str | None = None


@dataclass(slots=True)
class PlaylistJob(DownloadJob):
    """Download job with playlist-specific selection state."""

    selected_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.media.is_playlist:
            raise ValueError("PlaylistJob requires playlist metadata.")
        if any(index < 1 for index in self.selected_indices):
            raise ValueError("Playlist indices are one-based.")

"""Portable playlist checkpoints contain source identities, never stream URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from videodownloader.models.download import CookieBrowser, DownloadOptions, MediaItem, MediaKind


@dataclass(slots=True)
class SavedPlaylistItem:
    original_index: int
    source_url: str
    media_id: str | None
    extractor: str | None
    title: str
    output_stem: str
    completed_file: str | None = None
    completed_size: int | None = None
    completed_mtime_ns: int | None = None

    @property
    def completed(self) -> bool:
        return self.completed_file is not None


@dataclass(slots=True)
class SavedPlaylist:
    """A selected, ordered snapshot anchored to its selected folder on restore."""

    folder: Path
    session_id: str
    source_url: str
    title: str
    original_count: int
    options: DownloadOptions
    items: list[SavedPlaylistItem]
    runtime_items: tuple[SavedPlaylistItem, ...] = field(default=(), repr=False)

    @property
    def completed_count(self) -> int:
        return sum(item.completed for item in self.items)

    @property
    def pending_items(self) -> tuple[SavedPlaylistItem, ...]:
        return tuple(item for item in self.items if not item.completed)

    def download_options(self, browser: CookieBrowser | None = None) -> DownloadOptions:
        from dataclasses import replace

        return replace(
            self.options,
            destination=self.folder,
            cookie_browser=browser,
            create_playlist_folder=False,
        )

    def media(self) -> MediaItem:
        return MediaItem(
            self.source_url,
            self.title,
            MediaKind.PLAYLIST,
            item_count=self.original_count,
            entries=tuple(
                MediaItem(
                    i.source_url,
                    i.title,
                    MediaKind.VIDEO,
                    media_id=i.media_id,
                    extractor=i.extractor,
                    playlist_index=i.original_index,
                )
                for i in self.items
            ),
        )

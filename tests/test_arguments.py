from pathlib import Path

from videodownloader.downloader import (
    build_download_arguments,
    playlist_output_template,
    quality_expression,
)
from videodownloader.models import (
    Container,
    DownloadJob,
    DownloadOptions,
    MediaItem,
    MediaKind,
    PlaylistJob,
    Quality,
)


def test_quality_expression_limits_video_height() -> None:
    expression = quality_expression(Quality.FHD_1080, Container.MP4)

    assert "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]" in expression
    assert "best[height<=1080]" in expression


def test_best_quality_has_no_height_filter() -> None:
    assert "height" not in quality_expression(Quality.BEST, Container.MKV)


def test_playlist_naming_scales_width() -> None:
    media = MediaItem(
        source_url="https://example.test/list",
        title="Large list",
        kind=MediaKind.PLAYLIST,
        item_count=12_345,
    )

    assert playlist_output_template(media, True) == "%(playlist_index)05d - %(title)s.%(ext)s"


def test_playlist_arguments_include_range_archive_and_folder(tmp_path: Path) -> None:
    media = MediaItem(
        source_url="https://example.test/list",
        title="List",
        kind=MediaKind.PLAYLIST,
        item_count=20,
    )
    job = DownloadJob(
        media=media,
        options=DownloadOptions(destination=tmp_path, playlist_start=5, playlist_end=12),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--playlist-start") + 1] == "5"
    assert arguments[arguments.index("--playlist-end") + 1] == "12"
    assert "--download-archive" in arguments
    assert "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s" in arguments


def test_selected_playlist_indices_override_range(tmp_path: Path) -> None:
    media = MediaItem("https://example.test/list", "List", MediaKind.PLAYLIST, item_count=20)
    job = PlaylistJob(
        media=media,
        options=DownloadOptions(destination=tmp_path, playlist_start=5, playlist_end=12),
        selected_indices=(1, 3, 9),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--playlist-items") + 1] == "1,3,9"
    assert "--playlist-start" not in arguments


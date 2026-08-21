from pathlib import Path

from videodownloader.downloader import (
    build_download_arguments,
    playlist_output_template,
    quality_expression,
)
from videodownloader.downloader.arguments import (
    FINISHED_TEMPLATE,
    POSTPROCESS_TEMPLATE,
    PROGRESS_TEMPLATE,
)
from videodownloader.models import (
    Container,
    CookieBrowser,
    DownloadJob,
    DownloadOptions,
    MediaItem,
    MediaKind,
    PlaylistInterval,
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
    assert arguments[arguments.index("--download-archive") + 1].endswith(
        "videodownloader-archive.txt"
    )
    assert "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s" in arguments


def test_playlist_progress_templates_use_selected_download_queue() -> None:
    assert "%(info.playlist_autonumber)j" in PROGRESS_TEMPLATE
    assert "%(info.n_entries)j" in PROGRESS_TEMPLATE
    assert "%(info.playlist_index)j" not in PROGRESS_TEMPLATE
    assert "%(info.playlist_count)j" not in PROGRESS_TEMPLATE

    assert "%(info.playlist_autonumber)j" in POSTPROCESS_TEMPLATE
    assert "%(info.n_entries)j" in POSTPROCESS_TEMPLATE
    assert "%(info.playlist_index)j" not in POSTPROCESS_TEMPLATE
    assert "%(info.playlist_count)j" not in POSTPROCESS_TEMPLATE

    assert "%(playlist_autonumber)j" in FINISHED_TEMPLATE
    assert "%(n_entries)j" in FINISHED_TEMPLATE
    assert "%(playlist_index)j" not in FINISHED_TEMPLATE
    assert "%(playlist_count)j" not in FINISHED_TEMPLATE


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


def test_playlist_intervals_use_inclusive_yt_dlp_item_spec(tmp_path: Path) -> None:
    media = MediaItem("https://example.test/list", "List", MediaKind.PLAYLIST, item_count=20)
    job = DownloadJob(
        media=media,
        options=DownloadOptions(
            destination=tmp_path,
            playlist_intervals=(
                PlaylistInterval(1, 5),
                PlaylistInterval(8, 12),
                PlaylistInterval(20, 20),
            ),
        ),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--playlist-items") + 1] == "1:5,8:12,20"
    assert "--playlist-start" not in arguments
    assert "--playlist-end" not in arguments


def test_selected_playlist_indices_override_intervals(tmp_path: Path) -> None:
    media = MediaItem("https://example.test/list", "List", MediaKind.PLAYLIST, item_count=20)
    job = PlaylistJob(
        media=media,
        options=DownloadOptions(
            destination=tmp_path,
            playlist_intervals=(PlaylistInterval(5, 12),),
        ),
        selected_indices=(2, 7),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--playlist-items") + 1] == "2,7"


def test_download_arguments_use_managed_deno_runtime(tmp_path: Path) -> None:
    media = MediaItem("https://example.test/video", "Video", MediaKind.VIDEO)
    job = DownloadJob(media=media, options=DownloadOptions(destination=tmp_path))
    deno = tmp_path / "deno.exe"

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job, deno)

    assert arguments[arguments.index("--js-runtimes") + 1] == f"deno:{deno}"
    assert arguments[arguments.index("--remote-components") + 1] == "ejs:github"
    assert arguments[arguments.index("--merge-output-format") + 1] == "mp4"
    assert "--extract-audio" not in arguments


def test_download_arguments_use_explicit_browser_cookies(tmp_path: Path) -> None:
    media = MediaItem("https://example.test/video", "Video", MediaKind.VIDEO)
    job = DownloadJob(
        media=media,
        options=DownloadOptions(
            destination=tmp_path,
            cookie_browser=CookieBrowser.EDGE,
        ),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--cookies-from-browser") + 1] == "edge"


def test_audio_only_arguments_create_best_quality_mp3(tmp_path: Path) -> None:
    media = MediaItem("https://example.test/video", "Video", MediaKind.VIDEO)
    job = DownloadJob(
        media=media,
        options=DownloadOptions(
            destination=tmp_path,
            quality=Quality.LOW_360,
            container=Container.MKV,
            audio_only=True,
        ),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--format") + 1] == "bestaudio/best"
    assert "--extract-audio" in arguments
    assert arguments[arguments.index("--audio-format") + 1] == "mp3"
    assert arguments[arguments.index("--audio-quality") + 1] == "0"
    assert "--merge-output-format" not in arguments
    assert "height" not in arguments[arguments.index("--format") + 1]


def test_audio_playlist_uses_separate_archive_and_keeps_range(tmp_path: Path) -> None:
    media = MediaItem(
        "https://example.test/list",
        "List",
        MediaKind.PLAYLIST,
        item_count=20,
    )
    job = DownloadJob(
        media=media,
        options=DownloadOptions(
            destination=tmp_path,
            audio_only=True,
            playlist_start=5,
            playlist_end=12,
        ),
    )

    arguments = build_download_arguments(tmp_path / "yt-dlp.exe", tmp_path, job)

    assert arguments[arguments.index("--playlist-start") + 1] == "5"
    assert arguments[arguments.index("--playlist-end") + 1] == "12"
    assert arguments[arguments.index("--download-archive") + 1].endswith(
        "videodownloader-audio-archive.txt"
    )
    assert "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s" in arguments

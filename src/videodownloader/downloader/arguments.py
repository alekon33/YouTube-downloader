"""Pure yt-dlp download argument construction."""

from __future__ import annotations

from pathlib import Path

from videodownloader.models import Container, CookieBrowser, DownloadJob, MediaItem, Quality

PROGRESS_TEMPLATE = (
    "download:VDP_PROGRESS\t%(progress.status)j\t%(progress.downloaded_bytes)j\t"
    "%(progress.total_bytes)j\t%(progress.total_bytes_estimate)j\t%(progress.speed)j\t"
    "%(progress.eta)j\t%(info.playlist_index)j\t%(info.playlist_count)j\t"
    "%(progress.filename)j"
)
POSTPROCESS_TEMPLATE = (
    "postprocess:VDP_POSTPROCESS\t%(progress.status)j\t%(info.playlist_index)j\t"
    "%(info.playlist_count)j\t%(progress.postprocessor)j"
)
FINISHED_TEMPLATE = "after_move:VDP_FINISHED\t%(filepath)j\t%(playlist_index)j\t%(playlist_count)j"


def browser_cookie_arguments(browser: CookieBrowser | None) -> list[str]:
    """Return an explicit opt-in argument for reading cookies from a browser."""

    return ["--cookies-from-browser", browser.value] if browser is not None else []


def quality_expression(quality: Quality, container: Container) -> str:
    """Prefer separate best streams while retaining a combined-format fallback."""

    limit = "" if quality is Quality.BEST else f"[height<={quality.value}]"
    if container is Container.MP4:
        return (
            f"bestvideo{limit}[ext=mp4]+bestaudio[ext=m4a]/"
            f"best{limit}[ext=mp4]/bestvideo{limit}+bestaudio/best{limit}"
        )
    return f"bestvideo{limit}+bestaudio/best{limit}"


def playlist_output_template(media: MediaItem, number_items: bool) -> str:
    """Build a playlist filename with a width that scales beyond 999 entries."""

    width = max(3, len(str(media.item_count or 999)))
    prefix = f"%(playlist_index)0{width}d - " if number_items else ""
    return f"{prefix}%(title)s.%(ext)s"


def build_download_arguments(
    executable: Path,
    ffmpeg_directory: Path,
    job: DownloadJob,
    javascript_runtime: Path | None = None,
) -> list[str]:
    """Translate a job into an argument vector; the UI never handles CLI details."""

    options = job.options
    media = job.media
    output = "%(title)s.%(ext)s"
    if media.is_playlist:
        output = playlist_output_template(media, options.number_playlist_items)
        if options.create_playlist_folder:
            output = f"%(playlist_title)s/{output}"

    arguments = [
        str(executable),
        "--ignore-config",
        "--no-warnings",
        "--newline",
        "--progress",
        "--progress-template",
        PROGRESS_TEMPLATE,
        "--progress-template",
        POSTPROCESS_TEMPLATE,
        "--print",
        FINISHED_TEMPLATE,
        "--output-na-placeholder",
        "null",
        "--windows-filenames",
        "--trim-filenames",
        "180",
        "--continue",
        "--no-overwrites",
        "--ffmpeg-location",
        str(ffmpeg_directory),
        "--paths",
        str(options.destination),
        "--output",
        output,
        "--format",
        quality_expression(options.quality, options.container),
        "--merge-output-format",
        options.container.value,
    ]

    if media.is_playlist:
        arguments.append("--yes-playlist")
        selected = getattr(job, "selected_indices", ())
        if selected:
            arguments.extend(["--playlist-items", ",".join(str(item) for item in selected)])
        else:
            if options.playlist_start is not None:
                arguments.extend(["--playlist-start", str(options.playlist_start)])
            if options.playlist_end is not None:
                arguments.extend(["--playlist-end", str(options.playlist_end)])
        if options.use_download_archive:
            arguments.extend(
                ["--download-archive", str(options.destination / "videodownloader-archive.txt")]
            )
    else:
        arguments.append("--no-playlist")

    if javascript_runtime is not None:
        arguments.extend(
            [
                "--js-runtimes",
                f"deno:{javascript_runtime}",
                "--remote-components",
                "ejs:github",
            ]
        )

    arguments.extend(browser_cookie_arguments(options.cookie_browser))

    arguments.extend(["--", media.source_url])
    return arguments

import json
import os
import shutil
from pathlib import Path

import pytest

from videodownloader.core.exceptions import DownloadError
from videodownloader.downloader import DownloadExecutor
from videodownloader.downloader.arguments import build_download_arguments
from videodownloader.models import (
    CookieBrowser,
    DownloadJob,
    DownloadOptions,
    DownloadProgress,
    DownloadStage,
    MediaItem,
    MediaKind,
    PlaylistInterval,
)
from videodownloader.services.playlist_lock import PlaylistFolderLock
from videodownloader.services.playlist_sessions import (
    ARCHIVE_FILE,
    QUEUE_FILE,
    SESSION_FILE,
    PlaylistSessions,
)


def make_session(tmp_path: Path):
    media = MediaItem(
        "https://example.test/list",
        "Course",
        MediaKind.PLAYLIST,
        item_count=3,
        entries=tuple(
            MediaItem(
                f"https://example.test/{i}",
                f"Video {i}",
                MediaKind.VIDEO,
                media_id=str(i),
                extractor="Generic",
                playlist_index=i,
            )
            for i in (1, 2, 3)
        ),
    )
    options = DownloadOptions(
        tmp_path,
        playlist_intervals=(PlaylistInterval(1, 1), PlaylistInterval(3, 3)),
        cookie_browser=CookieBrowser.FIREFOX,
    )
    return PlaylistSessions.create(media, options)


def test_snapshot_preserves_selection_and_does_not_store_credentials(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    data = json.loads((session.folder / SESSION_FILE).read_text(encoding="utf-8"))
    assert [i["index"] for i in data["items"]] == [1, 3]
    assert [i["stem"] for i in data["items"]] == ["001 - Video 1", "003 - Video 3"]
    assert "cookie" not in json.dumps(data).lower()
    assert "firefox" not in json.dumps(data).lower()
    restored = PlaylistSessions.load(session.folder)
    assert restored.options.cookie_browser is None
    assert restored.options.destination == session.folder
    assert not restored.options.create_playlist_folder


def test_saved_positions_are_not_skipped_by_id_only_archive(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    assert session.options.use_download_archive
    PlaylistSessions.prepare(session)
    job = DownloadJob(session.media(), session.download_options(), playlist_session=session)
    args = build_download_arguments(Path("yt-dlp.exe"), Path("tools"), job)
    assert "--load-info-json" in args
    assert "--download-archive" not in args


def test_complete_files_survive_folder_move_and_missing_files_rejoin_queue(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    PlaylistSessions.prepare(session)
    first = session.folder / "001 - Video 1.mp4"
    first.write_bytes(b"finished media")
    PlaylistSessions.record_completed(session, 1, str(first))
    moved = tmp_path / "moved"
    shutil.copytree(session.folder, moved)
    restored = PlaylistSessions.load(moved)
    assert restored.completed_count == 1
    PlaylistSessions.prepare(restored)
    assert [i.original_index for i in restored.runtime_items] == [3]
    queue = json.loads((moved / QUEUE_FILE).read_text(encoding="utf-8"))
    assert queue["requested_entries"] == [3]
    assert queue["entries"][0]["url"] == "https://example.test/3"
    assert "generic 1" in (moved / ARCHIVE_FILE).read_text()
    (moved / "001 - Video 1.mp4").unlink()
    missing = PlaylistSessions.load(moved)
    assert missing.completed_count == 0
    PlaylistSessions.prepare(missing)
    assert (moved / ARCHIVE_FILE).read_text() == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("stem", "../escape"),
        ("stem", "C:\\outside"),
        ("url", "file:///secret"),
        ("url", "https://user:pass@example.test/video"),
        ("file", "../other.mp4"),
        ("index", True),
    ],
)
def test_untrusted_saved_paths_and_urls_are_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    session = make_session(tmp_path)
    path = session.folder / SESSION_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][0][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DownloadError):
        PlaylistSessions.load(session.folder)


def test_changed_or_unconfirmed_files_are_not_overwritten(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    PlaylistSessions.prepare(session)
    first = session.folder / "001 - Video 1.mp4"
    first.write_bytes(b"first")
    with pytest.raises(DownloadError) as error:
        PlaylistSessions.load(session.folder)
    assert "не подтверждено" in error.value.user_message
    PlaylistSessions.record_completed(session, 1, str(first))
    first.write_bytes(b"changed, unrelated file")
    with pytest.raises(DownloadError) as error:
        PlaylistSessions.load(session.folder)
    assert "изменён" in error.value.user_message
    assert first.read_bytes() == b"changed, unrelated file"


def test_completion_is_saved_after_final_marker_and_progress_uses_original_queue(
    tmp_path: Path,
) -> None:
    session = make_session(tmp_path)
    PlaylistSessions.prepare(session)
    first = session.folder / "001 - Video 1.mp4"
    first.write_bytes(b"finished")
    job = DownloadJob(session.media(), session.download_options(), playlist_session=session)
    processed = DownloadExecutor._session_progress(
        DownloadProgress(DownloadStage.POST_PROCESSING, percent=100, playlist_index=1), job
    )
    assert session.completed_count == 0
    assert processed.playlist_count == 2
    DownloadExecutor._session_progress(
        DownloadProgress(
            DownloadStage.COMPLETED, percent=100, playlist_index=1, filename=str(first)
        ),
        job,
    )
    assert PlaylistSessions.load(session.folder).completed_count == 1
    PlaylistSessions.prepare(session)
    progress = DownloadExecutor._session_progress(
        DownloadProgress(DownloadStage.VIDEO, percent=50, playlist_index=1), job
    )
    assert progress.playlist_index == 2
    assert progress.playlist_count == 2
    assert progress.overall_percent == 75


def test_folder_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    with (
        PlaylistFolderLock(tmp_path),
        pytest.raises(DownloadError) as error,
        PlaylistFolderLock(tmp_path),
    ):
        pytest.fail("must not enter")
    assert "уже используется" in error.value.user_message
    with PlaylistFolderLock(tmp_path):
        pass


def test_existing_checkpoint_is_not_replaced_by_different_job(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    original = (session.folder / SESSION_FILE).read_bytes()
    media = session.media()
    options = DownloadOptions(
        tmp_path, audio_only=True, playlist_intervals=session.options.playlist_intervals
    )
    with pytest.raises(DownloadError) as error:
        PlaylistSessions.create(media, options)
    assert "другое задание" in error.value.user_message
    assert (session.folder / SESSION_FILE).read_bytes() == original


def test_partial_file_hardlinks_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = make_session(tmp_path)
    outside = tmp_path / "other-data"
    outside.write_bytes(b"must not be changed")
    part = session.folder / "001 - Video 1.mp4.part"
    part.write_bytes(b"partial")
    original_stat = Path.stat

    def linked_stat(path: Path, *args: object, **kwargs: object):
        result = original_stat(path, *args, **kwargs)
        if path == part:
            fields = list(result)
            fields[3] = 2
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", linked_stat)
    with pytest.raises(DownloadError):
        PlaylistSessions.load(session.folder)
    assert outside.read_bytes() == b"must not be changed"


def test_empty_corrupt_or_future_checkpoint_reports_error(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    path = session.folder / SESSION_FILE
    for content in ("", "{", '{"schema_version": 99}', '{"schema_version": true}'):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(DownloadError):
            PlaylistSessions.load(session.folder)


def test_failed_checkpoint_write_keeps_previous_json_and_pending_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videodownloader.services import playlist_sessions

    session = make_session(tmp_path)
    PlaylistSessions.prepare(session)
    previous = (session.folder / SESSION_FILE).read_bytes()
    first = session.folder / "001 - Video 1.mp4"
    first.write_bytes(b"finished")

    def fail_replace(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(playlist_sessions.os, "replace", fail_replace)
    with pytest.raises(OSError):
        PlaylistSessions.record_completed(session, 1, str(first))
    assert session.completed_count == 0
    assert (session.folder / SESSION_FILE).read_bytes() == previous
    assert not list(session.folder.glob("*.tmp"))

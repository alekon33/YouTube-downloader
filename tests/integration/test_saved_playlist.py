"""A new executor restores only disk state, including relocated partial files."""

import io
import os
import time
import wave
from pathlib import Path

import psutil
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot
from test_resume_local import RunningJob, executor_and_job, media_server

from videodownloader.core.exceptions import DownloadCancelled
from videodownloader.downloader import DownloadExecutor
from videodownloader.models import (
    DownloadJob,
    DownloadOptions,
    DownloadProgress,
    JobState,
    MediaItem,
    MediaKind,
    PlaylistInterval,
    Quality,
)
from videodownloader.services.playlist_sessions import SESSION_FILE, PlaylistSessions
from videodownloader.settings import AppPaths, SettingsService
from videodownloader.tools import ToolManager
from videodownloader.ui import AppController, MainWindow

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("audio_only", [False, True])
def test_restore_saved_selection_after_cancel_and_folder_move(
    tmp_path: Path, audio_only: bool
) -> None:
    if not os.environ.get("VIDEODOWNLOADER_YTDLP"):
        pytest.skip("Set VIDEODOWNLOADER_YTDLP for real saved-playlist tests")
    with media_server() as server:
        executable, _ = executor_and_job(tmp_path, server)
        if audio_only:
            audio = io.BytesIO()
            with wave.open(audio, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(b"\x00\x00" * (48000 * 60))
            server.payload = audio.getvalue()
            server.extension, server.content_type = "wav", "audio/wav"
        else:
            server.payload *= 2
        media = MediaItem(
            server.url.replace("sample", "playlist"),
            "Saved course",
            MediaKind.PLAYLIST,
            item_count=3,
            entries=tuple(
                MediaItem(
                    server.url.replace("sample", str(i)),
                    f"Original title {i}",
                    MediaKind.VIDEO,
                    media_id=str(i),
                    extractor="Generic",
                    playlist_index=i,
                )
                for i in (1, 2, 3)
            ),
        )
        session = PlaylistSessions.create(
            media,
            DownloadOptions(
                tmp_path,
                quality=Quality.BEST,
                audio_only=audio_only,
                playlist_intervals=(PlaylistInterval(1, 1), PlaylistInterval(3, 3)),
            ),
        )
        job = DownloadJob(media, session.download_options(), playlist_session=session)
        assert (session.folder / SESSION_FILE).is_file()
        with RunningJob(executable, job) as run:
            deadline = time.monotonic() + 25
            while (
                time.monotonic() < deadline
                and not run.errors
                and not any(
                    p.playlist_index == 2
                    and p.downloaded_bytes
                    and p.downloaded_bytes >= 128 * 1024
                    for p in run.snapshots
                )
            ):
                time.sleep(0.02)
            assert not run.errors, run.errors
            assert session.completed_count == 1
            assert executable._process is not None
            root = psutil.Process(executable._process.pid)
            owned = [root, *root.children(recursive=True)]
            executable.cancel()
            run.thread.join(10)
            assert len(run.errors) == 1 and isinstance(run.errors[0], DownloadCancelled)
            _, alive = psutil.wait_procs(owned, timeout=3)
            assert not alive
        extension = "mp3" if audio_only else "mp4"
        first = session.folder / f"001 - Original title 1.{extension}"
        assert first.is_file()
        first_size, first_time = first.stat().st_size, first.stat().st_mtime_ns
        assert list(session.folder.glob("*.part"))
        moved = tmp_path / "relocated"
        session.folder.rename(moved)
        restored = PlaylistSessions.load(moved)
        assert restored.completed_count == 1
        assert restored.options.audio_only == audio_only
        before = len(server.requests)
        new_executor = DownloadExecutor(
            executable.executable, executable.ffmpeg_directory, retry_delay=0.1
        )
        snapshots = []
        result = new_executor.execute(
            DownloadJob(restored.media(), restored.download_options(), playlist_session=restored),
            snapshots.append,
        )
        assert result is not None
        assert PlaylistSessions.load(moved).completed_count == 2
        first = moved / first.name
        assert (first.stat().st_size, first.stat().st_mtime_ns) == (first_size, first_time)
        assert all(path != f"/1.{server.extension}" for path, _ in server.requests[before:])
        assert any(
            path == f"/3.{server.extension}" and offset > 0
            for path, offset in server.requests[before:]
        )
        assert (moved / f"003 - Original title 3.{extension}").is_file()
        assert not (moved / "Saved course").exists()
        assert snapshots[0].overall_percent == 50
        assert snapshots[-1].overall_percent == 100
        assert not list(moved.glob("*.part"))
        if not audio_only:
            assert first.read_bytes() == server.payload
            assert (moved / f"003 - Original title 3.{extension}").read_bytes() == server.payload


def test_window_creates_checkpoint_and_new_window_restores_repeated_video(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise both real Qt workers and the folder button, with duplicate IDs."""
    with media_server() as server:
        executor, _ = executor_and_job(tmp_path, server)
        server.payload *= 2
        paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
        settings = SettingsService(paths)
        tools = ToolManager(executor.ffmpeg_directory)
        controller = AppController(paths, tools)
        window = MainWindow(controller, settings, auto_prepare=False)
        qtbot.addWidget(window)
        window.show()
        # The same URL/ID occurs at two distinct selected positions. A CLI
        # archive must not skip the second file just because the first is ready.
        media = MediaItem(
            server.url.replace("sample", "playlist"),
            "GUI course",
            MediaKind.PLAYLIST,
            item_count=3,
            entries=tuple(
                MediaItem(
                    server.url.replace("sample", "1" if i == 3 else str(i)),
                    f"GUI title {i}",
                    MediaKind.VIDEO,
                    media_id="1" if i == 3 else str(i),
                    extractor="Generic",
                    playlist_index=i,
                )
                for i in (1, 2, 3)
            ),
        )
        window._set_state(JobState.ANALYZING)
        window._analysis_complete(media)
        window._folder.setText(str(paths.downloads_dir))
        window._set_combo_data(window._quality, Quality.BEST)
        window._playlist_intervals.setText("1, 3")
        progress: list[DownloadProgress] = []
        errors: list[object] = []
        controller.download_progress.connect(progress.append)
        controller.download_failed.connect(errors.append)
        try:
            qtbot.mouseClick(window._download, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(
                lambda: (
                    bool(errors)
                    or any(
                        p.playlist_index == 2 and (p.downloaded_bytes or 0) >= 128 * 1024
                        for p in progress
                    )
                ),
                timeout=30000,
            )
            assert not errors, errors
            folder = paths.downloads_dir / "GUI course"
            assert PlaylistSessions.load(folder).completed_count == 1
            worker = controller._download_worker
            assert worker is not None and worker.executor._process is not None
            root = psutil.Process(worker.executor._process.pid)
            owned = [root, *root.children(recursive=True)]
            with qtbot.waitSignal(controller.download_cancelled, timeout=10000):
                window._cancel_download()
            qtbot.waitUntil(lambda: not controller._threads, timeout=5000)
            _, alive = psutil.wait_procs(owned, timeout=3)
            assert not alive
        finally:
            controller.cancel_download()
            qtbot.waitUntil(lambda: not controller._threads, timeout=10000)
            window._explicit_exit = True
            window._state.reset()
            window.close()
        first = folder / "001 - GUI title 1.mp4"
        first_stat = first.stat()
        before = len(server.requests)
        restored_controller = AppController(paths, tools)
        restored_window = MainWindow(restored_controller, settings, auto_prepare=False)
        qtbot.addWidget(restored_window)
        restored_window.show()
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        restored_controller.download_failed.connect(errors.append)
        try:
            with qtbot.waitSignal(restored_controller.download_succeeded, timeout=30000):
                qtbot.mouseClick(restored_window._restore_playlist, Qt.MouseButton.LeftButton)
            assert not errors, errors
            assert restored_window._state.state is JobState.COMPLETED
            assert restored_window._overall_progress.value() == 100
            assert PlaylistSessions.load(folder).completed_count == 2
            assert (first.stat().st_size, first.stat().st_mtime_ns) == (
                first_stat.st_size,
                first_stat.st_mtime_ns,
            )
            assert (folder / "003 - GUI title 3.mp4").read_bytes() == server.payload
            assert any(path == "/1.mp4" and offset > 0 for path, offset in server.requests[before:])
        finally:
            restored_controller.cancel_download()
            qtbot.waitUntil(lambda: not restored_controller._threads, timeout=10000)
            restored_window._explicit_exit = True
            restored_window._state.reset()
            restored_window.close()

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from test_playlist_sessions import make_session
from videodownloader.models import CookieBrowser, JobState
from videodownloader.services.playlist_sessions import PlaylistSessions
from videodownloader.settings import AppPaths, SettingsService
from videodownloader.ui import AppController, MainWindow


def test_folder_restore_loads_original_options_and_resumes_without_analysis(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session(tmp_path)
    PlaylistSessions.prepare(session)
    first = session.folder / "001 - Video 1.mp4"
    first.write_bytes(b"ready")
    PlaylistSessions.record_completed(session, 1, str(first))
    session = PlaylistSessions.load(session.folder)
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    controller = AppController(paths)
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window, before_close_func=lambda w: w._state.reset())
    window.show()
    restored: list[Path] = []
    resumed: list[tuple[object, CookieBrowser | None]] = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(session.folder))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(controller, "restore_playlist", restored.append)
    monkeypatch.setattr(
        controller, "resume_playlist", lambda value, browser: resumed.append((value, browser))
    )
    monkeypatch.setattr(
        controller, "analyze", lambda *args: pytest.fail("must not reanalyse live playlist")
    )
    qtbot.mouseClick(window._restore_playlist, Qt.MouseButton.LeftButton)
    assert restored == [session.folder]
    assert window._state.state is JobState.ANALYZING
    controller.playlist_restored.emit(session)
    assert window._state.state is JobState.READY
    assert "готово 1 из 2" in window._media_details.text()
    assert window._folder.text() == str(session.folder)
    assert not window._folder.isEnabled()
    assert not window._quality.isEnabled()
    assert not window._playlist_intervals.isEnabled()
    assert window._cookie_browser.currentData() is None
    assert window._download.text() == "Продолжить плейлист"
    assert window._overall_progress.value() == 50
    window.resize(660, 560)
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.is_file() and QFontDatabase.addApplicationFont(str(font)) >= 0:
        window.setFont(QFont("Segoe UI", 10))
    qtbot.wait(30)
    window.grab().save(str(tmp_path / "restored-window.png"))
    qtbot.mouseClick(window._download, Qt.MouseButton.LeftButton)
    assert resumed == [(session, None)]
    assert window._state.state is JobState.DOWNLOADING
    assert not window._restore_playlist.isEnabled()
    assert window._overall_progress.value() == 50
    window._set_state(JobState.CANCELLED)
    qtbot.mouseClick(window._new_download, Qt.MouseButton.LeftButton)
    assert window._state.state is JobState.IDLE
    assert window._playlist_session is None
    assert window._quality.isEnabled()


def test_missing_checkpoint_does_not_strand_window(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path)
    controller = AppController(paths)
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)
    errors: list[object] = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    monkeypatch.setattr(window, "_show_error", errors.append)
    with qtbot.waitSignal(controller.playlist_restore_failed):
        window._choose_saved_playlist()
    assert len(errors) == 1
    assert window._state.state is JobState.IDLE
    assert window._restore_playlist.isEnabled()
    assert window._url.isEnabled()
    qtbot.waitUntil(lambda: not controller._threads)

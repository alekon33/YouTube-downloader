from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from videodownloader.models import CookieBrowser, JobState, MediaItem, MediaKind
from videodownloader.settings import AppPaths, SettingsService
from videodownloader.tools import ToolManager
from videodownloader.ui import AppController, MainWindow


def test_main_window_can_be_created(qtbot: QtBot, tmp_path: Path) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    controller = AppController(paths, ToolManager(paths.tools_dir))
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)

    assert window.windowTitle() == "VideoDownloader"
    assert window.minimumWidth() <= window.width()
    assert not hasattr(window, "_theme_combo")
    assert window._cookie_browser.currentData() is None
    assert window._cookie_browser.count() == 1 + 7


def test_playlist_controls_do_not_compete_with_active_progress(
    qtbot: QtBot, tmp_path: Path
) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    controller = AppController(paths, ToolManager(paths.tools_dir))
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)
    playlist = MediaItem(
        source_url="https://example.test/playlist",
        title="Playlist",
        kind=MediaKind.PLAYLIST,
        item_count=20,
    )

    window._set_state(JobState.ANALYZING)
    window._analysis_complete(playlist)

    assert not window._playlist_options.isHidden()
    assert window._playlist_options.parentWidget() is window._options_group
    assert window._overall_progress.isHidden()

    window._set_state(JobState.DOWNLOADING)

    assert window._playlist_options.isHidden()
    assert not window._overall_progress.isHidden()
    window._set_state(JobState.CANCELLED)


def test_small_playlist_window_scrolls_instead_of_squashing_controls(
    qtbot: QtBot, tmp_path: Path
) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    controller = AppController(paths, ToolManager(paths.tools_dir))
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)
    window.resize(660, 560)
    window.show()
    window._set_state(JobState.ANALYZING)
    window._analysis_complete(
        MediaItem(
            source_url="https://example.test/playlist",
            title="Playlist",
            kind=MediaKind.PLAYLIST,
            item_count=20,
        )
    )
    qtbot.wait(20)

    assert window._scroll_area.verticalScrollBar().maximum() > 0
    assert window._download.height() >= window._download.minimumHeight()


def test_browser_cookie_selection_requires_confirmation(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, tmp_path: Path
) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    settings = SettingsService(paths)
    controller = AppController(paths, ToolManager(paths.tools_dir))
    window = MainWindow(controller, settings, auto_prepare=False)
    qtbot.addWidget(window)
    answers = iter(
        [
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        ]
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: next(answers))
    firefox_index = window._cookie_browser.findData(CookieBrowser.FIREFOX)

    window._cookie_browser.setCurrentIndex(firefox_index)
    assert window._cookie_browser.currentData() is None

    window._cookie_browser.setCurrentIndex(firefox_index)
    assert window._selected_cookie_browser() is CookieBrowser.FIREFOX
    assert settings.load().cookie_browser is CookieBrowser.FIREFOX


def test_analysis_shows_indeterminate_progress_and_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, tmp_path: Path
) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    controller = AppController(paths, ToolManager(paths.tools_dir))
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)
    calls: list[tuple[str, CookieBrowser | None]] = []
    monkeypatch.setattr(controller, "analyze", lambda url, browser: calls.append((url, browser)))
    window._url.setText("https://example.test/video")

    window._start_analysis()

    assert calls == [("https://example.test/video", None)]
    assert window._state.state is JobState.ANALYZING
    assert window._current_progress.minimum() == 0
    assert window._current_progress.maximum() == 0
    assert not window._current_progress.isTextVisible()
    assert window._analysis_timer.isActive()
    assert window._telemetry.text() == "Анализ выполняется · прошло 0:00"

    qtbot.waitUntil(
        lambda: window._telemetry.text() != "Анализ выполняется · прошло 0:00",
        timeout=2500,
    )
    assert window._telemetry.text().startswith("Анализ выполняется · прошло 0:0")

    window._analysis_complete(
        MediaItem(
            source_url="https://example.test/video",
            title="Video",
            kind=MediaKind.VIDEO,
        )
    )

    assert window._state.state is JobState.READY
    assert window._current_progress.minimum() == 0
    assert window._current_progress.maximum() == 100
    assert window._current_progress.value() == 0
    assert window._current_progress.isTextVisible()
    assert not window._analysis_timer.isActive()
    assert window._telemetry.text() == "—"


def test_failed_analysis_restores_download_progress_mode(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, tmp_path: Path
) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    controller = AppController(paths, ToolManager(paths.tools_dir))
    window = MainWindow(controller, SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)
    monkeypatch.setattr(controller, "analyze", lambda url, browser: None)
    monkeypatch.setattr(window, "_show_error", lambda error: None)
    window._current_progress.setValue(73)
    window._telemetry.setText("старые данные")
    window._url.setText("https://example.test/video")
    window._start_analysis()

    window._analysis_failed(RuntimeError("network error"))

    assert window._state.state is JobState.IDLE
    assert window._current_progress.minimum() == 0
    assert window._current_progress.maximum() == 100
    assert window._current_progress.value() == 0
    assert window._current_progress.isTextVisible()
    assert not window._analysis_timer.isActive()
    assert window._telemetry.text() == "—"

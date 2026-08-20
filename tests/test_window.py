from pathlib import Path

from pytestqt.qtbot import QtBot

from videodownloader.models import JobState, MediaItem, MediaKind
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

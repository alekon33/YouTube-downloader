from pathlib import Path

from pytestqt.qtbot import QtBot

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

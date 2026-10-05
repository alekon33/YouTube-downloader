from collections.abc import Iterator
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon
from pytestqt.qtbot import QtBot

from videodownloader.models import JobState
from videodownloader.settings import AppPaths, SettingsService
from videodownloader.ui import AppController, MainWindow
from videodownloader.ui.tray import application_icon


@pytest.fixture
def tray_window(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, tmp_path: Path
) -> Iterator[MainWindow]:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", staticmethod(lambda: False))
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    window = MainWindow(AppController(paths), SettingsService(paths), auto_prepare=False)
    qtbot.addWidget(window)
    window.show()
    yield window
    # Widget cleanup must actually close the window rather than hide it in the tray.
    window._state.reset()
    window._explicit_exit = True
    window._tray.hide()


def start_active_download(window: MainWindow) -> None:
    window._set_state(JobState.ANALYZING)
    window._set_state(JobState.READY)
    window._set_state(JobState.DOWNLOADING)


def test_packaged_icon_has_tray_and_hidpi_sizes(qapp: object) -> None:
    icon = application_icon()

    assert not icon.isNull()
    assert not icon.pixmap(16, 16).isNull()
    assert not icon.pixmap(64, 64).isNull()


def test_close_hides_without_cancelling_active_download(
    tray_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_active_download(tray_window)
    cancellations: list[bool] = []
    monkeypatch.setattr(
        tray_window._controller, "cancel_download", lambda: cancellations.append(True)
    )

    assert tray_window.close() is False

    assert not tray_window.isVisible()
    assert tray_window._tray.isVisible()
    assert tray_window._state.state is JobState.DOWNLOADING
    assert cancellations == []
    assert not tray_window._shutting_down


def test_minimize_hides_and_click_restores_maximized_window(
    tray_window: MainWindow, qtbot: QtBot
) -> None:
    tray_window.showMaximized()
    tray_window.showMinimized()
    qtbot.waitUntil(lambda: not tray_window.isVisible())

    tray_window._tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    assert tray_window.isVisible()
    assert not tray_window.isMinimized()
    assert tray_window.isMaximized()
    tray_window._tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
    assert tray_window.isVisible()


def test_tray_menu_restores_window(tray_window: MainWindow) -> None:
    tray_window._hide_to_tray_action.trigger()
    assert not tray_window.isVisible()

    tray_window._tray.restore_action.trigger()

    assert tray_window.isVisible()


def test_disabling_tray_is_persisted_and_keeps_normal_minimize(
    tray_window: MainWindow, qtbot: QtBot
) -> None:
    tray_window._tray_enabled_action.setChecked(False)
    assert tray_window._settings_service.load().minimize_to_tray is False

    tray_window.showMinimized()
    qtbot.wait(20)

    assert tray_window.isVisible()
    assert tray_window.windowState() & Qt.WindowState.WindowMinimized
    with qtbot.waitSignal(tray_window.quit_requested):
        assert tray_window.close() is True


def test_no_tray_never_hides_or_strands_the_window(
    tray_window: MainWindow, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))

    assert tray_window._hide_to_tray() is False
    assert tray_window.isVisible()
    tray_window.showMinimized()
    qtbot.wait(20)
    assert tray_window.isVisible()
    with qtbot.waitSignal(tray_window.quit_requested):
        assert tray_window.close() is True


def test_exit_from_tray_can_be_cancelled_during_download(
    tray_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_active_download(tray_window)
    tray_window.close()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No
    )

    tray_window._tray.exit_action.trigger()

    assert tray_window.isVisible()
    assert not tray_window._explicit_exit
    assert not tray_window._shutting_down
    assert tray_window._state.state is JobState.DOWNLOADING


def test_confirmed_exit_cancels_download_and_removes_tray(
    tray_window: MainWindow, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    start_active_download(tray_window)
    cancellations: list[bool] = []
    monkeypatch.setattr(
        tray_window._controller, "cancel_download", lambda: cancellations.append(True)
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )

    with qtbot.waitSignal(tray_window.quit_requested):
        tray_window._exit_action.trigger()

    assert cancellations == [True]
    assert not tray_window.isVisible()
    assert not tray_window._tray.isVisible()
    assert tray_window._shutting_down


def test_background_completion_notifies_without_restoring(
    tray_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    start_active_download(tray_window)
    tray_window.close()
    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tray_window._tray, "notify", lambda title, text: notifications.append((title, text))
    )

    tray_window._controller.download_succeeded.emit(tmp_path / "video.mp4")

    assert not tray_window.isVisible()
    assert tray_window._current_progress.value() == 100
    assert tray_window._state.state is JobState.COMPLETED
    assert notifications == [("Загрузка завершена", "Файлы сохранены.")]


class WaitingWorker(QObject):
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def run(self) -> None:
        self.started.set()
        self.release.wait(timeout=5)
        self.finished.emit()


def test_exit_waits_for_workers_without_blocking_ui(
    tray_window: MainWindow, qtbot: QtBot
) -> None:
    worker = WaitingWorker()
    controller = tray_window._controller
    controller._launch(worker, (worker.finished,))
    qtbot.waitUntil(worker.started.is_set)
    signals: list[bool] = []
    tray_window.quit_requested.connect(lambda: signals.append(True))
    try:
        tray_window._request_exit()
        assert tray_window._shutting_down
        assert controller._threads
        assert signals == []
        assert tray_window._tray.isVisible()
        assert not tray_window._tray.menu.isEnabled()
        worker.release.set()
        qtbot.waitUntil(lambda: signals == [True])
        assert not controller._threads
        assert not tray_window._tray.isVisible()
        controller.shutdown()
        assert signals == [True]
    finally:
        worker.release.set()
        qtbot.waitUntil(lambda: not controller._threads)

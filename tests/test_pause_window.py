from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon
from pytestqt.qtbot import QtBot

from videodownloader.core.exceptions import DownloadError
from videodownloader.models import DownloadProgress, DownloadStage, JobState, MediaItem, MediaKind
from videodownloader.settings import AppPaths, SettingsService
from videodownloader.ui import AppController, MainWindow


@pytest.fixture
def window(qtbot: QtBot, tmp_path: Path) -> Iterator[MainWindow]:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    view = MainWindow(AppController(paths), SettingsService(paths), auto_prepare=False)

    def before_close(widget: MainWindow) -> None:
        widget._state.reset()
        widget._explicit_exit = True
        widget._tray.hide()

    qtbot.addWidget(view, before_close_func=before_close)
    view._set_state(JobState.ANALYZING)
    view._analysis_complete(
        MediaItem("https://example.test/playlist", "Playlist", MediaKind.PLAYLIST, item_count=8)
    )
    view._set_state(JobState.DOWNLOADING)
    view.show()
    yield view
    view._state.reset()
    view._explicit_exit = True
    view._tray.hide()


def test_pause_acknowledgement_keeps_progress_and_locks_options(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(window._controller, "pause_download", lambda: calls.append("pause") or True)
    monkeypatch.setattr(window._controller, "resume_download", lambda: calls.append("resume"))
    window._update_progress(
        DownloadProgress(
            DownloadStage.VIDEO, percent=40, overall_percent=60, playlist_index=2, playlist_count=3
        )
    )
    qtbot.mouseClick(window._pause, Qt.MouseButton.LeftButton)

    assert calls == ["pause"]
    assert window._state.state is JobState.PAUSING
    assert not window._pause.isEnabled()
    # Queued output from before the request must not reactivate downloading.
    window._update_progress(DownloadProgress(DownloadStage.VIDEO, percent=45))
    assert window._current_progress.value() == 40
    window._update_progress(
        DownloadProgress(
            DownloadStage.PAUSED, percent=40, overall_percent=60, playlist_index=2, playlist_count=3
        )
    )

    assert window._state.state is JobState.PAUSED
    assert window._pause.text() == "Продолжить"
    assert window._pause.isEnabled()
    assert window._cancel.isEnabled()
    assert not window._download.isEnabled()
    assert not window._url.isEnabled()
    assert not window._folder.isEnabled()
    assert not window._playlist_intervals.isEnabled()
    assert window._playlist_options.isHidden()
    assert not window._overall_progress.isHidden()
    assert window._overall_progress.value() == 60
    assert window._playlist_status.text() == "Видео 2 из 3"

    qtbot.mouseClick(window._pause, Qt.MouseButton.LeftButton)
    assert calls == ["pause", "resume"]
    assert window._state.state is JobState.DOWNLOADING


def test_waiting_for_connection_is_active_and_recovers(window: MainWindow) -> None:
    window._update_progress(
        DownloadProgress(
            DownloadStage.WAITING_FOR_CONNECTION, message="Ожидание соединения · повтор через 5 с"
        )
    )
    assert window._state.state is JobState.WAITING_FOR_CONNECTION
    assert "5 с" in window._status.text()
    assert window._pause.isEnabled()
    assert window._cancel.isEnabled()
    assert not window._folder.isEnabled()

    window._update_progress(DownloadProgress(DownloadStage.RESUMING))
    window._update_progress(DownloadProgress(DownloadStage.VIDEO, percent=55))
    assert window._state.state is JobState.DOWNLOADING
    assert window._current_progress.value() == 55


def test_pause_is_unavailable_during_processing_but_returns_for_next_item(
    window: MainWindow,
) -> None:
    window._update_progress(DownloadProgress(DownloadStage.POST_PROCESSING))
    assert window._state.state is JobState.POST_PROCESSING
    assert not window._pause.isEnabled()
    assert "обработки аудио" in window._pause.toolTip()
    window._update_progress(
        DownloadProgress(DownloadStage.AUDIO, percent=10, playlist_index=2, playlist_count=3)
    )
    assert window._state.state is JobState.DOWNLOADING
    assert window._pause.isEnabled()


def test_cancel_on_pause_ignores_late_progress(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancelled: list[bool] = []
    monkeypatch.setattr(window._controller, "cancel_download", lambda: cancelled.append(True))
    window._update_progress(DownloadProgress(DownloadStage.PAUSED))
    window._cancel_download()
    window._update_progress(DownloadProgress(DownloadStage.RESUMING))
    assert cancelled == [True]
    assert not window._pause.isEnabled()
    assert not window._cancel.isEnabled()
    assert window._status.text() == "Отмена…"
    window._download_cancelled(None)
    assert window._state.state is JobState.CANCELLED


def test_terminal_error_is_nonmodal_and_allows_retry_without_closing_window(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    modal_calls: list[bool] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: modal_calls.append(True) or 0)
    window._update_progress(DownloadProgress(DownloadStage.PAUSED, percent=64))
    window._update_progress(DownloadProgress(DownloadStage.RESUMING))
    window._download_failed(
        DownloadError("Не удалось подключиться к сайту.", "Unknown transport error")
    )

    assert modal_calls == []
    assert window._state.state is JobState.READY
    assert window._download.isEnabled()
    assert window._pause.isEnabled()
    assert window._pause.text() == "Повторить"
    assert window._url.isEnabled()
    assert window._current_progress.value() == 64
    box = window.findChild(QMessageBox)
    assert box is not None
    qtbot.addWidget(box)
    assert box.windowModality() is Qt.WindowModality.NonModal
    assert box.standardButtons() & QMessageBox.StandardButton.Retry
    captured: list[object] = []
    monkeypatch.setattr(window._controller, "download", lambda *args: captured.append(args))
    qtbot.mouseClick(window._pause, Qt.MouseButton.LeftButton)
    assert len(captured) == 1
    assert window._state.state is JobState.DOWNLOADING


def test_late_progress_after_terminal_failure_does_not_lock_ready_controls(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: 0)
    window._download_failed(DownloadError("Ошибка", "permanent failure"))
    window._controller.download_progress.emit(
        DownloadProgress(DownloadStage.WAITING_FOR_CONNECTION)
    )
    window._controller.download_progress.emit(DownloadProgress(DownloadStage.VIDEO, percent=64))
    assert window._state.state is JobState.READY
    assert window._url.isEnabled()
    assert window._download.isEnabled()


def test_error_dialog_retry_starts_new_download_once(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    captured: list[object] = []
    monkeypatch.setattr(window._controller, "download", lambda *args: captured.append(args))
    window._download_failed(DownloadError("Ошибка", "Unknown transport failure"))
    box = window._download_error_box
    assert box is not None
    button = box.button(QMessageBox.StandardButton.Retry)
    assert button is not None
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(captured) == 1
    assert window._state.state is JobState.DOWNLOADING
    assert window._download_error_box is None
    assert not window._download_retry_available


@pytest.mark.parametrize("stage", [DownloadStage.PAUSED, DownloadStage.WAITING_FOR_CONNECTION])
def test_explicit_exit_cancels_paused_and_waiting_jobs(
    window: MainWindow,
    stage: DownloadStage,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    cancelled: list[bool] = []
    monkeypatch.setattr(window._controller, "cancel_download", lambda: cancelled.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._update_progress(DownloadProgress(stage))
    with qtbot.waitSignal(window.quit_requested):
        window._request_exit()
    assert cancelled == [True]
    assert window._shutting_down


def test_playlist_notifies_only_once_after_whole_job(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    window._hide_to_tray()
    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._tray, "notify", lambda title, text: notifications.append((title, text))
    )
    for index in (1, 2):
        window._controller.download_progress.emit(
            DownloadProgress(
                DownloadStage.COMPLETED, percent=100, playlist_index=index, playlist_count=3
            )
        )
    assert notifications == []
    assert window._state.state is JobState.DOWNLOADING
    window._controller.download_succeeded.emit(tmp_path)
    assert notifications == [("Загрузка завершена", "Файлы сохранены.")]

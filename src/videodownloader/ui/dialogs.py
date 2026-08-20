"""Small focused dialogs for component preparation and application details."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videodownloader import __version__
from videodownloader.core.exceptions import VideoDownloaderError
from videodownloader.ui.controller import AppController


class PreparationDialog(QDialog):
    """Visible first-run flow for acquiring yt-dlp, FFmpeg, and Deno."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle(self.tr("Подготовка компонентов"))
        self.setModal(True)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        self._title = QLabel(self.tr("Подготавливаем yt-dlp, FFmpeg и Deno"))
        self._title.setObjectName("mediaTitle")
        layout.addWidget(self._title)
        layout.addWidget(
            QLabel(
                self.tr(
                    "Компоненты будут загружены из официальных источников, "
                    "проверены и сохранены только для текущего пользователя."
                )
            )
        )
        self._status = QLabel(self.tr("Ожидание…"))
        self._status.setObjectName("muted")
        layout.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        layout.addWidget(self._progress)
        self._retry = QPushButton(self.tr("Повторить"))
        self._retry.hide()
        self._retry.clicked.connect(self._start)
        layout.addWidget(self._retry)
        controller.tool_progress.connect(self._on_progress)
        controller.tools_succeeded.connect(self.accept)
        controller.tools_failed.connect(self._on_failed)
        QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        self._retry.hide()
        self._progress.setRange(0, 0)
        self._status.setText(self.tr("Подключение к источнику…"))
        self._controller.prepare_tools()

    def _on_progress(self, name: str, downloaded: int, total: int) -> None:
        self._status.setText(self.tr("Загрузка {name}…").format(name=name))
        if total > 0:
            self._progress.setRange(0, 100)
            self._progress.setValue(min(100, int(downloaded / total * 100)))
        else:
            self._progress.setRange(0, 0)

    def _on_failed(self, error: VideoDownloaderError) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._status.setText(error.user_message)
        self._retry.show()


def show_about(parent: QWidget | None = None) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("О программе")
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(f"VideoDownloader {__version__}")
    box.setInformativeText(
        "Открытый интерфейс для yt-dlp. Без телеметрии, рекламы и изменения PATH."
    )
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()

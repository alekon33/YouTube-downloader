"""System tray actions and a packaged icon shared with the Windows build."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def application_icon() -> QIcon:
    """Render embedded SVG data without relying on the working directory."""
    data = files("videodownloader.resources").joinpath("icon.svg").read_bytes()
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise RuntimeError("Invalid application icon")
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class TrayIcon(QSystemTrayIcon):
    """Keep a discoverable restore/exit menu while the main window is hidden."""

    restore_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(application_icon(), parent)
        self.setToolTip("VideoDownloader")
        self.menu = QMenu(parent)
        self.restore_action = self.menu.addAction(self.tr("Открыть VideoDownloader"))
        self.restore_action.triggered.connect(self.restore_requested)
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction(self.tr("Выйти"))
        self.exit_action.triggered.connect(self.exit_requested)
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.messageClicked.connect(self.restore_requested)
        if self.isSystemTrayAvailable():
            self.show()

    def can_hide_window(self) -> bool:
        if not self.isSystemTrayAvailable() or self.icon().isNull():
            return False
        self.show()
        return self.isVisible()

    def notify(self, title: str, text: str) -> None:
        if self.isVisible() and self.supportsMessages():
            self.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore_requested.emit()

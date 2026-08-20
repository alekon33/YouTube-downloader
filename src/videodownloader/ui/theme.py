"""Calm light and dark Qt styles without fixed widget geometry."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from videodownloader.models import Theme

_DARK = """
QWidget { background: #17191d; color: #f2f3f5; font-size: 14px; }
QMainWindow, QDialog { background: #17191d; }
QFrame#card, QGroupBox { background: #202329; border: 1px solid #30343b; border-radius: 10px; }
QGroupBox { margin-top: 14px; padding: 16px 12px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #b9c0cc; }
QLineEdit, QComboBox, QSpinBox { background: #282c33; border: 1px solid #414752; border-radius: 7px; padding: 8px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #6da8ff; }
QPushButton { background: #2d68c4; border: none; border-radius: 7px; padding: 9px 16px; color: white; font-weight: 600; }
QPushButton:hover { background: #3778dc; }
QPushButton:disabled { background: #343840; color: #777e89; }
QPushButton#secondary { background: #30343b; font-weight: 500; }
QPushButton#danger { background: #8d3440; }
QProgressBar { background: #2a2e35; border: none; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #5b95eb; border-radius: 5px; }
QLabel#muted { color: #9aa2ae; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#mediaTitle { font-size: 17px; font-weight: 650; }
"""

_LIGHT = """
QWidget { background: #f5f7fa; color: #1c2430; font-size: 14px; }
QMainWindow, QDialog { background: #f5f7fa; }
QFrame#card, QGroupBox { background: white; border: 1px solid #dfe4eb; border-radius: 10px; }
QGroupBox { margin-top: 14px; padding: 16px 12px 12px 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #596477; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #cbd2dc; border-radius: 7px; padding: 8px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #2f75d6; }
QPushButton { background: #2f6fc9; border: none; border-radius: 7px; padding: 9px 16px; color: white; font-weight: 600; }
QPushButton:hover { background: #245fab; }
QPushButton:disabled { background: #d5dbe4; color: #858d99; }
QPushButton#secondary { background: #e7ebf1; color: #273142; font-weight: 500; }
QPushButton#danger { background: #b74855; }
QProgressBar { background: #e1e6ed; border: none; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #397edb; border-radius: 5px; }
QLabel#muted { color: #687386; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#mediaTitle { font-size: 17px; font-weight: 650; }
"""


def apply_theme(application: QApplication, theme: Theme) -> None:
    """Apply an explicit palette or defer to Qt's system appearance."""

    if theme is Theme.DARK:
        application.setStyleSheet(_DARK)
    elif theme is Theme.LIGHT:
        application.setStyleSheet(_LIGHT)
    else:
        application.setStyleSheet("")


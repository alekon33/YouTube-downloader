"""GUI entry point."""

from __future__ import annotations


def main() -> int:
    """Start the desktop application."""

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from videodownloader.app import bootstrap_services
    from videodownloader.ui import AppController, MainWindow

    QCoreApplication.setOrganizationName("VideoDownloader")
    QCoreApplication.setApplicationName("VideoDownloader")
    application = QApplication.instance() or QApplication([])
    paths, settings = bootstrap_services()
    controller = AppController(paths)
    window = MainWindow(controller, settings)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

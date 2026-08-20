"""QObject workers that keep blocking I/O away from the GUI thread."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from videodownloader.core.exceptions import (
    DownloadCancelled,
    VideoDownloaderError,
)
from videodownloader.downloader import DownloadExecutor, YtDlpService
from videodownloader.models import DownloadJob, DownloadProgress
from videodownloader.tools import ToolManager
from videodownloader.tools.releases import YtDlpReleaseClient, YtDlpUpdate


class AnalysisWorker(QObject):
    """Analyze one URL on a dedicated thread."""

    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, service: YtDlpService, url: str) -> None:
        super().__init__()
        self._service = service
        self._url = url

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self._service.analyze(self._url))
        except VideoDownloaderError as error:
            self.failed.emit(error)
        except Exception as error:
            logging.getLogger(__name__).exception("Unexpected analysis error")
            self.failed.emit(
                VideoDownloaderError("Не удалось проанализировать ссылку.", str(error))
            )


class DownloadWorker(QObject):
    """Execute one download job on a dedicated thread."""

    progress = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal(object)

    def __init__(self, executor: DownloadExecutor, job: DownloadJob) -> None:
        super().__init__()
        self.executor = executor
        self._job = job

    @Slot()
    def run(self) -> None:
        try:
            result = self.executor.execute(self._job, self._emit_progress)
            self.succeeded.emit(result)
        except DownloadCancelled as error:
            self.cancelled.emit(error)
        except VideoDownloaderError as error:
            self.failed.emit(error)
        except Exception as error:
            logging.getLogger(__name__).exception("Unexpected download error")
            self.failed.emit(VideoDownloaderError("Не удалось скачать видео.", str(error)))

    def cancel(self) -> None:
        self.executor.cancel()

    def _emit_progress(self, progress: DownloadProgress) -> None:
        self.progress.emit(progress)


class ToolPreparationWorker(QObject):
    """Download and verify external components away from the GUI thread."""

    progress = Signal(str, int, int)
    succeeded = Signal()
    failed = Signal(object)

    def __init__(self, manager: ToolManager) -> None:
        super().__init__()
        self._manager = manager

    @Slot()
    def run(self) -> None:
        try:
            self._manager.ensure_all(self._emit_progress)
            self.succeeded.emit()
        except VideoDownloaderError as error:
            self.failed.emit(error)
        except Exception as error:
            logging.getLogger(__name__).exception("Tool preparation failed")
            self.failed.emit(
                VideoDownloaderError(
                    "Не удалось подготовить компоненты. Проверьте интернет-соединение.",
                    str(error),
                )
            )

    def _emit_progress(self, name: str, downloaded: int, total: int | None) -> None:
        self.progress.emit(name, downloaded, total or 0)


class UpdateCheckWorker(QObject):
    """Query the official yt-dlp release API on a background thread."""

    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, installed_version: str) -> None:
        super().__init__()
        self._installed_version = installed_version

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(YtDlpReleaseClient().check(self._installed_version))
        except VideoDownloaderError as error:
            self.failed.emit(error)
        except Exception as error:
            logging.getLogger(__name__).exception("Update check failed")
            self.failed.emit(VideoDownloaderError("Не удалось проверить обновление yt-dlp.", str(error)))


class UpdateInstallWorker(QObject):
    """Install one verified yt-dlp update without replacing FFmpeg or the app."""

    progress = Signal(str, int, int)
    succeeded = Signal(str)
    failed = Signal(object)

    def __init__(self, manager: ToolManager, update: YtDlpUpdate) -> None:
        super().__init__()
        self._manager = manager
        self._update = update

    @Slot()
    def run(self) -> None:
        try:
            self._manager.install_asset(self._update.asset, self._emit_progress)
            self.succeeded.emit(self._update.asset.version)
        except VideoDownloaderError as error:
            self.failed.emit(error)
        except Exception as error:
            logging.getLogger(__name__).exception("yt-dlp update failed")
            self.failed.emit(VideoDownloaderError("Не удалось обновить yt-dlp.", str(error)))

    def _emit_progress(self, name: str, downloaded: int, total: int | None) -> None:
        self.progress.emit(name, downloaded, total or 0)


def existing_result_path(result: object, fallback: Path) -> Path:
    """Return a usable folder whether yt-dlp reported a file or not."""

    if isinstance(result, Path):
        return result.parent if result.suffix else result
    return fallback

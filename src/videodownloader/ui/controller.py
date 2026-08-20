"""Thread-aware bridge between Qt widgets and application services."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, SignalInstance

from videodownloader.downloader import DownloadExecutor, YtDlpService
from videodownloader.models import (
    CookieBrowser,
    DownloadJob,
    DownloadOptions,
    MediaItem,
    PlaylistJob,
)
from videodownloader.settings import AppPaths
from videodownloader.tools import ToolManager
from videodownloader.tools.releases import YtDlpUpdate
from videodownloader.ui.workers import (
    AnalysisWorker,
    DownloadWorker,
    ToolPreparationWorker,
    UpdateCheckWorker,
    UpdateInstallWorker,
)


class AppController(QObject):
    """Own background operations and expose queued Qt signals to the window."""

    analysis_succeeded = Signal(object)
    analysis_failed = Signal(object)
    download_progress = Signal(object)
    download_succeeded = Signal(object)
    download_failed = Signal(object)
    download_cancelled = Signal(object)
    tool_progress = Signal(str, int, int)
    tools_succeeded = Signal()
    tools_failed = Signal(object)
    update_checked = Signal(object)
    update_check_failed = Signal(object)
    update_progress = Signal(str, int, int)
    update_installed = Signal(str)
    update_install_failed = Signal(object)

    def __init__(self, paths: AppPaths, tool_manager: ToolManager | None = None) -> None:
        super().__init__()
        self.paths = paths
        self.tools = tool_manager or ToolManager(paths.tools_dir)
        self._threads: set[QThread] = set()
        self._workers: set[QObject] = set()
        self._download_worker: DownloadWorker | None = None

    def tools_available(self) -> bool:
        return self.tools.all_available()

    def prepare_tools(self) -> None:
        worker = ToolPreparationWorker(self.tools)
        worker.progress.connect(self.tool_progress)
        worker.succeeded.connect(self.tools_succeeded)
        worker.failed.connect(self.tools_failed)
        self._launch(worker, (worker.succeeded, worker.failed))

    def analyze(self, url: str, cookie_browser: CookieBrowser | None = None) -> None:
        service = YtDlpService(
            self.tools.yt_dlp_path,
            self.tools.tools_dir,
            javascript_runtime=self.tools.deno_path,
            cookie_browser=cookie_browser,
        )
        worker = AnalysisWorker(service, url)
        worker.succeeded.connect(self.analysis_succeeded)
        worker.failed.connect(self.analysis_failed)
        self._launch(worker, (worker.succeeded, worker.failed))

    def check_yt_dlp_update(self) -> None:
        installed = self.tools.status()["yt-dlp"].version
        if not installed:
            self.update_check_failed.emit(
                ValueError("yt-dlp must be installed before checking for an update")
            )
            return
        worker = UpdateCheckWorker(installed)
        worker.succeeded.connect(self.update_checked)
        worker.failed.connect(self.update_check_failed)
        self._launch(worker, (worker.succeeded, worker.failed))

    def install_yt_dlp_update(self, update: YtDlpUpdate) -> None:
        worker = UpdateInstallWorker(self.tools, update)
        worker.progress.connect(self.update_progress)
        worker.succeeded.connect(self.update_installed)
        worker.failed.connect(self.update_install_failed)
        self._launch(worker, (worker.succeeded, worker.failed))

    def download(self, media: MediaItem, options: DownloadOptions) -> None:
        job: DownloadJob
        if media.is_playlist:
            job = PlaylistJob(media=media, options=options)
        else:
            job = DownloadJob(media=media, options=options)
        executor = DownloadExecutor(
            self.tools.yt_dlp_path,
            self.tools.tools_dir,
            self.tools.deno_path,
        )
        worker = DownloadWorker(executor, job)
        self._download_worker = worker
        worker.progress.connect(self.download_progress)
        worker.succeeded.connect(self.download_succeeded)
        worker.failed.connect(self.download_failed)
        worker.cancelled.connect(self.download_cancelled)
        terminal_signals = (worker.succeeded, worker.failed, worker.cancelled)
        for signal in terminal_signals:
            signal.connect(self._clear_download_worker)
        self._launch(worker, terminal_signals)

    def cancel_download(self) -> None:
        if self._download_worker:
            self._download_worker.cancel()

    def shutdown(self) -> None:
        self.cancel_download()
        for thread in tuple(self._threads):
            thread.quit()
            thread.wait(5000)

    def _launch(
        self,
        worker: (
            AnalysisWorker
            | DownloadWorker
            | ToolPreparationWorker
            | UpdateCheckWorker
            | UpdateInstallWorker
        ),
        terminal_signals: tuple[SignalInstance, ...],
    ) -> None:
        thread = QThread(self)
        self._threads.add(thread)
        self._workers.add(worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        for signal in terminal_signals:
            signal.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._release(thread, worker))
        thread.start()

    def _release(self, thread: QThread, worker: QObject) -> None:
        self._threads.discard(thread)
        self._workers.discard(worker)

    def _clear_download_worker(self) -> None:
        self._download_worker = None


def openable_folder(result: object, destination: Path) -> Path:
    if isinstance(result, Path):
        return result.parent if result.suffix else result
    return destination

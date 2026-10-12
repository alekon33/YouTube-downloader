"""Streaming child-process execution and Windows process-tree cancellation."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import psutil

from videodownloader.core.exceptions import DownloadCancelled, DownloadError
from videodownloader.downloader.arguments import build_download_arguments
from videodownloader.downloader.control import ProcessSuspension
from videodownloader.downloader.progress import ProgressParser
from videodownloader.downloader.recovery import is_transient_network_error
from videodownloader.models import (
    CookieBrowser,
    DownloadJob,
    DownloadProgress,
    DownloadStage,
    JobState,
)
from videodownloader.services.playlist_lock import PlaylistFolderLock
from videodownloader.services.playlist_sessions import PlaylistSessions
from videodownloader.utils.redaction import redact_sensitive_text

ProgressCallback = Callable[[DownloadProgress], None]


class DownloadExecutor:
    """Own one resumable job, its process tree, pause state and transport retries."""

    def __init__(
        self,
        executable: Path,
        ffmpeg_directory: Path,
        javascript_runtime: Path | None = None,
        *,
        retry_delay: float = 5.0,
    ) -> None:
        self.executable = executable
        self.ffmpeg_directory = ffmpeg_directory
        self.javascript_runtime = javascript_runtime
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._cancel_requested = threading.Event()
        self._pause_requested = threading.Event()
        self._finished = False
        self._phase = DownloadStage.VIDEO
        self._last_progress = DownloadProgress(stage=DownloadStage.VIDEO)
        self._overall_percent: float | None = None
        self._termination_thread: threading.Thread | None = None
        self._retry_delay = max(0.01, retry_delay)

    @property
    def active(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def execute(
        self,
        job: DownloadJob,
        on_progress: ProgressCallback | None = None,
    ) -> Path | None:
        """Own a folder lock for the whole saved job, including network waits."""
        if job.playlist_session is not None:
            with PlaylistFolderLock(job.playlist_session.folder):
                return self._execute(job, on_progress)
        return self._execute(job, on_progress)

    def _execute(
        self,
        job: DownloadJob,
        on_progress: ProgressCallback | None = None,
    ) -> Path | None:
        """Keep the same job and .part files through pauses and connection loss."""
        self._raise_if_cancelled(job)
        session = job.playlist_session
        if session is not None:
            PlaylistSessions.prepare(session)
            job.options = session.download_options(job.options.cookie_browser)
            self._overall_percent = session.completed_count / len(session.items) * 100
            self._last_progress = replace(
                self._last_progress,
                overall_percent=self._overall_percent,
                playlist_count=len(session.items),
            )
            if not session.runtime_items:
                job.state = JobState.COMPLETED
                self._finished = True
                return session.folder
        arguments = build_download_arguments(
            self.executable,
            self.ffmpeg_directory,
            job,
            self.javascript_runtime,
        )
        failures = 0
        final_path: Path | None = None
        try:
            while True:
                self._service_pause(None, job, on_progress)
                self._raise_if_cancelled(job)
                self._status(
                    DownloadStage.RESUMING
                    if failures
                    else (DownloadStage.AUDIO if job.options.audio_only else DownloadStage.VIDEO),
                    job,
                    on_progress,
                )
                return_code, detail, result = self._run_attempt(arguments, job, on_progress)
                final_path = result or final_path
                self._raise_if_cancelled(job)
                if return_code == 0:
                    if session is not None and session.pending_items:
                        raise DownloadError(
                            "Загрузчик завершился, но не все файлы сохранённого задания готовы.",
                            "Incomplete saved playlist",
                        )
                    job.state = JobState.COMPLETED
                    return final_path
                if not is_transient_network_error(detail):
                    job.state = JobState.FAILED
                    job.error_detail = detail
                    raise DownloadError(_friendly_error(detail, job.options.cookie_browser), detail)
                failures += 1
                delay = min(30.0, self._retry_delay * 2 ** min(failures - 1, 3))
                logging.getLogger(__name__).warning("Transport failure; retrying: %s", detail)
                self._status(
                    DownloadStage.WAITING_FOR_CONNECTION,
                    job,
                    on_progress,
                    f"Ожидание соединения · повтор через {delay:g} с",
                )
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._pause_requested.is_set() or self._cancel_requested.is_set(),
                        timeout=delay,
                    )
        finally:
            with self._condition:
                self._finished = True
                self._condition.notify_all()

    def _run_attempt(
        self,
        arguments: list[str],
        job: DownloadJob,
        on_progress: ProgressCallback | None,
    ) -> tuple[int, str, Path | None]:
        parser = ProgressParser(audio_only=job.options.audio_only)
        stderr_tail: deque[str] = deque(maxlen=80)
        reader_errors: list[Exception] = []
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=creation_flags,
        )
        with self._lock:
            self._process = process
        # A cancel between button press and Popen must not be lost.
        if self._cancel_requested.is_set():
            self._stop_async(process)

        def read_stdout() -> None:
            if process.stdout is None:
                return
            try:
                for line in process.stdout:
                    progress = parser.parse(line)
                    if progress:
                        progress = self._session_progress(progress, job)
                        self._publish(progress, job, on_progress)
            except Exception as error:
                reader_errors.append(error)
                self._stop_async(process)

        def read_stderr() -> None:
            if process.stderr is None:
                return
            for line in process.stderr:
                safe_line = redact_sensitive_text(line.rstrip())
                stderr_tail.append(safe_line)
                if is_transient_network_error(safe_line):
                    self._status(
                        DownloadStage.WAITING_FOR_CONNECTION,
                        job,
                        on_progress,
                        "Ожидание соединения…",
                    )

        readers = [
            threading.Thread(target=read_stdout, name="yt-dlp-stdout", daemon=True),
            threading.Thread(target=read_stderr, name="yt-dlp-stderr", daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            while True:
                self._service_pause(process, job, on_progress)
                try:
                    return_code = process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                self._terminate_process_tree(process)
            with self._lock:
                termination = self._termination_thread
            if termination:
                termination.join(timeout=10)
            for reader in readers:
                reader.join(timeout=5)
            with self._lock:
                self._process = None
                self._termination_thread = None
            for pipe in (process.stdout, process.stderr):
                if pipe:
                    pipe.close()
        detail = "\n".join(stderr_tail) or f"yt-dlp exited with code {return_code}"
        if reader_errors:
            raise reader_errors[0]
        return return_code, detail, parser.final_path

    @staticmethod
    def _session_progress(progress: DownloadProgress, job: DownloadJob) -> DownloadProgress:
        session = job.playlist_session
        if session is None:
            return progress
        ordinal = progress.playlist_index
        if ordinal is None or not 1 <= ordinal <= len(session.runtime_items):
            if progress.stage is DownloadStage.COMPLETED:
                raise DownloadError(
                    "Не удалось определить готовый элемент сохранённой очереди.",
                    "Missing queue index",
                )
            return progress
        item = session.runtime_items[ordinal - 1]
        if progress.stage is DownloadStage.COMPLETED and progress.filename:
            PlaylistSessions.record_completed(
                session, ordinal, progress.filename, progress.media_id, progress.extractor
            )
        fraction = (progress.percent or 0) / 100 if not item.completed else 0
        overall = min(100, (session.completed_count + fraction) / len(session.items) * 100)
        return replace(
            progress,
            overall_percent=overall,
            playlist_index=session.items.index(item) + 1,
            playlist_count=len(session.items),
        )

    def pause(self) -> bool:
        """Queue suspension; the worker performs OS calls, never the GUI thread."""
        with self._condition:
            if (
                self._finished
                or self._cancel_requested.is_set()
                or self._phase is DownloadStage.POST_PROCESSING
            ):
                return False
            self._pause_requested.set()
            self._condition.notify_all()
            return True

    def resume(self) -> None:
        with self._condition:
            self._pause_requested.clear()
            self._condition.notify_all()

    def _service_pause(
        self,
        process: subprocess.Popen[str] | None,
        job: DownloadJob,
        on_progress: ProgressCallback | None,
    ) -> None:
        if not self._pause_requested.is_set():
            return
        suspension = ProcessSuspension()
        if process is not None:
            with self._lock:
                if self._phase is DownloadStage.POST_PROCESSING:
                    self._pause_requested.clear()
                    self._status(DownloadStage.POST_PROCESSING, job, on_progress, force=True)
                    return
            try:
                suspension.suspend(process.pid)
            except psutil.NoSuchProcess:
                self._pause_requested.clear()
                return
            except psutil.Error as error:
                try:
                    suspension.resume()
                except psutil.Error as resume_error:
                    self._terminate_process_tree(process)
                    raise DownloadError(
                        "Не удалось безопасно включить паузу.", str(resume_error)
                    ) from resume_error
                self._pause_requested.clear()
                self._status(
                    DownloadStage.RESUMING,
                    job,
                    on_progress,
                    "Не удалось включить паузу; загрузка продолжается",
                    force=True,
                )
                logging.getLogger(__name__).warning("Cannot suspend download: %s", error)
                return
        try:
            with self._condition:
                self._status(DownloadStage.PAUSED, job, on_progress, force=True)
                self._condition.wait_for(
                    lambda: not self._pause_requested.is_set() or self._cancel_requested.is_set()
                )
        finally:
            try:
                suspension.resume()
            except psutil.Error as error:
                if process and process.poll() is None:
                    self._terminate_process_tree(process)
                self._raise_if_cancelled(job)
                raise DownloadError(
                    "Не удалось продолжить загрузку после паузы.", str(error)
                ) from error
        self._raise_if_cancelled(job)
        self._status(DownloadStage.RESUMING, job, on_progress)

    def _publish(
        self,
        progress: DownloadProgress,
        job: DownloadJob,
        on_progress: ProgressCallback | None,
        *,
        force: bool = False,
    ) -> None:
        with self._lock:
            if progress.overall_percent is not None:
                self._overall_percent = max(progress.overall_percent, self._overall_percent or 0)
            # Some yt-dlp markers have no percentage. They must not erase the
            # job-wide high-water mark before a retry revisits completed items.
            progress = replace(progress, overall_percent=self._overall_percent)
            self._last_progress = progress
            if not force:
                self._phase = progress.stage
                if self._pause_requested.is_set() or self._cancel_requested.is_set():
                    return
            states = {
                DownloadStage.PAUSED: JobState.PAUSED,
                DownloadStage.WAITING_FOR_CONNECTION: JobState.WAITING_FOR_CONNECTION,
                DownloadStage.POST_PROCESSING: JobState.POST_PROCESSING,
            }
            job.state = states.get(progress.stage, JobState.DOWNLOADING)
            if on_progress:
                on_progress(progress)

    def _status(
        self,
        stage: DownloadStage,
        job: DownloadJob,
        on_progress: ProgressCallback | None,
        message: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        with self._lock:
            progress = replace(
                self._last_progress,
                stage=stage,
                message=message,
                speed_bytes_per_second=None,
                eta_seconds=None,
            )
            self._publish(progress, job, on_progress, force=force)

    def _raise_if_cancelled(self, job: DownloadJob) -> None:
        if self._cancel_requested.is_set():
            job.state = JobState.CANCELLED
            raise DownloadCancelled("Загрузка отменена.", "Download process was cancelled")

    def cancel(self) -> None:
        """Request cancellation without blocking the Qt main thread."""

        with self._condition:
            self._cancel_requested.set()
            self._condition.notify_all()
            process = self._process
        if process is not None:
            self._stop_async(process)

    def _stop_async(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if process.poll() is not None or self._termination_thread is not None:
                return
            termination = threading.Thread(
                target=self._terminate_process_tree,
                args=(process,),
                name="yt-dlp-cancel",
                daemon=True,
            )
            self._termination_thread = termination
            termination.start()

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        """Terminate yt-dlp and its FFmpeg descendants without invoking a shell."""

        if os.name == "nt":
            taskkill = (
                Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
            )
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        logging.getLogger(__name__).info("Download process tree cancelled")


def _friendly_error(detail: str, cookie_browser: CookieBrowser | None = None) -> str:
    lowered = detail.casefold()
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        if cookie_browser is not None:
            return (
                "YouTube не принял авторизацию выбранного браузера. Убедитесь, что "
                "в нём выполнен вход в YouTube, и повторите анализ."
            )
        return (
            "YouTube запросил подтверждение. Выберите браузер с выполненным входом "
            "в поле «Авторизация YouTube» и повторите анализ."
        )
    if (
        "cookie" in lowered
        and any(token in lowered for token in ("could not copy", "permission denied"))
    ) or any(token in lowered for token in ("failed to decrypt", "dpapi", "v20")):
        return "Не удалось прочитать cookies. Закройте браузер или попробуйте Mozilla Firefox."
    if any(
        token in lowered for token in ("network is unreachable", "timed out", "unable to download")
    ):
        return "Не удалось подключиться к сайту. Проверьте интернет-соединение."
    if "unsupported url" in lowered:
        return "Этот сайт или тип ссылки не поддерживается."
    if any(token in lowered for token in ("private video", "sign in", "login", "authentication")):
        return "Для доступа к этому видео требуется авторизация."
    if any(
        token in lowered for token in ("video unavailable", "has been removed", "not available")
    ):
        return "Видео недоступно или было удалено."
    if "ffmpeg" in lowered and any(token in lowered for token in ("not found", "not installed")):
        return "FFmpeg не найден. Выполните подготовку компонентов."
    if any(token in lowered for token in ("no space left", "disk full", "not enough space")):
        return "Недостаточно свободного места на диске."
    if any(token in lowered for token in ("permission denied", "access is denied")):
        return "Не удалось записать файл в выбранную папку."
    return "Не удалось скачать файл."

"""Streaming child-process execution and Windows process-tree cancellation."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from videodownloader.core.exceptions import DownloadCancelled, DownloadError
from videodownloader.downloader.arguments import build_download_arguments
from videodownloader.downloader.progress import ProgressParser
from videodownloader.models import DownloadJob, DownloadProgress, JobState
from videodownloader.utils.redaction import redact_sensitive_text

ProgressCallback = Callable[[DownloadProgress], None]


class DownloadExecutor:
    """Run one yt-dlp job while draining both pipes and supporting cancellation."""

    def __init__(self, executable: Path, ffmpeg_directory: Path) -> None:
        self.executable = executable
        self.ffmpeg_directory = ffmpeg_directory
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._cancel_requested = threading.Event()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def execute(
        self,
        job: DownloadJob,
        on_progress: ProgressCallback | None = None,
    ) -> Path | None:
        """Block the calling worker thread until the job completes or is cancelled."""

        arguments = build_download_arguments(self.executable, self.ffmpeg_directory, job)
        parser = ProgressParser()
        stderr_tail: deque[str] = deque(maxlen=80)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        job.state = JobState.DOWNLOADING
        self._cancel_requested.clear()
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

        def read_stdout() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                progress = parser.parse(line)
                if progress and on_progress:
                    on_progress(progress)

        def read_stderr() -> None:
            if process.stderr is None:
                return
            for line in process.stderr:
                stderr_tail.append(redact_sensitive_text(line.rstrip()))

        readers = [
            threading.Thread(target=read_stdout, name="yt-dlp-stdout", daemon=True),
            threading.Thread(target=read_stderr, name="yt-dlp-stderr", daemon=True),
        ]
        for reader in readers:
            reader.start()
        return_code = process.wait()
        for reader in readers:
            reader.join(timeout=5)
        with self._lock:
            self._process = None

        if self._cancel_requested.is_set():
            job.state = JobState.CANCELLED
            raise DownloadCancelled("Загрузка отменена.", "Download process was cancelled")
        if return_code != 0:
            detail = "\n".join(stderr_tail) or f"yt-dlp exited with code {return_code}"
            job.state = JobState.FAILED
            job.error_detail = detail
            raise DownloadError(_friendly_error(detail), detail)
        job.state = JobState.COMPLETED
        return parser.final_path

    def cancel(self) -> None:
        """Terminate yt-dlp and its FFmpeg descendants without invoking a shell."""

        self._cancel_requested.set()
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
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


def _friendly_error(detail: str) -> str:
    lowered = detail.casefold()
    if any(token in lowered for token in ("network is unreachable", "timed out", "unable to download")):
        return "Не удалось подключиться к сайту. Проверьте интернет-соединение."
    if "unsupported url" in lowered:
        return "Этот сайт или тип ссылки не поддерживается."
    if any(token in lowered for token in ("private video", "sign in", "login", "authentication")):
        return "Для доступа к этому видео требуется авторизация."
    if any(token in lowered for token in ("video unavailable", "has been removed", "not available")):
        return "Видео недоступно или было удалено."
    if "ffmpeg" in lowered and any(token in lowered for token in ("not found", "not installed")):
        return "FFmpeg не найден. Выполните подготовку компонентов."
    if any(token in lowered for token in ("no space left", "disk full", "not enough space")):
        return "Недостаточно свободного места на диске."
    if any(token in lowered for token in ("permission denied", "access is denied")):
        return "Не удалось записать файл в выбранную папку."
    return "Не удалось скачать видео."

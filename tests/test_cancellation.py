"""Cancellation must not make the desktop event loop wait for taskkill."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, cast

from pytest import MonkeyPatch

from videodownloader.downloader import DownloadExecutor


class RunningProcess:
    """Small process double implementing the methods used by cancellation."""

    pid = 7319

    def poll(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


def test_cancel_returns_before_process_tree_shutdown_finishes(monkeypatch: MonkeyPatch) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"))
    executor._process = cast(Any, RunningProcess())
    termination_started = threading.Event()
    allow_termination = threading.Event()
    termination_finished = threading.Event()

    def slow_taskkill(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        termination_started.set()
        allow_termination.wait(timeout=2)
        termination_finished.set()
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", slow_taskkill)
    started = time.monotonic()
    executor.cancel()
    elapsed = time.monotonic() - started

    try:
        assert elapsed < 0.25
        assert termination_started.wait(timeout=1)
        assert not termination_finished.is_set()
    finally:
        allow_termination.set()
        assert termination_finished.wait(timeout=1)

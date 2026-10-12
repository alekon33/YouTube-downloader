from pathlib import Path
from threading import Event
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from videodownloader.core.exceptions import DownloadError
from videodownloader.downloader import DownloadExecutor
from videodownloader.models import DownloadJob, DownloadOptions, MediaItem, MediaKind
from videodownloader.settings import AppPaths
from videodownloader.ui import AppController


@pytest.mark.parametrize("_run", range(5))
def test_failed_worker_is_cleared_before_retry_callback(
    _run: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    controller = AppController(AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads"))
    media = MediaItem("https://example.test/video", "Video", MediaKind.VIDEO)
    options = DownloadOptions(tmp_path)
    started: list[DownloadJob] = []
    retry_started = Event()
    release_retry = Event()
    ownership: list[bool] = []

    def execute(self: DownloadExecutor, job: DownloadJob, callback: Any = None) -> Path:
        started.append(job)
        if len(started) == 1:
            raise DownloadError("Ошибка", "HTTP Error 403")
        retry_started.set()
        release_retry.wait(5)
        return tmp_path

    def retry(error: object) -> None:
        ownership.append(controller._download_worker is None)
        controller.download(media, options)

    monkeypatch.setattr(DownloadExecutor, "execute", execute)
    controller.download_failed.connect(retry)
    controller.download(media, options)
    try:
        qtbot.waitUntil(retry_started.is_set)
        assert ownership == [True]
        assert controller._download_worker is not None
        qtbot.wait(30)
        # The original terminal signal must not clear the new active worker.
        assert controller._download_worker is not None
        with qtbot.waitSignal(controller.download_succeeded):
            release_retry.set()
        assert controller._download_worker is None
        qtbot.waitUntil(lambda: not controller._threads)
    finally:
        release_retry.set()
        controller.shutdown()
        qtbot.waitUntil(lambda: not controller._threads)

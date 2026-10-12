from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from videodownloader.core.exceptions import DownloadCancelled, DownloadError
from videodownloader.downloader import DownloadExecutor
from videodownloader.downloader.recovery import is_transient_network_error
from videodownloader.models import (
    DownloadJob,
    DownloadOptions,
    DownloadProgress,
    DownloadStage,
    JobState,
    MediaItem,
    MediaKind,
    PlaylistInterval,
)


@pytest.mark.parametrize(
    "detail",
    [
        "ERROR: Unable to download: Network is unreachable",
        "ERROR: [WinError 10054] Connection reset by peer",
        "ERROR: timed out",
        "ERROR: getaddrinfo failed",
        "ERROR: HTTP Error 503: Service Unavailable",
        "ERROR: HTTP Error 429",
        "ERROR: IncompleteRead(1024 bytes read, 8192 more expected)",
        "ERROR: content too short",
        "ERROR: Temporary failure in name resolution",
        "ERROR: Unable to download: [WinError 10050] Операция на сокете обнаружила, что сеть отключена",
        "ERROR: [WinError 10053] Программное обеспечение разорвало установленное соединение",
        "ERROR: [WinError 10065] Нет маршрута к узлу",
        "ERROR: curl: (6) Could not resolve host: example.test",
        "ERROR: curl: (7) Failed to connect to example.test",
        "ERROR: curl: (18) Transferred a partial file",
        "ERROR: curl: (56) Failure when receiving data from the peer",
        "ERROR: Did not get any data blocks",
    ],
)
def test_transport_failures_are_recoverable(detail: str) -> None:
    assert is_transient_network_error(detail)


@pytest.mark.parametrize(
    "detail",
    [
        "ERROR: Unable to download: HTTP Error 403: Forbidden",
        "ERROR: HTTP Error 404: Not Found",
        "ERROR: Sign in to confirm you're not a bot",
        "ERROR: no space left on device",
        "ERROR: permission denied",
        "ERROR: cookies: Failed to decrypt with DPAPI",
        "ERROR: video unavailable",
        "ERROR: unsupported URL",
        "ERROR: Requested format is not available",
        "ERROR: authentication failed after a connection timeout",
        "ERROR: curl: (23) Failed writing received data to disk",
        "ERROR: curl: (60) SSL certificate problem",
    ],
)
def test_permanent_failures_are_not_retried(detail: str) -> None:
    assert not is_transient_network_error(detail)


def test_last_error_is_not_overridden_by_previous_attempt_history() -> None:
    assert is_transient_network_error(
        "ERROR: HTTP Error 403\nERROR: [WinError 10050] Сеть отключена"
    )
    assert not is_transient_network_error("ERROR: timed out\nERROR: HTTP Error 403")
    assert not is_transient_network_error(
        "ERROR: timed out\nERROR: Requested format is not available"
    )


def make_job(tmp_path: Path) -> DownloadJob:
    return DownloadJob(
        MediaItem("https://example.test/playlist", "Playlist", MediaKind.PLAYLIST, item_count=8),
        DownloadOptions(
            tmp_path,
            playlist_intervals=(PlaylistInterval(1, 2), PlaylistInterval(5, 5)),
            use_download_archive=False,
        ),
    )


def test_transport_retry_preserves_arguments_selection_and_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"), retry_delay=0.01)
    job = make_job(tmp_path)
    arguments: list[list[str]] = []
    snapshots: list[DownloadProgress] = []

    def attempt(args: list[str], job: DownloadJob, callback: Any) -> tuple[int, str, Path | None]:
        arguments.append(list(args))
        if len(arguments) > 1:
            executor._publish(DownloadProgress(DownloadStage.VIDEO), job, callback)
        progress = DownloadProgress(
            DownloadStage.VIDEO,
            percent=50,
            overall_percent=50 if len(arguments) == 1 else 10,
            playlist_index=2,
            playlist_count=3,
        )
        executor._publish(progress, job, callback)
        return (1, "ERROR: connection reset", None) if len(arguments) == 1 else (0, "", tmp_path)

    monkeypatch.setattr(executor, "_run_attempt", attempt)

    assert executor.execute(job, snapshots.append) == tmp_path

    assert len(arguments) == 2
    assert arguments[0] == arguments[1]
    assert arguments[0][arguments[0].index("--playlist-items") + 1] == "1:2,5"
    assert "--continue" in arguments[0]
    assert "--no-overwrites" in arguments[0]
    assert "--abort-on-error" in arguments[0]
    assert "--no-skip-unavailable-fragments" in arguments[0]
    assert any(p.stage is DownloadStage.WAITING_FOR_CONNECTION for p in snapshots)
    values = [p.overall_percent for p in snapshots if p.overall_percent is not None]
    assert values == sorted(values)
    assert job.state is JobState.COMPLETED


def test_permanent_error_finishes_instead_of_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"))
    monkeypatch.setattr(executor, "_run_attempt", lambda *args: (1, "ERROR: HTTP Error 403", None))
    job = make_job(tmp_path)

    with pytest.raises(DownloadError):
        executor.execute(job)
    assert job.state is JobState.FAILED


def test_cancel_before_worker_starts_is_not_lost(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"))
    monkeypatch.setattr(executor, "_run_attempt", lambda *args: pytest.fail("must not start"))
    executor.cancel()

    with pytest.raises(DownloadCancelled):
        executor.execute(make_job(tmp_path))


def test_pause_during_network_wait_prevents_retry_until_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"), retry_delay=0.01)
    job = make_job(tmp_path)
    attempts: list[bool] = []
    paused = Event()
    result: list[object] = []

    def attempt(*args: Any) -> tuple[int, str, Path | None]:
        attempts.append(True)
        return (1, "ERROR: timed out", None) if len(attempts) == 1 else (0, "", tmp_path)

    def progress(value: DownloadProgress) -> None:
        if value.stage is DownloadStage.WAITING_FOR_CONNECTION:
            assert executor.pause()
        elif value.stage is DownloadStage.PAUSED:
            paused.set()

    monkeypatch.setattr(executor, "_run_attempt", attempt)
    worker = Thread(target=lambda: result.append(executor.execute(job, progress)))
    worker.start()
    try:
        assert paused.wait(2)
        assert attempts == [True]
        assert job.state is JobState.PAUSED
        assert worker.is_alive()
        executor.resume()
        worker.join(2)
        assert not worker.is_alive()
        assert result == [tmp_path]
        assert len(attempts) == 2
    finally:
        executor.cancel()
        executor.resume()
        worker.join(2)


def test_cancel_while_paused_wakes_worker(tmp_path: Path) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"))
    paused = Event()
    errors: list[Exception] = []
    job = make_job(tmp_path)
    assert executor.pause()

    def run() -> None:
        try:
            executor.execute(
                job, lambda p: paused.set() if p.stage is DownloadStage.PAUSED else None
            )
        except Exception as error:
            errors.append(error)

    worker = Thread(target=run)
    worker.start()
    try:
        assert paused.wait(2)
        executor.cancel()
        worker.join(2)
        assert not worker.is_alive()
        assert len(errors) == 1
        assert isinstance(errors[0], DownloadCancelled)
        assert job.state is JobState.CANCELLED
    finally:
        executor.cancel()
        executor.resume()
        worker.join(2)


def test_pause_is_refused_during_postprocessing(tmp_path: Path) -> None:
    executor = DownloadExecutor(Path("yt-dlp.exe"), Path("tools"))
    executor._publish(DownloadProgress(DownloadStage.POST_PROCESSING), make_job(tmp_path), None)

    assert executor.pause() is False
    assert not executor._pause_requested.is_set()

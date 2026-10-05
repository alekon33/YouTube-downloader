import psutil
import pytest

from videodownloader.downloader.control import ProcessSuspension


def test_suspension_stops_parent_first_and_resumes_children_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[str] = []

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def suspend(self) -> None:
            operations.append(f"suspend {self.pid}")

        def resume(self) -> None:
            operations.append(f"resume {self.pid}")

        def children(self, recursive: bool = False) -> list["Process"]:
            assert not recursive
            return [Process(13), Process(12)] if self.pid == 11 else []

    monkeypatch.setattr(psutil, "Process", Process)
    suspension = ProcessSuspension()

    suspension.suspend(11)
    suspension.resume()
    suspension.resume()

    assert operations == [
        "suspend 11",
        "suspend 12",
        "suspend 13",
        "resume 13",
        "resume 12",
        "resume 11",
    ]


def test_partial_suspension_failure_resumes_already_suspended_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[str] = []

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def suspend(self) -> None:
            if self.pid == 13:
                raise psutil.AccessDenied(self.pid)
            operations.append(f"suspend {self.pid}")

        def resume(self) -> None:
            operations.append(f"resume {self.pid}")

        def children(self, recursive: bool = False) -> list["Process"]:
            return [Process(13), Process(12)] if self.pid == 11 else []

    monkeypatch.setattr(psutil, "Process", Process)

    with pytest.raises(psutil.AccessDenied):
        ProcessSuspension().suspend(11)

    assert operations == ["suspend 11", "suspend 12", "resume 12", "resume 11"]

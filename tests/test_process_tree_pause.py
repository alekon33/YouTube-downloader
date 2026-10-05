import psutil
import pytest

from videodownloader.downloader.control import ProcessSuspension


def test_every_parent_is_frozen_before_discovering_grandchildren(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def suspend(self) -> None:
            calls.append(("suspend", self.pid))

        def children(self) -> list["Process"]:
            assert ("suspend", self.pid) in calls
            calls.append(("children", self.pid))
            return [Process(self.pid + 1)] if self.pid < 13 else []

        def resume(self) -> None:
            calls.append(("resume", self.pid))

    monkeypatch.setattr(psutil, "Process", Process)
    suspension = ProcessSuspension()
    suspension.suspend(11)
    suspension.resume()

    assert calls == [
        ("suspend", 11),
        ("children", 11),
        ("suspend", 12),
        ("children", 12),
        ("suspend", 13),
        ("children", 13),
        ("resume", 13),
        ("resume", 12),
        ("resume", 11),
    ]

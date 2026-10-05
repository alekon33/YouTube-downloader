"""Suspend only the download process tree owned by this application."""

from __future__ import annotations

import psutil


class ProcessSuspension:
    """Hold process identities, so resume cannot affect a reused Windows PID."""

    def __init__(self) -> None:
        self._suspended: list[psutil.Process] = []

    def suspend(self, pid: int) -> None:
        root = psutil.Process(pid)
        try:
            pending = [root]
            while pending:
                process = pending.pop()
                try:
                    # Freeze each parent before enumerating its direct children.
                    # A PyInstaller child can itself spawn FFmpeg; freezing only
                    # the bootloader before a recursive snapshot is not enough.
                    process.suspend()
                    self._suspended.append(process)
                    pending.extend(process.children())
                except psutil.NoSuchProcess:
                    if process is root:
                        raise
        except psutil.Error:
            self.resume()
            raise

    def resume(self) -> None:
        errors: list[psutil.Error] = []
        remaining: list[psutil.Process] = []
        # Resume descendants before the parent waiting for their output.
        for process in reversed(self._suspended):
            try:
                process.resume()
            except psutil.NoSuchProcess:
                continue
            except psutil.Error as error:
                errors.append(error)
                remaining.append(process)
        self._suspended = list(reversed(remaining))
        if errors:
            raise errors[0]

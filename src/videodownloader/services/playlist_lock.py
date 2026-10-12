"""Prevent two app instances from writing the same playlist at the same time."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO, Self

from videodownloader.core.exceptions import DownloadError


class PlaylistFolderLock:
    """An OS lock, automatically released after an application crash."""

    def __init__(self, folder: Path) -> None:
        self._path = folder / ".videodownloader.lock"
        self._stream: BinaryIO | None = None

    def __enter__(self) -> Self:
        if self._path.is_symlink() or self._path.is_junction():
            raise DownloadError("Файл блокировки папки не должен быть ссылкой.")
        stream = self._path.open("a+b")
        try:
            if self._path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise DownloadError(
                "Эта папка уже используется другой загрузкой. Остановите её перед продолжением.",
                str(error),
            ) from error
        self._stream = stream
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

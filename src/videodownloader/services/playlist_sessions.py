"""Bounded, atomically written playlist state with safe relative filenames."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from videodownloader import __version__
from videodownloader.core.exceptions import DownloadError
from videodownloader.models import Container, DownloadOptions, MediaItem, PlaylistInterval, Quality
from videodownloader.models.session import SavedPlaylist, SavedPlaylistItem

SESSION_FILE = "videodownloader-playlist.json"
QUEUE_FILE = ".videodownloader-queue.json"
ARCHIVE_FILE = ".videodownloader-archive.txt"
_MAX_BYTES = 8 * 1024 * 1024
_MAX_ITEMS = 20000
_MEDIA_EXTENSIONS = {"mp4", "mkv", "webm", "m4a", "mp3", "wav", "flv", "ogg", "opus", "mov", "avi"}


def _fail(message: str) -> DownloadError:
    return DownloadError(message, "Invalid or conflicting saved playlist")


def safe_name(value: str, limit: int = 150) -> str:
    """Create one Windows basename, not an executable output template."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(". ")
    value = (
        value.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore").rstrip(". ")
        or "Без названия"
    )
    if value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
        *(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in "¹²³"),
    }:
        value = "_" + value
    return value


def _url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 8192 or any(c.isspace() for c in value):
        raise _fail("В сохранённом задании некорректная ссылка.")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise _fail("В сохранённом задании разрешены только обычные HTTP/HTTPS-ссылки без пароля.")
    return value


def _text(value: object, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise _fail("В сохранённом задании некорректные текстовые данные.")
    return value


def _integer(value: object, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail("В сохранённом задании некорректное число.")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise _fail("В сохранённом задании некорректные параметры.")
    return value


def _basename(value: object) -> str:
    name = _text(value, 200)
    if name != safe_name(name, 200) or name in {".", ".."}:
        raise _fail("Сохранённое задание содержит небезопасное имя файла.")
    return name


def _not_link(path: Path) -> None:
    if path.is_symlink() or path.is_junction():
        raise _fail("Служебные файлы и файлы задания не должны быть ссылками на другую папку.")


def atomic_write(path: Path, text: str) -> None:
    """Replace only this owned file; a crash leaves the previous checkpoint intact."""
    _not_link(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class PlaylistSessions:
    """Create, reconcile and checkpoint one session inside the actual media folder."""

    @staticmethod
    def folder_for(media: MediaItem, options: DownloadOptions) -> Path:
        return (
            options.destination / safe_name(media.title)
            if options.create_playlist_folder
            else options.destination
        ).resolve()

    @staticmethod
    def create(
        media: MediaItem, options: DownloadOptions, selected_indices: tuple[int, ...] = ()
    ) -> SavedPlaylist:
        if not media.entries:
            raise _fail("Не удалось сохранить состав плейлиста. Повторите анализ ссылки.")
        folder = PlaylistSessions.folder_for(media, options)
        items: list[SavedPlaylistItem] = []
        used_names: set[str] = set()
        used_indices: set[int] = set()
        width = max(3, len(str(media.item_count or len(media.entries))))

        def is_selected(index: int) -> bool:
            if selected_indices:
                return index in selected_indices
            if options.playlist_intervals:
                return any(
                    i.start <= index and (i.end is None or index <= i.end)
                    for i in options.playlist_intervals
                )
            return (options.playlist_start or 1) <= index <= (options.playlist_end or 100000)

        for position, entry in enumerate(media.entries, 1):
            index = _integer(entry.playlist_index if entry.playlist_index is not None else position)
            if index in used_indices:
                raise _fail("В плейлисте повторяются номера элементов.")
            used_indices.add(index)
            if not is_selected(index):
                continue
            if entry.source_url == media.source_url or not entry.source_url:
                raise _fail(
                    f"Не удалось получить ссылку на элемент {index}. Исключите его из интервалов и повторите анализ."
                )
            stem = safe_name(
                (f"{index:0{width}d} - " if options.number_playlist_items else "") + entry.title
            )
            base_stem = stem
            suffix = 0
            while stem.casefold() in used_names:
                suffix += 1
                stem = safe_name(base_stem[:130] + f" [{index}-{suffix}]")
            used_names.add(stem.casefold())
            items.append(
                SavedPlaylistItem(
                    index,
                    _url(entry.source_url),
                    _text(entry.media_id, 200) if entry.media_id is not None else None,
                    _text(entry.extractor, 100) if entry.extractor is not None else None,
                    _text(entry.title),
                    stem,
                )
            )
        if not items or len(items) > _MAX_ITEMS or any(i.original_index > 100000 for i in items):
            raise _fail("Выбранная очередь пуста или слишком велика для сохранённого задания.")
        if media.item_count and media.item_count <= 100000:
            expected = {i for i in range(1, media.item_count + 1) if is_selected(i)}
            if expected != {i.original_index for i in items}:
                raise _fail(
                    "Состав выбранной части плейлиста получен не полностью. Повторите анализ перед загрузкой."
                )
        items.sort(key=lambda i: i.original_index)
        if len({i.original_index for i in items}) != len(items):
            raise _fail("В плейлисте повторяются номера элементов.")
        session = SavedPlaylist(
            folder,
            str(uuid4()),
            _url(media.source_url),
            _text(media.title),
            max(media.item_count or 0, max(i.original_index for i in items)),
            options,
            items,
        )
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / SESSION_FILE).exists():
            old = PlaylistSessions.load(folder)

            def identity(s: SavedPlaylist) -> object:
                return (
                    s.source_url,
                    [(i.original_index, i.source_url) for i in s.items],
                    s.options.quality,
                    s.options.container,
                    s.options.audio_only,
                    s.options.number_playlist_items,
                )

            if identity(old) != identity(session) or any(
                a.media_id and b.media_id and a.media_id != b.media_id
                for a, b in zip(old.items, session.items, strict=True)
            ):
                raise _fail(
                    "В этой папке уже сохранено другое задание. Выберите другую папку или нажмите «Докачать плейлист из папки»."
                )
            from dataclasses import replace

            old.options = replace(old.options, use_download_archive=options.use_download_archive)
            return old
        PlaylistSessions.reconcile(session)
        PlaylistSessions.save(session)
        return session

    @staticmethod
    def load(folder: Path) -> SavedPlaylist:
        folder = folder.resolve()
        path = folder / SESSION_FILE
        _not_link(path)
        if not path.is_file():
            raise _fail(
                "В этой папке нет сохранённого задания. Выберите саму папку плейлиста, начатого в версии 0.3.0 или новее."
            )
        if path.stat().st_size > _MAX_BYTES:
            raise _fail("Файл сохранённого задания слишком велик.")
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or type(data.get("schema_version")) is not int
                or data.get("schema_version") != 1
            ):
                raise _fail("Формат сохранённого задания не поддерживается.")
            UUID(_text(data["session_id"]))
            raw_options = data["options"]
            if not isinstance(raw_options, dict):
                raise ValueError("options must be an object")
            raw_intervals = raw_options["intervals"]
            if not isinstance(raw_intervals, list) or len(raw_intervals) > _MAX_ITEMS:
                raise ValueError("invalid intervals")
            intervals = tuple(
                PlaylistInterval(
                    _integer(i["start"]), None if i["end"] is None else _integer(i["end"])
                )
                for i in raw_intervals
            )
            options = DownloadOptions(
                folder,
                quality=Quality(raw_options["quality"]),
                container=Container(raw_options["container"]),
                audio_only=_boolean(raw_options["audio_only"]),
                number_playlist_items=_boolean(raw_options["number_items"]),
                use_download_archive=_boolean(raw_options["archive"]),
                create_playlist_folder=False,
                playlist_intervals=intervals,
            )
            raw_items = data["items"]
            if not isinstance(raw_items, list) or not 0 < len(raw_items) <= _MAX_ITEMS:
                raise ValueError("invalid items")
            items = []
            for raw in raw_items:
                item = SavedPlaylistItem(
                    _integer(raw["index"]),
                    _url(raw["url"]),
                    None if raw["id"] is None else _text(raw["id"], 200),
                    None if raw["extractor"] is None else _text(raw["extractor"], 100),
                    _text(raw["title"]),
                    _basename(raw["stem"]),
                    None if raw["file"] is None else _basename(raw["file"]),
                    None if raw["size"] is None else _integer(raw["size"]),
                    None if raw["mtime_ns"] is None else _integer(raw["mtime_ns"], 0),
                )
                if item.original_index > 100000 or (
                    item.completed
                    and (item.completed_size is None or item.completed_mtime_ns is None)
                ):
                    raise ValueError("invalid completion record")
                if item.completed_file and not item.completed_file.startswith(
                    item.output_stem + "."
                ):
                    raise ValueError("completion does not match stem")
                if (
                    item.completed_file
                    and Path(item.completed_file).suffix.lstrip(".") not in _MEDIA_EXTENSIONS
                ):
                    raise ValueError("partial files cannot be completed")
                items.append(item)
            if len({i.original_index for i in items}) != len(items) or len(
                {i.output_stem.casefold() for i in items}
            ) != len(items):
                raise ValueError("duplicate identities or filenames")
            if [i.original_index for i in items] != sorted(i.original_index for i in items):
                raise ValueError("unordered queue")
            session = SavedPlaylist(
                folder,
                data["session_id"],
                _url(data["url"]),
                _text(data["title"]),
                _integer(data["original_count"]),
                options,
                items,
            )
            PlaylistSessions.reconcile(session)
            return session
        except (KeyError, ValueError, TypeError, OSError) as error:
            raise DownloadError(
                "Не удалось прочитать сохранённое задание. Файл повреждён или имеет неверный формат.",
                str(error),
            ) from error

    @staticmethod
    def reconcile(session: SavedPlaylist) -> None:
        stems = {i.output_stem.casefold() for i in session.items}
        # Include .part, .ytdl and separate track files, not just final media.
        # yt-dlp must never append through a link to a file outside this folder.
        for path in session.folder.iterdir():
            candidate = path.name
            while "." in candidate:
                candidate = candidate.rsplit(".", 1)[0]
                if candidate.casefold() in stems:
                    _not_link(path)
                    if path.is_file() and path.stat().st_nlink > 1:
                        raise _fail(
                            "Файл задания связан жёсткой ссылкой с другим файлом. Используйте обычную копию перед докачкой."
                        )
                    break
        for item in session.items:
            if item.completed_file:
                path = session.folder / item.completed_file
                _not_link(path)
                if not path.exists():
                    item.completed_file = None
                    item.completed_size = item.completed_mtime_ns = None
                elif (
                    not path.is_file()
                    or path.stat().st_size != item.completed_size
                    or path.stat().st_mtime_ns != item.completed_mtime_ns
                ):
                    raise _fail(
                        f"Файл «{path.name}» изменён. Переместите его из папки перед докачкой; программа не будет его перезаписывать."
                    )
            if not item.completed:
                for extension in _MEDIA_EXTENSIONS:
                    existing = session.folder / f"{item.output_stem}.{extension}"
                    if existing.exists() or existing.is_symlink():
                        raise _fail(
                            f"Файл «{existing.name}» уже существует, но его завершение не подтверждено. Переместите его перед докачкой; недокачанные .part-файлы оставьте."
                        )

    @staticmethod
    def save(session: SavedPlaylist) -> None:
        data = {
            "schema_version": 1,
            "app_version": __version__,
            "session_id": session.session_id,
            "url": session.source_url,
            "title": session.title,
            "original_count": session.original_count,
            "options": {
                "quality": session.options.quality.value,
                "container": session.options.container.value,
                "audio_only": session.options.audio_only,
                "number_items": session.options.number_playlist_items,
                "archive": session.options.use_download_archive,
                "intervals": [
                    {"start": i.start, "end": i.end} for i in session.options.playlist_intervals
                ],
            },
            "items": [
                {
                    "index": i.original_index,
                    "url": i.source_url,
                    "id": i.media_id,
                    "extractor": i.extractor,
                    "title": i.title,
                    "stem": i.output_stem,
                    "file": i.completed_file,
                    "size": i.completed_size,
                    "mtime_ns": i.completed_mtime_ns,
                }
                for i in session.items
            ],
        }
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if len(text.encode("utf-8")) > _MAX_BYTES:
            raise _fail("Сохранённое задание слишком велико. Выберите меньше элементов плейлиста.")
        atomic_write(session.folder / SESSION_FILE, text)

    @staticmethod
    def prepare(session: SavedPlaylist) -> None:
        PlaylistSessions.reconcile(session)
        PlaylistSessions.save(session)
        session.runtime_items = session.pending_items
        queue = {
            "_type": "playlist",
            "id": session.session_id,
            "title": session.title,
            "extractor": "generic",
            "extractor_key": "Generic",
            "playlist_count": session.original_count,
            "requested_entries": [i.original_index for i in session.runtime_items],
            "entries": [
                {
                    "_type": "url_transparent",
                    "url": i.source_url,
                    "title": i.title,
                    "vd_output_id": i.output_stem,
                }
                for i in session.runtime_items
            ],
        }
        atomic_write(session.folder / QUEUE_FILE, json.dumps(queue, ensure_ascii=False))
        # Rebuild the ledger from verified files, so deleted files aren't skipped.
        completed_ids = {
            (i.extractor.casefold(), i.media_id)
            for i in session.items
            if i.completed and i.extractor and i.media_id
        }
        pending_ids = {
            (i.extractor.casefold(), i.media_id)
            for i in session.items
            if not i.completed and i.extractor and i.media_id
        }
        atomic_write(
            session.folder / ARCHIVE_FILE,
            "".join(
                f"{extractor} {media_id}\n"
                for extractor, media_id in sorted(completed_ids - pending_ids)
            ),
        )

    @staticmethod
    def record_completed(
        session: SavedPlaylist,
        ordinal: int,
        filename: str,
        media_id: str | None = None,
        extractor: str | None = None,
    ) -> None:
        if not 1 <= ordinal <= len(session.runtime_items):
            raise _fail("Загрузчик сообщил неизвестный элемент сохранённой очереди.")
        item = session.runtime_items[ordinal - 1]
        path = Path(filename)
        _not_link(path)
        if (
            path.resolve().parent != session.folder
            or not path.name.startswith(item.output_stem + ".")
            or path.suffix.lstrip(".") not in _MEDIA_EXTENSIONS
        ):
            raise _fail(
                "Готовый файл находится вне сохранённой папки или не соответствует заданию."
            )
        stat = path.stat()
        if not path.is_file() or stat.st_size <= 0:
            raise _fail("Загрузчик не создал готовый файл.")
        previous = (
            item.completed_file,
            item.completed_size,
            item.completed_mtime_ns,
            item.media_id,
            item.extractor,
        )
        item.completed_file, item.completed_size, item.completed_mtime_ns = (
            path.name,
            stat.st_size,
            stat.st_mtime_ns,
        )
        if item.media_id is None and media_id is not None and len(media_id) <= 200:
            item.media_id = media_id
        if item.extractor is None and extractor is not None and len(extractor) <= 100:
            item.extractor = extractor
        try:
            PlaylistSessions.save(session)
        except Exception:
            (
                item.completed_file,
                item.completed_size,
                item.completed_mtime_ns,
                item.media_id,
                item.extractor,
            ) = previous
            raise

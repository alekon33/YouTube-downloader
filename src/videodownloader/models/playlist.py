"""Playlist item selection expressed as user-friendly one-based intervals."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

_INTERVAL_PATTERN = re.compile(r"^(?P<start>\d+)\s*[-\u2013\u2014]\s*(?P<end>\d*)$")
_SINGLE_ITEM_PATTERN = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class PlaylistInterval:
    """An inclusive, one-based playlist interval; ``end=None`` means to the end."""

    start: int
    end: int | None = None

    def __post_init__(self) -> None:
        if self.start < 1:
            raise ValueError("Начало интервала должно быть не меньше 1.")
        if self.end is not None and self.end < 1:
            raise ValueError("Конец интервала должен быть не меньше 1.")
        if self.end is not None and self.start > self.end:
            raise ValueError("Начало интервала не может быть больше конца.")

    def to_yt_dlp_spec(self) -> str:
        """Serialize using yt-dlp's inclusive START:STOP playlist syntax."""

        if self.end is None:
            return f"{self.start}:"
        if self.end == self.start:
            return str(self.start)
        return f"{self.start}:{self.end}"


def normalize_playlist_intervals(
    intervals: Iterable[PlaylistInterval],
) -> tuple[PlaylistInterval, ...]:
    """Sort intervals and merge duplicate, overlapping, or adjacent selections."""

    supplied = tuple(intervals)
    if any(not isinstance(interval, PlaylistInterval) for interval in supplied):
        raise TypeError("Интервалы плейлиста должны иметь тип PlaylistInterval.")

    ordered = sorted(supplied, key=lambda interval: interval.start)
    if not ordered:
        return ()

    normalized: list[PlaylistInterval] = []
    for current in ordered:
        if not normalized:
            normalized.append(current)
            continue

        previous = normalized[-1]
        if previous.end is None:
            continue
        if current.start > previous.end + 1:
            normalized.append(current)
            continue

        merged_end = None if current.end is None else max(previous.end, current.end)
        normalized[-1] = PlaylistInterval(previous.start, merged_end)

    return tuple(normalized)


def parse_playlist_intervals(
    text: str,
    item_count: int | None = None,
) -> tuple[PlaylistInterval, ...]:
    """Parse ``1-5, 8-12, 20`` into normalized playlist intervals."""

    value = text.strip()
    if not value:
        return ()

    intervals: list[PlaylistInterval] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError(
                "Между интервалами найдено пустое значение. Используйте формат: 1-5, 8-12, 20."
            )

        start: int
        end: int | None
        if _SINGLE_ITEM_PATTERN.fullmatch(part):
            start = end = int(part)
        else:
            match = _INTERVAL_PATTERN.fullmatch(part)
            if match is None:
                raise ValueError(
                    f"Интервал «{part}» записан неверно. Используйте формат: 1-5, 8-12, 20."
                )
            start = int(match.group("start"))
            end_text = match.group("end")
            end = int(end_text) if end_text else None

        try:
            interval = PlaylistInterval(start, end)
        except ValueError as error:
            raise ValueError(f"Интервал «{part}»: {error}") from error

        if item_count is not None:
            last_requested = interval.end or interval.start
            if last_requested > item_count:
                raise ValueError(
                    f"Номер {last_requested} выходит за пределы плейлиста "
                    f"(всего элементов: {item_count})."
                )

        intervals.append(interval)

    return normalize_playlist_intervals(intervals)

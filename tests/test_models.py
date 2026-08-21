from pathlib import Path

import pytest

from videodownloader.models import (
    DownloadOptions,
    DownloadProgress,
    DownloadStage,
    PlaylistInterval,
    parse_playlist_intervals,
)


def test_playlist_range_rejects_reversed_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Начало диапазона"):
        DownloadOptions(destination=tmp_path, playlist_start=5, playlist_end=2)


def test_playlist_intervals_parse_and_merge_friendly_syntax() -> None:
    intervals = parse_playlist_intervals("8—12, 1-5, 5–8, 20")

    assert intervals == (PlaylistInterval(1, 12), PlaylistInterval(20, 20))


def test_playlist_intervals_support_open_end() -> None:
    intervals = parse_playlist_intervals("1-3, 5-")

    assert intervals == (PlaylistInterval(1, 3), PlaylistInterval(5))
    assert intervals[1].to_yt_dlp_spec() == "5:"


def test_playlist_intervals_allow_open_end_with_known_playlist_size() -> None:
    assert parse_playlist_intervals("5–", item_count=20) == (PlaylistInterval(5),)


def test_playlist_intervals_allow_last_known_item() -> None:
    assert parse_playlist_intervals("20", item_count=20) == (PlaylistInterval(20, 20),)


def test_playlist_intervals_empty_input_selects_entire_playlist() -> None:
    assert parse_playlist_intervals("   ") == ()


@pytest.mark.parametrize("value", ["0", "5-2", "one-two", "1,,3", "-5"])
def test_playlist_intervals_reject_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        parse_playlist_intervals(value)


def test_playlist_intervals_reject_item_beyond_known_playlist() -> None:
    with pytest.raises(ValueError, match="всего элементов: 12"):
        parse_playlist_intervals("5-13", item_count=12)


def test_download_options_normalize_explicit_playlist_intervals(tmp_path: Path) -> None:
    options = DownloadOptions(
        destination=tmp_path,
        playlist_intervals=(PlaylistInterval(5, 9), PlaylistInterval(1, 5)),
    )

    assert options.playlist_intervals == (PlaylistInterval(1, 9),)


def test_download_options_reject_intervals_with_legacy_range(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="одновременно"):
        DownloadOptions(
            destination=tmp_path,
            playlist_intervals=(PlaylistInterval(1, 5),),
            playlist_start=1,
        )


def test_progress_rejects_percentage_above_one_hundred() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        DownloadProgress(stage=DownloadStage.VIDEO, percent=100.1)

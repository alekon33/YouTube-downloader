from pathlib import Path

import pytest

from videodownloader.models import DownloadOptions, DownloadProgress, DownloadStage


def test_playlist_range_rejects_reversed_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Начало диапазона"):
        DownloadOptions(destination=tmp_path, playlist_start=5, playlist_end=2)


def test_progress_rejects_percentage_above_one_hundred() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        DownloadProgress(stage=DownloadStage.VIDEO, percent=100.1)


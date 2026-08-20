from pathlib import Path

from videodownloader.models import AppSettings, Container, Quality, Theme
from videodownloader.settings import AppPaths, SettingsService


def test_settings_round_trip(tmp_path: Path) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    service = SettingsService(paths)
    expected = AppSettings(
        destination=tmp_path / "media",
        quality=Quality.UHD_2160,
        container=Container.MKV,
        theme=Theme.DARK,
        create_playlist_folder=False,
    )

    service.save(expected)

    assert service.load() == expected


def test_invalid_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    service = SettingsService(paths)
    service.settings_path.parent.mkdir(parents=True)
    service.settings_path.write_text("not-json", encoding="utf-8")

    assert service.load() == service.defaults()

import json
from pathlib import Path

from videodownloader.models import AppSettings, Container, CookieBrowser, Quality
from videodownloader.settings import AppPaths, SettingsService


def test_settings_round_trip(tmp_path: Path) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    service = SettingsService(paths)
    expected = AppSettings(
        destination=tmp_path / "media",
        quality=Quality.UHD_2160,
        container=Container.MKV,
        audio_only=True,
        minimize_to_tray=False,
        cookie_browser=CookieBrowser.FIREFOX,
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


def test_legacy_theme_setting_is_ignored_and_removed_on_save(tmp_path: Path) -> None:
    paths = AppPaths.from_data_dir(tmp_path / "app", tmp_path / "downloads")
    service = SettingsService(paths)
    service.settings_path.parent.mkdir(parents=True)
    service.settings_path.write_text(
        json.dumps(
            {
                "destination": str(tmp_path / "media"),
                "quality": Quality.HD_720.value,
                "container": Container.MKV.value,
                "theme": "dark",
            }
        ),
        encoding="utf-8",
    )

    loaded = service.load()
    service.save(loaded)
    persisted = json.loads(service.settings_path.read_text(encoding="utf-8"))

    assert loaded.quality is Quality.HD_720
    assert loaded.container is Container.MKV
    assert "theme" not in persisted


def test_unknown_cookie_browser_does_not_reset_other_settings(tmp_path: Path) -> None:
    loaded = AppSettings.from_dict(
        {
            "quality": Quality.HD_720.value,
            "container": Container.MKV.value,
            "cookie_browser": "unknown-browser",
        },
        tmp_path,
    )

    assert loaded.quality is Quality.HD_720
    assert loaded.container is Container.MKV
    assert loaded.cookie_browser is None


def test_legacy_settings_default_to_video_mode(tmp_path: Path) -> None:
    loaded = AppSettings.from_dict(
        {
            "quality": Quality.HD_720.value,
            "container": Container.MKV.value,
        },
        tmp_path,
    )

    assert loaded.audio_only is False
    assert loaded.quality is Quality.HD_720
    assert loaded.container is Container.MKV


def test_invalid_audio_only_setting_defaults_to_video_mode(tmp_path: Path) -> None:
    loaded = AppSettings.from_dict({"audio_only": "true"}, tmp_path)

    assert loaded.audio_only is False


def test_legacy_settings_enable_tray_without_resetting_options(tmp_path: Path) -> None:
    loaded = AppSettings.from_dict({"audio_only": True}, tmp_path)

    assert loaded.minimize_to_tray is True
    assert loaded.audio_only is True


def test_invalid_tray_setting_uses_default(tmp_path: Path) -> None:
    loaded = AppSettings.from_dict({"minimize_to_tray": "false"}, tmp_path)

    assert loaded.minimize_to_tray is True

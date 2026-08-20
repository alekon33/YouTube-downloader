import hashlib
import zipfile
from pathlib import Path

import pytest

from videodownloader.core.exceptions import ToolUnavailableError
from videodownloader.tools import ToolManager, ToolManifest, ToolStatus, validate_sha256


def test_checksum_validation(tmp_path: Path) -> None:
    artifact = tmp_path / "tool.exe"
    artifact.write_bytes(b"trusted artifact")
    expected = hashlib.sha256(b"trusted artifact").hexdigest()

    assert validate_sha256(artifact, expected)
    assert not validate_sha256(artifact, "0" * 64)


def test_manifest_rejects_non_https_url() -> None:
    with pytest.raises(ValueError, match="Insecure"):
        ToolManifest.from_dict(
            {
                "schema_version": 1,
                "tools": {
                    "example": {
                        "version": "1",
                        "url": "http://example.test/tool.exe",
                        "sha256": "0" * 64,
                        "architecture": "x86_64",
                        "archive": False,
                    }
                },
            }
        )


def test_tool_manager_uses_private_absolute_paths(tmp_path: Path) -> None:
    manager = ToolManager(tmp_path.resolve())

    assert manager.yt_dlp_path == tmp_path.resolve() / "yt-dlp.exe"
    assert manager.ffmpeg_path == tmp_path.resolve() / "ffmpeg.exe"
    assert manager.ffprobe_path == tmp_path.resolve() / "ffprobe.exe"
    assert manager.deno_path == tmp_path.resolve() / "deno.exe"


def test_deno_archive_is_extracted_and_validated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = ToolManager(tmp_path)
    archive = tmp_path / "deno.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("deno.exe", b"deno executable")
    monkeypatch.setattr(manager, "_version", lambda executable, argument: "deno 2.9.5")

    manager._install_deno_archive(archive)

    assert manager.deno_path.read_bytes() == b"deno executable"


def test_ensure_all_preserves_valid_newer_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = ToolManager(tmp_path)
    monkeypatch.setattr(
        manager,
        "status",
        lambda: {
            "yt-dlp": ToolStatus(
                "yt-dlp", manager.yt_dlp_path, True, "2099.01.01", True
            )
        },
    )

    installed: list[str] = []
    monkeypatch.setattr(manager, "install", lambda name, progress=None: installed.append(name))
    manager.ensure_all()

    assert installed == []


def test_failed_executable_validation_restores_previous_version(tmp_path: Path) -> None:
    source = tmp_path / "new.exe"
    destination = tmp_path / "tool.exe"
    source.write_bytes(b"new")
    destination.write_bytes(b"working previous")

    with pytest.raises(ToolUnavailableError, match="Executable validation failed"):
        ToolManager._atomic_replace(source, destination, validator=lambda: False)

    assert destination.read_bytes() == b"working previous"

"""Installation, integrity checks, and discovery for external executables."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from videodownloader.core.exceptions import ToolUnavailableError
from videodownloader.tools.manifest import ToolAsset, ToolManifest

ProgressCallback = Callable[[str, int, int | None], None]


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Installed-state snapshot for the preparation screen."""

    name: str
    path: Path
    installed: bool
    version: str | None
    valid: bool


def validate_sha256(path: Path, expected: str) -> bool:
    """Validate a file without loading a potentially large artifact into memory."""

    return file_sha256(path) == expected.lower()


def file_sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for an artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


class ToolManager:
    """Own trusted paths and lifecycle operations for yt-dlp and FFmpeg."""

    def __init__(self, tools_dir: Path, manifest: ToolManifest | None = None) -> None:
        self.tools_dir = tools_dir
        self.manifest = manifest or ToolManifest.packaged()
        self._installed_state_path = tools_dir / "installed-tools.json"

    @property
    def yt_dlp_path(self) -> Path:
        return self.tools_dir / "yt-dlp.exe"

    @property
    def ffmpeg_path(self) -> Path:
        return self.tools_dir / "ffmpeg.exe"

    @property
    def ffprobe_path(self) -> Path:
        return self.tools_dir / "ffprobe.exe"

    def status(self) -> dict[str, ToolStatus]:
        installed_state = self._load_installed_state()
        yt_dlp_exists = self.yt_dlp_path.is_file()
        ffmpeg_exists = self.ffmpeg_path.is_file() and self.ffprobe_path.is_file()
        yt_dlp_valid = yt_dlp_exists and self._matches_record(
            self.yt_dlp_path, installed_state.get("yt-dlp", {}).get("sha256")
        )
        ffmpeg_valid = (
            ffmpeg_exists
            and self._matches_record(
                self.ffmpeg_path, installed_state.get("ffmpeg", {}).get("ffmpeg_sha256")
            )
            and self._matches_record(
                self.ffprobe_path, installed_state.get("ffmpeg", {}).get("ffprobe_sha256")
            )
        )
        return {
            "yt-dlp": ToolStatus(
                "yt-dlp",
                self.yt_dlp_path,
                yt_dlp_exists,
                self._version(self.yt_dlp_path, "--version") if yt_dlp_valid else None,
                yt_dlp_valid,
            ),
            "ffmpeg": ToolStatus(
                "ffmpeg",
                self.ffmpeg_path,
                ffmpeg_exists,
                self._version(self.ffmpeg_path, "-version") if ffmpeg_valid else None,
                ffmpeg_valid,
            ),
        }

    def all_available(self) -> bool:
        return all(item.installed and item.valid and item.version for item in self.status().values())

    def require_tools(self) -> None:
        missing = [
            item.name for item in self.status().values() if not item.installed or not item.valid
        ]
        if missing:
            raise ToolUnavailableError(
                "Необходимо подготовить компоненты приложения.",
                f"Missing external tools: {', '.join(missing)}",
            )

    def install_all(self, progress: ProgressCallback | None = None) -> None:
        self.install("yt-dlp", progress)
        self.install("ffmpeg", progress)

    def ensure_all(self, progress: ProgressCallback | None = None) -> None:
        """Install only missing or invalid tools, preserving newer valid versions."""

        for name, status in self.status().items():
            if not status.installed or not status.valid or not status.version:
                self.install(name, progress)

    def install(self, name: str, progress: ProgressCallback | None = None) -> None:
        """Download, validate, and atomically install one pinned tool artifact."""

        try:
            asset = self.manifest.tools[name]
        except KeyError as error:
            raise ValueError(f"Unknown tool: {name}") from error
        self.install_asset(asset, progress)

    def install_asset(self, asset: ToolAsset, progress: ProgressCallback | None = None) -> None:
        """Install a trusted dynamically discovered release asset."""

        self.tools_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._download(asset, progress)
        try:
            if not validate_sha256(temporary, asset.sha256):
                raise ToolUnavailableError(
                    "Проверка целостности компонента не пройдена.",
                    f"SHA-256 mismatch for {asset.name}",
                )
            if asset.archive:
                self._install_ffmpeg_archive(temporary)
                self._record_install(
                    "ffmpeg",
                    {
                        "version": asset.version,
                        "ffmpeg_sha256": file_sha256(self.ffmpeg_path),
                        "ffprobe_sha256": file_sha256(self.ffprobe_path),
                    },
                )
            else:
                self._atomic_replace(
                    temporary,
                    self.yt_dlp_path,
                    validator=lambda: self._version(self.yt_dlp_path, "--version") is not None,
                )
                self._record_install(
                    "yt-dlp",
                    {"version": asset.version, "sha256": file_sha256(self.yt_dlp_path)},
                )
        finally:
            temporary.unlink(missing_ok=True)

    def _download(self, asset: ToolAsset, progress: ProgressCallback | None) -> Path:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{asset.name}-", suffix=".download", dir=self.tools_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        request = urllib.request.Request(
            asset.url,
            headers={"User-Agent": "VideoDownloader/0.1 (+https://github.com/)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as out:
                raw_total = response.headers.get("Content-Length")
                total = int(raw_total) if raw_total and raw_total.isdigit() else None
                downloaded = 0
                while chunk := response.read(1024 * 256):
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(asset.name, downloaded, total)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return temporary

    def _load_installed_state(self) -> dict[str, dict[str, str]]:
        try:
            payload = json.loads(self._installed_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(name): {str(key): str(value) for key, value in record.items()}
            for name, record in payload.items()
            if isinstance(record, dict)
        }

    def _record_install(self, name: str, record: dict[str, str]) -> None:
        state = self._load_installed_state()
        state[name] = record
        temporary = self._installed_state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self._installed_state_path)

    @staticmethod
    def _matches_record(path: Path, expected: object) -> bool:
        return isinstance(expected, str) and len(expected) == 64 and validate_sha256(path, expected)

    def _install_ffmpeg_archive(self, archive: Path) -> None:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.namelist()
            ffmpeg_member = next((item for item in members if item.endswith("/bin/ffmpeg.exe")), None)
            ffprobe_member = next((item for item in members if item.endswith("/bin/ffprobe.exe")), None)
            if not ffmpeg_member or not ffprobe_member:
                raise ToolUnavailableError(
                    "Архив FFmpeg имеет неожиданный формат.",
                    "ffmpeg.exe or ffprobe.exe is missing from the archive",
                )
            staging = Path(tempfile.mkdtemp(prefix="ffmpeg-", dir=self.tools_dir))
            try:
                staged_ffmpeg = staging / "ffmpeg.exe"
                staged_ffprobe = staging / "ffprobe.exe"
                with bundle.open(ffmpeg_member) as source, staged_ffmpeg.open("wb") as target:
                    shutil.copyfileobj(source, target)
                with bundle.open(ffprobe_member) as source, staged_ffprobe.open("wb") as target:
                    shutil.copyfileobj(source, target)
                self._atomic_replace_pair(
                    (staged_ffmpeg, self.ffmpeg_path),
                    (staged_ffprobe, self.ffprobe_path),
                    validator=lambda: (
                        self._version(self.ffmpeg_path, "-version") is not None
                        and self._version(self.ffprobe_path, "-version") is not None
                    ),
                )
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def _atomic_replace_pair(
        self,
        *pairs: tuple[Path, Path],
        validator: Callable[[], bool] | None = None,
    ) -> None:
        backups: list[tuple[Path, Path]] = []
        replaced: list[Path] = []
        try:
            for source, destination in pairs:
                backup = destination.with_suffix(destination.suffix + ".previous")
                backup.unlink(missing_ok=True)
                if destination.exists():
                    os.replace(destination, backup)
                    backups.append((backup, destination))
                os.replace(source, destination)
                replaced.append(destination)
            if validator is not None and not validator():
                raise ToolUnavailableError(
                    "Установленный компонент не запускается.",
                    "Executable validation failed after installation",
                )
        except Exception:
            for destination in reversed(replaced):
                destination.unlink(missing_ok=True)
            for backup, destination in reversed(backups):
                if backup.exists():
                    os.replace(backup, destination)
            raise
        for backup, _ in backups:
            backup.unlink(missing_ok=True)

    @staticmethod
    def _atomic_replace(
        source: Path,
        destination: Path,
        validator: Callable[[], bool] | None = None,
    ) -> None:
        backup = destination.with_suffix(destination.suffix + ".previous")
        backup.unlink(missing_ok=True)
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(source, destination)
            if validator is not None and not validator():
                raise ToolUnavailableError(
                    "Установленный компонент не запускается.",
                    "Executable validation failed after installation",
                )
        except Exception:
            destination.unlink(missing_ok=True)
            if backup.exists():
                os.replace(backup, destination)
            raise
        backup.unlink(missing_ok=True)

    @staticmethod
    def _version(executable: Path, argument: str) -> str | None:
        if not executable.is_file():
            return None
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                [str(executable), argument],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                shell=False,
                creationflags=creation_flags,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        if executable.name.casefold() == "ffmpeg.exe" and first_line.startswith("ffmpeg version "):
            return first_line.split()[2]
        return first_line.strip() or None

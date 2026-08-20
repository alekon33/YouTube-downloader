"""Official GitHub release discovery for independent yt-dlp updates."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from videodownloader.core.exceptions import ToolUnavailableError
from videodownloader.tools.manifest import ToolAsset

LATEST_RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"


@dataclass(frozen=True, slots=True)
class YtDlpUpdate:
    """A newer official yt-dlp Windows release."""

    installed_version: str
    asset: ToolAsset
    release_page: str


class YtDlpReleaseClient:
    """Resolve the latest stable Windows executable from the official repository."""

    def latest_asset(self) -> tuple[ToolAsset, str]:
        request = urllib.request.Request(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "VideoDownloader/0.1",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise ToolUnavailableError(
                "Не удалось проверить обновление yt-dlp.", str(error)
            ) from error
        if not isinstance(payload, dict):
            raise ToolUnavailableError(
                "Не удалось проверить обновление yt-dlp.", "Invalid GitHub API response"
            )
        return parse_latest_release(payload)

    def check(self, installed_version: str) -> YtDlpUpdate | None:
        asset, release_page = self.latest_asset()
        if _version_key(asset.version) <= _version_key(installed_version):
            return None
        return YtDlpUpdate(installed_version, asset, release_page)


def parse_latest_release(payload: dict[str, Any]) -> tuple[ToolAsset, str]:
    """Parse only the official x86-64 executable and its GitHub-provided digest."""

    version = str(payload.get("tag_name") or "")
    release_page = str(payload.get("html_url") or "")
    assets = payload.get("assets")
    if not version or not isinstance(assets, list):
        raise ToolUnavailableError(
            "Не удалось проверить обновление yt-dlp.", "Release metadata is incomplete"
        )
    executable = next(
        (
            asset
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") == "yt-dlp.exe"
        ),
        None,
    )
    if not executable:
        raise ToolUnavailableError(
            "Не удалось проверить обновление yt-dlp.", "yt-dlp.exe release asset is missing"
        )
    digest = str(executable.get("digest") or "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ToolUnavailableError(
            "Не удалось проверить подпись обновления yt-dlp.",
            "GitHub release asset has no SHA-256 digest",
        )
    asset = ToolAsset(
        name="yt-dlp",
        version=version,
        url=str(executable.get("browser_download_url") or ""),
        sha256=digest.removeprefix("sha256:").lower(),
        architecture="x86_64",
        archive=False,
    )
    if not asset.url.startswith("https://github.com/yt-dlp/yt-dlp/releases/download/"):
        raise ToolUnavailableError(
            "Источник обновления yt-dlp не прошёл проверку.", asset.url
        )
    return asset, release_page


def _version_key(value: str) -> tuple[int, ...]:
    pieces = value.replace("-", ".").split(".")
    return tuple(int(piece) if piece.isdigit() else 0 for piece in pieces)

import urllib.request
import zipfile
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
from pytestqt.qtbot import QtBot

from videodownloader.settings import AppPaths
from videodownloader.tools import ToolManager, ToolManifest
from videodownloader.ui.controller import AppController
from videodownloader.ui.dialogs import PreparationDialog


def test_first_run_keeps_yt_dlp_and_can_retry_unavailable_ffmpeg(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def archive(*filenames: str) -> bytes:
        with BytesIO() as output:
            with zipfile.ZipFile(output, "w") as bundle:
                for filename in filenames:
                    bundle.writestr(filename, b"test binary")
            return output.getvalue()

    downloads = {
        "yt-dlp": b"test yt-dlp",
        "ffmpeg": archive("build/bin/ffmpeg.exe", "build/bin/ffprobe.exe"),
        "deno": archive("deno.exe"),
    }
    manifest = ToolManifest.packaged()
    manifest = replace(
        manifest,
        tools={
            name: replace(asset, sha256=sha256(downloads[name]).hexdigest())
            for name, asset in manifest.tools.items()
        },
    )
    names_by_url = {asset.url: name for name, asset in manifest.tools.items()}
    requests: list[str] = []

    class Response(BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.headers = {"Content-Length": str(len(data))}

    def open_artifact(request: urllib.request.Request, timeout: float) -> Response:
        name = names_by_url[request.full_url]
        if name == "ffmpeg" and name not in requests:
            requests.append(name)
            raise HTTPError(request.full_url, 404, "Not Found", None, None)
        requests.append(name)
        return Response(downloads[name])

    paths = AppPaths.from_data_dir(tmp_path)
    manager = ToolManager(paths.tools_dir, manifest)
    monkeypatch.setattr(urllib.request, "urlopen", open_artifact)
    monkeypatch.setattr(manager, "_version", lambda *args: "test version")
    controller = AppController(paths, manager)
    dialog = PreparationDialog(controller)
    qtbot.addWidget(dialog)
    statuses: list[str] = []
    controller.tool_progress.connect(lambda *_: statuses.append(dialog._status.text()))

    try:
        with qtbot.waitSignal(controller.tools_failed):
            dialog.open()
        assert dialog.isVisible() and dialog._retry.isVisible()
        assert "ffmpeg" in dialog._status.text().lower()
        assert "404" in dialog._status.text()
        assert "Проверка и установка yt-dlp…" in statuses
        assert "Загрузка FFmpeg…" in statuses
        assert manager.yt_dlp_path.is_file()

        with qtbot.waitSignal(dialog.accepted):
            dialog._retry.click()
        assert requests == ["yt-dlp", "ffmpeg", "ffmpeg", "deno"]
        assert manager.all_available()
        assert not list(paths.tools_dir.glob("*.download"))
    finally:
        controller.shutdown()
        qtbot.waitUntil(lambda: not controller._threads)

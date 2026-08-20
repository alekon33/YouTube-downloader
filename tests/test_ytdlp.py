import json
import subprocess
from pathlib import Path

import pytest

from videodownloader.core.exceptions import MetadataError
from videodownloader.downloader import YtDlpService
from videodownloader.models import CookieBrowser


def test_analysis_arguments_are_a_safe_list(tmp_path: Path) -> None:
    deno = tmp_path / "deno.exe"
    service = YtDlpService(
        tmp_path / "yt-dlp.exe",
        tmp_path,
        deno,
        CookieBrowser.FIREFOX,
    )

    arguments = service.analysis_arguments("https://example.test/watch?v=1&list=2")

    assert isinstance(arguments, list)
    assert arguments[-2] == "--"
    assert arguments[-1] == "https://example.test/watch?v=1&list=2"
    assert "--dump-single-json" in arguments
    assert arguments[arguments.index("--js-runtimes") + 1] == f"deno:{deno}"
    assert arguments[arguments.index("--remote-components") + 1] == "ejs:github"
    assert arguments[arguments.index("--cookies-from-browser") + 1] == "firefox"


def test_analyze_parses_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "yt-dlp.exe"
    executable.touch()
    service = YtDlpService(executable, tmp_path)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[str(executable)],
            returncode=0,
            stdout=json.dumps({"id": "x", "title": "Title", "formats": []}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert service.analyze("https://example.test/x").title == "Title"


def test_invalid_url_is_rejected_before_process_start(tmp_path: Path) -> None:
    service = YtDlpService(tmp_path / "yt-dlp.exe", tmp_path)

    with pytest.raises(MetadataError, match="Invalid media URL"):
        service.analysis_arguments("not a URL")


def test_bot_confirmation_has_actionable_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "yt-dlp.exe"
    executable.touch()
    service = YtDlpService(executable, tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="ERROR: Sign in to confirm you're not a bot",
        ),
    )

    with pytest.raises(MetadataError) as caught:
        service.analyze("https://www.youtube.com/watch?v=test")

    assert "Выберите браузер" in caught.value.user_message

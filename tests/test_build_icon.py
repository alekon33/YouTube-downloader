import shutil
from pathlib import Path

from PySide6.QtGui import QImage
from scripts.render_icon import render_icon


def test_icon_build_creates_missing_assets_directory(qapp: object, tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "src/videodownloader/resources/icon.svg"
    target = tmp_path / "src/videodownloader/resources/icon.svg"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    assert not (tmp_path / "assets").exists()

    render_icon(tmp_path)

    for name in ("icon.png", "icon.ico"):
        image = QImage(str(tmp_path / "assets" / name))
        assert not image.isNull()
        assert image.width() == 256
        assert image.height() == 256


def test_rebuilding_icon_keeps_other_assets(qapp: object, tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "src/videodownloader/resources/icon.svg"
    target = tmp_path / "src/videodownloader/resources/icon.svg"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    marker = tmp_path / "assets/keep.txt"
    marker.parent.mkdir()
    marker.write_text("preserved", encoding="utf-8")

    render_icon(tmp_path)
    render_icon(tmp_path)

    assert marker.read_text(encoding="utf-8") == "preserved"

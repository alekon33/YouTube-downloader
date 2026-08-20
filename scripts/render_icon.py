"""Render the editable SVG application icon into Windows build formats."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = root / "assets" / "icon.svg"
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG icon: {source}")
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    outputs = (root / "assets" / "icon.png", root / "assets" / "icon.ico")
    for output in outputs:
        if not image.save(str(output)):
            raise RuntimeError(f"Qt could not write icon format: {output.suffix}")
    return 0


if __name__ == "__main__":
    application = QGuiApplication(sys.argv[:1])
    raise SystemExit(main())


"""Render the vector icon into PNG and a multi-resolution Windows ICO."""
from pathlib import Path
import struct

from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    app = QCoreApplication.instance() or QCoreApplication([])
    assets = Path(__file__).resolve().parents[1] / "pdflinker" / "assets"
    renderer = QSvgRenderer(str(assets / "icon.svg"))
    if not renderer.isValid():
        raise RuntimeError("Unable to read the SVG icon.")
    sizes, frames = (16, 24, 32, 48, 64, 128, 256), []
    for size in sizes:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Unable to encode the icon.")
        frames.append(bytes(data))
    offset, entries = 6 + 16 * len(sizes), []
    for size, frame in zip(sizes, frames):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    (assets / "icon.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(frames))
    (assets / "icon.png").write_bytes(frames[-1])
    print("Generated icon.ico and icon.png")


if __name__ == "__main__":
    main()

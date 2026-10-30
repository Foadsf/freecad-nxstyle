# SPDX-License-Identifier: LGPL-2.1-or-later
"""Render authored icon SVGs at actual toolbar sizes; requires PySide6, no FreeCAD."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtGui, QtWidgets, QtSvg
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont)
    # Qt's Windows offscreen plugin may start without a system font database.
    # Load a local system font explicitly rather than exporting unreadable boxes.
    if os.name == "nt" or not QtGui.QRawFont.fromFont(font).supportsCharacter(ord("A")):
        folders = QtCore.QStandardPaths.standardLocations(QtCore.QStandardPaths.FontsLocation)
        if os.environ.get("WINDIR"):
            folders.append(str(Path(os.environ["WINDIR"]) / "Fonts"))
        for folder in folders:
            for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
                path = Path(folder) / name
                if path.is_file():
                    font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
                    families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        font = QtGui.QFont(families[0])
                        break
            if QtGui.QRawFont.fromFont(font).supportsCharacter(ord("A")):
                break
    if not QtGui.QRawFont.fromFont(font).supportsCharacter(ord("A")):
        raise RuntimeError("No readable system font; use a Qt platform with fonts available")
    font.setPointSize(10)
    root = Path(__file__).resolve().parents[1] / "NXStyle/nxstyle/resources/icons/nx"
    files = sorted(root.glob("*.svg"))
    if not files:
        parser.error("no authored SVG icons found")
    columns, cell_w, cell_h = 4, 280, 116
    rows = (len(files) + columns - 1) // columns
    image = QtGui.QImage(columns * cell_w, rows * cell_h + 48, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#f4f6f8"))
    painter = QtGui.QPainter(image)
    painter.setPen(QtGui.QColor("#263b4e"))
    painter.setFont(font)
    painter.drawText(16, 25, "NXStyle original icons | 16 / 24 / 32 / 44 px + disabled 32 px")
    for i, path in enumerate(files):
        if not QtSvg.QSvgRenderer(str(path)).isValid():
            raise ValueError(f"Invalid SVG: {path}")
        x, y = i % columns * cell_w, i // columns * cell_h + 48
        painter.fillRect(x + 4, y, cell_w - 8, cell_h - 6, QtGui.QColor("white"))
        painter.drawText(x + 14, y + 21, path.stem)
        icon = QtGui.QIcon(str(path))
        offset = 14
        for size, mode in [(s, QtGui.QIcon.Normal) for s in (16, 24, 32, 44)] + [(32, QtGui.QIcon.Disabled)]:
            icon.paint(painter, QtCore.QRect(x + offset, y + 38, size, size), QtCore.Qt.AlignCenter, mode)
            offset += size + 12
    painter.end()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(args.out)):
        raise OSError(f"Cannot save {args.out}")
    print(f"Rendered {len(files)} icons at four sizes and disabled state ({font.family()}): {args.out}")
    del app


if __name__ == "__main__":
    main()

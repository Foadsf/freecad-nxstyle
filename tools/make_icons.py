#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Render NX-Style's own mark (docs/ui/img/logo.svg) into the icons the release bundles carry:

    packaging/icons/nxstyle.ico    Windows: the launcher's .exe resource (16-256 px, PNG-compressed entries)
    packaging/icons/nxstyle.icns   macOS: NX-Style.app (16-1024 px)
    packaging/icons/nxstyle.png    Linux: the AppImage and its desktop entry (256 px)

The files are committed, so building a release needs no SVG renderer; rerun ``python tools/make_icons.py``
after changing the logo. Needs PySide6 (with QtSvg); renders differ slightly between Qt versions, so the files
are not compared byte for byte anywhere. .ico and .icns are written by hand: both are a small header around PNG images.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "docs" / "ui" / "img" / "logo.svg"
OUT = ROOT / "packaging" / "icons"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# icns OSType per pixel size of a PNG entry (the @2x types reuse the larger render)
ICNS_TYPES = (("icp4", 16), ("icp5", 32), ("ic11", 32), ("icp6", 64), ("ic07", 128), ("ic12", 64),
              ("ic08", 256), ("ic13", 256), ("ic09", 512), ("ic14", 512), ("ic10", 1024))


def render(size: int) -> bytes:
    """The logo as a PNG of size x size pixels, transparent outside the mark."""
    from PySide6 import QtCore, QtGui, QtSvg

    renderer = QtSvg.QSvgRenderer(str(LOGO))
    if not renderer.isValid():
        raise SystemExit(f"cannot read {LOGO}")
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    renderer.render(p, QtCore.QRectF(0, 0, size, size))
    p.end()
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def ico(pngs: dict[int, bytes]) -> bytes:
    """ICONDIR + one ICONDIRENTRY per size, each pointing at a PNG (Windows Vista and later read these)."""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(pngs)
    for size, data in sorted(pngs.items()):
        dim = 0 if size >= 256 else size            # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


def icns(pngs: dict[int, bytes]) -> bytes:
    body = b"".join(struct.pack(">4sI", t.encode(), 8 + len(pngs[s])) + pngs[s] for t, s in ICNS_TYPES)
    return struct.pack(">4sI", b"icns", 8 + len(body)) + body


def build() -> dict[str, bytes]:
    from PySide6 import QtGui

    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication(["make_icons", "-platform", "offscreen"])
    sizes = sorted(set(ICO_SIZES) | {s for _t, s in ICNS_TYPES})
    pngs = {s: render(s) for s in sizes}
    return {
        "nxstyle.ico": ico({s: pngs[s] for s in ICO_SIZES}),
        "nxstyle.icns": icns(pngs),
        "nxstyle.png": pngs[256],
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    files = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"wrote packaging/icons/{name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

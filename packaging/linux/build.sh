#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Build NX-Style-<version>-linux-<arch>.AppImage: FreeCAD's AppImage, unpacked, with NX-Style added and an AppRun
# of NX-Style's own in front of FreeCAD's, packed again. Run on the target architecture (x86_64 or aarch64):
#     packaging/linux/build.sh <x86_64|aarch64> <output folder>
set -euo pipefail

ARCH="${1:?usage: build.sh <x86_64|aarch64> <output folder>}"
OUT="$(mkdir -p "${2:?output folder}" && cd "$2" && pwd)"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/packaging/linux"
WORK="${WORK:-$ROOT/build/release-linux-$ARCH}"
VERSION="$(python3 "$ROOT/packaging/bundle.py" version)"
NAME="NX-Style-$VERSION-linux-$ARCH"

case "$ARCH" in
    x86_64) TOOL_SHA=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 ;;
    aarch64) TOOL_SHA=f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158 ;;
    *) echo "unknown architecture $ARCH" >&2; exit 2 ;;
esac
[ "$(uname -m)" = "$ARCH" ] || { echo "build $ARCH on an $ARCH machine, not $(uname -m)" >&2; exit 2; }

mkdir -p "$WORK"
cd "$WORK"
rm -rf AppDir squashfs-root

python3 "$ROOT/packaging/bundle.py" fetch "linux-$ARCH" dl
FREECAD_IMG="$(ls dl/FreeCAD_*-Linux-"$ARCH"-*.AppImage)"
chmod +x "$FREECAD_IMG"
"$FREECAD_IMG" --appimage-extract >/dev/null          # unpacks without FUSE
mv squashfs-root AppDir

# FreeCAD's AppRun stays, renamed; NX-Style's goes in front of it
mv AppDir/AppRun AppDir/AppRun.freecad
install -m 755 "$HERE/AppRun" AppDir/AppRun
install -D -m 644 "$HERE/glprobe.py" AppDir/usr/libexec/nxstyle/glprobe.py
python3 "$ROOT/packaging/bundle.py" stage AppDir/usr/share/nxstyle

# NX-Style's desktop entry and icon replace FreeCAD's at the top (FreeCAD's stay in usr/share)
rm -f AppDir/*.desktop AppDir/*.svg AppDir/*.png AppDir/.DirIcon
sed "s/@VERSION@/$VERSION/" "$HERE/nxstyle.desktop" > AppDir/nxstyle.desktop
install -m 644 "$ROOT/packaging/icons/nxstyle.png" AppDir/nxstyle.png
ln -s nxstyle.png AppDir/.DirIcon
install -D -m 644 "$ROOT/packaging/icons/nxstyle.png" AppDir/usr/share/icons/hicolor/256x256/apps/nxstyle.png
install -D -m 644 AppDir/nxstyle.desktop AppDir/usr/share/applications/nxstyle.desktop

# appimagetool 1.9.1, checked against the digest its release publishes
TOOL="$WORK/appimagetool-$ARCH.AppImage"
if [ ! -f "$TOOL" ] || ! echo "$TOOL_SHA  $TOOL" | sha256sum -c --quiet; then
    curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-$ARCH.AppImage"
    echo "$TOOL_SHA  $TOOL" | sha256sum -c
fi
chmod +x "$TOOL"

# zstd at FreeCAD's own level; no update information (the release page is the update channel)
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" --no-appstream --comp zstd \
    --mksquashfs-opt -Xcompression-level --mksquashfs-opt 22 \
    AppDir "$OUT/$NAME.AppImage"
chmod +x "$OUT/$NAME.AppImage"
ls -l "$OUT/$NAME.AppImage"

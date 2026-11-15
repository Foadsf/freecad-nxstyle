#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Build NX-Style-<version>-macos-<arch>.dmg: NX-Style.app carrying FreeCAD's own FreeCAD.app (from its release
# .dmg, unmodified) and NX-Style. Run on a Mac of the target architecture (arm64 or x86_64):
#     packaging/macos/build.sh <arm64|x86_64> <output folder>
# The app is signed ad hoc, not notarized (that takes an Apple Developer ID): a downloaded copy has to be allowed
# once in System Settings > Privacy & Security, or with xattr -dr com.apple.quarantine.
set -euo pipefail

ARCH="${1:?usage: build.sh <arm64|x86_64> <output folder>}"
OUT="$(mkdir -p "${2:?output folder}" && cd "$2" && pwd)"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/packaging/macos"
WORK="${WORK:-$ROOT/build/release-macos-$ARCH}"
VERSION="$(python3 "$ROOT/packaging/bundle.py" version)"
FREECAD_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/packaging/freecad.json")"
NAME="NX-Style-$VERSION-macos-$ARCH"
[ "$(uname -m)" = "$ARCH" ] || { echo "build $ARCH on an $ARCH Mac, not $(uname -m)" >&2; exit 2; }

mkdir -p "$WORK"
cd "$WORK"
rm -rf stage mnt
python3 "$ROOT/packaging/bundle.py" fetch "macos-$ARCH" dl
DMG="$(ls dl/FreeCAD_*-macOS-"$ARCH"-*.dmg)"

APP="stage/NX-Style.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" mnt
hdiutil attach -nobrowse -readonly -mountpoint "$WORK/mnt" "$DMG" >/dev/null
trap 'hdiutil detach "$WORK/mnt" -force >/dev/null 2>&1 || true' EXIT
ditto mnt/FreeCAD.app "$APP/Contents/Resources/FreeCAD.app"
hdiutil detach "$WORK/mnt" >/dev/null
trap - EXIT

MINOS="$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$APP/Contents/Resources/FreeCAD.app/Contents/Info.plist" 2>/dev/null || echo 11.0)"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@FREECAD@/$FREECAD_VERSION/g" -e "s/@MINOS@/$MINOS/g" \
    "$HERE/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"
install -m 755 "$HERE/NX-Style" "$APP/Contents/MacOS/NX-Style"
install -m 644 "$ROOT/packaging/icons/nxstyle.icns" "$APP/Contents/Resources/nxstyle.icns"
python3 "$ROOT/packaging/bundle.py" stage "$APP/Contents/Resources/nxstyle"

# Ad-hoc signature over the outer app only: FreeCAD.app inside keeps FreeCAD's own signature
codesign --force --sign - "$APP" || echo "warning: the ad-hoc signature failed; the app is left unsigned" >&2
codesign --verify --verbose "$APP" || true

ln -s /Applications stage/Applications
rm -f "$OUT/$NAME.dmg"
hdiutil create -volname "NX-Style $VERSION" -srcfolder stage -fs HFS+ -format ULFO -ov "$OUT/$NAME.dmg"
ls -l "$OUT/$NAME.dmg"

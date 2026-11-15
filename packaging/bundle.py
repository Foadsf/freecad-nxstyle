#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Helpers the release workflow shares across Windows, Linux and macOS (standard library only):

    python packaging/bundle.py version                 NX-Style's version (NXStyle/nxstyle/__init__.py)
    python packaging/bundle.py freecad PLATFORM        the pinned FreeCAD release for PLATFORM, as JSON
    python packaging/bundle.py fetch PLATFORM DIR      download that release into DIR and check its SHA-256
    python packaging/bundle.py stage DIR               copy NX-Style (launcher, add-on, vendored add-ons) into DIR

PLATFORM is one of windows-x86_64, windows-arm64, linux-x86_64, linux-aarch64, macos-arm64, macos-x86_64; the
FreeCAD each carries is pinned in packaging/freecad.json. stage copies only files git tracks (submodules
included), so a build never picks up caches, test output or a developer's local files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINS = Path(__file__).resolve().parent / "freecad.json"
# What a bundle carries of this repository: the launcher, the add-on, the vendored add-ons, the licence
STAGED = ["launch_nx.py", "NXStyle", "vendor", "LICENSE", "README.md", "packaging/check_bundle.py"]
SKIP_PARTS = {"__pycache__", ".github", "tests", "test", ".git"}


def version() -> str:
    text = (ROOT / "NXStyle" / "nxstyle" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("no __version__ in NXStyle/nxstyle/__init__.py")
    return m.group(1)


def freecad(platform: str) -> dict:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    try:
        asset = dict(pins["assets"][platform])
    except KeyError:
        raise SystemExit(f"no FreeCAD pinned for {platform!r}; known: {', '.join(pins['assets'])}") from None
    asset["version"] = pins["version"]
    asset["url"] = f"https://github.com/FreeCAD/FreeCAD/releases/download/{pins['version']}/{asset['name']}"
    return asset


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(platform: str, dest: Path) -> Path:
    asset = freecad(platform)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / asset["name"]
    if target.is_file() and sha256(target) == asset["sha256"]:
        print(f"{target.name}: already here, SHA-256 matches")
        return target
    for attempt in range(1, 4):
        try:
            print(f"downloading {asset['url']} (attempt {attempt})", flush=True)
            part = target.with_suffix(target.suffix + ".part")
            with urllib.request.urlopen(asset["url"], timeout=120) as r, part.open("wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            part.replace(target)
            break
        except OSError as e:
            print(f"download failed: {e}", file=sys.stderr)
            if attempt == 3:
                raise
            time.sleep(10 * attempt)
    got = sha256(target)
    if got != asset["sha256"]:
        target.unlink()
        raise SystemExit(f"{asset['name']}: SHA-256 {got} is not the pinned {asset['sha256']}")
    print(f"{target.name}: {target.stat().st_size} bytes, SHA-256 matches the pin")
    return target


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--recurse-submodules", "-z", "--", *STAGED], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode("utf-8")
    return [f for f in out.split("\0") if f and not SKIP_PARTS.intersection(Path(f).parts)]


def stage(dest: Path) -> int:
    files = tracked_files()
    missing_vendor = [d.name for d in (ROOT / "vendor").iterdir() if d.is_dir() and not any(d.iterdir())]
    if missing_vendor:
        raise SystemExit(f"submodules not checked out: {missing_vendor}; run git submodule update --init")
    if not any(f.startswith("vendor/") for f in files):
        raise SystemExit("no vendored add-on files: git ls-files --recurse-submodules listed none")
    dest.mkdir(parents=True, exist_ok=True)
    for rel in files:
        src = ROOT / rel
        if src.is_symlink() or not src.is_file():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    (dest / "VERSION").write_text(version() + "\n", encoding="utf-8")
    print(f"staged {len(files)} files of NX-Style {version()} into {dest}")
    return len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    p = sub.add_parser("freecad")
    p.add_argument("platform")
    p = sub.add_parser("fetch")
    p.add_argument("platform")
    p.add_argument("dest", type=Path)
    p = sub.add_parser("stage")
    p.add_argument("dest", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "version":
        print(version())
    elif args.cmd == "freecad":
        print(json.dumps(freecad(args.platform)))
    elif args.cmd == "fetch":
        fetch(args.platform, args.dest)
    elif args.cmd == "stage":
        stage(args.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

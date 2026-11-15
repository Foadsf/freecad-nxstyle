#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check a built NX-Style.exe: machine type, GUI subsystem, version resource, and that its icon is NX-Style's
(every image of the .ico it was built from, byte for byte). Needs pefile.

    python packaging/check_exe.py NX-Style.exe --arch x86_64 --version 0.1.0 --icon packaging/icons/nxstyle.ico
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MACHINES = {"x86_64": 0x8664, "arm64": 0xAA64}
RT_ICON, RT_GROUP_ICON = 3, 14
SUBSYSTEM_WINDOWS_GUI = 2


def ico_images(path: Path) -> list[bytes]:
    data = path.read_bytes()
    _reserved, _type, count = struct.unpack_from("<HHH", data, 0)
    images = []
    for i in range(count):
        size, offset = struct.unpack_from("<II", data, 6 + 16 * i + 8)
        images.append(data[offset:offset + size])
    return images


def main(argv: list[str] | None = None) -> int:
    import pefile

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("exe", type=Path)
    ap.add_argument("--arch", choices=sorted(MACHINES), required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--icon", type=Path, required=True)
    args = ap.parse_args(argv)

    pe = pefile.PE(str(args.exe))
    problems = []
    if pe.FILE_HEADER.Machine != MACHINES[args.arch]:
        problems.append(f"machine 0x{pe.FILE_HEADER.Machine:04x}, not {args.arch} (0x{MACHINES[args.arch]:04x})")
    if pe.OPTIONAL_HEADER.Subsystem != SUBSYSTEM_WINDOWS_GUI:
        problems.append(f"subsystem {pe.OPTIONAL_HEADER.Subsystem}, not the Windows GUI (no console window)")

    resources: dict[int, list[bytes]] = {}
    root = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    for kind in root.entries if root else []:
        for entry in kind.directory.entries:
            for lang in entry.directory.entries:
                rva, size = lang.data.struct.OffsetToData, lang.data.struct.Size
                resources.setdefault(kind.id, []).append(pe.get_memory_mapped_image()[rva:rva + size])
    if not resources.get(RT_GROUP_ICON):
        problems.append("no icon group resource")
    want = ico_images(args.icon)
    have = resources.get(RT_ICON, [])
    missing = [i for i, img in enumerate(want) if img not in have]
    if missing:
        problems.append(f"{len(missing)} of the {len(want)} images of {args.icon.name} are not in the .exe")

    strings = {}
    for info in getattr(pe, "FileInfo", []) or []:
        for item in info:
            for table in getattr(item, "StringTable", []):
                strings.update({k.decode(): v.decode() for k, v in table.entries.items()})
    if strings.get("ProductVersion") != args.version:
        problems.append(f"ProductVersion {strings.get('ProductVersion')!r}, not {args.version!r}")

    print(f"{args.exe.name}: machine 0x{pe.FILE_HEADER.Machine:04x}, subsystem {pe.OPTIONAL_HEADER.Subsystem}, "
          f"{len(have)} icon images, {strings.get('ProductName')} {strings.get('ProductVersion')}")
    for p in problems:
        print(f"FAIL  {p}")
    print("ok" if not problems else "FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

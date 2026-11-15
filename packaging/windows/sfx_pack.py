#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Make NX-Style's single-file Windows executable: the launcher stub with a folder appended as its payload.

    python packaging/windows/sfx_pack.py STUB.exe FOLDER OUT.exe --key 0.1.1     pack
    python packaging/windows/sfx_pack.py OUT.exe --verify                       check a packed .exe

Needs the zstandard package. The stub (launcher.c, sfx.c) decompresses with zstd's own decoder, built in.

Layout of OUT.exe (integers little-endian):

    STUB.exe as built (PE image; resources: icon, version, manifest)
    payload:
        "NXSFXZS1"  u64 logical size  u32 zstd window log
        one zstd frame (level 19, long-distance matching) of the logical stream
    trailer, the last 64 bytes:
        u64 payload offset  u64 payload size  char[32] key (NUL-padded)  "NXSTYLE-SFX-END!"

The logical stream is an index followed by the files' bytes in index order:
    "NXIDX1\\0\\0"  u32 file count, then per file: u32 path length, UTF-8 path with '/', u64 size

The key names the folder the stub unpacks into (%LOCALAPPDATA%\\FreeCAD-NXStyle\\runtime\\<key>): the version and
the first 12 hex digits of the payload's SHA-256, so a new build never reuses an old unpacked copy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import time
from pathlib import Path

MAGIC, IDX_MAGIC, END_MAGIC = b"NXSFXZS1", b"NXIDX1\0\0", b"NXSTYLE-SFX-END!"
LEVEL, WINDOW_LOG = 19, 27          # 128 MiB window: the decoder allows exactly this much
CHUNK = 1 << 20


def files_of(folder: Path) -> list[tuple[str, Path]]:
    out = []
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for n in sorted(names):
            p = Path(root) / n
            out.append((p.relative_to(folder).as_posix(), p))
    return out


def index_of(files: list[tuple[str, Path]]) -> tuple[bytes, int]:
    parts, total = [IDX_MAGIC, struct.pack("<I", len(files))], 0
    for rel, p in files:
        b = rel.encode("utf-8")
        size = p.stat().st_size
        parts.append(struct.pack("<I", len(b)) + b + struct.pack("<Q", size))
        total += size
    idx = b"".join(parts)
    return idx, len(idx) + total


class HashingWriter:
    def __init__(self, f):
        self.f, self.h, self.n = f, hashlib.sha256(), 0

    def write(self, b):
        self.f.write(b)
        self.h.update(b)
        self.n += len(b)
        return len(b)

    def flush(self):
        self.f.flush()


def pack(stub: Path, folder: Path, out: Path, key: str, level: int) -> None:
    import zstandard

    files = files_of(folder)
    idx, logical = index_of(files)
    stub_bytes = stub.read_bytes()
    t0 = time.monotonic()
    params = zstandard.ZstdCompressionParameters.from_level(level, window_log=WINDOW_LOG, enable_ldm=True,
                                                            threads=-1)
    with out.open("wb") as f:
        f.write(stub_bytes)
        head = MAGIC + struct.pack("<QI", logical, WINDOW_LOG)
        hw = HashingWriter(f)
        hw.write(head)
        cctx = zstandard.ZstdCompressor(compression_params=params)
        with cctx.stream_writer(hw, size=logical, closefd=False) as z:
            z.write(idx)
            for _rel, p in files:
                with p.open("rb") as src:
                    while chunk := src.read(CHUNK):
                        z.write(chunk)
        full_key = f"{key}-{hw.h.hexdigest()[:12]}"
        if len(full_key) > 31:
            raise SystemExit(f"key {full_key!r} is longer than 31 characters")
        f.write(struct.pack("<QQ", len(stub_bytes), hw.n) + full_key.encode().ljust(32, b"\0") + END_MAGIC)
    print(f"{out.name}: {len(files)} files, {logical / 2**20:.0f} MB -> payload {hw.n / 2**20:.0f} MB, key {full_key}, "
          f"{time.monotonic() - t0:.0f} s")


def verify(exe: Path) -> int:
    """Decompress exe's payload (streaming) and check it against its index; prints the key."""
    import zstandard

    with exe.open("rb") as f:
        f.seek(-64, os.SEEK_END)
        off, size, key, magic = struct.unpack("<QQ32s16s", f.read(64))
        if magic != END_MAGIC:
            raise SystemExit("no payload trailer")
        f.seek(0, os.SEEK_END)
        if off + size + 64 != f.tell():
            raise SystemExit("the trailer does not match the file size")
        f.seek(off)
        head = f.read(20)
        if head[:8] != MAGIC:
            raise SystemExit("bad payload magic")
        logical, wlog = struct.unpack("<QI", head[8:])
        t0 = time.monotonic()
        dctx = zstandard.ZstdDecompressor(max_window_size=1 << wlog)
        reader = dctx.stream_reader(f, read_size=CHUNK, closefd=False)
        got, buf = 0, bytearray()
        files = sizes = None
        while chunk := reader.read(4 << 20):
            got += len(chunk)
            if files is None:
                buf += chunk
                if len(buf) >= 12 and buf[:8] == IDX_MAGIC:
                    n = struct.unpack_from("<I", buf, 8)[0]
                    q, total, ok = 12, 0, True
                    for _ in range(n):
                        if q + 4 > len(buf):
                            ok = False
                            break
                        ln = struct.unpack_from("<I", buf, q)[0]
                        if q + 4 + ln + 8 > len(buf):
                            ok = False
                            break
                        total += struct.unpack_from("<Q", buf, q + 4 + ln)[0]
                        q += 4 + ln + 8
                    if ok:
                        files, sizes, idx_len = n, total, q
                        buf = bytearray()
        if files is None or got != logical or idx_len + sizes != logical:
            raise SystemExit(f"the payload does not decompress to its index: {got} of {logical} bytes")
    name = key.rstrip(b"\0").decode()
    print(f"{exe.name}: key {name}, {files} files, {logical / 2**20:.0f} MB, "
          f"decompressed in {time.monotonic() - t0:.1f} s: ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stub", type=Path)
    ap.add_argument("folder", type=Path, nargs="?")
    ap.add_argument("out", type=Path, nargs="?")
    ap.add_argument("--key", help="the version part of the unpack folder's name")
    ap.add_argument("--level", type=int, default=LEVEL)
    ap.add_argument("--verify", action="store_true", help="check the payload of STUB (a packed .exe) instead")
    args = ap.parse_args(argv)
    if args.verify:
        return verify(args.stub)
    if not (args.folder and args.out and args.key):
        ap.error("STUB FOLDER OUT and --key are needed to pack")
    pack(args.stub, args.folder, args.out, args.key, args.level)
    return 0


if __name__ == "__main__":
    sys.exit(main())

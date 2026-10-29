# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rebuild NXStyle/nxstyle/resources/nxt/nx_names.qm from nx_names.ts: NX's names for FreeCAD-Nxt's words,
which nxstyle/nxt.py installs as a Qt translator while Nxt is on. Uses Qt's lrelease from a FreeCAD install
(FreeCAD ships it in lib/qt6/bin on Windows) or from PATH.

    python tools/build_nxt_names.py                 # lrelease next to the FreeCAD the launcher finds
    python tools/build_nxt_names.py C:/path/lrelease.exe
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launch_nx  # noqa: E402

TS = ROOT / "NXStyle" / "nxstyle" / "resources" / "nxt" / "nx_names.ts"


def find_lrelease():
    for install in launch_nx.discover():
        root = install.exe.parent.parent
        for cand in (root / "lib" / "qt6" / "bin" / "lrelease.exe", root / "bin" / "lrelease",
                     root / "lib" / "qt6" / "bin" / "lrelease"):
            if cand.is_file():
                return cand
    found = shutil.which("lrelease") or shutil.which("lrelease-qt6")
    return Path(found) if found else None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    tool = Path(argv[0]) if argv else find_lrelease()
    if tool is None or not tool.is_file():
        print("lrelease not found: pass its path (FreeCAD ships it in lib/qt6/bin)")
        return 1
    env = dict(os.environ)
    qt_bin = tool.parent.parent.parent.parent / "bin"        # FreeCAD/lib/qt6/bin/lrelease.exe -> FreeCAD/bin (Qt DLLs)
    if qt_bin.is_dir():
        env["PATH"] = f"{qt_bin}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run([str(tool), str(TS), "-qm", str(TS.with_suffix(".qm"))], env=env).returncode


if __name__ == "__main__":
    sys.exit(main())

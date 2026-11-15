# SPDX-License-Identifier: LGPL-2.1-or-later
"""Headless check of a release bundle, run by the bundled freecadcmd:

    freecadcmd -M <nxstyle>/NXStyle -M <vendor add-on> ... check_bundle.py

It proves that the FreeCAD inside the bundle is the one the release names and that NX-Style and the add-ons it
bundles load in it without a GUI: every NX-Style module that does not need FreeCAD's main window is imported,
and each bundled add-on's own package is imported from the folder the bundle ships. The result is written as
JSON to NXSTYLE_CHECK_OUT (and printed); the process exits 0 only if every check passed.

Environment: NXSTYLE_CHECK_OUT (result file), NXSTYLE_EXPECT_FREECAD ("1.1.4"), NXSTYLE_EXPECT_VERSION
(NX-Style's own version, "0.1.0").
"""

import importlib
import json
import os
import pkgutil
import sys
import traceback

import FreeCAD as App

# NX-Style modules that build or drive the GUI: they import FreeCADGui's widgets at load time, which freecadcmd
# does not have. Everything else in the package must import headless.
GUI_ONLY = {"boot"}

# The bundled add-ons, each by a package it ships: (name, import, folder name under vendor/)
ADDONS = [
    ("Strata", "strata", "freecad-strata"),
    ("Katydid", "katydid", "Katydid"),
    ("LCInterlocking", "lasercut", "LCInterlocking"),
]

checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


def main():
    ver = App.Version()
    have = ".".join(ver[:3])
    want = os.environ.get("NXSTYLE_EXPECT_FREECAD", "")
    check("FreeCAD version", not want or have == want, f"{have} (want {want or 'any'}), {ver[3] if len(ver) > 3 else ''}")
    check("no GUI", not App.GuiUp, f"GuiUp={App.GuiUp}")

    try:
        import nxstyle
        want_nx = os.environ.get("NXSTYLE_EXPECT_VERSION", "")
        check("NX-Style package", not want_nx or nxstyle.__version__ == want_nx,
              f"{nxstyle.__version__} from {os.path.dirname(nxstyle.__file__)}")
    except Exception:
        check("NX-Style package", False, traceback.format_exc())
        return

    failed, loaded = [], 0
    for mod in sorted(m.name for m in pkgutil.iter_modules(nxstyle.__path__)):
        if mod in GUI_ONLY:
            continue
        try:
            importlib.import_module(f"nxstyle.{mod}")
            loaded += 1
        except Exception as e:
            failed.append(f"{mod}: {type(e).__name__}: {e}")
    check("NX-Style modules import headless", not failed, f"{loaded} loaded" + (f"; failed: {failed}" if failed else ""))

    for name, package, folder in ADDONS:
        try:
            m = importlib.import_module(package)
            where = os.path.dirname(os.path.abspath(m.__file__))
            check(f"bundled {name}", f"vendor{os.sep}{folder}" in where or f"vendor/{folder}" in where, where)
        except Exception as e:
            check(f"bundled {name}", False, f"{type(e).__name__}: {e}")


try:
    main()
except Exception:
    check("check script", False, traceback.format_exc())

ok = bool(checks) and all(c["ok"] for c in checks)
out = os.environ.get("NXSTYLE_CHECK_OUT")
if out:
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "checks": checks, "python": sys.version}, f, indent=2)
print(f"bundle check: {'ok' if ok else 'FAILED'} ({sum(c['ok'] for c in checks)}/{len(checks)})")
sys.stdout.flush()
os._exit(0 if ok else 1)

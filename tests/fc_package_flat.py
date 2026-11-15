# SPDX-License-Identifier: LGPL-2.1-or-later
"""A sheet metal part's release package holds the bent part, not its flat pattern (run with freecadcmd; not
part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_package_flat.py

A 60 x 40 x 2 plate gets a bend (the SheetMetal add-on's Make Wall, bundled in vendor/FreeCAD_SheetMetal) and
a Flat Pattern (its Unfold). The Unfold uses the bent part as its base, so the package took the bent part as
used up and exported the flat plate alone. The package's STEP must hold the bent part (13 mm high, its volume),
and the part's solids must not include the flat pattern. Prints one line per check, writes them to
results.txt, exits non-zero when one fails.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))
sys.path.insert(0, os.path.join(HERE, "..", "vendor", "FreeCAD_SheetMetal"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from nxstyle import package_ui  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)
if os.path.exists(os.path.join(OUT, "results.txt")):
    os.remove(os.path.join(OUT, "results.txt"))
failures = []


def check(ok, what, detail=""):
    line = ("PASS " if ok else "FAIL ") + what + (f": {detail}" if detail and not ok else "")
    print(line, flush=True)
    with open(os.path.join(OUT, "results.txt"), "a", encoding="utf-8") as f:   # freecadcmd may drop stdout
        f.write(line + "\n")
    if not ok:
        failures.append(what)


try:
    import SheetMetalCmd
    import SheetMetalUnfoldCmd
except ImportError as e:
    check(False, "the bundled SheetMetal add-on imports (git submodule update --init)", e)
    sys.stdout.flush()
    os._exit(1)

def main():
    doc = App.newDocument("Bracket")
    plate = doc.addObject("Part::Box", "Plate")
    plate.Length, plate.Width, plate.Height = 60, 40, 2
    doc.recompute()
    edge = next(f"Edge{i}" for i, e in enumerate(plate.Shape.Edges, 1)
                if abs(e.CenterOfMass.x - 60) < 1e-9 and abs(e.CenterOfMass.z - 2) < 1e-9)
    bent = doc.addObject("Part::FeaturePython", "Bend")
    SheetMetalCmd.SMBendWall(bent, plate, [edge])
    doc.recompute()
    face = next(f"Face{i}" for i, f in enumerate(bent.Shape.Faces, 1)
                if abs(f.CenterOfMass.z - 2) < 1e-9 and f.Area > 1000)
    flat = doc.addObject("Part::FeaturePython", "Unfold")
    SheetMetalUnfoldCmd.SMUnfold(flat, bent, [face])
    doc.recompute()
    bb, fb = bent.Shape.BoundBox, flat.Shape.BoundBox
    check(abs(bb.ZLength - 13) < 1e-6 and abs(fb.ZLength - 2) < 1e-6 and fb.XLength > bb.XLength,
          "fixture: the bent part stands 13 mm high, its flat pattern lies 2 mm thick and longer", (bb, fb))
    known = getattr(package_ui, "is_flat_pattern", lambda o: False)
    check(known(flat) and not known(bent), "the Unfold is known as a flat pattern")
    names = [o.Name for o in package_ui.solids(doc)]
    check(names == ["Bend"], "the part's solids are the bent part, not its flat pattern", names)
    meta = {"part_number": "BRK-300", "revision": "A", "state": "Released", "description": "Bracket"}
    folder, m, _ = package_ui.publish(doc, os.path.join(OUT, "packages"), meta, {"step"}, make_zip=False)
    step = os.path.join(folder, "model", "BRK-300_A.step")
    s = Part.read(step) if os.path.exists(step) else Part.Shape()
    sb = s.BoundBox if not s.isNull() else None
    check(sb is not None and abs(sb.ZLength - 13) < 1e-3
          and abs(s.Volume - bent.Shape.Volume) < 1e-3 * bent.Shape.Volume,
          "the package's STEP holds the bent part", (sb, s.Volume if not s.isNull() else None, bent.Shape.Volume))


try:
    main()
except Exception:                      # freecadcmd exits 0 on an uncaught exception: count it as a failure
    import traceback
    check(False, "the test ran to its end", traceback.format_exc())
print("FAILED: %s" % failures if failures else "ALL PASSED", flush=True)
sys.stdout.flush()
os._exit(1 if failures else 0)

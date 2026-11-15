# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assembly Clearance on a pocketed plate resting on a panel (run with freecadcmd; not part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_clearance_touch.py

A 200 x 200 x 6 plate with 11 x 11 hexagonal through pockets (732 faces) rests on a floor panel. The pair
shares no volume, so the analysis asked distToShape for the distance, which took 137 s here (24 minutes for a
user's plate of 1458 faces) to answer 0. A pair that touches must come out touching in seconds, and the other
kinds must not change: a plate 0.5 mm above the floor is soft at 0.5, a block on an edge of the plate touches,
a block 4 mm away is soft at 4, an overlapping block is hard. Prints one line per check, writes them to
results.txt, exits non-zero when one fails.
"""

import math
import os
import sys
import tempfile
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from nxstyle import clearance  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)
if os.path.exists(os.path.join(OUT, "results.txt")):
    os.remove(os.path.join(OUT, "results.txt"))
failures = []
ZONE = 5.0


def check(ok, what, detail=""):
    line = ("PASS " if ok else "FAIL ") + what + (f": {detail}" if detail else "")
    print(line, flush=True)
    with open(os.path.join(OUT, "results.txt"), "a", encoding="utf-8") as f:   # freecadcmd may drop stdout
        f.write(line + "\n")
    if not ok:
        failures.append(what)


def pocketed_plate(n):
    plate = Part.makeBox(200, 200, 6, App.Vector(0, 0, 5))
    r = 6.0
    hexagon = Part.Face(Part.makePolygon([App.Vector(r * math.cos(math.radians(60 * k)),
                                                     r * math.sin(math.radians(60 * k)), 0) for k in range(7)]))
    step = 200.0 / (n + 1)
    pockets = []
    for i in range(n):
        for j in range(n):
            p = hexagon.extrude(App.Vector(0, 0, 10))
            p.translate(App.Vector(step * (i + 1), step * (j + 1), 3))
            pockets.append(p)
    return plate.cut(Part.makeCompound(pockets)).removeSplitter()


def pair(sa, sb):
    a, b = SimpleNamespace(Label="A", Name="A"), SimpleNamespace(Label="B", Name="B")
    t = time.monotonic()
    got = clearance.analyse_pair(a, b, sa, sb, ZONE)
    row = got[0] if got else None
    return (row["kind"], round(row["distance"], 4)) if row else None, time.monotonic() - t


def main():
    floor = Part.makeBox(220, 220, 5, App.Vector(-10, -10, 0))
    plate = pocketed_plate(11)
    small = pocketed_plate(5)
    check(len(plate.Faces) > 700, "fixture: the plate has over 700 faces", len(plate.Faces))
    got, s = pair(plate, floor)
    check(got == ("touching", 0.0) and s < 30, "a pocketed plate resting on a panel touches, found in seconds",
          f"{got} in {s:.1f} s")
    got, s = pair(small, floor.translated(App.Vector(0, 0, -0.5)))
    check(got == ("soft", 0.5), "a plate 0.5 mm above the panel is soft at 0.5", f"{got} in {s:.1f} s")
    edge = Part.makeBox(10, 10, 10, App.Vector(200, -10, 11))           # meets the plate along its top corner edge
    got, s = pair(small, edge)
    check(got == ("touching", 0.0), "a block on an edge of the plate touches", f"{got} in {s:.1f} s")
    gap = Part.makeBox(10, 10, 6, App.Vector(204, 50, 5))
    got, s = pair(small, gap)
    check(got == ("soft", 4.0), "a block 4 mm away is soft at 4", f"{got} in {s:.1f} s")
    over = Part.makeBox(10, 10, 6, App.Vector(195, 0, 5))
    got, s = pair(small, over)
    check(got is not None and got[0] == "hard", "an overlapping block is hard", f"{got} in {s:.1f} s")


try:
    main()
except Exception:                      # freecadcmd exits 0 on an uncaught exception: count it as a failure
    import traceback
    check(False, "the test ran to its end", traceback.format_exc())
print("FAILED: %s" % failures if failures else "ALL PASSED", flush=True)
sys.stdout.flush()
os._exit(1 if failures else 0)

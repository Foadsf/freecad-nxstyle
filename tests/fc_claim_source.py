# SPDX-License-Identifier: LGPL-2.1-or-later
"""A claim's Source is the shape of a space, not a part in it (run with freecadcmd; not part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_claim_source.py

Claim A takes its shape from a hidden envelope solid around part A; claim B is a box around part B; part C is
its own claim's Source and also its member. Check Volume Claims must find nothing: the envelope neither enters
claim A nor "belongs to no claim", while part C still counts as a part. Assembly Clearance leaves the envelope
out of its candidates too. Prints one line per check, writes them to results.txt, exits non-zero when one fails.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))

import FreeCAD as App  # noqa: E402

from nxstyle import claims, clearance  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
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


def box(doc, name, size, at):
    b = doc.addObject("Part::Box", name)
    b.Length, b.Width, b.Height = size
    b.Placement.Base = App.Vector(*at)
    return b


doc = App.newDocument("ClaimSource")
a = box(doc, "PartA", (10, 10, 10), (0, 0, 0))
env = box(doc, "EnvelopeA", (12, 12, 12), (-1, -1, -1))
env.Visibility = False
b = box(doc, "PartB", (10, 10, 10), (50, 0, 0))
c = box(doc, "PartC", (10, 10, 10), (0, 50, 0))
doc.recompute()
ca = claims.create(doc, "A", [a], source=env)
cb = claims.create(doc, "B", [b], size=(20, 20, 20), placement=App.Placement(App.Vector(45, -5, -5), App.Rotation()))
cc = claims.create(doc, "C", [c], source=c)
findings, _ = claims.check(doc)
texts = [f["text"] for f in findings]
names = sorted(o.Name for o, _ in claims.parts(doc))
check(names == ["PartA", "PartB", "PartC"], "the layout's parts leave out claim A's envelope and keep part C",
      names)
check(not any("EnvelopeA" in t or "Envelope" in t for t in texts),
      "the envelope neither enters its own claim nor belongs to no claim", texts)
check((ca.Status, cb.Status, cc.Status) == ("OK", "OK", "OK"), "every claim OK",
      (ca.Status, cb.Status, cc.Status, texts))
# the claim still takes its shape from the envelope
bb, bc = ca.Shape.BoundBox, cc.Shape.BoundBox
check(abs(ca.Shape.Volume - 12 ** 3) < 1e-6 and abs(bb.XMin + 1) < 1e-9 and abs(bb.ZMax - 11) < 1e-9,
      "claim A's shape is its envelope, where the envelope is", (ca.Shape.Volume, bb))
check(abs(bc.YMin - 50) < 1e-9 and abs(bc.XMin) < 1e-9, "claim C sits on part C, its Source (0, 50, 0)", bc)
# part C, its own claim's Source, still counts: moved out of claim B's way into claim A, it is found there
c.Placement.Base = App.Vector(5, 5, 5)
findings, _ = claims.check(doc)
texts = [f["text"] for f in findings]
check(any(t.startswith("PartC (Claim C) enters Claim A") for t in texts),
      "a part that is its own claim's Source and member is still checked", texts)
# the claims' folder holds the claim, a module (App::Part at x 100) holds its Source at y 100 in the module:
# the claim sits on the source, and follows it when the module moves (which does not touch the claim)
mod = doc.addObject("App::Part", "Module")
mod.Placement.Base = App.Vector(100, 0, 0)
e = box(doc, "EnvelopeE", (10, 10, 10), (0, 100, 0))
e.Visibility = False
mod.addObject(e)
doc.recompute()
ce = claims.create(doc, "E", [], source=e)
claims.check(doc)
g = claims.global_shape(ce).BoundBox
check(abs(g.XMin - 100) < 1e-9 and abs(g.YMin - 100) < 1e-9, "a claim sits on its Source inside a module", g)
mod.Placement.Base = App.Vector(0, 0, 30)
claims.check(doc)
g = claims.global_shape(ce).BoundBox
check(abs(g.XMin) < 1e-9 and abs(g.YMin - 100) < 1e-9 and abs(g.ZMin - 30) < 1e-9,
      "the claim follows its Source when the module moves", g)
cands = sorted(o.Name for o in clearance.candidates(doc))
check("EnvelopeA" not in cands and "PartC" in cands, "clearance candidates leave out the envelope", cands)
print("FAILED: %s" % failures if failures else "ALL PASSED", flush=True)
sys.stdout.flush()
os._exit(1 if failures else 0)

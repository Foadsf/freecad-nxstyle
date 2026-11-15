# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assembly Clearance and Volume Claims at component level, in a real FreeCAD (run with freecadcmd; not part
of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_components.py

A machine assembly links two sub-assemblies, each an Assembly in its own document, whose links place bodies of
a third document. The head's bearing sits 3 mm deep in its own fixture plate (a clash inside the sub-assembly),
and the head's plate overlaps the tank's plate by 10 mm. At top level the check sees two solids (head, tank); at
component level it must name the parts, find the clash inside the head, leave out a hidden part and see the
elements of a link array. Prints one line per check, writes them to results.txt, exits non-zero when one fails.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))

import FreeCAD as App  # noqa: E402

from nxstyle import claims, clearance  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
TMP = tempfile.mkdtemp(prefix="nxstyle-components-")
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


def new_doc(name):
    doc = App.newDocument(name)
    doc.saveAs(os.path.join(TMP, name + ".FCStd"))       # links to another document need a saved owner
    return doc


def body(doc, name, label, size):
    b = doc.addObject("PartDesign::Body", name)
    box = doc.addObject("Part::Box", name + "Stock")
    box.Length, box.Width, box.Height = size
    b.BaseFeature = box
    b.Label = label
    return b


def link(doc, asm, name, label, target, at=(0, 0, 0)):
    lk = doc.addObject("App::Link", name)
    lk.LinkedObject = target
    lk.Label = label
    lk.Placement.Base = App.Vector(*at)
    asm.addObject(lk)
    return lk


def assembly(doc):
    return doc.addObject("Assembly::AssemblyObject", "Assembly")


parts = new_doc("CmpParts")
bearing = body(parts, "Bearing", "Ceramic bearing", (10, 10, 10))
plate = body(parts, "Plate", "Fixture plate", (40, 40, 5))
parts.recompute()
parts.save()

head_doc = new_doc("CmpHead")
head = assembly(head_doc)
link(head_doc, head, "Link", "Fixture plate", plate)
link(head_doc, head, "Link001", "Ceramic bearing", bearing, (5, 5, 2))           # 3 mm into the plate: 300 mm³
head_doc.recompute()
head_doc.save()

tank_doc = new_doc("CmpTank")
tank = assembly(tank_doc)
link(tank_doc, tank, "Link", "Tank plate", plate)
spare = link(tank_doc, tank, "Link001", "Spare bearing", bearing, (0, 0, 0))     # hidden: not in the assembly
spare.Visibility = False
arr = link(tank_doc, tank, "Link002", "Feet", bearing)                            # two feet, 2 mm under the plate
arr.ElementCount = 2
arr.ShowElement = True
tank_doc.recompute()
for el, x in zip(arr.ElementList, (0, 30)):
    el.Placement = App.Placement(App.Vector(x, 0, -12), App.Rotation())
tank_doc.recompute()
tank_doc.save()

machine = new_doc("CmpMachine")
top = assembly(machine)
h = link(machine, top, "Link", "Wire feeder head", head, (100, 0, 0))
t = link(machine, top, "Link001", "Water tank", tank, (130, 0, 0))              # plates overlap 10x40x5 = 2000
machine.recompute()

# --- the walk
comps = {c.Name: c for o in (h, t) for c in claims.components(o)}
check(sorted(comps) == sorted(["Link.Link", "Link.Link001", "Link001.Link", "Link001.Link002.0",
                               "Link001.Link002.1"]),
      "components: the parts inside both sub-assemblies (other documents), not the hidden one, each array element",
      sorted(comps))
check(comps.get("Link.Link001") is not None and comps["Link.Link001"].Label == "Wire feeder head / Ceramic bearing",
      "a component is labelled by its path", comps.get("Link.Link001") and comps["Link.Link001"].Label)
bb = comps["Link.Link001"].Shape.BoundBox if "Link.Link001" in comps else None
check(bb is not None and [round(v, 6) for v in (bb.XMin, bb.YMin, bb.ZMin)] == [105, 5, 2],
      "a component's solid is where the machine puts it (both links' placements)", bb)
plain = claims.components(machine.getObject("Link"))
check(claims.expand([h], "Top level") == [h], "top level: the objects themselves")

# --- clearance, top level (unchanged behaviour)
cs_top = clearance.create(machine, zone=0.0, label="Top")
rows, _ = clearance.perform(cs_top)
pairs = sorted((r["a"], r["b"], r["kind"], round(r["volume"], 3)) for r in rows)
check(pairs == [("Wire feeder head", "Water tank", "hard", 2000.0)],
      "top level: the sub-assemblies are one solid each (as before)", pairs)

# --- clearance, component level
cs = clearance.create(machine, zone=0.0, label="Components", level="Components")
rows, solids = clearance.perform(cs)
pairs = sorted((r["a"], r["b"], r["kind"], round(r["volume"], 3)) for r in rows)
want = [("Wire feeder head / Ceramic bearing", "Wire feeder head / Fixture plate", "hard", 300.0),
        ("Wire feeder head / Fixture plate", "Water tank / Tank plate", "hard", 2000.0)]
got = sorted(tuple(sorted(p[:2])) + p[2:] for p in pairs)
check(got == sorted(tuple(sorted(w[:2])) + w[2:] for w in want),
      "components: the clash inside the head and the plates' overlap, by part; the hidden spare and the feet "
      "are clear", pairs)
r0 = next((r for r in rows if r["volume"] > 1000), {})
check(r0.get("a_top") in ("Link", "Link001") and r0.get("a_root") == "Assembly" and r0.get("a_sub", "").count(".") == 2,
      "a component row says where the part is, for Study Interference", {k: r0.get(k) for k in
                                                                        ("a_top", "a_root", "a_sub")})
text = clearance.report(cs)
check("Wire feeder head / Ceramic bearing" in text and "components inside sub-assemblies" in text,
      "the report names the parts in full", text)

# a pair rule by component label; then a move inside a sub-assembly makes the results out of date
cs.PairRules = ["Wire feeder head / Ceramic bearing|Wire feeder head / Fixture plate=exclude"]
rows, _ = clearance.perform(cs)
check(len(rows) == 1 and rows[0]["volume"] > 1000 and not cs.RuleProblems,
      "a pair rule names components by their path label", [(r["a"], r["b"]) for r in rows] + list(cs.RuleProblems))
check(not clearance.is_stale(cs), "fresh after Perform Analysis")
head_doc.getObject("Link001").Placement.Base = App.Vector(5, 5, 30)
head_doc.recompute()
machine.recompute()
check(clearance.is_stale(cs), "out of date after a part inside a sub-assembly moves")
cs.PairRules = []
rows, _ = clearance.perform(cs)
check(len(rows) == 1 and not clearance.is_stale(cs), "the bearing moved out of the plate: one interference left",
      [(r["a"], r["b"]) for r in rows])
head_doc.getObject("Link001").Placement.Base = App.Vector(5, 5, 2)
head_doc.recompute()
machine.recompute()

# --- volume claims
claim = claims.create(machine, owner="Head", members=[h], size=(36, 60, 40),
                      placement=App.Placement(App.Vector(99, -10, -5), App.Rotation()), level="Components")
findings, _ = claims.check(machine)
texts = [f["text"] for f in findings if f["claim"] == claim.Label]
check(any(f["kind"] == "outside" and f["other"] == "Wire feeder head / Fixture plate" for f in findings) and
      not any(f["kind"] == "outside" and "Ceramic bearing" in f["other"] for f in findings),
      "claim at component level: the part that sticks out is named, the one inside is not", texts)
check(any(f["kind"] == "intrusion" and f["other"] == "Water tank / Tank plate" for f in findings),
      "claim at component level: another owner's part that enters is named", texts)
claim.Level = "Top level"
findings, _ = claims.check(machine)
check(any(f["kind"] == "outside" and f["other"] == "Wire feeder head" for f in findings) and
      any(f["kind"] == "intrusion" and f["other"] == "Water tank" for f in findings),
      "claim at top level: as before, by sub-assembly", [f["text"] for f in findings])
check(machine.getObject(clearance.RESULT) is not None and
      not any("Clearance interferences" in f["text"] for f in findings),
      "Assembly Clearance's red result body is not a part of the layout", [f["text"] for f in findings])

for d in list(App.listDocuments()):
    App.closeDocument(d)
print("FAILED: %s" % failures if failures else "ALL PASSED", flush=True)
sys.stdout.flush()
os._exit(1 if failures else 0)

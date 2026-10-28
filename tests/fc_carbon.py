# SPDX-License-Identifier: LGPL-2.1-or-later
"""Publish to Manufacturing in a real FreeCAD (run with freecadcmd; not part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_carbon.py

Builds a plate and a bolt as documents of their own (part numbers in their NX attributes) and an assembly
that links the plate once, the bolt once and the bolt again as a link array of 3; reads the assembly's BOM
the way Publish to Manufacturing does (carbon_ui.bom_tree), makes its release package (package_ui.publish:
STEP and native file, verified), publishes it to the stand-in Carbon server (tests/carbon_fake.py, which
checks every request against Carbon's published schemas) and checks what Carbon holds. Prints one line per
check and exits non-zero when one fails.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))
sys.path.insert(0, HERE)

import FreeCAD as App  # noqa: E402

from nxstyle import carbon, carbon_ui, package_ui  # noqa: E402
import carbon_fake  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)
RESULTS = os.path.join(OUT, "carbon-results.txt")
if os.path.exists(RESULTS):
    os.remove(RESULTS)
failures = []


def check(ok, what):
    line = ("PASS " if ok else "FAIL ") + what
    print(line, flush=True)
    with open(RESULTS, "a", encoding="utf-8") as f:     # freecadcmd may drop stdout
        f.write(line + "\n")
    if not ok:
        failures.append(what)


def part(name, pn, rev, make):
    doc = App.newDocument(name)
    make(doc)
    doc.Meta = dict(doc.Meta, DB_PART_NO=pn, DB_PART_REV=rev, DB_PART_NAME=name)
    doc.recompute()
    doc.saveAs(os.path.join(OUT, name + ".FCStd"))
    return doc


def main():
    plate = part("Plate", "PLT-100", "A", lambda d: d.addObject("Part::Box", "Box"))
    bolt = part("Bolt", "BLT-M6", "0", lambda d: d.addObject("Part::Cylinder", "Cylinder"))
    asm_doc = App.newDocument("Bracket")
    asm = asm_doc.addObject("Assembly::AssemblyObject", "Assembly")
    asm_doc.saveAs(os.path.join(OUT, "Bracket.FCStd"))       # a link to another document needs a saved owner
    for i, (target, count) in enumerate(((plate.Box, 0), (bolt.Cylinder, 0), (bolt.Cylinder, 3))):
        link = asm_doc.addObject("App::Link", f"Link{i}")
        link.LinkedObject = target
        if count:
            link.ElementCount = count
        asm.addObject(link)
    asm_doc.recompute()
    asm_doc.save()

    tree = carbon_ui.bom_tree(asm)
    lines = sorted((c["id"], c["revision"], c["quantity"]) for c in tree["children"])
    check(lines == [("BLT-M6", "0", 1), ("BLT-M6", "0", 3), ("PLT-100", "A", 1)],
          f"bom_tree: each link with its document's part number and revision, a link array counted {lines}")
    merged = sorted((c["id"], c["quantity"]) for c in carbon.merge_children(tree["children"]))
    check(merged == [("BLT-M6", 4), ("PLT-100", 1)], f"BOM lines merged per part {merged}")
    ident = carbon_ui.identity(plate)
    check((ident["part_number"], ident["revision"]) == ("PLT-100", "A"),
          f"identity from NX attributes without a Strata release {ident}")

    meta = {"part_number": "BRK-200", "revision": "A", "state": "Released", "description": "Bracket"}
    folder, m, _ = package_ui.publish(asm_doc, os.path.join(OUT, "packages"), meta, {"step", "native"},
                                      make_zip=False)
    roles = sorted(e["role"] for e in m["files"])
    check(any(r.startswith("model (STEP)") for r in roles) and any("native" in r for r in roles),
          f"release package with STEP and native file {roles}")
    step_tree = carbon.step_bom(folder, m)
    print("product structure the STEP carries:", json.dumps(step_tree)[:400])

    with carbon_fake.Server() as s:
        c = carbon.Client(s.url, carbon_fake.KEY)
        review = carbon.publish(c, folder, bom=dict(tree, id="BRK-200"), dry_run=True)
        check(s.writes() == [], f"review writes nothing ({len(review['actions'])} writes listed)")
        r = carbon.publish(c, folder, bom=dict(tree, id="BRK-200"))
        co = s.company
        by_pn = {i["readableId"]: i for i in co.items.values()}
        check(set(by_pn) == {"BRK-200", "PLT-100", "BLT-M6"}, f"items in Carbon {sorted(by_pn)}")
        mm = next(x for x in co.methods.values() if x["itemId"] == by_pn["BRK-200"]["id"])
        bom = sorted((co.items[ln["itemId"]]["readableId"], co.items[ln["itemId"]]["revision"], ln["quantity"])
                     for ln in co.lines.values() if ln["makeMethodId"] == mm["id"])
        check(bom == [("BLT-M6", "0", 4), ("PLT-100", "A", 1)], f"Bracket's make method {bom}")
        model = co.models.get(by_pn["BRK-200"].get("modelUploadId"), {})
        check(model.get("name") == "BRK-200_A.step", f"the package STEP is the item's CAD model {model}")
        again = carbon.publish(c, folder, bom=dict(tree, id="BRK-200"))
        check(again["actions"] == [], "publishing the same release again writes nothing")
        check(s.schema_problems == [], f"every request matched Carbon's published schemas {s.schema_problems}")
        print(carbon.publish_text(r))
    for d in (asm_doc, plate, bolt):
        App.closeDocument(d.Name)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    failures.append("exception")
print(f"{len(failures)} failed" if failures else "all passed", flush=True)
with open(RESULTS, "a", encoding="utf-8") as f:
    f.write((f"{len(failures)} failed" if failures else "all passed") + "\n")
if failures:
    sys.exit(1)

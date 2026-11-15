# SPDX-License-Identifier: LGPL-2.1-or-later
"""A release package refuses a drawing that names another revision (run with freecadcmd; not part of the unit tests):

    NXSTYLE_OUT=folder freecadcmd tests/fc_package_revision.py

A part with an ISO 5457 sheet whose title block reads drawing number PLT-400, revision B, packaged as revision
C: the package must be refused (a critical loss naming both revisions), where it used to verify "all files
match". With the sheet at C it is made; with the revision left blank it is made and the gap is listed. Prints one
line per check, writes them to results.txt, exits non-zero when one fails.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))

import FreeCAD as App  # noqa: E402

from nxstyle import package, package_ui  # noqa: E402

OUT = os.environ.get("NXSTYLE_OUT") or tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)
if os.path.exists(os.path.join(OUT, "results.txt")):
    os.remove(os.path.join(OUT, "results.txt"))
failures = []


def check(ok, what, detail=""):
    line = ("PASS " if ok else "FAIL ") + what + (f": {detail}" if detail else "")
    print(line, flush=True)
    with open(os.path.join(OUT, "results.txt"), "a", encoding="utf-8") as f:   # freecadcmd may drop stdout
        f.write(line + "\n")
    if not ok:
        failures.append(what)


def publish(doc, sub, meta):
    try:
        # a release package (STEP and the native file): only it refuses critical losses
        folder, m, _ = package_ui.publish(doc, os.path.join(OUT, sub), meta, {"step", "native"}, make_zip=False)
        return m, None
    except package.PackageError as e:
        return None, str(e)


def main():
    doc = App.newDocument("Plate")
    doc.addObject("Part::Box", "Box")
    page = doc.addObject("TechDraw::DrawPage", "Sheet")
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    tpl.Template = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO",
                                "A4_Landscape_ISO5457_advanced.svg")
    page.Template = tpl
    doc.recompute()
    doc.saveAs(os.path.join(tempfile.mkdtemp(), "Plate.FCStd"))       # the native file is copied from it
    texts = dict(tpl.EditableTexts)
    check("drawing_number" in texts and "revision_index" in texts, "fixture: the ISO template has the two fields",
          sorted(texts)[:6])
    meta = {"part_number": "PLT-400", "revision": "C", "state": "Released", "description": "Plate"}

    tpl.EditableTexts = dict(texts, drawing_number="PLT-400", revision_index="B")
    doc.recompute()
    m, err = publish(doc, "b-sheet", meta)
    check(m is None and err is not None and "revision is B, the package's is C" in err,
          "a revision C package with a sheet that reads B is refused, naming both", err)

    tpl.EditableTexts = dict(texts, drawing_number="PLT-400", revision_index="C")
    doc.recompute()
    m, err = publish(doc, "c-sheet", meta)
    losses = [x["what"] for x in (m or {}).get("losses", [])] if m else None
    check(m is not None and not any("title block" in w for w in losses or []),
          "with the sheet at C the package is made", err or losses)

    tpl.EditableTexts = dict(texts, drawing_number="PLT-400", revision_index="")
    doc.recompute()
    m, err = publish(doc, "blank-sheet", meta)
    text = json.dumps(m or {})
    check(m is not None and "states no revision" in text,
          "with the revision left blank the package is made and the gap listed", err or text[:300])


try:
    main()
except Exception:                      # freecadcmd exits 0 on an uncaught exception: count it as a failure
    import traceback
    check(False, "the test ran to its end", traceback.format_exc())
print("FAILED: %s" % failures if failures else "ALL PASSED", flush=True)
sys.stdout.flush()
os._exit(1 if failures else 0)

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ribbon files, checked without FreeCAD."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RIBBONS = ROOT / "NXStyle" / "nxstyle" / "resources" / "ribbons"
LCINTERLOCKING = ROOT / "vendor" / "LCInterlocking"


def load(name):
    return json.loads((RIBBONS / name).read_text(encoding="utf-8"))


class RibbonTests(unittest.TestCase):
    def test_every_application_ribbon_can_switch_application(self):
        """Without the Application tab an application is a dead end: no ribbon way back."""
        files = sorted({a["ribbon"] for g in load("apps.json")["groups"] for a in g["apps"] if a.get("ribbon")})
        self.assertTrue(files)
        for f in files:
            with self.subTest(ribbon=f):
                includes = [t.get("include") for t in load(f)["tabs"]]
                self.assertIn("common:Application", includes)

    def test_essential_commands_are_on_their_ribbon(self):
        """'essential' names commands the layout keeps reachable first; each must be a button of that file."""
        for f in sorted(RIBBONS.glob("*.json")):
            spec = load(f.name)
            cmds = [i.get("cmd") for t in spec.get("tabs", []) for g in t.get("groups", []) for i in g["items"]]
            cmds += [s["cmd"] for t in spec.get("tabs", []) for g in t.get("groups", []) for i in g["items"]
                     for s in i.get("items", [])]
            for e in spec.get("essential", []):
                with self.subTest(ribbon=f.name, essential=e):
                    self.assertIn(e, cmds)

    def test_group_ranks_are_numbers(self):
        for f in sorted(RIBBONS.glob("*.json")):
            for t in load(f.name).get("tabs", []):
                for g in t.get("groups", []):
                    if "rank" in g:
                        with self.subTest(ribbon=f.name, group=g["name"]):
                            self.assertIsInstance(g["rank"], int)

    def test_every_application_ribbon_file_exists(self):
        for g in load("apps.json")["groups"]:
            for a in g["apps"]:
                if a.get("ribbon"):
                    with self.subTest(app=a["id"]):
                        self.assertTrue((RIBBONS / a["ribbon"]).is_file())


class LaserCutRibbonTests(unittest.TestCase):
    """Laser Cut: NX-style names on LCInterlocking's own commands."""

    def setUp(self):
        self.spec = load("laser_cut.json")
        self.items = [i for t in self.spec["tabs"] for g in t.get("groups", []) for i in g["items"]]

    def test_offered_as_an_application(self):
        apps = [a for g in load("apps.json")["groups"] for a in g["apps"]]
        app = next((a for a in apps if a["id"] == "laser_cut"), None)
        self.assertIsNotNone(app)
        self.assertEqual((app["workbench"], app["ribbon"]), ("LCInterlockingWorkbench", "laser_cut.json"))
        self.assertEqual(self.spec["workbench"], app["workbench"])

    def test_every_lcinterlocking_command_is_on_the_ribbon(self):
        cmds = {i["cmd"] for i in self.items if isinstance(i["cmd"], str)}
        for c in ("make_box_command", "make_rounded_box_command", "multiple_tabs_command", "crosspiece",
                  "livinghinge", "export_command"):
            self.assertIn(c, cmds)

    def test_each_button_has_an_nx_style_label(self):
        for i in self.items:
            with self.subTest(cmd=i["cmd"]):
                self.assertTrue(i.get("label"))
                self.assertNotEqual(i["label"], i["cmd"])       # the FreeCAD name goes in the tooltip

    def test_commands_exist_in_the_bundled_add_on(self):
        """The upstream names the ribbon refers to are the ones the add-on registers (Gui.addCommand)."""
        if not (LCINTERLOCKING / "InitGui.py").is_file():
            self.skipTest("vendor/LCInterlocking not checked out (git submodule update --init)")
        src = "".join(f.read_text(encoding="utf-8", errors="replace") for f in LCINTERLOCKING.rglob("*.py"))
        registered = set(re.findall(r"addCommand\(\s*['\"](\w+)['\"]", src))
        ours = {i["cmd"] for i in self.items if isinstance(i["cmd"], str) and not i["cmd"].startswith(
            ("Std_", "Part_", "Sketcher_", "NXStyle_"))}
        self.assertTrue(ours)
        self.assertEqual(ours - registered, set())
        self.assertIn("class LCInterlockingWorkbench", (LCINTERLOCKING / "InitGui.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

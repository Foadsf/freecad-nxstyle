# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ribbon files, checked without FreeCAD."""

import json
import unittest
from pathlib import Path

RIBBONS = Path(__file__).resolve().parents[1] / "NXStyle" / "nxstyle" / "resources" / "ribbons"


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

    def test_every_application_ribbon_file_exists(self):
        for g in load("apps.json")["groups"]:
            for a in g["apps"]:
                if a.get("ribbon"):
                    with self.subTest(app=a["id"]):
                        self.assertTrue((RIBBONS / a["ribbon"]).is_file())


if __name__ == "__main__":
    unittest.main()

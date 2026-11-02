# SPDX-License-Identifier: LGPL-2.1-or-later
"""The user's own add-ons: which folders of the normal profile's Mod the launcher loads (launch_nx.find_user_addons)
and which workbenches then become applications (nxstyle.addons). A fake Mod and vendor folder; no FreeCAD needed."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "NXStyle"))

import launch_nx  # noqa: E402
from nxstyle import addons  # noqa: E402

PKG = ('<?xml version="1.0" encoding="UTF-8"?>\n<package format="1" xmlns="https://wiki.freecad.org/Package_Metadata">'
       '<name>{}</name><version>1.0</version></package>\n')


def make(folder, files):
    for rel, text in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nx-addons-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        vendor = self.tmp / "vendor"
        make(vendor / "Katydid", {"InitGui.py": "", "package.xml": PKG.format("Katydid")})
        make(vendor / "freecad-strata", {"InitGui.py": "", "strata/__init__.py": "", "package.xml": PKG.format("Strata")})
        p = mock.patch.object(launch_nx, "VENDOR_DIR", vendor)
        p.start()
        self.addCleanup(p.stop)
        self.normal = self.tmp / "normal"
        mods = self.normal / "Mod"
        make(mods / "MyBench", {"Init.py": "", "InitGui.py": "", "package.xml": PKG.format("My Bench")})
        make(mods / "NsBench", {"freecad/nsbench/__init__.py": "", "freecad/nsbench/init_gui.py": ""})
        make(mods / "Katydid", {"InitGui.py": ""})                                   # same folder name as vendored
        make(mods / "Kd-renamed", {"InitGui.py": "", "package.xml": PKG.format("Katydid")})   # same package name
        make(mods / "StrataFork", {"InitGui.py": "", "strata/__init__.py": ""})       # Strata's own package inside
        make(mods / "Switched", {"InitGui.py": "", "ADDON_DISABLED": ""})             # disabled in the Addon Manager
        make(mods / "parts_library", {"README.md": ""})                              # no FreeCAD module
        make(mods / "AlsoInNX", {"InitGui.py": ""})
        (mods / "manifest.json").write_text("{}", encoding="utf-8")
        self.profile = self.tmp / "nx"
        make(self.profile / "data" / "Mod" / "AlsoInNX", {"InitGui.py": ""})      # FreeCAD loads this one itself

    def find(self, enabled=True):
        return launch_nx.find_user_addons(self.profile, (1, 1, 4), enabled, str(self.normal))

    def test_only_new_modules_are_loaded(self):
        load, why = self.find()
        self.assertEqual([d.name for d in load], ["MyBench", "NsBench"])
        for name in ("Katydid", "Kd-renamed", "StrataFork", "AlsoInNX"):
            self.assertIn(f"{name} (bundled or already in the NX profile)", why)
        self.assertIn("Switched (disabled)", why)
        self.assertIn("parts_library (not a module)", why)

    def test_off_by_default(self):
        """Negative control: without the setting nothing of the normal profile loads."""
        load, why = self.find(enabled=False)
        self.assertEqual(load, [])
        self.assertIn("--user-addons", why)

    def test_a_duplicate_loads_once(self):
        make(self.normal / "Mod" / "MyBench-copy", {"InitGui.py": "", "package.xml": PKG.format("My Bench")})
        load, _ = self.find()
        self.assertEqual([d.name for d in load], ["MyBench", "NsBench"])

    def test_no_mod_folder(self):
        load, why = launch_nx.find_user_addons(self.profile, (1, 1, 4), True, str(self.tmp / "missing"))
        self.assertEqual(load, [])
        self.assertIn("none found", why)

    def test_the_command_line_loads_them_with_m(self):
        load, _ = self.find()
        inst = launch_nx.Install(Path("freecad.exe"), (1, 1, 4))
        cmd = launch_nx.build_command(inst, [], [], tuple(load))
        self.assertEqual(cmd[-4:], ["-M", str(load[0]), "-M", str(load[1])])


class ApplicationTests(unittest.TestCase):
    """Which workbenches become applications on the Application tab."""

    def test_workbench_of_an_addon_folder(self):
        folder = os.path.abspath(os.path.join("x", "Mod", "MyBench"))
        apps = addons.addon_apps({"MyBenchWorkbench": ("My Bench", [os.path.join(folder, "InitGui.py")]),
                                  "PartWorkbench": ("Part", [os.path.abspath(os.path.join("fc", "Mod", "Part",
                                                                                          "InitGui.py"))])},
                                 [folder], set())
        self.assertEqual(apps, [{"id": "addon_MyBenchWorkbench", "title": "My Bench", "workbench": "MyBenchWorkbench"}])

    def test_a_workbench_apps_json_places_keeps_its_place(self):
        folder = os.path.abspath("Katydid")
        apps = addons.addon_apps({"KatydidWorkbench": ("Katydid", [os.path.join(folder, "InitGui.py")])},
                                 [folder], {"KatydidWorkbench"})
        self.assertEqual(apps, [])

    def test_a_folder_name_prefix_is_not_the_folder(self):
        mods = os.path.abspath("Mod")
        apps = addons.addon_apps({"OtherWorkbench": ("Other", [os.path.join(mods, "MyBench2", "InitGui.py")])},
                                 [os.path.join(mods, "MyBench")], set())
        self.assertEqual(apps, [])

    def test_files_of_a_workbench_freecad_execs_from_initgui(self):
        """FreeCAD runs InitGui.py with exec(compile(source, path, 'exec')); the methods keep that path."""
        path = os.path.abspath(os.path.join("Mod", "MyBench", "InitGui.py"))
        ns = {}
        exec(compile("class Base:\n    def Initialize(self):\n        pass\n"
                     "class MyBenchWorkbench(Base):\n    MenuText = 'My Bench'\n"
                     "    def GetClassName(self):\n        return 'Gui::PythonWorkbench'\n", path, "exec"), ns)
        files = addons.workbench_files(ns["MyBenchWorkbench"]())
        self.assertIn(path, files)
        apps = addons.addon_apps({"MyBenchWorkbench": ("My Bench", files)}, [os.path.dirname(path)], set())
        self.assertEqual([a["id"] for a in apps], ["addon_MyBenchWorkbench"])


if __name__ == "__main__":
    unittest.main()

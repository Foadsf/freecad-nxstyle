# SPDX-License-Identifier: LGPL-2.1-or-later
"""Preferences brought from the normal FreeCAD profile into the NX profile (launch_nx.import_preferences and the
settings layer in nxstyle.config), against a fake normal profile in a temporary folder. No FreeCAD needed."""

import copy
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "NXStyle"))

import launch_nx  # noqa: E402
from test_prefs import VIEW, Group, freecad  # noqa: E402

NORMAL_CFG = """<?xml version="1.0" encoding="utf-8"?>
<FCParameters>
  <FCParamGroup Name="Root">
    <FCParamGroup Name="BaseApp">
      <FCParamGroup Name="Preferences">
        <FCParamGroup Name="View">
          <FCText Name="NavigationStyle">Gui::TouchpadNavigationStyle</FCText>
          <FCInt Name="OrbitStyle" Value="2"/>
          <FCBool Name="ZoomAtCursor" Value="0"/>
          <FCBool Name="InvertZoom" Value="0"/>
          <FCFloat Name="ZoomStep" Value="0.350000000000"/>
          <FCBool Name="ShowNaviCube" Value="1"/>
          <FCUInt Name="BackgroundColor" Value="4294967295"/>
        </FCParamGroup>
        <FCParamGroup Name="NaviCube">
          <FCInt Name="CubeSize" Value="160"/>
        </FCParamGroup>
        <FCParamGroup Name="Macro">
          <FCText Name="MacroPath">{MACROS}</FCText>
          <FCBool Name="RecordGui" Value="0"/>
        </FCParamGroup>
      </FCParamGroup>
      <FCParamGroup Name="Macro">
        <FCParamGroup Name="Macros">
          <FCParamGroup Name="Std_Macro_0">
            <FCText Name="Script">gear.FCMacro</FCText>
            <FCText Name="Menu">Make Gear</FCText>
          </FCParamGroup>
        </FCParamGroup>
      </FCParamGroup>
    </FCParamGroup>
  </FCParamGroup>
</FCParameters>
"""

OLDER_CFG = NORMAL_CFG.replace("Gui::TouchpadNavigationStyle", "Gui::OpenInventorNavigationStyle")


def params(cfg, *path):
    """{name: (tag, value)} of one parameter group of a user.cfg."""
    g = launch_nx._param_group(ET.parse(cfg).getroot(), tuple(path))
    if g is None:
        return {}
    return {e.get("Name"): (e.tag, launch_nx._param_value(e)) for e in g if e.tag != "FCParamGroup"}


def macro_commands(cfg):
    g = launch_nx._param_group(ET.parse(cfg).getroot(), ("BaseApp", "Macro", "Macros"))
    return {} if g is None else {c.get("Name"): launch_nx._script(c) for c in g.findall("FCParamGroup")}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Fixture(unittest.TestCase):
    """A fake normal profile, in both the Windows/macOS layout (one folder) and the Linux one (config + data):
    an unversioned 1.0 user.cfg, a v1-1 one (the one to take for FreeCAD 1.1) and a v1-2 one (newer: ignored)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nx-import-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.macros = self.tmp / "normal-macros"            # the normal profile's MacroPath
        self.macros.mkdir()
        (self.macros / "gear.FCMacro").write_text("# gear from the normal profile\n", encoding="utf-8")
        (self.macros / "bolt.py").write_text("# bolt\n", encoding="utf-8")
        (self.macros / "notes.txt").write_text("not a macro\n", encoding="utf-8")
        for base in (self.tmp / "appdata" / "FreeCAD", self.tmp / "xdgconfig" / "FreeCAD",
                     self.tmp / "home" / "Library" / "Application Support" / "FreeCAD"):
            for sub, text in (("", OLDER_CFG), ("v1-1", NORMAL_CFG),
                              ("v1-2", NORMAL_CFG.replace("Touchpad", "Gesture"))):
                (base / sub).mkdir(parents=True, exist_ok=True)
                (base / sub / "user.cfg").write_text(text.replace("{MACROS}", self.macros.as_posix()),
                                                     encoding="utf-8")
        env = {"APPDATA": str(self.tmp / "appdata"), "XDG_CONFIG_HOME": str(self.tmp / "xdgconfig"),
               "XDG_DATA_HOME": str(self.tmp / "xdgdata")}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(launch_nx.Path, "home", classmethod(lambda cls: self.tmp / "home"))):
            p.start()
            self.addCleanup(p.stop)
        self.profile = self.tmp / "nx-profile"
        self.paths = launch_nx.prepare_profile(self.profile)
        launch_nx.seed_user_cfg(self.paths, (1, 1, 4))
        self.target = self.paths["home"] / "user.cfg"
        self.normal = launch_nx.normal_profile((1, 1, 4))
        self.source = self.normal["config"] / "user.cfg"


class NormalProfileTests(Fixture):
    def test_this_versions_folder_is_taken(self):
        self.assertEqual(self.normal["config"].name, "v1-1")
        self.assertIn("Touchpad", self.source.read_text(encoding="utf-8"))

    def test_an_older_freecad_takes_the_unversioned_folder(self):
        self.assertEqual(launch_nx.normal_profile((1, 0, 2))["config"].name, "FreeCAD")

    def test_none_when_there_is_no_normal_profile(self):
        with mock.patch.dict(os.environ, {"APPDATA": str(self.tmp / "nothing"),
                                          "XDG_CONFIG_HOME": str(self.tmp / "nothing"),
                                          "XDG_DATA_HOME": str(self.tmp / "nothing")}), \
                mock.patch.object(launch_nx.Path, "home", classmethod(lambda cls: self.tmp / "nothing")):
            self.assertIsNone(launch_nx.normal_profile((1, 1, 4)))


class ImportTests(Fixture):
    def test_navigation_copies_style_and_orbit_style_only(self):
        record = launch_nx.import_preferences(self.source, self.target, ["navigation"])
        view = params(self.target, "BaseApp", "Preferences", "View")
        self.assertEqual(view["NavigationStyle"], ("FCText", "Gui::TouchpadNavigationStyle"))
        self.assertEqual(view["OrbitStyle"], ("FCInt", 2))          # free turntable
        self.assertEqual(view["ZoomStep"], ("FCFloat", 0.35))
        self.assertEqual(view["ShowNaviCube"], ("FCBool", False))    # the view cube is a group of its own
        self.assertNotIn("BackgroundColor", view)                    # not a navigation preference
        self.assertEqual(record["settings"], {"navigation": "Gui::TouchpadNavigationStyle",
                                              "zoom_at_cursor": False, "invert_wheel_zoom": False})

    def test_the_normal_profile_is_only_read(self):
        """Every file outside the NX profile, the macro folder included, is unchanged, and none is added."""
        def outside():
            return {p: digest(p) for p in self.tmp.rglob("*") if p.is_file() and self.profile not in p.parents}
        before = outside()
        launch_nx.bring_preferences(self.paths, launch_nx.import_groups("all"), (1, 1, 4), "")
        self.assertEqual(outside(), before)
        self.assertEqual(len(before), 12)                    # 9 user.cfg and 3 files in the macro folder

    def test_the_nx_profile_keeps_what_was_not_imported(self):
        launch_nx.import_preferences(self.source, self.target, ["navigation"])
        start = params(self.target, "BaseApp", "Preferences", "Mod", "Start")
        self.assertEqual(start["FirstStart2024"], ("FCBool", False))    # seed_user_cfg's, untouched

    def test_view_cube_group(self):
        launch_nx.import_preferences(self.source, self.target, ["view_cube"])
        self.assertEqual(params(self.target, "BaseApp", "Preferences", "View")["ShowNaviCube"], ("FCBool", True))
        self.assertEqual(params(self.target, "BaseApp", "Preferences", "NaviCube")["CubeSize"], ("FCInt", 160))

    def test_macro_commands_are_merged_not_replaced(self):
        root = ET.parse(self.target)
        own = ET.SubElement(launch_nx._param_group(root.getroot(), ("BaseApp", "Macro", "Macros"), create=True),
                            "FCParamGroup", Name="Std_Macro_0")
        ET.SubElement(own, "FCText", Name="Script").text = "mine.FCMacro"
        root.write(self.target, encoding="UTF-8", xml_declaration=True)
        nx_macros = self.paths["data"] / "Macro"
        record = launch_nx.import_preferences(self.source, self.target, ["macros"], self.normal["data"], nx_macros)
        self.assertEqual(macro_commands(self.target), {"Std_Macro_0": "mine.FCMacro", "Std_Macro_1": "gear.FCMacro"})
        self.assertEqual(record["parameters"]["BaseApp/Macro/Macros"]["added"],
                         [{"command": "Std_Macro_1", "script": "gear.FCMacro"}])
        # the macro files are copied; the NX profile's macro folder stays its own
        self.assertEqual(sorted(p.name for p in nx_macros.iterdir()), ["bolt.py", "gear.FCMacro"])
        self.assertEqual(params(self.target, "BaseApp", "Preferences", "Macro")["MacroPath"],
                         ("FCText", str(nx_macros)))
        # at the next start nothing is added twice, and a macro edited in the NX profile is kept
        (nx_macros / "gear.FCMacro").write_text("# edited in NX-Style\n", encoding="utf-8")
        again = launch_nx.import_preferences(self.source, self.target, ["macros"], self.normal["data"], nx_macros)
        self.assertEqual(again["parameters"]["BaseApp/Macro/Macros"]["added"], [])
        self.assertEqual(again["parameters"]["BaseApp/Macro/Macros"]["commands"],
                         [{"command": "Std_Macro_1", "script": "gear.FCMacro"}])     # had: still reported
        self.assertEqual(again["parameters"]["macro files"]["kept"], ["bolt.py", "gear.FCMacro"])
        self.assertEqual((nx_macros / "gear.FCMacro").read_text(encoding="utf-8"), "# edited in NX-Style\n")
        self.assertEqual(len(macro_commands(self.target)), 2)

    def test_a_macro_path_of_the_nx_profile_outside_it_gets_no_files(self):
        root = ET.parse(self.target)
        ET.SubElement(launch_nx._param_group(root.getroot(), ("BaseApp", "Preferences", "Macro"), create=True),
                      "FCText", Name="MacroPath").text = str(self.macros)      # pointed at the normal folder
        root.write(self.target, encoding="UTF-8", xml_declaration=True)
        msg = launch_nx.bring_preferences(self.paths, ["macros"], (1, 1, 4), "")
        self.assertIn("macro files not copied", msg)
        self.assertEqual(sorted(p.name for p in self.macros.iterdir()), ["bolt.py", "gear.FCMacro", "notes.txt"])
        self.assertFalse((self.paths["data"] / "Macro").exists())

    def test_group_names(self):
        self.assertEqual(launch_nx.import_groups(True), ["navigation"])
        self.assertEqual(launch_nx.import_groups(None), [])
        self.assertEqual(launch_nx.import_groups([]), [])
        self.assertEqual(launch_nx.import_groups("navigation, macros"), ["navigation", "macros"])
        self.assertEqual(launch_nx.import_groups(["all"]), list(launch_nx.IMPORT_GROUPS))
        with self.assertRaises(ValueError):
            launch_nx.import_groups("navigation,colours")


class LauncherTests(Fixture):
    """bring_preferences, as main() calls it at each start."""

    def test_record_written_and_removed_when_switched_off(self):
        msg = launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), "")
        record = json.loads((self.paths["home"] / launch_nx.IMPORTED_FILE).read_text(encoding="utf-8"))
        self.assertEqual(record["settings"]["navigation"], "Gui::TouchpadNavigationStyle")
        self.assertIn("navigation", msg)
        msg = launch_nx.bring_preferences(self.paths, [], (1, 1, 4), "")
        self.assertFalse((self.paths["home"] / launch_nx.IMPORTED_FILE).exists())
        self.assertIn("none imported", msg)

    def test_a_named_normal_profile(self):
        other = self.tmp / "custom"
        other.mkdir()
        (other / "user.cfg").write_text(NORMAL_CFG.replace("Touchpad", "Maya"), encoding="utf-8")
        launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), str(other))
        self.assertEqual(params(self.target, "BaseApp", "Preferences", "View")["NavigationStyle"][1],
                         "Gui::MayaNavigationStyle")

    def test_an_unreadable_normal_user_cfg_imports_nothing_and_does_not_stop_the_start(self):
        broken = self.tmp / "broken"
        broken.mkdir()
        (broken / "user.cfg").write_text("<FCParameters><FCParamGroup Name='Root'>", encoding="utf-8")
        launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), "")      # an earlier good import
        msg = launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), str(broken))
        self.assertIn("nothing imported", msg)
        self.assertFalse((self.paths["home"] / launch_nx.IMPORTED_FILE).exists())

    def test_config_and_data_folders_apart_as_on_linux(self):
        config, data = self.tmp / "cfg", self.tmp / "share"
        config.mkdir()
        (config / "user.cfg").write_text(NORMAL_CFG.replace("Touchpad", "Maya").replace(
            "<FCText Name=\"MacroPath\">{MACROS}</FCText>", ""), encoding="utf-8")
        (data / "Macro").mkdir(parents=True)
        (data / "Macro" / "gear.FCMacro").write_text("# from share\n", encoding="utf-8")
        launch_nx.bring_preferences(self.paths, ["navigation", "macros"], (1, 1, 4),
                                    {"config": str(config), "data": str(data)})
        self.assertEqual(params(self.target, "BaseApp", "Preferences", "View")["NavigationStyle"][1],
                         "Gui::MayaNavigationStyle")
        self.assertEqual((self.paths["data"] / "Macro" / "gear.FCMacro").read_text(encoding="utf-8"),
                         "# from share\n")       # no MacroPath: FreeCAD's default <data>/Macro

    def test_no_normal_profile_says_so_and_writes_nothing(self):
        msg = launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), str(self.tmp / "missing"))
        self.assertIn("not found", msg)
        self.assertFalse((self.paths["home"] / launch_nx.IMPORTED_FILE).exists())


class SettingsLayerTests(Fixture):
    """nxstyle.config: imported values sit between the defaults and nxstyle.json, and prefs.apply writes them."""

    def load(self, user=None):
        tree = {}
        if user is not None:
            (self.paths["home"] / "nxstyle.json").write_text(json.dumps(user), encoding="utf-8")
        with mock.patch.dict(sys.modules, freecad(tree)), \
                mock.patch.dict(os.environ, {"NXSTYLE_PROFILE": str(self.profile)}):
            for m in ("nxstyle.prefs", "nxstyle.config"):
                sys.modules.pop(m, None)
            config = importlib.import_module("nxstyle.config")
            prefs = importlib.import_module("nxstyle.prefs")
            cfg = config.load()
            prefs.apply(copy.deepcopy(cfg))
        for m in ("nxstyle.prefs", "nxstyle.config"):
            sys.modules.pop(m, None)
        return cfg, tree.get(VIEW, Group())

    def test_imported_navigation_applies(self):
        launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), "")
        cfg, view = self.load()
        self.assertEqual(cfg["navigation"], "Gui::TouchpadNavigationStyle")
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::TouchpadNavigationStyle")
        self.assertIs(view.GetBool("ZoomAtCursor"), False)

    def test_nx_styles_own_navigation_setting_still_decides(self):
        """Negative control: a value set in nxstyle.json is not overwritten by the imported one."""
        launch_nx.bring_preferences(self.paths, ["navigation"], (1, 1, 4), "")
        cfg, view = self.load({"navigation": "nx", "zoom_at_cursor": True})
        self.assertEqual(cfg["navigation"], "nx")
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::BlenderNavigationStyle")   # NX-Style's base
        self.assertIs(view.GetBool("ZoomAtCursor"), True)
        self.assertIs(view.GetBool("InvertZoom"), False)          # not set in nxstyle.json: the imported one

    def test_without_import_nothing_changes(self):
        cfg, view = self.load()
        self.assertEqual(cfg["navigation"], "nx")
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::BlenderNavigationStyle")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Issue #44, "navigation": "native" did not take effect: which nxstyle.json is read and what the launcher says
about it (launch_nx.settings_report), the same file read by NXStyle (nxstyle.config.load) with the precedence
defaults < imported < nxstyle.json, navigation names (nxstyle.prefs), and FreeCAD 26.x version strings, profile
folders and checks, from fixtures (no FreeCAD 26.3 here). No FreeCAD needed."""

import contextlib
import importlib
import io
import json
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
from test_prefs import VIEW, Group, freecad  # noqa: E402


def nxstyle_modules(tree, version=("1", "1", "4")):
    """nxstyle.config and nxstyle.prefs imported against a stand-in FreeCAD of this version."""
    mods = freecad(tree)
    mods["FreeCAD"].Version = lambda: list(version)
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.dict(sys.modules, mods))
    for m in ("nxstyle.prefs", "nxstyle.config"):
        sys.modules.pop(m, None)
    config = importlib.import_module("nxstyle.config")
    prefs = importlib.import_module("nxstyle.prefs")
    stack.callback(lambda: [sys.modules.pop(m, None) for m in ("nxstyle.prefs", "nxstyle.config")])
    return stack, config, prefs


class Profile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nx-settings-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.profile = self.tmp / "profile"
        self.paths = launch_nx.prepare_profile(self.profile)
        self.cfg_dir = self.paths["home"]

    def write(self, name, text, encoding="utf-8"):
        (self.cfg_dir / name).write_text(text, encoding=encoding)

    def report(self):
        return launch_nx.settings_report(self.profile)

    def nxstyle_load(self, version=("1", "1", "4")):
        """NXStyle's own start: config.load() and prefs.apply() in this profile; (cfg, View parameters, source)."""
        tree = {}
        stack, config, prefs = nxstyle_modules(tree, version)
        with stack, mock.patch.dict(os.environ, {"NXSTYLE_PROFILE": str(self.profile)}):
            cfg = config.load()
            prefs.apply(dict(cfg))
            source = dict(config.source)
        return cfg, tree.get(VIEW, Group()), source


class WhichFileTests(Profile):
    def test_names_the_file_it_reads_and_what_it_sets(self):
        self.write("nxstyle.json", json.dumps({"navigation": "native", "background": "white"}))
        self.assertEqual(self.report()[0], f"{self.cfg_dir / 'nxstyle.json'} (navigation, background)")

    def test_says_when_there_is_none(self):
        line, = self.report()
        self.assertTrue(line.startswith("none: ") and "does not exist" in line, line)

    def test_an_old_file_in_the_profile_root_is_named(self):
        (self.profile / "nxstyle.json").write_text('{"navigation": "native"}', encoding="utf-8")
        self.assertEqual(self.report()[0], f"{self.profile / 'nxstyle.json'} (navigation)")

    def test_a_broken_file_is_reported_not_silently_dropped(self):
        self.write("nxstyle.json", '{"navigation": native}')
        line = self.report()[0]
        self.assertIn("could not be read", line)
        self.assertIn("line 1", line)


class NativeTakesEffectTests(Profile):
    """The file the launcher names is the one NXStyle reads, and "native" becomes FreeCAD's style."""

    def test_native_reaches_freecads_navigation_parameter(self):
        self.write("nxstyle.json", '{"navigation": "native"}')
        cfg, view, source = self.nxstyle_load()
        self.assertEqual(source["path"], str(self.cfg_dir / "nxstyle.json"))
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::SiemensNXNavigationStyle")

    def test_byte_order_mark_is_read(self):
        """Windows editors may save UTF-8 with a BOM; before the fix NXStyle ignored such a file entirely."""
        self.write("nxstyle.json", '{"navigation": "native"}', encoding="utf-8-sig")
        self.assertTrue(self.report()[0].endswith("(navigation)"))
        cfg, view, source = self.nxstyle_load()
        self.assertIsNone(source["error"])
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::SiemensNXNavigationStyle")

    def test_a_broken_file_leaves_nx_defaults_and_says_why(self):
        """The control: the same setting in a file that is not JSON does not apply, and the reason is recorded."""
        self.write("nxstyle.json", '{"navigation": native}')
        cfg, view, source = self.nxstyle_load()
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::BlenderNavigationStyle")
        self.assertTrue(source["error"])

    def test_nxstyle_json_wins_over_imported_preferences(self):
        self.write(launch_nx.IMPORTED_FILE, json.dumps({"settings": {"navigation": "Gui::TouchpadNavigationStyle",
                                                                     "zoom_at_cursor": False}}))
        self.write("nxstyle.json", '{"navigation": "native"}')
        cfg, view, _ = self.nxstyle_load()
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::SiemensNXNavigationStyle")
        self.assertIs(view.GetBool("ZoomAtCursor"), False)           # not in nxstyle.json: the imported one

    def test_native_on_freecad_26(self):
        self.write("nxstyle.json", '{"navigation": "native"}')
        _, view, _ = self.nxstyle_load(("26", "3", "0RC2"))
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::SiemensNXNavigationStyle")

    def test_native_on_freecad_1_0_falls_back_to_nx_base_style(self):
        self.write("nxstyle.json", '{"navigation": "native"}')
        _, view, _ = self.nxstyle_load(("1", "0", "2"))
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::BlenderNavigationStyle")


class DefaultsFileTests(Profile):
    """nxstyle.defaults.json is the only settings file a new profile has; a change made there is never read."""

    def test_nxstyle_writes_it_with_a_note_and_the_launcher_sees_no_edit(self):
        self.nxstyle_load()
        data = json.loads((self.cfg_dir / "nxstyle.defaults.json").read_text(encoding="utf-8"))
        self.assertIn("nxstyle.json", data["_note"])
        self.assertEqual(data["navigation"], "nx")
        self.assertEqual(len(self.report()), 1)                       # only the "none:" line: no false warning

    def test_an_edit_there_is_reported_and_has_no_effect(self):
        self.nxstyle_load()
        ref = self.cfg_dir / "nxstyle.defaults.json"
        ref.write_text(ref.read_text(encoding="utf-8").replace('"navigation": "nx"', '"navigation": "native"'),
                       encoding="utf-8")
        warn = [line for line in self.report() if "nxstyle.defaults.json was changed" in line]
        self.assertEqual(len(warn), 1, self.report())
        self.assertIn("navigation='native'", warn[0])
        cfg, view, source = self.nxstyle_load()
        self.assertEqual(view.GetString("NavigationStyle"), "Gui::BlenderNavigationStyle")   # never read
        self.assertEqual(source["defaults edited"], {"navigation": "native"})
        self.assertEqual(len(self.report()), 1)                       # rewritten: once only

    def test_an_old_unstamped_file_is_reported_carefully(self):
        defaults = launch_nx.module_literal(launch_nx.CONFIG_SOURCE, "DEFAULTS")
        self.write("nxstyle.defaults.json", json.dumps(dict(defaults, navigation="native"), indent=2))
        warn = [line for line in self.report() if "nxstyle.defaults.json" in line]
        self.assertEqual(len(warn), 1)
        self.assertIn("lists values other than NX-Style's defaults (navigation='native')", warn[0])

    def test_no_warning_once_the_setting_is_in_nxstyle_json(self):
        defaults = launch_nx.module_literal(launch_nx.CONFIG_SOURCE, "DEFAULTS")
        self.write("nxstyle.defaults.json", json.dumps(dict(defaults, navigation="native"), indent=2))
        self.write("nxstyle.json", '{"navigation": "native"}')
        self.assertEqual(len(self.report()), 1)

    def test_fingerprints_agree(self):
        defaults = launch_nx.module_literal(launch_nx.CONFIG_SOURCE, "DEFAULTS")
        stack, config, _ = nxstyle_modules({})
        with stack:
            self.assertEqual(config.fingerprint(defaults), launch_nx.settings_fingerprint(defaults))
            self.assertEqual(config.DEFAULTS, defaults)


class OrbitSeedTests(Profile):
    """FreeCAD's Preferences write the orbit style they show whenever they are saved: Rounded Arcball (4) on 1.1
    when none is set. A profile with NX-Style's own MB2 gets Trackball Classic (3), NX's rotation."""

    def orbit_after_start(self, user=None, before=None, version=("1", "1", "4")):
        if user is not None:
            self.write("nxstyle.json", json.dumps(user))
        tree = {}
        stack, config, prefs = nxstyle_modules(tree, version)
        if before is not None:
            tree.setdefault(VIEW, Group()).SetInt("OrbitStyle", before)
        with stack, mock.patch.dict(os.environ, {"NXSTYLE_PROFILE": str(self.profile)}):
            prefs.apply(config.load())
        return tree[VIEW].GetInt("OrbitStyle", -1)

    def test_a_profile_without_one_gets_trackball_classic(self):
        self.assertEqual(self.orbit_after_start(), 3)
        self.assertEqual(self.orbit_after_start(version=("26", "3", "0RC2")), 3)

    def test_a_chosen_or_imported_one_is_kept(self):
        self.assertEqual(self.orbit_after_start(before=2), 2)
        self.assertEqual(self.orbit_after_start(before=4), 4)

    def test_not_with_freecads_own_navigation(self):
        self.assertEqual(self.orbit_after_start({"navigation": "native"}), -1)

    def test_not_on_freecad_1_0_which_has_no_trackball_classic(self):
        self.assertEqual(self.orbit_after_start(version=("1", "0", "2")), -1)


class LauncherSettingsTests(Profile):
    def test_dfm_is_a_known_setting(self):
        """{"dfm": "none"} switches the DFM add-on off (launch_nx.find_dfm): no "unknown setting" line."""
        self.write("nxstyle.json", '{"dfm": "none"}')
        self.assertEqual(self.report(), [f"{self.cfg_dir / 'nxstyle.json'} (dfm)"])
        install = launch_nx.Install(self.tmp / "freecad.exe", (1, 1, 4))
        self.assertEqual(launch_nx.find_dfm(self.profile, install), ((), "off (nxstyle.json: dfm = 'none')"))

    def test_every_setting_the_launcher_reads_is_known(self):
        import re
        defaults = launch_nx.module_literal(launch_nx.CONFIG_SOURCE, "DEFAULTS")
        src = (ROOT / "launch_nx.py").read_text(encoding="utf-8")
        read = set(re.findall(r'(?:cfg|settings|read_settings\([^)]*\))\.get\("([a-z_]+)"', src))
        self.assertTrue(read and read <= set(defaults), sorted(read - set(defaults)))


class CarbonSettingsTests(Profile):
    def test_saving_the_carbon_connection_keeps_a_bom_file(self):
        """carbon_ui.save_settings reads nxstyle.json before it adds the server; a BOM must not break it."""
        import types
        self.write("nxstyle.json", '{"navigation": "native"}', encoding="utf-8-sig")
        stack, config, _ = nxstyle_modules({})
        class AnyClass:                         # QtWidgets.QDialog and friends, only subclassed at import
            def __getattr__(self, name):
                return object

        qt = types.ModuleType("nxstyle.qt")
        qt.QtCore = qt.QtWidgets = AnyClass()
        with stack, mock.patch.dict(sys.modules, {"nxstyle.qt": qt}), \
                mock.patch.dict(os.environ, {"NXSTYLE_PROFILE": str(self.profile)}):
            sys.modules.pop("nxstyle.carbon_ui", None)
            carbon_ui = importlib.import_module("nxstyle.carbon_ui")
            carbon_ui.save_settings("https://carbon.example", "Main")
            sys.modules.pop("nxstyle.carbon_ui", None)
        data = json.loads((self.cfg_dir / "nxstyle.json").read_text(encoding="utf-8"))
        self.assertEqual(data, {"navigation": "native", "carbon": {"url": "https://carbon.example",
                                                                   "location": "Main"}})


class NamesTests(Profile):
    def test_misspelt_setting_is_named_with_a_suggestion(self):
        self.write("nxstyle.json", '{"navigaton": "native"}')
        self.assertIn("unknown setting 'navigaton' is ignored (did you mean 'navigation'?)", self.report())

    def test_navigation_that_is_no_style(self):
        self.write("nxstyle.json", '{"navigation": "nxt"}')
        self.assertTrue(any(line.startswith("navigation 'nxt' is no navigation style") for line in self.report()))

    def test_menu_names_are_accepted(self):
        for name, cls in (("Touchpad", "Gui::TouchpadNavigationStyle"), ("Siemens NX", "Gui::SiemensNXNavigationStyle"),
                          ("OpenInventor", "Gui::InventorNavigationStyle"), ("blender", "Gui::BlenderNavigationStyle"),
                          ("Gui::GestureNavigationStyle", "Gui::GestureNavigationStyle")):
            self.write("nxstyle.json", json.dumps({"navigation": name}))
            self.assertEqual(len(self.report()), 1, (name, self.report()))
            _, view, _ = self.nxstyle_load()
            self.assertEqual(view.GetString("NavigationStyle"), cls, name)

    def test_launcher_and_nxstyle_share_the_style_table(self):
        styles = launch_nx.module_literal(launch_nx.PREFS_SOURCE, "FREECAD_STYLES")
        stack, _, prefs = nxstyle_modules({})
        with stack:
            for name in ("Touchpad", "Siemens NX", "Gui::RevitNavigationStyle", "inventor", "nxt", "Maya Gesture"):
                self.assertEqual(launch_nx.style_class(name, styles), prefs.style_class(name), name)


class Freecad26Tests(unittest.TestCase):
    """FreeCAD 26.3 RC2, the reporter's version, from fixture strings and folders."""

    def test_version_output(self):
        for text, want in (("FreeCAD 26.3.0RC2 Revision: 45678 (Git)\n", (26, 3, 0)),
                           ("FreeCAD 26.3 RC2\n", (26, 3, 0)),
                           ("FreeCAD 26.3.1 Revision: 1 (Git)", (26, 3, 1)),
                           ("FreeCAD 1.1.4 Revision: 20260928 (Git shallow)\n", (1, 1, 4)),
                           ("FreeCAD 1.1.0dev Revision: 4321 (Git)", (1, 1, 0))):
            self.assertEqual(launch_nx.version_from_output(text), want, text)
        self.assertIsNone(launch_nx.version_from_output("Qt: could not find the platform plugin"))

    def test_version_from_install_paths(self):
        for path in (r"C:\Program Files\FreeCAD 26.3\bin\freecad.exe",
                     "C:/tools/FreeCAD_26.3.0-RC2-conda-Windows-x86_64-py311/bin/freecad.exe",
                     "/home/u/Apps/FreeCAD_26.3.0-RC2-conda-Linux-x86_64-py311.AppImage"):
            self.assertEqual(launch_nx.version_from_path(Path(path)), (26, 3, 0), path)

    def test_26_sorts_after_1_1(self):
        installs = [launch_nx.Install(Path("a"), (1, 1, 4)), launch_nx.Install(Path("b"), (26, 3, 0))]
        installs.sort(key=lambda i: i.version, reverse=True)
        self.assertEqual(installs[0].version_str, "26.3.0")

    def test_profile_folder_and_dry_run(self):
        tmp = Path(tempfile.mkdtemp(prefix="nx-26-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        install = launch_nx.Install(tmp / "freecad.exe", (26, 3, 0))
        out = io.StringIO()
        with mock.patch.object(launch_nx, "pick_install", return_value=install), \
                mock.patch.object(launch_nx, "default_profile_root", return_value=tmp), \
                contextlib.redirect_stdout(out):
            self.assertEqual(launch_nx.main(["--dry-run"]), 0)
        info = json.loads(out.getvalue())
        self.assertEqual(Path(info["profile"]).name, "profile-26.3")
        self.assertEqual(info["version"], "26.3.0")
        self.assertTrue(info["settings"][0].startswith("none: "), info["settings"])

    def test_seed_uses_the_1_1_stylesheet(self):
        tmp = Path(tempfile.mkdtemp(prefix="nx-26-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        paths = launch_nx.prepare_profile(tmp / "p")
        launch_nx.seed_user_cfg(paths, (26, 3, 0))
        text = (paths["home"] / "user.cfg").read_text(encoding="utf-8")
        self.assertIn(">FreeCAD.qss<", text)
        self.assertIn(">FreeCAD Light<", text)

    def test_normal_profile_takes_the_v26_3_folder(self):
        tmp = Path(tempfile.mkdtemp(prefix="nx-26-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        base = tmp / "appdata" / "FreeCAD"
        for sub in ("v1-1", "v26-3", "v26-4"):
            (base / sub).mkdir(parents=True)
            (base / sub / "user.cfg").write_text("<FCParameters/>", encoding="utf-8")
        with mock.patch.dict(os.environ, {"APPDATA": str(tmp / "appdata"), "XDG_CONFIG_HOME": str(tmp / "appdata"),
                                          "XDG_DATA_HOME": str(tmp / "appdata")}), \
                mock.patch.object(launch_nx.Path, "home", classmethod(lambda cls: tmp / "home")):
            if sys.platform == "darwin":
                self.skipTest("macOS keeps the normal profile under ~/Library")
            self.assertEqual(launch_nx.normal_profile((26, 3, 0))["config"].name, "v26-3")
            self.assertEqual(launch_nx.normal_profile((1, 1, 4))["config"].name, "v1-1")

    def test_nxt_and_native_style_are_allowed(self):
        tmp = Path(tempfile.mkdtemp(prefix="nx-26-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        install = launch_nx.Install(tmp / "freecad.exe", (26, 3, 0))
        _, why = launch_nx.find_nxt(tmp, install, enabled=True)
        self.assertNotIn("needs FreeCAD", why)
        stack, _, prefs = nxstyle_modules({}, ("26", "3", "0RC2"))
        with stack:
            self.assertTrue(prefs.has_native_nx_style())


if __name__ == "__main__":
    unittest.main()

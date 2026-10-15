# SPDX-License-Identifier: LGPL-2.1-or-later
"""Launcher tests that need no FreeCAD: profile isolation, env, command line."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch_nx  # noqa: E402


class ProfileTests(unittest.TestCase):
    def test_profile_dirs_created_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = launch_nx.prepare_profile(Path(tmp) / "p")
            for key in ("home", "data", "temp"):
                self.assertTrue(paths[key].is_dir(), key)   # FreeCAD ignores missing dirs
            self.assertTrue((paths["data"] / "Mod").is_dir())

    def test_refuses_vanilla_profile(self):
        vanilla = launch_nx.vanilla_dirs()[0]
        with self.assertRaises(SystemExit):
            launch_nx.prepare_profile(vanilla / "nx")

    def test_refuses_parent_of_vanilla_profile(self):
        vanilla = launch_nx.vanilla_dirs()[0]
        with self.assertRaises(SystemExit):
            launch_nx.prepare_profile(vanilla.parent)

    def test_reset_removes_old_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "p"
            paths = launch_nx.prepare_profile(p)
            marker = paths["home"] / "user.cfg"
            marker.write_text("x")
            launch_nx.prepare_profile(p, reset=True)
            self.assertFalse(marker.exists())


class SeedTests(unittest.TestCase):
    def test_seeds_new_profile_for_each_version(self):
        import xml.etree.ElementTree as ET
        for version, sheet in (((1, 0, 2), "FreeCAD Light.qss"), ((1, 1, 4), "FreeCAD.qss")):
            with tempfile.TemporaryDirectory() as tmp:
                paths = launch_nx.prepare_profile(Path(tmp) / "p")
                self.assertTrue(launch_nx.seed_user_cfg(paths, version))
                tree = ET.parse(paths["home"] / "user.cfg")
                texts = {e.get("Name"): (e.text or "") for e in tree.iter("FCText")}
                self.assertEqual(texts["StyleSheet"], sheet)
                self.assertEqual(texts["Widgets"], "")          # no panels in overlays
                self.assertEqual(tree.getroot().tag, "FCParameters")

    def test_never_overwrites_existing_user_cfg(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = launch_nx.prepare_profile(Path(tmp) / "p")
            cfg = paths["home"] / "user.cfg"
            cfg.write_text("mine")
            self.assertFalse(launch_nx.seed_user_cfg(paths, (1, 1, 4)))
            self.assertEqual(cfg.read_text(), "mine")


class EnvTests(unittest.TestCase):
    def test_env_points_freecad_at_profile_and_drops_inherited_values(self):
        os.environ["FREECAD_USER_HOME"] = "SHOULD-NOT-LEAK"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                paths = launch_nx.prepare_profile(Path(tmp) / "p")
                env = launch_nx.build_env(paths)
                self.assertEqual(env["FREECAD_USER_HOME"], str(paths["home"]))
                self.assertEqual(env["FREECAD_USER_DATA"], str(paths["data"]))
                self.assertEqual(env["FREECAD_USER_TEMP"], str(paths["temp"]))
                self.assertNotIn("SHOULD-NOT-LEAK", launch_nx._clean_env().values())
        finally:
            del os.environ["FREECAD_USER_HOME"]

    def test_command_loads_module_with_M(self):
        inst = launch_nx.Install(Path("freecad"), (1, 0, 2))
        cmd = launch_nx.build_command(inst, ["a.FCStd"], [])
        self.assertEqual(cmd[1:3], ["-M", str(launch_nx.MODULE_DIR)])
        self.assertEqual(cmd[-1], "a.FCStd")
        self.assertTrue((launch_nx.MODULE_DIR / "InitGui.py").is_file())

    def test_command_adds_extra_modules_after_nxstyle(self):
        inst = launch_nx.Install(Path("freecad"), (1, 1, 4))
        cmd = launch_nx.build_command(inst, ["a.FCStd"], [], (Path("strata"),))
        self.assertEqual(cmd[1:5], ["-M", str(launch_nx.MODULE_DIR), "-M", "strata"])
        self.assertEqual(cmd[-1], "a.FCStd")


class VersionProbeTests(unittest.TestCase):
    """On Linux the GUI binary shows --version in a message box; it must never be asked."""

    def test_appimage_is_asked_through_its_bundled_freecadcmd(self):
        img = Path("/opt/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage")
        self.assertEqual(launch_nx._version_command(img), [str(img), "freecadcmd", "--version"])

    def test_console_binary_next_to_gui_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            gui = Path(tmp) / "freecad"
            gui.touch()
            (Path(tmp) / "freecadcmd").touch()
            self.assertEqual(launch_nx._version_command(gui), [str(Path(tmp) / "freecadcmd"), "--version"])

    @unittest.skipIf(os.name == "nt", "the GUI binary prints --version on Windows")
    def test_lone_gui_binary_is_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            gui = Path(tmp) / "freecad"
            gui.touch()
            self.assertIsNone(launch_nx._version_command(gui))

    def test_version_falls_back_to_appimage_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "FreeCAD_1.1.4-Linux-x86_64-py311.AppImage"   # not executable: the probe fails
            img.touch()
            self.assertEqual(launch_nx.probe_version(img), (1, 1, 4))


class StrataTests(unittest.TestCase):
    """Strata is on by default, loaded once: a copy in the NX profile wins over the bundled one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bundled = root / "vendor" / "freecad-strata"
        self.bundled.mkdir(parents=True)
        (self.bundled / "InitGui.py").write_text("")
        self.profile = root / "profile"
        self._saved = launch_nx.STRATA_DIR
        launch_nx.STRATA_DIR = self.bundled

    def tearDown(self):
        launch_nx.STRATA_DIR = self._saved
        self.tmp.cleanup()

    def test_bundled_copy_by_default(self):
        self.assertEqual(launch_nx.find_strata(self.profile)[0], self.bundled)

    def test_profile_install_is_not_loaded_twice(self):
        pkg = self.profile / "data" / "Mod" / "freecad-strata" / "strata"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        where, why = launch_nx.find_strata(self.profile)
        self.assertIsNone(where)
        self.assertIn("NX profile", why)

    def test_switched_off_by_flag_or_config(self):
        self.assertIsNone(launch_nx.find_strata(self.profile, disabled=True)[0])
        (self.profile / "config").mkdir(parents=True)
        (self.profile / "config" / "nxstyle.json").write_text('{"plm": "none"}')
        self.assertIsNone(launch_nx.find_strata(self.profile)[0])

    def test_missing_submodule_says_how_to_get_it(self):
        (self.bundled / "InitGui.py").unlink()
        where, why = launch_nx.find_strata(self.profile)
        self.assertIsNone(where)
        self.assertIn("submodule", why)


class KatydidTests(unittest.TestCase):
    """Katydid is on by default and loaded once, like Strata, and is switched off on its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bundled = root / "vendor" / "Katydid"
        self.bundled.mkdir(parents=True)
        (self.bundled / "InitGui.py").write_text("")
        self.profile = root / "profile"
        self._saved = launch_nx.KATYDID_DIR
        launch_nx.KATYDID_DIR = self.bundled

    def tearDown(self):
        launch_nx.KATYDID_DIR = self._saved
        self.tmp.cleanup()

    def _config(self, text):
        (self.profile / "config").mkdir(parents=True, exist_ok=True)
        (self.profile / "config" / "nxstyle.json").write_text(text)

    def test_bundled_copy_by_default(self):
        self.assertEqual(launch_nx.find_katydid(self.profile)[0], self.bundled)

    def test_profile_install_is_not_loaded_twice(self):
        pkg = self.profile / "data" / "Mod" / "Katydid" / "katydid"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        where, why = launch_nx.find_katydid(self.profile)
        self.assertIsNone(where)
        self.assertIn("NX profile", why)

    def test_switched_off_by_flag_or_config(self):
        self.assertIsNone(launch_nx.find_katydid(self.profile, disabled=True)[0])
        self._config('{"algorithmic_modeling": "none"}')
        self.assertIsNone(launch_nx.find_katydid(self.profile)[0])

    def test_switches_are_independent(self):
        # plm off leaves Katydid on, and Katydid off leaves Strata on
        self._config('{"plm": "none"}')
        self.assertEqual(launch_nx.find_katydid(self.profile)[0], self.bundled)
        self._config('{"algorithmic_modeling": "none"}')
        saved, launch_nx.STRATA_DIR = launch_nx.STRATA_DIR, self.bundled
        try:
            self.assertEqual(launch_nx.find_strata(self.profile)[0], self.bundled)
        finally:
            launch_nx.STRATA_DIR = saved

    def test_missing_submodule_says_how_to_get_it(self):
        (self.bundled / "InitGui.py").unlink()
        where, why = launch_nx.find_katydid(self.profile)
        self.assertIsNone(where)
        self.assertIn("submodule", why)

    def test_settings_in_config_win_over_an_old_root_file(self):
        (self.profile).mkdir(parents=True, exist_ok=True)
        (self.profile / "nxstyle.json").write_text('{"algorithmic_modeling": "none"}')
        self.assertIsNone(launch_nx.find_katydid(self.profile)[0])          # old place still honoured
        self._config('{"algorithmic_modeling": "katydid"}')
        self.assertEqual(launch_nx.find_katydid(self.profile)[0], self.bundled)

    def test_both_modules_on_the_command_line(self):
        inst = launch_nx.Install(Path("freecad.exe"), (1, 1, 4))
        cmd = launch_nx.build_command(inst, [], [], (Path("strata"), Path("katydid")))
        self.assertEqual(cmd[3:7], ["-M", "strata", "-M", "katydid"])


class SheetMetalTests(unittest.TestCase):
    """The SheetMetal add-on behind NX Sheet Metal: bundled, loaded once, switched off on its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bundled = root / "vendor" / "FreeCAD_SheetMetal"
        self.bundled.mkdir(parents=True)
        (self.bundled / "InitGui.py").write_text("")
        self.profile = root / "profile"
        self._saved = launch_nx.SHEETMETAL_DIR
        launch_nx.SHEETMETAL_DIR = self.bundled

    def tearDown(self):
        launch_nx.SHEETMETAL_DIR = self._saved
        self.tmp.cleanup()

    def test_bundled_copy_by_default(self):
        self.assertEqual(launch_nx.find_sheetmetal(self.profile)[0], self.bundled)

    def test_profile_install_is_not_loaded_twice(self):
        mod = self.profile / "data" / "Mod" / "sheetmetal"
        mod.mkdir(parents=True)
        (mod / "SheetMetalCmd.py").write_text("")
        where, why = launch_nx.find_sheetmetal(self.profile)
        self.assertIsNone(where)
        self.assertIn("NX profile", why)

    def test_switched_off_by_flag_or_config(self):
        self.assertIsNone(launch_nx.find_sheetmetal(self.profile, disabled=True)[0])
        (self.profile / "config").mkdir(parents=True)
        (self.profile / "config" / "nxstyle.json").write_text('{"sheet_metal": "none"}')
        self.assertIsNone(launch_nx.find_sheetmetal(self.profile)[0])

    def test_missing_submodule_says_how_to_get_it(self):
        (self.bundled / "InitGui.py").unlink()
        where, why = launch_nx.find_sheetmetal(self.profile)
        self.assertIsNone(where)
        self.assertIn("submodule", why)


class LCInterlockingTests(unittest.TestCase):
    """The LCInterlocking add-on behind Laser Cut: bundled, loaded once, switched off on its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bundled = root / "vendor" / "LCInterlocking"
        self.bundled.mkdir(parents=True)
        (self.bundled / "InitGui.py").write_text("")
        self.profile = root / "profile"
        self._saved = launch_nx.LCINTERLOCKING_DIR
        launch_nx.LCINTERLOCKING_DIR = self.bundled

    def tearDown(self):
        launch_nx.LCINTERLOCKING_DIR = self._saved
        self.tmp.cleanup()

    def dry_run(self, *flags):
        exe = Path(self.tmp.name) / "FreeCAD"          # never run: a lone GUI binary is not asked its version
        exe.write_text("")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            launch_nx.main(["--freecad", str(exe), "--profile", str(self.profile), "--dry-run", *flags])
        return json.loads(out.getvalue())

    def test_bundled_copy_by_default(self):
        self.assertEqual(launch_nx.find_lcinterlocking(self.profile)[0], self.bundled)

    def test_profile_install_is_not_loaded_twice(self):
        pkg = self.profile / "data" / "Mod" / "LCInterlocking" / "lasercut"
        pkg.mkdir(parents=True)
        (pkg / "join.py").write_text("")
        where, why = launch_nx.find_lcinterlocking(self.profile)
        self.assertIsNone(where)
        self.assertIn("NX profile", why)

    def test_switched_off_by_flag_or_config(self):
        self.assertIsNone(launch_nx.find_lcinterlocking(self.profile, disabled=True)[0])
        (self.profile / "config").mkdir(parents=True)
        (self.profile / "config" / "nxstyle.json").write_text('{"laser_cut": "none"}')
        where, why = launch_nx.find_lcinterlocking(self.profile)
        self.assertIsNone(where)
        self.assertIn("laser_cut", why)

    def test_missing_submodule_says_how_to_get_it(self):
        (self.bundled / "InitGui.py").unlink()
        where, why = launch_nx.find_lcinterlocking(self.profile)
        self.assertIsNone(where)
        self.assertIn("submodule", why)

    def test_loaded_with_M_after_the_others(self):
        cmd = self.dry_run()["command"]
        self.assertEqual(cmd[-2:], ["-M", str(self.bundled)])

    def test_flag_keeps_it_off_the_command_line(self):
        res = self.dry_run("--no-lcinterlocking")
        self.assertNotIn(str(self.bundled), res["command"])
        self.assertIn("--no-lcinterlocking", res["lcinterlocking"])

    def test_real_submodule_is_a_freecad_workbench(self):
        real = self._saved
        if not (real / "InitGui.py").is_file():
            self.skipTest("vendor/LCInterlocking not checked out (git submodule update --init)")
        self.assertIn("LCInterlockingWorkbench", (real / "InitGui.py").read_text(encoding="utf-8"))
        self.assertTrue((real / "lasercut" / "join.py").is_file())    # what a profile copy is recognised by


@unittest.skipUnless(os.name == "nt", "job objects are Windows-only")
class MemoryCeilingTests(unittest.TestCase):
    """A runaway test run must stop at its ceiling instead of exhausting the machine."""

    def run_child(self, code, gb=0.5, stats=None):
        # hidden=False: same job limits; a console child opens no window either way
        return launch_nx.run_on_hidden_desktop([sys.executable, "-c", code], dict(os.environ), timeout_s=60,
                                               max_memory_gb=gb, hidden=False, stats=stats)

    def test_runaway_allocation_is_stopped_at_the_ceiling(self):
        stats = {}
        code = self.run_child("b = []\nwhile True: b.append(bytearray(64 << 20))", stats=stats)
        self.assertEqual(code, launch_nx.STATUS_NO_MEMORY)
        self.assertGreaterEqual(stats["peak_mb"], stats["limit_mb"] - 64)

    def test_single_huge_request_is_refused_not_granted(self):
        # FreeCAD's runaway on 2026-10-12 asked for ~15 GB at once
        with tempfile.TemporaryDirectory() as tmp:
            verdict = Path(tmp) / "verdict.txt"
            probe = ("import ctypes\nk = ctypes.WinDLL('kernel32')\nk.VirtualAlloc.restype = ctypes.c_void_p\n"
                     "k.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]\n"
                     "p = k.VirtualAlloc(None, 2 << 30, 0x3000, 4)\n"
                     f"open({str(verdict)!r}, 'w').write('granted' if p else 'refused')")
            self.assertEqual(self.run_child(probe, gb=0.5), launch_nx.STATUS_NO_MEMORY)
            self.assertEqual(verdict.read_text(), "refused")

    def test_modest_run_is_left_alone(self):
        stats = {}
        self.assertEqual(self.run_child("b = bytearray(50 << 20)", stats=stats), 0)
        self.assertGreater(stats["peak_mb"], 40)        # the instrument measured the child

    def test_second_concurrent_run_is_refused(self):
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = ctypes.c_void_p
        held = k.CreateMutexW(None, True, launch_nx.HARNESS_MUTEX)
        try:
            # a different thread must hold it: a Win32 mutex is re-entrant for its owner
            import threading
            result = {}

            def other():
                try:
                    self.run_child("pass")
                except launch_nx.HarnessBusy:
                    result["busy"] = True
            t = threading.Thread(target=other)
            t.start()
            t.join(30)
            self.assertTrue(result.get("busy"))
        finally:
            k.ReleaseMutex(ctypes.c_void_p(held))
            k.CloseHandle(ctypes.c_void_p(held))


if __name__ == "__main__":
    unittest.main()

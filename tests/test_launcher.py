# SPDX-License-Identifier: LGPL-2.1-or-later
"""Launcher tests that need no FreeCAD: profile isolation, env, command line."""

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

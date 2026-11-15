# SPDX-License-Identifier: LGPL-2.1-or-later
"""launch_nx.py --run SCRIPT: the script runner (no FreeCAD), the result judge, and main() with FreeCAD stubbed."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "NXStyle")]

import launch_nx  # noqa: E402
from nxstyle import harness_result, run_script  # noqa: E402

RUN = "run-1"


def script(folder, body):
    p = Path(folder, "job.py")
    p.write_text(body, encoding="utf-8")
    return str(p)


def write_result(out, run=RUN, **result):
    data = dict({"exit_code": 0, "traceback": "", "output": "", "seconds": 0.1, "script": "job.py"}, **result)
    with mock.patch.dict(os.environ, {"NXSTYLE_RUN_ID": run}):
        harness_result.write(os.path.join(out, "run.json"), "run", data, ["script"], ["script"])


def judge(out, child=0):
    with contextlib.redirect_stdout(io.StringIO()) as so, contextlib.redirect_stderr(io.StringIO()) as se:
        code = launch_nx.judge_run(Path(out, "run.json"), RUN, child)
    return code, so.getvalue(), se.getvalue()


class RunPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def run_body(self, body):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return run_script.run_path(script(self.tmp.name, body))

    def test_a_script_that_returns_exits_0_and_its_output_is_kept(self):
        r = self.run_body("import sys\nprint('hello', sys.argv[0].endswith('job.py'), __name__)\n")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["output"], "hello True __main__\n")
        self.assertEqual(r["traceback"], "")

    def test_sys_exit_sets_the_code(self):
        self.assertEqual(self.run_body("import sys\nsys.exit(3)\n")["exit_code"], 3)
        self.assertEqual(self.run_body("import sys\nsys.exit()\n")["exit_code"], 0)
        r = self.run_body("import sys\nsys.exit('no input file')\n")
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("no input file", r["output"])

    def test_an_exception_gives_1_and_its_traceback(self):
        r = self.run_body("print('before')\nraise ValueError('broken part')\n")
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("ValueError: broken part", r["traceback"])
        self.assertEqual(r["output"], "before\n")

    def test_the_scripts_folder_is_importable_and_the_interpreter_is_restored(self):
        Path(self.tmp.name, "helper_mod_for_run.py").write_text("X = 7\n", encoding="utf-8")
        argv, path = sys.argv[:], sys.path[:]
        r = self.run_body("import helper_mod_for_run\nassert helper_mod_for_run.X == 7\n")
        sys.modules.pop("helper_mod_for_run", None)
        self.assertEqual(r["exit_code"], 0, r["traceback"])
        self.assertEqual((sys.argv, sys.path), (argv, path))

    def test_long_output_keeps_its_end(self):
        with mock.patch.object(run_script, "OUTPUT_LIMIT", 50):
            r = self.run_body("for i in range(100):\n    print(i)\n")
        self.assertTrue(r["output"].startswith("[... "))
        self.assertTrue(r["output"].endswith("99\n"))


class Judge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_matches(self):
        self.assertEqual(launch_nx.RESULT_FILES["run"], "run.json")

    def test_the_scripts_code_output_and_traceback_come_back(self):
        write_result(self.out, exit_code=2, output="made 3 parts\n", traceback="Traceback ...\nKeyError: 'x'\n")
        code, so, se = judge(self.out)
        self.assertEqual(code, 2)
        self.assertIn("made 3 parts", so)
        self.assertIn("KeyError", se)

    def test_a_result_of_another_run_is_refused(self):
        write_result(self.out, run="an-old-run")
        self.assertEqual(judge(self.out)[0], launch_nx.EXIT_INVALID_RESULT)

    def test_a_truncated_result_is_refused(self):
        write_result(self.out)
        p = Path(self.out, "run.json")
        p.write_text(p.read_text(encoding="utf-8")[:30], encoding="utf-8")
        self.assertEqual(judge(self.out)[0], launch_nx.EXIT_INVALID_RESULT)

    def test_a_script_that_ended_freecad_itself_gives_freecads_code(self):
        code, _, se = judge(self.out, child=4)
        self.assertEqual(code, 4)
        self.assertIn("os._exit", se)

    def test_a_crash_after_a_clean_script_fails(self):
        write_result(self.out)
        self.assertEqual(judge(self.out, child=-1073741819)[0], launch_nx.EXIT_CHILD_FAILED)


class ThroughMain(unittest.TestCase):
    """launch_nx.main(["--run", ...]) with the FreeCAD run replaced by a stub that plays run_script.run."""

    def main(self, argv, fake):
        install = launch_nx.Install(Path(sys.executable), (1, 1, 4))

        class FakeProc:                      # the non-Windows path waits on a Popen
            def __init__(self, cmd, env=None, **kw):
                self.env = env

            def wait(self, timeout=None):
                return fake(self.env)

            def kill(self):
                pass
        with tempfile.TemporaryDirectory() as prof, \
                mock.patch.object(launch_nx, "pick_install", return_value=install), \
                mock.patch.object(launch_nx, "run_on_hidden_desktop", side_effect=lambda cmd, env, **kw: fake(env)), \
                mock.patch.object(launch_nx.subprocess, "Popen", FakeProc), \
                mock.patch.object(launch_nx, "LOCK_POLL_S", 0), \
                contextlib.redirect_stdout(io.StringIO()) as so, contextlib.redirect_stderr(io.StringIO()) as se:
            code = launch_nx.main(argv + ["--profile", prof, "--no-strata", "--no-katydid", "--no-sheetmetal",
                                          "--no-lcinterlocking"])
        return code, so.getvalue(), se.getvalue()

    def test_script_env_and_exit_code_go_through_and_the_result_folder_is_removed(self):
        seen = {}

        def fake(env):
            seen.update(env)
            with mock.patch.dict(os.environ, {"NXSTYLE_RUN_ID": env["NXSTYLE_RUN_ID"]}):
                harness_result.write(os.path.join(env["NXSTYLE_RUN_OUT"], "run.json"), "run",
                                     {"exit_code": 3, "output": "step tank\n", "traceback": "", "seconds": 1,
                                      "script": env["NXSTYLE_RUN_SCRIPT"]}, ["script"], ["script"])
            return 0
        with tempfile.TemporaryDirectory() as d:
            job = script(d, "pass\n")
            code, so, _ = self.main(["--run", job, "--env", "ES_STEPS=tank", "--env", "ES_GB=5"], fake)
        self.assertEqual(code, 3)
        self.assertIn("step tank", so)
        self.assertEqual(seen["NXSTYLE_RUN_SCRIPT"], str(Path(job).resolve()))
        self.assertEqual((seen["ES_STEPS"], seen["ES_GB"]), ("tank", "5"))
        self.assertNotIn("NXSTYLE_SMOKE_OUT", seen)
        self.assertFalse(Path(seen["NXSTYLE_RUN_OUT"]).exists())

    @unittest.skipUnless(os.name == "nt", "the harness lock is Windows-only")
    def test_lock_wait_waits_and_without_it_the_run_is_refused(self):
        calls = []

        def busy_twice(env):
            calls.append(1)
            if len(calls) <= 2:
                raise launch_nx.HarnessBusy("another run is active")
            write_result(env["NXSTYLE_RUN_OUT"], run=env["NXSTYLE_RUN_ID"])
            return 0
        with tempfile.TemporaryDirectory() as d:
            job = script(d, "pass\n")
            code, so, _ = self.main(["--run", job, "--lock-wait", "60"], busy_twice)
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 3)
            self.assertEqual(so.count("waiting for it"), 1)        # once, not on every poll
            calls.clear()
            self.assertEqual(self.main(["--run", job], busy_twice)[0], 5)
            self.assertEqual(len(calls), 1)

    def test_bad_arguments_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            job = script(d, "pass\n")
            for argv in (["--run", str(Path(d, "missing.py"))], ["--run", job, "--env", "NOEQUALS"],
                         ["--run", job, "--smoke-test", d], ["--run", job, "--lock-wait", "-1"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                        contextlib.redirect_stderr(io.StringIO()):
                    launch_nx.main(argv)


if __name__ == "__main__":
    unittest.main()

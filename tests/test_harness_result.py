# SPDX-License-Identifier: LGPL-2.1-or-later
"""The launcher believes only a complete result of the run it started (launch_nx.judge_result and the
writer in nxstyle.harness_result). No FreeCAD needed: the FreeCAD run itself is stubbed out."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "NXStyle")]

import launch_nx  # noqa: E402
from nxstyle import harness_result  # noqa: E402

RUN = "run-1"


def write(folder, harness="smoke", run=RUN, rows=None, planned=("s_a", "s_b"), ran=("s_a", "s_b"), **extra):
    key = "checks" if harness == "smoke" else "steps"
    if rows is None:
        rows = ([{"name": "control", "ok": True, "status": "pass"}] if harness == "smoke" else
                [{"tutorial": "A: x", "n": 1, "nx": "n", "replay": "r", "outcome": "same", "detail": ""}])
    path = os.path.join(folder, launch_nx.RESULT_FILES[harness])
    with mock.patch.dict(os.environ, {"NXSTYLE_RUN_ID": run}):
        harness_result.write(path, harness, dict({key: rows}, **extra), planned, ran)
    return Path(path)


def judge(path, harness="smoke", child=0, **kw):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
        code = launch_nx.judge_result(Path(path), harness, RUN, child, **kw)
    return code, err.getvalue()


class Contract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_is_the_same_on_both_sides(self):
        self.assertEqual(launch_nx.HARNESS_SCHEMA, harness_result.SCHEMA)

    def test_complete_passing_run_is_accepted(self):
        self.assertEqual(judge(write(self.dir))[0], 0)

    def test_failed_check_fails(self):
        p = write(self.dir, rows=[{"name": "c", "ok": False, "status": "fail"}])
        self.assertEqual(judge(p)[0], 1)

    def test_stale_file_from_another_run_fails(self):
        code, err = judge(write(self.dir, run="an-old-run"))
        self.assertEqual(code, launch_nx.EXIT_INVALID_RESULT)
        self.assertIn("another run", err)

    def test_empty_object_fails(self):
        p = Path(self.dir, "smoke.json")
        p.write_text("{}", encoding="utf-8")
        self.assertEqual(judge(p)[0], launch_nx.EXIT_INVALID_RESULT)

    def test_empty_checks_fail(self):
        self.assertEqual(judge(write(self.dir, rows=[]))[0], launch_nx.EXIT_INVALID_RESULT)

    def test_truncated_file_fails(self):
        p = write(self.dir)
        p.write_text(p.read_text(encoding="utf-8")[:40], encoding="utf-8")
        code, err = judge(p)
        self.assertEqual(code, launch_nx.EXIT_INVALID_RESULT)
        self.assertIn("truncated", err)

    def test_missing_planned_step_fails(self):
        code, err = judge(write(self.dir, ran=("s_a",)))
        self.assertEqual(code, launch_nx.EXIT_INVALID_RESULT)
        self.assertIn("s_b", err)

    def test_unfinished_status_fails(self):
        p = write(self.dir)
        data = json.loads(p.read_text(encoding="utf-8"))
        data["status"] = "running"
        p.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(judge(p)[0], launch_nx.EXIT_INVALID_RESULT)

    def test_old_unversioned_result_fails(self):
        p = Path(self.dir, "smoke.json")
        p.write_text(json.dumps({"checks": [{"name": "c", "ok": True}]}), encoding="utf-8")
        self.assertEqual(judge(p)[0], launch_nx.EXIT_INVALID_RESULT)

    def test_crash_exit_fails_even_with_a_good_result(self):
        self.assertEqual(judge(write(self.dir), child=7)[0], launch_nx.EXIT_CHILD_FAILED)

    def test_skipped_checks_are_counted_apart_and_fail_only_when_required(self):
        p = write(self.dir, rows=[{"name": "a", "ok": True, "status": "pass"},
                                  {"name": "b", "ok": True, "status": "skipped"}])
        self.assertEqual(judge(p)[0], 0)
        self.assertEqual(judge(p, require_all=True)[0], 1)

    def test_tutorial_failed_step_and_dropped_steps(self):
        rows = [{"tutorial": "A: x", "n": 1, "nx": "n", "replay": "r", "outcome": "FAILED", "detail": "boom"}]
        p = write(self.dir, harness="tutorial", rows=rows, planned=("a_new", "a_part"), ran=("a_new", "a_part"),
                  dropped=["a_part"])
        self.assertEqual(judge(p, harness="tutorial")[0], 1)

    def test_writer_leaves_no_temporary_file(self):
        write(self.dir)
        self.assertEqual(sorted(os.listdir(self.dir)), ["smoke.json"])


class ThroughMain(unittest.TestCase):
    """The same gate in launch_nx.main, with the FreeCAD run replaced by a stub (no GUI)."""

    def run_main(self, out, child_code, produce):
        install = launch_nx.Install(Path(sys.executable), (1, 1, 4))

        def fake_run(env):
            if produce:
                write(str(out), run=env["NXSTYLE_RUN_ID"])
            return child_code

        class FakeProc:                      # the non-Windows path waits on a Popen
            def __init__(self, cmd, env=None, **kw):
                self.env = env

            def wait(self, timeout=None):
                return fake_run(self.env)

            def kill(self):
                pass
        with tempfile.TemporaryDirectory() as prof, \
                mock.patch.object(launch_nx, "pick_install", return_value=install), \
                mock.patch.object(launch_nx, "run_on_hidden_desktop", side_effect=lambda cmd, env, **kw: fake_run(env)), \
                mock.patch.object(launch_nx.subprocess, "Popen", FakeProc), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return launch_nx.main(["--smoke-test", str(out), "--profile", prof, "--no-strata", "--no-katydid",
                                   "--no-sheetmetal", "--no-lcinterlocking"])

    def test_good_run_passes_and_a_stale_file_cannot_rescue_a_crash(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(self.run_main(out, 0, produce=True), 0)
            # that run's passing smoke.json is still in the folder; this run crashes without writing one
            self.assertEqual(self.run_main(out, 7, produce=False), launch_nx.EXIT_INVALID_RESULT)
            # and a run that writes a good result but then exits with an error is not accepted either
            self.assertEqual(self.run_main(out, 7, produce=True), launch_nx.EXIT_CHILD_FAILED)


if __name__ == "__main__":
    unittest.main()

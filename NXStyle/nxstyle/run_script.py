# SPDX-License-Identifier: LGPL-2.1-or-later
"""launch_nx.py --run SCRIPT: run a user's script once NX-Style is up, record how it ended, close FreeCAD.

The script runs as __main__ with sys.argv == [SCRIPT] and its folder first on sys.path, from FreeCAD's event loop
right after NX-Style's setup, so the main window, the ribbon and the bundled add-ons are there. It runs to its
end; to let the user interface catch up it pumps events itself (QApplication.processEvents()). sys.exit(n) sets
the exit code, an uncaught exception gives 1 and its traceback. What it prints is recorded too. Then every
document is closed without saving and FreeCAD closes; the launcher reads the result (harness_result's contract,
harness "run") and exits with the script's code. A script that ends FreeCAD itself (os._exit) leaves no result.
"""

import io
import os
import runpy
import sys
import time
import traceback

OUTPUT_LIMIT = 200_000            # characters of the script's output kept in the result (the end of it)


class _Tee(io.TextIOBase):
    """Writes to the stream FreeCAD gave (its report view) and keeps a copy."""

    encoding = "utf-8"

    def __init__(self, stream, copy):
        self.stream, self.copy = stream, copy

    def write(self, s):
        self.copy.write(s)
        try:
            return self.stream.write(s) if self.stream is not None else len(s)
        except Exception:          # FreeCAD's stream may refuse odd characters; the copy has them
            return len(s)

    def flush(self):
        try:
            if self.stream is not None:
                self.stream.flush()
        except Exception:
            pass


def exit_code(e: SystemExit) -> int:
    """sys.exit's argument as a process exit code: None 0, an int itself, anything else 1 (and printed)."""
    if e.code is None:
        return 0
    if isinstance(e.code, int):
        return e.code
    print(e.code, file=sys.stderr)
    return 1


def run_path(script: str) -> dict:
    """Run script as __main__; return {"exit_code", "traceback", "output", "seconds"}. No FreeCAD needed."""
    copy = io.StringIO()
    saved = sys.argv, sys.stdout, sys.stderr
    sys.argv = [script]
    sys.stdout, sys.stderr = _Tee(saved[1], copy), _Tee(saved[2], copy)
    folder = os.path.dirname(os.path.abspath(script))
    sys.path.insert(0, folder)
    t0 = time.monotonic()
    tb = ""
    try:
        runpy.run_path(script, run_name="__main__")
        code = 0
    except SystemExit as e:
        code = exit_code(e)
    except BaseException:
        tb = traceback.format_exc()
        code = 1
    finally:
        sys.argv, sys.stdout, sys.stderr = saved
        try:
            sys.path.remove(folder)
        except ValueError:
            pass
    output = copy.getvalue()
    if len(output) > OUTPUT_LIMIT:
        output = "[... %d characters cut ...]\n" % (len(output) - OUTPUT_LIMIT) + output[-OUTPUT_LIMIT:]
    return {"exit_code": code, "traceback": tb, "output": output, "seconds": round(time.monotonic() - t0, 2)}


def start(shell=None):
    from PySide import QtCore
    QtCore.QTimer.singleShot(0, run)


def run():
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtCore
    from . import harness_result
    script = os.environ["NXSTYLE_RUN_SCRIPT"]
    result = run_path(script)
    if result["traceback"]:
        App.Console.PrintError(result["traceback"])
    result["script"] = script
    harness_result.write(os.path.join(os.environ["NXSTYLE_RUN_OUT"], "run.json"), "run", result,
                         ["script"], ["script"])
    for name in list(App.listDocuments()):
        try:
            App.closeDocument(name)
        except Exception:
            pass
    QtCore.QTimer.singleShot(300, Gui.getMainWindow().close)

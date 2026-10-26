# SPDX-License-Identifier: LGPL-2.1-or-later
"""The result file of a self-test or tutorial run, as the launcher accepts it (no FreeCAD needed).

The launcher (launch_nx.py) accepts a run only from a result that says it is this run's and that the run
finished: the schema, the harness, the run ID the launcher passed in NXSTYLE_RUN_ID, status "complete",
and every planned step listed as run. A stale file from an earlier run, an empty or truncated one, or one
written by a run that stopped half way therefore fails, whatever it says inside.

The file is written atomically (a temporary file renamed over it), so a crash while writing leaves the
previous file, which the run ID then rejects, never a half-written one.

Check statuses: "pass", "fail", and "skipped" (the capability it needs is absent in this FreeCAD, e.g. no
pythonocc); skipped checks are counted apart, never as passes.
"""

import json
import os

SCHEMA = "nxstyle-harness/1"
STATUSES = ("pass", "fail", "skipped")


def run_id():
    return os.environ.get("NXSTYLE_RUN_ID", "")


def write(path, harness, payload, planned, ran):
    """Write payload (a dict with "checks" or "steps") with the contract fields; atomic."""
    data = dict(payload)
    data.update(schema=SCHEMA, harness=harness, run_id=run_id(), status="complete",
                planned=list(planned), ran=list(ran))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return data

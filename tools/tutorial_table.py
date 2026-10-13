#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Replace the results table in docs/TUTORIAL-REPLAY.md with the steps of a tutorial run.

    python tools/tutorial_table.py OUTDIR/tutorial.json [docs/TUTORIAL-REPLAY.md]

Prints the outcome counts per tutorial (for the summary line above the table).
"""

import collections
import json
import os
import sys


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    js = argv[0]
    md = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "docs", "TUTORIAL-REPLAY.md")
    with open(js, encoding="utf-8") as f:
        steps = json.load(f)["steps"]
    rows = []
    for r in steps:
        cells = [f"{r['tutorial'][:1]}{r['n']}", r["nx"], r["replay"], f"**{r['outcome']}**", r["detail"]]
        rows.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    with open(md, encoding="utf-8") as f:
        lines = f.read().split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("| # | NX step |"))
    end = head + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    tmp = md + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines[:head + 2] + rows + lines[end:]))
    os.replace(tmp, md)
    counts = collections.Counter((r["tutorial"][:1], r["outcome"]) for r in steps)
    print(f"replaced {end - head - 2} rows with {len(rows)}")
    for t in sorted({k[0] for k in counts}):
        print(t, {k[1]: v for k, v in counts.items() if k[0] == t})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

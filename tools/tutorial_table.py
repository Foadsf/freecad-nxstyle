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


def key_of(step):
    """The tutorial's letter(s), from its title 'AA: ...'."""
    return step["tutorial"].split(":", 1)[0].strip()


def row_id(line):
    """('AA', 12) of a table row '| AA12 | ...'."""
    cell = line.split("|")[1].strip()
    letters = "".join(ch for ch in cell if ch.isalpha())
    digits = "".join(ch for ch in cell if ch.isdigit())
    return letters, int(digits or 0)


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
        cells = [f"{key_of(r)}{r['n']}", r["nx"], r["replay"], f"**{r['outcome']}**", r["detail"]]
        # one table row per step: line breaks inside a cell would end the Markdown row
        rows.append("| " + " | ".join(" ".join(str(c).replace("|", "/").split()) for c in cells) + " |")
    with open(md, encoding="utf-8") as f:
        lines = f.read().split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("| # | NX step |"))
    end = head + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    # a run of some tutorials (--tutorials S,T) replaces those tutorials' rows only, as gen_docs --results does
    ran = {key_of(r) for r in steps}
    kept = [ln for ln in lines[head + 2:end] if row_id(ln)[0] not in ran]

    def order(ln):
        letters, n = row_id(ln)
        return len(letters), letters, n
    merged = sorted(kept + rows, key=order)
    tmp = md + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines[:head + 2] + merged + lines[end:]))
    os.replace(tmp, md)
    counts = collections.Counter((key_of(r), r["outcome"]) for r in steps)
    print(f"replaced {end - head - 2 - len(kept)} rows of {','.join(sorted(ran, key=lambda k: (len(k), k)))} with "
          f"{len(rows)}; kept {len(kept)}")
    for t in sorted({k[0] for k in counts}, key=lambda k: (len(k), k)):
        print(t, {k[1]: v for k, v in counts.items() if k[0] == t})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

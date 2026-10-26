# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection rules that need no FreeCAD: occurrence paths, the selection scope, collectors, curve chains
and the choice QuickPick and select-through make.

A pick is named the way FreeCAD's selection names it: a top-level object and a dotted sub-name, e.g.
``Asm`` + ``UnitB.Box.Face6``. The path ``("Asm", "UnitB", "Box")`` is the occurrence: two links to the
same part look alike in the graphics window but have different paths, which is what keeps a pick on
one of them from landing on its sibling.
"""

import math

SCOPES = [
    ("Entire Assembly", "assembly"),
    ("Within Work Part and Components", "work_part_and_components"),
    ("Within Work Part Only", "work_part_only"),
]
SCOPE_LABELS = {key: label for label, key in SCOPES}

RULES = [("Single Curve", "single"), ("Tangent Curves", "tangent"), ("Connected Curves", "connected")]
TANGENT_TOL_DEG = 0.5          # two curves meeting closer than this to a straight continuation are tangent

NOUNS = {"edge": "an edge", "face": "a face", "vertex": "a point", "curve": "a curve", "body": "a solid body",
         "sketch": "a sketch", "datum": "a datum", "feature": "a feature", "object": "a whole object"}


def plain(sub):
    """A sub-name without FreeCAD's mapped element names (topological naming):
    'Round.;Edge10;:M;FLT;:H12dc:7,E.Edge7' -> 'Round.Edge7'."""
    parts = (sub or "").split(".")
    if len(parts) > 1 and parts[-1].startswith(";"):
        return sub              # a mapped name with no plain one after it: leave it to FreeCAD
    return ".".join(p for p in parts if not p.startswith(";"))


def split(top, sub):
    """('Asm', 'UnitB.Box.Face6') -> (('Asm', 'UnitB', 'Box'), 'Face6'); a whole object has element ''."""
    parts = plain(sub).split(".")
    return (top,) + tuple(p for p in parts[:-1] if p), parts[-1]


def path_text(path, labels=None):
    labels = labels or {}
    return " › ".join(labels.get(n, n) for n in path)


def scope_verdict(path, components, work, mode, labels=None):
    """May a pick at occurrence ``path`` be selected under the selection scope?

    components: for each name in path, True when that object is a component occurrence (a part or a
    link to one); work: the work part's occurrence path, or None for the whole document.
    Returns (ok, reason)."""
    if mode == "assembly" or not work:
        return True, ""
    work = tuple(work)
    where = SCOPE_LABELS.get(mode, mode)
    if tuple(path[:len(work)]) != work:
        # the first name where the paths part is the occurrence the user actually hit
        i = next((k for k, (a, b) in enumerate(zip(path, work)) if a != b), min(len(path), len(work)))
        hit = path[:i + 1]
        return False, (f"{path_text(hit, labels)} is outside the work part {path_text(work, labels)} "
                       f"(Selection Scope: {where})")
    if mode == "work_part_only":
        inner = [n for n, c in zip(path[len(work):], components[len(work):]) if c]
        if inner:
            return False, (f"it belongs to the component {path_text(path[:path.index(inner[0]) + 1], labels)}, "
                           f"not to the work part itself (Selection Scope: {where})")
    return True, ""


class Pick:
    """One selectable thing as a collector sees it."""

    def __init__(self, doc, top, sub, kind, owner="", label=""):
        self.doc, self.top, self.sub, self.kind, self.owner = doc, top, plain(sub), kind, owner
        self.path, self.element = split(top, sub)
        self.label = label or (f"{self.element} of {path_text(self.path)}" if self.element else path_text(self.path))

    @property
    def key(self):
        return (self.doc, self.top, self.sub)

    def __repr__(self):
        return f"Pick({self.top}.{self.sub}, {self.kind})"


class Collector:
    """An NX selection collector: what a command input takes, how many, and why a pick was refused.

    accepts: the kinds it takes ('edge', 'face', ...); minimum/maximum: the count it needs (maximum None:
    no limit); one_owner: every pick must come from the same body (Edge Blend works on one body)."""

    REJECTED_KEPT = 20

    def __init__(self, label, accepts, minimum=1, maximum=None, one_owner=False, command=""):
        self.label, self.accepts, self.minimum, self.maximum = label, tuple(accepts), minimum, maximum
        self.one_owner, self.command = one_owner, command or label
        self.items = []
        self.rejected = []        # (pick label, reason), latest last

    def owner(self):
        return self.items[0].owner if self.items else None

    def verdict(self, pick):
        """(ok, reason) for adding pick; a pick already collected is ok (nothing to add)."""
        if pick.kind not in self.accepts:
            wants = " or ".join(NOUNS.get(k, k) for k in self.accepts)
            return False, f"{self.command} takes {wants}; {pick.label} is {NOUNS.get(pick.kind, pick.kind)}"
        if any(p.key == pick.key for p in self.items):
            return True, ""
        if self.one_owner and self.items and pick.owner != self.owner():
            return False, (f"{self.command} works on one body: {pick.label} is in {pick.owner or '?'}, "
                           f"the collected ones are in {self.owner()}")
        if self.maximum is not None and len(self.items) >= self.maximum:
            return False, f"{self.label} takes at most {self.maximum}"
        return True, ""

    def offer(self, pick):
        """Add pick if it is acceptable; otherwise record why not. Returns (ok, reason)."""
        ok, reason = self.verdict(pick)
        if ok:
            if not any(p.key == pick.key for p in self.items):
                self.items.append(pick)
        else:
            self.reject(pick.label, reason)
        return ok, reason

    def reject(self, label, reason):
        self.rejected.append((label, reason))
        del self.rejected[:-self.REJECTED_KEPT]

    def remove(self, key):
        self.items = [p for p in self.items if p.key != key]

    def clear(self):
        self.items = []

    @property
    def count(self):
        return len(self.items)

    @property
    def valid(self):
        return self.count >= self.minimum and (self.maximum is None or self.count <= self.maximum)

    def status(self):
        """'Select Edge (3)'; NX marks a required, still empty collector."""
        return f"{self.label} ({self.count})"

    def problem(self):
        """Why the collector is not complete, or ''."""
        if self.count < self.minimum:
            need = self.minimum - self.count
            noun = " or ".join(NOUNS.get(k, k).split(" ", 1)[1] for k in self.accepts)
            return f"select {need} more {noun}" if self.count else f"select at least {self.minimum} {noun}"
        if self.maximum is not None and self.count > self.maximum:
            return f"at most {self.maximum}"
        return ""


# ------------------------------------------------------------------ chains
def _angle(a, b):
    """Angle in degrees between two unit vectors."""
    d = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.degrees(math.acos(d))


def chain(edges, seed, rule, tol_deg=TANGENT_TOL_DEG):
    """The edges a curve rule adds from the seed edge.

    edges: {id: (v0, v1, out0, out1)}: the vertex keys at the two ends and, at each end, the unit
    tangent pointing from that vertex into the edge. Two edges meeting at a vertex continue each other
    smoothly when their out-tangents there are opposite.

    single:    the seed alone;
    tangent:   grow through vertices where exactly one other edge continues the chain tangentially
               (within tol_deg); stop where none or several do;
    connected: grow through vertices where exactly one other edge meets the chain (on a solid three
               edges meet at a corner, so the chain stops there).
    Returns the edge ids in order along the chain, the seed included."""
    if rule == "single" or seed not in edges:
        return [seed] if seed in edges else []
    at = {}
    for eid, (v0, v1, _, _) in edges.items():
        at.setdefault(v0, []).append(eid)
        if v1 != v0:
            at.setdefault(v1, []).append(eid)

    def end(eid, v):
        v0, _, o0, o1 = edges[eid]
        return o0 if v == v0 else o1

    def other(eid, v):
        v0, v1, _, _ = edges[eid]
        return v1 if v == v0 else v0

    taken = {seed}

    def walk(v, came):
        out = []
        while True:
            others = [e for e in at.get(v, []) if e != came]
            if rule == "tangent":
                back = tuple(-c for c in end(came, v))
                others = [e for e in others if _angle(back, end(e, v)) <= tol_deg]
            if len(others) != 1 or others[0] in taken:
                return out
            nxt = others[0]
            taken.add(nxt)
            out.append(nxt)
            if edges[nxt][0] == edges[nxt][1]:      # a closed edge: nothing beyond it
                return out
            v, came = other(nxt, v), nxt

    v0, v1, _, _ = edges[seed]
    if v0 == v1:
        return [seed]
    back = walk(v0, seed)
    forward = walk(v1, seed)
    return list(reversed(back)) + [seed] + forward


# ---------------------------------------------------- QuickPick, select-through
def dedupe(hits):
    """Ray hits in depth order -> one row per (document, top object, sub-name), nearest first."""
    seen, rows = set(), []
    for h in hits:
        key = (h["doc"], h["top"], h["sub"])
        if key not in seen:
            seen.add(key)
            rows.append(h)
    return rows


def select_through(rows):
    """With a gate in force: when the nearest row is refused, the nearest allowed one behind it
    (NX selects through what the filter excludes). rows: dicts with 'ok'. Returns a row or None."""
    if not rows or rows[0]["ok"]:
        return None
    return next((r for r in rows if r["ok"]), None)

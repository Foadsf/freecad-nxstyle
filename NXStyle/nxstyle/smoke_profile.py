# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of Profile's typed points (called from smoke.py; the fields are sketch_profile.py).

Profile (Z) in the sketch in edit, through the real keys: the first point's X and Y typed in the fields beside the
pointer, each next point's length and angle (fields matched to what they show, as the tutorials' replay does),
Enter after each, MB2 at the end. A closed outline with two slanted sides (a negative angle among them), the last
point typed onto the first: four lines, the end on the first point, every point within 1e-7 mm of the point typed,
fully constrained with no redundancy. Then tutorial AY's open section (three lines from (50, 0)): one chain, the
first point on the X axis. The same closed outline with NX-Style's fields off (FreeCAD 1.1.4's Polyline alone: no
fields, so the driver can only click) is the negative control and must fail."""

import math

import FreeCAD as App
import FreeCADGui as Gui

from .qt import Qt, QtCore, QtWidgets
from .smoke_typed import Drive, frame, qwait, rows

CLOSED = [(10.0, 10.0), (50.0, 10.0), (50.0, 30.0), (25.0, 40.0), (10.0, 10.0)]
OPEN = [(50.0, 0.0), (50.0, 30.0), (-50.0, 30.0), (-50.0, 0.0)]          # tutorial AY's three lines


def draw(d, pts):
    """Z, then each point typed (the first point's X and Y, then the length and the angle from the point before,
    as the fields offer them; clicked where no fields show), MB2. Returns the record."""
    from . import sketch_ui
    sk = d.sk
    rec = {"want": pts, "typed": [], "clicked": [], "fields": []}
    n0, k0 = len(sk.Geometry), len(sk.Constraints)
    d.key(Qt.Key_Z)
    prev = None
    for x, y in pts:
        if prev is None:
            near = d.at(x + 3, y + 4)
            d.move(near)
            fields = sketch_ui.xy_fields(sk, d.w, near)
            rec["fields"].append([sketch_ui.field_value(f) for f in d.fields()])
            pairs = list(zip(fields, (x, y))) if fields else []
        else:
            d.move(d.at(x, y))
            shown_w = d.fields()[:2]
            shown = [sketch_ui.field_value(f) for f in shown_w]
            rec["fields"].append(shown)
            want = (math.hypot(x - prev[0], y - prev[1]), math.degrees(math.atan2(y - prev[1], x - prev[0])))

            def err(order):
                da = abs(shown[order[1]] - want[1]) % 360
                return abs(shown[order[0]] - want[0]) + min(da, 360 - da)
            order = min(((0, 1), (1, 0)), key=err) if len(shown) == 2 else None
            pairs = [(shown_w[order[k]], want[k]) for k in range(2)] if order else []
        if pairs:
            rec["typed"].append([d.type_in(f, v) for f, v in pairs])
        else:
            p = d.at(x, y)
            d.smoke.send(d.f, QtCore.QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton)
            d.smoke.send(d.f, QtCore.QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
            QtWidgets.QApplication.processEvents()
            rec["clicked"].append((x, y))
        qwait(120)
        prev = (x, y)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    away = d.at(min(xs) - 15, max(ys) + 15)
    d.end_tool(away)
    d.move(away)
    rec["tool ended"] = not d.f.sketch_tool_active()
    App.ActiveDocument.recompute()
    rec["made"] = list(range(n0, len(sk.Geometry)))
    rec["constraints"] = rows(sk, k0)
    return rec


def vertex_error(sk, made, pts):
    """The largest distance of each wanted point from the nearest end of the curves made."""
    ends = [sk.getPoint(g, p) for g in made for p in (1, 2)]
    return max(min(math.hypot(e.x - x, e.y - y) for e in ends) for x, y in pts) if ends else float("inf")


def chained(sk, made):
    """Each line's end joined (Coincident) to the next line's start."""
    pairs = {frozenset(((c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))))
             for c in sk.Constraints if c.Type == "Coincident"}
    return [frozenset(((a, 2), (b, 1))) in pairs for a, b in zip(made, made[1:])]


def closed_case(smoke, label, enabled):
    from . import sketch_profile, sketch_ui
    sk = sketch_ui.edited_sketch()
    guard = sketch_profile.install()
    guard.enabled, guard.log = enabled, []
    d = Drive(smoke, sk)
    frame(d, sk, 30, 25, 90)
    rec = draw(d, CLOSED)
    made = rec["made"]
    sk.solve()
    bad = list(sk.RedundantConstraints) + list(sk.ConflictingConstraints)
    err = vertex_error(sk, made, CLOSED[:-1])
    links = chained(sk, made)
    closing = any(c.Type == "Coincident" and {(c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))}
                  == {(made[-1], 2), (made[0], 1)} for c in sk.Constraints) if made else False
    try:
        dof = int(sk.DoF)
    except Exception:
        dof = None
    ok = len(made) == 4 and err < 1e-7 and all(links) and closing and dof == 0 and not bad and rec["tool ended"]
    info = {"record": rec, "fields log": guard.log, "largest error mm": f"{err:.3e}", "chained": links,
            "closed": closing, "DoF": dof, "redundant or conflicting": bad}
    detail = (f"{len(made)} lines, typed {len(rec['typed'])} of {len(CLOSED)} points (clicked {len(rec['clicked'])}), "
              f"largest error {err:.2e} mm, chained {links}, closed on the first point {closing}, DoF {dof}, "
              f"redundant/conflicting {bad}, tool ended by MB2 {rec['tool ended']}")
    if enabled:
        # one Undo takes back the closing line with what holds it: the typed values add no undo step
        doc = sk.Document
        doc.undo()
        doc.recompute()
        sk.solve()
        after = (len(sk.Geometry) - (made[0] if made else 0), list(sk.RedundantConstraints)
                 + list(sk.ConflictingConstraints))
        info["after one Undo"] = {"lines": after[0], "redundant or conflicting": after[1], "constraints": rows(sk)}
        ok = ok and after == (3, [])
        detail += f"; one Undo leaves {after[0]} lines, redundant/conflicting {after[1]}"
    smoke.info[f"profile typed {label}"] = info
    sk.deleteAllGeometry()
    App.ActiveDocument.recompute()
    guard.enabled = True
    return ok, detail


def open_case(smoke):
    from . import sketch_profile, sketch_ui
    sk = sketch_ui.edited_sketch()
    guard = sketch_profile.install()
    guard.log = []
    d = Drive(smoke, sk)
    frame(d, sk, 0, 15, 180)
    rec = draw(d, OPEN)
    made = rec["made"]
    sk.solve()
    bad = list(sk.RedundantConstraints) + list(sk.ConflictingConstraints)
    err = vertex_error(sk, made, OPEN)
    links = chained(sk, made)
    on_axis = any(c.Type == "PointOnObject" and c.First == (made[0] if made else None) and c.Second == -1
                  for c in sk.Constraints)
    ok = len(made) == 3 and err < 1e-7 and all(links) and links and on_axis and not bad and rec["tool ended"]
    smoke.info["profile typed AY section"] = {"record": rec, "fields log": guard.log, "largest error mm": f"{err:.3e}",
                                              "chained": links, "first point on the X axis": on_axis,
                                              "redundant or conflicting": bad}
    detail = (f"{len(made)} lines, typed {len(rec['typed'])} of {len(OPEN)} points, largest error {err:.2e} mm, "
              f"chained {links}, first point held on the X axis {on_axis}, redundant/conflicting {bad}, tool ended "
              f"{rec['tool ended']}")
    sk.deleteAllGeometry()
    App.ActiveDocument.recompute()
    return ok, detail


def arc_case(smoke):
    """A line, M three times (a tangent arc, as FreeCAD's Polyline cycles after a line), the arc's radius and sweep,
    then the line FreeCAD holds tangent to the arc, its length only: a U from (10, -20) to (10, 0), exact and fully
    constrained."""
    from . import sketch_profile, sketch_ui
    sk = sketch_ui.edited_sketch()
    guard = sketch_profile.install()
    guard.log = []
    d = Drive(smoke, sk)
    frame(d, sk, 25, -10, 80)
    n0 = len(sk.Geometry)
    steps = []

    def typed(want):
        """Type each value into the field showing the nearest number, Enter after each; returns the kinds."""
        shown = {f.property(sketch_profile.FIELD): f for f in d.fields() if f.property(sketch_profile.FIELD)}
        steps.append({k: sketch_ui.field_value(f) for k, f in shown.items()})
        for kind, v in want:
            if kind not in shown:
                return False
            d.type_in(shown[kind], v)
        return True

    d.key(Qt.Key_Z)
    d.move(d.at(13, -16))
    ok = typed([("x", 10.0), ("y", -20.0)])
    d.move(d.at(40, -20))
    ok = typed([("length", 30.0), ("angle", 0.0)]) and ok
    for _ in range(3):
        d.key(Qt.Key_M)
    d.move(d.at(40, 0))
    modes = [guard.segment, guard.transition]
    ok = typed([("radius", 10.0), ("sweep", 180.0)]) and ok
    d.move(d.at(10, 0))
    after_arc = [guard.segment, guard.transition]
    ok = typed([("length", 30.0)]) and ok
    away = d.at(-5, 15)
    d.end_tool(away)
    d.move(away)
    ended = not d.f.sketch_tool_active()
    App.ActiveDocument.recompute()
    made = list(range(n0, len(sk.Geometry)))
    sk.solve()
    bad = list(sk.RedundantConstraints) + list(sk.ConflictingConstraints)
    kinds = [sk.Geometry[g].TypeId.split("::")[-1] for g in made]
    err = vertex_error(sk, made, [(10, -20), (40, -20), (40, 0), (10, 0)])
    try:
        dof = int(sk.DoF)
    except Exception:
        dof = None
    radius = sk.Geometry[made[1]].Radius if len(made) > 1 and "Arc" in kinds[1] else None
    good = ok and kinds == ["GeomLineSegment", "GeomArcOfCircle", "GeomLineSegment"] and err < 1e-7 \
        and dof == 0 and not bad and ended and radius is not None and abs(radius - 10) < 1e-9
    smoke.info["profile typed arc"] = {"fields shown": steps, "mode after M x3": modes, "mode after the arc": after_arc,
                                       "curves": kinds, "largest error mm": f"{err:.3e}", "DoF": dof,
                                       "redundant or conflicting": bad, "constraints": rows(sk, 0),
                                       "fields log": guard.log}
    sk.deleteAllGeometry()
    App.ActiveDocument.recompute()
    return good, (f"fields found {ok}; mode after M x3 {modes}, after the arc {after_arc}; curves {kinds}; radius "
                  f"{radius}; largest error {err:.2e} mm; DoF {dof}; redundant/conflicting {bad}; tool ended {ended}")


def run(smoke):
    from . import sketch_ui
    import traceback
    name = ("Profile (Z) takes typed points: X and Y, then each line's length and angle in fields beside the "
            "pointer; a closed outline with slanted sides lands exactly, fully constrained, the last point closing "
            "it; FreeCAD's Polyline alone shows no fields (control)")
    if sketch_ui.edited_sketch() is None:
        smoke.check(name, False, "no sketch in edit")
        return
    try:
        ok, detail = closed_case(smoke, "with NX-Style", True)
        bad, control = closed_case(smoke, "FreeCAD alone", False)
    except Exception:
        smoke.check(name, False, traceback.format_exc()[-900:])
        return
    smoke.check(name, ok and not bad, f"{detail} | control (NX-Style's fields off) passes: {bad}: {control}")
    try:
        ok, detail = open_case(smoke)
    except Exception:
        ok, detail = False, traceback.format_exc()[-900:]
    smoke.check("Profile typed: tutorial AY's open section, three lines from (50, 0) on the X axis, one chain, MB2 "
                "ends the tool", ok, detail)
    try:
        ok, detail = arc_case(smoke)
    except Exception:
        ok, detail = False, traceback.format_exc()[-900:]
    smoke.check("Profile typed after M: a tangent arc's radius and sweep, then the tangent line's length; exact, "
                "fully constrained", ok, detail)
    Gui.Selection.clearSelection()

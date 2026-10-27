# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints in FreeCAD terms, without FreeCAD: the Geometric Constraints gallery (NX: C), the
choices behind Collinear, and which constraints Hide, Show and Show All change. sketch_ui.py runs them.

FreeCAD's sketch selections name elements, not geometry: Edge3 is curve 2, H_Axis and V_Axis are -1 and -2,
ExternalEdge1 is -3. Curves 0 and up belong to the sketch and can move; the axes and external geometry
cannot. Constraint3 is constraint 2.

FreeCAD hides a sketch constraint by moving it to its "virtual space": the view shows the real space, and its
constraint list's check boxes treat the virtual space as hidden in the 3D view. NX's Hide (Ctrl+B) puts
dimensions there, Show (Ctrl+Shift+K) and Show All (Ctrl+Shift+U) bring them back.
"""

import math
import re

H_AXIS, V_AXIS = -1, -2

# NX 2212's Geometric Constraints gallery, in its order: (NX name, FreeCAD command candidates, what to pick).
# FreeCAD has no separate command for some of them; the command named does the same with that pick.
GALLERY = [
    ("Coincident", ["Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainCoincident"], "two points"),
    ("Point on Curve", ["Sketcher_ConstrainPointOnObject", "Sketcher_ConstrainCoincidentUnified"],
     "a point and a curve"),
    ("Tangent", ["Sketcher_ConstrainTangent"], "two curves"),
    ("Parallel", ["Sketcher_ConstrainParallel"], "two lines"),
    ("Perpendicular", ["Sketcher_ConstrainPerpendicular"], "two lines"),
    ("Horizontal", ["Sketcher_ConstrainHorizontal"], "a line"),
    ("Vertical", ["Sketcher_ConstrainVertical"], "a line"),
    ("Horizontal Alignment", ["Sketcher_ConstrainHorizontal"], "two points (FreeCAD's Horizontal)"),
    ("Vertical Alignment", ["Sketcher_ConstrainVertical"], "two points (FreeCAD's Vertical)"),
    ("Midpoint", ["Sketcher_ConstrainSymmetric"], "a line, then the point (FreeCAD's Symmetric)"),
    ("Collinear", ["NXStyle_SketchCollinear"], "two lines, then Collinear"),
    ("Concentric", ["Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainCoincident"],
     "two arcs or circles (FreeCAD's Coincident)"),
    ("Equal Length", ["Sketcher_ConstrainEqual"], "two lines"),
    ("Equal Radius", ["Sketcher_ConstrainEqual"], "two arcs or circles"),
    ("Fixed", ["Sketcher_ConstrainLock"], "a point"),
    ("Fully Fixed", ["Sketcher_ConstrainBlock"], "a curve"),
]


def geo_id(sub):
    """FreeCAD's sketch element name -> curve index (GeoId), or None for a point or anything else."""
    if sub == "H_Axis":
        return H_AXIS
    if sub == "V_Axis":
        return V_AXIS
    m = re.fullmatch(r"(External)?Edge(\d+)", sub or "")
    if not m:
        return None
    n = int(m.group(2))
    return -2 - n if m.group(1) else n - 1


def constraint_id(sub):
    """FreeCAD's sketch element name -> constraint index, or None for anything that is not a constraint."""
    m = re.fullmatch(r"Constraint(\d+)", sub or "")
    return int(m.group(1)) - 1 if m and int(m.group(1)) > 0 else None


def xy_fields(values, cursor):
    """Which two of FreeCAD's positional on-view fields are X and Y: the order of the fields is not fixed, so
    each is matched to the cursor's sketch coordinates it shows. values: the fields' numbers; cursor: (x, y).
    Returns (index of X, index of Y), or None with fewer than two fields."""
    if len(values) < 2:
        return None
    pairs = [(i, j) for i in range(len(values)) for j in range(len(values)) if i != j]
    return min(pairs, key=lambda p: abs(values[p[0]] - cursor[0]) + abs(values[p[1]] - cursor[1]))


def spline_step(prev, point):
    """What FreeCAD's B-spline tool (NX's Studio Spline) takes for a point after the first: its on-view fields
    there are the length and the angle (degrees, from the sketch's X axis) from the point before, not X and Y.
    Returns (length, angle) that put the next point exactly at point."""
    dx, dy = point[0] - prev[0], point[1] - prev[1]
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx))


def spline_step_fields(values, cursor, prev):
    """Which two of the B-spline tool's on-view fields are the length and the angle, with the pointer at cursor
    and the last point at prev (matched like xy_fields). Returns (index of length, index of angle) or None."""
    return xy_fields(values, spline_step(prev, cursor))


VISIBILITY = ("hide", "show", "show_all")


def visibility_change(kind, picked, hidden):
    """Which constraints move, and to which space, for Hide / Show / Show All in a sketch.

    picked: constraint indices selected (any order, repeats allowed); hidden: one bool per constraint of the
    sketch, True when it is in the virtual space. Returns (indices to change, sorted; True to hide them).
    Show All needs no pick; a constraint already where it should be is left alone."""
    if kind not in VISIBILITY:
        raise ValueError(f"unknown visibility change {kind!r}")
    to_hide = kind == "hide"
    ids = range(len(hidden)) if kind == "show_all" else sorted({i for i in picked if 0 <= i < len(hidden)})
    return [i for i in ids if hidden[i] != to_hide], to_hide


GEO_UNDEF = -2000          # FreeCAD's GeoId for "no curve" (a constraint's unused Third)
TRIM_MOVES = ("Tangent", "Perpendicular")


def trim_losses(before, after, trimmed, pieces, renumber):
    """Tangent and Perpendicular constraints FreeCAD's trim dropped instead of moving them to a piece.

    FreeCAD 1.1 moves such a constraint on the trimmed curve to the first piece it finds an intersection with
    (SketchObject::deriveConstraintsForPieces). A line held tangent where it ends, as Profile makes it (point on
    the circle plus Tangent) or as Tangent makes it (end on the curve, tangent there), touches the circle at its
    very end; OCC's extrema then find the contact or not by the sign of a rounding error, and the constraint
    is dropped. The caller puts each one back on the piece the other curve still touches.

    before, after: (Type, First, FirstPos, Second, SecondPos, Third) of every constraint; before in the
    numbering before the trim, after in the numbering after it. trimmed: the trimmed curve, numbered as before;
    pieces: what is left of it, numbered as after; renumber: the other curves' numbers, before -> after (a
    curve the trim deleted maps to None). Returns [(Type, other curve, its point or 0 for the edge)] as after."""
    left = [c for c in after if c[0] in TRIM_MOVES]
    lost = []
    for kind, a, apos, b, bpos, third in before:
        if kind not in TRIM_MOVES or third != GEO_UNDEF or (a == trimmed) == (b == trimmed):
            continue
        other, pos, tpos = (b, bpos, apos) if a == trimmed else (a, apos, bpos)
        if tpos:                   # an end of the trimmed curve: FreeCAD moves those with the end
            continue
        other = renumber.get(other, other) if other >= 0 else other
        if other is None:
            continue
        match = next((c for c in left if c[0] == kind and {c[1], c[3]} & {other}
                      and {c[1], c[3]} & set(pieces)), None)
        if match is not None:
            left.remove(match)     # a pair can hold twice (a line across an arc): count them
        else:
            lost.append((kind, other, pos))
    return lost


def moved_constraint(kind, other, pos, piece):
    """Sketcher.Constraint's arguments for a lost constraint put back on piece: the point first, as FreeCAD
    writes an end held on a curve."""
    return (kind, other, pos, piece) if pos else (kind, other, piece)


class NotCollinear(ValueError):
    """The picks cannot be made collinear; the message says why, for the cue line."""


def collinear_roles(picks):
    """[(GeoId, is_line)] for the two picks -> (moving, target): the first pick that belongs to the sketch
    moves onto the line through the other, as NX's 'object to constrain' and 'object to constrain to'."""
    if len(picks) != 2:
        raise NotCollinear(f"Collinear takes two lines; {len(picks)} picked")
    if not all(line for _, line in picks):
        raise NotCollinear("Collinear takes two lines; one of the picks is not a line")
    (a, _), (b, _) = picks
    if a == b:
        raise NotCollinear("Collinear takes two different lines")
    if a >= 0:
        return a, b
    if b >= 0:
        return b, a
    raise NotCollinear("Collinear needs one line of this sketch: the axes and projected curves cannot move")

# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints in FreeCAD terms, without FreeCAD: the Geometric Constraints gallery (NX: C), the
choices behind Collinear, which constraints Hide, Show and Show All change, and Profile's typed points.
sketch_ui.py and sketch_profile.py run them.

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


TYPED_DATUMS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")


def printf_f(v):
    """v as C's printf '%f' writes it: 6 decimals."""
    return float("%f" % v)


def exact_datum(value, typed):
    """The typed value a sketch constraint's datum stands for, or None to leave the datum alone.

    FreeCAD 1.1.4's sketch tools write the constraint of each value typed in an on-view field through C's '%f'
    (6 decimals), in the sketch's units: mm, and radians for angles typed in degrees. A typed 90 deg sweep is
    kept as 1.570796 rad, 3.3e-7 rad short of a quarter turn: on R63.5 the arc's end moves 2e-5 mm off the point
    typed. value: the datum as FreeCAD wrote it (mm or radians); typed: [(number as typed, is_angle)] in the
    fields' units (mm, degrees). Returns the typed number in the datum's units and sign, when value is its '%f'
    image and not already that number."""
    best = None
    for t, is_angle in typed:
        exact = abs(math.radians(t) if is_angle else t)
        if exact == abs(value):
            return None
        if abs(printf_f(exact) - abs(value)) < 1e-12 and (best is None or abs(exact - abs(value)) < best[0]):
            best = (abs(exact - abs(value)), exact)
    if best is None:
        return None
    return best[1] if value >= 0 else -best[1]


JOINING = ("Coincident", "Tangent", "Perpendicular")    # with a point on each side, they join the two points


def missing_joins(points, new, links, tol):
    """Points of the new curves that lie on a point of another curve without a constraint joining them.

    points: {(GeoId, PointPos): (x, y)}; new: the GeoIds a tool just made; links: [((g, p), (h, q))] the points
    already joined (Coincident, or Tangent / Perpendicular end to end), directly or through others; tol: mm.
    Returns [((g, p), (h, q))], the new point first, each joined to the nearest point within tol: one of older
    curves before one of the new ones. (FreeCAD 1.1.4's detectMissingPointOnPointConstraints cannot be used
    here: it starts its list of coincidences from all constraints, so a point held by a DistanceX or a point on
    the X axis falls out of its group, and a typed point is held so.)"""
    group = {k: k for k in points}

    def root(k):
        while group[k] != k:
            group[k] = group[group[k]]
            k = group[k]
        return k

    for a, b in links:
        if a in group and b in group:
            group[root(a)] = root(b)
    out = []
    for v in sorted(k for k in points if k[0] in new):
        x, y = points[v]
        near = [(k[0] in new, math.hypot(points[k][0] - x, points[k][1] - y), k) for k in points
                if k[0] != v[0] and root(k) != root(v)]
        near = [n for n in near if n[1] <= tol]
        if near:
            u = min(near)[2]
            out.append((v, u))
            group[root(v)] = root(u)
    return out


# ------------------------------------------------------------------ Profile's typed points (NX: Z)
# FreeCAD 1.1.4's Polyline (DrawSketchHandlerLineSet) has no on-view fields; sketch_profile.py adds NX's. Here: the
# tool's segment modes as the handler switches them, the fields each mode offers, the point the values typed put
# the next click at, and the constraints that hold those values (as FreeCAD's Line holds its typed values).

FREE, TANGENT, PERP_L, PERP_R = "free", "tangent", "perp_l", "perp_r"
LINE, ARC = "line", "arc"


def profile_mode_after(was_arc):
    """(segment, transition) the Polyline starts its next segment in: after an arc a line held tangent to it,
    after a line a free line (DrawSketchHandlerLineSet::releaseButton)."""
    return LINE, TANGENT if was_arc else FREE


def profile_mode_switch(segment, transition, prev_is_arc):
    """The mode M switches the Polyline to (DrawSketchHandlerLineSet::registerPressedKey). After a line: free
    line, perpendicular line, tangent line, tangent arc, two perpendicular arcs; after an arc: tangent line,
    perpendicular line, free line, then the arcs."""
    if segment == LINE:
        if transition == FREE:
            return (ARC, TANGENT) if prev_is_arc else (LINE, PERP_L)
        if transition == PERP_L:
            return (LINE, FREE) if prev_is_arc else (LINE, TANGENT)
        if transition == TANGENT:
            return (LINE, PERP_L) if prev_is_arc else (ARC, TANGENT)
        return LINE, FREE
    if transition == TANGENT:
        return ARC, PERP_L
    if transition == PERP_L:
        return ARC, PERP_R
    return LINE, TANGENT if prev_is_arc else FREE


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n > 1e-12 else (1.0, 0.0)


def end_direction(kind, start, end, center, pos):
    """The direction leaving a curve's end point pos (1 start, 2 end), as the Polyline takes it for the next
    segment: along a line; for an arc (FreeCAD keeps arcs counter-clockwise) tangent to it, onward."""
    if kind == LINE:
        d = (end[0] - start[0], end[1] - start[1])
        return _unit(d if pos == 2 else (-d[0], -d[1]))
    p = end if pos == 2 else start
    r = (p[0] - center[0], p[1] - center[1])
    return _unit((-r[1], r[0]) if pos == 2 else (r[1], -r[0]))


def transition_direction(transition, d):
    """The direction a segment leaves in: the previous curve's (tangent) or square to it, on the left or the
    right; None for a free one."""
    if transition == TANGENT:
        return d
    if transition == PERP_L:
        return -d[1], d[0]
    if transition == PERP_R:
        return d[1], -d[0]
    return None


def polar(start, p):
    """(length, angle in degrees from the X axis) from start to p."""
    return math.hypot(p[0] - start[0], p[1] - start[1]), math.degrees(math.atan2(p[1] - start[1], p[0] - start[0]))


def tangent_arc_through(start, tangent, p):
    """(radius, sweep in degrees, counter-clockwise positive) of the arc leaving start along tangent through p, as
    the Polyline draws it; the radius is None when p lies on the tangent."""
    d = (p[0] - start[0], p[1] - start[1])
    cross = tangent[0] * d[1] - tangent[1] * d[0]
    theta = math.atan2(abs(cross), tangent[0] * d[0] + tangent[1] * d[1])     # tangent to chord: half the sweep
    s = math.sin(theta)
    radius = math.hypot(*d) / (2 * s) if s > 1e-12 else None
    return radius, math.degrees(2 * theta) * (1 if cross >= 0 else -1)


def tangent_arc_end(start, tangent, radius, sweep):
    """The end point of the arc leaving start along tangent with this radius and sweep (degrees, positive
    counter-clockwise): the chord is 2 r sin(sweep / 2), turned half the sweep from the tangent."""
    half = math.radians(sweep) / 2
    c, s = math.cos(half), math.sin(half)
    chord = 2 * radius * abs(math.sin(half))
    d = (tangent[0] * c - tangent[1] * s, tangent[0] * s + tangent[1] * c)
    return start[0] + chord * d[0], start[1] + chord * d[1]


def profile_fields(stage, segment=LINE, transition=FREE, visibility=2):
    """The on-view fields Profile shows, as FreeCAD's Line does: visibility is FreeCAD's OnViewParameterVisibility
    (0 none, 1 dimensions only, 2 position and dimensions). stage 'first' (the first point: X and Y) or 'next'.
    A line held tangent or square to the curve before takes its length only: its angle is shown, not typed."""
    if visibility <= 0 or stage == "first" and visibility < 2:
        return ()
    if stage == "first":
        return "x", "y"
    if segment == ARC:
        return "radius", "sweep"
    return ("length", "angle") if transition == FREE else ("length", "direction")


def profile_point(fields, values, cursor, start=None, direction=None, either_way=False):
    """What the fields show with the pointer at cursor, and where the point goes: ({field: value}, (x, y)).

    values: {field: number} of the fields typed (locked); the others follow the pointer. fields: as
    profile_fields; start: the point the segment starts at; direction: transition_direction (tangent or square
    to the curve before; for an arc, the tangent at its start). A line square to the curve before goes to
    either side, the pointer's (either_way); a tangent line only onward. Lengths in mm, angles in degrees."""
    v = dict(values)
    if fields == ("x", "y"):
        x, y = v.get("x", cursor[0]), v.get("y", cursor[1])
        return {"x": x, "y": y}, (x, y)
    if fields == ("length", "angle"):
        length, angle = polar(start, cursor)
        length, angle = v.get("length", length), v.get("angle", angle)
        a = math.radians(angle)
        return {"length": length, "angle": angle}, (start[0] + length * math.cos(a), start[1] + length * math.sin(a))
    if fields == ("length", "direction"):
        d = direction
        along = (cursor[0] - start[0]) * d[0] + (cursor[1] - start[1]) * d[1]
        sign = -1.0 if either_way and along < 0 else 1.0
        length = v.get("length", abs(along))
        angle = math.degrees(math.atan2(sign * d[1], sign * d[0]))
        return {"length": length, "direction": angle}, (start[0] + sign * length * d[0],
                                                         start[1] + sign * length * d[1])
    if fields == ("radius", "sweep"):
        radius, sweep = tangent_arc_through(start, direction, cursor)
        radius, sweep = v.get("radius", radius), v.get("sweep", sweep)
        if radius is None:
            return {"radius": 0.0, "sweep": sweep}, tuple(cursor)
        return {"radius": radius, "sweep": sweep}, tangent_arc_end(start, direction, radius, sweep)
    return {}, tuple(cursor)


def _axis_angle(angle, quarter):
    """Is angle (degrees) a multiple of quarter (90: horizontal or vertical; 180: horizontal)?"""
    r = math.remainder(angle, quarter)
    return abs(r) < 1e-9


def profile_constraints(fields, values, geo, start_pos, end_pos):
    """Sketcher.Constraint arguments that hold the values typed for the segment geo (its points start_pos and
    end_pos), as FreeCAD 1.1.4's Line holds its typed values (SketcherGui ConstraintToAttachment,
    ConstraintLineByAngle), each with the number typed (FreeCAD writes them with six decimals):
    X and Y of the first point as distances from the axes (on an axis for 0, on the origin for both 0); a length
    as the line's Distance; an angle of 0 or 180 degrees as Horizontal, of 90 as Vertical, else the Angle from the
    X axis (radians); an arc's radius and sweep. A value of 0 for a length or a radius holds nothing."""
    v = dict(values)
    out = []
    if fields == ("x", "y"):
        if v.get("x") == 0 and v.get("y") == 0:
            return [("Coincident", geo, start_pos, -1, 1)]
        if "x" in v:
            out.append(("DistanceX", geo, start_pos, v["x"]) if v["x"] else ("PointOnObject", geo, start_pos, V_AXIS))
        if "y" in v:
            out.append(("DistanceY", geo, start_pos, v["y"]) if v["y"] else ("PointOnObject", geo, start_pos, H_AXIS))
        return out
    if fields in (("length", "angle"), ("length", "direction")) and v.get("length"):
        out.append(("Distance", geo, abs(v["length"])))
    if fields == ("length", "angle") and "angle" in v:
        a = v["angle"]
        if _axis_angle(a, 180):
            out.append(("Horizontal", geo))
        elif _axis_angle(a, 90):
            out.append(("Vertical", geo))
        else:
            out.append(("Angle", H_AXIS, geo, math.radians(math.remainder(a, 360))))
    if fields == ("radius", "sweep"):
        if v.get("radius"):
            out.append(("Radius", geo, abs(v["radius"])))
        if v.get("sweep"):
            out.append(("Angle", geo, math.radians(abs(v["sweep"]))))
    return out


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

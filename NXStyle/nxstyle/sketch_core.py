# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX sketch constraints in FreeCAD terms, without FreeCAD: the Geometric Constraints gallery (NX: C) and the
choices behind Collinear. sketch_ui.py runs them.

FreeCAD's sketch selections name elements, not geometry: Edge3 is curve 2, H_Axis and V_Axis are -1 and -2,
ExternalEdge1 is -3. Curves 0 and up belong to the sketch and can move; the axes and external geometry
cannot.
"""

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

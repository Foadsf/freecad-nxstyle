# SPDX-License-Identifier: LGPL-2.1-or-later
"""What NX's Move Object decides, without FreeCAD: the motion, the result and the copies.

NX moves the selected objects by a rigid motion (Transform: Distance, Angle, Point to Point, Dynamic), either
the objects themselves (Move Original) or copies of them (Copy Original, Number of Copies: copy i is moved i
times). Distance/Angle Divisions divides the motion: each step is the distance (angle) over the divisions.

A rigid motion here is (t, q): a translation (x, y, z) in mm and a unit quaternion (x, y, z, w); a point p
moves to q p + t. A FreeCAD Placement is the same pair, so a moved object's Placement is motion * Placement
(App.Placement(t, App.Rotation(*q)).multiply(P)). Coordinates are absolute (FreeCAD has no movable WCS, so XC,
YC, ZC are X, Y, Z).
"""

import math

from .primitive_core import VECTOR, VECTORS, CommandError, rotate  # noqa: F401  (VECTORS: the panel's list)

MOTIONS = ["Distance", "Angle", "Point to Point", "Dynamic"]
RESULTS = ["Move Original", "Copy Original"]

IDENTITY = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))

# NX's defaults for a millimetre part
DEFAULTS = {"motion": "Distance", "vector": "ZC", "distance": 10.0, "axis": "ZC", "angle": 90.0,
            "result": "Move Original", "copies": 1, "divisions": 1}

FREECAD_NAME = "Transform"           # FreeCAD's closest command (Std_TransformManip), for labels: freecad


# ------------------------------------------------------------------ quaternions
def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise CommandError("the vector has no length")
    return tuple(c / n for c in v)


def qmul(a, b):
    """The quaternion a b (b first, then a)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def axis_angle(axis, degrees):
    """The quaternion of a turn by degrees about axis (right hand)."""
    ax = _unit(axis)
    h = math.radians(degrees) / 2.0
    s = math.sin(h)
    return (ax[0] * s, ax[1] * s, ax[2] * s, math.cos(h))


# ------------------------------------------------------------------ motions
def add(a, b):
    return tuple(p + q for p, q in zip(a, b))


def sub(a, b):
    return tuple(p - q for p, q in zip(a, b))


def apply(m, p):
    """Where the motion m takes the point p."""
    t, q = m
    return add(rotate(q, p), t)


def compose(a, b):
    """The motion 'b, then a' (as FreeCAD's a.multiply(b))."""
    return add(rotate(a[1], b[0]), a[0]), qmul(a[1], b[1])


def inverse(m):
    t, q = m
    qi = qinv(q)
    return tuple(-c for c in rotate(qi, t)), qi


def power(m, k):
    """m applied k times (k >= 0)."""
    out = IDENTITY
    for _ in range(int(k)):
        out = compose(m, out)
    return out


def distance(vector, dist):
    """Distance: dist along the vector."""
    d = _unit(vector)
    return tuple(c * float(dist) for c in d), IDENTITY[1]


def angle(axis, point, degrees):
    """Angle: a turn by degrees about the axis vector through the point."""
    q = axis_angle(axis, degrees)
    return sub(point, rotate(q, point)), q


def point_to_point(start, end):
    """Point to Point: the translation that takes the From point to the To point."""
    return sub(end, start), IDENTITY[1]


def step(motion, values):
    """The motion of one step, divisions applied.

    values: {'vector', 'distance'} for Distance; {'axis', 'point', 'angle'} for Angle; {'from', 'to'} for Point to
    Point; 'divisions' (default 1) divides the distance, the angle or the Point to Point translation."""
    div = int(values.get("divisions", 1))
    if div < 1:
        raise CommandError("Distance/Angle Divisions must be at least 1")
    if motion == "Distance":
        return distance(values["vector"], float(values["distance"]) / div)
    if motion == "Angle":
        return angle(values["axis"], values["point"], float(values["angle"]) / div)
    if motion == "Point to Point":
        a, b = values["from"], values["to"]
        return point_to_point(a, add(a, tuple(c / div for c in sub(b, a))))
    raise CommandError(f"{motion} is not a typed motion (Dynamic uses FreeCAD's dragger)")


def motions(result, one, copies=1):
    """The motions to apply: Move Original moves the objects once; Copy Original makes copies copies, copy i moved
    i times."""
    if result == "Move Original":
        return [one]
    if result != "Copy Original":
        raise CommandError(f"unknown Result '{result}'")
    n = int(copies)
    if n < 1:
        raise CommandError("Number of Copies must be at least 1")
    return [power(one, i) for i in range(1, n + 1)]


def is_identity(m, tol=1e-9):
    t, q = m
    return all(abs(c) <= tol for c in t) and all(abs(c) <= tol for c in q[:3])


def issues(motion, values, result="Move Original", copies=1):
    """(error or None, [warnings]) for the dialog's values, as NX shows them before OK."""
    try:
        one = step(motion, values)
        motions(result, one, copies)
    except (CommandError, KeyError, TypeError, ValueError) as e:
        if isinstance(e, KeyError):
            return f"specify {e.args[0]}", []
        return str(e), []
    if is_identity(one):
        what = {"Distance": "Distance is 0", "Angle": "Angle is 0 (or a whole turn)",
                "Point to Point": "the From and To points are the same"}[motion]
        return None, [f"the objects do not move: {what}"]
    return None, []


# ------------------------------------------------------------------ placements
def moved(m, placement):
    """The Placement (t, q) of an object after the motion m."""
    return compose(m, placement)


def moved_offset(m, placement, offset):
    """The AttachmentOffset that moves an attached object by m: its Placement P is the support's frame S times the
    offset O, so the new offset is S^-1 m P = O P^-1 m P."""
    return compose(offset, compose(inverse(placement), compose(m, placement)))


# ------------------------------------------------------------------ objects
# what is moved and how it is copied; the panel classifies the FreeCAD objects
KINDS = {
    "body": "a PartDesign Body: its Placement moves; a copy is a new Body on a static copy of the solid",
    "part": "a Part object: its Placement moves; a copy is a static Part feature (Part's Simple Copy)",
    "link": "an assembly link or part container: its Placement moves; a copy is another link to the same object",
    "attached": "an attached sketch or datum: its Attachment Offset moves it, so it stays attached",
    "placed": "a sketch or datum that is not attached: its Placement moves",
}
COPYABLE = {"body", "part", "link"}


def copy_issue(kinds, result):
    """The reason Copy Original cannot copy these kinds, or None."""
    if result != "Copy Original":
        return None
    bad = sorted({k for k in kinds if k not in COPYABLE})
    if bad:
        return ("Copy Original copies bodies, Part objects and links; a sketch or datum is moved only "
                "(choose Move Original)")
    return None


# the NX options and what NX-Style does with each (the docs and the panel's tooltip)
OPTIONS = [
    ("Motion Distance: Specify Vector XC, YC, ZC, -XC, -YC, -ZC and Reverse Direction, Distance", "supported", ""),
    ("Motion Angle: axis vector, axis point, Angle", "supported", ""),
    ("Motion Point to Point: From and To points, typed or picked", "supported", ""),
    ("Motion Dynamic", "differs", "FreeCAD's Transform dragger in its own dialog"),
    ("Motion Distance between Points, Radial Distance, Align Axis to Vector, CSYS to CSYS, Delta XYZ, Rotate by "
     "Three Points", "not supported", "use Distance, Angle or Point to Point"),
    ("Result Move Original, Copy Original, Number of Copies, Distance/Angle Divisions", "supported", ""),
    ("Specify Vector from a picked face or edge", "not supported", "choose one of the six axes"),
    ("Associative (a Move Object feature)", "not supported", "copies are not associative, as NX's default"),
    ("Move Parents, Create Trace Lines, Layer Option", "not supported", ""),
]

# SPDX-License-Identifier: LGPL-2.1-or-later
"""What NX's primitive solids decide, without FreeCAD: Block, Cylinder, Cone and Sphere.

NX builds a primitive from its Type, a point (and an axis vector) and its dimensions, then combines it with a
target body by its Boolean. NX-Style builds it as a PartDesign primitive (AdditiveBox, SubtractiveCylinder, ...)
whose Placement holds the point and the axis, so the result stays a feature that Edit Parameters reopens:

- None: an additive primitive in a new Body (in the work Body while that Body has no solid yet);
- Unite: an additive primitive in the target Body;
- Subtract: a subtractive primitive in the target Body;
- Intersect: an additive primitive in a new tool Body, and a PartDesign Boolean (Common) in the target Body.

Points are (x, y, z) tuples in millimetres, in absolute coordinates (FreeCAD has no movable WCS, so XC, YC, ZC
are X, Y, Z).
"""

import math

# command -> (PartDesign primitive, NX types this command offers, NX types it does not)
PRIMITIVES = {
    "Block": ("Box", ["Origin and Edge Lengths", "Height and Two Points", "Two Diagonal Points"], []),
    "Cylinder": ("Cylinder", ["Axis, Diameter, and Height"], ["Arc and Height"]),
    "Cone": ("Cone", ["Diameters and Height"],
             ["Diameters and Half Angle", "Base Diameter, Height, and Half Angle",
              "Top Diameter, Height, and Half Angle", "Two Coaxial Arcs"]),
    "Sphere": ("Sphere", ["Center Point and Diameter"], ["Arc"]),
}

# the dimension fields of each command: (key, NX label); lengths in mm
DIMENSIONS = {
    "Block": [("length", "Length (XC)"), ("width", "Width (YC)"), ("height", "Height (ZC)")],
    "Cylinder": [("diameter", "Diameter"), ("height", "Height")],
    "Cone": [("baseDiameter", "Base Diameter"), ("topDiameter", "Top Diameter"), ("height", "Height")],
    "Sphere": [("diameter", "Diameter")],
}

# NX's defaults for a millimetre part
DEFAULTS = {
    "Block": {"length": 100.0, "width": 100.0, "height": 100.0},
    "Cylinder": {"diameter": 50.0, "height": 100.0},
    "Cone": {"baseDiameter": 50.0, "topDiameter": 0.0, "height": 25.0},
    "Sphere": {"diameter": 50.0},
}

# the Height and Two Points type needs only the height
TYPE_DIMENSIONS = {"Height and Two Points": ["height"], "Two Diagonal Points": []}

VECTORS = [("XC", (1.0, 0.0, 0.0)), ("YC", (0.0, 1.0, 0.0)), ("ZC", (0.0, 0.0, 1.0)),
           ("-XC", (-1.0, 0.0, 0.0)), ("-YC", (0.0, -1.0, 0.0)), ("-ZC", (0.0, 0.0, -1.0))]
VECTOR = dict(VECTORS)

# NX's Point dialog types offered here (NX has more: Cursor Location, Control Point, Intersection Point, ...)
POINT_TYPES = ["Inferred Point", "Existing Point", "End Point", "Arc/Ellipse/Sphere Center", "Point on Curve/Edge",
               "Point on Face", "Between Two Points"]

BOOLEANS = [("none", "None"), ("unite", "Unite"), ("subtract", "Subtract"), ("intersect", "Intersect")]
LABELS = dict(BOOLEANS)

# FreeCAD's names, for labels: freecad
FREECAD_NAMES = {"Block": "Additive Box", "Cylinder": "Additive Cylinder", "Cone": "Additive Cone",
                 "Sphere": "Additive Sphere"}


class CommandError(ValueError):
    pass


# ------------------------------------------------------------------ vectors
def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise CommandError("the vector has no length")
    return tuple(c / n for c in v)


def vector(key, reverse=False):
    d = VECTOR[key]
    return tuple(-c for c in d) if reverse else d


def vector_key(d):
    """The NX vector name of a direction ('ZC', '-YC'), or None for any other direction."""
    d = _unit(d)
    return next((k for k, v in VECTORS if sum(abs(a - b) for a, b in zip(v, d)) < 1e-9), None)


def rotation_to(d):
    """Quaternion (x, y, z, w) that turns +Z onto d: a PartDesign primitive's axis is its local Z."""
    dx, dy, dz = _unit(d)
    if dz < -1.0 + 1e-12:
        return (1.0, 0.0, 0.0, 0.0)                    # half a turn about X
    q = (-dy, dx, 0.0, 1.0 + dz)                      # axis Z x d, angle from 1 + Z.d
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def rotate(q, v):
    """v turned by the quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 q.xyz x v; v' = v + w t + q.xyz x t
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


# ------------------------------------------------------------------ points
def midpoint(a, b):
    return tuple((p + q) / 2.0 for p, q in zip(a, b))


def nearest(points, p):
    """The point of points closest to p."""
    return min(points, key=lambda q: sum((a - b) ** 2 for a, b in zip(q, p)))


def close(a, b, tol=1e-9):
    return all(abs(p - q) <= tol * max(1.0, abs(p), abs(q)) for p, q in zip(a, b))


# ------------------------------------------------------------------ shapes
def _positive(label, value):
    if value is None or not value > 1e-9:
        raise CommandError(f"{label} must be greater than 0")
    return float(value)


def block_box(kind, origin, dims=None, point2=None):
    """(corner, (length, width, height)) of a Block of the given NX type, axis-aligned in XC, YC, ZC.

    Origin and Edge Lengths: the origin is the corner, the block runs along +XC, +YC, +ZC.
    Two Diagonal Points: the origin and point2 are opposite corners, in any order.
    Height and Two Points: the origin and point2 are opposite corners of the base, in the XC-YC plane through
    the origin; the block rises the height along +ZC."""
    dims = dims or {}
    if kind == "Origin and Edge Lengths":
        return tuple(origin), (_positive("Length (XC)", dims.get("length")), _positive("Width (YC)", dims.get("width")),
                               _positive("Height (ZC)", dims.get("height")))
    if point2 is None:
        raise CommandError("specify the point from the origin corner")
    if kind == "Two Diagonal Points":
        size = tuple(abs(b - a) for a, b in zip(origin, point2))
        if min(size) <= 1e-9:
            raise CommandError("the two diagonal points must differ in XC, YC and ZC")
        return tuple(min(a, b) for a, b in zip(origin, point2)), size
    if kind == "Height and Two Points":
        size = (abs(point2[0] - origin[0]), abs(point2[1] - origin[1]))
        if min(size) <= 1e-9:
            raise CommandError("the two points must differ in XC and YC (they are opposite corners of the base)")
        return ((min(origin[0], point2[0]), min(origin[1], point2[1]), origin[2]),
                size + (_positive("Height (ZC)", dims.get("height")),))
    raise CommandError(f"unknown Block type '{kind}'")


def check_dimensions(command, dims):
    """The PartDesign parameters {property: value} for the dimensions, or CommandError with the reason."""
    if command == "Cylinder":
        return {"Radius": _positive("Diameter", dims.get("diameter")) / 2.0,
                "Height": _positive("Height", dims.get("height"))}
    if command == "Cone":
        base, top = dims.get("baseDiameter"), dims.get("topDiameter")
        if base is None or top is None or base < 0 or top < 0:
            raise CommandError("the diameters cannot be negative")
        if base <= 1e-9 and top <= 1e-9:
            raise CommandError("Base Diameter and Top Diameter cannot both be 0")
        return {"Radius1": base / 2.0, "Radius2": top / 2.0, "Height": _positive("Height", dims.get("height"))}
    if command == "Sphere":
        return {"Radius": _positive("Diameter", dims.get("diameter")) / 2.0}
    raise CommandError(f"unknown primitive '{command}'")


def dimensions_of(command, props):
    """The NX dimensions of an existing PartDesign primitive's properties (Edit Parameters)."""
    if command == "Block":
        return {"length": props["Length"], "width": props["Width"], "height": props["Height"]}
    if command == "Cylinder":
        return {"diameter": 2.0 * props["Radius"], "height": props["Height"]}
    if command == "Cone":
        return {"baseDiameter": 2.0 * props["Radius1"], "topDiameter": 2.0 * props["Radius2"],
                "height": props["Height"]}
    return {"diameter": 2.0 * props["Radius"]}


def command_of(type_id):
    """'PartDesign::SubtractiveCylinder' -> ('Cylinder', 'subtractive'); None for anything else."""
    for prefix in ("PartDesign::Additive", "PartDesign::Subtractive"):
        if type_id.startswith(prefix):
            name = type_id[len(prefix):]
            command = next((c for c, (prim, _, _) in PRIMITIVES.items() if prim == name), None)
            return (command, "additive" if "Additive" in prefix else "subtractive") if command else None
    return None


# ------------------------------------------------------------------ Boolean
def plan(mode, has_target, work_body_empty=False):
    """How a Boolean choice is built:
    {'body': 'work' | 'new' | 'target', 'feature': 'Additive' | 'Subtractive', 'common': bool}.
    Raises CommandError with the reason when it cannot be built."""
    if mode not in LABELS:
        raise CommandError(f"unknown Boolean '{mode}'")
    if mode == "none":
        return {"body": "work" if work_body_empty else "new", "feature": "Additive", "common": False}
    if not has_target:
        raise CommandError(f"{LABELS[mode]} needs a target body: select one (a body with a solid)")
    if mode == "intersect":
        return {"body": "new", "feature": "Additive", "common": True}
    return {"body": "target", "feature": "Additive" if mode == "unite" else "Subtractive", "common": False}


def result_issue(mode, base_volume, volume, base_solids, solids, command="primitive", rel=1e-9):
    """('error' | 'warning', text) for a result that is not what the Boolean promises, else None."""
    eps = rel * max(base_volume, volume, 1.0)
    what = command.lower()
    if mode == "unite":
        if solids > base_solids:
            return "error", (f"Unite would leave a separate solid: the {what} does not touch the target body "
                             "(choose None for a new body)")
        if volume <= base_volume + eps:
            return "warning", f"Unite adds nothing: the {what} lies inside the target body"
    elif mode == "subtract" and volume >= base_volume - eps:
        return "warning", f"Subtract removes nothing: the {what} does not reach the target body"
    elif mode == "intersect" and (solids == 0 or volume <= eps):
        return "error", f"Intersect leaves nothing: the {what} does not meet the target body"
    return None


# the NX options and what NX-Style does with each (the docs and the panel's tooltip)
OPTIONS = [
    ("Block: Origin and Edge Lengths, Height and Two Points, Two Diagonal Points", "supported", ""),
    ("Cylinder: Axis, Diameter, and Height", "supported", ""),
    ("Cylinder: Arc and Height", "not supported", "use Arc/Ellipse/Sphere Center for the point"),
    ("Cone: Diameters and Height", "supported", ""),
    ("Cone: the Half Angle types and Two Coaxial Arcs", "not supported", "type the diameters and the height"),
    ("Sphere: Center Point and Diameter", "supported", ""),
    ("Sphere: Arc", "not supported", "use Arc/Ellipse/Sphere Center for the centre"),
    ("Specify Vector: XC, YC, ZC, -XC, -YC, -ZC and Reverse Direction", "supported", ""),
    ("Specify Vector from a picked face or edge", "not supported", "choose one of the six axes"),
    ("Boolean None, Unite, Subtract, Intersect with a target body", "supported", ""),
    ("Point dialog as a separate window", "differs", "its type and XC, YC, ZC are part of the command's panel"),
    ("Associative points", "differs", "NX primitives are not associative either: the point is copied"),
]

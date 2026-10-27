# SPDX-License-Identifier: LGPL-2.1-or-later
"""The FreeCAD side of NX's Thread, without the GUI: reading a picked cylinder, and building or updating the two
thread features in a PartDesign Body (thread_core decides the numbers).

- Detailed: a sketch 'ThreadProfile' in a plane through the axis (hidden) and a PartDesign SubtractiveHelix that
  sweeps it about the sketch's V axis.
- Symbolic: a PartDesign::FeaturePython 'SymbolicThread' whose shape is its base feature's, unchanged.

Both carry the thread as NX_ properties (thread_core.record) plus where it sits (NX_Start, NX_Direction in the
Body's coordinates, NX_Surface the cylinder's radius, NX_Available its length), so Edit Parameters can reopen the
dialog and drawings or PMI can read the callout.
"""

import FreeCAD as App

from . import thread_core as core

GROUP = "NX Thread"

PROPS = [
    ("App::PropertyString", "NX_ThreadType", "Symbolic or Detailed"),
    ("App::PropertyString", "NX_Callout", "The thread's callout (M6 x 1, 1/4-20 UNC)"),
    ("App::PropertyString", "NX_Standard", "The table the values come from"),
    ("App::PropertyLength", "NX_MajorDiameter", "Major Diameter"),
    ("App::PropertyLength", "NX_MinorDiameter", "Minor Diameter"),
    ("App::PropertyLength", "NX_Pitch", "Pitch"),
    ("App::PropertyAngle", "NX_Angle", "Thread angle (included)"),
    ("App::PropertyLength", "NX_Length", "Thread length from the start face"),
    ("App::PropertyString", "NX_Rotation", "Right Hand or Left Hand"),
    ("App::PropertyBool", "NX_Internal", "True for a hole's thread"),
    ("App::PropertyVector", "NX_Start", "Where the thread starts on the axis (Body coordinates)"),
    ("App::PropertyVector", "NX_Direction", "The direction the thread runs from the start (Body coordinates)"),
    ("App::PropertyLength", "NX_Surface", "The threaded cylinder's radius"),
    ("App::PropertyLength", "NX_Available", "The threaded cylinder's length"),
]


# ------------------------------------------------------------------ the picked cylinder
def cylinder(face):
    """{'center', 'axis', 'radius', 'extent': (s0, s1), 'internal'} of a cylindrical face (global coordinates);
    CommandError for any other face. s runs along the axis from center."""
    surface = getattr(face, "Surface", None)
    if face.ShapeType != "Face" or type(surface).__name__ != "Cylinder":
        raise core.CommandError("Select Cylinder takes a cylindrical face")
    c, d = App.Vector(surface.Center), App.Vector(surface.Axis).normalize()
    pts = [p for e in face.Edges for p in e.discretize(12)]
    s = [(p - c).dot(d) for p in pts]
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    radial = p - c - d * (p - c).dot(d)
    return {"center": c, "axis": d, "radius": surface.Radius, "extent": (min(s), max(s)),
            "internal": n.dot(radial) < 0}


def placement_from(cyl, picked, reverse=False):
    """(start point, direction, available length) for a cylinder, the picked point and Reverse Thread
    Direction, in the cylinder's coordinates (global)."""
    s, sign, available = core.start_end(cyl["extent"], (picked - cyl["center"]).dot(cyl["axis"]), reverse)
    return cyl["center"] + cyl["axis"] * s, cyl["axis"] * sign, available


def start_from_face(cyl, face):
    """The extent end a planar start face lies on (as Select Start takes it), or CommandError."""
    surface = getattr(face, "Surface", None)
    if face.ShapeType != "Face" or type(surface).__name__ != "Plane":
        raise core.CommandError("Select Start takes a planar face at an end of the cylinder")
    n = App.Vector(surface.Axis).normalize()
    if abs(abs(n.dot(cyl["axis"])) - 1.0) > 1e-6:
        raise core.CommandError("the start face must be perpendicular to the cylinder's axis")
    s = (App.Vector(surface.Position) - cyl["center"]).dot(cyl["axis"])
    s0, s1 = cyl["extent"]
    tol = 1e-6 * max(1.0, abs(s1 - s0))
    if abs(s - s0) > tol and abs(s - s1) > tol:
        raise core.CommandError("the thread starts at an end of the cylinder: pick the face at one of its ends")
    return s


# ------------------------------------------------------------------ records
def is_thread(obj):
    return obj is not None and "NX_ThreadType" in getattr(obj, "PropertiesList", [])


def write_record(obj, values):
    for kind, name, doc in PROPS:
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, GROUP, doc)
    for name, v in values.items():
        if isinstance(v, (tuple, list)):
            v = App.Vector(*v)
        if getattr(obj, name) != v:
            setattr(obj, name, v)


def read_record(obj):
    out = {}
    for _, name, _ in PROPS:
        v = getattr(obj, name, None)
        out[name] = v.Value if hasattr(v, "Value") else v
    return out


# ------------------------------------------------------------------ Detailed
def _matrix(origin, x, y, z):
    return App.Matrix(x[0], y[0], z[0], origin[0], x[1], y[1], z[1], origin[1], x[2], y[2], z[2], origin[2],
                      0, 0, 0, 1)


def set_profile(sketch, points, centre):
    """Rewrite the sketch's geometry as the closed profile, its centre at centre along the sketch's y."""
    import Part
    import Sketcher
    sketch.deleteAllGeometry()
    n = len(points)
    for i in range(n):
        (r0, a0), (r1, a1) = points[i], points[(i + 1) % n]
        sketch.addGeometry(Part.LineSegment(App.Vector(r0, centre + a0, 0), App.Vector(r1, centre + a1, 0)), False)
    for i in range(n):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))


def apply_detailed(helix, sketch, p):
    """Set the sketch and the helix from p: {'start', 'direction', 'major', 'minor', 'pitch', 'angle', 'length',
    'rotation', 'internal', 'surface'} (start and direction in Body coordinates)."""
    points = core.profile(p["major"], p["minor"], p["pitch"], p["angle"], p["internal"], p["surface"])
    h = core.helix(p["length"], p["pitch"], points)
    origin, x, y, z = core.frame(tuple(p["start"]), tuple(p["direction"]))
    pl = App.Placement(_matrix(origin, x, y, z))
    if not sketch.Placement.isSame(pl, 1e-12):
        sketch.Placement = pl
    set_profile(sketch, points, h["start"])
    left = core.left_handed(p["rotation"])
    for name, v in (("Mode", "pitch-height-angle"), ("Pitch", p["pitch"]), ("Height", h["height"]),
                    ("Angle", 0.0), ("LeftHanded", left), ("Reversed", False)):
        cur = getattr(helix, name)
        if (cur.Value if hasattr(cur, "Value") else cur) != v:
            setattr(helix, name, v)


def make_detailed(body, p):
    """A new Detailed thread in body: (sketch, helix)."""
    sketch = body.newObject("Sketcher::SketchObject", "ThreadProfile")
    sketch.MapMode = "Deactivated"
    helix = body.newObject("PartDesign::SubtractiveHelix", "Thread")
    helix.Profile = sketch
    helix.ReferenceAxis = (sketch, ["V_Axis"])
    apply_detailed(helix, sketch, p)
    if getattr(sketch, "ViewObject", None) is not None:
        sketch.ViewObject.Visibility = False
    return sketch, helix


# ------------------------------------------------------------------ Symbolic
class SymbolicThread:
    """Proxy of a symbolic thread (PartDesign::FeaturePython): the base feature's solid, unchanged; the thread is
    in its NX_ properties."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        base = getattr(obj, "BaseFeature", None)
        obj.Shape = base.Shape.copy() if base is not None and not base.Shape.isNull() else obj.Shape

    def onChanged(self, obj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_symbolic(body):
    obj = body.newObject("PartDesign::FeaturePython", "SymbolicThread")
    SymbolicThread(obj)
    return obj


# ------------------------------------------------------------------ the result
def helix_points(helix, samples=120):
    """Points along the longest edge of the helix's sweep (a helical edge), for its handedness."""
    shape = getattr(helix, "AddSubShape", None)
    edges = sorted(shape.Edges, key=lambda e: e.Length, reverse=True) if shape is not None else []
    if not edges:
        return []
    e = edges[0]
    a, b = e.FirstParameter, e.LastParameter
    return [tuple(e.valueAt(a + k * (b - a) / samples)) for k in range(samples + 1)]


def volume(obj):
    try:
        return sum(s.Volume for s in obj.Shape.Solids)
    except Exception:
        return 0.0


def thread_parameters(values, place, surface, internal):
    """The apply_detailed parameters from the panel's values and the placement (Body coordinates)."""
    start, direction = place
    return {"start": tuple(start), "direction": tuple(direction), "major": values["major"],
            "minor": values["minor"], "pitch": values["pitch"], "angle": values["angle"],
            "length": values["length"], "rotation": values["rotation"], "internal": internal,
            "surface": surface}

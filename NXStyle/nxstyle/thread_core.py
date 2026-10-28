# SPDX-License-Identifier: LGPL-2.1-or-later
"""What NX's Thread command decides, without FreeCAD: the standard thread for a picked diameter, the thread
profile, and the helix that sweeps it.

NX's Thread (Insert > Design Feature > Thread) puts a thread on a cylindrical face:

- Detailed: a real helical thread. NX-Style builds it as a PartDesign SubtractiveHelix of a thread profile (a
  sketch in a plane through the axis), so the part stays history-based and Edit Parameters reopens the dialog.
- Symbolic: a cosmetic thread. The cylinder keeps its shape; the thread is recorded on a feature in the Body
  (its callout, diameters, pitch, length, hand), for drawings and PMI.

Once a face is picked, NX fills in the nearest standard thread. The tables below are data, with their sources:
ISO 261 (general purpose metric screw threads, coarse pitches; first and second choice diameters, as in the
ISO 262 selection) and ASME B1.1 (Unified inch screw threads, UNC series). The basic minor diameter is the basic
profile's (ISO 68-1, ISO 724 D1; ASME B1.1): D1 = D - 1.082532 P, with the fundamental triangle H = 0.866025 P.

Lengths in millimetres, angles in degrees. The profile is given in (radial, axial) coordinates: radial is the
distance from the thread's axis, axial the offset from the profile's centre along the axis.
"""

import math
from collections import namedtuple

INCH = 25.4
H_FACTOR = math.sqrt(3.0) / 2.0              # fundamental triangle height H = 0.866025 P (60 degree threads)
MINOR_FACTOR = 5.0 * math.sqrt(3.0) / 8.0     # D - D1 = 2 x 5/8 H = 1.082532 P

THREAD_TYPES = ["Symbolic", "Detailed"]
ROTATIONS = ["Right Hand", "Left Hand"]

# ISO 261 coarse pitch series, first and second choice nominal diameters: (designation, major mm, pitch mm)
METRIC_COARSE = [
    ("M1", 1.0, 0.25), ("M1.1", 1.1, 0.25), ("M1.2", 1.2, 0.25), ("M1.4", 1.4, 0.3), ("M1.6", 1.6, 0.35),
    ("M1.8", 1.8, 0.35), ("M2", 2.0, 0.4), ("M2.2", 2.2, 0.45), ("M2.5", 2.5, 0.45), ("M3", 3.0, 0.5),
    ("M3.5", 3.5, 0.6), ("M4", 4.0, 0.7), ("M4.5", 4.5, 0.75), ("M5", 5.0, 0.8), ("M6", 6.0, 1.0),
    ("M7", 7.0, 1.0), ("M8", 8.0, 1.25), ("M10", 10.0, 1.5), ("M12", 12.0, 1.75), ("M14", 14.0, 2.0),
    ("M16", 16.0, 2.0), ("M18", 18.0, 2.5), ("M20", 20.0, 2.5), ("M22", 22.0, 2.5), ("M24", 24.0, 3.0),
    ("M27", 27.0, 3.0), ("M30", 30.0, 3.5), ("M33", 33.0, 3.5), ("M36", 36.0, 4.0), ("M39", 39.0, 4.0),
    ("M42", 42.0, 4.5), ("M45", 45.0, 4.5), ("M48", 48.0, 5.0), ("M52", 52.0, 5.0), ("M56", 56.0, 5.5),
    ("M60", 60.0, 5.5), ("M64", 64.0, 6.0),
]

# ASME B1.1 Unified National Coarse (UNC): (size, major inch, threads per inch)
UNIFIED_COARSE = [
    ("#1", 0.073, 64), ("#2", 0.086, 56), ("#3", 0.099, 48), ("#4", 0.112, 40), ("#5", 0.125, 40),
    ("#6", 0.138, 32), ("#8", 0.164, 32), ("#10", 0.190, 24), ("#12", 0.216, 24), ("1/4", 0.25, 20),
    ("5/16", 0.3125, 18), ("3/8", 0.375, 16), ("7/16", 0.4375, 14), ("1/2", 0.5, 13), ("9/16", 0.5625, 12),
    ("5/8", 0.625, 11), ("3/4", 0.75, 10), ("7/8", 0.875, 9), ("1", 1.0, 8), ("1-1/8", 1.125, 7),
    ("1-1/4", 1.25, 7), ("1-3/8", 1.375, 6), ("1-1/2", 1.5, 6), ("1-3/4", 1.75, 5), ("2", 2.0, 4.5),
]

Thread = namedtuple("Thread", "callout standard major minor pitch angle")

# NX names Rotation and Thread Type; FreeCAD's name, for labels: freecad
FREECAD_NAME = "Subtractive Helix (thread)"


class CommandError(ValueError):
    pass


# ------------------------------------------------------------------ tables
def basic_minor(major, pitch):
    """The basic minor diameter D1 = D - 1.082532 P (ISO 68-1, ISO 724; ASME B1.1)."""
    return major - MINOR_FACTOR * pitch


def _tpi(t):
    return f"{t:g}"


def table():
    """Every standard thread, in mm: metric coarse first, then UNC."""
    rows = [Thread(f"{d} x {p:g}", "ISO 261 coarse", major, basic_minor(major, p), p, 60.0)
            for d, major, p in METRIC_COARSE]
    rows += [Thread(f"{s}-{_tpi(tpi)} UNC", "ASME B1.1 UNC", major * INCH, basic_minor(major * INCH, INCH / tpi),
                    INCH / tpi, 60.0) for s, major, tpi in UNIFIED_COARSE]
    return rows


def find(callout):
    """The table's thread with this callout ('M6 x 1', '1/4-20 UNC'), or None."""
    return next((t for t in table() if t.callout == callout), None)


INCH_MATCH = 0.005        # mm: a diameter this close to an inch size was typed as that size


def nearest(diameter, internal=False):
    """The standard thread for a picked cylinder of this diameter, as NX fills it in. A shaft (external) is
    matched by its major diameter, a hole (internal) by its minor diameter (a hole is drilled at about the minor
    diameter). NX-Style parts are metric with inch sizes typed in mm, so a diameter that is an inch size (within
    INCH_MATCH) takes the UNC thread, as NX's inch table does for an inch part; any other takes the nearest ISO
    coarse thread. On a tie the smaller thread wins."""
    if diameter is None or not diameter > 0:
        raise CommandError("the cylinder's diameter must be greater than 0")
    key = (lambda t: t.minor) if internal else (lambda t: t.major)
    rows = table()
    inch = [t for t in rows if t.standard.startswith("ASME") and abs(key(t) - diameter) <= INCH_MATCH]
    if inch:
        return min(inch, key=lambda t: abs(key(t) - diameter))
    metric = [t for t in rows if t.standard.startswith("ISO")]
    return min(metric, key=lambda t: (round(abs(key(t) - diameter), 9), t.major))


# ------------------------------------------------------------------ checks
def check(major, minor, pitch, angle, length):
    """CommandError with the reason when the values cannot make a thread."""
    for label, v in (("Major Diameter", major), ("Minor Diameter", minor), ("Pitch", pitch), ("Length", length)):
        if v is None or not v > 1e-9:
            raise CommandError(f"{label} must be greater than 0")
    if not minor < major - 1e-9:
        raise CommandError("Minor Diameter must be smaller than Major Diameter")
    if angle is None or not 1.0 <= angle <= 120.0:
        raise CommandError("Angle must be between 1 and 120 degrees")


# ------------------------------------------------------------------ profile
def profile(major, minor, pitch, angle, internal=False, surface=None):
    """The closed thread profile that the helix sweeps: the material it takes away, as (radial, axial) points
    around the profile's centre, in order.

    The basic profile (ISO 68-1, ASME B1.1) pivots at the major diameter: an external thread keeps a crest flat of
    P/8 there, so the groove is 7P/8 wide at the major diameter and narrows along the flanks (half the Angle each
    side of the radial direction) to the minor diameter (P/4 for the basic 60 degree profile). An internal thread
    has its root flat of P/8 at the major diameter and widens to the minor diameter (3P/4 basic).

    The profile runs past the cylinder's surface (surface: its radius) by a quarter pitch, with the width it has
    at the surface diameter, so the crest flats stay where the profile puts them."""
    check(major, minor, pitch, angle, 1.0)
    r_maj, r_min = major / 2.0, minor / 2.0
    depth = r_maj - r_min
    slope = math.tan(math.radians(angle / 2.0))
    margin = 0.25 * pitch
    if not internal:
        crest = 7.0 * pitch / 16.0                       # half the groove at the major diameter
        root = crest - depth * slope                     # half the groove at the minor diameter
        if root <= 1e-6 * pitch:
            raise CommandError(f"the flanks meet before the Minor Diameter: with Pitch {pitch:g} and Angle "
                               f"{angle:g} the thread is at most {2 * crest / slope:.4g} deep; make the Minor "
                               "Diameter larger")
        outer = max(r_maj, surface if surface else r_maj) + margin
        return [(r_min, -root), (r_min, root), (r_maj, crest), (outer, crest), (outer, -crest), (r_maj, -crest)]
    root = pitch / 16.0                                  # half the groove at the major diameter
    crest = root + depth * slope                         # half the groove at the minor diameter
    if crest >= 0.5 * pitch - 1e-6 * pitch:
        raise CommandError(f"the grooves of neighbouring turns would meet: with Pitch {pitch:g} and Angle "
                           f"{angle:g} the thread is at most {2 * (0.5 * pitch - root) / slope:.4g} deep; make the "
                           "Minor Diameter larger")
    inner = min(r_min, surface if surface else r_min) - margin
    if inner <= 0:
        inner = 0.5 * min(r_min, surface if surface else r_min)
    return [(inner, -crest), (r_min, -crest), (r_maj, -root), (r_maj, root), (r_min, crest), (inner, crest)]


def half_span(points):
    """Half the profile's extent along the axis."""
    return max(abs(a) for _, a in points)


# ------------------------------------------------------------------ helix
def helix(length, pitch, points):
    """How the profile is swept: it starts one pitch before the start face (outside the material, so the thread
    runs out through the start face) and its far flank ends at Length from the start face. Returns
    {'start': axial position of the profile's centre from the start face, 'height': helix height, 'turns'}."""
    if length is None or not length > 1e-9:
        raise CommandError("Length must be greater than 0")
    height = length + pitch - half_span(points)
    if height <= pitch:
        raise CommandError(f"Length must be more than {half_span(points):.4g} (half the thread's width)")
    return {"start": -pitch, "height": height, "turns": height / pitch}


def left_handed(rotation):
    if rotation not in ROTATIONS:
        raise CommandError(f"unknown Rotation '{rotation}'")
    return rotation == "Left Hand"


def handedness(points, axis_point, axis_dir):
    """'Right Hand' or 'Left Hand' of a helical curve sampled as points (x, y, z), from the sense of rotation
    about the axis as it advances: a right-hand helix turns counter-clockwise as it moves along the axis (seen
    from where it goes), whichever way it is followed. None when the points do not wind about the axis."""
    d = _unit(axis_dir)
    u = _unit(_perpendicular(d))
    v = _cross(d, u)
    turn = advance = 0.0
    prev = None
    for p in points:
        q = tuple(a - b for a, b in zip(p, axis_point))
        ang = math.atan2(_dot(q, v), _dot(q, u))
        s = _dot(q, d)
        if prev is not None:
            turn += (ang - prev[0] + math.pi) % (2 * math.pi) - math.pi
            advance += s - prev[1]
        prev = (ang, s)
    if abs(turn) < 1e-6 or abs(advance) < 1e-9:
        return None
    return "Right Hand" if turn * advance > 0 else "Left Hand"


# ------------------------------------------------------------------ the cylinder
def start_end(extent, picked, reverse=False):
    """Where the thread starts on a cylinder spanning extent = (s0, s1) along its axis: at the end nearest the
    picked position, or the other end with Reverse Thread Direction. Returns (start, sign, available length);
    sign +1 runs the thread towards larger s."""
    s0, s1 = sorted(extent)
    if s1 - s0 <= 1e-9:
        raise CommandError("the cylinder has no length")
    near_first = abs(picked - s0) <= abs(picked - s1)
    if reverse:
        near_first = not near_first
    return (s0, 1, s1 - s0) if near_first else (s1, -1, s1 - s0)


def check_length(length, available):
    if length > available + 1e-6:
        raise CommandError(f"Length {length:g} runs past the end of the cylinder ({available:g} available)")


def surface_issue(major, minor, diameter, internal):
    """A warning when the thread does not sit on the cylinder as the table thread would, else None."""
    tol = 1e-6 * max(1.0, diameter)
    if not internal:
        if major < diameter - tol:
            return (f"the cylinder (diameter {diameter:g}) is larger than the Major Diameter {major:g}: the "
                    "thread's crests stay on the cylinder")
        if major > diameter + tol:
            return f"the Major Diameter {major:g} is larger than the cylinder ({diameter:g}): the crests are cut flat"
        return None
    if minor > diameter + tol:
        return f"the hole (diameter {diameter:g}) is smaller than the Minor Diameter {minor:g}: its wall stays"
    if major <= diameter + tol:
        return f"the hole (diameter {diameter:g}) is not smaller than the Major Diameter {major:g}: no thread"
    return None


# ------------------------------------------------------------------ an independent reference volume
def _clip(points, radius, keep_inside):
    """The polygon clipped to radial <= radius (keep_inside) or >= radius (Sutherland-Hodgman)."""
    def inside(p):
        return p[0] <= radius if keep_inside else p[0] >= radius
    out = []
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        if inside(p):
            out.append(p)
        if inside(p) != inside(q):
            t = (radius - p[0]) / (q[0] - p[0])
            out.append((radius, p[1] + t * (q[1] - p[1])))
    return out


def _moment(points):
    """The first moment of the polygon about the axis, the integral of the radial coordinate over its area."""
    m = 0.0
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        m += (x0 + x1) * (x0 * y1 - x1 * y0)
    return abs(m) / 6.0


def removed_volume(points, length, pitch, surface, internal=False):
    """The volume the thread takes from the cylinder, without a solid model. A helical sweep shears the profile
    along the axis, which keeps volume: one turn removes 2 pi times the profile's first moment about the axis.
    The swept profile is clipped to the material (radial <= surface, or >= for a hole) and the profile's centre
    travels Length - half span within the material (helix() starts it one pitch outside), so
    V = 2 pi (Length - half span) / Pitch x moment. Assumes the start face is an end of the cylinder."""
    inside = _clip(points, surface, keep_inside=not internal)
    if len(inside) < 3:
        return 0.0
    return 2.0 * math.pi * (length - half_span(points)) / pitch * _moment(inside)


# ------------------------------------------------------------------ recorded parameters
def record(kind, thread, length, rotation, internal):
    """The thread as NX-Style records it on the feature (both types), {property: value}."""
    return {"NX_ThreadType": kind, "NX_Callout": thread.callout, "NX_Standard": thread.standard,
            "NX_MajorDiameter": float(thread.major), "NX_MinorDiameter": float(thread.minor),
            "NX_Pitch": float(thread.pitch), "NX_Angle": float(thread.angle), "NX_Length": float(length),
            "NX_Rotation": rotation, "NX_Internal": bool(internal)}


def callout_for(major, minor, pitch, angle):
    """The table's callout when the values are a table thread's, else a generic one ('M6.35 x 1.27 (custom)')."""
    for t in table():
        if all(abs(a - b) < 1e-6 for a, b in ((t.major, major), (t.minor, minor), (t.pitch, pitch),
                                              (t.angle, angle))):
            return t.callout, t.standard
    return f"{major:g} x {pitch:g}, {angle:g} deg", "custom"


# ------------------------------------------------------------------ vectors
def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v):
    n = math.sqrt(_dot(v, v))
    if n < 1e-12:
        raise CommandError("the axis has no length")
    return tuple(c / n for c in v)


def _perpendicular(d):
    """A unit vector perpendicular to d."""
    helper = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _unit(_cross(d, helper))


def frame(start, direction):
    """(origin, x, y, z) of the profile sketch: its y axis runs along the thread from the start point, x is
    radial; z = x cross y is the sketch normal."""
    y = _unit(direction)
    x = _perpendicular(y)
    return tuple(start), x, y, _cross(x, y)


# the NX options and what NX-Style does with each (the docs and the panel's tooltip)
OPTIONS = [
    ("Thread Type Detailed: a real helical thread", "supported", "a PartDesign SubtractiveHelix of the profile"),
    ("Thread Type Symbolic: the thread recorded, the cylinder kept", "supported",
     "a feature in the Body carries the callout; no dashed display"),
    ("Select Cylinder: an external (shaft) or internal (hole) cylindrical face", "supported", ""),
    ("Major/Minor Diameter, Pitch, Angle, Length from the nearest table thread", "supported",
     "ISO 261 coarse and UNC tables"),
    ("Rotation: Right Hand, Left Hand", "supported", ""),
    ("Start: an end face of the cylinder, Reverse Thread Direction", "supported", ""),
    ("Start on a face or plane part-way along the cylinder", "not supported", "the thread starts at an end"),
    ("Symbolic: Method, Form, Number of Starts, Tapered, Full Thread", "not supported",
     "single-start, straight, the length typed"),
    ("Fine pitch and UNF tables", "not supported", "type the values; the callout reads custom"),
]

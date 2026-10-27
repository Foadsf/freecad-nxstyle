# SPDX-License-Identifier: LGPL-2.1-or-later
"""What the command controller decides, without FreeCAD: typed lengths, the Boolean options of Extrude and
Revolve, Revolve's axis and limits, and sections of picked curves.

NX's Extrude has one Boolean list: None (a new body), Unite, Subtract, Intersect. PartDesign has no Boolean
property: a Pad adds to its Body, a Pocket removes from it, and a separate solid is a separate Body. The
controller maps the NX choice onto those features (Revolution and Groove for Revolve) and states every choice
it cannot map instead of approximating it.

A section is the curves NX's Section collector holds. FreeCAD's Profile names them as sub-elements of one sketch
('Edge3'); outside sketch edit those names follow the sketch shape's edge order, not the geometry index.
"""

import re

# ------------------------------------------------------------------ lengths
LENGTH_UNITS = {
    "mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0, "um": 1e-3, "µm": 1e-3, "μm": 1e-3, "nm": 1e-6,
    "in": 25.4, "inch": 25.4, '"': 25.4, "ft": 304.8, "'": 304.8, "thou": 0.0254, "mil": 0.0254,
}
_NUMBER = re.compile(r"^\s*([+-]?)\s*([0-9]*[.,]?[0-9]*)\s*([A-Za-zµμ\"']*)\s*$")


class UnitError(ValueError):
    pass


def parse_length(text, decimal=".", default_unit="mm"):
    """Typed length text -> millimetres. decimal is the field's decimal separator ('.' or ','); the other
    one is refused, not guessed: in a ',' locale Qt reads '3.175' as 3175."""
    t = (text or "").replace("−", "-").strip()
    if not t:
        raise UnitError("no value")
    if t.startswith("=") or any(op in t for op in "*/()"):
        raise UnitError(f"'{text}' is an expression; only plain lengths are read here")
    other = "," if decimal == "." else "."
    m = _NUMBER.match(t)
    if not m or not m.group(2) or m.group(2) in ".,":
        raise UnitError(f"'{text}' is not a length")
    sign, num, unit = m.groups()
    if other in num:
        raise UnitError(f"'{text}': the decimal separator here is '{decimal}'")
    unit = unit or default_unit
    key = unit if unit in LENGTH_UNITS else unit.lower()
    if key not in LENGTH_UNITS:
        raise UnitError(f"'{unit}' is not a length unit")
    value = float(num.replace(decimal, ".")) * LENGTH_UNITS[key]
    return -value if sign == "-" else value


def read_back_issue(text, read_mm, decimal=".", tol=1e-6):
    """The message for a field that took typed text as another length than the text says, else None.

    The case it exists for: '3.175' typed where ',' is the decimal separator, which the field reads as
    3175 mm. Text this module cannot read (an expression, an angle) gives None: nothing to compare."""
    try:
        meant = parse_length(text, decimal)
    except UnitError:
        other = "," if decimal == "." else "."
        try:
            meant = parse_length(text, other)
        except UnitError:
            return None
        if abs(meant - read_mm) <= tol * max(1.0, abs(meant)):
            return None
        return (f"'{text}' was read as {read_mm:g} mm: the decimal separator here is '{decimal}' "
                f"(type {text.replace(other, decimal)} for {meant:g} mm)")
    if abs(meant - read_mm) <= tol * max(1.0, abs(meant)):
        return None
    return f"'{text}' means {meant:g} mm, but the field read {read_mm:g} mm"


# ------------------------------------------------------------------ Extrude
BOOLEANS = [("new_body", "None"), ("unite", "Unite"), ("subtract", "Subtract"), ("intersect", "Intersect")]
LABELS = dict(BOOLEANS)

UNSUPPORTED = {
    "intersect": "Intersect is not offered: PartDesign has no intersecting extrude, and NX-Style does not "
                 "approximate it.",
}
SECTION_ONE_SKETCH = "FreeCAD's Profile is one object: the section takes the curves of one sketch"

# NX Extrude options and what this Extrude does with each (shown in the command panel and in the docs)
EXTRUDE_OPTIONS = [
    ("Boolean None (a new body)", "supported", "a Pad that starts a Body: in the sketch's Body while it has no "
                                             "solid, otherwise in a new Body through a sub-shape binder"),
    ("Boolean Unite", "supported", "a Pad in the sketch's Body"),
    ("Boolean Subtract", "supported", "a Pocket in the sketch's Body"),
    ("Boolean Intersect", "not supported", UNSUPPORTED["intersect"]),
    ("Boolean target body", "sketch's Body only", "NX lets you pick the target body; here it is the Body that "
                                                 "holds the sketch"),
    ("Section of picked curves (Single, Tangent, Connected Curves)", "supported",
     "the picked curves of one sketch become the Profile; Inferred Curves takes the whole sketch"),
    ("Section from several sketches, or from edges of a solid", "not supported", SECTION_ONE_SKETCH),
    ("Limits Value, Symmetric Value, Until Next, Until Selected, Through All", "supported",
     "the FreeCAD panel's Type list (Dimension, Symmetric, To first, Up to face, Through all)"),
    ("Limits Start 0, End d, Reverse Direction", "supported", "Dimension d with Reversed ticked (NX: -ZC 0.5 in)"),
    ("Limits Start -a, End b", "supported", "Two dimensions: Length b, 2nd length a"),
    ("Start limit other than 0 on one side", "not supported", "FreeCAD extrudes from the sketch plane; Two "
                                                            "sided gives a length each way"),
    ("Until Extended", "not supported", "no FreeCAD equivalent"),
    ("Draft from start limit", "supported", "the Pad's Taper angle"),
    ("Draft from section, asymmetric or matched ends", "not supported", "FreeCAD has one taper angle"),
    ("Offset (single, two-sided, symmetric)", "not supported", "FreeCAD's Offset is the up-to-face offset, "
                                                               "not NX's section offset"),
    ("Body type Sheet", "not supported", "a Pad makes solids"),
    ("Change the Boolean when editing", "not supported", "it would replace the feature and break what refers "
                                                         "to it; delete and extrude again"),
]

DIRECTION_NOTE = ("Subtract cuts into the part (against the sketch normal) and Unite or None build along "
                  "it, unless Reversed is ticked; NX keeps one direction for every Boolean.")
SHORT_NOTE = ("Subtract cuts into the part unless Reversed. Not offered: Intersect, target body, start limit, "
              "Until Extended, section draft, Offset, Sheet.")


def unsupported_summary():
    return "; ".join(name for name, status, _ in EXTRUDE_OPTIONS if status == "not supported")


def options_tooltip(options=None, note=DIRECTION_NOTE):
    """Every NX option with what this command does with it (the command box's tooltip); Extrude's by default."""
    rows = [f"{name}: {status} ({how})" for name, status, how in (options or EXTRUDE_OPTIONS)]
    return "\n".join(([note, ""] if note else []) + rows)


def infer_boolean(requested, has_body, has_solid):
    """NX's inferred Boolean: Unite onto the part, None (a new body) when there is nothing to unite with."""
    if requested:
        return requested
    return "unite" if has_body and has_solid else "new_body"


def plan_feature(mode, has_body, has_solid, body_label="the Body", add="PartDesign::Pad", cut="PartDesign::Pocket"):
    """How a Boolean choice is built: {'feature': type id, 'body': 'sketch' or 'new'}, with add the feature that
    adds material (Pad, Revolution) and cut the one that removes it (Pocket, Groove). Raises CommandError with
    the reason when it cannot be built."""
    if mode not in LABELS:
        raise CommandError(f"unknown Boolean '{mode}'")
    if mode in UNSUPPORTED:
        raise CommandError(UNSUPPORTED[mode])
    if mode == "new_body":
        if has_body and not has_solid:
            return {"feature": add, "body": "sketch"}
        return {"feature": add, "body": "new"}
    if not has_body:
        raise CommandError(f"{LABELS[mode]} needs a target body: the sketch is not in a Body")
    if not has_solid:
        raise CommandError(f"{LABELS[mode]} needs a solid in {body_label}, which has none yet: choose None for a new body")
    return {"feature": add if mode == "unite" else cut, "body": "sketch"}


def plan_extrude(mode, has_body, has_solid, body_label="the Body"):
    return plan_feature(mode, has_body, has_solid, body_label)


def plan_revolve(mode, has_body, has_solid, body_label="the Body"):
    return plan_feature(mode, has_body, has_solid, body_label, "PartDesign::Revolution", "PartDesign::Groove")


def mode_of(type_id, has_base):
    """The NX Boolean an existing Pad, Pocket, Revolution or Groove stands for."""
    if type_id in ("PartDesign::Pocket", "PartDesign::Groove"):
        return "subtract"
    return "unite" if has_base else "new_body"


def result_warning(mode, base_volume, volume, rel=1e-9, noun="extrusion"):
    """A Unite that adds nothing or a Subtract that removes nothing (the extrusion misses the part)."""
    eps = rel * max(base_volume, volume, 1.0)
    if mode == "unite" and volume <= base_volume + eps:
        return f"Unite adds nothing: the {noun} lies inside the part"
    if mode == "subtract" and volume >= base_volume - eps:
        return f"Subtract removes nothing: the {noun} does not reach the part (Reversed?)"
    return None


# ------------------------------------------------------------------ Revolve
REVOLVE_OPTIONS = [
    ("Boolean None, Unite, Subtract", "supported", "a Revolution (None, Unite) or a Groove (Subtract), as Extrude"),
    ("Boolean Intersect", "not supported", UNSUPPORTED["intersect"]),
    ("Section of picked curves (Single, Tangent, Connected Curves)", "supported",
     "the picked curves of one sketch become the Profile; Inferred Curves takes the whole sketch"),
    ("Section from several sketches, or from edges of a solid", "not supported", SECTION_ONE_SKETCH),
    ("Axis Specify Vector XC, YC, ZC and reversed, Specify Point", "supported",
     "through the origin: the Body's own axis (reversed: Reversed); elsewhere: a datum line the Revolve keeps"),
    ("Axis a sketch axis or a sketch line", "supported", "the sketch's H or V axis, or the picked line"),
    ("Limits Start and End angle", "supported",
     "from the sketch plane: Angle; on both sides of it: Two angles (FreeCAD's 2nd angle is minus the Start)"),
    ("Start and End angle on the same side of the sketch plane, neither 0", "not supported",
     "FreeCAD revolves from the sketch plane"),
    ("Limits Until Selected", "supported", "the FreeCAD panel's Type list (Up to face)"),
    ("Offset, Draft, Body type Sheet", "not supported", "no FreeCAD equivalent in a Revolution"),
    ("Change the Boolean when editing", "not supported", "it would replace the feature and break what refers "
                                                         "to it; delete and revolve again"),
]
REVOLVE_NOTE = ("Not offered: Intersect, Start and End on one side of the sketch plane, Offset, Draft, Sheet. "
                "An axis off the origin is kept as a datum line.")

# Specify Vector: (key, label, the Body axis, reversed)
VECTORS = [("XC", "XC", "X", False), ("YC", "YC", "Y", False), ("ZC", "ZC", "Z", False),
           ("-XC", "−XC", "X", True), ("-YC", "−YC", "Y", True), ("-ZC", "−ZC", "Z", True)]
AXIS_DIRS = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
SKETCH_AXES = [("sketch_h", "Sketch H axis", "H_Axis"), ("sketch_v", "Sketch V axis", "V_Axis")]


def revolve_axis(vector, point=(0.0, 0.0, 0.0), tol=1e-9):
    """The reference an NX axis (Specify Vector, Specify Point) is built on:
    {'kind': 'origin', 'axis': 'X', 'reversed': bool} through the origin, {'kind': 'sketch', 'sub': 'H_Axis'}
    for a sketch axis, {'kind': 'sketch', 'sub': 'Edge3'} for a sketch line ('line:Edge3'), or
    {'kind': 'datum', 'point': p, 'direction': d, 'reversed': False} for a vector through another point."""
    if vector.startswith("line:"):
        return {"kind": "sketch", "sub": vector[5:], "reversed": False}
    for key, _label, sub in SKETCH_AXES:
        if vector == key:
            return {"kind": "sketch", "sub": sub, "reversed": False}
    for key, _label, axis, rev in VECTORS:
        if vector == key:
            if all(abs(c) <= tol for c in point):
                return {"kind": "origin", "axis": axis, "reversed": rev}
            d = tuple(-c if rev else c for c in AXIS_DIRS[axis])
            return {"kind": "datum", "point": tuple(point), "direction": d, "reversed": False}
    raise CommandError(f"unknown vector '{vector}'")


def vector_of(kind, sub, reversed_):
    """The Specify Vector entry an existing ReferenceAxis stands for: kind 'origin' (sub 'X_Axis'), 'sketch'
    (sub 'H_Axis', 'Edge3') or 'other'; None when there is no entry for it (a datum line, an edge of a solid)."""
    if kind == "origin":
        axis = sub[:1].upper()
        return next((k for k, _l, a, r in VECTORS if a == axis and r == bool(reversed_)), None)
    if kind == "sketch":
        hit = next((k for k, _l, s in SKETCH_AXES if s == sub), None)
        return hit or (f"line:{sub}" if sub.startswith("Edge") else None)
    return None


def revolve_limits(start, end, tol=1e-9):
    """NX Start and End angle (degrees) -> the Revolution's {'Type', 'Angle', 'Angle2', 'flip'}. FreeCAD revolves
    from the sketch plane: Angle one way, the 2nd angle the other; flip says the sweep runs the other way round
    the axis (the Revolution's Reversed, combined with a reversed vector). Raises CommandError otherwise."""
    lo, hi = min(start, end), max(start, end)
    if hi - lo <= tol:
        raise CommandError("the Start and End angles are equal: nothing to revolve")
    if hi - lo > 360 + tol:
        raise CommandError(f"End minus Start is {hi - lo:g}°: at most 360°")
    if abs(lo) <= tol:
        return {"Type": "Angle", "Angle": hi, "Angle2": 0.0, "flip": False}
    if abs(hi) <= tol:
        return {"Type": "Angle", "Angle": -lo, "Angle2": 0.0, "flip": True}
    if lo < 0 < hi:
        return {"Type": "TwoAngles", "Angle": hi, "Angle2": -lo, "flip": False}
    raise CommandError(f"Start {start:g}° and End {end:g}° are on the same side of the sketch plane: FreeCAD "
                       "revolves from the sketch plane, so one of them must be 0 or on the other side")


def limits_of(type_, angle, angle2, flip=False, midplane=False):
    """The (Start, End) an existing Revolution shows, or None for a type set in FreeCAD's panel (Up to face)."""
    if midplane and type_ == "Angle":
        return (-angle / 2.0, angle / 2.0)
    if type_ == "Angle":
        return (0.0, -angle) if flip else (0.0, angle)
    if type_ == "TwoAngles":
        return (-angle, angle2) if flip else (-angle2, angle)
    return None


# ------------------------------------------------------------------ sections
def section_from_picks(picks):
    """Picks of a section -> (sketch, edges): edges None for the whole sketch. picks: (sketch, element) with
    element '' for a whole sketch or 'EdgeN' for one of its curves; the first sketch is the section's, picks of
    other sketches come back as refused. Returns (sketch, edges, refused)."""
    sketch, edges, whole, refused = None, [], False, []
    for sk, element in picks:
        if sketch is None:
            sketch = sk
        if sk != sketch:
            refused.append((sk, element))
            continue
        if not element:
            whole = True
        elif element.startswith("Edge") and element not in edges:
            edges.append(element)
        elif not element.startswith("Edge"):
            refused.append((sk, element))
    if sketch is None:
        return None, None, refused
    return sketch, (None if whole or not edges else sort_edges(edges)), refused


def sort_edges(edges):
    """'Edge10' after 'Edge9'."""
    def n(e):
        try:
            return int(e[4:])
        except ValueError:
            return 0
    return sorted(set(edges), key=n)


def add_to_section(section, picked):
    """The section after picking curves (its whole sketch: None; no section yet: []). Picking curves of a whole
    sketch section starts a section of just those curves."""
    if section is None:
        return sort_edges(picked)
    return sort_edges(list(section) + list(picked))


def remove_from_section(section, removed):
    if section is None:
        return None
    return [e for e in section if e not in set(removed)]


def section_gaps(records, edges):
    """Where the curves of a section do not form closed loops: (open ends, branch points), as vertex keys. records:
    {edge: (v0, v1, ...)} as for selection_core.chain. A loop needs exactly two curves at each of its points; a
    closed curve (a circle) has v0 == v1 and closes itself."""
    degree = {}
    for e in edges:
        if e not in records:
            continue
        v0, v1 = records[e][0], records[e][1]
        if v0 == v1:
            continue
        degree[v0] = degree.get(v0, 0) + 1
        degree[v1] = degree.get(v1, 0) + 1
    return sorted(v for v, n in degree.items() if n == 1), sorted(v for v, n in degree.items() if n > 2)


def section_problem(records, edges):
    """The reason a section of curves cannot be a profile, or ''."""
    if edges is not None and not edges:
        return "the section is empty: select curves"
    if edges is None:
        return ""
    missing = [e for e in edges if e not in records]
    if missing:
        return f"{', '.join(missing)} not found in the sketch"
    ends, branches = section_gaps(records, edges)
    if ends:
        return f"the section is open at {len(ends)} point{'s' if len(ends) != 1 else ''}: select the curves that close it"
    if branches:
        return (f"the section branches at {len(branches)} point{'s' if len(branches) != 1 else ''} (three or more "
                "curves meet): Single Curve picks one of them")
    return ""


def match_edges(geometry, edges, tol=1e-6):
    """Which shape edge (outside sketch edit, 'EdgeN' follows the sketch shape's order, not the geometry's) each
    geometry is. geometry: {index: (start, end, mid)}; edges: {'EdgeN': (start, end, mid)}; an edge may run either
    way. Returns {index: 'EdgeN'}; a geometry without a matching edge (construction, a point) is left out."""
    def near(a, b):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    out, used = {}, set()
    for i, (s, e, m) in geometry.items():
        for name, (s2, e2, m2) in edges.items():
            if name in used or not near(m, m2):
                continue
            if (near(s, s2) and near(e, e2)) or (near(s, e2) and near(e, s2)):
                out[i] = name
                used.add(name)
                break
    return out


def undo_steps_added(before, after):
    """How many undo steps were added, from the undo names (newest first) before and after. FreeCAD's undo list
    has a size limit: a full one drops its oldest step for each new one, so its count stays the same. The
    smallest number of new steps that explains the two lists; None when none does (an undo, a cleared list)."""
    before, after = list(before), list(after)
    if len(after) < len(before):
        return None
    # at least one old step must still be there to line the lists up, unless there was none
    for k in range(len(after) - len(before), len(after) + (0 if before else 1)):
        if after[k:] == before[:len(after) - k]:
            return k
    return None


class CommandError(ValueError):
    pass

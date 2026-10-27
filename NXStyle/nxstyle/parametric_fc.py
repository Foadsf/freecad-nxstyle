# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parametric STEP in FreeCAD: a part's design intent out to ISO 10303-55/108/111 and back in.

Export (export()): the part's explicit B-rep is written by OpenCASCADE as STEP AP242 (Part 42 geometry,
the product structure other CAD systems read), and the construction history, sketches, constraints and
parameters are appended to the same file (parametric.merge): the dual model of ISO 10303-55. A
system that knows only B-reps opens the solid; one that reads Parts 55, 108 and 111 can rebuild and edit.

What is read from FreeCAD:
  Spreadsheet aliases         parameters (mm, deg or plain numbers)
  expressions                 on feature properties and sketch constraints, when they use only those
                              aliases, numbers with units, + - * / ^ and FreeCAD's functions
  Sketcher sketches           lines, circles, arcs, points (construction too) and their constraints
  PartDesign history          Pad, Pocket (Length, Two sides, Symmetric, Through all, taper, Up to face,
                              Up to first, Up to last, with an Offset), Revolution, Groove (also Up to
                              face), Hole (simple flat or drill point, counterbore, countersink, through
                              all), Fillet, Chamfer, Thickness, LinearPattern, PolarPattern, Mirrored and
                              MultiTransform of one or more features, Pipe (Standard mode along a tangent
                              continuous sketch path, profile normal to it), the additive and subtractive
                              primitives
  hybrid steps                Draft, Loft, other Pipes, other Holes (threaded, tapered, counterdrill), a
                              pattern of holes or fillets, and any other feature with a solid: written with
                              their explicit solid (Part 55 5.2.2), so the history goes on past them
  attachments                 a sketch attached FlatFace to an origin plane, a datum plane or a planar face
  Part workbench              Box, Cylinder, Cone, Sphere, Torus, Cut, Fuse, Common

The report lists each hybrid step and anything else that was not written. The B-rep carries the whole shape.

Import (import_file()) rebuilds a PartDesign Body (or Part CSG objects), a 'Parameters' spreadsheet with
the expressions on it, and the sketches with their constraints. A sketch attached to an origin plane, or to
a face found again on the rebuilt features by its geometry, is re-attached (FlatFace, with the attachment
offset that keeps it in place); other sketches come in placed. Picked edges and faces of fillets, chamfers,
shells, drafts and up-to extents are found again by their geometry (Part 55's user-selected elements). A
hole's sketch is the one whose circles sit at its positions. Draft, Loft and Pipe hybrid steps are rebuilt
from what they record; other hybrid steps end the rebuilt history. When the file carries the explicit B-rep
too, the rebuilt solid is compared with it, which checks that the history means what was sent.
"""

import math
import os
import re
import tempfile

import FreeCAD as App
import Part

from . import iso10303, p21, parametric

X, Y, Z = App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)
BIG = 1e6                                            # "through all" when nothing else bounds it
EXTRUDE_TYPES = ("PartDesign::Pad", "PartDesign::Pocket")
REVOLVE_TYPES = ("PartDesign::Revolution", "PartDesign::Groove")
PRIMITIVES = {"Box": ("box", {"Length": "x", "Width": "y", "Height": "z"}),
              "Cylinder": ("cylinder", {"Radius": "radius", "Height": "height"}),
              "Sphere": ("sphere", {"Radius": "radius"}),
              "Cone": ("cone", {}),
              "Torus": ("torus", {"Radius1": "major", "Radius2": "minor"})}


def v3(v):
    return [float(v.x), float(v.y), float(v.z)]


def vec(a):
    return App.Vector(*[float(x) for x in a])


# ------------------------------------------------------------------ FreeCAD expressions
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "um": 1e-3, "µm": 1e-3, "in": 25.4, "ft": 304.8,
         "deg": math.pi / 180, "°": math.pi / 180, "rad": 1.0}
TRIG = ("sin", "cos", "tan")
_ETOK = re.compile(r"\s*(?:(?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)\s*(?P<unit>mm|cm|um|µm|m|in|"
                   r"ft|deg|°|rad)?(?![A-Za-z_])|(?P<id><<[^>]+>>(?:\.[A-Za-z_][\w]*)+|[A-Za-z_][\w]*(?:\.[A-Za-z_]"
                   r"[\w]*)*)|(?P<op>[-+*/^(),;]))")


class ExprError(ValueError):
    pass


def expression_from_fc(text, aliases):
    """FreeCAD expression -> model expression tree (lengths in mm, angles in radians).

    aliases: {(object name or label, alias): parameter name}. Raises ExprError for what the model cannot
    carry (references to other objects' properties, units other than lengths and angles, conditionals).
    """
    toks, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _ETOK.match(text, pos)
        if not m or m.end() == pos:
            raise ExprError(f"cannot read {text[pos:]!r}")
        if m.group("num") is not None:
            toks.append(("num", float(m.group("num")) * UNITS.get(m.group("unit") or "", 1.0),
                         m.group("unit")))
        elif m.group("id"):
            toks.append(("id", m.group("id"), None))
        else:
            toks.append(("op", m.group("op"), None))
        pos = m.end()
    i = [0]

    def peek():
        return toks[i[0]] if i[0] < len(toks) else ("end", None, None)

    def take(v=None):
        t = peek()
        if v is not None and t[1] != v:
            raise ExprError(f"expected {v!r} in {text!r}")
        i[0] += 1
        return t

    def atom():
        k, v, unit = take()
        if k == "num":
            return ["num", v]
        if k == "op" and v == "(":
            e = expr()
            take(")")
            return e
        if k == "id":
            if peek()[1] == "(":
                take("(")
                args = [expr()]
                while peek()[1] in (",", ";"):
                    take()
                    args.append(expr())
                take(")")
                fn = {"atan2": "atan", "ln": "log"}.get(v, v)
                if fn not in parametric.FUNCS:
                    raise ExprError(f"function {v} has no ISO 13584-20 counterpart")
                if fn in TRIG:                     # FreeCAD reads a plain number as degrees
                    args = [["num", math.radians(a[1])] if a[0] == "num" else a for a in args]
                if v == "atan2":
                    args = [args[0], args[1]]
                return ["call", fn, args]
            if v == "pi":
                return ["num", math.pi]
            if v == "e":
                return ["num", math.e]
            obj, _, member = v.rpartition(".")
            obj = obj.strip("<>")
            if (obj, member) in aliases:
                return ["var", aliases[(obj, member)]]
            raise ExprError(f"{v} is not a spreadsheet parameter")
        raise ExprError(f"unexpected {v!r} in {text!r}")

    def power():
        a = atom()
        if peek()[1] == "^":
            take()
            return ["^", a, unary()]
        return a

    def unary():
        if peek()[1] == "-":
            take()
            return ["neg", unary()]
        if peek()[1] == "+":
            take()
            return unary()
        return power()

    def term():
        a = unary()
        while peek()[1] in ("*", "/"):
            op = take()[1]
            a = [op, a, unary()]
        return a

    def expr():
        a = term()
        while peek()[1] in ("+", "-"):
            op = take()[1]
            a = [op, a, term()]
        return a

    e = expr()
    if peek()[0] != "end":
        raise ExprError(f"cannot read the rest of {text!r}")
    return e


def expression_to_fc(e, sheet="Parameters", angle=False):
    """Model expression tree -> FreeCAD expression text. A number added to or subtracted from a quantity
    gets the attribute's unit (mm, or deg for an angle)."""
    unit = "deg" if angle else "mm"

    def num(v, with_unit):
        if with_unit:
            v = math.degrees(v) if angle else v
            return f"{_fmt(v)} {unit}"
        return _fmt(v)

    def go(x, additive=False, prec=0):
        k = x[0]
        if k == "num":
            return num(x[1], additive)
        if k == "var":
            return f"{sheet}.{x[1]}"
        if k == "neg":
            return "-" + go(x[1], additive, 4)
        if k == "call":
            if x[1] in TRIG and x[2][0][0] == "num":
                return f"{x[1]}({_fmt(math.degrees(x[2][0][1]))} deg)"
            name = {"atan": "atan2" if len(x[2]) == 2 else "atan"}.get(x[1], x[1])
            return f"{name}(" + "; ".join(go(a) for a in x[2]) + ")"
        p = parametric._PREC[k]
        add = k in "+-"
        s = f"{go(x[1], add, p)} {k} {go(x[2], add, p + (k != '^'))}"
        return f"({s})" if p < prec else s

    return go(e, additive=True)


def _fmt(v):
    return repr(round(float(v), 12)).rstrip("0").rstrip(".") if v != int(v) else str(int(v))


# ------------------------------------------------------------------ geometry snapshots
def curve_dict(edge, reverse=False):
    """An edge's curve, oriented so that its parameter runs from p1 to p2."""
    c = edge.Curve
    t = type(c).__name__
    vs = edge.Vertexes
    p1, p2 = (v3(vs[0].Point), v3(vs[-1].Point)) if vs else ([0, 0, 0], [0, 0, 0])
    if reverse:
        p1, p2 = p2, p1
    if t in ("Line", "LineSegment"):
        return {"type": "line", "origin": p1, "dir": parametric._sub(p2, p1)}, p1, p2
    if t in ("Circle", "ArcOfCircle"):
        circ = c if t == "Circle" else c.Circle
        axis = v3(circ.Axis * (-1 if reverse else 1))
        return {"type": "circle", "center": v3(circ.Center), "axis": axis, "x": v3(circ.XAxis),
                "r": float(circ.Radius)}, p1, p2
    if t in ("Ellipse", "ArcOfEllipse"):
        el = c if t == "Ellipse" else c.Ellipse
        return {"type": "ellipse", "center": v3(el.Center), "axis": v3(el.Axis * (-1 if reverse else 1)),
                "x": v3(el.XAxis), "r1": float(el.MajorRadius), "r2": float(el.MinorRadius)}, p1, p2
    bs = c if t == "BSplineCurve" else c.toBSpline(edge.FirstParameter, edge.LastParameter)
    if bs.isRational():
        raise ValueError("rational B-spline edges are not written")
    poles, knots, mults = [v3(p) for p in bs.getPoles()], list(bs.getKnots()), list(bs.getMultiplicities())
    if reverse:
        a, b = knots[0], knots[-1]
        poles, knots, mults = poles[::-1], [a + b - k for k in knots[::-1]], mults[::-1]
    return {"type": "bspline", "degree": bs.Degree, "poles": poles, "knots": knots, "mults": mults,
            "closed": bool(bs.isClosed())}, p1, p2


def edge_dict(edge, reverse=False):
    c, p1, p2 = curve_dict(edge, reverse)
    return {"curve": c, "p1": p1, "p2": p2}


def surface_dict(face):
    s = face.Surface
    t = type(s).__name__
    if t == "Plane":
        rot = s.Rotation if hasattr(s, "Rotation") else App.Rotation(Z, s.Axis)
        return {"type": "plane", "origin": v3(s.Position), "axis": v3(s.Axis), "x": v3(rot.multVec(X))}
    if t == "Cylinder":
        return {"type": "cylinder", "origin": v3(s.Center), "axis": v3(s.Axis), "x": v3(_perp(s.Axis)),
                "r": float(s.Radius)}
    if t == "Cone":
        return {"type": "cone", "origin": v3(s.Center), "axis": v3(s.Axis), "x": v3(_perp(s.Axis)),
                "r": float(s.Radius), "semi_angle": float(s.SemiAngle)}
    if t == "Sphere":
        return {"type": "sphere", "origin": v3(s.Center), "axis": v3(s.Axis), "x": v3(_perp(s.Axis)),
                "r": float(s.Radius)}
    if t == "Toroid":
        return {"type": "torus", "origin": v3(s.Center), "axis": v3(s.Axis), "x": v3(_perp(s.Axis)),
                "R": float(s.MajorRadius), "r": float(s.MinorRadius)}
    raise ValueError(f"{t} faces are not written")


def _perp(a):
    a = App.Vector(a).normalize()
    x = X if abs(a.x) < 0.9 else Y
    return (x - a * x.dot(a)).normalize()


def face_dict(face):
    loops = []
    for w in [face.OuterWire] + [w for w in face.Wires if not w.isSame(face.OuterWire)]:
        loop = []
        for e in w.OrderedEdges:
            loop.append(edge_dict(e, reverse=e.Orientation == "Reversed"))
        loops.append(loop)
    return {"surface": surface_dict(face), "loops": loops, "same_sense": face.Orientation != "Reversed"}


def profile_faces(sketch):
    wires = [w for w in sketch.Shape.Wires if w.isClosed()]
    if not wires:
        return []
    try:
        made = Part.makeFace(wires, "Part::FaceMakerBullseye")
    except Exception:
        return []
    return [face_dict(f) for f in made.Faces]


# ------------------------------------------------------------------ FreeCAD -> model
def placement_dict(pl):
    return {"origin": v3(pl.Base), "axis": v3(pl.Rotation.multVec(Z)), "x": v3(pl.Rotation.multVec(X))}


def sketch_model(sk, aliases, notes):
    geo = []
    for i, g in enumerate(sk.Geometry):
        t = g.TypeId
        cons = bool(sk.getConstruction(i))
        if t == "Part::GeomLineSegment":
            geo.append({"type": "line", "p1": [g.StartPoint.x, g.StartPoint.y], "p2": [g.EndPoint.x, g.EndPoint.y]})
        elif t == "Part::GeomCircle":
            geo.append({"type": "circle", "c": [g.Center.x, g.Center.y], "r": g.Radius})
        elif t == "Part::GeomArcOfCircle":
            s, e = (g.StartPoint, g.EndPoint) if g.Axis.z > 0 else (g.EndPoint, g.StartPoint)
            geo.append({"type": "arc", "c": [g.Center.x, g.Center.y], "r": g.Radius, "p1": [s.x, s.y],
                        "p2": [e.x, e.y]})
        elif t == "Part::GeomPoint":
            geo.append({"type": "point", "p": [g.X, g.Y]})
        else:
            geo.append({"type": "unsupported"})
            notes.append(f"{sk.Label}: geometry {i} ({t}) has no mapping; it and its constraints are not written")
            continue
        if cons:
            geo[-1]["construction"] = True
    exprs = dict(sk.ExpressionEngine)
    cons = []
    for i, c in enumerate(sk.Constraints):
        d = {"type": c.Type, "first": c.First, "first_pos": int(c.FirstPos), "second": c.Second,
             "second_pos": int(c.SecondPos), "third": c.Third, "third_pos": int(c.ThirdPos), "value": c.Value,
             "name": c.Name or "", "driving": bool(c.Driving)}
        if c.Type == "Angle" and c.Third != -2000:
            d["type"] = "AngleViaPoint"
        text = exprs.get(f".Constraints.{c.Name}") if c.Name else None
        text = text or exprs.get(f".Constraints[{i}]")
        if text:
            try:
                d["expression"] = expression_from_fc(text, aliases)
            except ExprError as err:
                notes.append(f"{sk.Label}: constraint {c.Name or i} expression {text!r} not written ({err})")
        cons.append(d)
    out = {"name": sk.Label, "placement": placement_dict(sk.getGlobalPlacement()), "geometry": geo,
           "constraints": cons, "faces": profile_faces(sk)}
    att = _attachment(sk, notes)
    if att:
        out["attachment"] = att
    return out


def _attachment(sk, notes):
    """A sketch attached FlatFace to a planar face or a plane -> {mode, face or plane, name, offset}."""
    mode, sup = getattr(sk, "MapMode", "Deactivated"), _support(sk)
    if mode == "Deactivated" or not sup:
        return None
    if mode != "FlatFace" or len(sup) != 1:
        notes.append(f"{sk.Label}: attachment {mode} to {len(sup)} reference(s) not written; the sketch is placed")
        return None
    obj, subs = sup[0]
    sub = subs[0] if subs else ""
    att = {"mode": mode}
    if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
        pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        att.update(plane=placement_dict(pl), name=getattr(obj, "Role", "") or obj.Label)
    elif sub.startswith("Face") and type(obj.Shape.getElement(sub).Surface).__name__ == "Plane":
        fc = obj.Shape.getElement(sub)
        sd = surface_dict(fc)
        att.update(face=face_dict(fc), plane={"origin": sd["origin"], "axis": sd["axis"], "x": sd["x"]}, name="")
    else:
        notes.append(f"{sk.Label}: attachment to {obj.Label} {sub} not written; the sketch is placed")
        return None
    pl = sk.getGlobalPlacement()
    normal, pn = pl.Rotation.multVec(Z), vec(att["plane"]["axis"]).normalize()
    if abs(abs(normal.dot(pn)) - 1) > 1e-9:
        notes.append(f"{sk.Label}: its attachment offset tilts it off its support; written placed, not attached")
        return None
    att["offset"] = (pl.Base - vec(att["plane"]["origin"])).dot(pn)
    return att


def parameters(doc):
    """Spreadsheet aliases -> (model parameters, {(sheet name or label, alias): parameter name})."""
    params, aliases = [], {}
    for sh in doc.findObjects("Spreadsheet::Sheet"):
        for cell in sorted(sh.getUsedCells()):
            alias = sh.getAlias(cell)
            if not alias:
                continue
            v = getattr(sh, alias, None)
            unit = ""
            if hasattr(v, "Unit"):
                if v.Unit == App.Units.Length:
                    unit, val = "mm", float(v.getValueAs("mm"))
                elif v.Unit == App.Units.Angle:
                    unit, val = "deg", float(v.getValueAs("deg"))
                elif str(v.Unit) == str(App.Units.Unit()):
                    val = float(v.Value)
                else:
                    continue
            elif isinstance(v, (int, float)):
                val = float(v)
            else:
                continue
            name = alias if not any(p["name"] == alias for p in params) else f"{sh.Label}_{alias}"
            params.append({"name": name, "value": val, "unit": unit, "description": f"{sh.Label}.{alias}"})
            aliases[(sh.Name, alias)] = aliases[(sh.Label, alias)] = name
    return params, aliases


def _expr(obj, prop, aliases, notes, scale=None):
    text = dict(obj.ExpressionEngine).get(prop)
    if not text:
        return None
    try:
        e = expression_from_fc(text, aliases)
    except ExprError as err:
        notes.append(f"{obj.Label}.{prop}: expression {text!r} not written ({err})")
        return None
    return ["/", e, ["num", scale]] if scale else e


def _sketch_normal(sk):
    return sk.getGlobalPlacement().Rotation.multVec(Z)


def _direction_of(link, notes, label):
    """A pattern's Direction or Axis link -> (point, unit vector) in global coordinates."""
    if not link:
        return None
    obj, subs = link[0], (link[1] or [""])
    sub = subs[0] if subs else ""
    if obj.TypeId == "Sketcher::SketchObject":
        pl = obj.getGlobalPlacement()
        local = {"H_Axis": X, "V_Axis": Y, "N_Axis": Z}.get(sub)
        if local is not None:
            return pl.Base, pl.Rotation.multVec(local)
    if obj.TypeId in ("App::Line", "PartDesign::Line"):
        pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        base = Z if obj.TypeId == "PartDesign::Line" else X
        return pl.Base, pl.Rotation.multVec(base)
    if sub.startswith("Edge"):
        e = obj.Shape.getElement(sub)
        if type(e.Curve).__name__ in ("Line", "LineSegment"):
            return e.Vertexes[0].Point, (e.Vertexes[-1].Point - e.Vertexes[0].Point).normalize()
        if hasattr(e.Curve, "Axis"):
            return e.Curve.Center, e.Curve.Axis
    notes.append(f"{label}: direction reference {obj.Label} {sub} not understood")
    return None


def _rotation(axis_point, axis, angle):
    r = App.Rotation(axis, math.degrees(angle))
    m = r.toMatrix()
    rows = [[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]]
    t = axis_point - r.multVec(axis_point)
    return {"matrix": rows, "translation": v3(t)}


TOOL_TYPES = ("extrude", "revolve", "pipe", "box", "cylinder", "cone", "sphere", "torus")
PATTERN_TYPES = ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored",
                 "PartDesign::MultiTransform")
UP_TO = ("UpToFace", "UpToFirst", "UpToLast")


def _brep_text(shape, notes, label):
    """Part 21 text of a shape's (first) solid, written by OpenCASCADE, for a hybrid step."""
    solids = shape.Solids if shape is not None and not shape.isNull() else []
    if not solids:
        return None
    if len(solids) > 1:
        notes.append(f"{label}: {len(solids)} solids; the first is written")
    tmp = tempfile.NamedTemporaryFile(suffix=".step", delete=False)
    tmp.close()
    try:
        solids[0].exportStep(tmp.name)
        with open(tmp.name, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    finally:
        os.unlink(tmp.name)


def _explicit(f, kind, op, shape, notes, why, **extra):
    """A feature no ISO 10303-42/111 entity represents: its explicit solid in the history (Part 55 hybrid)."""
    text = _brep_text(shape, notes, f.Label)
    if text is None:
        return None
    ft = {"type": "explicit", "name": f.Label, "kind": kind, "op": op, "brep": text, "why": why}
    ft.update({k: v for k, v in extra.items() if v is not None})
    return ft


def _support(sk):
    return getattr(sk, "AttachmentSupport", None) if hasattr(sk, "AttachmentSupport") else getattr(sk, "Support", None)


def _plane_of(link, notes, label):
    """A mirror plane link -> (point, unit normal) in global coordinates."""
    if not link:
        return None
    obj, subs = link[0], (link[1] or [""])
    sub = subs[0] if subs else ""
    if obj.TypeId == "Sketcher::SketchObject":
        pl = obj.getGlobalPlacement()
        local = {"H_Axis": Y, "V_Axis": X, "": Z}.get(sub)
        if local is not None:
            return pl.Base, pl.Rotation.multVec(local)
    if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
        pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        return pl.Base, pl.Rotation.multVec(Z)
    if sub.startswith("Face"):
        fc = obj.Shape.getElement(sub)
        if type(fc.Surface).__name__ == "Plane":
            return fc.Surface.Position, fc.Surface.Axis
    notes.append(f"{label}: mirror plane {obj.Label} {sub} not understood")
    return None


def _transforms_of(f, notes):
    """(kind, rigid motions other than the identity) of a LinearPattern, PolarPattern or Mirrored."""
    t, n = f.TypeId, None
    if t.endswith("LinearPattern"):
        got = _direction_of(f.Direction, notes, f.Label)
        if got is None:
            return None
        n = int(f.Occurrences)
        d = got[1].normalize() * (-1 if f.Reversed else 1)
        mode = getattr(f, "Mode", "Overall length")
        step = float(f.Offset.Value) if mode == "Offset" and hasattr(f.Offset, "Value") else \
            float(f.Length.Value) / max(n - 1, 1)
        return "linear", [{"matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation": v3(d * (step * k))}
                          for k in range(1, n)]
    if t.endswith("PolarPattern"):
        got = _direction_of(f.Axis, notes, f.Label)
        if got is None:
            return None
        n = int(f.Occurrences)
        p, ax = got[0], got[1].normalize() * (-1 if f.Reversed else 1)
        ang = float(f.Angle.Value)
        mode = getattr(f, "Mode", "Overall angle")
        if mode == "Offset angle" and hasattr(f, "Offset"):
            step = float(f.Offset.Value)
        else:
            step = ang / n if abs(ang - 360) < 1e-9 else ang / max(n - 1, 1)
        return "polar", [_rotation(p, ax, math.radians(step * k)) for k in range(1, n)]
    if t.endswith("Mirrored"):
        got = _plane_of(f.MirrorPlane, notes, f.Label)
        if got is None:
            return None
        p, nv = got[0], App.Vector(got[1]).normalize()
        nn = [nv.x, nv.y, nv.z]
        m = [[(1.0 if i == j else 0.0) - 2 * nn[i] * nn[j] for j in range(3)] for i in range(3)]
        return "mirror", [{"matrix": m, "translation": v3(nv * (2 * p.dot(nv)))}]
    return None


def _wire_edges(obj, subs):
    """The edges of a sketch (or the named ones), chained into one wire: [(edge, reversed)]."""
    edges = [obj.Shape.getElement(s) for s in subs if s.startswith("Edge")] if subs else list(obj.Shape.Edges)
    wire = Part.Wire(Part.__sortEdges__(edges))
    return [(e, e.Orientation == "Reversed") for e in wire.OrderedEdges]


def _tangent(e, rev, at_end):
    u = e.LastParameter if (at_end != rev) else e.FirstParameter
    t = e.tangentAt(u)
    return t * (-1 if rev else 1)


def _pipe_model(f):
    """A Pipe of a sketch along a planar sketch path in Standard mode, profile normal to the path at its start
    -> a "pipe" feature (Part 42's surface-curve sweep), or (None, why)."""
    prof = f.Profile[0] if f.Profile else None
    spine = f.Spine
    if prof is None or prof.TypeId != "Sketcher::SketchObject" or not spine or \
            spine[0].TypeId != "Sketcher::SketchObject":
        return None, "profile and path must be sketches"
    if f.Mode != "Standard" or f.Transformation != "Constant" or list(f.Sections or []) or \
            getattr(f, "AuxiliarySpine", None):
        return None, f"mode {f.Mode}, {f.Transformation} sections (only Standard, Constant matches Part 42's sweep)"
    path = spine[0]
    edges = _wire_edges(path, list(spine[1] or []))
    ppl, kpl = path.getGlobalPlacement(), prof.getGlobalPlacement()
    N, pn, po = ppl.Rotation.multVec(Z), kpl.Rotation.multVec(Z), kpl.Base
    first, last = edges[0], edges[-1]
    start = first[0].Vertexes[-1 if first[1] else 0].Point
    end = last[0].Vertexes[0 if last[1] else -1].Point
    if abs((end - po).dot(pn)) < abs((start - po).dot(pn)):
        edges = [(e, not r) for e, r in reversed(edges)]
        start = end
    t0 = _tangent(*edges[0], False)
    if abs(abs(t0.normalize().dot(pn)) - 1) > 1e-7 or abs((start - po).dot(pn)) > 1e-6:
        return None, "the profile is not normal to the path at its start"
    for (e1, r1), (e2, r2) in zip(edges, edges[1:]):
        if (_tangent(e1, r1, True).normalize() - _tangent(e2, r2, False).normalize()).Length > 1e-6:
            return None, "the path is not tangent continuous (FreeCAD's corner transitions have no Part 42 match)"
    return {"type": "pipe", "name": f.Label, "sketch": prof.Label, "path": path.Label,
            "path_edges": [edge_dict(e, reverse=r) for e, r in edges], "normal": v3(N),
            "plane": placement_dict(ppl)}, None


def _hole_positions(f):
    sk = f.Profile[0]
    pl = sk.getGlobalPlacement()
    bits = int(getattr(f, "BaseProfileType", 6) or 6)
    out = []
    for i, g in enumerate(sk.Geometry):
        if sk.getConstruction(i):
            continue
        t = g.TypeId
        if (t == "Part::GeomCircle" and bits & 2) or (t == "Part::GeomArcOfCircle" and bits & 4):
            out.append(pl.multVec(g.Center))
        elif t == "Part::GeomPoint" and bits & 1:
            out.append(pl.multVec(App.Vector(g.X, g.Y, g.Z)))
    return out


def _hole_model(f, notes):
    """A PartDesign Hole -> a "hole" feature (ISO 10303-111 round holes), or (None, why)."""
    sk = f.Profile[0] if f.Profile else None
    if sk is None or sk.TypeId != "Sketcher::SketchObject":
        return None, "its profile is not a sketch"
    if f.Threaded or f.Tapered or getattr(f, "Midplane", False):
        return None, "threaded, tapered or midplane holes have no ISO 10303-111 counterpart here"
    if f.HoleCutType not in ("None", "Counterbore", "Countersink") or f.DepthType not in ("Dimension", "ThroughAll"):
        return None, f"cut type {f.HoleCutType}, depth type {f.DepthType}"
    pl = sk.getGlobalPlacement()
    normal = pl.Rotation.multVec(Z)
    axis = normal * (-1 if f.Reversed else 1)            # out of the hole entrance (111, 4.4.22)
    positions = _hole_positions(f)
    if not positions:
        return None, "no circle or point in its sketch"
    r, depth = float(f.Diameter.Value) / 2, float(f.Depth.Value)
    ft = {"type": "hole", "name": f.Label, "sketch": sk.Label, "positions": [v3(p) for p in positions],
          "axis": v3(axis), "x": v3(pl.Rotation.multVec(X))}
    if f.HoleCutType == "Counterbore":
        cb_r, cb_d = float(f.HoleCutDiameter.Value) / 2, float(f.HoleCutDepth.Value)
        ft["radii"], ft["depths"] = [cb_r, r], [cb_d, depth - cb_d]
    else:
        ft["radii"], ft["depths"] = [r], [depth]
    if f.HoleCutType == "Countersink":
        ft["transitions"] = [{"number": 1, "apex": math.radians(float(f.HoleCutCountersinkAngle.Value)),
                              "radius": float(f.HoleCutDiameter.Value) / 2}]
    if f.DepthType == "ThroughAll":
        ft["through"] = True
        base = f.BaseFeature.Shape
        exits, depths = [], []
        for p in positions:
            line = Part.LineSegment(p + axis * BIG, p - axis * BIG).toShape()
            hit = base.common(line)
            ts = [(v.Point - p).dot(axis * -1) for v in hit.Vertexes]
            if not ts or max(ts) <= 1e-9:
                return None, "a through hole that misses the solid"
            far = p - axis * max(ts)
            faces = [fc for fc in base.Faces if fc.distToShape(Part.Vertex(far))[0] < 1e-6]
            exits.append([face_dict(fc) for fc in faces[:1]])
            depths.append(max(ts) - sum(ft["depths"][:-1]))
        ft["exit_faces"], ft["exit_depths"] = exits, depths
        ft["depths"][-1] = depths[0]
    elif f.DrillPoint == "Angled":
        semi = math.radians(float(f.DrillPointAngle.Value)) / 2
        ft.update(bottom="conical", semi_apex=semi, tip_radius=0.0)
        if f.DrillForDepth:                                # FreeCAD's depth then ends at the tip
            ft["depths"][-1] -= r / math.tan(semi)
    else:
        ft.update(bottom="flat", fillet_radius=0.0)
    if any(d <= 0 for d in ft["depths"]):
        return None, "a segment of zero depth"
    if any(dict(f.ExpressionEngine).get(k) for k in ("Diameter", "Depth", "HoleCutDiameter", "HoleCutDepth")):
        notes.append(f"{f.Label}: hole radii and depths are lists in ISO 10303-111; their expressions are not written")
    return ft, None


def _up_to_face(f, d, prof):
    """The face an up-to extrusion ends at, its extent from the sketch plane and its offset."""
    tool = f.AddSubShape
    origin = prof.getGlobalPlacement().Base
    pts = [v.Point for v in tool.Vertexes] + [fc.CenterOfMass for fc in tool.Faces]
    extent = max((q - origin).dot(d) for q in pts)
    if f.Type == "UpToFace":
        obj, subs = f.UpToFace
        face = obj.Shape.getElement(subs[0]) if subs and subs[0] else (obj.Shape.Faces[0] if obj.Shape.Faces else None)
    else:
        base, face = f.BaseFeature.Shape, None
        for tf in tool.Faces:
            c = tf.CenterOfMass
            u, v = tf.Surface.parameter(c)
            if tf.normalAt(u, v).dot(d) < 0.5:
                continue
            hits = [bf for bf in base.Faces if bf.distToShape(Part.Vertex(c))[0] < 1e-6]
            if hits:
                face = hits[0]
                break
    if face is None:
        return None
    return {"face": face_dict(face), "offset": float(f.Offset.Value)}, extent


def body_model(body, aliases, notes):
    """A PartDesign Body -> (features, sketches used)."""
    chain, f = [], body.Tip
    while f is not None:
        chain.append(f)
        f = getattr(f, "BaseFeature", None)
    chain.reverse()
    feats, sketches, prev = [], {}, None
    for f in chain:
        t = f.TypeId
        ft = None
        exprs = {}
        word = t.split("::")[-1]
        addsub = ("difference" if "Subtractive" in t else "union") if prev else None
        if t in EXTRUDE_TYPES + REVOLVE_TYPES:
            prof = f.Profile[0] if f.Profile else None
            if prof is None or prof.TypeId != "Sketcher::SketchObject":
                notes.append(f"history stops at {f.Label}: its profile is not a sketch")
                break
            sketches[prof.Label] = prof
            n = _sketch_normal(prof)
            sub = t in ("PartDesign::Pocket", "PartDesign::Groove")
            side = getattr(f, "SideType", "Symmetric" if getattr(f, "Midplane", False) else "One side")
        if t in EXTRUDE_TYPES:
            d = n * (-1 if sub else 1)
            if getattr(f, "UseCustomVector", False):
                d = App.Vector(f.Direction).normalize()
            if f.Reversed:
                d = d * -1
            L, L2 = float(f.Length.Value), float(f.Length2.Value)
            kind = f.Type
            intent = ["blind", "blind"]
            up = None
            if kind == "ThroughAll":
                L, intent = BIG, ["through_all", "blind"]
            elif kind in UP_TO and side == "One side":
                got = _up_to_face(f, d, prof)
                if got is None:
                    notes.append(f"{f.Label}: the face of its {kind} extent was not found; written as its length")
                else:
                    up, L = got
                    intent = ["up_to_next" if kind == "UpToFirst" else "unspecified", "blind"]
            elif kind not in ("Length", "TwoLengths"):
                notes.append(f"{f.Label}: Type {kind} written as its Length ({L:g} mm); the extent intent is lost")
            if side == "Symmetric":
                first, second = L / 2, -L / 2
                if kind == "ThroughAll":
                    first, second, intent = BIG, -BIG, ["through_all", "through_all"]
                e = _expr(f, "Length", aliases, notes, 2.0)
                if e:
                    exprs["first"] = e
            elif side == "Two sides" or kind == "TwoLengths":
                first, second = L, -L2
                e1, e2 = _expr(f, "Length", aliases, notes), _expr(f, "Length2", aliases, notes)
                if e1:
                    exprs["first"] = e1
                if e2:
                    exprs["second"] = ["neg", e2]
            else:
                first, second = L, 0.0
                e = _expr(f, "Length", aliases, notes)
                if e and kind not in ("ThroughAll",) + UP_TO:
                    exprs["first"] = e
            if up is None and abs(float(getattr(f, "Offset", 0) and f.Offset.Value or 0)) > 1e-12:
                notes.append(f"{f.Label}: Offset not written")
            ft = {"type": "extrude", "name": f.Label, "sketch": prof.Label, "direction": v3(d),
                  "first": first, "second": second, "intent": intent,
                  "op": ("difference" if sub else "union") if prev else None}
            if up:
                ft["up_to"] = up
            taper = float(f.TaperAngle.Value) if hasattr(f, "TaperAngle") else 0.0
            if taper:
                ft["taper"] = math.radians(taper)
        elif t in REVOLVE_TYPES:
            axis = App.Vector(f.Axis).normalize()
            if f.Reversed:
                axis = axis * -1
            a = math.radians(float(f.Angle.Value))
            if f.Type == "ThroughAll":
                a = 2 * math.pi
            first, second = a, 0.0
            e = None
            up = None
            if f.Type == "UpToFace" and side == "One side" and f.UpToFace:
                obj, subs = f.UpToFace
                if subs and subs[0].startswith("Face"):
                    up = {"face": face_dict(obj.Shape.getElement(subs[0]))}
            elif f.Type in UP_TO:
                notes.append(f"{f.Label}: Type {f.Type} written as its Angle; the extent intent is lost")
            if up:
                pass
            elif side == "Symmetric":
                first, second = a / 2, -a / 2
                e = _expr(f, "Angle", aliases, notes, 2.0)
            elif f.Type == "TwoAngles" or side == "Two sides":
                first, second = a, -math.radians(float(f.Angle2.Value))
                e = _expr(f, "Angle", aliases, notes)
            else:
                e = _expr(f, "Angle", aliases, notes)
            if e:
                exprs["angle"] = e
            ft = {"type": "revolve", "name": f.Label, "sketch": prof.Label,
                  "axis": {"origin": v3(f.Base), "dir": v3(axis)}, "angle": first, "second": second,
                  "op": ("difference" if sub else "union") if prev else None}
            if up:
                ft["up_to"] = up
        elif t in ("PartDesign::Fillet", "PartDesign::Chamfer"):
            base, subs = f.Base[0], f.Base[1]
            if getattr(f, "UseAllEdges", False):
                subs = [f"Edge{i + 1}" for i in range(len(base.Shape.Edges))]
            edges = [edge_dict(base.Shape.getElement(s)) for s in subs if s.startswith("Edge")]
            if t == "PartDesign::Fillet":
                ft = {"type": "fillet", "name": f.Label, "radius": float(f.Radius.Value), "edges": edges}
                e = _expr(f, "Radius", aliases, notes)
                if e:
                    exprs["radius"] = e
            else:
                kind = {"Equal distance": "single", "Two distances": "double",
                        "Distance and Angle": "angle"}.get(f.ChamferType, "single")
                ft = {"type": "chamfer", "name": f.Label, "kind": kind, "d1": float(f.Size.Value), "edges": edges}
                if kind == "double":
                    ft["d2"] = float(f.Size2.Value)
                if kind == "angle":
                    ft["angle"], ft["left"] = math.radians(float(f.Angle.Value)), not f.FlipDirection
                e = _expr(f, "Size", aliases, notes)
                if e and kind == "single":
                    exprs["d1"] = e
        elif t == "PartDesign::Thickness":
            base, subs = f.Base[0], f.Base[1]
            faces = [face_dict(base.Shape.getElement(s)) for s in subs if s.startswith("Face")]
            thick = float(f.Value.Value) * (-1 if f.Reversed else 1)
            ft = {"type": "shell", "name": f.Label, "thickness": thick, "faces": faces}
            e = _expr(f, "Value", aliases, notes)
            if e:
                exprs["thickness"] = ["neg", e] if f.Reversed else e
            if getattr(f, "Join", "Arc") != "Arc" or getattr(f, "Mode", "Skin") != "Skin":
                notes.append(f"{f.Label}: Join/Mode other than Arc/Skin not written")
        elif t == "PartDesign::Hole":
            ft, why = _hole_model(f, notes)
            if ft is None:
                ft = _explicit(f, "Hole", "difference" if prev else None, f.AddSubShape, notes, why)
            else:
                sketches[ft["sketch"]] = f.Profile[0]
        elif t in PATTERN_TYPES:
            originals = list(getattr(f, "Originals", []) or [])
            known = {x["name"]: x for x in feats}
            why = None
            if not originals:
                why = "it transforms the whole body rather than features"
            elif "body" in str(getattr(f, "TransformMode", "")).lower():
                why = "it transforms the whole body rather than features"
            elif not all(o.Label in known and (known[o.Label]["type"] in TOOL_TYPES or
                                               (known[o.Label]["type"] == "explicit" and known[o.Label].get("op")))
                         for o in originals):
                why = "a pattern is written for features that add or remove a solid (Pad, Pocket, Revolution, " \
                      "Groove, Pipe, primitives), not for " + ", ".join(o.Label for o in originals)
            got = None
            if why is None:
                if t.endswith("MultiTransform"):
                    steps = []
                    for sub_f in f.Transformations:
                        g = _transforms_of(sub_f, notes)
                        if g is None:
                            why = f"its step {sub_f.Label} ({sub_f.TypeId}) is not written"
                            break
                        steps.append({"name": sub_f.Label, "kind": g[0], "transforms": g[1]})
                    if why is None:
                        allt = [x for st in parametric.multi_transforms(steps) for x in st]
                        got = ("multi", allt, steps)
                else:
                    g = _transforms_of(f, notes)
                    got = (g[0], g[1], None) if g else None
                    if got is None:
                        why = "its direction, axis or plane is not understood"
            if why is not None:
                ft = _explicit(f, word, None, f.Shape, notes, why)
            else:
                ft = {"type": "pattern", "name": f.Label, "source": originals[0].Label,
                      "sources": [o.Label for o in originals], "kind": got[0], "transforms": got[1]}
                if got[2]:
                    ft["steps"] = got[2]
        elif t in ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe"):
            ft, why = _pipe_model(f)
            if ft is not None:
                ft["op"] = addsub
                sketches[ft["sketch"]] = f.Profile[0]
                sketches[ft["path"]] = f.Spine[0]
            else:
                spine = f.Spine
                path = spine[0] if spine else None
                for o in [f.Profile[0] if f.Profile else None, path]:
                    if o is not None and o.TypeId == "Sketcher::SketchObject":
                        sketches[o.Label] = o
                ft = _explicit(f, word, addsub, f.AddSubShape, notes, why,
                               profile=f.Profile[0].Label if f.Profile else None,
                               path=path.Label if path is not None else None,
                               path_edges=[edge_dict(e, reverse=r) for e, r in _wire_edges(path, list(spine[1] or []))]
                               if path is not None else None,
                               params={"mode": f.Mode, "transition": f.Transition})
        elif t in ("PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft"):
            prof = f.Profile[0] if f.Profile else None
            secs = [s[0] if isinstance(s, tuple) else s for s in (f.Sections or [])]
            for o in [prof] + secs:
                if o is not None and o.TypeId == "Sketcher::SketchObject":
                    sketches[o.Label] = o
            ft = _explicit(f, word, addsub, f.AddSubShape, notes,
                           "ISO 10303-42 has no lofted solid (sectioned_spine leaves the shape between sections "
                           "undefined and is no solid)", profile=prof.Label if prof is not None else None,
                           sections=[o.Label for o in secs], params={"ruled": bool(f.Ruled), "closed": bool(f.Closed)})
        elif t == "PartDesign::Draft":
            base, subs = f.Base[0], f.Base[1]
            faces = [face_dict(base.Shape.getElement(s)) for s in subs if s.startswith("Face")]
            neutral, pull = None, None
            if f.NeutralPlane:
                obj, nsubs = f.NeutralPlane
                nsub = nsubs[0] if nsubs else ""
                if nsub.startswith("Face"):
                    neutral = {"face": face_dict(obj.Shape.getElement(nsub))}
                else:
                    neutral = {"plane": placement_dict(obj.getGlobalPlacement()),
                               "name": getattr(obj, "Role", "") or obj.Label}
            if f.PullDirection:
                obj, psubs = f.PullDirection
                if psubs and psubs[0].startswith("Edge"):
                    pull = edge_dict(obj.Shape.getElement(psubs[0]))
            if dict(f.ExpressionEngine).get("Angle"):
                notes.append(f"{f.Label}: no ISO 10303 attribute carries a draft's angle; its expression is not written")
            ft = _explicit(f, "Draft", None, f.Shape, notes,
                           "no ISO 10303-111 entity drafts selected faces of a solid (extruded_face_solid_with_draft_"
                           "angle drafts an extrusion as it is made)", faces=faces, neutral=neutral, pull=pull,
                           params={"angle": math.radians(float(f.Angle.Value)), "reversed": bool(f.Reversed)})
        elif t.startswith("PartDesign::Additive") or t.startswith("PartDesign::Subtractive"):
            w2 = t.split("Additive")[-1].split("Subtractive")[-1]
            ft = _primitive(f, w2, aliases, notes) if w2 in PRIMITIVES else None
            if ft is not None:
                ft["op"] = addsub
            else:
                ft = _explicit(f, word, addsub, f.AddSubShape, notes, "no ISO 10303-42/111 entity is mapped to it")
        elif hasattr(f, "Shape") and f.Shape.Solids:
            ft = _explicit(f, word, None, f.Shape, notes, "no ISO 10303-42/111 entity is mapped to it")
        if ft is None:
            notes.append(f"history stops at {f.Label} ({t}): it could not be written; the explicit B-rep still "
                         "carries the whole shape")
            break
        if exprs:
            ft.setdefault("expressions", {}).update(exprs)
        feats.append(ft)
        prev = ft
    return feats, sketches


def _primitive(o, word, aliases, notes):
    if word not in PRIMITIVES:
        return None
    kind, props = PRIMITIVES[word]
    pl = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
    ft = {"type": kind, "name": o.Label, "placement": placement_dict(pl)}
    for prop, key in props.items():
        ft[key] = float(getattr(o, prop).Value)
        e = _expr(o, prop, aliases, notes)
        if e:
            ft.setdefault("expressions", {})[key] = e
    if kind == "cone":
        r1, r2, h = float(o.Radius1.Value), float(o.Radius2.Value), float(o.Height.Value)
        if r2 > r1:                                  # STEP's cone narrows from its base: turn it over
            ft["placement"] = placement_dict(pl.multiply(App.Placement(App.Vector(0, 0, h), App.Rotation(X, 180))))
            r1, r2 = r2, r1
        ft.update(radius=r1, height=h, semi_angle=math.atan2(r1 - r2, h))
    if hasattr(o, "Angle") and abs(float(o.Angle.Value) - 360) > 1e-9:
        notes.append(f"{o.Label}: a partial {word} (Angle {float(o.Angle.Value):g}°) has no CSG primitive")
        return None
    return ft


def part_model(obj, aliases, notes, feats, seen):
    """Part workbench CSG tree -> features in dependency order."""
    if obj.Name in seen:
        return seen[obj.Name]
    t = obj.TypeId
    word = t.split("::")[-1]
    ft = None
    if word in PRIMITIVES:
        ft = _primitive(obj, word, aliases, notes)
    elif t in ("Part::Cut", "Part::Fuse", "Part::Common", "Part::MultiFuse", "Part::MultiCommon"):
        ops = list(obj.Shapes) if hasattr(obj, "Shapes") and t.startswith("Part::Multi") else [obj.Base, obj.Tool]
        names = [part_model(o, aliases, notes, feats, seen) for o in ops]
        if None in names:
            return None
        op = {"Cut": "difference", "Fuse": "union", "Common": "intersection", "MultiFuse": "union",
              "MultiCommon": "intersection"}[word]
        cur = names[0]
        for k, nm in enumerate(names[1:], 1):
            label = obj.Label if k == len(names) - 1 else f"{obj.Label}.{k}"
            feats.append({"type": "boolean", "name": label, "op": op, "first": cur, "second": nm})
            cur = label
        seen[obj.Name] = cur
        return cur
    if ft is None:
        notes.append(f"{obj.Label} ({t}) is not a CSG primitive or Boolean; not written")
        seen[obj.Name] = None
        return None
    feats.append(ft)
    seen[obj.Name] = ft["name"]
    return ft["name"]


def model_from_object(obj):
    """A Body, a Part CSG object or a sketch -> (model, notes)."""
    doc = obj.Document
    notes = []
    params, aliases = parameters(doc)
    model = {"name": obj.Label, "parameters": params, "sketches": [], "features": []}
    if obj.TypeId == "PartDesign::Body":
        feats, sketches = body_model(obj, aliases, notes)
        for o in obj.Group:                          # sketches the history does not use still carry intent
            if o.TypeId == "Sketcher::SketchObject":
                sketches.setdefault(o.Label, o)
        model["features"] = feats
        model["sketches"] = [sketch_model(s, aliases, notes) for s in sketches.values()]
    elif obj.TypeId == "Sketcher::SketchObject":
        model["sketches"] = [sketch_model(obj, aliases, notes)]
    else:
        feats = []
        part_model(obj, aliases, notes, feats, {})
        model["features"] = feats
    return model, notes


# ------------------------------------------------------------------ export
def export(obj, path, brep=True, sketch_commands=False):
    """Write obj (a Body, Part CSG object or sketch) as STEP AP242 with its parametric model; with
    sketch_commands, each sketch also as ISO 10303-112 commands (outside AP242's schema).
    Returns a report text."""
    model, notes = model_from_object(obj)
    if brep and hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids:
        import Import
        tmp = tempfile.NamedTemporaryFile(suffix=".step", delete=False)
        tmp.close()
        try:
            Part.setStaticValue("write.step.schema", "AP242DIS")
            Import.export([obj], tmp.name)
            f = p21.read(tmp.name)
        finally:
            os.unlink(tmp.name)
        f, more = parametric.merge(f, model, sketch_commands=sketch_commands)
    else:
        f, more = parametric.to_step(model, sketch_commands=sketch_commands)
    notes += more
    p21.write(f, path)
    issues = iso10303.check(path)
    errors = [i for i in issues if i.level == "error"]
    inv = iso10303.inventory(p21.read(path))
    lines = [f"{path}", f"{obj.Label}: {len(model['parameters'])} parameter(s), {len(model['sketches'])} sketch(es), "
             f"{len(model['features'])} feature(s) in the history"]
    for std in sorted(inv):
        lines.append(f"  {std}: {sum(inv[std].values())} instances")
    lines.append(f"Check against ISO 10303 (Parts 21, 42, 43, 55, 108, 111{', 112' if sketch_commands else ''}): "
                 f"{len(errors)} error(s)")
    lines += ["  " + repr(i) for i in errors[:20]]
    if notes:
        lines += ["", "Not written:"] + ["  " + n for n in notes]
    return "\n".join(lines)


# ------------------------------------------------------------------ model -> FreeCAD
def _rotation_of(pl):
    z, x = vec(pl["axis"]).normalize(), vec(pl["x"]).normalize()
    y = z.cross(x)
    return App.Rotation(x, y, z, "ZXY")


def _placement(pl):
    return App.Placement(vec(pl["origin"]), _rotation_of(pl))


def make_sketch(container, doc, sk, notes, sheet):
    import Sketcher
    s = container.newObject("Sketcher::SketchObject", "Sketch") if container else \
        doc.addObject("Sketcher::SketchObject", "Sketch")
    s.Label = sk["name"]
    s.MapMode = "Deactivated"
    s.Placement = _placement(sk["placement"])
    for g in sk["geometry"]:
        t = g["type"]
        if t == "line":
            geo = Part.LineSegment(App.Vector(*g["p1"], 0), App.Vector(*g["p2"], 0))
        elif t == "circle":
            geo = Part.Circle(App.Vector(*g["c"], 0), Z, g["r"])
        elif t == "arc":
            a1 = math.atan2(g["p1"][1] - g["c"][1], g["p1"][0] - g["c"][0])
            a2 = math.atan2(g["p2"][1] - g["c"][1], g["p2"][0] - g["c"][0])
            while a2 <= a1:
                a2 += 2 * math.pi
            geo = Part.ArcOfCircle(Part.Circle(App.Vector(*g["c"], 0), Z, g["r"]), a1, a2)
        elif t == "point":
            geo = Part.Point(App.Vector(*g["p"], 0))
        elif t == "ellipse":
            c, m = App.Vector(*g["c"], 0), App.Vector(*g["major"], 0)
            minor = App.Vector(-m.y, m.x, 0).normalize() * g["r2"]
            # Part.Ellipse(S1, S2, centre) wants the end of the major axis first
            geo = Part.Ellipse(c + m, c + minor, c) if m.Length >= g["r2"] else Part.Ellipse(c + minor, c + m, c)
        elif t == "spline":
            geo = Part.BSplineCurve()
            geo.interpolate([App.Vector(*q, 0) for q in g["points"]], PeriodicFlag=bool(g.get("closed")))
        else:
            geo = Part.Point(App.Vector(0, 0, 0))      # keeps the indices of the constraints right
            notes.append(f"{sk['name']}: geometry of type {t} replaced by a point")
        s.addGeometry(geo, bool(g.get("construction")))
    for c in sk["constraints"]:
        t = c["type"]
        a, ap, b, bp, cc = (c.get("first", -2000), c.get("first_pos", 0), c.get("second", -2000),
                            c.get("second_pos", 0), c.get("third", -2000))
        v = c.get("value")
        if t in ("Distance", "Radius", "Diameter", "DistanceX", "DistanceY"):
            v = App.Units.Quantity(f"{v} mm")
        elif t == "Angle":
            v = App.Units.Quantity(f"{math.degrees(v)} deg")
        args = {
            "Coincident": (a, ap, b, bp), "PointOnObject": (a, ap, b), "Horizontal": (a,), "Vertical": (a,),
            "Parallel": (a, b), "Perpendicular": (a, b), "Tangent": (a, b), "Equal": (a, b), "Block": (a,),
            "Radius": (a, v), "Diameter": (a, v), "Symmetric": (a, ap, b, bp, cc),
        }.get(t)
        if t == "Distance":
            args = (a, v) if b == -2000 else (a, ap, b, bp, v) if bp else (a, ap, b, v)
        elif t in ("DistanceX", "DistanceY"):
            args = (a, v) if b == -2000 and not ap else (a, ap, v) if b == -2000 else (a, ap, b, bp, v)
        elif t == "Angle":
            args = (a, v) if b == -2000 else (a, b, v)
        if args is None:
            notes.append(f"{sk['name']}: constraint {t} not created")
            continue
        try:
            i = s.addConstraint(Sketcher.Constraint(t, *args))
        except Exception as err:
            notes.append(f"{sk['name']}: {t} {args} not created ({err})")
            continue
        if c.get("name"):
            try:
                s.renameConstraint(i, c["name"])
            except Exception:
                pass
        if c.get("expression") and sheet:
            path = f".Constraints.{c['name']}" if c.get("name") else f".Constraints[{i}]"
            try:
                s.setExpression(path, expression_to_fc(c["expression"], angle=t == "Angle"))
            except Exception as err:
                notes.append(f"{sk['name']}: expression on {t} not set ({err})")
    return s


def _set_expr(obj, prop, e, notes, angle=False, wrap=None):
    if not e:
        return
    try:
        text = expression_to_fc(e, angle=angle)
        obj.setExpression(prop, wrap.format(text) if wrap else text)
    except Exception as err:
        notes.append(f"{obj.Label}.{prop}: expression not set ({err})")


def _match_edges(shape, snaps, tol=1e-4):
    out = []
    for s in snaps:
        mid = edge_midpoint(s)
        best = None
        for i, e in enumerate(shape.Edges):
            vs = [v.Point for v in e.Vertexes]
            if len(vs) == 0:
                continue
            a, b = vs[0], vs[-1]
            p1, p2 = vec(s["p1"]), vec(s["p2"])
            if not ((a.distanceToPoint(p1) < tol and b.distanceToPoint(p2) < tol)
                    or (a.distanceToPoint(p2) < tol and b.distanceToPoint(p1) < tol)):
                continue
            if mid is not None:
                m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
                if m.distanceToPoint(vec(mid)) > max(tol, 1e-3 * e.Length):
                    continue
            best = f"Edge{i + 1}"
            break
        if best:
            out.append(best)
    return out


def edge_midpoint(s):
    c = s["curve"]
    p1, p2 = s["p1"], s["p2"]
    if c["type"] == "line":
        return [(a + b) / 2 for a, b in zip(p1, p2)]
    if c["type"] == "circle":
        ctr, ax = vec(c["center"]), vec(c["axis"]).normalize()
        v1, v2 = vec(p1) - ctr, vec(p2) - ctr
        if v1.Length < 1e-12:
            return None
        ang = math.atan2(ax.dot(v1.cross(v2)), v1.dot(v2))
        if ang <= 1e-12:
            ang += 2 * math.pi
        return v3(ctr + App.Rotation(ax, math.degrees(ang / 2)).multVec(v1))
    return None


def _match_faces(shape, snaps, tol=1e-4):
    out = []
    for s in snaps:
        want = sorted({tuple(round(x, 4) for x in e["p1"]) for loop in s["loops"] for e in loop})
        for i, f in enumerate(shape.Faces):
            have = sorted({tuple(round(x, 4) for x in v3(v.Point)) for v in f.Vertexes})
            if have == want and type(f.Surface).__name__.lower().startswith(s["surface"]["type"][:4]):
                out.append(f"Face{i + 1}")
                break
            if not want and f.Surface.TypeId and type(f.Surface).__name__ == "Plane":
                continue
    return out


def _axis_reference(body, sketch, origin, d, notes, label):
    """A link for a revolution or pattern axis: a sketch axis, an origin axis, or a new datum line."""
    o, d = vec(origin), vec(d).normalize()
    if sketch is not None:
        pl = sketch.Placement
        for sub, local in (("V_Axis", Y), ("H_Axis", X), ("N_Axis", Z)):
            ax = pl.Rotation.multVec(local)
            if abs(abs(ax.dot(d)) - 1) < 1e-9 and (o - pl.Base).cross(ax).Length < 1e-6:
                return (sketch, [sub]), ax.dot(d) < 0
    for feat in body.Origin.OriginFeatures:
        role = getattr(feat, "Role", feat.Name)
        if role in ("X_Axis", "Y_Axis", "Z_Axis"):
            ax = {"X_Axis": X, "Y_Axis": Y, "Z_Axis": Z}[role]
            if abs(abs(ax.dot(d)) - 1) < 1e-9 and o.cross(ax).Length < 1e-6:
                return (feat, [""]), ax.dot(d) < 0
    line = body.newObject("PartDesign::Line", f"{label}_Axis")
    line.MapMode = "Deactivated"
    line.Placement = App.Placement(o, App.Rotation(Z, d))
    notes.append(f"{label}: axis is a new datum line {line.Label}")
    return (line, [""]), False


def _rotation_axis(m):
    """Axis and angle of a 3x3 rotation matrix (rows)."""
    mat = App.Matrix(m[0][0], m[0][1], m[0][2], 0, m[1][0], m[1][1], m[1][2], 0, m[2][0], m[2][1], m[2][2], 0)
    r = App.Rotation(mat)
    return r.Axis, r.Angle


ORIGIN_PLANES = {"XY_Plane": Z, "XZ_Plane": Y, "YZ_Plane": X}


def _origin_plane(body, point, normal):
    p, nv = vec(point), vec(normal).normalize()
    for feat in body.Origin.OriginFeatures:
        role = getattr(feat, "Role", feat.Name)
        if role in ORIGIN_PLANES:
            ax = ORIGIN_PLANES[role]
            if abs(abs(ax.dot(nv)) - 1) < 1e-9 and abs(p.dot(ax)) < 1e-6:
                return feat
    return None


def _plane_reference(body, point, normal, notes, label):
    """A link for a mirror plane: an origin plane, or a new datum plane."""
    feat = _origin_plane(body, point, normal)
    if feat is not None:
        return (feat, [""])
    pl = body.newObject("PartDesign::Plane", f"{label}_Plane")
    pl.MapMode = "Deactivated"
    pl.Placement = App.Placement(vec(point), App.Rotation(Z, vec(normal)))
    notes.append(f"{label}: mirror plane is a new datum plane {pl.Label}")
    return (pl, [""])


def _transform_class(trs):
    m = trs[0]["matrix"]
    if parametric._det(m) < 0:
        return "PartDesign::Mirrored"
    _ax, ang = _rotation_axis(m)
    return "PartDesign::LinearPattern" if abs(ang) < 1e-9 else "PartDesign::PolarPattern"


def _setup_transform(o, body, trs, n, notes):
    """Set a LinearPattern, PolarPattern or Mirrored up from its rigid motions (identity excluded)."""
    if o.TypeId.endswith("Mirrored"):
        m = trs[0]["matrix"]
        cols = [[(1.0 if i == j else 0.0) - m[i][j] for i in range(3)] for j in range(3)]   # (I - M) = 2 n n^T
        c = max(cols, key=lambda v: sum(x * x for x in v))
        nv = vec(c).normalize()
        point = vec(trs[0]["translation"]) * 0.5
        o.MirrorPlane = _plane_reference(body, point, nv, notes, n)
    elif o.TypeId.endswith("LinearPattern"):
        t1, tl = vec(trs[0]["translation"]), vec(trs[-1]["translation"])
        ref, rev = _axis_reference(body, None, [0, 0, 0], v3(t1.normalize()), notes, n)
        o.Direction = ref
        o.Reversed = rev
        o.Occurrences = len(trs) + 1
        o.Length = tl.Length
    else:
        ax, ang = _rotation_axis(trs[0]["matrix"])
        t = vec(trs[0]["translation"])
        rot = App.Rotation(ax, math.degrees(ang))
        p = _axis_point(rot, t, ax)
        ref, rev = _axis_reference(body, None, v3(p), v3(ax), notes, n)
        o.Axis = ref
        o.Reversed = rev
        count = len(trs) + 1
        step = math.degrees(ang)
        o.Occurrences = count
        o.Angle = 360 if abs(step * count - 360) < 1e-6 else step * (count - 1)


def _attach(doc, sk, support, notes):
    """Attach a placed sketch FlatFace to support, with the AttachmentOffset that keeps it where it is."""
    want = App.Placement(sk.Placement)
    prop = "AttachmentSupport" if hasattr(sk, "AttachmentSupport") else "Support"
    setattr(sk, prop, [support])
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = App.Placement()
    doc.recompute()
    sk.AttachmentOffset = sk.Placement.inverse().multiply(want)
    doc.recompute()
    if (sk.Placement.Base - want.Base).Length > 1e-6 or not sk.Placement.Rotation.isSame(want.Rotation, 1e-9):
        setattr(sk, prop, [])
        sk.MapMode = "Deactivated"
        sk.Placement = want
        notes.append(f"{sk.Label}: re-attachment did not keep its placement; left placed")
        return False
    return True


def _find_hole_sketch(ft, sketches):
    """Name of the sketch whose circle centres are the hole positions (the hole's own sketch), if any."""
    want = [vec(p) for p in ft["positions"]]
    axis = vec(ft["axis"]).normalize()
    for name, sk in sketches.items():
        pl = sk.Placement
        if abs(abs(pl.Rotation.multVec(Z).dot(axis)) - 1) > 1e-9:
            continue
        have = [pl.multVec(g.Center) for i, g in enumerate(sk.Geometry) if not sk.getConstruction(i) and
                g.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle")]
        if len(have) == len(want) and all(any((h - w).Length < 1e-6 for h in have) for w in want):
            return name
    return None


def _hole_sketch(body, ft, sketches):
    """The hole's own sketch, or a new one with circles at its positions."""
    name = _find_hole_sketch(ft, sketches)
    if name is not None:
        return sketches[name], False
    want = [vec(p) for p in ft["positions"]]
    sk = body.newObject("Sketcher::SketchObject", f"{ft['name']}Sketch")
    sk.MapMode = "Deactivated"
    sk.Placement = _placement({"origin": ft["positions"][0], "axis": ft["axis"], "x": ft["x"]})
    inv = sk.Placement.inverse()
    for p in want:
        sk.addGeometry(Part.Circle(inv.multVec(p), Z, ft["radii"][-1]), False)
    return sk, True


def _make_hole(doc, body, ft, sketches, notes):
    radii, depths, tr = ft["radii"], list(ft["depths"]), ft.get("transitions") or []
    n = ft["name"]
    if len(radii) > 2 or (len(radii) == 2 and tr) or any(c["number"] != 1 for c in tr) or \
            ft.get("bottom") == "spherical" or ft.get("fillet_radius", 0) > 1e-9 or ft.get("tip_radius", 0) > 1e-9:
        notes.append(f"{n}: this hole shape has no PartDesign Hole equivalent; stopped")
        return None
    sk, new = _hole_sketch(body, ft, sketches)
    if new:
        notes.append(f"{n}: no sketch has its centres; a new sketch {sk.Label} holds them")
    doc.recompute()
    o = body.newObject("PartDesign::Hole", "Hole")
    o.Profile = sk
    o.Reversed = sk.Placement.Rotation.multVec(Z).dot(vec(ft["axis"])) < 0
    o.Diameter = 2 * radii[-1]
    if len(radii) == 2:
        o.HoleCutType = "Counterbore"
        o.HoleCutDiameter, o.HoleCutDepth = 2 * radii[0], depths[0]
    elif tr:
        o.HoleCutType = "Countersink"
        o.HoleCutDiameter, o.HoleCutCountersinkAngle = 2 * tr[0]["radius"], math.degrees(tr[0]["apex"])
    if ft.get("through"):
        o.DepthType = "ThroughAll"
    else:
        o.Depth = sum(depths)
        if ft.get("bottom") == "conical":
            o.DrillPoint, o.DrillPointAngle, o.DrillForDepth = "Angled", math.degrees(2 * ft["semi_apex"]), False
        else:
            o.DrillPoint = "Flat"
    return o


def model_to_document(model, doc):
    """Build FreeCAD objects for a model. Returns (main object, notes)."""
    notes = []
    sheet = None
    if model.get("parameters"):
        sheet = doc.addObject("Spreadsheet::Sheet", "Parameters")
        for k, p in enumerate(model["parameters"], 1):
            unit = {"mm": " mm", "deg": " deg"}.get(p.get("unit"), "")
            sheet.set(f"A{k}", p["name"])
            sheet.set(f"B{k}", f"{_fmt(p['value'])}{unit}")
            sheet.setAlias(f"B{k}", p["name"])
        doc.recompute()
    kinds = {ft["type"] for ft in model["features"]}
    body_mode = bool(kinds & {"extrude", "revolve", "fillet", "chamfer", "shell", "pattern", "hole", "pipe",
                              "explicit"}) or (model["sketches"] and not kinds)
    if body_mode:
        # a new part (Ctrl+N) starts with an empty Body: build into it rather than beside it
        empty = [b for b in doc.findObjects("PartDesign::Body") if not b.Group or
                 all(o.TypeId == "App::Origin" for o in b.Group)]
        body = empty[0] if len(empty) == 1 else \
            doc.addObject("PartDesign::Body", "Body")
        body.Label = model["name"]
    sketches = {}
    for sk in model["sketches"]:
        sketches[sk["name"]] = make_sketch(body if body_mode else None, doc, sk, notes, sheet)
    doc.recompute()
    pending = {}                                     # sketches to attach to a face once it exists
    for sk in model["sketches"]:
        att = sk.get("attachment")
        if not att or not body_mode:
            continue
        if att.get("face"):
            pending[sk["name"]] = att
            continue
        feat = _origin_plane(body, att["plane"]["origin"], att["plane"]["axis"])
        if feat is None:
            notes.append(f"{sk['name']}: its support plane {att.get('name') or ''} is not an origin plane; left placed")
        else:
            _attach(doc, sketches[sk["name"]], (feat, [""]), notes)

    def attach_pending(names, built):
        """Attach to the newest built feature that has the support face (FreeCAD attaches to one feature's
        face; the face may be gone from later ones)."""
        for nm in names:
            att = pending.get(nm)
            if att is None:
                continue
            doc.recompute()
            for base in reversed(built):
                subs = _match_faces(base.Shape, [att["face"]])
                if subs:
                    if _attach(doc, sketches[nm], (base, subs[:1]), notes):
                        del pending[nm]
                    break
    objs, last = {}, None
    for ft in model["features"]:
        t, n = ft["type"], ft["name"]
        ex = ft.get("expressions") or {}
        o = None
        if body_mode:
            used = [ft.get("sketch"), ft.get("path"), ft.get("profile")] + list(ft.get("sections") or [])
            if t == "hole":
                used.append(_find_hole_sketch(ft, sketches))
            attach_pending([u for u in used if u], [x for x in objs.values() if hasattr(x, "Shape")])
        if not body_mode:
            if t == "boolean":
                cls = {"difference": "Part::Cut", "union": "Part::Fuse", "intersection": "Part::Common"}[ft["op"]]
                o = doc.addObject(cls, "Boolean")
                o.Base, o.Tool = objs[ft["first"]], objs[ft["second"]]
                for x in (o.Base, o.Tool):
                    if hasattr(x, "Visibility"):
                        x.Visibility = False
            else:
                o = _make_primitive(doc, None, ft, notes)
        elif t == "extrude":
            sk = sketches.get(ft["sketch"])
            if sk is None:
                notes.append(f"{n}: no sketch for its profile; stopped")
                break
            pocket = ft.get("op") == "difference"
            o = body.newObject("PartDesign::Pocket" if pocket else "PartDesign::Pad", "Pocket" if pocket else "Pad")
            o.Profile = sk
            normal = sk.Placement.Rotation.multVec(Z)
            d = vec(ft["direction"]).normalize()
            expect = normal * (-1 if pocket else 1)
            if abs(abs(d.dot(normal)) - 1) > 1e-9:
                o.UseCustomVector = True
                o.Direction = d
            elif d.dot(expect) < 0:
                o.Reversed = True
            first, second = ft["first"], ft.get("second", 0.0)
            intent = (ft.get("intent") or ["blind"])[0]
            up = ft.get("up_to")
            if up:
                doc.recompute()
                subs = _match_faces(last.Shape, [up["face"]]) if last is not None else []
                off = float(up.get("offset", 0.0))
                if intent == "up_to_next" and abs(off) < 1e-12:
                    o.Type = "UpToFirst"
                elif subs:
                    o.Type = "UpToFace"
                    o.UpToFace = (last, subs[:1])
                    o.Offset = off
                else:
                    o.Length = first - second
                    notes.append(f"{n}: the face of its up-to extent was not found; built to its length")
            elif intent == "through_all" and pocket:
                o.Type = "ThroughAll"
                if abs(first + second) < 1e-9:
                    o.SideType = "Symmetric"
            elif abs(first + second) < 1e-9 and first > 0:
                o.SideType = "Symmetric"
                o.Length = 2 * first
                _set_expr(o, "Length", ex.get("first"), notes, wrap="({}) * 2")
            elif abs(second) < 1e-12:
                o.Length = first
                _set_expr(o, "Length", ex.get("first"), notes)
            else:
                o.SideType = "Two sides"
                o.Length, o.Length2 = first, -second
                _set_expr(o, "Length", ex.get("first"), notes)
                e2 = ex.get("second")
                _set_expr(o, "Length2", e2[1] if e2 and e2[0] == "neg" else (["neg", e2] if e2 else None), notes)
            if ft.get("taper"):
                o.TaperAngle = math.degrees(ft["taper"])
            if intent == "through_all" and not pocket:
                notes.append(f"{n}: a pad through all became its length")
        elif t == "revolve":
            sk = sketches.get(ft["sketch"])
            groove = ft.get("op") == "difference"
            o = body.newObject("PartDesign::Groove" if groove else "PartDesign::Revolution",
                               "Groove" if groove else "Revolution")
            o.Profile = sk
            ref, rev = _axis_reference(body, sk, ft["axis"]["origin"], ft["axis"]["dir"], notes, n)
            o.ReferenceAxis = ref
            o.Reversed = rev
            first, second = ft["angle"], ft.get("second", 0.0)
            subs = []
            if ft.get("up_to") and last is not None:
                doc.recompute()
                subs = _match_faces(last.Shape, [ft["up_to"]["face"]])
            if subs:
                o.Type = "UpToFace"
                o.UpToFace = (last, subs[:1])
                o.Angle = math.degrees(first - second)
            elif abs(first + second) < 1e-9 and second:
                o.SideType = "Symmetric"
                o.Angle = math.degrees(2 * first)
                _set_expr(o, "Angle", ex.get("angle"), notes, angle=True, wrap="({}) * 2")
            elif second:
                o.Type = "TwoAngles"
                o.Angle, o.Angle2 = math.degrees(first), math.degrees(-second)
            else:
                o.Angle = math.degrees(first)
                _set_expr(o, "Angle", ex.get("angle"), notes, angle=True)
        elif t in ("fillet", "chamfer", "shell"):
            if last is None:
                notes.append(f"{n}: nothing to apply it to; stopped")
                break
            doc.recompute()
            shape = last.Shape
            if t == "shell":
                subs = _match_faces(shape, ft["faces"])
                want = len(ft["faces"])
            else:
                subs = _match_edges(shape, ft["edges"])
                want = len(ft["edges"])
            if len(subs) != want:
                notes.append(f"{n}: found {len(subs)} of the {want} picked {'faces' if t == 'shell' else 'edges'} "
                             "on the rebuilt solid")
            if not subs:
                notes.append(f"{n}: not created")
                break
            cls = {"fillet": "PartDesign::Fillet", "chamfer": "PartDesign::Chamfer",
                   "shell": "PartDesign::Thickness"}[t]
            o = body.newObject(cls, cls.split("::")[1])
            o.Base = (last, subs)
            if t == "fillet":
                o.Radius = ft["radius"]
                _set_expr(o, "Radius", ex.get("radius"), notes)
            elif t == "chamfer":
                o.ChamferType = {"single": "Equal distance", "double": "Two distances",
                                 "angle": "Distance and Angle"}[ft.get("kind", "single")]
                o.Size = ft["d1"]
                if ft.get("kind") == "double":
                    o.Size2 = ft["d2"]
                if ft.get("kind") == "angle":
                    o.Angle = math.degrees(ft["angle"])
                    o.FlipDirection = not ft.get("left", True)
                _set_expr(o, "Size", ex.get("d1"), notes)
            else:
                o.Value = abs(ft["thickness"])
                o.Reversed = ft["thickness"] < 0
                e = ex.get("thickness")
                _set_expr(o, "Value", e[1] if e and e[0] == "neg" else e, notes)
        elif t == "hole":
            if last is None:
                notes.append(f"{n}: nothing to drill; stopped")
                break
            o = _make_hole(doc, body, ft, sketches, notes)
        elif t == "pattern":
            srcs = [objs.get(x) for x in (ft.get("sources") or [ft["source"]])]
            trs = ft["transforms"]
            if None in srcs or not trs:
                notes.append(f"{n}: pattern source {ft.get('sources') or ft['source']} missing; stopped")
                break
            if ft.get("kind") == "multi":
                o = body.newObject("PartDesign::MultiTransform", "MultiTransform")
                o.Originals = srcs
                steps = []
                for st in ft["steps"]:
                    sub = doc.addObject(_transform_class(st["transforms"]), "Transformation")
                    _setup_transform(sub, body, st["transforms"], st["name"], notes)
                    sub.Label = st["name"]
                    steps.append(sub)
                o.Transformations = steps
            else:
                cls = _transform_class(trs)
                o = body.newObject(cls, cls.split("::")[1])
                o.Originals = srcs
                _setup_transform(o, body, trs, n, notes)
        elif t == "pipe":
            sk, path = sketches.get(ft["sketch"]), sketches.get(ft.get("path"))
            if sk is None or path is None:
                notes.append(f"{n}: its profile or path sketch is missing; stopped")
                break
            sub = ft.get("op") == "difference"
            o = body.newObject("PartDesign::SubtractivePipe" if sub else "PartDesign::AdditivePipe", "Pipe")
            o.Spine = (path, [f"Edge{i + 1}" for i in range(len(path.Shape.Edges))])
            o.Profile = sk
            o.Mode = "Standard"
        elif t == "explicit":
            o = _make_explicit(doc, body, ft, sketches, last, notes)
        elif t in ("box", "cylinder", "cone", "sphere", "torus"):
            o = _make_primitive(doc, body, ft, notes)
        else:
            notes.append(f"{n}: feature type {t} not built; stopped")
            break
        if o is None:
            break
        o.Label = n
        objs[n] = o
        last = o
        if body_mode and o.TypeId.startswith("PartDesign::"):
            body.Tip = o                             # newObject does not move the Tip onto a pattern
        doc.recompute()
        if hasattr(o, "isValid") and not o.isValid():
            notes.append(f"{n}: does not recompute ({o.getStatusString() if hasattr(o, 'getStatusString') else ''})")
    if body_mode:
        attach_pending(list(pending), [x for x in objs.values() if hasattr(x, "Shape")])
        for nm in pending:
            notes.append(f"{nm}: its support face was not found on the rebuilt solid; left placed")
    doc.recompute()
    main = body if body_mode else last
    return main, notes


def _make_explicit(doc, body, ft, sketches, last, notes):
    """Rebuild a hybrid step from what it records (Draft, Loft, Pipe), or stop."""
    kind, n, prm = ft.get("kind", ""), ft["name"], ft.get("params") or {}
    if kind == "Draft":
        if last is None:
            return None
        doc.recompute()
        subs = _match_faces(last.Shape, ft.get("faces") or [])
        if not subs:
            notes.append(f"{n}: its drafted faces were not found; stopped")
            return None
        o = body.newObject("PartDesign::Draft", "Draft")
        o.Base = (last, subs)
        nt = ft.get("neutral") or {}
        if nt.get("face"):
            ns = _match_faces(last.Shape, [nt["face"]])
            if ns:
                o.NeutralPlane = (last, ns[:1])
        elif nt.get("plane"):
            feat = _origin_plane(body, nt["plane"]["origin"], nt["plane"]["axis"])
            if feat is not None:
                o.NeutralPlane = (feat, [""])
        if ft.get("pull"):
            es = _match_edges(last.Shape, [ft["pull"]])
            if es:
                o.PullDirection = (last, es[:1])
        o.Angle = math.degrees(float(prm.get("angle", 0.0)))
        o.Reversed = bool(prm.get("reversed", False))
        return o
    if kind in ("AdditiveLoft", "SubtractiveLoft"):
        prof = sketches.get(ft.get("profile"))
        secs = [sketches.get(x) for x in ft.get("sections") or []]
        if prof is None or None in secs:
            notes.append(f"{n}: a loft section sketch is missing; stopped")
            return None
        o = body.newObject(f"PartDesign::{kind}", "Loft")
        o.Profile = prof
        o.Sections = secs
        o.Ruled, o.Closed = bool(prm.get("ruled", False)), bool(prm.get("closed", False))
        return o
    if kind in ("AdditivePipe", "SubtractivePipe"):
        prof, path = sketches.get(ft.get("profile")), sketches.get(ft.get("path"))
        if prof is None or path is None:
            notes.append(f"{n}: its profile or path sketch is missing; stopped")
            return None
        o = body.newObject(f"PartDesign::{kind}", "Pipe")
        o.Spine = (path, [f"Edge{i + 1}" for i in range(len(path.Shape.Edges))])
        o.Profile = prof
        for prop in ("mode", "transition"):
            if prm.get(prop):
                setattr(o, prop.capitalize(), str(prm[prop]).replace("_", " "))
        return o
    notes.append(f"{n} ({kind}): written as an explicit solid only; the history is rebuilt up to it")
    return None


def _axis_point(rot, t, ax):
    """A point p with p - R p = t (the fixed axis of a rotation about a line not through the origin)."""
    # least squares on the plane normal to the axis: iterate p = R p + t projected, a few fixed-point steps
    u = _perp(ax)
    w = ax.cross(u)
    m = [[1 - rot.multVec(u).dot(u), -rot.multVec(w).dot(u)], [-rot.multVec(u).dot(w), 1 - rot.multVec(w).dot(w)]]
    det = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    if abs(det) < 1e-12:
        return App.Vector()
    bu, bw = t.dot(u), t.dot(w)
    a = (bu * m[1][1] - m[0][1] * bw) / det
    b = (m[0][0] * bw - m[1][0] * bu) / det
    return u * a + w * b


def _make_primitive(doc, body, ft, notes):
    t = ft["type"]
    word = {"box": "Box", "cylinder": "Cylinder", "cone": "Cone", "sphere": "Sphere", "torus": "Torus"}[t]
    if body is not None:
        cls = ("PartDesign::Subtractive" if ft.get("op") == "difference" else "PartDesign::Additive") + word
        o = body.newObject(cls, word)
        o.MapMode = "Deactivated"
    else:
        o = doc.addObject(f"Part::{word}", word)
    pl = ft.get("placement") or {"origin": [0, 0, 0], "axis": [0, 0, 1], "x": [1, 0, 0]}
    o.Placement = _placement(pl)
    ex = ft.get("expressions") or {}
    props = PRIMITIVES[word][1]
    for prop, key in props.items():
        setattr(o, prop, ft[key])
        _set_expr(o, prop, ex.get(key), notes)
    if t == "cone":
        o.Radius1, o.Height = ft["radius"], ft["height"]
        o.Radius2 = max(ft["radius"] - ft["height"] * math.tan(ft["semi_angle"]), 0.0)
    return o


def compare_solids(a, b):
    """(volume of the symmetric difference, how it was found). When OpenCASCADE's Booleans fail on two
    coincident shapes (no common volume between solids of equal volume, as with lofted B-spline faces read
    back from STEP), the volumes, areas, bounding boxes and face areas are compared instead: equal, the
    difference is 0."""
    diff = a.cut(b).Volume + b.cut(a).Volume
    big = max(a.Volume, b.Volume, 1.0)
    if diff <= 1e-3 * big or a.common(b).Volume > 1e-9 * big:
        return diff, "symmetric difference"
    ba, bb = a.BoundBox, b.BoundBox
    box = max(abs(x - y) for x, y in zip((ba.XMin, ba.YMin, ba.ZMin, ba.XMax, ba.YMax, ba.ZMax),
                                         (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)))
    fa, fb = sorted(f.Area for f in a.Faces), sorted(f.Area for f in b.Faces)
    alike = abs(a.Volume - b.Volume) <= 1e-7 * big and abs(a.Area - b.Area) <= 1e-7 * max(a.Area, 1.0) and \
        box <= 1e-5 and len(fa) == len(fb) and all(abs(x - y) <= 1e-6 * max(x, 1.0) for x, y in zip(fa, fb))
    return (0.0 if alike else diff), "volume, area, bounding box and face areas (the Boolean comparison failed)"


def import_file(path, doc=None):
    """Rebuild the parametric models in a STEP file. Returns (objects, report text)."""
    doc = doc or App.ActiveDocument or App.newDocument()
    f = p21.read(path)
    models, notes = parametric.from_step(f)
    made = []
    lines = [path]
    if not models:
        import Import
        Import.insert(path, doc.Name)
        lines.append("No ISO 10303-55/108 data: the explicit B-rep was imported as it is.")
        return [], "\n".join(lines)
    for m in models:
        obj, more = model_to_document(m, doc)
        notes += more
        if obj is None:
            continue
        made.append(obj)
        lines.append(f"{obj.Label}: {len(m['parameters'])} parameter(s), {len(m['sketches'])} sketch(es), "
                     f"{len(m['features'])} feature(s)")
    if parametric.brep_representation(f) is not None and made and hasattr(made[0], "Shape"):
        try:
            explicit = Part.read(path)
            rebuilt = made[0].Shape
            diff, how = compare_solids(rebuilt, explicit)
            vol = max(explicit.Volume, 1e-12)
            lines.append(f"Rebuilt history against the explicit B-rep in the file: volumes {rebuilt.Volume:.4f} and "
                         f"{explicit.Volume:.4f} mm³, difference {diff:.6f} mm³ ({100 * diff / vol:.4f} %) by {how}")
        except Exception as err:
            lines.append(f"Comparison with the explicit B-rep failed: {err}")
    if notes:
        lines += ["", "Notes:"] + ["  " + n for n in notes]
    doc.recompute()
    return made, "\n".join(lines)

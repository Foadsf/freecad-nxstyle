# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parametric and procedural models in STEP: ISO 10303-55, -108 and -111 (no FreeCAD needed).

A model here is a plain dict (JSON-able) that parametric_fc.py fills from a FreeCAD document and builds
a FreeCAD document from:

  parameters   named values (Spreadsheet aliases): name, value, unit ("mm", "deg" or ""), description
  sketches     name, placement, 2D geometry (line, circle, arc, point; construction flag), Sketcher
               constraints (FreeCAD's type names and geometry/position indices), and the 3D faces of
               its closed profiles
  features     the history: extrude (Pad, Pocket), revolve (Revolution, Groove), fillet, chamfer, shell
               (Thickness), pattern (LinearPattern, PolarPattern), the CSG primitives box, cylinder,
               cone, sphere, torus, and boolean (Cut, Fuse, Common)
  expressions  per feature attribute or sketch constraint, an expression tree over the parameters

to_step(model) writes it as ISO 10303 entities; from_step(file) reads it back:

  ISO 10303-108 (with Cor.1 and Cor.2)
    a sketch          NEUTRAL_SKETCH_REPRESENTATION (2D, its current result) inside a
                      VARIATIONAL_REPRESENTATION that adds the constraints and parameters
                      (VARIATIONAL_CURRENT_REPRESENTATION_RELATIONSHIP, 6.3.4); lines and arcs are
                      TRIMMED_CURVEs, constraints apply to their basis curves and end points (annex F.2);
                      placed by REPOSITIONED_NEUTRAL_SKETCH and tied to the POSITIONED_SKETCH of each
                      profile face by IMPLICIT_EXPLICIT_POSITIONED_SKETCH_RELATIONSHIP (8.4.11-12)
    constraints       Coincident and PointOnObject -> INCIDENCE; Horizontal, Vertical, Parallel ->
                      PARALLEL (to the sketch axes for the first two); Perpendicular; Tangent; Equal ->
                      CURVE_LENGTH (lines) or RADIUS (circles), the undirected forms; Distance ->
                      CLGC_WITH_DIMENSION (a line's length) or PDGC_WITH_DIMENSION; DistanceX/Y ->
                      PDGC_WITH_DIMENSION to an auxiliary line through the anchor point, kept parallel
                      to the other axis and on the point; Radius and Diameter -> RGC_WITH_DIMENSION;
                      Angle -> AGC_WITH_DIMENSION; Symmetric (two points about a line) -> SYMMETRY;
                      Block -> FIXED_ELEMENT. Sketch axes and construction geometry are
                      AUXILIARY_GEOMETRIC_REPRESENTATION_ITEMs.
    parameters        UNBOUND_VARIATIONAL_PARAMETER per model parameter; a driven value gets a
                      BOUND_VARIATIONAL_PARAMETER bound by INSTANCE_ATTRIBUTE_REFERENCE to the attribute
                      it drives, and an EQUAL_PARAMETER_CONSTRAINT (plain reference) or a
                      FREE_FORM_ASSIGNMENT whose expression is ISO 13584-20 (annex F of Cor.1)
  ISO 10303-55        the history as a PROCEDURAL_SOLID_REPRESENTATION_SEQUENCE in a
                      PROCEDURAL_SHAPE_REPRESENTATION; picked edges and faces as
                      USER_SELECTED_SHAPE_ELEMENTS before the operation that uses them; a pattern as a
                      nested sequence; tied to the explicit B-rep by
                      EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP when there is one (5.4.1)
  ISO 10303-42/111    EXTRUDED_FACE_SOLID_WITH_TRIM_CONDITIONS (and _WITH_DRAFT_ANGLE), REVOLVED_FACE_SOLID
                      (_WITH_TRIM_CONDITIONS), BOOLEAN_RESULT, SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND,
                      SOLID_WITH_SINGLE/DOUBLE_OFFSET_CHAMFER, SOLID_WITH_ANGLE_BASED_CHAMFER, SHELLED_SOLID,
                      SOLID_REPLICA, BLOCK, RIGHT_CIRCULAR_CYLINDER/CONE, SPHERE, TORUS

Where Parts 55 and 108 contradict each other the choice is recorded here:
  * procedural_solid_representation_sequence WR1 wants SOLID_MODEL in its type list, and
    procedural_shape_representation_sequence WR1 wants every element to be a geometric or topological
    item, which USER_SELECTED_SHAPE_ELEMENTS is not; Part 55's own annex E writes both as simple
    instances. They are written as complex instances that satisfy the rules.
  * a procedural representation may only hold sequences (55, 4.3.3) while a variational wrapper must
    have the type list of its current result (108, 6.3.4 WR4); the parameters of the history therefore
    wrap a plain SHAPE_REPRESENTATION that holds the sequence.
  * a variational wrapper must have its current result's type list plus VARIATIONAL_REPRESENTATION
    (108, 6.3.4 WR4), but NEUTRAL_SKETCH_REPRESENTATION only admits points and curves as items (8.4.9),
    so a wrapper of that type could not hold a single constraint. The wrapper of a sketch is a
    SHAPE_REPRESENTATION + VARIATIONAL_REPRESENTATION; iso10303.rules() reports the WR4 gap as a warning.
  * angles in AGC_WITH_DIMENSION are 0-90 degrees and distances unsigned (108, 7.4.19); the sign and
    the branch are taken from the current geometry when reading (108, 5.2.3).
"""

import math

from . import p21

R = p21.Ref
E = p21.Enum
T = p21.Typed
U, D = p21.UNSET, p21.DERIVED
SCHEMAS = ("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF",)
TOOL = "NXStyle parametric STEP (ISO 10303-55/108/111)"
NUM = (int, float)


class StepError(ValueError):
    pass


# ------------------------------------------------------------------ small vector helpers
def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _add(a, b):
    return [x + y for x, y in zip(a, b)]


def _mul(a, k):
    return [x * k for x in a]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    return [x / n for x in a] if n > 1e-15 else list(a)


def _dist(a, b):
    return math.sqrt(_dot(_sub(a, b), _sub(a, b)))


# ------------------------------------------------------------------ expressions (ISO 13584-20)
# An expression tree is a nested list: ["num", 2.0], ["var", "L"], ["neg", e], [op, a, b] with op in
# + - * / ^, ["call", name, [args]] with name in FUNCS.
FUNCS = {"sin": "SIN_FUNCTION", "cos": "COS_FUNCTION", "tan": "TAN_FUNCTION", "asin": "ASIN_FUNCTION",
         "acos": "ACOS_FUNCTION", "atan": "ATAN_FUNCTION", "sqrt": "SQUARE_ROOT_FUNCTION",
         "abs": "ABS_FUNCTION", "exp": "EXP_FUNCTION", "log": "LOG_FUNCTION", "log10": "LOG10_FUNCTION",
         "min": "MINIMUM_FUNCTION", "max": "MAXIMUM_FUNCTION"}
OPS = {"+": "PLUS_EXPRESSION", "-": "MINUS_EXPRESSION", "*": "MULT_EXPRESSION", "/": "SLASH_EXPRESSION",
       "^": "POWER_EXPRESSION"}
_PREC = {"+": 1, "-": 1, "*": 2, "/": 2, "^": 3}


def expr_vars(e):
    if e[0] == "var":
        return {e[1]}
    if e[0] == "num":
        return set()
    if e[0] == "call":
        out = set()
        for a in e[2]:
            out |= expr_vars(a)
        return out
    out = set()
    for a in e[1:]:
        out |= expr_vars(a)
    return out


def expr_text(e, prec=0):
    """Infix text of an expression tree (FreeCAD's expression syntax, minus units)."""
    k = e[0]
    if k == "num":
        v = e[1]
        return repr(float(v)).rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    if k == "var":
        return e[1]
    if k == "neg":
        return "-" + expr_text(e[1], 4)
    if k == "call":
        return f"{e[1]}(" + "; ".join(expr_text(a) for a in e[2]) + ")"
    p = _PREC[k]
    s = f"{expr_text(e[1], p)} {k} {expr_text(e[2], p + (k != '^'))}"
    return f"({s})" if p < prec else s


def expr_eval(e, env):
    k = e[0]
    if k == "num":
        return float(e[1])
    if k == "var":
        return float(env[e[1]])
    if k == "neg":
        return -expr_eval(e[1], env)
    if k == "call":
        args = [expr_eval(a, env) for a in e[2]]
        f = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
             "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
             "acos": math.acos}.get(e[1])
        if e[1] == "atan":
            return math.atan2(*args) if len(args) == 2 else math.atan(args[0])
        return f(*args)
    a, b = expr_eval(e[1], env), expr_eval(e[2], env)
    return {"+": a + b, "-": a - b, "*": a * b, "/": a / b, "^": a ** b}[k]


# ------------------------------------------------------------------ writing
class _Writer:
    def __init__(self, f, ctx3=None, ctx2=None):
        self.f = f
        self.ctx3, self.ctx2 = ctx3, ctx2
        self.cache = {}
        self.notes = []
        self.reals = None

    def add(self, name, *params):
        return self.f.add(name, *params)

    def cx(self, *records):
        return self.f.add_complex(records)

    # geometry
    def point(self, p):
        key = ("pt", tuple(round(c, 9) for c in p))
        if key not in self.cache:
            self.cache[key] = self.add("CARTESIAN_POINT", "", [float(c) for c in p])
        return self.cache[key]

    def fresh_point(self, p, name=""):
        return self.add("CARTESIAN_POINT", name, [float(c) for c in p])

    def direction(self, d):
        d = _norm(d)
        key = ("dir", tuple(round(c, 12) for c in d))
        if key not in self.cache:
            self.cache[key] = self.add("DIRECTION", "", [float(c) for c in d])
        return self.cache[key]

    def a2p3(self, origin, axis, x):
        return self.add("AXIS2_PLACEMENT_3D", "", self.point(origin), self.direction(axis), self.direction(x))

    def placement(self, pl):
        return self.a2p3(pl["origin"], pl["axis"], pl["x"])

    def a1p(self, origin, axis):
        return self.add("AXIS1_PLACEMENT", "", self.point(origin), self.direction(axis))

    def contexts(self):
        if self.ctx3 is None:
            mm = self.cx(("LENGTH_UNIT", []), ("NAMED_UNIT", [D]), ("SI_UNIT", [E("MILLI"), E("METRE")]))
            rad = self.cx(("NAMED_UNIT", [D]), ("PLANE_ANGLE_UNIT", []), ("SI_UNIT", [U, E("RADIAN")]))
            sr = self.cx(("NAMED_UNIT", [D]), ("SI_UNIT", [U, E("STERADIAN")]), ("SOLID_ANGLE_UNIT", []))
            unc = self.add("UNCERTAINTY_MEASURE_WITH_UNIT", T("LENGTH_MEASURE", 1e-7), mm, "distance_accuracy_value",
                           "confusion accuracy")
            for dim in (3, 2):
                c = self.cx(("GEOMETRIC_REPRESENTATION_CONTEXT", [dim]),
                            ("GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT", [[unc]]),
                            ("GLOBAL_UNIT_ASSIGNED_CONTEXT", [[mm, rad, sr]]),
                            ("REPRESENTATION_CONTEXT", [f"{dim}D", "NXStyle"]))
                if dim == 3:
                    self.ctx3 = c
                else:
                    self.ctx2 = c
        elif self.ctx2 is None:
            self.ctx2 = self.add("GEOMETRIC_REPRESENTATION_CONTEXT", "2D", "sketch", 2)

    def space(self):
        if self.reals is None:
            self.reals = self.add("ELEMENTARY_SPACE", E("ES_REALS"))
        return self.reals

    # topology snapshots (picked edges and faces, profile faces), 3D
    def curve3(self, c):
        t = c["type"]
        if t == "line":
            return self.add("LINE", "", self.point(c["origin"]),
                            self.add("VECTOR", "", self.direction(c["dir"]), 1.0))
        if t == "circle":
            return self.add("CIRCLE", "", self.a2p3(c["center"], c["axis"], c["x"]), float(c["r"]))
        if t == "ellipse":
            return self.add("ELLIPSE", "", self.a2p3(c["center"], c["axis"], c["x"]), float(c["r1"]),
                            float(c["r2"]))
        if t == "bspline":
            return self.add("B_SPLINE_CURVE_WITH_KNOTS", "", int(c["degree"]), [self.point(p) for p in c["poles"]],
                            E("UNSPECIFIED"), bool(c.get("closed", False)), False, [int(m) for m in c["mults"]],
                            [float(k) for k in c["knots"]], E("UNSPECIFIED"))
        raise StepError(f"curve type {t!r} cannot be written")

    def surface(self, s):
        t = s["type"]
        pos = self.a2p3(s["origin"], s["axis"], s["x"])
        if t == "plane":
            return self.add("PLANE", "", pos)
        if t == "cylinder":
            return self.add("CYLINDRICAL_SURFACE", "", pos, float(s["r"]))
        if t == "cone":
            return self.add("CONICAL_SURFACE", "", pos, float(s["r"]), float(s["semi_angle"]))
        if t == "sphere":
            return self.add("SPHERICAL_SURFACE", "", pos, float(s["r"]))
        if t == "torus":
            return self.add("TOROIDAL_SURFACE", "", pos, float(s["R"]), float(s["r"]))
        raise StepError(f"surface type {t!r} cannot be written")

    def vertex(self, p, verts):
        key = tuple(round(c, 7) for c in p)
        if key not in verts:
            verts[key] = self.add("VERTEX_POINT", "", self.point(p))
        return verts[key]

    def edge(self, e, verts=None, name=""):
        verts = {} if verts is None else verts
        v1, v2 = self.vertex(e["p1"], verts), self.vertex(e["p2"], verts)
        return self.add("EDGE_CURVE", name, v1, v2, self.curve3(e["curve"]), True)

    def face(self, fc, name=""):
        verts, bounds = {}, []
        for k, loop in enumerate(fc["loops"]):
            oes = [self.add("ORIENTED_EDGE", "", D, D, self.edge(e, verts), True) for e in loop]
            el = self.add("EDGE_LOOP", "", oes)
            bounds.append(self.add("FACE_OUTER_BOUND" if k == 0 else "FACE_BOUND", "", el, True))
        return self.add("FACE_SURFACE", name, bounds, self.surface(fc["surface"]), bool(fc.get("same_sense", True)))

    def selected(self, name, items):
        """USER_SELECTED_SHAPE_ELEMENTS as a complex instance that is a geometric item (55, 5.4.4 WR1)."""
        return self.cx(("GEOMETRIC_REPRESENTATION_ITEM", []), ("REPRESENTATION_ITEM", [name]),
                       ("USER_SELECTED_ELEMENTS", [items]), ("USER_SELECTED_SHAPE_ELEMENTS", []))

    def sequence(self, name, elements, suppressed=(), rationale=""):
        return self.cx(("GEOMETRIC_REPRESENTATION_ITEM", []),
                       ("PROCEDURAL_REPRESENTATION_SEQUENCE", [list(elements), list(suppressed), rationale]),
                       ("PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE", []),
                       ("PROCEDURAL_SOLID_REPRESENTATION_SEQUENCE", []),
                       ("REPRESENTATION_ITEM", [name]), ("SOLID_MODEL", []))


class _Params:
    """Unbound parameters and the bindings (bound parameter + assignment) of one variational wrapper."""

    def __init__(self, w, params):
        self.w, self.params = w, params
        self.unbound = {}

    def unbound_param(self, name):
        if name not in self.unbound:
            p = self.params[name]
            desc = (f"[{p['unit']}] " if p.get("unit") else "") + (p.get("description") or "")
            v = math.radians(p["value"]) if p.get("unit") == "deg" else float(p["value"])
            ref = self.w.add("UNBOUND_VARIATIONAL_PARAMETER", name, self.w.space(), name, desc or U, v)
            sem = self.w.add("UNBOUND_VARIATIONAL_PARAMETER_SEMANTICS")
            self.w.add("UNBOUND_PARAMETER_ENVIRONMENT", ref, sem)
            self.unbound[name] = ref
        return self.unbound[name]

    def expression(self, e):
        """ISO 13584-20 instances for an expression tree (numbers already in mm and radians)."""
        k = e[0]
        if k == "num":
            return self.w.add("REAL_LITERAL", float(e[1]))
        if k == "var":
            return self.unbound_param(e[1])
        if k == "neg":
            return self.w.add("MINUS_FUNCTION", self.expression(e[1]))
        if k == "call":
            args = [self.expression(a) for a in e[2]]
            name = FUNCS[e[1]]
            if e[1] == "atan" and len(args) == 2:
                return self.w.add("ATAN_FUNCTION", args)
            if e[1] in ("min", "max"):
                return self.w.add(name, args)
            return self.w.add(name, args[0])
        return self.w.add(OPS[k], [self.expression(e[1]), self.expression(e[2])])

    def bind(self, name, owner, attribute, expr):
        """Bound parameter on owner.attribute driven by expr (over the model parameters); returns the
        variational items it adds. An expression without parameters binds nothing."""
        w = self.w
        if not expr_vars(expr):
            return []
        bp = w.add("BOUND_VARIATIONAL_PARAMETER", name, w.space(), name, U, D)
        iar = w.add("INSTANCE_ATTRIBUTE_REFERENCE", attribute, owner)
        w.add("BOUND_PARAMETER_ENVIRONMENT", bp, iar)
        if expr[0] == "var":
            con = w.add("EQUAL_PARAMETER_CONSTRAINT", name, U, [bp], [self.unbound_param(expr[1])])
        else:
            refs = [self.unbound_param(v) for v in sorted(expr_vars(expr))]
            con = w.add("FREE_FORM_ASSIGNMENT", name, U, [bp], refs, self.expression(expr))
        return [bp, con]

    def items(self):
        return list(self.unbound.values())


# sketch geometry and constraints
def _sketch_point(geo, g, pos, refs):
    """Ref of the point (geometry g, FreeCAD position pos: 1 start, 2 end, 3 centre) in a written sketch."""
    if g == -1 and pos == 1:
        return refs["origin"]()
    r = refs["geo"].get(g)
    if r is None:
        return None
    if pos == 1:
        return r.get("p1") or r.get("p")
    if pos == 2:
        return r.get("p2")
    if pos == 3:
        return r.get("c")
    return None


def _sketch_curve(g, refs, bounded=False):
    if g == -1:
        return refs["xaxis"]()
    if g == -2:
        return refs["yaxis"]()
    r = refs["geo"].get(g)
    if r is None:
        return None
    return r.get("item") if bounded else r.get("basis")


def _write_sketch(w, sk, params):
    """A sketch -> (variational representation, current result, repositioned sketch, positioned sketches)."""
    w.contexts()
    items, var_items, geo = [], [], {}
    lazy = {}

    def aux_line(key, p, d):
        if key not in lazy:
            pt = w.fresh_point(p)
            vec = w.add("VECTOR", "", w.add("DIRECTION", "", [float(d[0]), float(d[1])]), 1.0)
            lazy[key] = w.cx(("AUXILIARY_GEOMETRIC_REPRESENTATION_ITEM", []), ("CURVE", []),
                             ("GEOMETRIC_REPRESENTATION_ITEM", []), ("LINE", [pt, vec]),
                             ("REPRESENTATION_ITEM", [f"{sk['name']}.{key}"]),
                             ("VARIATIONAL_REPRESENTATION_ITEM", []))
            var_items.append(lazy[key])
        return lazy[key]

    def origin():
        if "origin" not in lazy:
            lazy["origin"] = w.cx(("AUXILIARY_GEOMETRIC_REPRESENTATION_ITEM", []),
                                  ("CARTESIAN_POINT", [[0.0, 0.0]]), ("GEOMETRIC_REPRESENTATION_ITEM", []),
                                  ("POINT", []), ("REPRESENTATION_ITEM", [f"{sk['name']}.origin"]),
                                  ("VARIATIONAL_REPRESENTATION_ITEM", []))
            var_items.append(lazy["origin"])
        return lazy["origin"]

    refs = {"geo": geo, "origin": origin, "xaxis": lambda: aux_line("x_axis", (0, 0), (1, 0)),
            "yaxis": lambda: aux_line("y_axis", (0, 0), (0, 1))}
    for i, g in enumerate(sk["geometry"]):
        nm = f"{sk['name']}.g{i}"
        t = g["type"]
        if t not in ("point", "line", "circle", "arc"):
            continue                                  # noted by the caller; its constraints are skipped
        if t == "point":
            p = w.fresh_point(g["p"], nm)
            geo[i] = {"p": p, "item": p, "basis": p}
            items.append(p)
            continue
        if t == "line":
            p1, p2 = w.fresh_point(g["p1"]), w.fresh_point(g["p2"])
            d = _sub(g["p2"], g["p1"])
            ln = math.hypot(*d) or 1.0
            basis = w.add("LINE", "", p1, w.add("VECTOR", "", w.add("DIRECTION", "", [d[0] / ln, d[1] / ln]), ln))
            rec = {"p1": p1, "p2": p2, "basis": basis}
        else:
            c = w.fresh_point(g["c"])
            a2 = w.add("AXIS2_PLACEMENT_2D", "", c, w.add("DIRECTION", "", [1.0, 0.0]))
            basis = w.add("CIRCLE", "" if t == "arc" else nm, a2, float(g["r"]))
            rec = {"c": c, "basis": basis}
            if t == "circle":
                rec["item"] = basis
            else:
                rec["p1"], rec["p2"] = w.fresh_point(g["p1"]), w.fresh_point(g["p2"])
        if "item" not in rec:
            trim = (basis, [rec["p1"]], [rec["p2"]], True, E("CARTESIAN"))
            if g.get("construction"):
                rec["item"] = w.cx(("AUXILIARY_GEOMETRIC_REPRESENTATION_ITEM", []), ("BOUNDED_CURVE", []),
                                   ("CURVE", []), ("GEOMETRIC_REPRESENTATION_ITEM", []),
                                   ("REPRESENTATION_ITEM", [nm]), ("TRIMMED_CURVE", list(trim)),
                                   ("VARIATIONAL_REPRESENTATION_ITEM", []))
            else:
                rec["item"] = w.add("TRIMMED_CURVE", nm, *trim)
        elif g.get("construction"):                    # a construction circle: variational, not geometry
            w.notes.append(f"{sk['name']}: construction circle g{i} written as ordinary geometry")
        geo[i] = rec
        (var_items if g.get("construction") and t != "circle" else items).append(rec["item"])

    P = _Params(w, params)
    named = {}
    for ci, c in enumerate(sk["constraints"]):
        made = _write_constraint(w, sk, ci, c, refs, var_items, aux_line)
        if made is None:
            continue
        cref, attribute = made
        expr = c.get("expression")
        if expr and attribute:
            var_items += P.bind(c.get("name") or f"{sk['name']}.Constraints.{ci}", cref, attribute, expr)
        named[ci] = cref
    var_items += P.items()
    ctx = w.ctx2
    cur = w.add("NEUTRAL_SKETCH_REPRESENTATION", sk["name"], items, ctx, E("CURVES"))
    # The wrapper is not itself a NEUTRAL_SKETCH_REPRESENTATION: that entity's items may only be points
    # and curves (8.4.9), so it could not hold the constraints; 6.3.4 WR4 cannot be met at the same time.
    var = w.cx(("REPRESENTATION", [sk["name"], items + var_items, ctx]),
               ("SHAPE_REPRESENTATION", []), ("VARIATIONAL_REPRESENTATION", []))
    w.add("VARIATIONAL_CURRENT_REPRESENTATION_RELATIONSHIP", sk["name"], U, var, cur, cur)
    origin2 = w.add("AXIS2_PLACEMENT_2D", "", w.fresh_point([0.0, 0.0]), w.add("DIRECTION", "", [1.0, 0.0]))
    rmap = w.add("REPRESENTATION_MAP", origin2, cur)
    rep = w.add("REPOSITIONED_NEUTRAL_SKETCH", sk["name"], rmap, w.placement(sk["placement"]))
    positioned = []
    for k, fc in enumerate(sk.get("faces") or []):
        face = w.face(fc, f"{sk['name']}.face{k}")
        ps = w.add("POSITIONED_SKETCH", f"{sk['name']}.face{k}", face, [])
        w.add("IMPLICIT_EXPLICIT_POSITIONED_SKETCH_RELATIONSHIP", sk["name"], U, rep, ps)
        positioned.append((face, ps))
    return {"var": var, "current": cur, "repositioned": rep, "faces": positioned}


DIM_ATTR = {"PDGC_WITH_DIMENSION": "DISTANCE_VALUE", "CLGC_WITH_DIMENSION": "LENGTH_VALUE",
            "RGC_WITH_DIMENSION": "RADIUS_VALUE", "AGC_WITH_DIMENSION": "ANGLE_VALUE"}


def _write_constraint(w, sk, ci, c, refs, var_items, aux_line):
    """One Sketcher constraint -> (ref of the main constraint instance, attribute it carries a value in)."""
    t = c["type"]
    nm = c.get("name") or f"{sk['name']}.c{ci}"
    a, ap, b, bp, cc = (c.get("first", -2000), c.get("first_pos", 0), c.get("second", -2000),
                        c.get("second_pos", 0), c.get("third", -2000))
    val = c.get("value")
    if not c.get("driving", True):
        w.notes.append(f"{sk['name']}: reference (non-driving) constraint {nm} not written")
        return None

    def done(name, *params):
        r = w.add(name, nm, t, *params)
        var_items.append(r)
        return r, (f"EXPLICIT_GEOMETRIC_CONSTRAINT_SCHEMA.{name}.{DIM_ATTR[name]}" if name in DIM_ATTR else None)

    pt = lambda g, p: _sketch_point(sk["geometry"], g, p, refs)   # noqa: E731
    cv = lambda g, bounded=False: _sketch_curve(g, refs, bounded)  # noqa: E731
    skip = None
    if t == "Coincident":
        pa, pb = pt(a, ap), pt(b, bp)
        if pa and pb:
            return done("INCIDENCE_GEOMETRIC_CONSTRAINT", [pa], [pb], [])
    elif t == "PointOnObject":
        pa, cb = pt(a, ap), cv(b)
        if pa and cb:
            return done("INCIDENCE_GEOMETRIC_CONSTRAINT", [pa], [cb], [])
    elif t in ("Horizontal", "Vertical"):
        if b == -2000:
            la = cv(a)
            if la:
                return done("PARALLEL_GEOMETRIC_CONSTRAINT", [la], [cv(-1 if t == "Horizontal" else -2)])
        skip = "between two points"
    elif t in ("Parallel", "Perpendicular"):
        la, lb = cv(a), cv(b)
        if la and lb:
            r = done(f"{t.upper()}_GEOMETRIC_CONSTRAINT", [la], [lb])
            if ap and bp:                          # perpendicular at end points: plus the incidence
                w2 = w.add("INCIDENCE_GEOMETRIC_CONSTRAINT", nm + ".endpoints", t, [pt(a, ap)], [pt(b, bp)], [])
                var_items.append(w2)
            return r
    elif t == "Tangent":
        la, lb = cv(a), cv(b)
        if la and lb:
            r = done("TANGENT_GEOMETRIC_CONSTRAINT", [la], [lb], [], E("POINT_CONTACT"))
            if ap and bp:
                w2 = w.add("INCIDENCE_GEOMETRIC_CONSTRAINT", nm + ".endpoints", t, [pt(a, ap)], [pt(b, bp)], [])
                var_items.append(w2)
            return r
    elif t == "Equal":
        ga, gb = sk["geometry"][a]["type"] if a >= 0 else "", sk["geometry"][b]["type"] if b >= 0 else ""
        if ga == gb == "line":
            return done("CURVE_LENGTH_GEOMETRIC_CONSTRAINT", [cv(a, True), cv(b, True)], [])
        if ga in ("circle", "arc") and gb in ("circle", "arc"):
            return done("RADIUS_GEOMETRIC_CONSTRAINT", [cv(a), cv(b)], [])
        skip = f"between {ga} and {gb}"
    elif t == "Distance":
        if b == -2000 and a >= 0 and sk["geometry"][a]["type"] == "line":
            return done("CLGC_WITH_DIMENSION", [cv(a, True)], [], abs(val))
        if ap and b != -2000 and bp:
            return done("PDGC_WITH_DIMENSION", [pt(a, ap)], [pt(b, bp)], abs(val))
        if ap and b != -2000 and not bp:
            return done("PDGC_WITH_DIMENSION", [pt(a, ap)], [cv(b)], abs(val))
        skip = "between these elements"
    elif t in ("DistanceX", "DistanceY"):
        # the distance of a point from a line through the anchor point, parallel to the other axis
        other = -2 if t == "DistanceX" else -1
        own = b == -2000 and a >= 0 and sk["geometry"][a]["type"] == "line" and not ap
        if b == -2000 and not own:                 # a point's coordinate: from the sketch axis
            target = pt(a, ap)
            if target:
                return done("PDGC_WITH_DIMENSION", [target], [cv(other)], abs(val))
        else:
            (ag, apos), target = ((a, 1), pt(a, 2)) if own else ((a, ap), pt(b, bp))
            anchor = pt(ag, apos)
            if anchor and target:
                ref_line = aux_line(f"c{ci}_ref", _point_of(sk, ag, apos), (0, 1) if t == "DistanceX" else (1, 0))
                for name, params in (("INCIDENCE_GEOMETRIC_CONSTRAINT", ([anchor], [ref_line], [])),
                                     ("PARALLEL_GEOMETRIC_CONSTRAINT", ([ref_line], [cv(other)]))):
                    var_items.append(w.add(name, f"{nm}.ref", t, *params))
                return done("PDGC_WITH_DIMENSION", [target], [ref_line], abs(val))
    elif t in ("Radius", "Diameter"):
        ca = cv(a)
        if ca:
            return done("RGC_WITH_DIMENSION", [ca], [], abs(val) / (2.0 if t == "Diameter" else 1.0))
    elif t == "Angle":
        la, lb = cv(a), cv(b) if b != -2000 else cv(-1)
        if la and lb:
            ang = abs(val) % math.pi
            ang = min(ang, math.pi - ang)
            return done("AGC_WITH_DIMENSION", [la], [lb], ang)
    elif t == "Symmetric":
        pa, pb, mirror = pt(a, ap), pt(b, bp), cv(cc)
        if c.get("third_pos", 0) == 0 and pa and pb and mirror:
            return done("SYMMETRY_GEOMETRIC_CONSTRAINT", [pa, pb], [], mirror)
        skip = "about a point"
    elif t == "Block":
        it = cv(a, True)
        if it:
            return done("FIXED_ELEMENT_GEOMETRIC_CONSTRAINT", [it], [])
    else:
        skip = "(no ISO 10303-108 equivalent mapped)"
    w.notes.append(f"{sk['name']}: {t} constraint {nm} {skip or 'refers to geometry that is not written'}; "
                   "not written")
    return None


def _point_of(sk, g, pos):
    if g == -1:
        return [0.0, 0.0]
    geo = sk["geometry"][g]
    if pos == 1:
        return geo.get("p1") or geo.get("p")
    if pos == 2:
        return geo.get("p2")
    return geo.get("c")


# features
SOLID_ATTR = {"extrude": "SOLID_SHAPE_ELEMENT_SCHEMA.EXTRUDED_FACE_SOLID_WITH_TRIM_CONDITIONS",
              "revolve": "GEOMETRIC_MODEL_SCHEMA.REVOLVED_FACE_SOLID"}
FEATURE_ATTR = {   # model attribute -> STEP attribute of the instance that carries it
    ("extrude", "first"): "SOLID_SHAPE_ELEMENT_SCHEMA.EXTRUDED_FACE_SOLID_WITH_TRIM_CONDITIONS.FIRST_TRIM_CONDITION",
    ("extrude", "second"): "SOLID_SHAPE_ELEMENT_SCHEMA.EXTRUDED_FACE_SOLID_WITH_TRIM_CONDITIONS.SECOND_TRIM_CONDITION",
    ("extrude", "taper"): "SOLID_SHAPE_ELEMENT_SCHEMA.EXTRUDED_FACE_SOLID_WITH_DRAFT_ANGLE.DRAFT_ANGLE",
    ("revolve", "angle"): "GEOMETRIC_MODEL_SCHEMA.REVOLVED_FACE_SOLID.ANGLE",
    ("fillet", "radius"): "SOLID_SHAPE_ELEMENT_SCHEMA.SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND.RADIUS",
    ("chamfer", "d1"): "SOLID_SHAPE_ELEMENT_SCHEMA.SOLID_WITH_SINGLE_OFFSET_CHAMFER.OFFSET_DISTANCE",
    ("shell", "thickness"): "SOLID_SHAPE_ELEMENT_SCHEMA.SHELLED_SOLID.THICKNESS",
    ("box", "x"): "GEOMETRIC_MODEL_SCHEMA.BLOCK.X", ("box", "y"): "GEOMETRIC_MODEL_SCHEMA.BLOCK.Y",
    ("box", "z"): "GEOMETRIC_MODEL_SCHEMA.BLOCK.Z",
    ("cylinder", "height"): "GEOMETRIC_MODEL_SCHEMA.RIGHT_CIRCULAR_CYLINDER.HEIGHT",
    ("cylinder", "radius"): "GEOMETRIC_MODEL_SCHEMA.RIGHT_CIRCULAR_CYLINDER.RADIUS",
    ("cone", "height"): "GEOMETRIC_MODEL_SCHEMA.RIGHT_CIRCULAR_CONE.HEIGHT",
    ("cone", "radius"): "GEOMETRIC_MODEL_SCHEMA.RIGHT_CIRCULAR_CONE.RADIUS",
    ("sphere", "radius"): "GEOMETRIC_MODEL_SCHEMA.SPHERE.RADIUS",
    ("torus", "major"): "GEOMETRIC_MODEL_SCHEMA.TORUS.MAJOR_RADIUS",
    ("torus", "minor"): "GEOMETRIC_MODEL_SCHEMA.TORUS.MINOR_RADIUS",
}
BOOL_OP = {"union": "UNION", "difference": "DIFFERENCE", "intersection": "INTERSECTION"}
INTENTS = ("blind", "through_all", "up_to_next", "offset", "unspecified")


def _write_tool(w, ft, sketches):
    """The solid an extrude or revolve feature adds or removes (several profile faces are united)."""
    sk = sketches[ft["sketch"]]
    if not sk["faces"]:
        raise StepError(f"{ft['name']}: sketch {ft['sketch']} has no closed profile")
    tools = []
    for face, _ps in sk["faces"]:
        if ft["type"] == "extrude":
            first, second = float(ft["first"]), float(ft.get("second", 0.0))
            depth = max(abs(first - second), 1e-9)
            intents = [E(i.upper()) for i in ft.get("intent", ("blind", "blind"))]
            common = [ft["name"], face, w.direction(ft["direction"]), depth, T("LENGTH_MEASURE", first),
                      T("LENGTH_MEASURE", second), intents[0], intents[1], 0.0, 0.0]
            if ft.get("taper"):
                tools.append(w.add("EXTRUDED_FACE_SOLID_WITH_DRAFT_ANGLE", *common, float(ft["taper"])))
            else:
                tools.append(w.add("EXTRUDED_FACE_SOLID_WITH_TRIM_CONDITIONS", *common))
        else:
            axis = w.a1p(ft["axis"]["origin"], ft["axis"]["dir"])
            first, second = float(ft["angle"]), float(ft.get("second", 0.0))
            if second:
                tools.append(w.add("REVOLVED_FACE_SOLID_WITH_TRIM_CONDITIONS", ft["name"], face, axis,
                                   abs(first - second), T("PLANE_ANGLE_MEASURE", first),
                                   T("PLANE_ANGLE_MEASURE", second)))
            else:
                tools.append(w.add("REVOLVED_FACE_SOLID", ft["name"], face, axis, first))
    tool = tools[0]
    for k, t in enumerate(tools[1:], 2):
        tool = w.add("BOOLEAN_RESULT", f"{ft['name']}.profiles{k}", E("UNION"), tool, t)
    return tool, tools


def _write_primitive(w, ft):
    t, n = ft["type"], ft["name"]
    pl = ft.get("placement") or {"origin": [0, 0, 0], "axis": [0, 0, 1], "x": [1, 0, 0]}
    if t == "box":
        return w.add("BLOCK", n, w.placement(pl), float(ft["x"]), float(ft["y"]), float(ft["z"]))
    if t == "cylinder":
        return w.add("RIGHT_CIRCULAR_CYLINDER", n, w.a1p(pl["origin"], pl["axis"]), float(ft["height"]),
                     float(ft["radius"]))
    if t == "cone":
        return w.add("RIGHT_CIRCULAR_CONE", n, w.a1p(pl["origin"], pl["axis"]), float(ft["height"]),
                     float(ft["radius"]), float(ft["semi_angle"]))
    if t == "sphere":
        return w.add("SPHERE", n, float(ft["radius"]), w.point(pl["origin"]))
    if t == "torus":
        return w.add("TORUS", n, w.a1p(pl["origin"], pl["axis"]), float(ft["major"]), float(ft["minor"]))
    raise StepError(f"{n}: primitive {t!r}")


def _transform(w, tr, name):
    """A rigid motion {matrix: 3x3 rows, translation} as CARTESIAN_TRANSFORMATION_OPERATOR_3D."""
    m = tr["matrix"]
    cols = [[m[0][k], m[1][k], m[2][k]] for k in range(3)]
    return w.add("CARTESIAN_TRANSFORMATION_OPERATOR_3D", name, name, U, w.direction(cols[0]),
                 w.direction(cols[1]), w.point(tr["translation"]), 1.0, w.direction(cols[2]))


def to_step(model, f=None, brep=None, sketch_commands=False):
    """Write a model into a p21.File (a new one unless f is given).

    brep: (representation ref, context ref) of an explicit B-rep already in f that the procedural model
    describes; the 3D items then use that context, and EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP
    ties the two. sketch_commands also writes each sketch as ISO 10303-112 commands, paired with its
    explicit form; no AP242 edition includes Part 112, so this is for exchanges that agree on it.
    Returns (file, notes).
    """
    new = f is None
    if new:
        f = p21.File(SCHEMAS, description=(f"{model.get('name', 'model')}: parametric model",),
                     name=model.get("name", "model"), preprocessor=TOOL, system="FreeCAD")
    w = _Writer(f, ctx3=brep[1] if brep else None)
    w.contexts()
    params = {p["name"]: p for p in model.get("parameters", [])}
    sketches, sk_refs = {}, []
    for sk in model.get("sketches", []):
        sketches[sk["name"]] = _write_sketch(w, sk, params)
        sk_refs.append(sketches[sk["name"]]["repositioned"])
        sk_refs += [ps for _f, ps in sketches[sk["name"]]["faces"]]
        if sketch_commands:
            from . import procedural_sketch
            if procedural_sketch.write(w, sk, w.ctx2, explicit=sketches[sk["name"]]["current"]) is not None:
                w.notes.append(f"{sk['name']}: also written as ISO 10303-112 commands, which AP242's schema "
                               "does not include")

    solids, tools, elements = {}, {}, []
    bindings = []                                   # (feature, attribute name, owner ref, expr)
    prev = None
    for ft in model.get("features", []):
        t, n = ft["type"], ft["name"]
        exprs = ft.get("expressions") or {}
        if t in ("extrude", "revolve"):
            tool, parts = _write_tool(w, ft, sketches)
            tools[n] = tool
            op = ft.get("op")
            base = solids.get(ft.get("base")) if ft.get("base") else prev
            if op and base is not None:
                res = w.add("BOOLEAN_RESULT", n + ".result", E(BOOL_OP[op]), base, tool)
                elements.append(res)
            else:
                res = tool
                elements.append(tool)
            for attr, e in exprs.items():
                for k, part in enumerate(parts):
                    bindings.append((ft, attr, part, e, k))
        elif t in ("fillet", "chamfer"):
            base = solids.get(ft.get("base")) if ft.get("base") else prev
            edges = [w.edge(e, name=f"{n}.edge{k}") for k, e in enumerate(ft["edges"])]
            elements.append(w.selected(n + ".edges", edges))
            if t == "fillet":
                res = w.add("SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND", n, "Fillet", base, edges, float(ft["radius"]))
            elif ft.get("kind") == "double":
                res = w.add("SOLID_WITH_DOUBLE_OFFSET_CHAMFER", n, "Chamfer", base, edges, float(ft["d1"]),
                            float(ft["d2"]))
            elif ft.get("kind") == "angle":
                res = w.add("SOLID_WITH_ANGLE_BASED_CHAMFER", n, "Chamfer", base, edges, float(ft["d1"]),
                            bool(ft.get("left", True)), float(ft["angle"]))
            else:
                res = w.add("SOLID_WITH_SINGLE_OFFSET_CHAMFER", n, "Chamfer", base, edges, float(ft["d1"]))
            elements.append(res)
            for attr, e in exprs.items():
                bindings.append((ft, attr, res, e, 0))
        elif t == "shell":
            base = solids.get(ft.get("base")) if ft.get("base") else prev
            faces = [w.face(fc, f"{n}.face{k}") for k, fc in enumerate(ft["faces"])]
            elements.append(w.selected(n + ".faces", faces))
            res = w.add("SHELLED_SOLID", n, "Thickness", base, faces, float(ft["thickness"]))
            elements.append(res)
            for attr, e in exprs.items():
                bindings.append((ft, attr, res, e, 0))
        elif t == "pattern":
            base = solids.get(ft.get("base")) if ft.get("base") else prev
            src = model_feature(model, ft["source"])
            tool = tools.get(ft["source"])
            if tool is None or src is None:
                raise StepError(f"{n}: pattern of {ft['source']}, which has no tool solid")
            inner, cur = [], base
            for k, tr in enumerate(ft["transforms"], 1):
                rep = w.add("SOLID_REPLICA", f"{n}.instance{k}", tool, _transform(w, tr, f"{n}.transform{k}"))
                cur = w.add("BOOLEAN_RESULT", f"{n}.step{k}", E(BOOL_OP[src.get("op") or "union"]), cur, rep)
                inner.append(cur)
            res = w.sequence(n, inner, rationale=f"{ft.get('kind', '')} pattern of {ft['source']}".strip())
            elements.append(res)
        elif t in ("box", "cylinder", "cone", "sphere", "torus"):
            res = _write_primitive(w, ft)
            tools[n] = res
            if ft.get("op") and prev is not None:
                res = w.add("BOOLEAN_RESULT", n + ".result", E(BOOL_OP[ft["op"]]), prev, res)
            elements.append(res)
            for attr, e in exprs.items():
                bindings.append((ft, attr, tools[n], e, 0))
        elif t == "boolean":
            res = w.add("BOOLEAN_RESULT", n, E(BOOL_OP[ft["op"]]), solids[ft["first"]], solids[ft["second"]])
            elements.append(res)
        else:
            raise StepError(f"{n}: feature type {t!r} is not supported")
        solids[n] = res
        prev = res
    if sk_refs:
        w.add("SHAPE_REPRESENTATION", f"{model.get('name', 'model')} sketches", sk_refs, w.ctx3)
    if not elements:
        return f, w.notes

    seq = w.sequence(model.get("name", "model"), elements, [solids[s] for s in model.get("suppressed", [])
                                                            if s in solids],
                     rationale=model.get("rationale", "construction history"))
    proc = w.add("PROCEDURAL_SHAPE_REPRESENTATION", model.get("name", "model"), [seq], w.ctx3)
    if brep:
        w.add("EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP", model.get("name", "model"), U, proc,
              brep[0])

    # parameters of the history: a variational wrapper around a shape representation holding the sequence
    P = _Params(w, params)
    var_items = []
    for ft, attr, owner, e, k in bindings:
        key = (ft["type"], attr)
        if key not in FEATURE_ATTR:
            w.notes.append(f"{ft['name']}.{attr}: no ISO 10303-111/42 attribute carries it; expression not written")
            continue
        var_items += P.bind(f"{ft['name']}.{attr}" + (f".{k}" if k else ""), owner, FEATURE_ATTR[key], e)
    var_items += P.items()
    for name in params:                             # parameters nothing uses still belong to the model
        if name not in P.unbound and not any(name in s_params(sk) for sk in model.get("sketches", [])):
            w.notes.append(f"parameter {name} drives nothing; written without a constraint")
            P.unbound_param(name)
            var_items.append(P.unbound[name])
    if var_items:
        cur = w.add("SHAPE_REPRESENTATION", model.get("name", "model") + " history", [seq], w.ctx3)
        var = w.cx(("REPRESENTATION", [model.get("name", "model") + " parameters", [seq] + var_items, w.ctx3]),
                   ("SHAPE_REPRESENTATION", []), ("VARIATIONAL_REPRESENTATION", []))
        w.add("VARIATIONAL_CURRENT_REPRESENTATION_RELATIONSHIP", model.get("name", "model"), U, var, cur, cur)
    return f, w.notes


def s_params(sk):
    out = set()
    for c in sk.get("constraints", []):
        if c.get("expression"):
            out |= expr_vars(c["expression"])
    return out


def model_feature(model, name):
    for ft in model.get("features", []):
        if ft["name"] == name:
            return ft
    return None


# ------------------------------------------------------------------ reading
class _Reader:
    def __init__(self, f):
        from . import iso10303
        self.f = f
        self.d = iso10303.dictionary()
        self.m = iso10303._Model(f, self.d)
        self.notes = []
        self.L = self.A = 1.0                       # file units -> mm and radians

    PREFIX = {"EXA": 1e18, "PETA": 1e15, "TERA": 1e12, "GIGA": 1e9, "MEGA": 1e6, "KILO": 1e3, "HECTO": 1e2,
              "DECA": 1e1, "DECI": 1e-1, "CENTI": 1e-2, "MILLI": 1e-3, "MICRO": 1e-6, "NANO": 1e-9,
              "PICO": 1e-12, "FEMTO": 1e-15, "ATTO": 1e-18}

    def unit_factor(self, u, depth=0):
        """('length' | 'angle' | None, factor to mm or radians) of a unit instance."""
        inst = self.inst(u)
        if inst is None or depth > 5:
            return None, 1.0
        names = inst.names
        kind = "length" if "LENGTH_UNIT" in names else "angle" if "PLANE_ANGLE_UNIT" in names else None
        si = inst.record("SI_UNIT")
        if si is not None:
            pre = self.PREFIX.get(str(si.params[0]), 1.0) if isinstance(si.params[0], p21.Enum) else 1.0
            base = {"METRE": 1000.0, "RADIAN": 1.0}.get(str(si.params[1]), 1.0)
            return kind, pre * base
        cb = inst.record("CONVERSION_BASED_UNIT")
        if cb is not None and isinstance(cb.params[1], p21.Ref):
            m = self.inst(cb.params[1])
            rec = m.records[0] if not m.complex else m.record("MEASURE_WITH_UNIT")
            if rec is not None and len(rec.params) >= 2:
                v = rec.params[0].value if isinstance(rec.params[0], p21.Typed) else rec.params[0]
                k2, f2 = self.unit_factor(rec.params[1], depth + 1)
                return kind or k2, float(v) * f2
        return kind, 1.0

    def use_units(self, ctx):
        """Take the length and plane angle units of a representation context."""
        inst = self.inst(ctx)
        rec = inst.record("GLOBAL_UNIT_ASSIGNED_CONTEXT") if inst is not None else None
        if rec is None or not rec.params:
            return
        for u in rec.params[0]:
            kind, fac = self.unit_factor(u)
            if kind == "length":
                self.L = fac
            elif kind == "angle":
                self.A = fac
        if (self.L, self.A) != (1.0, 1.0):
            self.notes.append(f"file units: 1 length unit = {self.L:g} mm, 1 angle unit = {self.A:g} rad")

    def ln(self, r, a):
        return float(self.get(r, a)) * self.L

    def an(self, r, a):
        return float(self.get(r, a)) * self.A

    def inst(self, r):
        return self.f.get(r)

    def isa(self, r, n):
        return self.m.isa(r, n)

    def get(self, r, a):
        return self.m.get(r, a)

    def name(self, r):
        return self.get(r, "representation_item.name") or ""

    def coords(self, r):
        return [float(c) * self.L for c in self.get(r, "coordinates")]

    def dir(self, r):
        return [float(c) for c in self.get(r, "direction_ratios")]

    def a2p3(self, r):
        loc = self.coords(self.get(r, "location"))
        ax = self.get(r, "axis")
        rd = self.get(r, "ref_direction")
        axis = self.dir(ax) if isinstance(ax, p21.Ref) else [0.0, 0.0, 1.0]
        x = self.dir(rd) if isinstance(rd, p21.Ref) else ([1.0, 0, 0] if abs(axis[0]) < 0.9 else [0, 1.0, 0])
        x = _norm(_sub(x, _mul(axis, _dot(x, axis))))
        return {"origin": loc, "axis": _norm(axis), "x": x}

    def a1p(self, r):
        ax = self.get(r, "axis")
        return {"origin": self.coords(self.get(r, "location")),
                "dir": self.dir(ax) if isinstance(ax, p21.Ref) else [0.0, 0.0, 1.0]}

    def value(self, v):
        return float(v.value if isinstance(v, p21.Typed) else v)

    # topology
    def curve3(self, r):
        if self.isa(r, "line"):
            vec = self.get(r, "dir")
            return {"type": "line", "origin": self.coords(self.get(r, "pnt")),
                    "dir": _norm(self.dir(self.get(vec, "orientation")))}
        if self.isa(r, "circle"):
            pl = self.a2p3(self.get(r, "position"))
            return {"type": "circle", "center": pl["origin"], "axis": pl["axis"], "x": pl["x"],
                    "r": self.ln(r, "radius")}
        if self.isa(r, "ellipse"):
            pl = self.a2p3(self.get(r, "position"))
            return {"type": "ellipse", "center": pl["origin"], "axis": pl["axis"], "x": pl["x"],
                    "r1": self.ln(r, "semi_axis_1"), "r2": self.ln(r, "semi_axis_2")}
        if self.isa(r, "b_spline_curve_with_knots"):
            return {"type": "bspline", "degree": self.get(r, "degree"),
                    "poles": [self.coords(p) for p in self.get(r, "control_points_list")],
                    "mults": list(self.get(r, "knot_multiplicities")), "knots": list(self.get(r, "knots")),
                    "closed": self.get(r, "closed_curve") == "T"}
        raise StepError(f"#{int(r)}: curve {self.inst(r).name} is not read")

    def surface(self, r):
        pl = self.a2p3(self.get(r, "position"))
        s = dict(pl)
        if self.isa(r, "plane"):
            s["type"] = "plane"
        elif self.isa(r, "cylindrical_surface"):
            s.update(type="cylinder", r=self.ln(r, "radius"))
        elif self.isa(r, "conical_surface"):
            s.update(type="cone", r=self.ln(r, "radius"), semi_angle=self.an(r, "semi_angle"))
        elif self.isa(r, "spherical_surface"):
            s.update(type="sphere", r=self.ln(r, "radius"))
        elif self.isa(r, "toroidal_surface"):
            s.update(type="torus", R=self.ln(r, "major_radius"), r=self.ln(r, "minor_radius"))
        else:
            raise StepError(f"#{int(r)}: surface {self.inst(r).name} is not read")
        return s

    def edge(self, r):
        p1 = self.coords(self.get(self.get(r, "edge_start"), "vertex_geometry"))
        p2 = self.coords(self.get(self.get(r, "edge_end"), "vertex_geometry"))
        return {"curve": self.curve3(self.get(r, "edge_geometry")), "p1": p1, "p2": p2}

    def face(self, r):
        loops = []
        for b in self.get(r, "bounds"):
            loop = self.get(b, "bound")
            edges = []
            for oe in self.get(loop, "edge_list"):
                e = self.edge(self.get(oe, "edge_element"))
                if self.get(oe, "orientation") == "F":
                    e["p1"], e["p2"] = e["p2"], e["p1"]
                    e["reversed"] = True
                edges.append(e)
            (loops.insert(0, edges) if self.isa(b, "face_outer_bound") else loops.append(edges))
        return {"surface": self.surface(self.get(r, "face_geometry")), "loops": loops,
                "same_sense": self.get(r, "same_sense") != "F"}


def _read_sketch(rd, var, cur, rep):
    """Variational sketch representation -> model sketch."""
    name = rd.get(cur, "name")
    items = rd.get(var, "items")
    geo, gid, lookup = [], {}, {}
    pts = {}

    def pt2(r):
        return [float(c) * rd.L for c in rd.get(r, "coordinates")][:2]

    for it in items:
        if rd.isa(it, "variational_representation_item") and not rd.isa(it, "trimmed_curve"):
            continue
        construction = rd.isa(it, "auxiliary_geometric_representation_item")
        if rd.isa(it, "trimmed_curve"):
            basis = rd.get(it, "basis_curve")
            t1 = [x for x in rd.get(it, "trim_1") if isinstance(x, p21.Ref)][0]
            t2 = [x for x in rd.get(it, "trim_2") if isinstance(x, p21.Ref)][0]
            if rd.get(it, "sense_agreement") == "F":
                t1, t2 = t2, t1
            if rd.isa(basis, "line"):
                g = {"type": "line", "p1": pt2(t1), "p2": pt2(t2)}
                lookup[int(basis)] = (len(geo), 0)
            else:
                c = rd.get(rd.get(basis, "position"), "location")
                g = {"type": "arc", "c": pt2(c), "r": rd.ln(basis, "radius"), "p1": pt2(t1),
                     "p2": pt2(t2)}
                lookup[int(basis)] = (len(geo), 0)
                pts[int(c)] = (len(geo), 3)
            pts[int(t1)], pts[int(t2)] = (len(geo), 1), (len(geo), 2)
        elif rd.isa(it, "circle"):
            c = rd.get(rd.get(it, "position"), "location")
            g = {"type": "circle", "c": pt2(c), "r": rd.ln(it, "radius")}
            lookup[int(it)] = (len(geo), 0)
            pts[int(c)] = (len(geo), 3)
        elif rd.isa(it, "cartesian_point"):
            g = {"type": "point", "p": pt2(it)}
            pts[int(it)] = (len(geo), 1)
            lookup[int(it)] = (len(geo), 1)
        else:
            rd.notes.append(f"{name}: sketch item #{int(it)} ({rd.inst(it).name}) not read")
            continue
        if construction:
            g["construction"] = True
        gid[int(it)] = len(geo)
        geo.append(g)

    def axis_of(r):
        n = rd.name(r)
        if n.endswith(".x_axis"):
            return -1
        if n.endswith(".y_axis"):
            return -2
        return None

    def as_point(r):
        if int(r) in pts:
            return pts[int(r)]
        if rd.name(r).endswith(".origin"):
            return (-1, 1)
        return None

    def as_curve(r):
        if int(r) in lookup:
            return lookup[int(r)][0]
        if int(r) in gid:
            return gid[int(r)]
        return axis_of(r)

    cons = []
    aux_refs = {}                                     # aux line -> anchor point (from its incidence)
    for it in items:
        if rd.isa(it, "incidence_geometric_constraint") and rd.name(it).endswith(".ref"):
            ref = rd.get(it, "reference_elements")[0]
            aux_refs[int(ref)] = as_point(rd.get(it, "constrained_elements")[0])
    for it in items:
        if not rd.isa(it, "explicit_geometric_constraint"):
            continue
        nm, desc = rd.name(it), rd.get(it, "description")
        if nm.endswith(".ref") or nm.endswith(".endpoints"):
            continue
        consd, refs = rd.get(it, "constrained_elements"), rd.get(it, "reference_elements")
        c = {"name": "" if nm.startswith(f"{name}.c") else nm, "ref": int(it)}
        kind = desc if isinstance(desc, str) and desc else None
        if rd.isa(it, "incidence_geometric_constraint"):
            pa, pb = as_point(consd[0]), as_point(refs[0])
            if pb is not None:
                c.update(type="Coincident", first=pa[0], first_pos=pa[1], second=pb[0], second_pos=pb[1])
            else:
                c.update(type="PointOnObject", first=pa[0], first_pos=pa[1], second=as_curve(refs[0]))
            if pa[0] == -1 and pb is not None:          # FreeCAD wants the root point second
                c.update(first=pb[0], first_pos=pb[1], second=-1, second_pos=1)
        elif rd.isa(it, "parallel_geometric_constraint"):
            a, b = as_curve(consd[0]), as_curve(refs[0])
            if b in (-1, -2) and a >= 0:
                c.update(type="Horizontal" if b == -1 else "Vertical", first=a)
            else:
                c.update(type="Parallel", first=a, second=b)
        elif rd.isa(it, "perpendicular_geometric_constraint"):
            c.update(type="Perpendicular", first=as_curve(consd[0]), second=as_curve(refs[0]))
        elif rd.isa(it, "tangent_geometric_constraint"):
            c.update(type="Tangent", first=as_curve(consd[0]), second=as_curve(refs[0]))
        elif rd.isa(it, "clgc_with_dimension"):
            c.update(type="Distance", first=as_curve(consd[0]), value=rd.ln(it, "length_value"))
        elif rd.isa(it, "curve_length_geometric_constraint") or rd.isa(it, "radius_geometric_constraint") \
                and not rd.isa(it, "rgc_with_dimension"):
            c.update(type="Equal", first=as_curve(consd[0]), second=as_curve(consd[1]))
        elif rd.isa(it, "pdgc_with_dimension"):
            v = rd.ln(it, "distance_value")
            pa = as_point(consd[0])
            ref = refs[0]
            if kind in ("DistanceX", "DistanceY"):
                anchor = aux_refs.get(int(ref), (-1, 1))
                ia = 0 if kind == "DistanceX" else 1
                pa_xy = _geo_point(geo, *pa)
                an_xy = _geo_point(geo, *anchor)
                sign = 1.0 if pa_xy[ia] - an_xy[ia] >= 0 else -1.0
                if anchor == (-1, 1):
                    c.update(type=kind, first=pa[0], first_pos=pa[1], value=sign * v)
                elif anchor[0] == pa[0] and anchor[1] == 1 and pa[1] == 2 and geo[pa[0]]["type"] == "line":
                    c.update(type=kind, first=pa[0], value=sign * v)
                else:
                    c.update(type=kind, first=anchor[0], first_pos=anchor[1], second=pa[0], second_pos=pa[1],
                             value=sign * v)
            else:
                pb = as_point(ref)
                if pb is not None:
                    c.update(type="Distance", first=pa[0], first_pos=pa[1], second=pb[0], second_pos=pb[1], value=v)
                else:
                    c.update(type="Distance", first=pa[0], first_pos=pa[1], second=as_curve(ref), value=v)
        elif rd.isa(it, "rgc_with_dimension"):
            v = rd.ln(it, "radius_value")
            diameter = kind == "Diameter"
            c.update(type="Diameter" if diameter else "Radius", first=as_curve(consd[0]),
                     value=2 * v if diameter else v)
        elif rd.isa(it, "agc_with_dimension"):
            a, b = as_curve(consd[0]), as_curve(refs[0])
            v = rd.an(it, "angle_value")
            ang = _current_angle(geo, a, b, v)
            if b == -1:
                c.update(type="Angle", first=a, value=ang)
            else:
                c.update(type="Angle", first=a, second=b, value=ang)
        elif rd.isa(it, "symmetry_geometric_constraint"):
            pa, pb = as_point(consd[0]), as_point(consd[1])
            c.update(type="Symmetric", first=pa[0], first_pos=pa[1], second=pb[0], second_pos=pb[1],
                     third=as_curve(rd.get(it, "mirror_element")))
        elif rd.isa(it, "fixed_element_geometric_constraint"):
            c.update(type="Block", first=as_curve(consd[0]))
        else:
            rd.notes.append(f"{name}: constraint #{int(it)} ({rd.inst(it).name}) not read")
            continue
        cons.append(c)
    placement = rd.a2p3(rd.get(rep, "mapping_target")) if rep is not None else \
        {"origin": [0, 0, 0], "axis": [0, 0, 1], "x": [1, 0, 0]}
    return {"name": name, "placement": placement, "geometry": geo, "constraints": cons}


def _geo_point(geo, g, pos):
    if g == -1:
        return [0.0, 0.0]
    x = geo[g]
    return {1: x.get("p1") or x.get("p"), 2: x.get("p2"), 3: x.get("c")}[pos]


def _line_dir(geo, g):
    if g == -1:
        return [1.0, 0.0]
    if g == -2:
        return [0.0, 1.0]
    x = geo[g]
    return _sub(x["p2"], x["p1"])


def _current_angle(geo, a, b, v):
    """FreeCAD's signed angle from line b to line a in the current geometry, consistent with v (0-90)."""
    try:
        da, db = _line_dir(geo, a), _line_dir(geo, b)
        cur = math.atan2(da[1], da[0]) - math.atan2(db[1], db[0])
        cur = (cur + math.pi) % (2 * math.pi) - math.pi
        geometric = min(abs(cur) % math.pi, math.pi - abs(cur) % math.pi)
        return cur if abs(geometric - v) < 1e-6 else math.copysign(v, cur)
    except (KeyError, TypeError, IndexError):
        return v


def _read_expr(rd, r, params):
    if rd.isa(r, "variational_parameter"):
        return ["var", rd.get(r, "representation_item.name")]
    if rd.isa(r, "literal_number"):
        return ["num", float(rd.get(r, "the_value"))]
    for op, name in OPS.items():
        if rd.isa(r, name.lower()):
            a, b = rd.get(r, "operands")
            return [op, _read_expr(rd, a, params), _read_expr(rd, b, params)]
    if rd.isa(r, "minus_function"):
        return ["neg", _read_expr(rd, rd.get(r, "operand"), params)]
    for fn, name in FUNCS.items():
        if rd.isa(r, name.lower()):
            ops = rd.get(r, "operands") if fn in ("min", "max") or (fn == "atan" and rd.isa(r, "binary_generic_expression")) \
                else [rd.get(r, "operand")]
            return ["call", fn, [_read_expr(rd, a, params) for a in ops]]
    raise StepError(f"#{int(r)}: expression {rd.inst(r).name} is not read")


def from_step(f):
    """A p21.File -> (list of models, notes). One model per PROCEDURAL_SHAPE_REPRESENTATION."""
    from . import procedural_sketch
    rd = _Reader(f)
    reps = rd.m.all_of("procedural_shape_representation") or rd.m.all_of("neutral_sketch_representation")
    if reps:
        rd.use_units(rd.get(reps[0], "context_of_items"))
    params, bindings = {}, {}
    for p in rd.m.all_of("unbound_variational_parameter"):
        name = rd.get(p, "representation_item.name")
        desc = rd.get(p, "parameter_description")
        unit, text = "", desc if isinstance(desc, str) else ""
        if text.startswith("[") and "]" in text:
            unit, text = text[1:text.index("]")], text[text.index("]") + 1:].strip()
        v = float(rd.value(rd.get(p, "parameter_current_value")))
        v = v * rd.L if unit == "mm" else v * rd.A if unit == "deg" else v
        params[name] = {"name": name, "value": math.degrees(v) if unit == "deg" else v, "unit": unit,
                        "description": text}
    for env in rd.m.all_of("bound_parameter_environment"):
        bp, iar = rd.get(env, "syntactic_representation"), rd.get(env, "semantics")
        owner, attr = rd.get(iar, "owning_instance"), rd.get(iar, "attribute_name")
        expr = None
        for c in rd.m.users(bp):
            if rd.isa(c, "equal_parameter_constraint") and int(bp) in map(int, rd.get(c, "constrained_elements")):
                expr = ["var", rd.get(rd.get(c, "reference_elements")[0], "representation_item.name")]
            elif rd.isa(c, "free_form_assignment") and int(bp) in map(int, rd.get(c, "constrained_elements")):
                expr = _read_expr(rd, rd.get(c, "constraining_expression"), params)
        if expr is not None:
            bindings.setdefault(int(owner), []).append((attr, expr))

    sketches, by_rep, by_current = [], {}, {}
    for rel in rd.m.all_of("variational_current_representation_relationship"):
        var, cur = rd.get(rel, "rep_1"), rd.get(rel, "rep_2")
        if not rd.isa(cur, "neutral_sketch_representation"):
            continue
        rep = None
        for m in rd.m.users(cur):
            if rd.isa(m, "representation_map"):
                for u in rd.m.users(m.id):
                    if rd.isa(u, "repositioned_neutral_sketch"):
                        rep = u.id
        sk = _read_sketch(rd, var, cur, rep)
        for c in sk["constraints"]:
            for attr, expr in bindings.get(c.pop("ref"), []):
                c["expression"] = expr
        for c in sk["constraints"]:
            c.pop("ref", None)
        sketches.append(sk)
        by_current[int(cur)] = sk
        if rep is not None:
            by_rep[rep] = sk["name"]
    face_sketch = {}
    for rel in rd.m.all_of("implicit_explicit_positioned_sketch_relationship"):
        rep, ps = rd.get(rel, "relating_representation_item"), rd.get(rel, "related_representation_item")
        face_sketch[int(rd.get(ps, "sketch_basis"))] = by_rep.get(int(rep))

    # ISO 10303-112 sketches: evaluated; checked against the explicit sketch they are paired with, if any
    command_reps = set()
    explicit_of = {int(rd.get(r, "rep_1")): rd.get(r, "rep_2")
                   for r in rd.m.all_of("explicit_procedural_shape_representation_relationship")}
    for proc in rd.m.all_of("procedural_shape_representation"):
        seqs = rd.get(proc, "items") or []
        if not seqs or not all(procedural_sketch.is_command_sequence(rd, q) for q in seqs):
            continue
        command_reps.add(proc.id)
        geo, more = [], []
        for q in seqs:
            g, n = procedural_sketch.evaluate(rd, q, rd.L, rd.A)
            geo += g
            more += n
        rd.notes += more
        pair = by_current.get(int(explicit_of.get(proc.id, 0)))
        name = rd.get(proc, "name") or "Sketch"
        if pair is not None:
            want = [x for x in pair["geometry"] if x["type"] != "point"]
            hit = sum(1 for x in want if any(_same_geo(x, y) for y in geo))
            rd.notes.append(f"{pair['name']}: its ISO 10303-112 commands make {hit} of its {len(want)} curves")
        else:
            sketches.append({"name": name[:-9] if name.endswith(" commands") else name,
                             "placement": {"origin": [0, 0, 0], "axis": [0, 0, 1], "x": [1, 0, 0]},
                             "geometry": geo, "constraints": [], "from": "ISO 10303-112"})
            rd.notes.append(f"{name}: an ISO 10303-112 sketch of {len(geo)} curves, placed on XY (Part 112 does "
                            "not position a sketch)")

    models = []
    for proc in rd.m.all_of("procedural_shape_representation"):
        if proc.id in command_reps:
            continue
        seqs = rd.get(proc, "items")
        model = {"name": rd.get(proc, "name"), "parameters": list(params.values()), "sketches": sketches,
                 "features": []}
        names = {}
        for s in seqs:
            _read_sequence(rd, s, model, names, face_sketch, bindings)
        models.append(model)
    if not models and (sketches or params):
        models.append({"name": "sketches", "parameters": list(params.values()), "sketches": sketches,
                       "features": []})
    return models, rd.notes


def _same_geo(a, b, tol=1e-6):
    """Two model sketch elements with the same geometry (a line either way round)."""
    if a["type"] != b["type"]:
        return False

    def close(p, q):
        return all(abs(x - y) <= tol for x, y in zip(p, q))
    if a["type"] == "line":
        return (close(a["p1"], b["p1"]) and close(a["p2"], b["p2"])) or \
            (close(a["p1"], b["p2"]) and close(a["p2"], b["p1"]))
    if a["type"] in ("circle", "arc"):
        same = close(a["c"], b["c"]) and abs(a["r"] - b["r"]) <= tol
        return same and (a["type"] == "circle" or (close(a["p1"], b["p1"]) and close(a["p2"], b["p2"])))
    return close(a.get("p", []), b.get("p", []))


def _feature_bindings(rd, r, kind, bindings, ft):
    inv = {v: k for (t, k), v in FEATURE_ATTR.items() if t == kind}
    for attr, expr in bindings.get(int(r), []):
        if attr in inv:
            ft.setdefault("expressions", {})[inv[attr]] = expr


def _read_tool(rd, r, face_sketch, bindings):
    """An extrusion or revolution (or a union of them over several faces) -> partial feature dict."""
    parts = []

    def walk(x):
        if rd.isa(x, "boolean_result") and rd.name(x).rsplit(".", 1)[-1].startswith("profiles"):
            walk(rd.get(x, "first_operand"))
            walk(rd.get(x, "second_operand"))
        else:
            parts.append(x)

    walk(r)
    x = parts[0]
    if not (rd.isa(x, "extruded_face_solid") or rd.isa(x, "revolved_face_solid")):
        return None
    face = rd.get(x, "swept_face")
    ft = {"name": rd.name(x), "sketch": face_sketch.get(int(face))}
    if rd.isa(x, "extruded_face_solid"):
        ft["type"] = "extrude"
        ft["direction"] = rd.dir(rd.get(x, "extruded_direction"))
        if rd.isa(x, "extruded_face_solid_with_trim_conditions"):
            ft["first"] = rd.value(rd.get(x, "first_trim_condition")) * rd.L
            ft["second"] = rd.value(rd.get(x, "second_trim_condition")) * rd.L
            ft["intent"] = [str(rd.get(x, "first_trim_intent")).lower(), str(rd.get(x, "second_trim_intent")).lower()]
            if rd.isa(x, "extruded_face_solid_with_draft_angle"):
                ft["taper"] = rd.an(x, "draft_angle")
        else:
            ft["first"], ft["second"] = rd.ln(x, "depth"), 0.0
        kind = "extrude"
    elif rd.isa(x, "revolved_face_solid"):
        ft["type"] = "revolve"
        ft["axis"] = rd.a1p(rd.get(x, "axis"))
        if rd.isa(x, "revolved_face_solid_with_trim_conditions"):
            ft["angle"] = rd.value(rd.get(x, "first_trim_condition")) * rd.A
            ft["second"] = rd.value(rd.get(x, "second_trim_condition")) * rd.A
        else:
            ft["angle"] = rd.an(x, "angle")
        kind = "revolve"
    else:
        return None
    if ft["sketch"] is None:
        ft["face"] = rd.face(face)
    _feature_bindings(rd, x, kind, bindings, ft)
    return ft


def _read_primitive(rd, r, bindings):
    n = rd.name(r)
    if rd.isa(r, "block"):
        ft = {"type": "box", "name": n, "placement": rd.a2p3(rd.get(r, "position")),
              "x": rd.ln(r, "x"), "y": rd.ln(r, "y"), "z": rd.ln(r, "z")}
    elif rd.isa(r, "right_circular_cylinder"):
        a = rd.a1p(rd.get(r, "position"))
        ft = {"type": "cylinder", "name": n, "placement": _axis_placement(a),
              "height": rd.ln(r, "height"), "radius": rd.ln(r, "radius")}
    elif rd.isa(r, "right_circular_cone"):
        a = rd.a1p(rd.get(r, "position"))
        ft = {"type": "cone", "name": n, "placement": _axis_placement(a), "height": rd.ln(r, "height"),
              "radius": rd.ln(r, "radius"), "semi_angle": rd.an(r, "semi_angle")}
    elif rd.isa(r, "sphere"):
        ft = {"type": "sphere", "name": n, "radius": rd.ln(r, "radius"),
              "placement": {"origin": rd.coords(rd.get(r, "centre")), "axis": [0, 0, 1], "x": [1, 0, 0]}}
    elif rd.isa(r, "torus"):
        a = rd.a1p(rd.get(r, "position"))
        ft = {"type": "torus", "name": n, "placement": _axis_placement(a),
              "major": rd.ln(r, "major_radius"), "minor": rd.ln(r, "minor_radius")}
    else:
        return None
    _feature_bindings(rd, r, ft["type"], bindings, ft)
    return ft


def _axis_placement(a):
    ax = _norm(a["dir"])
    x = [1.0, 0, 0] if abs(ax[0]) < 0.9 else [0, 1.0, 0]
    x = _norm(_sub(x, _mul(ax, _dot(x, ax))))
    return {"origin": a["origin"], "axis": ax, "x": x}


def _read_transform(rd, r):
    cols = [rd.dir(rd.get(r, a)) for a in ("axis1", "axis2", "axis3")]
    m = [[cols[k][i] for k in range(3)] for i in range(3)]
    return {"matrix": m, "translation": rd.coords(rd.get(r, "local_origin"))}


def _read_sequence(rd, seq, model, names, face_sketch, bindings):
    """Walk a procedural sequence and append the features it represents."""
    feats = model["features"]
    last = [None]

    def solid_name(r):
        return names.get(int(r))

    def add(ft, result):
        feats.append(ft)
        names[int(result)] = ft["name"]
        last[0] = ft["name"]

    elements = rd.get(seq, "elements")
    for el in elements:
        if rd.isa(el, "user_selected_elements"):
            continue
        if rd.isa(el, "procedural_representation_sequence"):
            inner = rd.get(el, "elements")
            reps = []
            for x in inner:
                if rd.isa(x, "boolean_result") and rd.isa(rd.get(x, "second_operand"), "solid_replica"):
                    reps.append(rd.get(x, "second_operand"))
            if reps and len(reps) == len(inner):
                src_tool = rd.get(reps[0], "parent_solid")
                src = names.get(int(src_tool))
                ft = {"type": "pattern", "name": rd.name(el), "source": src,
                      "transforms": [_read_transform(rd, rd.get(x, "transformation")) for x in reps]}
                rat = rd.get(el, "rationale") or ""
                ft["kind"] = "polar" if rat.startswith("polar") else "linear" if rat.startswith("linear") else ""
                add(ft, el)
            else:
                _read_sequence(rd, el, model, names, face_sketch, bindings)
                names[int(el)] = last[0]
            continue
        if rd.isa(el, "boolean_result"):
            a, b = rd.get(el, "first_operand"), rd.get(el, "second_operand")
            op = str(rd.get(el, "operator")).lower()
            tool = _read_tool(rd, b, face_sketch, bindings) or _read_primitive(rd, b, bindings)
            if tool is not None and solid_name(a) is not None and solid_name(b) is None:
                tool["op"] = op
                names[int(b)] = tool["name"]
                add(tool, el)
            else:
                add({"type": "boolean", "name": rd.name(el), "op": op, "first": solid_name(a),
                     "second": solid_name(b)}, el)
            continue
        ft = _read_tool(rd, el, face_sketch, bindings) or _read_primitive(rd, el, bindings)
        if ft is not None:
            names[int(el)] = ft["name"]
            add(ft, el)
            continue
        if rd.isa(el, "edge_blended_solid"):
            edges = [rd.edge(e) for e in rd.get(el, "blended_edges")]
            ft = {"name": rd.name(el), "edges": edges, "base": solid_name(rd.get(el, "base_solid"))}
            if rd.isa(el, "solid_with_constant_radius_edge_blend"):
                ft.update(type="fillet", radius=rd.ln(el, "radius"))
                _feature_bindings(rd, el, "fillet", bindings, ft)
            elif rd.isa(el, "solid_with_double_offset_chamfer"):
                ft.update(type="chamfer", kind="double", d1=rd.ln(el, "left_offset_distance"),
                          d2=rd.ln(el, "right_offset_distance"))
            elif rd.isa(el, "solid_with_angle_based_chamfer"):
                ft.update(type="chamfer", kind="angle", d1=rd.ln(el, "offset_distance"),
                          angle=rd.an(el, "offset_angle"), left=rd.get(el, "left_offset") == "T")
            elif rd.isa(el, "solid_with_single_offset_chamfer"):
                ft.update(type="chamfer", kind="single", d1=rd.ln(el, "offset_distance"))
                _feature_bindings(rd, el, "chamfer", bindings, ft)
            else:
                rd.notes.append(f"#{el.id if hasattr(el, 'id') else int(el)}: blend type not read")
                continue
            add(ft, el)
            continue
        if rd.isa(el, "shelled_solid"):
            ft = {"type": "shell", "name": rd.name(el), "thickness": rd.ln(el, "thickness"),
                  "faces": [rd.face(x) for x in rd.get(el, "deleted_face_set")],
                  "base": solid_name(rd.get(el, "base_solid"))}
            _feature_bindings(rd, el, "shell", bindings, ft)
            add(ft, el)
            continue
        rd.notes.append(f"#{int(el)}: {rd.inst(el).name} in the construction history is not read")
    sup = {int(x) for x in rd.get(seq, "suppressed_items") or []}
    if sup:
        model["suppressed"] = [names[x] for x in sup if x in names]


# ------------------------------------------------------------------ dual model: append to a B-rep file
def brep_representation(f):
    """(representation ref, context ref) of the solid B-rep in a STEP file written by OpenCASCADE."""
    best = None
    for inst in f:
        names = inst.names
        for n in ("ADVANCED_BREP_SHAPE_REPRESENTATION", "MANIFOLD_SURFACE_SHAPE_REPRESENTATION",
                  "FACETED_BREP_SHAPE_REPRESENTATION"):
            if n in names:
                rec = inst.record(n) if inst.complex else inst.records[0]
                if inst.complex:
                    rec = inst.record("REPRESENTATION")
                if rec and len(rec.params) >= 3:
                    best = best or (p21.Ref(inst.id), rec.params[2])
    return best


def merge(brep_file, model, sketch_commands=False):
    """Append a model's procedural and parametric data to a STEP file holding its explicit B-rep (the
    dual model of ISO 10303-55). FILE_SCHEMA is set to AP242, whose schema includes Parts 55, 108 and
    111. Returns (file, notes)."""
    f = brep_file
    br = brep_representation(f)
    if br is None:
        raise StepError("the B-rep file has no solid shape representation")
    _, notes = to_step(model, f, brep=br, sketch_commands=sketch_commands)
    fs = f.header_record("FILE_SCHEMA")
    if fs and not any(s.startswith("AP242") for s in fs.params[0]):
        notes.append(f"FILE_SCHEMA was {fs.params[0]}; set to AP242 (the schema that holds Parts 55, 108, 111)")
        fs.params[0] = [SCHEMAS[0] + " { 1 0 10303 442 1 1 4 }"]
    return f, notes

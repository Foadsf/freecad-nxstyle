# SPDX-License-Identifier: LGPL-2.1-or-later
"""2D sketches as ISO 10303-112 modelling commands: evaluate them, and write them (no FreeCAD needed).

A Part 112 sketch is a procedural sequence (ISO 10303-55) of commands. evaluate() runs one into the
geometry of a model sketch (parametric.py's sketch dict): lines, arcs, circles, ellipses and splines.

  creation     create_line_segment_2_points, _point_tangent, _2_tangents (lines and circles),
               create_centreline (construction), create_polyline, create_rectangle, create_polygon
               (inscribed, circumscribed), create_circle_centre_point, _2_points, _3_points, _concentric,
               create_circular_arc_3_points, _centre_ends, _angles, _concentric, _start_centre_angle,
               _start_centre_length, _start_end_angle, _start_end_direction, _start_end_radius,
               create_ellipse_3_points, _centre_point, create_spline
  operations   create_fillet and create_chamfer between two lines (trimmed or not), create_divided_curve
               (a line split at a point), sketch_transform_translate, _rotate, _mirror, _scale (copy or
               move), create_pattern_rectangular, create_pattern_circular (radially aligned or not)

The operations refer to earlier results the way Part 112 4.2.2 shows: through explicit curves (a
TRIMMED_CURVE on a LINE, a CIRCLE) picked with USER_SELECTED_SHAPE_ELEMENTS. Those are matched to the
geometry made so far by their position. Not evaluated, and reported: circles and arcs tangent to three
curves, fillets and chamfers involving arcs, parabolic arcs.

Where the text of Part 112 leaves a choice it is made here: the start point of create_polygon is its first
vertex; the second semi-axis of an ellipse is the third point's distance from the first axis (the text says
"projection onto the line defined by the first two points", which would lie along the first axis);
create_circular_arc_start_end_radius takes the shorter of the two arcs in the given direction.

write() turns a model sketch into such commands, for files whose schema includes ISO 10303-112: no AP242
edition does (their long forms carry Parts 55, 108 and 111, not 112), so parametric.to_step() writes them
only when asked.
"""

import math

from . import p21

E = p21.Enum
TOL = 1e-7


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, k):
    return (a[0] * k, a[1] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _len(a):
    return math.hypot(a[0], a[1])


def _unit(a):
    n = _len(a)
    return (a[0] / n, a[1] / n) if n > 1e-15 else (0.0, 0.0)


def _rot(v, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


def _close(a, b, tol=1e-6):
    return _len(_sub(a, b)) <= tol


def circle_3(p1, p2, p3):
    """Centre and radius of the circle through three points."""
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-15:
        raise ValueError("collinear points")
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), _len(_sub(p1, (ux, uy)))


def arc(c, r, start, end, ccw=True):
    """A model arc (counterclockwise from p1 to p2) for the arc from start to end in the given sense."""
    s, e = (start, end) if ccw else (end, start)
    return {"type": "arc", "c": list(c), "r": r, "p1": list(s), "p2": list(e)}


def line(a, b, construction=False):
    g = {"type": "line", "p1": list(a), "p2": list(b)}
    if construction:
        g["construction"] = True
    return g


def _line_line(p, d, q, e):
    """Intersection of p + t d and q + s e."""
    den = _cross(d, e)
    if abs(den) < 1e-15:
        raise ValueError("parallel lines")
    t = _cross(_sub(q, p), e) / den
    return _add(p, _mul(d, t))


def _foot(p, a, d):
    d = _unit(d)
    return _add(a, _mul(d, _dot(_sub(p, a), d)))


def transform_geo(g, fn, scale=1.0, reflect=False):
    """A copy of geometry g with every point mapped by fn (a similarity: rotation, translation, scale,
    reflection)."""
    t = g["type"]
    out = dict(g)
    for k in ("p1", "p2", "c", "p"):
        if k in g:
            out[k] = list(fn(tuple(g[k])))
    if t in ("circle", "arc"):
        out["r"] = g["r"] * scale
    if t == "arc" and reflect:                      # a reflection turns counterclockwise into clockwise
        out["p1"], out["p2"] = out["p2"], out["p1"]
    if t == "ellipse":
        o = fn((0.0, 0.0))
        m = fn(tuple(g["major"]))
        out["major"] = list(_sub(m, o))
        out["r2"] = g["r2"] * scale
    if t == "spline":
        out["points"] = [list(fn(tuple(q))) for q in g["points"]]
    return out


class _Eval:
    def __init__(self, rd, length=1.0, angle=1.0):
        self.rd, self.L, self.A = rd, length, angle
        self.geo, self.notes = [], []

    def pt(self, r):
        c = self.rd.coords(r)
        return (c[0] * self.L, c[1] * self.L)

    def num(self, v):
        return self.rd.value(v)

    def explicit(self, r):
        """An explicit curve -> ('line', a, b, bounded) or ('circle', c, r, (start, end) or None)."""
        rd = self.rd
        if rd.isa(r, "trimmed_curve"):
            basis = rd.get(r, "basis_curve")
            t1 = [x for x in rd.get(r, "trim_1") if isinstance(x, p21.Ref)]
            t2 = [x for x in rd.get(r, "trim_2") if isinstance(x, p21.Ref)]
            ends = (self.pt(t1[0]), self.pt(t2[0])) if t1 and t2 else None
            if ends and rd.get(r, "sense_agreement") == "F":
                ends = (ends[1], ends[0])
            kind = self.explicit(basis)
            if kind[0] == "line" and ends:
                return ("line", ends[0], ends[1], True)
            if kind[0] == "circle":
                return ("circle", kind[1], kind[2], ends)
            return kind
        if rd.isa(r, "line"):
            p = self.pt(rd.get(r, "pnt"))
            v = rd.get(r, "dir")
            d = rd.dir(rd.get(v, "orientation"))[:2]
            m = float(rd.get(v, "magnitude")) * self.L
            return ("line", p, _add(p, (d[0] * m, d[1] * m)), False)
        if rd.isa(r, "circle"):
            c = self.pt(rd.get(rd.get(r, "position"), "location"))
            return ("circle", c, float(rd.get(r, "radius")) * self.L, None)
        raise ValueError(f"curve #{int(r)} ({rd.inst(r).name}) is not a line or a circle")

    def find(self, r):
        """Index of the geometry an explicit curve stands for."""
        k = self.explicit(r)
        for i in range(len(self.geo) - 1, -1, -1):
            g = self.geo[i]
            if k[0] == "line" and g["type"] == "line":
                a, b = tuple(g["p1"]), tuple(g["p2"])
                if k[3] and ((_close(a, k[1]) and _close(b, k[2])) or (_close(a, k[2]) and _close(b, k[1]))):
                    return i
                if not k[3]:
                    d = _unit(_sub(k[2], k[1]))
                    if abs(_cross(_sub(a, k[1]), d)) < 1e-6 and abs(_cross(_sub(b, k[1]), d)) < 1e-6:
                        return i
            if k[0] == "circle" and g["type"] in ("circle", "arc") and _close(tuple(g["c"]), k[1]) \
                    and abs(g["r"] - k[2]) < 1e-6:
                return i
        raise ValueError(f"curve #{int(r)} matches nothing made so far")

    def selected(self, r):
        """Indices of the geometry a GEOMETRIC_CURVE_SET (or a selection) holds."""
        rd = self.rd
        items = rd.get(r, "elements") if rd.isa(r, "geometric_set") else rd.get(r, "picked_items") or []
        return sorted({self.find(x) for x in items if not rd.isa(x, "point")})

    def direction(self, v):
        return (math.cos(v), math.sin(v))

    def run(self, el):
        rd, g = self.rd, self.geo
        get = lambda a: rd.get(el, a)                # noqa: E731
        P = lambda a: self.pt(get(a))                # noqa: E731
        ccw = lambda: str(get("arc_rotation_direction")).upper() != "CW"   # noqa: E731
        name = rd.inst(el).name.lower() if not rd.inst(el).complex else ""
        kind = next((n for n in (
            "create_line_segment_2_points", "create_line_segment_point_tangent", "create_line_segment_2_tangents",
            "create_centreline", "create_polyline", "create_rectangle", "create_polygon",
            "create_circle_centre_point", "create_circle_2_points", "create_circle_3_points",
            "create_circle_concentric", "create_circle_3_tangents", "create_circular_arc_3_points",
            "create_circular_arc_centre_ends", "create_circular_arc_angles", "create_circular_arc_concentric",
            "create_circular_arc_start_centre_angle", "create_circular_arc_start_centre_length",
            "create_circular_arc_start_end_angle", "create_circular_arc_start_end_direction",
            "create_circular_arc_start_end_radius", "create_circular_arc_3_tangents", "create_ellipse_3_points",
            "create_ellipse_centre_point", "create_spline", "create_parabolic_arc", "create_fillet",
            "create_chamfer", "create_divided_curve", "sketch_transform_translate", "sketch_transform_rotate",
            "sketch_transform_mirror", "sketch_transform_scale", "create_pattern_rectangular",
            "create_pattern_circular") if rd.isa(el, n)), name)
        if kind == "create_line_segment_2_points":
            g.append(line(P("start_point"), P("end_point")))
        elif kind == "create_centreline":
            g.append(line(P("first_ref_point"), P("second_ref_point"), construction=True))
        elif kind == "create_polyline":
            pts = [self.pt(x) for x in get("points")]
            g += [line(a, b) for a, b in zip(pts, pts[1:])]
        elif kind == "create_rectangle":
            p1, p2, p3 = P("first_point"), P("second_point"), P("third_point")
            d = _unit(_sub(p2, p1))
            n = (-d[1], d[0])
            h = _dot(_sub(p3, p1), n)
            p4, p5 = _add(p2, _mul(n, h)), _add(p1, _mul(n, h))
            g += [line(p1, p2), line(p2, p4), line(p4, p5), line(p5, p1)]
        elif kind == "create_polygon":
            n = int(round(self.num(get("polygon_sides"))))
            c, s = P("centre_point"), P("start_point")
            r = self.num(get("circle_radius")) * self.L
            if str(get("circle_type")).upper() == "CIRCUMSCRIBED":
                r = r / math.cos(math.pi / n)
            v = _mul(_unit(_sub(s, c)), r)
            pts = [_add(c, _rot(v, 2 * math.pi * k / n)) for k in range(n)]
            g += [line(pts[k], pts[(k + 1) % n]) for k in range(n)]
        elif kind == "create_circle_centre_point":
            g.append({"type": "circle", "c": list(P("centre_point")), "r": self.num(get("radius")) * self.L})
        elif kind == "create_circle_2_points":
            a, b = P("first_point"), P("second_point")
            g.append({"type": "circle", "c": list(_mul(_add(a, b), 0.5)), "r": _len(_sub(a, b)) / 2})
        elif kind == "create_circle_3_points":
            c, r = circle_3(P("first_point"), P("second_point"), P("third_point"))
            g.append({"type": "circle", "c": list(c), "r": r})
        elif kind == "create_circle_concentric":
            c = self.explicit(get("reference_element"))[1]
            g.append({"type": "circle", "c": list(c), "r": self.num(get("radius")) * self.L})
        elif kind == "create_circular_arc_3_points":
            a, m, b = P("first_point"), P("second_point"), P("third_point")
            c, r = circle_3(a, m, b)
            g.append(arc(c, r, a, b, ccw=_cross(_sub(m, a), _sub(b, m)) > 0))   # a, m, b turn left
        elif kind in ("create_circular_arc_centre_ends", "create_circular_arc_concentric"):
            c = P("centre_point") if kind.endswith("ends") else self.explicit(get("reference_curve"))[1]
            s, e = P("start_point"), P("end_point")
            g.append(arc(c, _len(_sub(s, c)), s, _add(c, _mul(_unit(_sub(e, c)), _len(_sub(s, c)))), ccw()))
        elif kind == "create_circular_arc_angles":
            c, r = P("centre_point"), self.num(get("radius")) * self.L
            a1, a2 = self.num(get("start_angle")) * self.A, self.num(get("end_angle")) * self.A
            g.append(arc(c, r, _add(c, _mul(self.direction(a1), r)), _add(c, _mul(self.direction(a2), r))))
        elif kind == "create_circular_arc_start_centre_angle":
            c, s = P("centre_point"), P("start_point")
            r = _len(_sub(s, c))
            a = self.num(get("end_angle")) * self.A
            g.append(arc(c, r, s, _add(c, _mul(self.direction(a), r)), ccw()))
        elif kind == "create_circular_arc_start_centre_length":
            c, s = P("centre_point"), P("start_point")
            r = _len(_sub(s, c))
            chord = self.num(get("chord_length")) * self.L
            sweep = 2 * math.asin(min(1.0, chord / (2 * r))) * (1 if ccw() else -1)
            g.append(arc(c, r, s, _add(c, _rot(_sub(s, c), sweep)), ccw()))
        elif kind in ("create_circular_arc_start_end_angle", "create_circular_arc_start_end_radius"):
            s, e = P("start_point"), P("end_point")
            chord = _len(_sub(e, s))
            if kind.endswith("angle"):
                sweep = self.num(get("arc_angle")) * self.A
                r = chord / (2 * math.sin(sweep / 2))
            else:
                r = self.num(get("radius")) * self.L
                sweep = 2 * math.asin(min(1.0, chord / (2 * r)))       # the shorter arc
            h = math.sqrt(max(r * r - chord * chord / 4, 0.0)) * (1 if sweep <= math.pi else -1)
            mid, u = _mul(_add(s, e), 0.5), _unit(_sub(e, s))
            left = (-u[1], u[0])
            c = _add(mid, _mul(left, h if ccw() else -h))
            g.append(arc(c, r, s, e, ccw()))
        elif kind == "create_circular_arc_start_end_direction":
            s, e = P("start_point"), P("end_point")
            t = _unit(tuple(rd.dir(get("start_direction"))[:2]))
            n = (-t[1], t[0])
            chord = _sub(e, s)
            k = _dot(chord, chord) / (2 * _dot(chord, n))
            c = _add(s, _mul(n, k))
            g.append(arc(c, abs(k), s, e, ccw=k > 0))
        elif kind == "create_ellipse_3_points" or kind == "create_ellipse_centre_point":
            if kind.endswith("3_points"):
                a, b, q = P("first_point"), P("second_point"), P("third_point")
                c = _mul(_add(a, b), 0.5)
                major = _sub(b, c)
            else:
                c, a, q = P("centre_point"), P("first_point"), P("second_point")
                major = _sub(a, c)
            r2 = abs(_cross(_sub(q, c), _unit(major)))
            g.append({"type": "ellipse", "c": list(c), "major": list(major), "r2": r2})
        elif kind == "create_spline":
            g.append({"type": "spline", "points": [list(self.pt(x)) for x in get("points")],
                      "closed": get("closed") == "T"})
        elif kind == "create_line_segment_point_tangent":
            s = P("start_point")
            k = self.explicit(get("tangent_curve"))
            near = self.pt(rd.get(get("tangent_curve_near_point"), "related_representation_item"))
            c, r = k[1], k[2]
            d = _len(_sub(s, c))
            if d <= r:
                raise ValueError("start point inside the circle")
            base, off = math.atan2(s[1] - c[1], s[0] - c[0]), math.acos(r / d)
            cands = [_add(c, _mul(self.direction(base + sg * off), r)) for sg in (1, -1)]
            g.append(line(s, min(cands, key=lambda p: _len(_sub(p, near)))))
        elif kind == "create_line_segment_2_tangents":
            k1, k2 = self.explicit(get("first_curve")), self.explicit(get("second_curve"))
            n1 = self.pt(rd.get(get("first_near_point"), "related_representation_item"))
            n2 = self.pt(rd.get(get("second_near_point"), "related_representation_item"))
            g.append(self._tangent_2(k1[1], k1[2], k2[1], k2[2], n1, n2))
        elif kind in ("create_fillet", "create_chamfer"):
            self._corner(el, kind)
        elif kind == "create_divided_curve":
            i = self.find(get("selected_curve"))
            poc = get("division_point")
            k = self.explicit(rd.get(poc, "basis_curve"))
            u = self.num(rd.get(poc, "point_parameter"))
            if g[i]["type"] != "line" or k[0] != "line":
                raise ValueError("only a line can be divided")
            p = _add(k[1], _mul(_sub(k[2], k[1]), u))      # line(u) = pnt + u * dir (ISO 10303-42)
            a, b = g[i]["p1"], g[i]["p2"]
            g[i] = line(a, p)
            g.append(line(p, b))
        elif kind.startswith("sketch_transform_"):
            self._transform(el, kind)
        elif kind in ("create_pattern_rectangular", "create_pattern_circular"):
            self._pattern(el, kind)
        else:
            raise ValueError(f"{rd.inst(el).name} is not evaluated")

    def _tangent_2(self, c1, r1, c2, r2, n1, n2):
        best = None
        d = _len(_sub(c2, c1))
        base = math.atan2(c2[1] - c1[1], c2[0] - c1[0])
        for s2 in (1, -1):                           # external (+) and internal (-) tangents
            rr = r1 - s2 * r2
            if d < abs(rr):
                continue
            off = math.acos(rr / d)
            for sg in (1, -1):
                u = self.direction(base + sg * off)
                t1, t2 = _add(c1, _mul(u, r1)), _add(c2, _mul(u, s2 * r2))
                score = _len(_sub(t1, n1)) + _len(_sub(t2, n2))
                if best is None or score < best[0]:
                    best = (score, t1, t2)
        if best is None:
            raise ValueError("no common tangent")
        return line(best[1], best[2])

    def _corner(self, el, kind):
        rd, g = self.rd, self.geo
        f = "first_curve" if kind == "create_fillet" else "first_line"
        s = "second_curve" if kind == "create_fillet" else "second_line"
        k1, k2 = self.explicit(rd.get(el, f)), self.explicit(rd.get(el, s))
        if k1[0] != "line" or k2[0] != "line":
            raise ValueError(f"{kind} between {k1[0]} and {k2[0]} is not evaluated")
        i1, i2 = self.find(rd.get(el, f)), self.find(rd.get(el, s))
        d1, d2 = _sub(k1[2], k1[1]), _sub(k2[2], k2[1])
        x = _line_line(k1[1], d1, k2[1], d2)
        trim = rd.get(el, "trim_option") == "T"
        if kind == "create_fillet":
            r = self.num(rd.get(el, "radius")) * self.L
            s1 = 1 if rd.get(el, "to_right_of_first_curve") == "T" else -1
            s2 = 1 if rd.get(el, "to_right_of_second_curve") == "T" else -1
            n1, n2 = _unit((d1[1], -d1[0])), _unit((d2[1], -d2[0]))     # right of the curve's direction
            c = _line_line(_add(k1[1], _mul(n1, s1 * r)), d1, _add(k2[1], _mul(n2, s2 * r)), d2)
            t1, t2 = _foot(c, k1[1], d1), _foot(c, k2[1], d2)
            g.append(arc(c, r, t1, t2, ccw=_cross(_sub(t1, c), _sub(t2, c)) > 0))
        else:
            l1 = self.num(rd.get(el, "first_chamfer_length")) * self.L
            v2 = rd.get(el, "second_chamfer_length")
            l2 = l1 if v2 is p21.UNSET or v2 is None else self.num(v2) * self.L

            def along(gi, length):
                a, b = tuple(g[gi]["p1"]), tuple(g[gi]["p2"])
                far = a if _len(_sub(a, x)) > _len(_sub(b, x)) else b
                return _add(x, _mul(_unit(_sub(far, x)), length))
            t1, t2 = along(i1, l1), along(i2, l2)
            g.append(line(t1, t2))
        if trim:
            for gi, t in ((i1, t1), (i2, t2)):
                a, b = tuple(g[gi]["p1"]), tuple(g[gi]["p2"])
                key = "p1" if _len(_sub(a, x)) < _len(_sub(b, x)) else "p2"
                g[gi] = dict(g[gi], **{key: list(t)})

    def _transform(self, el, kind):
        rd, g = self.rd, self.geo
        idx = self.selected(rd.get(el, "selected_objects"))
        keep = rd.get(el, "preserve_selected_objects") == "T"
        scale, reflect = 1.0, False
        if kind == "sketch_transform_translate":
            dx, dy = self.num(rd.get(el, "displacement_x")) * self.L, self.num(rd.get(el, "displacement_y")) * self.L
            fn = lambda p: (p[0] + dx, p[1] + dy)   # noqa: E731
        elif kind == "sketch_transform_rotate":
            a = self.num(rd.get(el, "rotation_angle")) * self.A
            if str(rd.get(el, "objects_rotation_direction")).upper() == "CW":
                a = -a
            c = self.pt(rd.get(el, "rotation_centre"))
            fn = lambda p: _add(c, _rot(_sub(p, c), a))   # noqa: E731
        elif kind == "sketch_transform_scale":
            sx, sy = self.num(rd.get(el, "scale_x")), self.num(rd.get(el, "scale_y"))
            if abs(sx - sy) > 1e-12:
                self.notes.append("sketch_transform_scale with different x and y factors: circles keep their x scale")
            c = self.pt(rd.get(el, "fixed_point"))
            scale = sx
            fn = lambda p: (c[0] + (p[0] - c[0]) * sx, c[1] + (p[1] - c[1]) * sy)   # noqa: E731
        else:
            k = self.explicit(rd.get(el, "reference_axis"))
            a, d = k[1], _unit(_sub(k[2], k[1]))
            reflect = True
            fn = lambda p: _sub(_mul(_foot(p, a, d), 2), p)   # noqa: E731
        made = [transform_geo(g[i], fn, scale, reflect) for i in idx]
        if keep:
            g += made
        else:
            for i, m in zip(idx, made):
                g[i] = m

    def _pattern(self, el, kind):
        rd, g = self.rd, self.geo
        idx = self.selected(rd.get(el, "selected_objects"))
        base = [g[i] for i in idx]
        if kind == "create_pattern_rectangular":
            u = _unit(tuple(rd.dir(rd.get(el, "row_direction"))[:2]))
            sense = rd.get(el, "column_augmentation_direction")
            v = (-u[1], u[0]) if sense is p21.UNSET or str(sense).upper() != "CW" else (u[1], -u[0])
            rows, cols = int(rd.get(el, "row_number")), int(rd.get(el, "column_number"))
            rs, cs = self.num(rd.get(el, "row_spacing")) * self.L, self.num(rd.get(el, "column_spacing")) * self.L
            # rows are spaced across the row direction, columns along it (Part 112 figure 27)
            for i in range(rows):
                for j in range(cols):
                    if i == 0 and j == 0:
                        continue
                    off = _add(_mul(u, j * cs), _mul(v, i * rs))
                    g += [transform_geo(b, lambda p, o=off: _add(p, o)) for b in base]
        else:
            n = int(rd.get(el, "number_of_replicates"))
            step = self.num(rd.get(el, "angle_increment")) * self.A
            c, ref = self.pt(rd.get(el, "centre_point")), self.pt(rd.get(el, "reference_point"))
            radial = rd.get(el, "radial_alignment") == "T"
            for k in range(1, n + 1):
                a = step * k
                if radial:
                    fn = lambda p, a=a: _add(c, _rot(_sub(p, c), a))   # noqa: E731
                else:
                    moved = _sub(_add(c, _rot(_sub(ref, c), a)), ref)
                    fn = lambda p, m=moved: _add(p, m)                 # noqa: E731
                g += [transform_geo(b, fn) for b in base]


def evaluate(rd, seq, length=1.0, angle=1.0):
    """A procedural sequence of Part 112 commands -> (geometry list, notes). length and angle convert the
    file's units to mm and radians."""
    ev = _Eval(rd, length, angle)
    for el in rd.get(seq, "elements"):
        if rd.isa(el, "user_selected_elements") or not rd.isa(el, "sketch_command"):
            continue
        try:
            ev.run(el)
        except (ValueError, ZeroDivisionError, TypeError, IndexError) as err:
            ev.notes.append(f"#{int(el)} {rd.inst(el).name}: {err}")
    return ev.geo, ev.notes


def is_command_sequence(rd, seq):
    return any(rd.isa(el, "sketch_command") for el in rd.get(seq, "elements") or [])


# ------------------------------------------------------------------ writing
def write(w, sk, ctx, explicit=None):
    """Part 112 commands for a model sketch's geometry, in a PROCEDURAL_SHAPE_REPRESENTATION in the 2D
    context ctx; tied to the explicit sketch representation (the dual model of ISO 10303-55) when given.
    Points have no Part 112 command and are left out. Returns the representation."""
    cmds = []
    for i, g in enumerate(sk["geometry"]):
        nm = f"{sk['name']}.g{i}"
        t = g["type"]
        pt = lambda q: w.fresh_point([float(q[0]), float(q[1])])   # noqa: E731
        if t == "line":
            cls = "CREATE_CENTRELINE" if g.get("construction") else "CREATE_LINE_SEGMENT_2_POINTS"
            cmds.append(w.add(cls, nm, pt(g["p1"]), pt(g["p2"])))
        elif t == "circle":
            cmds.append(w.add("CREATE_CIRCLE_CENTRE_POINT", nm, pt(g["c"]), float(g["r"])))
        elif t == "arc":
            cmds.append(w.add("CREATE_CIRCULAR_ARC_CENTRE_ENDS", nm, pt(g["c"]), pt(g["p1"]), pt(g["p2"]), E("CCW")))
        elif t == "ellipse":
            c = g["c"]
            a = [c[0] + g["major"][0], c[1] + g["major"][1]]
            u = _unit(tuple(g["major"]))
            q = [c[0] - u[1] * g["r2"], c[1] + u[0] * g["r2"]]
            cmds.append(w.add("CREATE_ELLIPSE_CENTRE_POINT", nm, pt(c), pt(a), pt(q)))
        elif t == "spline":
            cmds.append(w.add("CREATE_SPLINE", nm, [pt(q) for q in g["points"]], bool(g.get("closed"))))
    if not cmds:
        return None
    seq = w.add("PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE", sk["name"] + " commands", cmds, [],
                "ISO 10303-112 modelling commands of the sketch")
    rep = w.add("PROCEDURAL_SHAPE_REPRESENTATION", sk["name"] + " commands", [seq], ctx)
    if explicit is not None:
        w.add("EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP", sk["name"], p21.UNSET, rep, explicit)
    return rep

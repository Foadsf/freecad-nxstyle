# SPDX-License-Identifier: LGPL-2.1-or-later
"""Datum reference frames: which degrees of freedom the datums of a feature control frame arrest
(no FreeCAD needed).

Drake, Dimensioning and Tolerancing Handbook, 5.9.7: a part has six degrees of freedom, three
translations and three rotations. A planar primary datum arrests three (one translation, two rotations),
a planar secondary two (one translation, one rotation), a tertiary the last translation (the 3-2-1 rule).
A cylinder used as a datum (its axis) arrests four: two translations across it and two rotations.

Each datum feature is a set of contacts: a plane touches at three points, an axis along two lines, a
centre plane (a slot's or a tab's) like a plane. A contact at point x along direction n stops the motions
(v, w) (translation v, rotation w) with n . (v + w x x) = 0, a row (n, x x n) of a constraint matrix.
The datums arrest, in their order of precedence, what each adds to the rank of that matrix; the
motions left free are its null space.

A datum feature is ("plane" | "axis" | "centre plane", point, direction): the plane's normal, the
axis's direction.
"""

_EPS = 1e-9


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _scale(a, s):
    return tuple(x * s for x in a)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = _dot(a, a) ** 0.5
    if n < _EPS:
        raise ValueError("zero direction")
    return _scale(a, 1 / n)


def _perpendiculars(n):
    """Two unit vectors perpendicular to n and to each other."""
    n = _unit(n)
    helper = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _unit(_cross(n, helper))
    return u, _cross(n, u)


def contacts(feature):
    """Constraint rows (n, x x n) of a datum feature."""
    kind, p, d = feature
    rows = []
    if kind in ("plane", "centre plane"):
        n = _unit(d)
        u, w = _perpendiculars(n)
        for x in (p, _add(p, u), _add(p, w)):
            rows.append(n + _cross(x, n))
    elif kind == "axis":
        a = _unit(d)
        u, w = _perpendiculars(a)
        for x in (p, _add(p, a)):
            for n in (u, w):
                rows.append(n + _cross(x, n))
    else:
        raise ValueError(f"datum feature kind {kind!r}: plane, axis or centre plane")
    return rows


def _rank(rows):
    m = [list(r) for r in rows]
    rank, col = 0, 0
    while rank < len(m) and col < 6:
        piv = max(range(rank, len(m)), key=lambda i: abs(m[i][col]))
        if abs(m[piv][col]) < 1e-9:
            col += 1
            continue
        m[rank], m[piv] = m[piv], m[rank]
        for i in range(len(m)):
            if i != rank and abs(m[i][col]) > 1e-12:
                f = m[i][col] / m[rank][col]
                m[i] = [a - f * b for a, b in zip(m[i], m[rank])]
        rank += 1
        col += 1
    return rank


def _null_space(rows):
    """A basis of the motions (v, w) every row stops (reduced row echelon form, free columns)."""
    m = [list(r) for r in rows]
    pivots, rank = [], 0
    for col in range(6):
        if rank >= len(m):
            break
        piv = max(range(rank, len(m)), key=lambda i: abs(m[i][col]))
        if abs(m[piv][col]) < 1e-9:
            continue
        m[rank], m[piv] = m[piv], m[rank]
        p = m[rank][col]
        m[rank] = [a / p for a in m[rank]]
        for i in range(len(m)):
            if i != rank and abs(m[i][col]) > 1e-12:
                f = m[i][col]
                m[i] = [a - f * b for a, b in zip(m[i], m[rank])]
        pivots.append(col)
        rank += 1
    free = [c for c in range(6) if c not in pivots]
    basis = []
    for fc in free:
        x = [0.0] * 6
        x[fc] = 1.0
        for r, pc in enumerate(pivots):
            x[pc] = -m[r][fc]
        basis.append(tuple(x))
    return basis


_AXES = {(1, 0, 0): "X", (0, 1, 0): "Y", (0, 0, 1): "Z"}


def _axis_name(d):
    d = _unit(d)
    for a, name in _AXES.items():
        if abs(abs(_dot(d, a)) - 1) < 1e-6:
            return name
    return "(" + ", ".join(f"{c:.3g}" for c in d) + ")"


def describe(motion):
    """'translation along X' or 'rotation about an axis along Z through (x, y, z)'."""
    v, w = motion[:3], motion[3:]
    if _dot(w, w) < 1e-12:
        return f"translation along {_axis_name(v)}"
    through = _scale(_cross(w, v), 1 / _dot(w, w))          # the point on the rotation axis nearest the origin
    pitch = _dot(w, v) / _dot(w, w)
    text = f"rotation about {_axis_name(w)}"
    if _dot(through, through) > 1e-12:
        text += " through (" + ", ".join(f"{c:.4g}" for c in through) + ")"
    if abs(pitch) > 1e-9:
        text += f" with a screw pitch {pitch:.4g}"
    return text


def analyse(features):
    """[(arrested by each datum in order)], [free motions described], total arrested."""
    rows, per, before = [], [], 0
    for f in features:
        rows += contacts(f)
        now = _rank(rows)
        per.append(now - before)
        before = now
    free = [describe(m) for m in _null_space(rows)] if rows else ["all six"]
    return per, free, before


def report(letters, features):
    """One line: what A | B | C arrests, and what stays free."""
    per, free, total = analyse(features)
    parts = ", ".join(f"{letter} {n}" for letter, n in zip(letters, per))
    text = f"{' | '.join(letters)} arrests {total} of 6 degrees of freedom ({parts})"
    if total < 6:
        text += "; free: " + "; ".join(free)
    return text

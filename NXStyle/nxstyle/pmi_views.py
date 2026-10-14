# SPDX-License-Identifier: LGPL-2.1-or-later
"""PMI model views: the geometry (no FreeCAD needed).

NX keeps PMI in model views (Wünsch, Pilz and Vajna, NX für Einsteiger, 6.10; Tickoo ch. 12): a new part has
Front, Top, Right, Back, Bottom, Left, Isometric and Trimetric; a PMI is created in the work view, lies in that
view's plane, and is hidden when another view is made the work view, unless it is displayed in that view too
(RMB > Display > in Views).

A view is a viewing direction (from the eye into the model) and an up direction on the screen. Directions
follow FreeCAD's standard views (View > Standard views), so a model view and the matching FreeCAD view look
the same. Vectors are (x, y, z) tuples.
"""

import math

_S3 = 1 / math.sqrt(3)
_E, _A = math.radians(35), math.radians(30)      # FreeCAD's trimetric: 35° elevation, 30° azimuth (measured)

# name: (viewing direction, screen up)
STANDARD = {
    "Front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "Top": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "Right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "Back": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "Bottom": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    "Left": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "Isometric": ((-_S3, _S3, -_S3), (0.0, 0.0, 1.0)),
    "Trimetric": ((-math.cos(_E) * math.sin(_A), math.cos(_E) * math.cos(_A), -math.sin(_E)), (0.0, 0.0, 1.0)),
}
ORDER = list(STANDARD)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(_dot(a, a))
    if n < 1e-12:
        raise ValueError("zero vector")
    return (a[0] / n, a[1] / n, a[2] / n)


def frame(direction, up):
    """(right, up, back) of a view: screen right and up, and back towards the eye; up is made
    perpendicular to the viewing direction (the screen's up for a direction that is not level)."""
    d = _unit(direction)
    u = (up[0] - d[0] * _dot(up, d), up[1] - d[1] * _dot(up, d), up[2] - d[2] * _dot(up, d))
    if math.sqrt(_dot(u, u)) < 1e-9:
        raise ValueError("up is along the viewing direction")
    u = _unit(u)
    back = (-d[0], -d[1], -d[2])
    right = _cross(u, back)
    return right, u, back


def quaternion(direction, up):
    """The camera orientation (x, y, z, w) that looks along direction with up on top: it turns the
    camera's -Z onto direction and +Y onto up (Coin's and FreeCAD's convention)."""
    r, u, b = frame(direction, up)
    m = ((r[0], u[0], b[0]), (r[1], u[1], b[1]), (r[2], u[2], b[2]))     # columns: right, up, back
    t = m[0][0] + m[1][1] + m[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x = 0.25 * s, (m[2][1] - m[1][2]) / s
        y, z = (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        w, x = (m[2][1] - m[1][2]) / s, 0.25 * s
        y, z = (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        w, x = (m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s
        y, z = 0.25 * s, (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        w, x = (m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s
        y, z = (m[1][2] + m[2][1]) / s, 0.25 * s
    return x, y, z, w


def rotate(q, v):
    """v turned by the quaternion q (x, y, z, w)."""
    x, y, z, w = q
    t = _cross((x, y, z), v)
    t = (2 * t[0], 2 * t[1], 2 * t[2])
    c = _cross((x, y, z), t)
    return (v[0] + w * t[0] + c[0], v[1] + w * t[1] + c[1], v[2] + w * t[2] + c[2])


def label_point(corners, size, direction, up, row):
    """Where the row-th PMI label of a view sits: a column left of the part as the view shows it, rows
    downwards from its top edge, in the plane through the part's centre facing the viewer.
    corners: the 8 corners of the part's box."""
    right, u, _ = frame(direction, up)
    xs = [_dot(c, right) for c in corners]
    ys = [_dot(c, u) for c in corners]
    centre = tuple(sum(c[i] for c in corners) / len(corners) for i in range(3))
    along_r = min(xs) - 0.35 * size - _dot(centre, right)
    along_u = max(ys) + 0.1 * size - 0.14 * size * row - _dot(centre, u)
    return tuple(centre[i] + right[i] * along_r + u[i] * along_u for i in range(3))


def label_row(corners, size, direction, up, point, exact=False):
    """The row a label at point is in (the inverse of label_point); exact: unrounded, for a label that
    spans rows and sits between them."""
    _, u, _ = frame(direction, up)
    top = max(_dot(c, u) for c in corners) + 0.1 * size
    r = (top - _dot(point, u)) / (0.14 * size)
    return r if exact else round(r)


def rows_taken(centre, span):
    """The rows a label spanning span rows, centred at row centre, occupies."""
    first = round(centre - (span - 1) / 2)
    return set(range(first, first + span))


def free_rows(used, span):
    """The first run of span rows none of which is used; returns the centre row of the run."""
    r = 0
    while any(x in used for x in range(r, r + span)):
        r += 1
    return r + (span - 1) / 2


def shown(views, work):
    """Whether a PMI displayed in views (names; empty = all views) shows while work (a name or None) is
    the work view."""
    return work is None or not views or work in views

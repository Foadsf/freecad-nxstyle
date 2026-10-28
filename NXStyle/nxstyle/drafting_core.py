# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's Projected View, the geometry (no FreeCAD needed, so the unit tests can check it).

A TechDraw view looks along -Direction (Direction points from the part to the viewer); its paper x is
XDirection and its paper y is Direction x XDirection. A projected view placed beside its parent turns the
part a quarter turn about the paper axis across that side:

- third angle (ASME): the view placed to the right shows the right side, so its viewer sits on the parent's
  paper +x; the view placed above shows the top, its viewer on the parent's paper +y;
- first angle (ISO): the view placed to the right shows the left side, its viewer on the parent's paper -x.

A side view keeps the parent's paper y (its XDirection is y x Direction); a view above or below keeps the
parent's paper x. Projected views keep their parent's scale and line up with it: a side view at the parent's
paper Y, a view above or below at its paper X (Leu et al., NX 12 for Engineering Design, 5.2)."""

SIDES = ("Above", "Right", "Below", "Left")
GAP = 20.0               # mm of paper between a parent view and its projected view


def add(a, b):
    return tuple(p + q for p, q in zip(a, b))


def scale(a, k):
    return tuple(p * k for p in a)


def dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    n = dot(a, a) ** 0.5
    if n < 1e-12:
        raise ValueError("zero vector")
    return scale(a, 1.0 / n)


def paper_axes(direction, xdirection):
    """(x, y, d): the view's paper x and y in the model, and its Direction, all unit vectors."""
    d = unit(direction)
    x = unit(add(xdirection, scale(d, -dot(xdirection, d))))      # XDirection squared up to Direction
    return x, cross(d, x), d


def projected(direction, xdirection, side, projection="Third angle"):
    """(Direction, XDirection) of the view projected from a parent view onto one side of it."""
    if side not in SIDES:
        raise ValueError(f"side {side!r}: one of {', '.join(SIDES)}")
    x, y, _ = paper_axes(direction, xdirection)
    toward = {"Right": x, "Left": scale(x, -1), "Above": y, "Below": scale(y, -1)}[side]
    first = projection.lower().startswith("first")
    d = scale(toward, -1) if first else toward
    if side in ("Right", "Left"):
        return d, cross(y, d)            # keeps the parent's paper y
    return d, x                          # keeps the parent's paper x


def extent(points, direction, xdirection):
    """(width, height, centre x, centre y) on the paper (unscaled) of model points seen in a view."""
    x, y, _ = paper_axes(direction, xdirection)
    us = [dot(p, x) for p in points]
    vs = [dot(p, y) for p in points]
    return max(us) - min(us), max(vs) - min(vs), (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2


ARROW = (3.0, 1.0)       # leader arrowhead length and width, mm (ISO 129-1's closed filled arrow, 3:1)
MARGIN = 1.0             # mm of empty SVG round a leader


def leader(tip, knee, stub):
    """A note's leader on the sheet (mm, y up): from the arrow's tip on the terminating object to the knee, then a
    horizontal stub towards the text (stub < 0 runs left). Returns (svg body, width, height, centre, text start):
    the SVG in its own box (y down), where that box's centre goes on the sheet, and where the stub ends."""
    end = (knee[0] + stub, knee[1])
    xs, ys = (tip[0], knee[0], end[0]), (tip[1], knee[1], end[1])
    x0, x1 = min(xs) - MARGIN - ARROW[0], max(xs) + MARGIN + ARROW[0]
    y0, y1 = min(ys) - MARGIN - ARROW[0], max(ys) + MARGIN + ARROW[0]

    def svg(p):
        return p[0] - x0, y1 - p[1]
    (tx, ty), (kx, ky), (ex, ey) = svg(tip), svg(knee), svg(end)
    dx, dy = tx - kx, ty - ky
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / n, dy / n                       # along the leader, towards the tip
    bx, by = tx - ux * ARROW[0], ty - uy * ARROW[0]
    w2 = ARROW[1] / 2
    body = (f'<path d="M {ex:.3f} {ey:.3f} L {kx:.3f} {ky:.3f} L {bx:.3f} {by:.3f}" fill="none" stroke="black" '
            f'stroke-width="0.25"/>'
            f'<path d="M {tx:.3f} {ty:.3f} L {bx - uy * w2:.3f} {by + ux * w2:.3f} L {bx + uy * w2:.3f} '
            f'{by - ux * w2:.3f} Z" fill="black" stroke="none"/>')
    return body, x1 - x0, y1 - y0, ((x0 + x1) / 2, (y0 + y1) / 2), end


def arrow_tip(svg_centre, width, height, tip_in_svg):
    """Inverse of leader(): where a point of the leader's SVG lies on the sheet."""
    return svg_centre[0] - width / 2 + tip_in_svg[0], svg_centre[1] + height / 2 - tip_in_svg[1]


def place(parent_xy, parent_size, child_size, side, scale_, gap=GAP):
    """Where the projected view's centre goes on the sheet (mm): beside the parent on that side, a gap of
    paper between their outlines, lined up with the parent. Sizes are (width, height) in model mm."""
    px, py = parent_xy
    if side in ("Right", "Left"):
        off = (parent_size[0] + child_size[0]) / 2 * scale_ + gap
        return (px + off if side == "Right" else px - off), py
    off = (parent_size[1] + child_size[1]) / 2 * scale_ + gap
    return px, (py + off if side == "Above" else py - off)

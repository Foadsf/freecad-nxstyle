# SPDX-License-Identifier: LGPL-2.1-or-later
"""How NX-Style's MB2 rotation turns the camera under FreeCAD's orbit style. Pure maths, no FreeCAD.

FreeCAD keeps the orbit style in BaseApp/Preferences/View/OrbitStyle (Preferences › Display › Navigation ›
Orbit style); its navigation styles turn the camera through Gui::NavigationStyle::spin (src/Gui/Navigation/
NavigationStyle.cpp, FreeCAD 1.1.0), which NX-Style's own MB2 handling bypasses. This module gives NX-Style's
rotation the same axes:

    0 Turntable          one axis per mouse move: about the world Z axis (horizontal) or the screen's
                         horizontal axis (vertical), whichever the move is mostly along; the horizon stays level
    1 Trackball          a virtual trackball: the axis follows where the pointer is, so a drag near the window's
                         edge rolls the view about the view direction
    2 Free Turntable     both parts of every move: about world Z, then about the screen's horizontal axis
    3 Trackball Classic  about the screen's vertical and horizontal axes: NX's own rotation
    4 Rounded Arcball    a trackball (FreeCAD rounds its sphere's rim; the axes are a trackball's)

With no orbit style set (the parameter is missing, as in a new NX profile) the rotation is NX's own, about the
screen's axes. How far the view turns is NX-Style's "rotate_degrees_per_pixel" in every style.
"""

import math

TURNTABLE, TRACKBALL, FREE_TURNTABLE, TRACKBALL_CLASSIC, ROUNDED_ARCBALL = range(5)
NAMES = {TURNTABLE: "Turntable", TRACKBALL: "Trackball", FREE_TURNTABLE: "Free Turntable",
         TRACKBALL_CLASSIC: "Trackball Classic", ROUNDED_ARCBALL: "Rounded Arcball"}

NX = "nx"                       # NX's own: about the screen's vertical and horizontal axes
SCREEN = NX
TURN = "turntable"
FREE_TURN = "free_turntable"
BALL = "trackball"
MODES = {TURNTABLE: TURN, TRACKBALL: BALL, FREE_TURNTABLE: FREE_TURN, TRACKBALL_CLASSIC: SCREEN,
         ROUNDED_ARCBALL: BALL}
SPHERE_RADIUS = 0.8             # FCSphereSheetProjector::defaultSphereRadius, in a [-1, 1] window


def mode(orbit_style, setting="freecad"):
    """The rotation NX-Style's MB2 uses: NX's own when the "orbit_style" setting is "nx" or FreeCAD has no orbit
    style (None or negative: the parameter is missing), else the one FreeCAD's orbit style names. An unknown
    number (a FreeCAD newer than this list) keeps NX's own."""
    if setting == "nx" or orbit_style is None or orbit_style < 0:
        return NX
    return MODES.get(int(orbit_style), NX)


def sphere_point(x, y, r=SPHERE_RADIUS):
    """A window point (x, y in [-1, 1], y up) on the trackball: a sphere of radius r, and outside its rim the
    hyperbolic sheet z = r²/2d that meets it smoothly (Bell's trackball, as Coin's SbSphereSheetProjector)."""
    d2 = x * x + y * y
    if d2 <= r * r / 2.0:
        return x, y, math.sqrt(r * r - d2)
    return x, y, r * r / (2.0 * math.sqrt(d2))


def window_point(px, py, width, height):
    """Pixel (Qt: y down) -> [-1, 1] window coordinates, y up, as FreeCAD normalises a pointer for the spin."""
    return 2.0 * px / max(width - 1, 1) - 1.0, 1.0 - 2.0 * py / max(height - 1, 1)


def trackball_axis(last, cur, width, height):
    """The camera-local axis (x right, y up, z towards the viewer) a trackball turns the model about when the
    pointer moves from last to cur (pixels), or None for no move. The model turns the way the pointer drags it."""
    a = sphere_point(*window_point(last[0], last[1], width, height))
    b = sphere_point(*window_point(cur[0], cur[1], width, height))
    axis = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    n = math.sqrt(sum(c * c for c in axis))
    return tuple(c / n for c in axis) if n > 1e-12 else None


def steps(how, dx, dy, k, up_z=1.0, last=None, cur=None, size=None):
    """The camera turns for one mouse move of (dx, dy) pixels, applied in order: a list of (axis, radians), the
    axis "up" or "right" (the camera's, as it is after the turns before it), "z" (world Z) or a camera-local
    (x, y, z) vector; the angle turns the camera (right-handed), so the model appears to turn the other way. The
    signs are NX's own rotation's, so a drag to the right turns the model the same way in every style.
    up_z: the world Z component of the camera's up vector, so a turntable keeps that sense when the view is upside
    down. last, cur, size: the pointer before and after (pixels) and the window's (width, height), for a trackball."""
    if how == TURN:
        if abs(dy) > abs(dx):
            return [("right", -dy * k)]
        return [("z", -dx * k * (1.0 if up_z >= 0 else -1.0))] if dx else []
    if how == FREE_TURN:
        out = [("z", -dx * k * (1.0 if up_z >= 0 else -1.0))] if dx else []
        return out + ([("right", -dy * k)] if dy else [])
    if how == BALL and last is not None and cur is not None and size:
        axis = trackball_axis(last, cur, size[0], size[1])
        return [(axis, -k * math.hypot(dx, dy))] if axis else []
    return [("up", -dx * k), ("right", -dy * k)]

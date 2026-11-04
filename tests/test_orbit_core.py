# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX-Style's MB2 rotation under FreeCAD's orbit style (nxstyle/orbit_core.py): which rotation each OrbitStyle
value gives, and that the turns it asks for keep a turntable's horizon level, against a small rotation model of
the camera (Rodrigues' formula). No FreeCAD needed; smoke_navigation.py drives the real view."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import orbit_core as oc  # noqa: E402

K = math.radians(0.4)


def rot(v, axis, angle):
    """v turned about the unit axis by angle (right-handed)."""
    n = math.sqrt(sum(a * a for a in axis))
    ax = [a / n for a in axis]
    c, s = math.cos(angle), math.sin(angle)
    dot = sum(a * b for a, b in zip(ax, v))
    cross = (ax[1] * v[2] - ax[2] * v[1], ax[2] * v[0] - ax[0] * v[2], ax[0] * v[1] - ax[1] * v[0])
    return tuple(v[i] * c + cross[i] * s + ax[i] * dot * (1 - c) for i in range(3))


class Camera:
    """A camera frame (right, up, back = towards the viewer) turned as navigation.NxMouse.rotate turns it."""

    def __init__(self, right, up):
        self.right, self.up = right, up
        self.back = (right[1] * up[2] - right[2] * up[1], right[2] * up[0] - right[0] * up[2],
                     right[0] * up[1] - right[1] * up[0])

    def apply(self, steps):
        for axis, angle in steps:
            if axis == "z":
                vec = (0, 0, 1)
            elif axis == "up":
                vec = self.up
            elif axis == "right":
                vec = self.right
            else:                                    # camera-local
                vec = tuple(axis[0] * self.right[i] + axis[1] * self.up[i] + axis[2] * self.back[i]
                            for i in range(3))
            self.right, self.up, self.back = (rot(v, vec, angle) for v in (self.right, self.up, self.back))


def isometric():
    s2, s6 = 1 / math.sqrt(2), 1 / math.sqrt(6)
    return Camera((s2, -s2, 0.0), (-s6, -s6, 2 * s6))     # FreeCAD's isometric: right level, up towards +Z


class ModeTests(unittest.TestCase):
    def test_no_orbit_style_is_nx_own_rotation(self):
        """A new NX profile has no OrbitStyle: NX's rotation stays the default."""
        self.assertEqual(oc.mode(None), oc.NX)
        self.assertEqual(oc.mode(-1), oc.NX)

    def test_each_freecad_orbit_style(self):
        self.assertEqual([oc.mode(i) for i in range(5)],
                         [oc.TURN, oc.BALL, oc.FREE_TURN, oc.NX, oc.BALL])

    def test_setting_nx_keeps_nx_rotation_whatever_freecad_says(self):
        self.assertEqual({oc.mode(i, "nx") for i in range(5)}, {oc.NX})

    def test_unknown_style_number_keeps_nx_rotation(self):
        self.assertEqual(oc.mode(9), oc.NX)


class StepTests(unittest.TestCase):
    def test_nx_rotation_is_about_the_screen_axes(self):
        self.assertEqual(oc.steps(oc.NX, 6, 2, K), [("up", -6 * K), ("right", -2 * K)])

    def test_turntable_takes_only_the_main_direction_of_a_move(self):
        self.assertEqual(oc.steps(oc.TURN, 6, 2, K), [("z", -6 * K)])
        self.assertEqual(oc.steps(oc.TURN, 2, 6, K), [("right", -6 * K)])

    def test_free_turntable_takes_both(self):
        self.assertEqual(oc.steps(oc.FREE_TURN, 6, 2, K), [("z", -6 * K), ("right", -2 * K)])

    def test_turntable_keeps_its_sense_upside_down(self):
        self.assertEqual(oc.steps(oc.FREE_TURN, 6, 0, K, up_z=-0.5), [("z", 6 * K)])

    def test_trackball_at_the_centre_turns_like_nx(self):
        """Near the window's centre a trackball drag to the right turns about the camera's up axis, the same way."""
        (axis, angle), = oc.steps(oc.BALL, 6, 0, K, last=(497, 400), cur=(503, 400), size=(1000, 800))
        self.assertAlmostEqual(axis[1], 1.0, places=3)
        self.assertAlmostEqual(angle, -6 * K)

    def test_trackball_at_the_edge_rolls(self):
        """At the right edge a vertical drag turns mostly about the view direction (z): FreeCAD's trackball roll."""
        (axis, _), = oc.steps(oc.BALL, 0, 8, K, last=(992, 392), cur=(992, 400), size=(1000, 800))
        self.assertGreater(abs(axis[2]), 0.9)


class CameraTests(unittest.TestCase):
    """The turns applied to an isometric camera: a diagonal drag of 10 moves of (6, 2.5) pixels."""

    def drag(self, how):
        cam = isometric()
        for _ in range(10):
            cam.apply(oc.steps(how, 6, 2.5, K, up_z=cam.up[2]))
        return cam

    def test_free_turntable_keeps_the_horizon_level(self):
        self.assertAlmostEqual(self.drag(oc.FREE_TURN).right[2], 0.0, places=9)

    def test_turntable_keeps_the_horizon_level(self):
        self.assertAlmostEqual(self.drag(oc.TURN).right[2], 0.0, places=9)

    def test_nx_rotation_tilts_it(self):
        """The control: NX's own free rotation turns about the tilted screen-up axis, so the horizon tilts."""
        self.assertGreater(abs(self.drag(oc.NX).right[2]), 0.01)


if __name__ == "__main__":
    unittest.main()

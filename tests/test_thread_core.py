# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX Thread's decisions: the standard thread for a diameter, the profile, the helix, the hand (no FreeCAD)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import thread_core as tc  # noqa: E402

P20 = 25.4 / 20                         # 1/4-20 UNC pitch, 1.27 mm


class Tables(unittest.TestCase):
    def test_quarter_twenty_unc(self):
        t = tc.find("1/4-20 UNC")
        self.assertAlmostEqual(t.major, 6.35, places=12)
        self.assertAlmostEqual(t.pitch, 1.27, places=12)
        self.assertAlmostEqual(t.minor / 25.4, 0.1959, places=4)      # ASME B1.1 basic minor 0.1959 in
        self.assertEqual(t.angle, 60.0)

    def test_iso_basic_minor_diameters(self):
        # ISO 724 D1 for M6 x 1, M10 x 1.5, M20 x 2.5
        for callout, d1 in (("M6 x 1", 4.917), ("M10 x 1.5", 8.376), ("M20 x 2.5", 17.294)):
            with self.subTest(callout=callout):
                self.assertAlmostEqual(tc.find(callout).minor, d1, places=3)

    def test_series_are_ordered_and_callouts_unique(self):
        rows = tc.table()
        self.assertEqual(len({t.callout for t in rows}), len(rows))
        for standard in ("ISO 261 coarse", "ASME B1.1 UNC"):
            series = [t for t in rows if t.standard == standard]
            self.assertTrue(all(a.major < b.major for a, b in zip(series, series[1:])), standard)
            self.assertTrue(all(a.pitch <= b.pitch + 1e-12 for a, b in zip(series, series[1:])), standard)

    def test_minor_is_major_less_five_eighths_of_two_h(self):
        self.assertAlmostEqual(tc.basic_minor(10, 1), 10 - 2 * 5 / 8 * math.sqrt(3) / 2, places=12)


class Nearest(unittest.TestCase):
    def test_inch_shank_takes_unc(self):
        self.assertEqual(tc.nearest(6.35).callout, "1/4-20 UNC")
        self.assertEqual(tc.nearest(12.7).callout, "1/2-13 UNC")
        self.assertEqual(tc.nearest(7.9375).callout, "5/16-18 UNC")

    def test_metric_shank_takes_iso_coarse(self):
        self.assertEqual(tc.nearest(6.0).callout, "M6 x 1")
        self.assertEqual(tc.nearest(8.0).callout, "M8 x 1.25")
        self.assertEqual(tc.nearest(6.2).callout, "M6 x 1")
        self.assertEqual(tc.nearest(6.34).callout, "M6 x 1")          # not an inch size: no UNC

    def test_tie_takes_the_smaller(self):
        self.assertEqual(tc.nearest(6.5).callout, "M6 x 1")

    def test_hole_matched_by_minor_diameter(self):
        self.assertEqual(tc.nearest(5.0, internal=True).callout, "M6 x 1")
        self.assertEqual(tc.nearest(8.5, internal=True).callout, "M10 x 1.5")
        quarter = tc.find("1/4-20 UNC").minor
        self.assertEqual(tc.nearest(round(quarter, 3), internal=True).callout, "1/4-20 UNC")

    def test_no_diameter_refused(self):
        for d in (0, -1, None):
            with self.subTest(d=d), self.assertRaises(tc.CommandError):
                tc.nearest(d)


class Profile(unittest.TestCase):
    def width_at(self, points, r):
        return 2 * max(abs(a) for x, a in points if abs(x - r) < 1e-12)

    def test_external_basic_profile(self):
        t = tc.find("1/4-20 UNC")
        pts = tc.profile(t.major, t.minor, t.pitch, 60, surface=t.major / 2)
        self.assertEqual(len(pts), 6)
        self.assertAlmostEqual(self.width_at(pts, t.minor / 2), P20 / 4, places=6)      # root of the groove
        self.assertAlmostEqual(self.width_at(pts, t.major / 2), 7 * P20 / 8, places=12)  # crest flat P/8 left
        outer = max(x for x, _ in pts)
        self.assertAlmostEqual(outer, t.major / 2 + P20 / 4, places=12)
        # flank at 30 degrees from the radial direction
        (r0, a0), (r1, a1) = pts[1], pts[2]
        self.assertAlmostEqual(math.degrees(math.atan2(a1 - a0, r1 - r0)), 30.0, places=4)

    def test_internal_basic_profile(self):
        t = tc.find("M6 x 1")
        pts = tc.profile(t.major, t.minor, t.pitch, 60, internal=True, surface=2.5)
        self.assertAlmostEqual(self.width_at(pts, t.major / 2), 1 / 8, places=12)        # root flat at D
        self.assertAlmostEqual(self.width_at(pts, t.minor / 2), 3 / 4, places=6)         # crest flat P/4 left
        self.assertAlmostEqual(min(x for x, _ in pts), min(t.minor / 2, 2.5) - 0.25, places=12)

    def test_profile_reaches_past_a_larger_shank(self):
        pts = tc.profile(6.0, tc.basic_minor(6, 1), 1.0, 60, surface=3.4)
        self.assertAlmostEqual(max(x for x, _ in pts), 3.4 + 0.25, places=12)

    def test_flanks_that_meet_refused(self):
        with self.assertRaises(tc.CommandError) as e:
            tc.profile(6.0, 3.0, 1.0, 60)
        self.assertIn("flanks meet", str(e.exception))
        with self.assertRaises(tc.CommandError):
            tc.profile(6.0, 3.0, 1.0, 60, internal=True)

    def test_bad_values_refused(self):
        for args in ((6, 6, 1, 60), (6, 7, 1, 60), (6, 5, 0, 60), (6, 5, 1, 0), (6, 5, 1, 150), (0, -1, 1, 60)):
            with self.subTest(args=args), self.assertRaises(tc.CommandError):
                tc.profile(*args)


class Helix(unittest.TestCase):
    def test_starts_a_pitch_outside_and_ends_at_length(self):
        t = tc.find("1/4-20 UNC")
        pts = tc.profile(t.major, t.minor, t.pitch, 60, surface=3.175)
        h = tc.helix(38.1, t.pitch, pts)
        self.assertAlmostEqual(h["start"], -1.27)
        # the profile's far flank: centre start + height + half span = Length
        self.assertAlmostEqual(h["start"] + h["height"] + tc.half_span(pts), 38.1, places=12)
        self.assertAlmostEqual(h["turns"], h["height"] / 1.27, places=12)

    def test_too_short_refused(self):
        pts = tc.profile(6, tc.basic_minor(6, 1), 1, 60)
        for length in (0, 0.4, None):
            with self.subTest(length=length), self.assertRaises(tc.CommandError):
                tc.helix(length, 1, pts)

    def test_rotation(self):
        self.assertFalse(tc.left_handed("Right Hand"))
        self.assertTrue(tc.left_handed("Left Hand"))
        with self.assertRaises(tc.CommandError):
            tc.left_handed("Clockwise")


def helix_points(hand, axis=(0, 0, 1), turns=3, n=90):
    """Points of a helix about axis through the origin: right hand = counter-clockwise as it advances."""
    d = tc._unit(axis)
    u = tc._perpendicular(d)
    v = tc._cross(d, u)
    sign = 1 if hand == "Right Hand" else -1
    out = []
    for k in range(n + 1):
        t = 2 * math.pi * turns * k / n
        c, s, z = 3 * math.cos(t), 3 * sign * math.sin(t), 0.5 * t
        out.append(tuple(c * a + s * b + z * e for a, b, e in zip(u, v, d)))
    return out


class Handedness(unittest.TestCase):
    def test_right_and_left(self):
        for axis in ((0, 0, 1), (1, 0, 0), (1, 2, -3)):
            for hand in tc.ROTATIONS:
                with self.subTest(axis=axis, hand=hand):
                    pts = helix_points(hand, axis)
                    self.assertEqual(tc.handedness(pts, (0, 0, 0), axis), hand)
                    # whichever way it is followed, and whichever way the axis points
                    self.assertEqual(tc.handedness(pts[::-1], (0, 0, 0), axis), hand)
                    self.assertEqual(tc.handedness(pts, (0, 0, 0), tuple(-c for c in axis)), hand)

    def test_not_a_helix(self):
        circle = [(math.cos(t / 10), math.sin(t / 10), 0) for t in range(60)]
        self.assertIsNone(tc.handedness(circle, (0, 0, 0), (0, 0, 1)))
        line = [(1, 0, z) for z in range(10)]
        self.assertIsNone(tc.handedness(line, (0, 0, 0), (0, 0, 1)))


class Start(unittest.TestCase):
    def test_nearest_end_and_reverse(self):
        self.assertEqual(tc.start_end((0, 38.1), 37), (38.1, -1, 38.1))
        self.assertEqual(tc.start_end((38.1, 0), 1), (0, 1, 38.1))
        self.assertEqual(tc.start_end((0, 38.1), 37, reverse=True), (0, 1, 38.1))

    def test_no_length_refused(self):
        with self.assertRaises(tc.CommandError):
            tc.start_end((5, 5), 5)

    def test_length_past_the_end_refused(self):
        tc.check_length(38.1, 38.1)
        with self.assertRaises(tc.CommandError):
            tc.check_length(40, 38.1)


class RemovedVolume(unittest.TestCase):
    def test_rectangle_profile(self):
        rect = [(1, -0.25), (2, -0.25), (2, 0.25), (1, 0.25)]
        turns = 9.75                                # (Length - half span) / Pitch
        ring = lambda a, b: 0.5 * (b * b - a * a) / 2       # noqa: E731  first moment of a 0.5-wide band
        self.assertAlmostEqual(tc.removed_volume(rect, 10, 1, 3), 2 * math.pi * turns * ring(1, 2), places=12)
        self.assertAlmostEqual(tc.removed_volume(rect, 10, 1, 1.5), 2 * math.pi * turns * ring(1, 1.5), places=12)
        self.assertAlmostEqual(tc.removed_volume(rect, 10, 1, 1.5, internal=True),
                               2 * math.pi * turns * ring(1.5, 2), places=12)
        self.assertEqual(tc.removed_volume(rect, 10, 1, 0.5), 0.0)

    def test_book_screw_against_numeric_integration(self):
        t = tc.find("1/4-20 UNC")
        pts = tc.profile(t.major, t.minor, t.pitch, 60, surface=3.175)
        n, a, b = 20000, t.minor / 2, 3.175
        slope = math.tan(math.radians(30))
        moment = sum((a + (i + .5) * (b - a) / n) * (P20 / 4 + 2 * slope * (i + .5) * (b - a) / n) * (b - a) / n
                     for i in range(n))
        want = 2 * math.pi * (38.1 - 7 * P20 / 16) / P20 * moment
        got = tc.removed_volume(pts, 38.1, t.pitch, 3.175)
        self.assertAlmostEqual(got, want, delta=1e-6 * want)
        # measured in FreeCAD 1.1.4: the PartDesign SubtractiveHelix removed 264.0593 mm3
        self.assertAlmostEqual(got, 264.0593, delta=1e-3)


class Surface(unittest.TestCase):
    def test_issues(self):
        self.assertIsNone(tc.surface_issue(6.35, 4.97, 6.35, False))
        self.assertIn("larger than the Major", tc.surface_issue(6.0, 4.9, 6.35, False))
        self.assertIn("crests are cut flat", tc.surface_issue(6.0, 4.9, 5.9, False))
        self.assertIsNone(tc.surface_issue(6.0, 4.917, 5.0, True))
        self.assertIn("wall stays", tc.surface_issue(6.0, 5.2, 5.0, True))
        self.assertIn("no thread", tc.surface_issue(6.0, 4.9, 6.0, True))


class Records(unittest.TestCase):
    def test_callout_of_table_values_and_custom(self):
        t = tc.find("M6 x 1")
        self.assertEqual(tc.callout_for(t.major, t.minor, t.pitch, t.angle), ("M6 x 1", "ISO 261 coarse"))
        self.assertEqual(tc.callout_for(6, 4.8, 1, 60)[1], "custom")

    def test_record(self):
        r = tc.record("Detailed", tc.find("1/4-20 UNC"), 38.1, "Right Hand", False)
        self.assertEqual(r["NX_Callout"], "1/4-20 UNC")
        self.assertEqual(r["NX_ThreadType"], "Detailed")
        self.assertAlmostEqual(r["NX_Pitch"], 1.27)

    def test_frame_is_right_handed_along_the_thread(self):
        for d in ((0, 0, -1), (1, 0, 0), (0.3, -0.4, 0.5)):
            o, x, y, z = tc.frame((1, 2, 3), d)
            self.assertAlmostEqual(tc._dot(x, y), 0, places=12)
            self.assertAlmostEqual(tc._dot(y, tc._unit(d)), 1, places=12)
            self.assertTrue(all(abs(a - b) < 1e-12 for a, b in zip(tc._cross(x, y), z)))


if __name__ == "__main__":
    unittest.main()

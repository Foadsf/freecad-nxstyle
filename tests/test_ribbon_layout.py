# SPDX-License-Identifier: LGPL-2.1-or-later
"""Responsive ribbon: the fitting plan, the saved user layout and the window-size matrix; no FreeCAD needed."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import ribbon_layout as rl  # noqa: E402
from nxstyle.ribbon_layout import COLLAPSED, COMPACT, FULL, OVERFLOW  # noqa: E402


def group(full, compact, collapsed, rank=0, index=0, pref=rl.AUTO):
    return rl.GroupFit({FULL: full, COMPACT: compact, COLLAPSED: collapsed, OVERFLOW: 0}, rank, index, pref)


def page(*specs):
    return [group(*s[:3], index=i, **(s[3] if len(s) > 3 else {})) for i, s in enumerate(specs)]


class Plan(unittest.TestCase):
    def test_everything_full_when_it_fits(self):
        gs = page((100, 60, 40), (100, 60, 40))
        self.assertEqual(rl.plan(gs, 200), [FULL, FULL])

    def test_rightmost_group_gives_way_first(self):
        gs = page((100, 60, 40), (100, 60, 40), (100, 60, 40))
        self.assertEqual(rl.plan(gs, 300), [FULL, FULL, FULL])
        self.assertEqual(rl.plan(gs, 260), [FULL, FULL, COMPACT])
        self.assertEqual(rl.plan(gs, 220), [FULL, COMPACT, COMPACT])

    def test_compact_everywhere_before_collapsing_anything(self):
        gs = page((100, 60, 40), (100, 60, 40), (100, 60, 40))
        self.assertEqual(rl.plan(gs, 180), [COMPACT, COMPACT, COMPACT])
        self.assertEqual(rl.plan(gs, 160), [COMPACT, COMPACT, COLLAPSED])

    def test_higher_rank_keeps_its_space_longer(self):
        gs = page((100, 60, 40), (100, 60, 40, {"rank": 10}), (100, 60, 40))
        self.assertEqual(rl.plan(gs, 220), [COMPACT, FULL, COMPACT])

    def test_keep_expanded_goes_last_even_above_rank(self):
        gs = page((100, 60, 40, {"rank": 10}), (100, 60, 40, {"pref": rl.EXPANDED}))
        self.assertEqual(rl.plan(gs, 160), [COMPACT, FULL])
        # but it still gives way rather than leave the page clipped
        self.assertEqual(rl.plan(gs, 100), [COLLAPSED, COMPACT])

    def test_always_collapsed_even_when_there_is_room(self):
        gs = page((100, 60, 40), (100, 60, 40, {"pref": COLLAPSED}))
        self.assertEqual(rl.plan(gs, 1000), [FULL, COLLAPSED])

    def test_overflow_counts_the_more_button(self):
        gs = page((100, 60, 40), (100, 60, 40), (100, 60, 40))
        stages = rl.plan(gs, 100, overflow_width=30)
        self.assertEqual(stages, [COLLAPSED, OVERFLOW, OVERFLOW])
        self.assertLessEqual(rl.plan_width(gs, stages, overflow_width=30), 100)

    def test_result_fits_whenever_possible(self):
        gs = page((180, 90, 50), (240, 150, 60, {"rank": 10}), (120, 120, 120), (90, 50, 45))
        for avail in range(0, 700, 7):
            stages = rl.plan(gs, avail, base=4, overflow_width=40)
            if avail >= 4 + 40:
                with self.subTest(avail=avail):
                    self.assertLessEqual(rl.plan_width(gs, stages, base=4, overflow_width=40), avail)

    def test_wider_never_reduces_more(self):
        """More room never makes a group smaller: a plan is a prefix of one fixed sequence of steps."""
        gs = page((180, 90, 50), (240, 150, 60), (120, 80, 45), (90, 50, 45, {"rank": 5}),
                  (300, 300, 40, {"pref": rl.EXPANDED}))
        prev = None
        for avail in range(50, 1200, 5):
            stages = [rl.STAGES.index(s) for s in rl.plan(gs, avail, overflow_width=40)]
            if prev is not None:
                with self.subTest(avail=avail):
                    self.assertTrue(all(a <= b for a, b in zip(stages, prev)))
            prev = stages

    def test_less_important_groups_collapse_before_an_essential_one_loses_its_labels(self):
        gs = page((300, 120, 50, {"rank": 10}), (100, 60, 40), (100, 60, 40))
        self.assertEqual(rl.plan(gs, 390), [FULL, COLLAPSED, COLLAPSED])
        self.assertEqual(rl.plan(gs, 200), [COMPACT, COLLAPSED, COLLAPSED])

    def test_base_margins_are_counted(self):
        gs = page((100, 60, 40))
        self.assertEqual(rl.plan(gs, 100, base=4), [COMPACT])


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_round_trip_through_the_file(self):
        s = rl.LayoutStore(self.dir)
        s.set_preference("modeling", "Home", "Feature", rl.EXPANDED)
        s.set_preference("modeling", "View", "Orientation", COLLAPSED)
        s.set_minimized(True)
        again = rl.LayoutStore(self.dir)
        self.assertEqual(again.preference("modeling", "Home", "Feature"), rl.EXPANDED)
        self.assertEqual(again.preference("modeling", "View", "Orientation"), COLLAPSED)
        self.assertEqual(again.preference("drafting", "Home", "Feature"), rl.AUTO)   # per application
        self.assertTrue(again.minimized)

    def test_automatic_removes_the_entry(self):
        s = rl.LayoutStore(self.dir)
        s.set_preference("modeling", "Home", "Feature", COLLAPSED)
        s.set_preference("modeling", "Home", "Feature", rl.AUTO)
        with open(s.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["groups"], {})

    def test_reset(self):
        s = rl.LayoutStore(self.dir)
        s.set_preference("modeling", "Home", "Feature", COLLAPSED)
        s.set_minimized(True)
        s.reset()
        again = rl.LayoutStore(self.dir)
        self.assertEqual((again.data["groups"], again.minimized), ({}, False))

    def test_unknown_choice_refused(self):
        with self.assertRaises(ValueError):
            rl.LayoutStore(self.dir).set_preference("modeling", "Home", "Feature", "hidden")

    def test_corrupt_file_is_reported_not_fatal(self):
        with open(os.path.join(self.dir, rl.LayoutStore.FILE), "w", encoding="utf-8") as f:
            f.write("{not json")
        s = rl.LayoutStore(self.dir)
        self.assertTrue(s.error)
        self.assertEqual(s.preference("modeling", "Home", "Feature"), rl.AUTO)

    def test_bad_values_in_the_file_are_dropped(self):
        with open(os.path.join(self.dir, rl.LayoutStore.FILE), "w", encoding="utf-8") as f:
            json.dump({"groups": {"a/b/c": "hidden", "a/b/d": "collapsed"}}, f)
        s = rl.LayoutStore(self.dir)
        self.assertEqual(s.data["groups"], {"a/b/d": "collapsed"})

    def test_no_folder_keeps_choices_in_memory(self):
        s = rl.LayoutStore("")
        s.set_preference("modeling", "Home", "Feature", COLLAPSED)
        self.assertEqual(s.preference("modeling", "Home", "Feature"), COLLAPSED)


class Matrix(unittest.TestCase):
    def test_eight_cells_two_resolutions_four_scales(self):
        cells = rl.matrix_cells()
        self.assertEqual(len(cells), 8)
        self.assertEqual({c["screen"] for c in cells}, {(1366, 768), (1920, 1080)})
        self.assertEqual({c["scale"] for c in cells}, {1.0, 1.25, 1.5, 2.0})

    def test_logical_window_sizes(self):
        cells = {c["name"]: c["window"] for c in rl.matrix_cells()}
        bars = rl.TASKBAR + rl.TITLE_BAR
        self.assertEqual(cells["1366x768@100%"], (1366, 768 - bars))
        self.assertEqual(cells["1366x768@200%"], (683, 384 - bars))
        self.assertEqual(cells["1920x1080@150%"], (1280, 720 - bars))
        self.assertEqual(cells["1920x1080@125%"], (1536, 864 - bars))


if __name__ == "__main__":
    unittest.main()

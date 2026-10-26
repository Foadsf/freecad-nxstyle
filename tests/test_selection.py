# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection scope, collectors, curve chains and select-through (no FreeCAD needed)."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import selection_core as sc  # noqa: E402


class Paths(unittest.TestCase):
    def test_split(self):
        self.assertEqual(sc.split("Asm", "UnitB.Box.Face6"), (("Asm", "UnitB", "Box"), "Face6"))
        self.assertEqual(sc.split("Box", "Edge3"), (("Box",), "Edge3"))
        self.assertEqual(sc.split("Asm", "UnitA."), (("Asm", "UnitA"), ""))
        self.assertEqual(sc.split("Box", ""), (("Box",), ""))

    def test_mapped_element_names_are_dropped(self):
        sub = "Round.;Edge10;:M;FLT;:H12dc:7,E.Edge7"
        self.assertEqual(sc.plain(sub), "Round.Edge7")
        self.assertEqual(sc.split("Body", sub), (("Body", "Round"), "Edge7"))
        self.assertEqual(sc.Pick("D", "Body", sub, "edge").key, ("D", "Body", "Round.Edge7"))
        self.assertEqual(sc.plain("UnitA.Box.Face6"), "UnitA.Box.Face6")


class Scope(unittest.TestCase):
    # Asm holds two links, UnitA and UnitB, to the same part Unit (which holds Box), and a bolt of its own
    A = ("Asm", "UnitA", "Box")
    B = ("Asm", "UnitB", "Box")
    COMP = (False, True, False)

    def test_sibling_occurrence_is_outside_the_work_part(self):
        work = ("Asm", "UnitA")
        ok, _ = sc.scope_verdict(self.A, self.COMP, work, "work_part_and_components")
        self.assertTrue(ok)
        ok, why = sc.scope_verdict(self.B, self.COMP, work, "work_part_and_components")
        self.assertFalse(ok)
        self.assertIn("Asm › UnitB is outside the work part Asm › UnitA", why)

    def test_entire_assembly_takes_both(self):
        for p in (self.A, self.B):
            self.assertTrue(sc.scope_verdict(p, self.COMP, ("Asm", "UnitA"), "assembly")[0])

    def test_no_work_part_means_the_whole_document(self):
        self.assertTrue(sc.scope_verdict(self.B, self.COMP, None, "work_part_only")[0])

    def test_work_part_only_refuses_component_geometry(self):
        work = ("Asm",)
        ok, why = sc.scope_verdict(self.A, self.COMP, work, "work_part_only")
        self.assertFalse(ok)
        self.assertIn("component Asm › UnitA", why)
        self.assertTrue(sc.scope_verdict(("Asm", "Bolt"), (False, False), work, "work_part_only")[0])
        self.assertTrue(sc.scope_verdict(self.A, self.COMP, work, "work_part_and_components")[0])

    def test_labels_in_reasons(self):
        _, why = sc.scope_verdict(self.B, self.COMP, ("Asm", "UnitA"), "work_part_and_components",
                                  {"UnitA": "Left unit", "UnitB": "Right unit"})
        self.assertIn("Right unit", why)
        self.assertIn("Left unit", why)


class Collectors(unittest.TestCase):
    def pick(self, sub, kind="edge", owner="Body"):
        return sc.Pick("D", "Body", sub, kind, owner)

    def test_count_validity_and_reasons(self):
        c = sc.Collector("Select Edge", ["edge"], minimum=1, one_owner=True, command="Edge Blend")
        self.assertFalse(c.valid)
        self.assertEqual(c.status(), "Select Edge (0)")
        self.assertIn("select at least 1 edge", c.problem())
        self.assertTrue(c.offer(self.pick("Pad.Edge1"))[0])
        self.assertTrue(c.offer(self.pick("Pad.Edge1"))[0])          # the same edge again: no second copy
        self.assertEqual(c.count, 1)
        ok, why = c.offer(self.pick("Pad.Face2", "face"))
        self.assertFalse(ok)
        self.assertIn("Edge Blend takes an edge; Face2 of Body › Pad is a face", why)
        ok, why = c.offer(sc.Pick("D", "Body001", "Pad.Edge4", "edge", "Body001"))
        self.assertFalse(ok)
        self.assertIn("works on one body", why)
        self.assertTrue(c.valid)
        self.assertEqual(c.status(), "Select Edge (1)")
        self.assertEqual([label for label, _ in c.rejected], ["Face2 of Body › Pad", "Edge4 of Body001 › Pad"])

    def test_maximum(self):
        c = sc.Collector("Select Face", ["face"], minimum=1, maximum=1)
        self.assertTrue(c.offer(self.pick("Pad.Face1", "face"))[0])
        ok, why = c.offer(self.pick("Pad.Face2", "face"))
        self.assertFalse(ok)
        self.assertIn("at most 1", why)

    def test_remove(self):
        c = sc.Collector("Select Edge", ["edge"])
        p = self.pick("Pad.Edge1")
        c.offer(p)
        c.remove(p.key)
        self.assertEqual(c.count, 0)
        self.assertFalse(c.valid)


def unit(x, y, z=0.0):
    n = math.sqrt(x * x + y * y + z * z)
    return (x / n, y / n, z / n)


def line(a, b, pa, pb):
    """A straight edge between vertex keys a and b at points pa, pb."""
    d = unit(pb[0] - pa[0], pb[1] - pa[1])
    return (a, b, d, (-d[0], -d[1], -d[2]))


class Chains(unittest.TestCase):
    def square(self):
        p = {0: (0, 0), 1: (10, 0), 2: (10, 10), 3: (0, 10)}
        return {f"E{i}": line(i, (i + 1) % 4, p[i], p[(i + 1) % 4]) for i in range(4)}

    def obround(self):
        """Two lines joined by two half circles, all tangent: one smooth loop."""
        e = {"L1": line(0, 1, (0, 0), (10, 0)), "L2": line(2, 3, (10, 10), (0, 10))}
        # arc from vertex 1 (10,0) round to vertex 2 (10,10): leaves 1 along +x, reaches 2 heading -x
        e["A1"] = (1, 2, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        e["A2"] = (3, 0, (-1.0, 0.0, 0.0), (-1.0, 0.0, 0.0))
        return e

    def test_single(self):
        self.assertEqual(sc.chain(self.square(), "E0", "single"), ["E0"])

    def test_tangent_stops_at_corners(self):
        self.assertEqual(sc.chain(self.square(), "E0", "tangent"), ["E0"])

    def test_connected_follows_a_wire(self):
        self.assertEqual(sorted(sc.chain(self.square(), "E1", "connected")), ["E0", "E1", "E2", "E3"])

    def test_tangent_follows_a_smooth_loop_once(self):
        got = sc.chain(self.obround(), "L1", "tangent")
        self.assertEqual(sorted(got), ["A1", "A2", "L1", "L2"])
        self.assertEqual(len(got), 4)

    def test_tangent_within_tolerance(self):
        e = {"a": line(0, 1, (0, 0), (10, 0)), "b": line(1, 2, (10, 0), (20, 0.05))}   # 0.29 degrees off
        self.assertEqual(sc.chain(e, "a", "tangent"), ["a", "b"])
        e["b"] = line(1, 2, (10, 0), (20, 1))                                          # 5.7 degrees off
        self.assertEqual(sc.chain(e, "a", "tangent"), ["a"])

    def test_connected_stops_where_three_edges_meet(self):
        e = {"a": line(0, 1, (0, 0), (10, 0)), "b": line(1, 2, (10, 0), (20, 0)),
             "c": line(1, 3, (10, 0), (10, 10))}
        self.assertEqual(sc.chain(e, "a", "connected"), ["a"])
        self.assertEqual(sc.chain(e, "a", "tangent"), ["a", "b"])      # only b continues a smoothly

    def test_tangent_stops_at_an_ambiguous_branch(self):
        e = {"a": line(0, 1, (0, 0), (10, 0)), "b": line(1, 2, (10, 0), (20, 0)),
             "c": line(1, 3, (10, 0), (25, 0))}
        self.assertEqual(sc.chain(e, "a", "tangent"), ["a"])

    def test_closed_edge(self):
        self.assertEqual(sc.chain({"circle": (0, 0, (0, 1, 0), (0, -1, 0))}, "circle", "tangent"), ["circle"])


class SelectThrough(unittest.TestCase):
    def rows(self, oks):
        return sc.dedupe([{"doc": "D", "top": "Asm", "sub": f"S{i}", "ok": ok} for i, ok in enumerate(oks)])

    def test_nearest_allowed_behind_a_refused_one(self):
        self.assertEqual(sc.select_through(self.rows([False, False, True, True]))["sub"], "S2")

    def test_nothing_when_the_nearest_is_allowed_or_none_is(self):
        self.assertIsNone(sc.select_through(self.rows([True, False])))
        self.assertIsNone(sc.select_through(self.rows([False, False])))
        self.assertIsNone(sc.select_through([]))

    def test_dedupe_keeps_the_nearest(self):
        hits = [{"doc": "D", "top": "Asm", "sub": "UnitB.Box.Face6", "z": 40},
                {"doc": "D", "top": "Asm", "sub": "UnitB.Box.Face6", "z": 39},
                {"doc": "D", "top": "Asm", "sub": "UnitA.Box.Face6", "z": 10}]
        self.assertEqual([h["z"] for h in sc.dedupe(hits)], [40, 10])


if __name__ == "__main__":
    unittest.main()

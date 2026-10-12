# SPDX-License-Identifier: LGPL-2.1-or-later
"""GD&T symbol builder (no FreeCAD needed)."""

import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import gdt  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"


def editable(svg):
    """Editable text values in document order, as TechDraw reads them."""
    root = ET.fromstring(svg)
    out = []
    for t in root.iter(NS + "text"):
        if any(k.endswith("editable") for k in t.attrib):
            out.append("".join(t.itertext()))
    return out


class FeatureControlFrame(unittest.TestCase):
    def test_position_frame_has_tolerance_and_datums_as_editable_texts(self):
        svg, w = gdt.feature_control_frame("position", "0.254", True, "MMC", [("A", ""), ("B", ""), ("C", "")])
        self.assertEqual(editable(svg), ["0.254", "A", "B", "C"])
        # symbol cell + tolerance cell + three datum cells: five cells, so four inner walls
        self.assertEqual(len(re.findall(r'<path d="M [\d.]+ 0 V 7.000"', svg)), 4)
        self.assertGreater(w, 4 * gdt.CELL)

    def test_values_are_inside_tspans(self):
        svg, _ = gdt.feature_control_frame("flatness", "0.051")
        self.assertIn('freecad:editable="tolerance"><tspan>0.051</tspan>', svg)

    def test_modifier_draws_a_circled_letter(self):
        with_m, _ = gdt.feature_control_frame("position", "0.1", True, "MMC", [("A", "")])
        without, _ = gdt.feature_control_frame("position", "0.1", True, "", [("A", "")])
        self.assertIn(">M</text>", with_m)
        self.assertNotIn(">M</text>", without)

    def test_unknown_characteristic_is_refused(self):
        with self.assertRaises(ValueError):
            gdt.feature_control_frame("roughness", "0.1")

    def test_text_is_escaped(self):
        svg, _ = gdt.feature_control_frame("flatness", "<0.1&>")
        ET.fromstring(svg)          # still valid XML
        self.assertEqual(editable(svg), ["<0.1&>"])

    def test_callout(self):
        self.assertEqual(gdt.callout("position", "0.254", True, "MMC", [("A", ""), ("B", ""), ("C", "")]),
                         "position | Ø0.254 (M) | A | B | C")


class DatumFeatureSymbol(unittest.TestCase):
    def test_letter_is_editable(self):
        svg, _ = gdt.datum_feature_symbol("B")
        self.assertEqual(editable(svg), ["B"])

    def test_triangle_is_on_the_attachment_side(self):
        for attach in ("bottom", "top", "left", "right"):
            svg, (w, h) = gdt.datum_feature_symbol("A", attach)
            tri = re.findall(r'<path d="(M [^"]+ Z)" fill="black"', svg)[0]
            nums = [float(v) for v in re.findall(r"[-\d.]+", tri)]
            xs, ys = nums[0::2], nums[1::2]
            edge = {"bottom": max(ys) == round(h, 3), "top": min(ys) == 0, "left": min(xs) == 0,
                    "right": max(xs) == round(w, 3)}[attach]
            self.assertTrue(edge, f"{attach}: triangle {tri} not on the {attach} side of {w} x {h}")

    def test_vertical_and_horizontal_sizes(self):
        _, (w1, h1) = gdt.datum_feature_symbol("A", "bottom")
        _, (w2, h2) = gdt.datum_feature_symbol("A", "left")
        self.assertGreater(h1, w1)
        self.assertGreater(w2, h2)


if __name__ == "__main__":
    unittest.main()

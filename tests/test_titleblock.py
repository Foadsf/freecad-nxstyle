# SPDX-License-Identifier: LGPL-2.1-or-later
"""Title block values and the revision block (titleblock.py); no FreeCAD needed."""

import os
import sys
import unittest
import xml.dom.minidom

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import titleblock as tb  # noqa: E402

ISO_FIELDS = ["legal_owner_1", "drawing_number", "revision_index", "date_of_issue", "sheet_number", "title",
              "approval_person", "creator", "document_type", "scale", "general_tolerances", "part_material"]


class Values(unittest.TestCase):
    def test_release_wins_over_attributes_and_properties(self):
        attrs = {"DB_PART_NO": "OLD-1", "DB_PART_REV": "A", "DB_PART_NAME": "PLATE, MOUNTING"}
        info = tb.merge({"part_number": "PLATE-200", "revision": "B"}, tb.from_attributes(attrs), {"title": "Unnamed"})
        self.assertEqual((info["part_number"], info["revision"], info["title"]), ("PLATE-200", "B", "PLATE, MOUNTING"))

    def test_fill_keeps_what_it_cannot_fill(self):
        info = {"part_number": "PLATE-200", "revision": "B", "scale": "1:1"}
        out = tb.fill(ISO_FIELDS, info, keep={"legal_owner_1": "Acme", "title": "kept"})
        self.assertEqual(out["drawing_number"], "PLATE-200")
        self.assertEqual(out["legal_owner_1"], "Acme")
        self.assertEqual(out["title"], "kept")
        self.assertEqual(out["approval_person"], "")
        self.assertEqual(sorted(out), sorted(ISO_FIELDS))

    def test_td_template_names(self):
        v = tb.values({"title": "Plate", "released_by": "F. S.", "mass": "0.25 kg"})
        self.assertEqual((v["FC-Title"], v["AuthorName"], v["Weight"]), ("Plate", "F. S.", "0.25 kg"))

    def test_scale_and_tolerancing_note(self):
        self.assertEqual([tb.scale_text(s) for s in (1.0, 0.5, 0.2, 2.0)], ["1:1", "1:2", "1:5", "2:1"])
        self.assertEqual(tb.tolerancing_note("ISO", "ISO 2768-mK"), "ISO 2768-mK")    # fits the ISO 7200 field
        self.assertEqual(tb.tolerancing_note("ISO", None), "ISO 8015")
        self.assertEqual(tb.tolerancing_note("ASME", None), "ASME Y14.5-2018")

    def test_iso_7200_list(self):
        self.assertIn("drawing_number", tb.ISO_7200)
        self.assertNotIn("FC-Title", tb.ISO_7200)


class RevisionBlock(unittest.TestCase):
    def test_rows_and_wellformed_svg(self):
        svg, w, h = tb.revision_block([("A", "First release", "2026-10-01", "J. Doe"),
                                       ("B", "Holes Ø6.35 H11, composite position 0.05", "2026-10-14", "J. Doe")])
        xml.dom.minidom.parseString(svg)
        self.assertAlmostEqual(h, 4 * tb.ROW)
        self.assertAlmostEqual(w, sum(c for _, c in tb.COLUMNS))
        self.assertIn(">REVISIONS<", svg)
        self.assertIn(">B<", svg)

    def test_long_description_is_cut(self):
        svg, _, _ = tb.revision_block([("A", "x" * 200, "2026-10-01", "J. Doe")])
        self.assertIn("…", svg)
        self.assertNotIn("x" * 100, svg)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Portable catalogue/artwork checks; real QAction tests live beside these."""
import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "NXStyle"))
from nxstyle import icon_theme


class Catalogue(unittest.TestCase):
    def test_aliases_are_unique_and_all_artwork_exists(self):
        data = json.loads((icon_theme.ROOT / "icon-theme.json").read_text(encoding="utf-8"))
        names = [name for group in data.values() for name in group]
        self.assertGreater(len(data), 40)
        self.assertEqual(len(names), len(set(names)), "a command may only have one semantic icon")
        for command in names:
            self.assertIsNotNone(icon_theme.asset_path(command), command)
        self.assertIsNone(icon_theme.asset_path("NXStyle_NotACommand"))
        with patch.object(icon_theme, "ROOT", Path("a-directory-that-does-not-exist")):
            self.assertIsNone(icon_theme.asset_path("PartDesign_Pad"))

    def test_vectors_are_local_editable_and_sized(self):
        for path in (icon_theme.ROOT / "icons" / "nx").glob("*.svg"):
            with self.subTest(icon=path.name):
                root = ET.parse(path).getroot()
                self.assertEqual(root.get("viewBox"), "0 0 32 32")
                for node in root.iter():
                    self.assertNotIn(node.tag.split("}")[-1], ("text", "image", "script", "foreignObject"))
                    for attr, value in node.attrib.items():
                        if attr.split("}")[-1] == "href":
                            self.assertTrue(value.startswith("#"), value)

    def test_creation_and_removal_are_distinct(self):
        for a, b in (("PartDesign_Pad", "PartDesign_Pocket"), ("PartDesign_Revolution", "PartDesign_Groove"),
                     ("Sketcher_ConstrainHorizontal", "Sketcher_ConstrainVertical")):
            self.assertNotEqual(icon_theme.asset_path(a), icon_theme.asset_path(b))
            self.assertNotEqual(icon_theme.asset_path(a).read_bytes(), icon_theme.asset_path(b).read_bytes())


if __name__ == "__main__":
    unittest.main()

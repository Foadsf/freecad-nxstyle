# SPDX-License-Identifier: LGPL-2.1-or-later
"""Theme colour tokens: one definition (theme.py), used by both stylesheets and the Python code."""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import theme  # noqa: E402

PKG = Path(__file__).resolve().parents[1] / "NXStyle" / "nxstyle"
SHEETS = ("nx_theme.qss", "ribbon.qss")
LITERAL = re.compile(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(|\b(?:white|black)\b")
# chrome/theme modules: their colours must come from theme.TOKENS (engineering colours elsewhere, such as
# PMI validity red or the graphics backgrounds, are not theme chrome)
CHROME_MODULES = ("shell.py", "ribbon.py", "finder.py", "plm.py")


def strip_comments(qss):
    return re.sub(r"/\*.*?\*/", "", qss, flags=re.S)


class Tokens(unittest.TestCase):
    def test_stylesheets_name_tokens_not_colours(self):
        for name in SHEETS:
            with self.subTest(sheet=name):
                text = strip_comments((PKG / "resources" / name).read_text(encoding="utf-8"))
                self.assertEqual(LITERAL.findall(text), [])
                self.assertTrue(theme.TOKEN_RE.search(text))

    def test_every_token_used_is_defined(self):
        for name in SHEETS:
            with self.subTest(sheet=name):
                filled = theme.stylesheet(name)            # raises on an unknown token
                self.assertNotIn("@nx-", strip_comments(filled))

    def test_unknown_token_is_an_error(self):
        with self.assertRaises(KeyError):
            theme.fill("QWidget { color: @nx-no-such-colour; }")

    def test_longer_token_names_are_not_cut_short(self):
        self.assertEqual(theme.fill("@nx-tint2 @nx-tint @nx-tintline-strong"),
                         f"{theme.TOKENS['tint2']} {theme.TOKENS['tint']} {theme.TOKENS['tintline-strong']}")

    def test_freecad_placeholders_filled(self):
        out = theme.fill_freecad("a { color: @ThemeAccentColor1; b: @ThemeAccentColor2; c: @ThemeAccentColor3 }")
        self.assertNotIn("@Theme", out)
        self.assertIn(theme.TOKENS["accent"], out)

    def test_values_are_colours(self):
        for k, v in theme.TOKENS.items():
            with self.subTest(token=k):
                self.assertRegex(v, r"^(#[0-9A-F]{6}|rgba\(\d+, \d+, \d+, \d+\))$")

    def test_chrome_modules_have_no_literal_colours(self):
        for name in CHROME_MODULES:
            with self.subTest(module=name):
                src = (PKG / name).read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"[\"']#[0-9A-Fa-f]{6}[\"']", src), [])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: LGPL-2.1-or-later
"""The NX light theme's colours, in one place.

The stylesheets (``nx_theme.qss``, ``ribbon.qss``) name a colour as ``@nx-<token>``; ``stylesheet()``
fills them in from TOKENS when it loads the file. Python code that paints or styles a widget reads
TOKENS too, so a colour is changed here and nowhere else. Original values in the spirit of the NX
light theme; no Siemens assets.
"""

import os
import re

TOKENS = {
    # surfaces
    "chrome": "#EEF1F4",          # window background, bars, ribbon tab row
    "panel": "#FFFFFF",           # navigators, ribbon page, menus
    "panel-alt": "#F5F7F9",       # table headers
    "strip": "#E4E8EC",           # resource bar, inactive document tabs
    "overlay": "rgba(238, 241, 244, 235)",   # chrome over content (ribbon scroll arrows)
    # lines
    "line": "#D5DAE0",            # borders and separators
    "line-soft": "#E1E5E9",       # separators inside a page or menu
    "line-faint": "#E6E9ED",      # table column lines
    "line-disabled": "#DDE1E5",
    "field": "#C3CAD1",           # input and menu borders
    # text
    "text": "#1E2329",
    "text-tab": "#3A4249",        # ribbon tab labels
    "muted": "#5D6670",           # secondary text
    "label": "#6B747D",           # ribbon group labels
    "disabled": "#A3AAB1",
    "disabled-menu": "#9AA1A8",
    "on-accent": "#FFFFFF",       # text on the accent colour
    # accent and its tints
    "accent": "#0B6E79",          # selected tab, focus, File button, cue line
    "accent-hover": "#0D8290",
    "accent-pressed": "#095E68",
    "contextual": "#007A87",      # contextual ribbon tabs (Sketch)
    "tint": "#E3F1F3",            # hover
    "tint-strip": "#D7EDF0",      # hover on the resource bar
    "tint2": "#C7E3E7",           # pressed / selected
    "tintline": "#8CC5CC",        # hover border
    "tintline-strong": "#6FB6BF",  # pressed border
}

# FreeCAD fills these placeholders when it loads one of its own stylesheets; an unfilled one makes Qt
# drop the rules around it. NXStyle fills them with the NX accent tints.
FREECAD_PLACEHOLDERS = {"@ThemeAccentColor1": "accent", "@ThemeAccentColor2": "tintline",
                        "@ThemeAccentColor3": "tint2"}

TOKEN_RE = re.compile(r"@nx-([a-z0-9]+(?:-[a-z0-9]+)*)")
RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def color(name):
    return TOKENS[name]


def fill(text):
    """Replace every @nx-<token> in a stylesheet; an unknown token is an error, not a silent gap."""
    def sub(m):
        try:
            return TOKENS[m.group(1)]
        except KeyError:
            raise KeyError(f"unknown theme token @nx-{m.group(1)}") from None
    return TOKEN_RE.sub(sub, text)


def fill_freecad(text):
    """FreeCAD's own @ThemeAccentColorN placeholders, filled with the NX tints."""
    for placeholder, token in FREECAD_PLACEHOLDERS.items():
        text = text.replace(placeholder, TOKENS[token])
    return text


def stylesheet(name):
    """A stylesheet from resources/ with its tokens filled in."""
    with open(os.path.join(RESOURCES, name), encoding="utf-8") as f:
        return fill(f.read())

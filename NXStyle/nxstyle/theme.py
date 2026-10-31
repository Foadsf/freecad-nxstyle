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
    "chrome": "#F0F4F8",          # window background, bars, ribbon tab row
    "panel": "#FFFFFF",           # navigators, ribbon page, menus
    "panel-alt": "#F7F9FC",       # table headers
    "strip": "#E8EFF5",           # resource bar, inactive document tabs
    "overlay": "rgba(240, 244, 248, 245)",   # chrome over content (ribbon scroll arrows)
    # lines
    "line": "#D6E1EA",            # borders and separators
    "line-soft": "#E5EBF1",       # separators inside a page or menu
    "line-faint": "#EDF1F5",      # table column lines
    "line-disabled": "#E0E6ED",
    "field": "#BCCBD8",           # input and menu borders
    # text
    "text": "#243447",
    "text-tab": "#475569",        # ribbon tab labels
    "muted": "#526579",           # secondary text
    "label": "#526579",           # ribbon group labels
    "disabled": "#8B98A6",
    "disabled-menu": "#8B98A6",
    "on-accent": "#FFFFFF",       # text on the accent colour
    # accent and its tints
    "accent": "#086F7C",          # selected tab, focus, File button, cue line
    "accent-hover": "#075E69",
    "accent-pressed": "#064E59",
    "contextual": "#077C89",      # contextual ribbon tabs (Sketch)
    "tint": "#EAF5F6",            # hover
    "tint-strip": "#DDEEF1",      # hover on the resource bar
    "tint2": "#D5ECEF",           # pressed / selected
    "tintline": "#95C6CC",        # hover border
    "tintline-strong": "#5CABB5",  # pressed border
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

# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX Drafting's Feature Control Frame and Datum Feature Symbol for TechDraw.

FreeCAD 1.1 ships GD&T characteristic symbols as fixed pictures, with no frame
you fill in. These build the frame as an SVG symbol on the sheet (sizes in mm,
ASME Y14.5 proportions: 7 mm frame height for 3.5 mm text). The symbols are
drawn as paths, so they do not depend on a font having GD&T glyphs. Values are
`freecad:editable` texts: the tolerance and the datum letters can be changed
later in the symbol's EditableTexts property.
"""

from xml.sax.saxutils import escape

H = 7.0          # frame height, mm
TEXT = 3.5       # lettering height, mm
STROKE = 0.35
CELL = 7.0       # width of the symbol cell and of a one-letter datum cell
FONT = "osifont, DejaVu Sans, sans-serif"

# characteristic name -> SVG path data in a 7 x 7 cell (origin top left)
SYMBOLS = {
    "position": "M 3.5 1.2 V 5.8 M 1.2 3.5 H 5.8 M 5.1 3.5 A 1.6 1.6 0 1 1 1.9 3.5 A 1.6 1.6 0 1 1 5.1 3.5",
    "flatness": "M 1.0 5.0 L 2.6 2.0 H 6.0 L 4.4 5.0 Z",
    "straightness": "M 1.0 3.5 H 6.0",
    "circularity": "M 5.6 3.5 A 2.1 2.1 0 1 1 1.4 3.5 A 2.1 2.1 0 1 1 5.6 3.5",
    "cylindricity": "M 4.9 3.5 A 1.6 1.6 0 1 1 1.7 3.5 A 1.6 1.6 0 1 1 4.9 3.5 M 1.6 6.0 L 3.3 1.0 M 3.3 6.0 L 5.0 1.0",
    "perpendicularity": "M 1.0 5.5 H 6.0 M 3.5 5.5 V 1.3",
    "parallelism": "M 1.6 5.8 L 3.4 1.2 M 3.6 5.8 L 5.4 1.2",
    "angularity": "M 1.0 5.5 H 6.0 M 1.0 5.5 L 5.4 1.6",
    "profile of a surface": "M 1.2 5.0 A 2.3 2.3 0 0 1 5.8 5.0 Z",
    "profile of a line": "M 1.2 5.0 A 2.3 2.3 0 0 1 5.8 5.0",
    "concentricity": ("M 5.6 3.5 A 2.1 2.1 0 1 1 1.4 3.5 A 2.1 2.1 0 1 1 5.6 3.5 "
                      "M 4.5 3.5 A 1.0 1.0 0 1 1 2.5 3.5 A 1.0 1.0 0 1 1 4.5 3.5"),
    "symmetry": "M 1.0 3.5 H 6.0 M 1.8 2.2 H 5.2 M 1.8 4.8 H 5.2",
    "circular runout": "M 1.2 5.6 L 5.0 1.8 M 5.0 1.8 L 3.6 2.2 M 5.0 1.8 L 4.6 3.2",
    "total runout": ("M 1.0 5.6 L 3.8 1.8 M 3.8 1.8 L 2.6 2.1 M 3.8 1.8 L 3.5 3.0 M 3.0 5.6 L 5.8 1.8 "
                     "M 5.8 1.8 L 4.6 2.1 M 5.8 1.8 L 5.5 3.0 M 1.0 5.6 H 3.0"),
}
CHARACTERISTICS = list(SYMBOLS)
MODIFIERS = {"": "", "MMC": "M", "LMC": "L", "RFS": ""}   # Y14.5-2009+: RFS is the default, no symbol


def _circle_letter(x, letter):
    """Material condition modifier: a letter in a circle, 3.6 mm across, centred at x."""
    return (f'<circle cx="{x:.3f}" cy="{H / 2:.3f}" r="1.8" fill="none" stroke="black" '
            f'stroke-width="{STROKE}"/>'
            f'<text x="{x:.3f}" y="{H / 2 + 0.95:.3f}" font-family="{FONT}" font-size="2.6" '
            f'text-anchor="middle">{letter}</text>')


def _diameter(x):
    """The diameter sign, 3 mm across, centred at x."""
    return (f'<circle cx="{x:.3f}" cy="{H / 2:.3f}" r="1.25" fill="none" stroke="black" '
            f'stroke-width="{STROKE}"/>'
            f'<path d="M {x - 1.4:.3f} {H / 2 + 1.4:.3f} L {x + 1.4:.3f} {H / 2 - 1.4:.3f}" '
            f'stroke="black" stroke-width="{STROKE}" fill="none"/>')


def text_width(s, size=TEXT):
    return 0.62 * size * max(len(s), 1)


def feature_control_frame(characteristic, tolerance, diameter=False, modifier="", datums=()):
    """SVG for one feature control frame.

    characteristic: a key of SYMBOLS; tolerance: e.g. "0.25"; diameter: Ø before the value;
    modifier: "", "MMC", "LMC" or "RFS"; datums: e.g. [("A", ""), ("B", ""), ("C", "MMC")].
    Returns (svg text, width in mm)."""
    if characteristic not in SYMBOLS:
        raise ValueError(f"unknown characteristic {characteristic!r}")
    parts, x = [], 0.0
    # symbol cell
    parts.append(f'<g transform="translate({x:.3f},0)"><path d="{SYMBOLS[characteristic]}" fill="none" '
                 f'stroke="black" stroke-width="{STROKE}" stroke-linejoin="round"/></g>')
    x += CELL
    walls = [x]
    # tolerance cell: [Ø] value [modifier]
    t0 = x + 1.2
    tx = t0
    if diameter:
        parts.append(_diameter(tx + 1.5))
        tx += 3.6
    parts.append(f'<text x="{tx:.3f}" y="{H / 2 + TEXT / 2 - 0.3:.3f}" font-family="{FONT}" font-size="{TEXT}" '
                 f'freecad:editable="tolerance"><tspan>{escape(tolerance)}</tspan></text>')
    tx += text_width(tolerance) + 0.6
    letter = MODIFIERS.get(modifier, "")
    if letter:
        parts.append(_circle_letter(tx + 1.9, letter))
        tx += 4.0
    x = max(tx + 1.0, x + 10.0)
    walls.append(x)
    # datum cells
    for i, (name, mod) in enumerate(datums):
        w = max(CELL, text_width(name) + 2.0) + (4.2 if MODIFIERS.get(mod, "") else 0.0)
        cx = x + (w - (4.2 if MODIFIERS.get(mod, "") else 0.0)) / 2
        parts.append(f'<text x="{cx:.3f}" y="{H / 2 + TEXT / 2 - 0.3:.3f}" font-family="{FONT}" '
                     f'font-size="{TEXT}" text-anchor="middle" freecad:editable="datum{i + 1}"><tspan>{escape(name)}</tspan></text>')
        if MODIFIERS.get(mod, ""):
            parts.append(_circle_letter(x + w - 2.4, MODIFIERS[mod]))
        x += w
        walls.append(x)
    width = x
    frame = (f'<rect x="{STROKE / 2:.3f}" y="{STROKE / 2:.3f}" width="{width - STROKE:.3f}" height="{H - STROKE:.3f}" '
             f'fill="white" stroke="black" stroke-width="{STROKE}"/>')
    lines = "".join(f'<path d="M {w:.3f} 0 V {H:.3f}" stroke="black" stroke-width="{STROKE}"/>' for w in walls[:-1])
    return _svg(width, H, frame + lines + "".join(parts)), width


def datum_feature_symbol(letter, attach="bottom"):
    """SVG for a datum feature symbol: the letter in a square, a stem and a filled triangle.

    attach is the side the triangle is on ("bottom", "top", "left", "right"): the triangle's
    base is the edge that touches the datum feature; the letter always stays upright.
    Returns (svg text, (width, height) in mm)."""
    box = max(CELL, text_width(letter) + 2.0)
    stem, tri = 3.0, 3.0
    reach = stem + tri
    vertical = attach in ("bottom", "top")
    w, h = (box, H + reach) if vertical else (box + reach, H)
    bx = (reach if attach == "left" else 0.0)            # where the letter box sits
    by = (reach if attach == "top" else 0.0)
    cx, cy = bx + box / 2, by + H / 2
    body = (f'<rect x="{bx + STROKE / 2:.3f}" y="{by + STROKE / 2:.3f}" width="{box - STROKE:.3f}" '
            f'height="{H - STROKE:.3f}" fill="white" stroke="black" stroke-width="{STROKE}"/>'
            f'<text x="{cx:.3f}" y="{cy + TEXT / 2 - 0.3:.3f}" font-family="{FONT}" font-size="{TEXT}" '
            f'text-anchor="middle" freecad:editable="datum"><tspan>{escape(letter)}</tspan></text>')
    half = tri / 1.7
    if attach == "bottom":
        stem_d = f"M {cx:.3f} {H:.3f} V {H + stem:.3f}"
        tri_d = f"M {cx - half:.3f} {h:.3f} L {cx + half:.3f} {h:.3f} L {cx:.3f} {H + stem:.3f} Z"
    elif attach == "top":
        stem_d = f"M {cx:.3f} {reach:.3f} V {tri:.3f}"
        tri_d = f"M {cx - half:.3f} 0 L {cx + half:.3f} 0 L {cx:.3f} {tri:.3f} Z"
    elif attach == "left":
        stem_d = f"M {reach:.3f} {cy:.3f} H {tri:.3f}"
        tri_d = f"M 0 {cy - half:.3f} L 0 {cy + half:.3f} L {tri:.3f} {cy:.3f} Z"
    else:
        stem_d = f"M {box:.3f} {cy:.3f} H {box + stem:.3f}"
        tri_d = f"M {w:.3f} {cy - half:.3f} L {w:.3f} {cy + half:.3f} L {box + stem:.3f} {cy:.3f} Z"
    body += (f'<path d="{stem_d}" stroke="black" stroke-width="{STROKE}"/>'
             f'<path d="{tri_d}" fill="black" stroke="black" stroke-width="{STROKE}"/>')
    return _svg(w, h, body), (w, h)


def _svg(w, h, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:freecad="http://www.freecad.org/wiki/index.php?title=Svg_Namespace" '
            f'width="{w:.3f}mm" height="{h:.3f}mm" viewBox="0 0 {w:.3f} {h:.3f}">{body}</svg>')


def callout(characteristic, tolerance, diameter=False, modifier="", datums=()):
    """The frame as text, for reports: e.g. 'position | Ø0.25 (M) | A | B | C'."""
    tol = ("Ø" if diameter else "") + tolerance + (f" ({MODIFIERS[modifier]})" if MODIFIERS.get(modifier) else "")
    ds = [n + (f" ({MODIFIERS[m]})" if MODIFIERS.get(m) else "") for n, m in datums]
    return " | ".join([characteristic, tol] + ds)

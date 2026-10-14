# SPDX-License-Identifier: LGPL-2.1-or-later
"""ISO tolerancing data for technical product documentation (no FreeCAD needed).

- ISO 286-1: standard tolerance grades IT1..IT16 and the limit deviations of the common hole and
  shaft positions (D..S, d..s) for nominal sizes up to 500 mm, and fits (H7/g6 ...).
- ISO 2768-1: general tolerances for linear and angular dimensions (classes f, m, c, v).
- ISO 2768-2: general geometrical tolerances (classes H, K, L) for straightness and flatness,
  perpendicularity and circular run-out.

The IT values are the ISO 286-1 table (cross-checked: the published IT table and the IT5 column of a
second table agree). Shaft fundamental deviations are the rounded ISO 286 values; tests compare them
with the ISO 286-1 formulas they are rounded from (d 16 D^0.44, e 11 D^0.41, f 5.5 D^0.41,
g 2.5 D^0.34, k 0.6 D^(1/3), m IT7 - IT6, n 5 D^0.34, p IT7 + 0..5, s IT8 + 1..4 / IT7 + 0.4 D),
D the geometric mean of the size range. Holes follow ISO 286-1's rules from the shafts: EI = -es for
A..H; ES = -ei + delta for K, M, N up to IT8 and P..ZC up to IT7 (delta = ITn - IT(n-1), 0 up to 3 mm).
All values in micrometres unless a function says mm. Symmetry (ISO 2768-2) is left out: the sources
checked disagree on it.
"""

import bisect
import math
import re

# upper limits of the nominal size ranges (mm); a size belongs to the first range whose limit >= size
RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]
LOWER = [0] + RANGES[:-1]

# ISO 286-1 standard tolerances, micrometres: IT1 .. IT16 for each range above
IT = {
    1: [0.8, 1, 1, 1.2, 1.5, 1.5, 2, 2.5, 3.5, 4.5, 6, 7, 8],
    2: [1.2, 1.5, 1.5, 2, 2.5, 2.5, 3, 4, 5, 7, 8, 9, 10],
    3: [2, 2.5, 2.5, 3, 4, 4, 5, 6, 8, 10, 12, 13, 15],
    4: [3, 4, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20],
    5: [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
    6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40],
    7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
    8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97],
    9: [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
    10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250],
    11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
    12: [100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630],
    13: [140, 180, 220, 270, 330, 390, 460, 540, 630, 720, 810, 890, 970],
    14: [250, 300, 360, 430, 520, 620, 740, 870, 1000, 1150, 1300, 1400, 1550],
    15: [400, 480, 580, 700, 840, 1000, 1200, 1400, 1600, 1850, 2100, 2300, 2500],
    16: [600, 750, 900, 1100, 1300, 1600, 1900, 2200, 2500, 2900, 3200, 3600, 4000],
}

# shaft upper deviations es (d..g) and lower deviations ei (k..p), micrometres, per range
ES = {
    "d": [-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230],
    "e": [-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135],
    "f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
    "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],
    "h": [0] * 13,
}
EI = {
    "k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],          # IT4..IT7; 0 for the other grades
    "m": [2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23],
    "n": [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40],
    "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68],
}
# r and s change inside the ranges above 50 mm: (upper limit of the sub-range, ei)
EI_SPLIT = {
    "r": [(3, 10), (6, 15), (10, 19), (18, 23), (30, 28), (50, 34), (65, 41), (80, 43), (100, 51), (120, 54),
          (140, 63), (160, 65), (180, 68), (200, 77), (225, 80), (250, 84), (280, 94), (315, 98), (355, 108),
          (400, 114), (450, 126), (500, 132)],
    "s": [(3, 14), (6, 19), (10, 23), (18, 28), (30, 35), (50, 43), (65, 53), (80, 59), (100, 71), (120, 79),
          (140, 92), (160, 100), (180, 108), (200, 122), (225, 130), (250, 140), (280, 158), (315, 170), (355, 190),
          (400, 208), (450, 232), (500, 252)],
}
SHAFTS = sorted(set(ES) | set(EI) | set(EI_SPLIT) | {"js"})
HOLES = sorted(s.upper() for s in SHAFTS)


def range_index(size):
    if not 0 < size <= RANGES[-1]:
        raise ValueError(f"ISO 286 data here covers nominal sizes up to {RANGES[-1]} mm, not {size}")
    return bisect.bisect_left(RANGES, size)


def it(grade, size):
    """Standard tolerance ITgrade at a nominal size, micrometres."""
    if grade not in IT:
        raise ValueError(f"IT{grade}: grades IT1 to IT16 are covered")
    return IT[grade][range_index(size)]


def _split(letter, size):
    for upto, v in EI_SPLIT[letter]:
        if size <= upto:
            return v
    raise ValueError(f"{letter}: no value for {size} mm")


def shaft(letter, grade, size):
    """(es, ei) of a shaft tolerance class such as g6, micrometres."""
    t = it(grade, size)
    i = range_index(size)
    if letter == "js":
        return t / 2, -t / 2
    if letter in ES:
        es = ES[letter][i]
        return es, es - t
    if letter == "k":
        ei = EI["k"][i] if 4 <= grade <= 7 else 0
    elif letter in EI:
        ei = EI[letter][i]
    elif letter in EI_SPLIT:
        ei = _split(letter, size)
    else:
        raise ValueError(f"shaft position {letter!r}: covered are {', '.join(SHAFTS)}")
    return ei + t, ei


def hole(letter, grade, size):
    """(ES, EI) of a hole tolerance class such as H7, micrometres (ISO 286-1 rules from the shafts)."""
    L = letter.upper()
    t = it(grade, size)
    s = L.lower()
    if L == "JS":
        return t / 2, -t / 2
    if s in ES:                                   # D..H: EI = -es
        ei = -ES[s][range_index(size)]
        return ei + t, ei
    _, ei_shaft = shaft(s, grade, size)
    if L == "K" and not 4 <= grade <= 7:
        ei_shaft = 0
    delta = 0
    small = size <= 3
    if not small and ((L in ("K", "M", "N") and grade <= 8) or (L in ("P", "R", "S") and grade <= 7)):
        delta = it(grade, size) - it(grade - 1, size)
    if L == "N" and grade > 8 and not small:
        es_hole = 0
    else:
        es_hole = -ei_shaft + delta
    return es_hole, es_hole - t


CLASS = re.compile(r"^\s*([A-Za-z]{1,2})\s*(\d{1,2})\s*$")


def parse_class(text):
    """'H7' -> ('H', 7, 'hole'); 'g6' -> ('g', 6, 'shaft')."""
    m = CLASS.match(text or "")
    if not m:
        raise ValueError(f"not a tolerance class: {text!r} (e.g. H7, g6, js5)")
    letter, grade = m.group(1), int(m.group(2))
    kind = "hole" if letter[0].isupper() else "shaft"
    if (letter.upper() if kind == "hole" else letter) not in (HOLES if kind == "hole" else SHAFTS):
        raise ValueError(f"tolerance position {letter!r} not covered: holes {', '.join(HOLES)}; shafts "
                         f"{', '.join(SHAFTS)}")
    return letter, grade, kind


def deviations(cls, size):
    """(upper, lower) deviation in mm of a tolerance class at a nominal size."""
    letter, grade, kind = parse_class(cls)
    up, lo = (hole if kind == "hole" else shaft)(letter, grade, size)
    return up / 1000.0, lo / 1000.0


def fit(size, hole_class, shaft_class):
    """A fit such as 10 H7/g6: the limits of both parts and the clearance range (mm; negative = interference)."""
    hu, hl = deviations(hole_class, size)
    su, sl = deviations(shaft_class, size)
    cmax, cmin = hu - sl, hl - su
    kind = "clearance" if cmin >= 0 else "interference" if cmax <= 0 else "transition"
    return {"size": size, "hole": hole_class, "shaft": shaft_class, "hole_limits": (size + hl, size + hu),
            "shaft_limits": (size + sl, size + su), "clearance_min": cmin, "clearance_max": cmax, "kind": kind}


# ---------------------------------------------------------------- ISO 2768
LINEAR_RANGES = [(0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000)]
LINEAR = {   # ISO 2768-1 table 1, +/- mm
    "f": [0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None],
    "m": [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2],
    "c": [0.2, 0.3, 0.5, 0.8, 1.2, 2, 3, 4],
    "v": [None, 0.5, 1, 1.5, 2.5, 4, 6, 8],
}
ANGULAR_RANGES = [10, 50, 120, 400, math.inf]           # length of the shorter side, mm
ANGULAR = {   # ISO 2768-1 table 3, +/- arc minutes (f and m share one column)
    "f": [60, 30, 20, 10, 5], "m": [60, 30, 20, 10, 5],
    "c": [90, 60, 30, 15, 10], "v": [180, 120, 60, 30, 20],
}
FLATNESS_RANGES = [10, 30, 100, 300, 1000, 3000]
FLATNESS = {"H": [0.02, 0.05, 0.1, 0.2, 0.3, 0.4], "K": [0.05, 0.1, 0.2, 0.4, 0.6, 0.8],
            "L": [0.1, 0.2, 0.4, 0.8, 1.2, 1.6]}        # ISO 2768-2 straightness and flatness, mm
PERPENDICULARITY_RANGES = [100, 300, 1000, 3000]
PERPENDICULARITY = {"H": [0.2, 0.3, 0.4, 0.5], "K": [0.4, 0.6, 0.8, 1.0], "L": [0.6, 1.0, 1.5, 2.0]}
RUNOUT = {"H": 0.1, "K": 0.2, "L": 0.5}                 # ISO 2768-2 circular run-out, mm

NOTE = re.compile(r"ISO\s*2768\s*-\s*([fmcv])\s*([HKL])?(?:\s*-?\s*(E)\b)?", re.I)


def parse_general(note):
    """'ISO 2768-mK' -> ('m', 'K', False); 'ISO 2768-mK-E' -> envelope for all features of size."""
    m = NOTE.search(note or "")
    if not m:
        return None
    return m.group(1).lower(), (m.group(2) or "").upper() or None, bool(m.group(3))


def linear(size, cls):
    """+/- general tolerance (mm) of a linear dimension, ISO 2768-1."""
    if size < 0.5:
        raise ValueError("ISO 2768-1 starts at 0.5 mm: give smaller sizes their own tolerance")
    for (lo, hi), v in zip(LINEAR_RANGES, LINEAR[cls]):
        if size <= hi:
            if v is None:
                raise ValueError(f"ISO 2768-{cls} gives no tolerance for {size} mm")
            return v
    raise ValueError("ISO 2768-1 ends at 4000 mm")


def angular(shorter_side, cls):
    """+/- general tolerance of an angle, in degrees, ISO 2768-1."""
    for hi, v in zip(ANGULAR_RANGES, ANGULAR[cls]):
        if shorter_side <= hi:
            return v / 60.0


def flatness(length, cls):
    for hi, v in zip(FLATNESS_RANGES, FLATNESS[cls]):
        if length <= hi:
            return v
    raise ValueError("ISO 2768-2 straightness and flatness end at 3000 mm")


def perpendicularity(shorter_side, cls):
    for hi, v in zip(PERPENDICULARITY_RANGES, PERPENDICULARITY[cls]):
        if shorter_side <= hi:
            return v
    raise ValueError("ISO 2768-2 perpendicularity ends at 3000 mm")

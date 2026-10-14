# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pin location: how well two pins locate one part on another (no FreeCAD needed).

Drake, Dimensioning and Tolerancing Handbook, ch. 24 ("Pinned interfaces"):

Two round pins in two holes. The parts assemble when the hole clearances absorb the difference
between the pin spacing dp and the hole spacing dh (24.2):

    c = 1/2 (Øh1 + Øh2 - Øp1 - Øp2) - |dh - dp| >= 0

The pin line can turn against the hole line by the angle of the triangle with sides dh, dp and
e = (Øh1 - Øp1 + Øh2 - Øp2)/2 (24.4): cos a = (dh² + dp² - e²) / (2 dh dp), about (Øh - Øp)/dp (24.5).
Drake calls 24.5 slightly conservative; with equal spacings 24.4 is 2 asin(e/2d), which exceeds e/d by
about (e/d)³/24, so the two agree to far better than any tolerance and both are reported.
Translation is set by the tighter pin: d = 1/2 min(Øh1 - Øp1, Øh2 - Øp2).

A hole and a slot (24.12). The slot runs along the line of centres, so the spacings no longer enter the
fit; the slot only has to be long enough for their variation. Translation is the hole's clearance
(Øh - Øp1)/2. The rotation follows from the pin line with one end inside the hole's clearance circle
and the other inside the slot's clearance band: sin a = (Dhole + Dslot)/dp with Dhole = (Øh - Øp1)/2,
Dslot = (w - Øp2)/2.

Temperature (24.10). Parts of different materials assembled dT away from the reference temperature
change their spacings by dp dT |cte1 - cte2|; with two holes each hole must grow by that much
(Dh), which adds Dh/2 to the translation and dT |cte1 - cte2| to the rotation. A slot takes it up
in its length instead.

Fischer, Mechanical Tolerance Stackup and Analysis, ch. 15: an angle error a moves a point at
distance D by D tan a; for an optical axis, that is the pointing error on a target D away.

Sizes are (minimum, maximum) pairs in mm, angles in radians.
"""

import math

from . import iso

TWO_HOLES = "Two holes"
HOLE_SLOT = "Hole and slot"
LAYOUTS = (TWO_HOLES, HOLE_SLOT)


def limits(nominal, cls=None, plus=0.0, minus=0.0):
    """(min, max) of a size: from an ISO 286 class such as G6, or deviations (minus as a magnitude)."""
    if cls:
        up, lo = iso.deviations(cls, nominal)
        return nominal + lo, nominal + up
    return nominal - minus, nominal + plus


def spacing_gap(dh, dp):
    """Largest |dh - dp| and the smallest of it, over the two spacing ranges (min, max)."""
    worst = max(abs(dh[1] - dp[0]), abs(dp[1] - dh[0]))
    best = 0.0 if dh[0] <= dp[1] and dp[0] <= dh[1] else min(abs(dh[0] - dp[1]), abs(dp[0] - dh[1]))
    return worst, best


def thermal_growth(dp, dT, cte1, cte2):
    """Drake 24.10: how much the spacings of two materials part over dT (mm; ctes in 1/K)."""
    return abs(dp * dT * (cte1 - cte2))


def rotation_two_holes(dh, dp, e):
    """Drake 24.4: the angle between the hole line and the pin line (radians), or None when the
    clearance e cannot close the triangle (the parts do not assemble)."""
    if e <= 0 or dh <= 0 or dp <= 0:
        return 0.0 if e == 0 else None
    c = (dh * dh + dp * dp - e * e) / (2 * dh * dp)
    if c > 1:
        return None
    return math.acos(max(-1.0, c))


def pointing(angle, distance):
    """Fischer ch. 15: lateral error at a distance for an angle error (mm)."""
    return distance * math.tan(angle)


def analyse(layout, hole1, pin1, hole2, pin2, dh, dp, slot_length=None, dT=0.0, cte_holes=0.0, cte_pins=0.0,
            distance=None, min_clearance=0.0):
    """Worst-case fit, translation and rotation of a two-pin location.

    hole1/pin1/hole2/pin2: (min, max) diameters; for a hole and slot, hole2 is the slot's width.
    dh, dp: (min, max) spacing of the holes (or hole to slot centre) and of the pins.
    slot_length: the slot's length along the line of centres (hole and slot only).
    dT, cte_holes, cte_pins: assembly temperature away from the reference (K), expansion of the part
    with the holes and of the part with the pins (1/K).
    distance: where the pointing error is wanted (mm), e.g. the target of an optical axis.

    Returns a dict: clearance (worst), clearance_best, assembles, translation, rotation (radians),
    rotation_simplified (24.5, two holes), thermal (spacing change), pointing, findings.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    findings = []
    d_nom = (dp[0] + dp[1]) / 2
    growth = thermal_growth(d_nom, dT, cte_holes, cte_pins) if dT else 0.0
    gap_worst, gap_best = spacing_gap(dh, dp)
    r = {"layout": layout, "thermal": growth}
    if layout == TWO_HOLES:
        c = 0.5 * (hole1[0] + hole2[0] - pin1[1] - pin2[1]) - gap_worst - growth
        c_best = 0.5 * (hole1[1] + hole2[1] - pin1[0] - pin2[0]) - gap_best
        e_max = 0.5 * (hole1[1] - pin1[0] + hole2[1] - pin2[0])
        # the angle is largest for the shortest, most equal spacings the tolerances allow
        lo = max(dh[0], dp[0])
        d_h, d_p = (lo, lo) if lo <= min(dh[1], dp[1]) else (dh[0], dp[0])
        rot = rotation_two_holes(d_h, d_p, e_max)
        simple = (max(hole1[1] - pin1[0], hole2[1] - pin2[0])) / dp[0]
        trans = 0.5 * min(hole1[1] - pin1[0], hole2[1] - pin2[0])
        if growth:
            findings.append(f"two materials {dT:g} K away from the reference temperature: the spacings part by "
                            f"{growth:.4f} mm; Drake 24.10 enlarges each hole by that, which adds {growth / 2:.4f} mm "
                            f"of translation and {dT * abs(cte_holes - cte_pins) * 1e6:.1f} µrad of rotation")
            trans += growth / 2
            if rot is not None:
                rot += dT * abs(cte_holes - cte_pins)
            simple += dT * abs(cte_holes - cte_pins)
        r.update(rotation_simplified=simple)
    else:
        c_fit = min(hole1[0] - pin1[1], hole2[0] - pin2[1]) / 2
        c_best = min(hole1[1] - pin1[0], hole2[1] - pin2[0]) / 2
        if slot_length is not None:
            room = (slot_length - pin2[1]) / 2 - gap_worst - growth
            if room < 0:
                findings.append(f"the slot is {-room:.4f} mm too short for the spacing tolerances"
                                + (" and the thermal growth" if growth else ""))
            elif growth:
                findings.append(f"two materials {dT:g} K away from the reference temperature: the spacings part by "
                                f"{growth:.4f} mm; the slot takes it up ({room:.4f} mm of its length to spare), so "
                                "translation and rotation do not grow (two holes would each need "
                                f"{growth:.4f} mm more)")
            c = min(c_fit, room)
        else:
            c = c_fit
            findings.append("no slot length given: only the widths are checked")
        dhole = (hole1[1] - pin1[0]) / 2
        dslot = (hole2[1] - pin2[0]) / 2
        s = (dhole + dslot) / dp[0]
        rot = math.asin(s) if s <= 1 else None
        trans = dhole
    ok = c >= min_clearance - 1e-12 and rot is not None
    if c < min_clearance - 1e-12:
        findings.insert(0, f"does not assemble in the worst case: clearance {c:.4f} mm")
    r.update(clearance=c, clearance_best=c_best, assembles=ok, translation=trans, rotation=rot,
             findings=findings)
    if distance and rot is not None:
        r["pointing"] = pointing(rot, distance)
        r["distance"] = distance
    return r


def report(r, title="Pin location", digits=4):
    lines = [f"{title}: {r['layout']}",
             f"  fit: worst-case clearance {r['clearance']:+.{digits}f} mm ({'assembles' if r['assembles'] else 'does NOT assemble'}),"
             f" best {r['clearance_best']:+.{digits}f} mm",
             f"  translation: {r['translation']:.{digits}f} mm"]
    if r["rotation"] is not None:
        lines.append(f"  rotation: {r['rotation'] * 1e3:.4f} mrad ({math.degrees(r['rotation']) * 3600:.1f}\")"
                     + (f"; simplified (Drake 24.5) {r['rotation_simplified'] * 1e3:.4f} mrad"
                        if r.get("rotation_simplified") is not None else ""))
    if r.get("pointing") is not None:
        lines.append(f"  pointing error at {r['distance']:g} mm: {r['pointing']:.{digits}f} mm (D tan a, Fischer ch. 15)")
    lines += [f"  {f}" for f in r["findings"]]
    return "\n".join(lines)

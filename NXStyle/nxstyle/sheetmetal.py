# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sheet metal bends and flat lengths (no FreeCAD needed).

A bend of angle A (the angle the sheet turns through, 90° for a right-angle flange) and inside radius R
in a sheet of thickness T stretches the outside and compresses the inside; the neutral layer keeps its
length and lies at K x T from the inside face. K, NX's neutral factor, is the ANSI K-factor; DIN 6935
quotes k = 2K. Shih (Parametric Modeling with Siemens NX, ch. 13) gives the bend allowance

    BA = A (R + K T)                       A in radians

with K between 0.25 and 0.5 in practice; his exercise uses 0.41. With the outside setback
OSSB = tan(A/2) (R + T),
the bend deduction is BD = 2 OSSB - BA: a part dimensioned to its outside mould lines (legs a, b) has
the flat length a + b - BD, and one dimensioned between bend tangent lines has the straight lengths
plus BA for each bend.
"""

import math

K_DEFAULT = 0.41          # the neutral factor of Shih's ch. 13 exercise; NXStyle's starting value
K_TYPICAL = (0.25, 0.5)
INCH = 25.4


def bend_allowance(angle, R, T, K=K_DEFAULT):
    """Length of the neutral layer through a bend of angle (degrees)."""
    return math.radians(angle) * (R + K * T)


def outside_setback(angle, R, T):
    """From the bend's tangent line to the outside mould line (the outer sharp corner)."""
    return math.tan(math.radians(angle) / 2) * (R + T)


def inside_setback(angle, R):
    return math.tan(math.radians(angle) / 2) * R


def bend_deduction(angle, R, T, K=K_DEFAULT):
    """Two outside setbacks minus the bend allowance: what a bend takes off the outside dimensions."""
    return 2 * outside_setback(angle, R, T) - bend_allowance(angle, R, T, K)


def flat_from_tangents(straights, bends, T, K=K_DEFAULT):
    """Flat length from the straight lengths between bend tangent lines and the bends [(angle, R)]."""
    return sum(straights) + sum(bend_allowance(a, r, T, K) for a, r in bends)


def flat_from_outside(legs, bends, T, K=K_DEFAULT):
    """Flat length from the outside dimensions (outer sharp to outer sharp) and the bends [(angle, R)]."""
    return sum(legs) - sum(bend_deduction(a, r, T, K) for a, r in bends)


def din(k):
    """DIN 6935 k-factor of an ANSI K-factor (the SheetMetal add-on offers both)."""
    return 2 * k


def ansi(k_din):
    return k_din / 2


def check(T, R, K, angle=90.0):
    """Findings [(severity, text)] for a thickness, inside radius and neutral factor."""
    out = []
    if T <= 0:
        out.append(("error", "the material thickness must be positive"))
    if R < 0:
        out.append(("error", "the bend radius cannot be negative"))
    if not 0 <= K <= 0.5:
        out.append(("error", f"neutral factor {K:g} is outside 0 to 0.5: the neutral layer must lie inside the "
                             "sheet (a DIN k-factor is twice the ANSI value NX uses)"))
    elif not K_TYPICAL[0] <= K <= K_TYPICAL[1]:
        out.append(("warning", f"neutral factor {K:g} is outside the usual {K_TYPICAL[0]} to {K_TYPICAL[1]}"))
    if T > 0 and 0 <= R < T:
        out.append(("note", f"inside radius {R:g} is less than the thickness {T:g}: check the material's minimum "
                            "bend radius"))
    if not 0 < angle < 180:
        out.append(("error", f"bend angle {angle:g}° must be between 0 and 180"))
    return out


def report(T, R, K, angle=90.0, unit="mm", digits=4):
    """A few lines for the preferences dialog and the flat pattern information."""
    ba, bd = bend_allowance(angle, R, T, K), bend_deduction(angle, R, T, K)
    lines = [f"Thickness {T:.{digits}g} {unit}, inside radius {R:.{digits}g} {unit}, neutral factor K {K:g} "
             f"(DIN k {din(K):g})",
             f"{angle:g}° bend: bend allowance {ba:.{digits}f} {unit}, outside setback "
             f"{outside_setback(angle, R, T):.{digits}f} {unit}, bend deduction {bd:.{digits}f} {unit}"]
    lines += [f"{s}: {t}" for s, t in check(T, R, K, angle)]
    return "\n".join(lines)

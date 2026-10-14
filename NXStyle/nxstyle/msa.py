# SPDX-License-Identifier: LGPL-2.1-or-later
"""Measurement capability: is the gauge good enough for the tolerance it checks? No FreeCAD needed.

- Gauge repeatability, range method (Drake, Dimensioning and Tolerancing Handbook, ch. 25): the same
  parts measured n times; the gauge's standard deviation is the average range over d2 (1.128 for
  two trials), its spread k sigma, and the share of the tolerance it uses decides: under 10 % the
  gauge is acceptable, 10 to 30 % it may be, depending on the risk and cost, over 30 % it is not.
  Drake's worked example spreads 3 sigma; the AIAG MSA manual takes 6 sigma, twice the share.
- Test uncertainty ratio, TUR (ANSI/NCSL Z540.3): the tolerance span over twice the expanded
  uncertainty U (k = 2); 4:1 is the usual minimum, 10:1 the traditional rule.
- Decision rule (ISO 14253-1): conformance is proven only inside the specification zone reduced by U
  at each limit (the acceptance zone, a guard band); a result within U of a limit proves neither
  conformance nor non-conformance.
"""

D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}
ACCEPTABLE, MARGINAL = 10.0, 30.0


def ranges(trials):
    """Range of each part's repeated readings: trials is [[r1, r2, ...] per part]."""
    return [max(t) - min(t) for t in trials]


def repeatability(trials, tolerance, spread=6.0):
    """The range method. trials: [[reading, ...] per part], the same number of readings each.
    Returns {"n", "parts", "ranges", "r_bar", "d2", "sigma", "spread", "k", "percent", "verdict"}."""
    if not trials:
        raise ValueError("no measurements")
    n = len(trials[0])
    if any(len(t) != n for t in trials):
        raise ValueError("every part needs the same number of readings")
    if n not in D2:
        raise ValueError(f"{n} readings per part: the range method takes 2 to 10")
    if tolerance <= 0:
        raise ValueError("the tolerance must be greater than zero")
    rs = ranges(trials)
    r_bar = sum(rs) / len(rs)
    sigma = r_bar / D2[n]
    pct = 100.0 * spread * sigma / tolerance
    return {"n": n, "parts": len(trials), "ranges": rs, "r_bar": r_bar, "d2": D2[n], "sigma": sigma,
            "k": spread, "spread": spread * sigma, "percent": pct, "verdict": verdict(pct)}


def verdict(percent):
    if percent < ACCEPTABLE:
        return "acceptable"
    if percent <= MARGINAL:
        return "marginal: acceptable depending on the risk and the cost of a better gauge"
    return "unacceptable: improve the gauge or the method"


def tur(lower, upper, u):
    """Test uncertainty ratio: tolerance span / (2 U)."""
    if u <= 0:
        return float("inf")
    return (upper - lower) / (2.0 * u)


def ratio_text(ratio):
    """'5.3:1': one decimal, halves rounded up whichever side of .x5 the floating point lands
    (0.021 / 0.004 is 5.2500000001, 0.01 / 0.008 is 1.2499999999)."""
    import math
    if ratio == float("inf"):
        return "∞"
    return f"{math.floor(ratio * 10 + 0.5 + 1e-9) / 10:.1f}:1"


def tur_verdict(ratio):
    if ratio >= 10:
        return "meets 10:1"
    if ratio >= 4:
        return "meets 4:1"
    return "below 4:1: guard band or a better method"


def acceptance(lower, upper, u, one_sided=False):
    """ISO 14253-1 acceptance limits: the specification zone reduced by U at each limit. A geometrical
    tolerance (one_sided: zero is not a limit, the deviation cannot be below it) is reduced at the upper
    limit only. Returns (lower, upper), or None when U leaves no acceptance zone."""
    lo = lower if one_sided else lower + u
    hi = upper - u
    return (lo, hi) if hi > lo else None


def decide(value, lower, upper, u, one_sided=False):
    """'conforms' (inside the acceptance zone), 'does not conform' (outside the specification widened by U),
    or 'undecided' (within U of a limit)."""
    acc = acceptance(lower, upper, u, one_sided)
    if acc is not None and acc[0] <= value <= acc[1]:
        return "conforms"
    lo = lower if one_sided else lower - u
    if value < lo or value > upper + u:
        return "does not conform"
    return "undecided"


def report(r, tolerance, unit="mm", title="Gauge repeatability (range method)"):
    lines = [title, f"{r['parts']} parts, {r['n']} readings each; tolerance {tolerance:g} {unit}", ""]
    lines.append("Part  Range")
    for i, x in enumerate(r["ranges"], 1):
        lines.append(f"{i:>4}  {x:.4f}")
    lines += ["", f"Average range R̄ = {r['r_bar']:.4f} {unit}",
              f"σ = R̄ / d2 = {r['r_bar']:.4f} / {r['d2']:.3f} = {r['sigma']:.4f} {unit}",
              f"Spread {r['k']:g}σ = {r['spread']:.4f} {unit}: {r['percent']:.1f} % of the tolerance",
              f"Verdict: {r['verdict']} (under {ACCEPTABLE:g} % acceptable, over {MARGINAL:g} % not)"]
    return "\n".join(lines)

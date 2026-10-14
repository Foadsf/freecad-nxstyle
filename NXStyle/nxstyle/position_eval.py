# SPDX-License-Identifier: LGPL-2.1-or-later
"""Position of a pattern of holes or pins from measured data: what a CMM report or a paper gauge
(Cogorno ch. 13, Drake ch. 5) decides. No FreeCAD needed.

Each feature has its basic (true) position in the datum reference frame, its measured axis position
and its measured size. With the tolerance at MMC, the zone grows by the bonus, the size's departure
from MMC (a hole larger than its MMC size, a pin smaller). The deviation is diametral: twice the
distance from the true position.

The pattern-locating row (PLTZF) is fixed to its datums: every axis must lie in its zone where the
basic dimensions put it. The feature-relating row (FRTZF) of a composite frame may move: the zones keep
their basic spacing but the framework translates, and turns as well unless the datums it repeats stop it
(a primary datum plane only orients it, so it still turns in that plane). The pattern passes the row
when one position of the framework holds every axis in its zone: a minimax fit, the largest of the
deviations over the zone sizes made as small as it can be. That ratio is the utilisation: at most 1
is a pass.
"""

import math

TRANSLATE = ("tx", "ty")
TRANSLATE_ROTATE = ("tx", "ty", "rot")


def bonus(size, at, internal=True, modifier="MMC"):
    """Extra tolerance from the size's departure from the material condition the tolerance applies at
    (at: the MMC or LMC size); negative when the size is beyond it, which is a size reject."""
    if modifier == "LMC":
        return at - size if internal else size - at
    return size - at if internal else at - size


def zone(tolerance, modifier, size, at, internal=True):
    if modifier in ("MMC", "LMC") and at is not None and size is not None:
        return tolerance + bonus(size, at, internal, modifier)
    return tolerance


def deviation(actual, basic):
    """Diametral deviation of an axis from its true position (2D, in the plane of the pattern)."""
    return 2.0 * math.hypot(actual[0] - basic[0], actual[1] - basic[1])


def _moved(basics, centre, tx, ty, rot):
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for x, y in basics:
        dx, dy = x - centre[0], y - centre[1]
        out.append((centre[0] + c * dx - s * dy + tx, centre[1] + s * dx + c * dy + ty))
    return out


def _nelder_mead(f, x0, steps, tol=1e-13, iters=4000):
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (steps[j] if j == i else 0.0) for j in range(n)] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < tol and max(abs(pts[-1][j] - pts[0][j]) for j in range(n)) < tol:
            break
        cen = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        xr = [cen[j] + (cen[j] - pts[-1][j]) for j in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [cen[j] + 2 * (cen[j] - pts[-1][j]) for j in range(n)]
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = [cen[j] + 0.5 * (pts[-1][j] - cen[j]) for j in range(n)]
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][j] + 0.5 * (pts[i][j] - pts[0][j]) for j in range(n)]
                    vals[i] = f(pts[i])
    i = min(range(n + 1), key=lambda k: vals[k])
    return pts[i], vals[i]


def best_fit(basics, actuals, zones, motions=TRANSLATE_ROTATE):
    """Move the framework of zones (basic positions, the zone sizes) by the allowed motions so that the
    largest deviation/zone ratio is smallest. Returns (utilisation, (tx, ty, rot radians), deviations)."""
    if not motions:
        devs = [deviation(a, b) for a, b in zip(actuals, basics)]
        return max(d / z for d, z in zip(devs, zones)), (0.0, 0.0, 0.0), devs
    centre = (sum(b[0] for b in basics) / len(basics), sum(b[1] for b in basics) / len(basics))
    span = max(max(math.hypot(b[0] - centre[0], b[1] - centre[1]) for b in basics), 1e-9)
    free = [m for m in ("tx", "ty", "rot") if m in motions]

    def unpack(v):
        p = dict(zip(free, v))
        return p.get("tx", 0.0), p.get("ty", 0.0), p.get("rot", 0.0) / span     # rot scaled to a length

    def worst(v):
        moved = _moved(basics, centre, *unpack(v))
        return max(deviation(a, b) / z for a, b, z in zip(actuals, moved, zones))

    # start from the mean offset (least squares for translation), then polish the minimax by restarts
    mx = sum(a[0] - b[0] for a, b in zip(actuals, basics)) / len(basics)
    my = sum(a[1] - b[1] for a, b in zip(actuals, basics)) / len(basics)
    start = {"tx": mx, "ty": my, "rot": 0.0}
    v = [start[m] for m in free]
    step = max(max(zones), 1e-6)
    best = None
    for _ in range(6):
        v, val = _nelder_mead(worst, v, [step] * len(free))
        if best is not None and val >= best - 1e-15:
            break
        best = val
        step *= 0.1
    tx, ty, rot = unpack(v)
    devs = [deviation(a, b) for a, b in zip(actuals, _moved(basics, centre, tx, ty, rot))]
    return best, (tx, ty, rot), devs


def evaluate(features, tolerance, modifier="", mmc=None, internal=True, lower=None, lower_motions=None, lmc=None):
    """features: [{"basic": (x, y), "actual": (x, y), "size": d}, ...] in the datum reference frame.
    tolerance/modifier: the pattern-locating (upper) row; mmc (and lmc, for LMC) the size limits.
    lower: {"tolerance", "modifier"} of the feature-relating row, with lower_motions how its framework
    may move (default translate and turn).

    Returns {"features": [...], "upper_pass", "lower_pass", "pass", "lower_fit", "lower_utilisation",
    "upper_utilisation"}; per feature: deviation, upper zone, lower zone and deviation after the fit.
    A size outside its limits (beyond MMC, or beyond LMC when lmc is given) fails the feature."""
    def at(mod):
        return lmc if mod == "LMC" else mmc

    rows = []
    for f in features:
        size = f.get("size")
        r = {"basic": tuple(f["basic"]), "actual": tuple(f["actual"]), "size": size,
             "bonus": (bonus(size, at(modifier), internal, modifier)
                       if modifier in ("MMC", "LMC") and at(modifier) is not None and size is not None else 0.0),
             "deviation": deviation(f["actual"], f["basic"])}
        size_ok = True
        if size is not None and mmc is not None:
            size_ok = bonus(size, mmc, internal) >= -1e-12
        if size is not None and lmc is not None:
            size_ok = size_ok and bonus(size, lmc, internal, "LMC") >= -1e-12
        r["size_ok"] = size_ok
        r["upper_zone"] = zone(tolerance, modifier, size, at(modifier), internal)
        r["upper_ok"] = size_ok and r["deviation"] <= r["upper_zone"] + 1e-12
        rows.append(r)
    out = {"features": rows, "upper_pass": all(r["upper_ok"] for r in rows),
           "upper_utilisation": max(r["deviation"] / r["upper_zone"] for r in rows)}
    if lower:
        lm = lower.get("modifier", "")
        zones = [zone(lower["tolerance"], lm, r["size"], at(lm), internal) for r in rows]
        motions = TRANSLATE_ROTATE if lower_motions is None else lower_motions
        util, fit, devs = best_fit([r["basic"] for r in rows], [r["actual"] for r in rows], zones, motions)
        for r, z, d in zip(rows, zones, devs):
            r["lower_zone"], r["lower_deviation"] = z, d
            r["lower_ok"] = d <= z + 1e-12
        out.update(lower_pass=util <= 1 + 1e-9, lower_utilisation=util, lower_fit=fit)
    out["pass"] = out["upper_pass"] and out.get("lower_pass", True)
    return out


def motions_for(lower_datums, frame="composite"):
    """How the lower row's framework may move in the plane of the pattern, from the datums it repeats:
    a composite row with none or a primary plane only translates and turns; a secondary datum stops
    the turn (Cogorno ch. 12)."""
    n = len(lower_datums or [])
    if frame == "composite":
        return TRANSLATE_ROTATE if n <= 1 else TRANSLATE
    return TRANSLATE_ROTATE if n == 0 else (TRANSLATE if n == 1 else ())


def report(result, digits=3, unit="mm"):
    """The evaluation as text, one line per feature, narrow enough for the Information window: the
    measured position and size, the deviation and the zone (with its bonus) of each row."""
    lines = ["True positions: " + ", ".join(f"({r['basic'][0]:g}, {r['basic'][1]:g})" for r in result["features"]),
             ""]
    lower = "lower_pass" in result
    lines.append(f"{'No.':>3}  {'Measured':^15} {'Size':>6}  {'Dev':>6} {'Zone':>6}" +
                 (f"     {'Fit':>6} {'Zone':>6}" if lower else ""))
    for i, r in enumerate(result["features"], 1):
        line = (f"{i:>3}  {r['actual'][0]:>7.{digits}f} {r['actual'][1]:>7.{digits}f} {(r['size'] or 0):>6.{digits}f}  "
                f"{r['deviation']:>6.{digits}f} {r['upper_zone']:>6.{digits}f} {'ok' if r['upper_ok'] else 'OUT':<3}")
        if "lower_zone" in r:
            ok = "ok" if r["lower_ok"] else "OUT"
            line += f"  {r['lower_deviation']:>6.{digits}f} {r['lower_zone']:>6.{digits}f} {ok}"
        lines.append(line)
    lines.append("")
    lines.append(f"Pattern-locating row: {'PASS' if result['upper_pass'] else 'FAIL'} "
                 f"({100 * result['upper_utilisation']:.0f}% of the zone used)")
    if "lower_pass" in result:
        tx, ty, rot = result["lower_fit"]
        lines.append(f"Feature-relating row: {'PASS' if result['lower_pass'] else 'FAIL'} "
                     f"({100 * result['lower_utilisation']:.0f}% of the zone used)")
        lines.append(f"  best fit: shift {tx:+.{digits}f}, {ty:+.{digits}f} {unit}, turn {math.degrees(rot) * 3600:+.1f}\"")
    lines.append(f"Pattern: {'ACCEPT' if result['pass'] else 'REJECT'}")
    return "\n".join(lines)

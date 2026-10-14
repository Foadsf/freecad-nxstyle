# SPDX-License-Identifier: LGPL-2.1-or-later
"""One-dimensional tolerance stack-up analysis (no FreeCAD needed).

The method is the one in Bryan R. Fischer, *Mechanical Tolerance Stackup and Analysis*
(2nd ed.): the loop runs from point A to point B along one direction; every contributor
is converted to equal-bilateral form (mean value +/- half its total tolerance); positive
contributors take the loop in the stack direction, negative ones against it.

Methods (all on the equal-bilateral values):

- worst case:    T_wc   = sum t_i
- RSS:           T_rss  = sqrt(sum t_i^2)                    (Fischer ch. 8)
- adjusted RSS:  T_arss = 1.5 * T_rss                         (Fischer's adjusted statistical stack)
- MRSS:          T_mrss = C_f * T_rss, C_f = 0.5 (T_wc - T_rss) / (T_rss (sqrt(n) - 1)) + 1
                                                              (Drake, Dimensioning and Tolerancing Handbook, ch. 9)
- Monte Carlo:   each contributor drawn from a normal distribution with sigma = t_i / 3
                 (its tolerance is a +/-3 sigma process), or a uniform one between its limits

GD&T contributors follow Fischer's conversion rules: a geometric tolerance zone T enters as
0 +/- T/2, bonus tolerance as 0 +/- (LMC - MMC)/2 on its own line, the assembly shift of a
floating fastener as 0 +/- (hole LMC - fastener MMC)/2 for each part that floats, flatness as a
zone shift of -F/2 with +/- F/2. Fastener and boundary formulas follow Cogorno, *Geometric
Dimensioning and Tolerancing for Mechanical Design* (ch. 3, 7, 8).
"""

import math
import random

KINDS = ("dimension", "position", "profile", "flatness", "orientation", "runout", "bonus",
         "datum shift", "assembly shift", "other")


class Contributor:
    """One line of a stack-up.

    nominal: the dimension's nominal value (a magnitude); plus: the upper deviation, minus: how far
    the lower limit lies below the nominal (8.50 +0.25/-0.10 is nominal 8.50, plus 0.25, minus 0.10;
    a 16 g6 shaft, 15.983 to 15.994, is nominal 16, plus -0.006, minus 0.017); minus defaults to
    plus. direction: +1 if the dimension takes the loop in the stack direction, -1 against it."""

    __slots__ = ("name", "nominal", "plus", "minus", "direction", "kind", "part", "source", "distribution")

    def __init__(self, name, nominal, plus, minus=None, direction=1, kind="dimension", part="", source="",
                 distribution="normal"):
        self.name = str(name)
        self.nominal = float(nominal)
        self.plus = float(plus)
        self.minus = abs(self.plus) if minus is None else float(minus)
        if self.plus + self.minus < 0:
            raise ValueError(f"{name}: the upper limit is below the lower limit")
        self.direction = 1 if direction >= 0 else -1
        self.kind = kind if kind in KINDS else "other"
        self.part = str(part)
        self.source = str(source)
        if distribution not in ("normal", "uniform"):
            raise ValueError(f"unknown distribution {distribution!r}")
        self.distribution = distribution

    # equal-bilateral form (Fischer: total tolerance / 2 about the mean of the limits)
    @property
    def upper(self):
        return self.nominal + self.plus

    @property
    def lower(self):
        return self.nominal - self.minus

    @property
    def mean(self):
        return (self.upper + self.lower) / 2

    @property
    def tolerance(self):
        """The equal-bilateral +/- value."""
        return (self.plus + self.minus) / 2

    @property
    def shift(self):
        """Dimension shift: the mean's distance from the nominal."""
        return (self.plus - self.minus) / 2

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__slots__ if k in d})

    def __repr__(self):
        return (f"Contributor({self.name!r}, {self.nominal:g} +{self.plus:g}/-{self.minus:g}, "
                f"{'+' if self.direction > 0 else '-'}, {self.kind})")


# ---------------------------------------------------------------- GD&T contributors (Fischer)
def geometric(name, zone, kind="position", part="", source=""):
    """A geometric tolerance of total zone width (or diameter) `zone`: 0 +/- zone/2."""
    return Contributor(name, 0.0, zone / 2, kind=kind, part=part, source=source or f"{kind} {zone:g}")


def bonus(name, mmc, lmc, part="", source=""):
    """Bonus tolerance of a feature of size at MMC, on its own line: 0 +/- |LMC - MMC| / 2."""
    return Contributor(name, 0.0, abs(lmc - mmc) / 2, kind="bonus", part=part,
                       source=source or f"({lmc:g} - {mmc:g}) / 2")


def assembly_shift(name, hole_lmc, fastener_mmc, part="", source=""):
    """Assembly shift of a part floating on a fastener: 0 +/- (hole LMC - fastener MMC) / 2.
    In a floating-fastener joint it is entered once for each part that floats."""
    if hole_lmc < fastener_mmc:
        raise ValueError("the hole at LMC is smaller than the fastener at MMC: no clearance")
    return Contributor(name, 0.0, (hole_lmc - fastener_mmc) / 2, kind="assembly shift", part=part,
                       source=source or f"({hole_lmc:g} - {fastener_mmc:g}) / 2")


def flatness(name, value, part="", source=""):
    """Flatness of one of two mating planar faces (the smaller one): a zone shift of -F/2
    with +/- F/2 (Fischer's translational nesting)."""
    return Contributor(name, value / 2, value / 2, direction=-1, kind="flatness", part=part,
                       source=source or f"flatness {value:g}")


# ---------------------------------------------------------------- fastener and boundary formulas
def floating_fastener(fastener_mmc, position_tol=None, hole_mmc=None):
    """Cogorno ch. 8: H = F + T. Give two of fastener MMC F, position tolerance T, hole MMC H;
    returns the third."""
    if position_tol is None:
        return hole_mmc - fastener_mmc
    return fastener_mmc + position_tol


def fixed_fastener(fastener_mmc, t1=None, t2=None, hole_mmc=None):
    """Cogorno ch. 8: H = F + t1 + t2 (t1 threaded/fixed hole, t2 clearance hole).
    With hole_mmc and one of t1, t2: the other; with both tolerances: H. With hole_mmc alone the
    available tolerance H - F is split equally."""
    if hole_mmc is None:
        return fastener_mmc + t1 + t2
    avail = hole_mmc - fastener_mmc
    if t1 is None and t2 is None:
        return avail / 2, avail / 2
    return avail - (t1 if t1 is not None else t2)


def virtual_condition(mmc, tol, internal):
    """Worst-case functional boundary: hole MMC - tol, pin MMC + tol (tolerance at MMC)."""
    return mmc - tol if internal else mmc + tol


def resultant_condition(mmc, lmc, tol, internal):
    """The other worst-case boundary, at LMC with the full bonus: hole LMC + tol + bonus,
    pin LMC - tol - bonus."""
    b = abs(lmc - mmc)
    return lmc + tol + b if internal else lmc - tol - b


def total_position(tol, mmc, actual):
    """Tolerance available at an actual (mating) size: tol + |actual - MMC| (bonus)."""
    return tol + abs(actual - mmc)


# ---------------------------------------------------------------- analysis
def mrss_factor(t_wc, t_rss, n):
    """Drake's calculated MRSS correction factor; 1 for a single contributor."""
    if n <= 1 or t_rss <= 0:
        return 1.0
    return 0.5 * (t_wc - t_rss) / (t_rss * (math.sqrt(n) - 1)) + 1.0


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class Result:
    """Numbers of one analysis; min/max pairs are (mean - t, mean + t) for each method."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def as_dict(self):
        return dict(self.__dict__)


def analyse(contributors, lsl=None, usl=None, factor=1.5, samples=0, seed=1, sigma=3.0):
    """Analyse a stack. lsl / usl: the requirement on the result (e.g. a minimum gap), or None.
    samples > 0 adds a Monte Carlo run with that many assemblies (seeded, so repeatable)."""
    cs = [c for c in contributors]
    if not cs:
        raise ValueError("a stack-up needs at least one contributor")
    nominal = sum(c.direction * c.nominal for c in cs)
    mean = sum(c.direction * c.mean for c in cs)
    tols = [c.tolerance for c in cs]
    t_wc = sum(tols)
    t_rss = math.sqrt(sum(t * t for t in tols))
    n = sum(1 for t in tols if t > 0)
    cf = mrss_factor(t_wc, t_rss, n)
    methods = {
        "worst case": t_wc,
        "RSS": t_rss,
        f"adjusted RSS ({factor:g} x RSS)": factor * t_rss,
        f"MRSS (Cf {cf:.4f})": cf * t_rss,
    }
    limits = {m: (mean - t, mean + t) for m, t in methods.items()}
    wc_share = [t / t_wc if t_wc else 0.0 for t in tols]
    rss_share = [t * t / (t_rss * t_rss) if t_rss else 0.0 for t in tols]
    verdicts = {m: _verdict(lo, hi, lsl, usl) for m, (lo, hi) in limits.items()}
    # the statistical prediction behind RSS: each tolerance is +/- sigma standard deviations
    sd = t_rss / sigma
    stat = {"mean": mean, "sd": sd}
    if sd > 0:
        p_lo = normal_cdf((lsl - mean) / sd) if lsl is not None else 0.0
        p_hi = 1.0 - normal_cdf((usl - mean) / sd) if usl is not None else 0.0
        stat["ppm"] = (p_lo + p_hi) * 1e6
        if lsl is not None and usl is not None:
            stat["cp"] = (usl - lsl) / (6 * sd)
        ks = [(usl - mean) / (3 * sd)] if usl is not None else []
        ks += [(mean - lsl) / (3 * sd)] if lsl is not None else []
        if ks:
            stat["cpk"] = min(ks)
    mc = monte_carlo(cs, samples, seed, sigma, lsl, usl) if samples else None
    return Result(nominal=nominal, mean=mean, n=len(cs), active=n, t_wc=t_wc, t_rss=t_rss, cf=cf, factor=factor,
                  methods=methods, limits=limits, wc_share=wc_share, rss_share=rss_share, lsl=lsl, usl=usl,
                  verdicts=verdicts, stat=stat, mc=mc)


def _verdict(lo, hi, lsl, usl, eps=1e-12):
    if lsl is None and usl is None:
        return ""
    ok = (lsl is None or lo >= lsl - eps) and (usl is None or hi <= usl + eps)
    return "OK" if ok else "FAILS"


def monte_carlo(contributors, samples, seed=1, sigma=3.0, lsl=None, usl=None):
    """Simulate `samples` assemblies; returns their statistics and the share out of spec."""
    rng = random.Random(seed)
    draws = []
    for c in contributors:
        if c.tolerance == 0:
            draws.append(lambda c=c: c.mean)
        elif c.distribution == "uniform":
            draws.append(lambda c=c: rng.uniform(c.lower, c.upper))
        else:
            draws.append(lambda c=c, s=c.tolerance / sigma: rng.gauss(c.mean, s))
    signs = [c.direction for c in contributors]
    total = total2 = 0.0
    lo = hi = None
    below = above = 0
    for _ in range(int(samples)):
        v = 0.0
        for d, s in zip(draws, signs):
            v += s * d()
        total += v
        total2 += v * v
        lo = v if lo is None or v < lo else lo
        hi = v if hi is None or v > hi else hi
        if lsl is not None and v < lsl:
            below += 1
        if usl is not None and v > usl:
            above += 1
    m = total / samples
    sd = math.sqrt(max(total2 / samples - m * m, 0.0))
    return {"samples": int(samples), "seed": seed, "mean": m, "sd": sd, "min": lo, "max": hi,
            "below": below, "above": above, "ppm": (below + above) / samples * 1e6}


# ---------------------------------------------------------------- report
def report(contributors, result, title="Tolerance stack-up", units="mm", digits=4, direction=""):
    """A stack-up report laid out like Fischer's: + and - dimension columns, +/- tolerance,
    percent contribution, source; then each method's min and max."""
    cs = list(contributors)
    r = result
    f = f"{{:.{digits}f}}"
    lines = [title, f"Units: {units}" + (f"   Direction: {direction}" if direction else "")
             + f"   Contributors: {r.n}", ""]
    head = f"{'#':>3}  {'Description':<34} {'Part':<12} {'+ dims':>10} {'- dims':>10} {'+/- tol':>9} " \
           f"{'% WC':>6} {'% RSS':>6}  Source"
    lines += [head, "-" * len(head)]
    pos = neg = 0.0
    for i, c in enumerate(cs):
        m = c.mean
        p = f.format(m) if c.direction > 0 and m else ""
        q = f.format(m) if c.direction < 0 and m else ""
        pos += m if c.direction > 0 else 0.0
        neg += m if c.direction < 0 else 0.0
        src = c.source
        if c.shift:
            src = (src + "; " if src else "") + f"{c.nominal:g} +{c.plus:g}/-{c.minus:g} as {m:g} +/-{c.tolerance:g}"
        lines.append(f"{i + 1:>3}  {c.name[:34]:<34} {c.part[:12]:<12} {p:>10} {q:>10} {f.format(c.tolerance):>9} "
                     f"{100 * r.wc_share[i]:>6.1f} {100 * r.rss_share[i]:>6.1f}  {src}")
    lines += ["-" * len(head),
              f"{'':>3}  {'Totals':<34} {'':<12} {f.format(pos):>10} {f.format(neg):>10} {f.format(r.t_wc):>9}",
              "", f"Nominal result (+ dims minus - dims): {f.format(r.mean)}"
              + ("" if abs(r.mean - r.nominal) < 1e-12 else f"   (from nominal values {f.format(r.nominal)})")]
    req = []
    if r.lsl is not None:
        req.append(f">= {f.format(r.lsl)}")
    if r.usl is not None:
        req.append(f"<= {f.format(r.usl)}")
    lines += [f"Requirement: {' and '.join(req) if req else 'none given'}", "",
              f"{'Method':<26} {'+/- tol':>9} {'Min':>10} {'Max':>10}  Verdict"]
    for m, t in r.methods.items():
        lo, hi = r.limits[m]
        lines.append(f"{m:<26} {f.format(t):>9} {f.format(lo):>10} {f.format(hi):>10}  {r.verdicts[m]}")
    s = r.stat
    lines += ["", f"Statistical prediction: each tolerance taken as +/-3 sigma; sigma of the result "
              f"{f.format(s['sd'])}"]
    extra = []
    if "ppm" in s and (r.lsl is not None or r.usl is not None):
        extra.append(f"out of spec {s['ppm']:.1f} ppm")
    if "cp" in s:
        extra.append(f"Cp {s['cp']:.3f}")
    if "cpk" in s:
        extra.append(f"Cpk {s['cpk']:.3f}")
    if extra:
        lines.append("  " + ", ".join(extra))
    if r.mc:
        mc = r.mc
        lines += [f"Monte Carlo: {mc['samples']} assemblies (seed {mc['seed']}), mean {f.format(mc['mean'])}, "
                  f"sigma {f.format(mc['sd'])}, range {f.format(mc['min'])} to {f.format(mc['max'])}"]
        if r.lsl is not None or r.usl is not None:
            lines.append(f"  out of spec: {mc['below']} below, {mc['above']} above ({mc['ppm']:.1f} ppm)")
    if r.active < 4:
        lines += ["", "Note: fewer than four contributors; Fischer and Drake recommend the worst-case result here."]
    return "\n".join(lines)


def to_csv_rows(contributors, result):
    """Rows (with a header) for a spreadsheet or a release package."""
    rows = [["#", "description", "part", "kind", "direction", "nominal", "plus", "minus", "mean", "tolerance",
             "pct_wc", "pct_rss", "source"]]
    for i, c in enumerate(contributors):
        rows.append([i + 1, c.name, c.part, c.kind, "+" if c.direction > 0 else "-", c.nominal, c.plus, c.minus,
                     c.mean, c.tolerance, round(100 * result.wc_share[i], 3), round(100 * result.rss_share[i], 3),
                     c.source])
    rows.append([])
    rows.append(["method", "tolerance", "min", "max", "verdict"])
    for m, t in result.methods.items():
        lo, hi = result.limits[m]
        rows.append([m, t, lo, hi, result.verdicts[m]])
    return rows

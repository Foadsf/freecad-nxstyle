# SPDX-License-Identifier: LGPL-2.1-or-later
"""Product and Manufacturing Information (PMI): the semantic part (no FreeCAD needed).

A PMI annotation is a dict, as stored in the model (see pmi_ui) and in a release package:

  id            unique name of the annotation in its part
  kind          "dimension", "fcf" (geometrical tolerance frame), "datum" (datum feature)
  feature       what it is attached to, e.g. "Body:Face7" (one string, or two joined by " | ")
  feature_type  "plane", "hole" (internal cylinder), "pin" (external cylinder), "width" (two
                opposed planes: a slot or a tab), or "other"
  dimension:    dim_type ("distance", "diameter", "radius", "angle"), nominal, plus, minus
                (deviations as magnitudes), fit (an ISO 286 tolerance class such as "H7"; it
                gives the deviations), envelope (ISO 14405 (E)), basic (theoretically exact),
                count (4 for "4X")
  fcf:          characteristic (a key of gdt.SYMBOLS), tolerance, diameter (Ø zone),
                modifier ("", "MMC", "LMC"), datums [[letter, modifier], ...]; a two-row frame also
                has lower {tolerance, modifier, datums} and frame "composite" (ASME Y14.5 composite:
                the lower row, FRTZF, refines the spacing of the pattern and its orientation to the
                datums it repeats, never their location) or "single" (two single-segment frames: the
                lower row's datums locate as well as orient)
  datum:        letter
  number        characteristic number for inspection (set by number())
  uncertainty   expanded measurement uncertainty U (k = 2) of the method that checks it, mm (optional:
                the inspection plan then gives the TUR and the ISO 14253-1 acceptance limits; msa.py)

The part's tolerancing standard is ISO GPS by default (technical product documentation: ISO 1101,
ISO 5459, ISO 8015, ISO 14405, ISO 286, ISO 2768), or ASME Y14.5. They differ where it matters:

- ISO 8015 independency (ISO's default): a size tolerance controls local sizes only, never form;
  a feature that must fit needs the envelope (E) or a form tolerance. ASME's Rule #1 puts every
  size inside an envelope of perfect form at MMC, so (E) is redundant there.
- ISO 2768 general tolerances cover dimensions without an individual tolerance when the title
  block says so (e.g. ISO 2768-mK); ASME Y14.5 has none.
- ASME Y14.5 does not use I, O and Q as datum letters, and its 2018 edition dropped concentricity
  and symmetry.

Common to both: form tolerances take no datums, orientation and run-out need one, (M) and (L)
apply only to features of size, run-out is always RFS, and every datum a frame refers to must be
identified. Gauge sizes are the virtual condition (Cogorno ch. 3 and 13): a fixed gauge pin for a
hole at MMC is its MMC size minus its tolerance; a datum feature of size referenced at MMC is
simulated at its maximum material boundary.
"""

from . import gdt, iso

FORM = {"flatness", "straightness", "circularity", "cylindricity"}
ORIENTATION = {"perpendicularity", "parallelism", "angularity"}
LOCATION = {"position", "concentricity", "symmetry"}
RUNOUT = {"circular runout", "total runout"}
PROFILE = {"profile of a surface", "profile of a line"}
SIZE_FEATURES = {"hole", "pin", "width"}
NOT_DATUM_LETTERS = set("IOQ")
DIAMETER = "Ø"
ENVELOPE = "Ⓔ"
STANDARDS = ("ISO", "ASME")


def fmt(v, digits=3):
    return f"{v:.{digits}f}"


# ------------------------------------------------------------------------ dimensions
def deviations(a, general=None):
    """(plus, minus, source) of a dimension: its fit class (ISO 286), its own tolerance, or the
    general tolerance (ISO 2768-1) the part's note gives; (0, 0, '') when none applies."""
    if a.get("basic"):
        return 0.0, 0.0, "basic"
    if a.get("fit"):
        up, lo = iso.deviations(a["fit"], a["nominal"])
        return up, -lo, f"ISO 286 {a['fit']}"           # minus as a magnitude below nominal
    p, m = a.get("plus", 0.0), a.get("minus", 0.0)
    if p or m:
        return p, m, "individual"
    g = iso.parse_general(general) if general else None
    if g and a.get("dim_type") in ("distance", "diameter", "radius"):
        t = iso.linear(a["nominal"], g[0])
        return t, t, f"ISO 2768-{g[0]}"
    return 0.0, 0.0, ""


def size_limits(a, general=None):
    """(lower, upper) of a dimension."""
    p, m, _ = deviations(a, general)
    return a["nominal"] - m, a["nominal"] + p


def mmc_lmc(a, general=None):
    """(MMC, LMC) of a size dimension: a hole is at MMC when smallest, a pin when largest."""
    lo, hi = size_limits(a, general)
    if internal(a):
        return lo, hi
    return hi, lo


def internal(a):
    return a.get("feature_type") == "hole" or (a.get("feature_type") == "width" and a.get("internal", True))


def deviation_text(v, digits=3):
    """A limit deviation: signed, and a zero one as the digit 0 without a sign (ISO 129-1; ASME Y14.5 for
    metric drawings), never "-0.000" or "+0.000"."""
    if abs(v) < 0.5 * 10 ** -digits:
        return "0"
    return f"{v:+.{digits}f}"


def dimension_text(a, digits=3):
    prefix = {"diameter": DIAMETER, "radius": "R"}.get(a.get("dim_type"), "")
    count = f"{a['count']}X " if a.get("count", 1) > 1 else ""
    value = prefix + fmt(a["nominal"], digits) + ("°" if a.get("dim_type") == "angle" else "")
    env = f" {ENVELOPE}" if a.get("envelope") else ""
    if a.get("basic"):
        return f"{count}[{value}]"
    if a.get("fit"):
        up, lo = iso.deviations(a["fit"], a["nominal"])
        return f"{count}{value} {a['fit']} ({deviation_text(up, digits)}/{deviation_text(lo, digits)}){env}"
    p, m = a.get("plus", 0.0), a.get("minus", 0.0)
    if p == 0 and m == 0:
        return count + value + env
    if abs(p - m) < 1e-12:
        return f"{count}{value} ±{fmt(p, digits)}{env}"
    # signed deviations: a zone wholly above (or below) nominal reads +0.050/+0.020, never "--0.020"
    return f"{count}{value} {deviation_text(p, digits)}/{deviation_text(-m, digits)}{env}"


def lower(a):
    """The lower row of a two-row frame (dict), or None for a single frame."""
    low = a.get("lower")
    if a.get("kind") != "fcf" or not low or not low.get("tolerance"):
        return None
    return low


def composite(a):
    return lower(a) is not None and a.get("frame", "composite") == "composite"


def text(a, digits=3):
    """The annotation as one line of text."""
    k = a["kind"]
    if k == "dimension":
        return dimension_text(a, digits)
    if k == "fcf":
        upper = (fmt(a["tolerance"], digits), a.get("diameter", False), a.get("modifier", ""),
                 [tuple(d) for d in a.get("datums", [])])
        low = lower(a)
        if low is None:
            return gdt.callout(a["characteristic"], *upper)
        row = (fmt(low["tolerance"], digits), a.get("diameter", False), low.get("modifier", ""),
               [tuple(d) for d in low.get("datums", [])])
        return gdt.stacked_callout(a["characteristic"], [upper, row], a.get("frame", "composite") == "composite")
    if k == "datum":
        return f"datum feature {a['letter']}"
    return a.get("text", "")


# ------------------------------------------------------------------------ checks
def check(annotations, standard="ISO", general=None):
    """Consistency checks. Returns [(severity, id, message)], severity "error", "warning" or "note"."""
    out = []
    datums = {}
    std = standard.upper()
    g = iso.parse_general(general) if general else None
    for a in annotations:
        if a["kind"] == "datum":
            L = a["letter"]
            if not L or not L.isalpha() or not L.isupper():
                out.append(("error", a["id"], f"datum letter {L!r}: use capital letters"))
            elif std == "ASME" and any(c in NOT_DATUM_LETTERS for c in L):
                out.append(("error", a["id"], f"datum letter {L}: ASME Y14.5 does not use I, O and Q"))
            if L in datums:
                out.append(("error", a["id"], f"datum {L} is identified twice ({datums[L]['id']} and {a['id']})"))
            datums[L] = a
    sizes = {a.get("feature"): a for a in annotations if a["kind"] == "dimension" and not a.get("basic")
             and a.get("feature_type") in SIZE_FEATURES}
    form_on = {a.get("feature") for a in annotations if a["kind"] == "fcf" and a["characteristic"] in FORM}
    for a in annotations:
        if a["kind"] == "dimension":
            out += _check_dimension(a, std, g, general, form_on)
            continue
        if a["kind"] != "fcf":
            continue
        c, ds, mod = a["characteristic"], [d[0] for d in a.get("datums", [])], a.get("modifier", "")
        if a.get("tolerance", 0) <= 0:
            out.append(("error", a["id"], "the tolerance must be greater than zero"))
        if c in FORM and ds:
            out.append(("error", a["id"], f"{c} is a form tolerance: it takes no datum reference"))
        if (c in ORIENTATION or c in RUNOUT or c in {"concentricity", "symmetry"}) and not ds:
            out.append(("error", a["id"], f"{c} needs a datum reference"))
        if std == "ASME" and c in {"concentricity", "symmetry"}:
            out.append(("warning", a["id"], f"ASME Y14.5-2018 no longer has {c}: use position or profile"))
        if c == "position" and not ds:
            out.append(("warning", a["id"], "position without datums only locates the features to each other"))
        fos = a.get("feature_type") in SIZE_FEATURES
        if mod and not fos:
            out.append(("error", a["id"], f"{mod} applies only to a feature of size, not to a {a.get('feature_type')}"))
        if mod and c in RUNOUT | {"concentricity", "symmetry"}:
            out.append(("error", a["id"], f"{c} is always RFS; no material condition modifier"))
        if mod and c in PROFILE:
            out.append(("error", a["id"], "profile takes no material condition modifier on its tolerance"))
        if a.get("diameter") and not (fos and c in LOCATION | ORIENTATION | {"straightness"}):
            out.append(("error", a["id"], f"a Ø zone needs an axis: not for {c} on a {a.get('feature_type')}"))
        if mod and fos and a.get("feature") not in sizes:
            out.append(("warning", a["id"], "the feature has no size dimension: its MMC (and bonus) is unknown"))
        if len(set(ds)) != len(ds):
            out.append(("error", a["id"], "a datum letter is repeated in the frame"))
        low = lower(a)
        low_refs = list(low.get("datums", [])) if low else []
        if low:
            out += _check_lower(a, low, std, ds, fos)
        for d, dm in list(a.get("datums", [])) + low_refs:
            if d not in datums:
                out.append(("error", a["id"], f"datum {d} is referenced but not identified on the part"))
            elif dm and datums[d].get("feature_type") not in SIZE_FEATURES:
                out.append(("error", a["id"], f"datum {d} is not a feature of size: it cannot be referenced at "
                            f"{'MMC' if dm == 'MMC' else 'LMC'}"))
    return out


def _check_lower(a, low, std, ds, fos):
    """The lower row of a two-row frame (Cogorno ch. 12, Drake ch. 5): it refines the upper row, so it
    must be tighter; a composite lower row may only repeat the upper row's datums, in their order, and
    they orient it, never locate it."""
    out = []
    c, kind = a["characteristic"], a.get("frame", "composite")
    lds = [d[0] for d in low.get("datums", [])]
    if c not in {"position"} | PROFILE:
        out.append(("error", a["id"], f"a two-row frame is for position or profile, not {c}"))
    if low["tolerance"] >= a.get("tolerance", 0):
        out.append(("error", a["id"], f"the lower row ({fmt(low['tolerance'])}) must be tighter than the upper "
                    f"({fmt(a.get('tolerance', 0))}): it refines the pattern within it"))
    if kind == "composite" and lds != ds[:len(lds)]:
        out.append(("error", a["id"], f"the composite lower row may only repeat the upper row's datums in their "
                    f"order ({'|'.join(ds) or 'none'}), not {'|'.join(lds)}"))
    if len(set(lds)) != len(lds):
        out.append(("error", a["id"], "a datum letter is repeated in the lower row"))
    if low.get("modifier") and not fos:
        out.append(("error", a["id"], f"{low['modifier']} in the lower row applies only to a feature of size"))
    if low.get("modifier") and c in PROFILE:
        out.append(("error", a["id"], "profile takes no material condition modifier on its tolerance"))
    if kind == "single" and not lds:
        out.append(("warning", a["id"], "a single-segment lower row without datums is the same as a composite one: "
                    "use the composite frame"))
    if std == "ISO":
        out.append(("note", a["id"], "two-row (composite) frames are ASME Y14.5 notation; ISO GPS states a "
                    "pattern with ISO 5458 (two frames, combined zone CZ)"))
    return out


def _check_dimension(a, std, g, general, form_on):
    out = []
    if a.get("basic"):
        if a.get("plus") or a.get("minus") or a.get("fit"):
            out.append(("error", a["id"], "a theoretically exact (basic) dimension has no tolerance of its own"))
        return out
    try:
        p, m, source = deviations(a, general)
    except ValueError as e:
        return [("error", a["id"], str(e))]
    if not source:
        what = "and the part has no ISO 2768 general tolerance note" if std == "ISO" else \
            "(ASME Y14.5 has no general tolerances: give it one, or a title block tolerance)"
        out.append(("warning", a["id"], f"{dimension_text(a)} has no tolerance {what}"))
    if a.get("fit") and (a.get("plus") or a.get("minus")):
        out.append(("warning", a["id"], f"both a fit class {a['fit']} and +/- values: the fit class is used"))
    if a.get("fit"):
        _, _, kind = iso.parse_class(a["fit"])
        ft = a.get("feature_type")
        if (kind == "hole") != (ft == "hole") and ft in ("hole", "pin"):
            out.append(("error", a["id"], f"{a['fit']} is a {kind} class on a {'hole' if ft == 'hole' else 'shaft'}: "
                        f"use {'capital' if ft == 'hole' else 'lower-case'} letters"))
    fos = a.get("feature_type") in SIZE_FEATURES
    envelope = a.get("envelope") or (g is not None and g[2])
    if std == "ISO" and fos and not envelope and a.get("feature") not in form_on:
        if a.get("fit"):
            out.append(("warning", a["id"], f"{a['fit']} is a fit, but under ISO 8015 independency the size controls "
                        "only two-point sizes, not form: add the envelope (E) (ISO 14405) or a form tolerance"))
        else:
            out.append(("note", a["id"], "ISO 8015: the size limits do not control the form of this feature; "
                        "add (E) if it must mate"))
    if std == "ASME" and a.get("envelope"):
        out.append(("note", a["id"], "ASME Y14.5 Rule #1 already applies the envelope; (E) is ISO notation"))
    return out


# ------------------------------------------------------------------------ characteristics
def characteristic(a, general=None):
    """What an inspector measures and records: dimensions with a tolerance (their own, a fit
    class, or the general tolerance) and geometrical tolerances."""
    if a["kind"] == "fcf":
        return True
    if a["kind"] != "dimension" or a.get("basic"):
        return False
    try:
        return bool(deviations(a, general)[2])
    except ValueError:
        return False


def number(annotations, start=1, general=None):
    """Give every characteristic a number (its balloon), in order; others get 0."""
    n = start
    for a in annotations:
        if characteristic(a, general):
            a["number"] = n
            n += 1
        else:
            a["number"] = 0
    return annotations


def method(a):
    if a["kind"] == "dimension":
        if a.get("envelope"):
            return "GO gauge (envelope) and two-point NO-GO, or CMM"
        return {"diameter": "bore gauge or CMM" if a.get("feature_type") == "hole" else "micrometer or CMM",
                "angle": "CMM", "radius": "radius gauge or CMM"}.get(a.get("dim_type"), "caliper, height gauge or CMM")
    if a.get("modifier") == "MMC" and a["characteristic"] in LOCATION | ORIENTATION:
        return "functional gauge (virtual condition) or CMM"
    if a["characteristic"] in FORM:
        return "surface plate and indicator, or CMM"
    if a["characteristic"] in RUNOUT:
        return "indicator on a datum axis"
    return "CMM"


def inspection_plan(annotations, digits=3, general=None):
    """One row per characteristic: number, requirement, nominal, lower and upper limit, where the
    tolerance comes from, feature, datums, method. Frames at MMC also give the tolerance at LMC."""
    sizes = {a.get("feature"): a for a in annotations if a["kind"] == "dimension" and not a.get("basic")}
    rows = []
    for a in annotations:
        if not characteristic(a, general):
            continue
        row = {"number": a.get("number", 0), "id": a["id"], "requirement": text(a, digits), "feature": a.get("feature", ""),
               "datums": "", "method": method(a), "note": "", "tolerance_from": "individual"}
        if a["kind"] == "dimension":
            p, m, source = deviations(a, general)
            row.update(kind=a.get("dim_type", "distance"), nominal=a["nominal"], lower=a["nominal"] - m,
                       upper=a["nominal"] + p, tolerance_from=source)
            if source.startswith("ISO 2768"):
                row["requirement"] += f" ({source}: ±{fmt(p, digits)})"
            notes = []
            if a.get("count", 1) > 1:
                notes.append(f"{a['count']} places")
            if a.get("envelope"):
                notes.append("envelope: perfect form at MMC")
            row["note"] = "; ".join(notes)
        else:
            low = lower(a)
            segments = [(a["tolerance"], a.get("modifier", ""), a.get("datums", []), "")]
            if low:
                comp = composite(a)
                segments = [(a["tolerance"], a.get("modifier", ""), a.get("datums", []), "PLTZF" if comp else "upper"),
                            (low["tolerance"], low.get("modifier", ""), low.get("datums", []), "FRTZF" if comp else "lower")]
            size = sizes.get(a.get("feature"))
            for tol, mod, datums, seg in segments:
                r = dict(row)
                letters = "|".join(d + ({"MMC": "(M)", "LMC": "(L)"}.get(m, "")) for d, m in datums)
                r.update(kind=a["characteristic"], nominal=0.0, lower=0.0, upper=tol, datums=letters, segment=seg)
                notes = []
                if seg:
                    r["requirement"] = gdt.callout(a["characteristic"], fmt(tol, digits), a.get("diameter", False), mod,
                                                   [tuple(d) for d in datums])
                    notes.append(_segment_note(seg, letters))
                    r["method"] = segment_method(a, mod, seg)
                if mod in ("MMC", "LMC") and size is not None:
                    mmc, lmc = mmc_lmc(size, general)
                    at = mmc if mod == "MMC" else lmc
                    other = lmc if mod == "MMC" else mmc
                    r["upper_at_departure"] = tol + abs(other - at)
                    notes.append(f"{fmt(tol, digits)} at {mod} ({fmt(at, digits)}), up to "
                                 f"{fmt(r['upper_at_departure'], digits)} at {'LMC' if mod == 'MMC' else 'MMC'} "
                                 f"({fmt(other, digits)})")
                r["note"] = "; ".join(notes)
                rows.append(r)
            continue
        rows.append(row)
    by_id = {a["id"]: a for a in annotations}
    for r in rows:
        u = by_id[r["id"]].get("uncertainty", 0.0)
        if u > 0:
            _add_uncertainty(r, u, digits)
    return rows


def _add_uncertainty(r, u, digits):
    """TUR and the ISO 14253-1 acceptance limits of a plan row whose method has the uncertainty U."""
    from . import msa
    one_sided = r["kind"] not in ("distance", "diameter", "radius", "angle")
    ratio = msa.tur(r["lower"], r["upper"], u)
    acc = msa.acceptance(r["lower"], r["upper"], u, one_sided)
    r.update(uncertainty=u, tur=round(ratio, 2))
    text = f"U {fmt(u, digits)}: TUR {msa.ratio_text(ratio)} ({msa.tur_verdict(ratio)})"
    if acc is None:
        r.update(accept_lower="", accept_upper="")
        text += "; U leaves no acceptance zone (ISO 14253-1): the method cannot prove conformance"
    else:
        r.update(accept_lower=acc[0], accept_upper=acc[1])
        text += (f"; accept {fmt(acc[1], digits)} max" if one_sided else
                 f"; accept {fmt(acc[0], digits)} to {fmt(acc[1], digits)}") + " (ISO 14253-1)"
    r["note"] = "; ".join(x for x in (r["note"], text) if x)


def _segment_note(seg, letters):
    return {"PLTZF": f"pattern-locating zone: locates and orients the pattern to {letters or 'nothing'}",
            "FRTZF": "feature-relating zone: spacing of the features" + (f", orientation to {letters}" if letters else
                                                                          "; the pattern may float and turn"),
            "upper": f"upper segment: locates the pattern to {letters or 'nothing'}",
            "lower": f"lower segment: locates and orients the pattern to {letters or 'nothing'}, spacing tighter"}[seg]


def segment_method(a, mod, seg):
    """How a row of a two-row frame is verified (Cogorno ch. 13): one functional gauge per row, the
    FRTZF gauge without the location datums; or a CMM, the lower row best-fit."""
    if mod == "MMC":
        return ("functional gauge with datums" if seg in ("PLTZF", "upper") else
                "second functional gauge (orientation datums only, pins float)" if seg == "FRTZF" else
                "second functional gauge") + " or CMM"
    if seg == "FRTZF":
        return "CMM: best fit of the pattern (Analysis > Position Evaluation)"
    return "CMM"


def gauges(annotations, general=None):
    """Functional gauge elements for frames at MMC on features of size, and datum feature
    simulators at MMC (MMB). Returns rows: element, for, size, how."""
    sizes = {a.get("feature"): a for a in annotations if a["kind"] == "dimension" and not a.get("basic")
             and a.get("feature_type") in SIZE_FEATURES}
    datum_feature = {a["letter"]: a.get("feature") for a in annotations if a["kind"] == "datum"}
    out = []
    vc_of = {}
    for a in annotations:
        if a["kind"] != "fcf":
            continue
        size = sizes.get(a.get("feature"))
        if size is None:
            continue
        mmc, _ = mmc_lmc(size, general)
        hole = internal(size)
        count = size.get("count", 1)
        low = lower(a)
        rows = [(a["tolerance"], a.get("modifier", ""), a.get("datums", []), "")]
        if low:                       # a two-row frame takes one gauge per row (Cogorno ch. 13)
            comp = composite(a)
            rows = [(a["tolerance"], a.get("modifier", ""), a.get("datums", []), "PLTZF" if comp else "upper"),
                    (low["tolerance"], low.get("modifier", ""), low.get("datums", []), "FRTZF" if comp else "lower")]
        for tol, mod, datums, seg in rows:
            if mod != "MMC":
                continue
            vc = mmc - tol if hole else mmc + tol
            if not seg or seg in ("PLTZF", "upper"):
                vc_of.setdefault(a.get("feature"), []).append((a, vc))
            what = text(a) if not seg else f"{seg}: " + gdt.callout(a["characteristic"], fmt(tol), a.get("diameter", False),
                                                                   mod, [tuple(d) for d in datums])
            how = f"virtual condition: MMC {mmc:g} {'-' if hole else '+'} {tol:g}"
            if seg == "FRTZF":
                letters = "|".join(d for d, _ in datums)
                how += ("; on " + letters + " only, the pins float" if letters else "; the pins float") + \
                    " (no stops for the location datums)"
            out.append({"element": ("gauge pin" if hole else "gauge hole") + (f" x{count}" if count > 1 else ""),
                        "for": what, "size": vc, "feature": a.get("feature"), "how": how})
    for letter, feat in datum_feature.items():
        referenced = any(a["kind"] == "fcf" and any(d == letter and m == "MMC" for d, m in a.get("datums", []))
                         for a in annotations)
        size = sizes.get(feat)
        if not referenced or size is None:
            continue
        hole = internal(size)
        # a secondary or tertiary datum feature at MMC is simulated at its virtual condition with respect to
        # the higher-precedence datums (its orientation tolerance); with none, at its MMC size
        cands = [vc for a, vc in vc_of.get(feat, []) if a["characteristic"] in ORIENTATION]
        cands = cands or [vc for _, vc in vc_of.get(feat, [])]
        mmc, _ = mmc_lmc(size, general)
        mmb = (max(cands) if hole else min(cands)) if cands else mmc
        out.append({"element": f"datum {letter} simulator ({'pin' if hole else 'hole'})", "for": f"datum {letter} at MMC",
                    "size": mmb, "feature": feat,
                    "how": "maximum material boundary: " + ("its orientation tolerance's virtual condition" if cands
                                                            else "its MMC size")})
    return out


def report(annotations, digits=3, title="PMI", standard="ISO", general=None):
    """Characteristics, gauge elements and checks as text, for the Information window."""
    number(annotations, general=general)
    std = "ISO GPS (ISO 8015 independency)" if standard.upper() == "ISO" else "ASME Y14.5 (Rule #1 envelope)"
    lines = [title, f"Standard: {std}" + (f"; general tolerances {general}" if general else ""), ""]
    plan = inspection_plan(annotations, digits, general)
    lines.append(f"{'No.':>4}  {'Requirement':<46} {'Lower':>9} {'Upper':>9}  {'Datums':<8}  Method")
    for r in plan:
        lines.append(f"{r['number']:>4}  {r['requirement'][:46]:<46} {fmt(r['lower'], digits):>9} "
                     f"{fmt(r['upper'], digits):>9}  {r['datums']:<8}  {r['method']}")
        if r["note"]:
            lines.append(f"{'':>6}{r['note']}")
    gg = gauges(annotations, general)
    if gg:
        lines += ["", "Functional gauge"]
        for e in gg:
            lines.append(f"  {e['element']:<26} {DIAMETER}{fmt(e['size'], digits):<10} {e['for']}  ({e['how']})")
    issues = check(annotations, standard, general)
    lines += ["", "Checks: " + ("no issues" if not issues else f"{len(issues)} finding(s)")]
    for sev, aid, msg in issues:
        lines.append(f"  {sev:<7} {aid}: {msg}")
    return "\n".join(lines)

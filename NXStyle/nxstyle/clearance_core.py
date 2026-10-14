# SPDX-License-Identifier: LGPL-2.1-or-later
"""Assembly clearance analysis: how a pair of objects is classified (no FreeCAD needed).

NX's Assembly Clearance reports four kinds of interference between two objects:

- hard:        the objects intersect (a common volume);
- containment: one object lies completely inside the other (a hard interference whose common
               volume is the whole of the smaller object);
- touching:    they touch but do not intersect (distance zero, no common volume);
- soft:        they do not touch, but are closer than the clearance zone.

Pairs further apart than the zone are clear. The zone is the set's default, or a pair's own.
"""

KINDS = ("hard", "containment", "touching", "soft")
VOLUME_TOL = 1e-3        # mm^3: a smaller common volume is a numerical sliver, not an interference
DISTANCE_TOL = 1e-6      # mm: closer than this is touching


def classify(distance, common_volume, volume_a, volume_b, zone=0.0, vtol=VOLUME_TOL, dtol=DISTANCE_TOL):
    """'hard', 'containment', 'touching', 'soft' or None (clear)."""
    if common_volume > vtol:
        smaller = min(volume_a, volume_b)
        if smaller > 0 and abs(common_volume - smaller) <= max(vtol, 1e-6 * smaller):
            return "containment"
        return "hard"
    if distance <= dtol:
        return "touching"
    if zone > 0 and distance <= zone:
        return "soft"
    return None


def pair_key(a, b):
    """Order-independent key of a pair of object names."""
    return "|".join(sorted((a, b)))


def parse_rules(lines):
    """Pair rules as stored in a clearance set, one per line:
        'Bolt|Plate=exclude'   leave this pair out
        'Shaft|Bushing=0.5'    this pair's own clearance zone (mm)
    Returns {pair key: 'exclude' or zone float}."""
    rules = {}
    for line in lines or []:
        if "=" not in line or "|" not in line:
            continue
        pair, value = line.split("=", 1)
        a, b = (p.strip() for p in pair.split("|", 1))
        value = value.strip().lower()
        if value in ("exclude", "excluded", "ignore"):
            rules[pair_key(a, b)] = "exclude"
        else:
            try:
                rules[pair_key(a, b)] = float(value)
            except ValueError:
                continue
    return rules


def status(previous, current):
    """NX's clearance browser marks each interference New, Unchanged or Changed against the last
    run, and lists the ones that are gone. previous / current: {pair key: kind}."""
    out = {}
    for k, kind in current.items():
        if k not in previous:
            out[k] = "New"
        elif previous[k] == kind:
            out[k] = "Unchanged"
        else:
            out[k] = f"Changed (was {previous[k]})"
    for k in previous:
        if k not in current:
            out[k] = "Gone"
    return out

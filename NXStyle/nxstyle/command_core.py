# SPDX-License-Identifier: LGPL-2.1-or-later
"""What the command controller decides, without FreeCAD: typed lengths, and Extrude's Boolean options.

NX's Extrude has one Boolean list: None (a new body), Unite, Subtract, Intersect. PartDesign has no Boolean
property: a Pad adds to its Body, a Pocket removes from it, and a separate solid is a separate Body. The
controller maps the NX choice onto those features and states every choice it cannot map instead of
approximating it.
"""

import re

# ------------------------------------------------------------------ lengths
LENGTH_UNITS = {
    "mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0, "um": 1e-3, "µm": 1e-3, "μm": 1e-3, "nm": 1e-6,
    "in": 25.4, "inch": 25.4, '"': 25.4, "ft": 304.8, "'": 304.8, "thou": 0.0254, "mil": 0.0254,
}
_NUMBER = re.compile(r"^\s*([+-]?)\s*([0-9]*[.,]?[0-9]*)\s*([A-Za-zµμ\"']*)\s*$")


class UnitError(ValueError):
    pass


def parse_length(text, decimal=".", default_unit="mm"):
    """Typed length text -> millimetres. decimal is the field's decimal separator ('.' or ','); the other
    one is refused, not guessed: in a ',' locale Qt reads '3.175' as 3175."""
    t = (text or "").replace("−", "-").strip()
    if not t:
        raise UnitError("no value")
    if t.startswith("=") or any(op in t for op in "*/()"):
        raise UnitError(f"'{text}' is an expression; only plain lengths are read here")
    other = "," if decimal == "." else "."
    m = _NUMBER.match(t)
    if not m or not m.group(2) or m.group(2) in ".,":
        raise UnitError(f"'{text}' is not a length")
    sign, num, unit = m.groups()
    if other in num:
        raise UnitError(f"'{text}': the decimal separator here is '{decimal}'")
    unit = unit or default_unit
    key = unit if unit in LENGTH_UNITS else unit.lower()
    if key not in LENGTH_UNITS:
        raise UnitError(f"'{unit}' is not a length unit")
    value = float(num.replace(decimal, ".")) * LENGTH_UNITS[key]
    return -value if sign == "-" else value


def read_back_issue(text, read_mm, decimal=".", tol=1e-6):
    """The message for a field that took typed text as another length than the text says, else None.

    The case it exists for: '3.175' typed where ',' is the decimal separator, which the field reads as
    3175 mm. Text this module cannot read (an expression, an angle) gives None: nothing to compare."""
    try:
        meant = parse_length(text, decimal)
    except UnitError:
        other = "," if decimal == "." else "."
        try:
            meant = parse_length(text, other)
        except UnitError:
            return None
        if abs(meant - read_mm) <= tol * max(1.0, abs(meant)):
            return None
        return (f"'{text}' was read as {read_mm:g} mm: the decimal separator here is '{decimal}' "
                f"(type {text.replace(other, decimal)} for {meant:g} mm)")
    if abs(meant - read_mm) <= tol * max(1.0, abs(meant)):
        return None
    return f"'{text}' means {meant:g} mm, but the field read {read_mm:g} mm"


# ------------------------------------------------------------------ Extrude
BOOLEANS = [("new_body", "None"), ("unite", "Unite"), ("subtract", "Subtract"), ("intersect", "Intersect")]
LABELS = dict(BOOLEANS)

UNSUPPORTED = {
    "intersect": "Intersect is not offered: PartDesign has no intersecting extrude, and NX-Style does not "
                 "approximate it.",
}

# NX Extrude options and what this Extrude does with each (shown in the command panel and in the docs)
EXTRUDE_OPTIONS = [
    ("Boolean None (a new body)", "supported", "a Pad that starts a Body: in the sketch's Body while it has no "
                                             "solid, otherwise in a new Body through a sub-shape binder"),
    ("Boolean Unite", "supported", "a Pad in the sketch's Body"),
    ("Boolean Subtract", "supported", "a Pocket in the sketch's Body"),
    ("Boolean Intersect", "not supported", UNSUPPORTED["intersect"]),
    ("Boolean target body", "sketch's Body only", "NX lets you pick the target body; here it is the Body that "
                                                 "holds the sketch"),
    ("Limits Value, Symmetric Value, Until Next, Until Selected, Through All", "supported",
     "the FreeCAD panel's Type list (Dimension, Symmetric, To first, Up to face, Through all)"),
    ("Start limit other than 0 on one side", "not supported", "FreeCAD extrudes from the sketch plane; Two "
                                                            "sided gives a length each way"),
    ("Until Extended", "not supported", "no FreeCAD equivalent"),
    ("Draft from start limit", "supported", "the Pad's Taper angle"),
    ("Draft from section, asymmetric or matched ends", "not supported", "FreeCAD has one taper angle"),
    ("Offset (single, two-sided, symmetric)", "not supported", "FreeCAD's Offset is the up-to-face offset, "
                                                               "not NX's section offset"),
    ("Body type Sheet", "not supported", "a Pad makes solids"),
    ("Change the Boolean when editing", "not supported", "it would replace the feature and break what refers "
                                                         "to it; delete and extrude again"),
]

DIRECTION_NOTE = ("Subtract cuts into the part (against the sketch normal) and Unite or None build along "
                  "it, unless Reversed is ticked; NX keeps one direction for every Boolean.")
SHORT_NOTE = ("Subtract cuts into the part unless Reversed. Not offered: Intersect, target body, start limit, "
              "Until Extended, section draft, Offset, Sheet.")


def unsupported_summary():
    return "; ".join(name for name, status, _ in EXTRUDE_OPTIONS if status == "not supported")


def options_tooltip():
    """Every NX Extrude option with what this Extrude does with it (the command box's tooltip)."""
    return "\n".join([DIRECTION_NOTE, ""] + [f"{name}: {status} ({how})" for name, status, how in EXTRUDE_OPTIONS])


def infer_boolean(requested, has_body, has_solid):
    """NX's inferred Boolean: Unite onto the part, None (a new body) when there is nothing to unite with."""
    if requested:
        return requested
    return "unite" if has_body and has_solid else "new_body"


def plan_extrude(mode, has_body, has_solid, body_label="the Body"):
    """How a Boolean choice is built: {'feature': type id, 'body': 'sketch' or 'new'}. Raises CommandError
    with the reason when it cannot be built."""
    if mode not in LABELS:
        raise CommandError(f"unknown Boolean '{mode}'")
    if mode in UNSUPPORTED:
        raise CommandError(UNSUPPORTED[mode])
    if mode == "new_body":
        if has_body and not has_solid:
            return {"feature": "PartDesign::Pad", "body": "sketch"}
        return {"feature": "PartDesign::Pad", "body": "new"}
    if not has_body:
        raise CommandError(f"{LABELS[mode]} needs a target body: the sketch is not in a Body")
    if not has_solid:
        raise CommandError(f"{LABELS[mode]} needs a solid in {body_label}, which has none yet: choose None for a new body")
    return {"feature": "PartDesign::Pad" if mode == "unite" else "PartDesign::Pocket", "body": "sketch"}


def mode_of(type_id, has_base):
    """The NX Boolean an existing Pad or Pocket stands for."""
    if type_id == "PartDesign::Pocket":
        return "subtract"
    return "unite" if has_base else "new_body"


def result_warning(mode, base_volume, volume, rel=1e-9):
    """A Unite that adds nothing or a Subtract that removes nothing (the extrusion misses the part)."""
    eps = rel * max(base_volume, volume, 1.0)
    if mode == "unite" and volume <= base_volume + eps:
        return "Unite adds nothing: the extrusion lies inside the part"
    if mode == "subtract" and volume >= base_volume - eps:
        return "Subtract removes nothing: the extrusion does not reach the part (Reversed?)"
    return None


def undo_steps_added(before, after):
    """How many undo steps were added, from the undo names (newest first) before and after. FreeCAD's undo list
    has a size limit: a full one drops its oldest step for each new one, so its count stays the same. The
    smallest number of new steps that explains the two lists; None when none does (an undo, a cleared list)."""
    before, after = list(before), list(after)
    if len(after) < len(before):
        return None
    # at least one old step must still be there to line the lists up, unless there was none
    for k in range(len(after) - len(before), len(after) + (0 if before else 1)):
        if after[k:] == before[:len(after) - k]:
            return k
    return None


class CommandError(ValueError):
    pass

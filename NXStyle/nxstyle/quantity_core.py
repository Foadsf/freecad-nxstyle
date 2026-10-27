# SPDX-License-Identifier: LGPL-2.1-or-later
"""How many decimals a typed value needs to survive FreeCAD's quantity fields (no FreeCAD needed)."""

MAX_DECIMALS = 15


def decimals_needed(x):
    """Decimals that show x to 15 significant digits, trailing zeros dropped: 28.095 -> 3, 20.0 -> 0,
    1/64 in in mm (0.396875) -> 6. Fifteen digits leave out the last bits of a unit conversion
    (1.125 in = 28.574999999999996 mm -> 28.575) and keep every value a user can type."""
    mantissa, _, exp = f"{float(x):.14e}".partition("e")
    digits = mantissa.replace("-", "").replace(".", "").rstrip("0")
    return max(0, min(MAX_DECIMALS, len(digits) - 1 - int(exp)))

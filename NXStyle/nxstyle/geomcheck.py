# SPDX-License-Identifier: LGPL-2.1-or-later
"""Is a built solid the expected one? Volume alone is not: a 2 x 1 x 1 block and a 1 x 1 x 2 block have the
same volume. This compares the solid with a reference made directly with the Part API: the volume of their
symmetric difference (what one has and the other has not) must be negligible, and so must the bounding
box difference. Both are measured in mm³ and mm. Topology (face and edge counts) is reported, not
required: two correct builds may split faces differently."""


def compare(got, ref, rel_tol=1e-6, abs_tol=1e-6):
    """(ok, detail) for solid shapes got and ref."""
    if got is None or got.isNull() or not got.Solids:
        return False, "no solid"
    size = max(ref.Volume, 1e-12)
    extra = got.cut(ref).Volume              # material that should not be there
    missing = ref.cut(got).Volume            # material that should be there and is not
    a, b = got.BoundBox, ref.BoundBox
    box = max(abs(a.XMin - b.XMin), abs(a.YMin - b.YMin), abs(a.ZMin - b.ZMin),
              abs(a.XMax - b.XMax), abs(a.YMax - b.YMax), abs(a.ZMax - b.ZMax))
    tol = max(rel_tol * size, abs_tol)
    ok = extra <= tol and missing <= tol and box <= max(1e-4, rel_tol * b.DiagonalLength)
    detail = (f"same solid as the reference: {extra + missing:.3g} mm³ differ, box within {box:.2g} mm, "
              f"{len(got.Faces)} faces ({len(ref.Faces)} in the reference)" if ok else
              f"NOT the reference solid: {extra:.3g} mm³ extra, {missing:.3g} mm³ missing, box off by {box:.3g} mm")
    return ok, detail

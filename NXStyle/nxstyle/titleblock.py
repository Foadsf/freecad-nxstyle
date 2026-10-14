# SPDX-License-Identifier: LGPL-2.1-or-later
"""Title block and revision block of a released drawing (no FreeCAD needed).

What a released drawing's title block carries (Drake, Dimensioning and Tolerancing Handbook, ch. 4;
ISO 7200): the part (drawing) number, its revision, the title, the material, the scale, the sheet,
the general tolerancing note, who made and who approved it, and when. The revision block keeps the
history: one row per revision, with what changed, when and who approved it. NX fills the title block
from the part's attributes (DB_PART_NO, DB_PART_REV from Teamcenter; Populate Title Block); here they
come from the part's Strata release, or the document's attributes, so the sheet says what the PLM
record says.

The fields are those of FreeCAD's ISO 5457 templates (ISO 7200 names) and of its TD templates.
"""

from xml.sax.saxutils import escape

# template field -> what fills it
FIELDS = {
    # ISO 7200 (TechDraw's ISO 5457 templates)
    "drawing_number": "part_number", "revision_index": "revision", "date_of_issue": "released",
    "title": "title", "supplementary_title_1": "description", "creator": "released_by",
    "approval_person": "approved_by", "document_status": "state", "document_type": "document_type",
    "scale": "scale", "sheet_number": "sheet", "general_tolerances": "general", "part_material": "material",
    "legal_owner_1": "company", "language_code": "language",
    # TechDraw's TD templates
    "FC-Title": "title", "Subtitle": "description", "AuthorName": "released_by", "CreationDate": "released",
    "SupervisorName": "approved_by", "SheetNumber": "sheet", "Weight": "mass", "copyright": "company",
}
ISO_7200 = [f for f in FIELDS if f[0].islower() and f != "copyright"]
# NX part attributes (as Teamcenter fills them) a document may carry in its Meta map
ATTRIBUTES = {"DB_PART_NO": "part_number", "DB_PART_REV": "revision", "DB_PART_NAME": "title",
              "DB_PART_DESC": "description"}


def scale_text(s):
    if s <= 0:
        return ""
    if abs(s - 1) < 1e-9:
        return "1:1"
    if s < 1:
        return f"1:{1 / s:g}"
    return f"{s:g}:1"


def tolerancing_note(standard, general):
    """The title block's general tolerances entry: the general tolerance (ISO 2768-mK) when there is one.
    ISO 8015 needs no mention beside it, since ISO 8015:2011 applies whenever ISO GPS is invoked; without
    a general tolerance the entry names it, or ASME Y14.5 (which has no general tolerances)."""
    if standard.upper().startswith("ASME"):
        return general or "ASME Y14.5-2018"
    return general or "ISO 8015"


def values(info):
    """{template field: text} for every field the info (canonical keys) can fill."""
    out = {}
    for field, key in FIELDS.items():
        v = info.get(key)
        if v not in (None, ""):
            out[field] = str(v)
    return out


def fill(template_fields, info, keep=None):
    """The EditableTexts of a template: its fields filled from info; fields info does not cover keep
    their current text (keep)."""
    new = values(info)
    keep = keep or {}
    return {f: new.get(f, keep.get(f, "")) for f in template_fields}


def merge(*sources):
    """Earlier sources win: a release record before the document's attributes before its properties."""
    out = {}
    for s in sources:
        for k, v in (s or {}).items():
            if v not in (None, "") and k not in out:
                out[k] = v
    return out


def from_attributes(meta):
    return {key: meta[a] for a, key in ATTRIBUTES.items() if meta.get(a)}


ROW, TEXT = 6.0, 2.5
COLUMNS = (("REV", 12.0), ("DESCRIPTION", 74.0), ("DATE", 22.0), ("APPROVED", 26.0))


def revision_block(rows):
    """SVG of the revision block: a header and one row per revision, newest last (Drake 4.6.16).
    rows: [(revision, description, date, approved by)]. Returns (svg, width, height) in mm."""
    from .gdt import FONT, STROKE, _svg
    width = sum(w for _, w in COLUMNS)
    lines = [("REVISIONS", None)] + [(None, [c for c, _ in COLUMNS])] + [(None, [str(x) for x in r]) for r in rows]
    height = ROW * len(lines)
    body = [f'<rect x="{STROKE / 2:.3f}" y="{STROKE / 2:.3f}" width="{width - STROKE:.3f}" '
            f'height="{height - STROKE:.3f}" fill="white" stroke="black" stroke-width="{STROKE}"/>']
    for i, (title, cells) in enumerate(lines):
        y = i * ROW
        if i:
            body.append(f'<path d="M 0 {y:.3f} H {width:.3f}" stroke="black" stroke-width="{STROKE}"/>')
        base = y + ROW / 2 + TEXT / 2 - 0.2
        if title is not None:
            body.append(f'<text x="{width / 2:.3f}" y="{base:.3f}" font-family="{FONT}" font-size="{TEXT}" '
                        f'text-anchor="middle" font-weight="bold">{escape(title)}</text>')
            continue
        x = 0.0
        for j, ((_, w), text) in enumerate(zip(COLUMNS, cells)):
            if j:
                body.append(f'<path d="M {x:.3f} {y:.3f} V {y + ROW:.3f}" stroke="black" stroke-width="{STROKE}"/>')
            limit = int(w / (0.6 * TEXT))                 # characters that fit the cell
            t = text if len(text) <= limit else text[:max(limit - 1, 1)] + "…"
            anchor, tx = ("start", x + 1.2) if j == 1 else ("middle", x + w / 2)
            weight = ' font-weight="bold"' if i == 1 else ""
            body.append(f'<text x="{tx:.3f}" y="{base:.3f}" font-family="{FONT}" font-size="{TEXT}" '
                        f'text-anchor="{anchor}"{weight}>{escape(t)}</text>')
            x += w
    return _svg(width, height, "".join(body)), width, height

# SPDX-License-Identifier: LGPL-2.1-or-later
"""Drafting > Populate Title Block: the sheet's title block from the part's release record, and its
revision block from the release history (titleblock.py).

Sources, first wins: the part's newest Strata release (part number, revision, description, state,
who released and approved it, the date), the document's NX attributes (DB_PART_NO, DB_PART_REV,
DB_PART_NAME in its Meta), the document itself (label, author, company). The drawing adds what it
knows: the scale, the sheet, the part's material and mass, and the tolerancing note of its PMI. A
sheet whose template has no title block fields (FreeCAD's default sheet is blank) is given the ISO 5457
template of its size, whose title block is ISO 7200's.
"""

import datetime
import os

import FreeCAD as App
import FreeCADGui as Gui

from . import config, titleblock
from .qt import QtWidgets

SIZES = {(297, 210): "A4", (420, 297): "A3", (594, 420): "A2", (841, 594): "A1", (1189, 841): "A0"}
REVISION_BLOCK = "RevisionBlock"


def iso_template(page):
    """FreeCAD's ISO 5457 template (ISO 7200 title block) of the page's size and orientation, or None."""
    try:
        w, h = round(float(page.Template.Width)), round(float(page.Template.Height))
    except Exception:
        w, h = 420, 297
    size = SIZES.get((max(w, h), min(w, h)), "A3")
    orient = "Landscape" if w >= h else "Portrait"
    path = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO",
                        f"{size}_{orient}_ISO5457_advanced.svg")
    return path if os.path.isfile(path) else None


def template_fields(page):
    t = getattr(page, "Template", None)
    try:
        return list(t.EditableTexts.keys()) if t is not None else []
    except Exception:
        return []


def has_title_block(page):
    return any(f in titleblock.FIELDS for f in template_fields(page))


def releases(doc):
    from . import package_ui
    try:
        return package_ui.releases_of(doc)[1]
    except Exception:
        return []


def solids_on(page):
    """The part objects the page's views show."""
    out = []
    for v in page.Views:
        for o in getattr(v, "Source", []) or []:
            if o not in out and getattr(o, "Shape", None) is not None:
                out.append(o)
        for o in getattr(v, "XSource", []) or []:
            if o not in out:
                out.append(o)
    return out


def material_and_mass(objs):
    name, mass = "", 0.0
    for o in objs:
        chain = [o]
        try:
            chain += [p for p in o.InListRecursive if p.isDerivedFrom("PartDesign::Body")]
        except Exception:
            pass
        mat = next((getattr(c, "ShapeMaterial", None) for c in chain if getattr(c, "ShapeMaterial", None) is not None),
                   None)
        if mat is None or getattr(mat, "Name", "") in ("", "Default"):   # FreeCAD's placeholder, not a material
            continue
        name = name or mat.Name
        try:
            rho = mat.getPhysicalValue("Density")
            rho = float(getattr(rho, "Value", rho))          # kg/m³ or kg/mm³ by the unit FreeCAD gives
            vol = o.Shape.Volume                              # mm³
            mass += vol * (rho if rho < 1 else rho * 1e-9)
        except Exception:
            pass
    return name, (f"{mass:.3f} kg" if mass > 0 else "")


def info(page):
    """Canonical title block values for a page (see titleblock.FIELDS)."""
    from . import package_ui, pmi_ui
    doc = page.Document
    rels = releases(doc)
    rel = {}
    if rels:
        # the newest release identifies the sheet; its description says what changed (the revision block's),
        # so the title is the part's name: what the first release was described as
        m = package_ui.release_meta(rels[-1])
        rel = {k: m.get(k, "") for k in ("part_number", "revision", "state", "released", "released_by",
                                          "approved_by")}
        rel["title"] = package_ui.release_meta(rels[0]).get("description", "")
    try:
        meta = dict(doc.Meta)
    except Exception:
        meta = {}
    own = {"title": doc.Label, "released_by": getattr(doc, "CreatedBy", ""), "company": getattr(doc, "Company", ""),
           "released": datetime.date.today().isoformat(), "state": "Not released"}
    std, general = pmi_ui.settings(doc)
    pages = [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")]
    material, mass = material_and_mass(solids_on(page))
    drawing = {"scale": titleblock.scale_text(float(getattr(page, "Scale", 1.0) or 1.0)),
               "sheet": f"{pages.index(page) + 1}/{len(pages)}" if page in pages else "1/1",
               "general": titleblock.tolerancing_note(std, general), "material": material, "mass": mass,
               "document_type": "Detail drawing", "language": "en"}
    attrs = titleblock.from_attributes(meta)
    if attrs.get("title"):                       # a part name given as an attribute names the part
        rel.pop("title", None)
    return titleblock.merge(rel, attrs, drawing, own)


def revision_rows(doc):
    """[(revision, description, date, approved by)] of the part's releases, oldest first."""
    from . import package_ui
    out = []
    for r in releases(doc):
        m = package_ui.release_meta(r)
        out.append((m["revision"], m.get("description", ""), m.get("released", ""),
                    m.get("approved_by") or m.get("released_by", "")))
    return out


def place_revision_block(page, rows):
    """The revision block in the sheet's top right corner, inside the ISO 5457 frame; replaced when it
    is there already."""
    from . import gdt_ui
    doc = page.Document
    old = [v for v in page.Views if getattr(v, "NX_Kind", "") == "revision block"]
    for v in old:
        doc.removeObject(v.Name)
    if not rows:
        return None
    svg, w, h = titleblock.revision_block(rows)
    W, H = float(page.Template.Width), float(page.Template.Height)
    sym = gdt_ui.add_symbol(page, REVISION_BLOCK, svg, W - 10.0 - 2.0 - w / 2, H - 10.0 - 2.0 - h / 2)
    sym.Label = "Revision block"
    gdt_ui.tag(sym, kind="revision block")
    return sym


def apply(page, values, template=None, rows=None):
    """Fill the page's title block (switching to template first, when given) and place the revision block."""
    doc = page.Document
    keep = dict(page.Template.EditableTexts)
    if template:
        page.Template.Template = template
        doc.recompute()
        keep = {}                     # a new template's texts are its samples ("A. Nemesis"): not this part's
    page.Template.EditableTexts = {f: values.get(f, keep.get(f, "")) for f in template_fields(page)}
    from . import pmi_ui
    pmi_ui.tolerancing_note(page)    # the title block states the tolerancing now: Inherit PMI's note goes
    block = place_revision_block(page, rows) if rows is not None else None
    doc.recompute()
    last.update(page=page.Name, values=dict(page.Template.EditableTexts), block=block.Name if block else None)
    return block


last = {}


class TitleBlockPanel:
    def __init__(self, page):
        self.page = page
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Populate Title Block")
        lay = QtWidgets.QFormLayout(self.form)
        self.template = None
        if not has_title_block(page):
            self.template = iso_template(page)
            lay.addRow(QtWidgets.QLabel("This sheet has no title block: it gets "
                                        f"{os.path.basename(self.template) if self.template else 'none (not found)'}"))
        data = info(page)
        fields = titleblock.ISO_7200 if self.template else template_fields(page)
        known = [f for f in fields if f in titleblock.FIELDS]
        filled = titleblock.values(data)
        current = {} if self.template else dict(page.Template.EditableTexts)
        self.edits = {}
        for f in known:
            e = QtWidgets.QLineEdit(filled.get(f, current.get(f, "")))
            e.setObjectName(f)
            lay.addRow(f.replace("_", " ").replace("-", " ").capitalize(), e)
            self.edits[f] = e
        rels = revision_rows(page.Document)
        self.revisions = QtWidgets.QCheckBox(f"Revision block from the releases ({len(rels)})")
        self.revisions.setObjectName("revisionBlock")
        self.revisions.setChecked(bool(rels))
        self.revisions.setEnabled(bool(rels))
        lay.addRow(self.revisions)
        src = "Strata release" if releases(page.Document) else "document attributes and properties (not released)"
        note = QtWidgets.QLabel(f"From the {src}; the tolerancing note from the PMI. NX: Populate Title Block "
                                "(attributes DB_PART_NO, DB_PART_REV).")
        note.setWordWrap(True)
        lay.addRow(note)
        self.rows = rels

    def accept(self):
        doc = self.page.Document
        doc.openTransaction("Populate Title Block")
        apply(self.page, {f: e.text() for f, e in self.edits.items()}, self.template,
              self.rows if self.revisions.isChecked() else None)
        doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class PopulateTitleBlock:
    def GetResources(self):
        return {"MenuText": "Populate Title Block",
                "ToolTip": "Fill the sheet's title block from the part's release (part number, revision, approval) "
                           "and its PMI (tolerancing note), and add the revision block",
                "Pixmap": config.resource("icons", "title_block.svg")}

    @staticmethod
    def _page():
        sel = [o for o in Gui.Selection.getSelection() if o.isDerivedFrom("TechDraw::DrawPage")]
        if sel:
            return sel[0]
        from . import gdt_ui
        return gdt_ui.active_page()

    def IsActive(self):
        return App.ActiveDocument is not None and self._page() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(TitleBlockPanel(self._page()))


COMMANDS = {"NXStyle_PopulateTitleBlock": PopulateTitleBlock()}

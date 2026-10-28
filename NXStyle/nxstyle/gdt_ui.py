# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX Drafting's Feature Control Frame and Datum Feature Symbol dialogs for TechDraw.

Select a view edge (or a dimension) first, as in NX, and the symbol is placed
against it: a datum feature symbol touches the edge from outside the view, a
feature control frame goes just outside the edge or under the dimension's text.
With nothing selected the symbol goes to the middle of the sheet.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, gdt
from .qt import QtWidgets

GAP = 2.0     # mm between a frame and the edge or dimension it belongs to


# ------------------------------------------------------------------ placement
def selection_target():
    """(page, kind, data) for the first TechDraw selection: kind 'edge' with (view, edge) or
    'dimension' with the dimension; (page, None, None) if nothing usable is selected."""
    for s in Gui.Selection.getSelectionEx():
        o = s.Object
        page = owning_page(o)
        if o.isDerivedFrom("TechDraw::DrawViewDimension"):
            return page, "dimension", o
        if o.isDerivedFrom("TechDraw::DrawViewPart"):
            for sub in s.SubElementNames:
                if sub.startswith("Edge"):
                    try:
                        return page, "edge", (o, o.getEdgeByIndex(int(sub[4:])))
                    except Exception:
                        continue
            return page, None, None
    return active_page(), None, None


def owning_page(obj):
    for p in getattr(obj, "InList", []):
        if p.isDerivedFrom("TechDraw::DrawPage"):
            return p
        for q in getattr(p, "InList", []):          # a view inside a projection group
            if q.isDerivedFrom("TechDraw::DrawPage"):
                return q
    return active_page()


def active_page():
    doc = App.ActiveDocument
    if doc is None:
        return None
    pages = [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")]
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi else None
    title = sub.windowTitle() if sub else ""
    for p in pages:
        if p.Label and title.startswith(p.Label):
            return p
    return pages[-1] if pages else None


def view_origin(view):
    """(x, y, scale) of a view on the sheet: a projection group's view (FreeCAD 1.1's Base View makes one) is
    placed relative to its group, and takes the group's scale."""
    x, y = float(view.X), float(view.Y)
    if view.TypeId == "TechDraw::DrawProjGroupItem":
        g = next((o for o in view.InList if o.isDerivedFrom("TechDraw::DrawProjGroup")), None)
        if g is not None:
            x, y = x + float(g.X), y + float(g.Y)
    s = float(view.getScale()) if hasattr(view, "getScale") else float(view.Scale)
    return x, y, s


def edge_on_sheet(view, edge):
    """Edge midpoint, direction and outward normal on the sheet (mm, Y up)."""
    vx, vy, s = view_origin(view)
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
    x, y = vx + mid.x * s, vy + mid.y * s
    dx, dy = b.x - a.x, b.y - a.y
    horizontal = abs(dx) >= abs(dy)
    # outward = away from the view centre (edge geometry is relative to it)
    if horizontal:
        out = (0.0, 1.0 if mid.y >= 0 else -1.0)
    else:
        out = (1.0 if mid.x >= 0 else -1.0, 0.0)
    return (x, y), horizontal, out


def dimension_on_sheet(dim):
    view = dim.References2D[0][0] if dim.References2D else None
    if view is None:
        return float(dim.X), float(dim.Y)
    vx, vy, _ = view_origin(view)
    return vx + float(dim.X), vy + float(dim.Y)


def add_symbol(page, name, svg, x, y):
    doc = page.Document
    sym = doc.addObject("TechDraw::DrawViewSymbol", name)
    sym.Symbol = svg
    page.addView(sym)
    sym.X, sym.Y = x, y
    doc.recompute()
    return sym


def place_datum(letter, page, kind, data):
    """Create a datum feature symbol touching the selected edge from outside."""
    if kind == "edge":
        (x, y), horizontal, (ox, oy) = edge_on_sheet(*data)
        attach = ("bottom" if oy > 0 else "top") if horizontal else ("left" if ox > 0 else "right")
        svg, (w, h) = gdt.datum_feature_symbol(letter, attach)
        # the triangle's base sits on the edge, the rest of the symbol outside
        x += ox * w / 2
        y += oy * h / 2
    else:
        svg, (w, h) = gdt.datum_feature_symbol(letter)
        x, y = page_centre(page)
    sym = add_symbol(page, f"Datum{letter}", svg, x, y)
    tag(sym, kind="datum feature symbol", datum=letter)
    return sym


def place_frame(params, page, kind, data):
    """params: characteristic, tolerance, diameter, modifier, datums; a two-row frame also has lower
    (tolerance, modifier, datums) and composite."""
    params = dict(params)
    lower = params.pop("lower", None)
    composite = params.pop("composite", True)
    h = gdt.H
    if lower:
        rows = [(params["tolerance"], params["diameter"], params["modifier"], params["datums"]),
                (lower[0], params["diameter"], lower[1], lower[2])]
        svg, w, h = gdt.stacked_frame(params["characteristic"], rows, composite)
        text = gdt.stacked_callout(params["characteristic"], rows, composite)
    else:
        svg, w = gdt.feature_control_frame(params["characteristic"], params["tolerance"], params["diameter"],
                                           params["modifier"], params["datums"])
        text = gdt.callout(**params)
    if kind == "dimension":
        x, y = dimension_on_sheet(data)
        y -= h / 2 + GAP + 3.5                # under the dimension text
    elif kind == "edge":
        (x, y), horizontal, (ox, oy) = edge_on_sheet(*data)
        if horizontal:
            y += oy * (h / 2 + GAP + 12.0)        # clear of a datum symbol on the same edge
        else:
            x += ox * (w / 2 + GAP + 12.0)
    else:
        x, y = page_centre(page)
    sym = add_symbol(page, "FeatureControlFrame", svg, x, y)
    tag(sym, kind="feature control frame", callout=text)
    return sym


def page_centre(page):
    try:
        t = page.Template
        return float(t.Width) / 2, float(t.Height) / 2
    except Exception:
        return 148.5, 105.0


def tag(sym, **values):
    """Remember what the symbol says (shown in the property view, read by the replay)."""
    for k, v in values.items():
        prop = "NX_" + "".join(p.capitalize() for p in k.split())
        if prop not in sym.PropertiesList:
            sym.addProperty("App::PropertyString", prop, "NX", f"NX {k}")
        setattr(sym, prop, str(v))


def used_letters(page):
    return {getattr(o, "NX_Datum", "") for o in getattr(page, "Views", [])}


# ------------------------------------------------------------------ dialogs
class _Panel:
    title = ""

    def __init__(self):
        self.page, self.kind, self.data = selection_target()
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(self.title)
        self.layout = QtWidgets.QFormLayout(self.form)

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def where(self):
        return {"edge": "against the selected edge", "dimension": "under the selected dimension"}.get(
            self.kind, "in the middle of the sheet (select an edge or dimension first to place it)")


class DatumPanel(_Panel):
    title = "Datum Feature Symbol"

    def __init__(self):
        super().__init__()
        used = used_letters(self.page) if self.page else set()
        nxt = next((c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in used), "A")
        self.letter = QtWidgets.QLineEdit(nxt)
        self.letter.setObjectName("datumLetter")
        self.letter.setMaxLength(2)
        self.layout.addRow("Letter", self.letter)
        self.layout.addRow(QtWidgets.QLabel(f"Placed {self.where()}."))

    def accept(self):
        if self.page is None:
            App.Console.PrintError("Datum Feature Symbol: no drawing sheet\n")
            return False
        letter = self.letter.text().strip().upper() or "A"
        App.ActiveDocument.openTransaction("Datum Feature Symbol")
        place_datum(letter, self.page, self.kind, self.data)
        App.ActiveDocument.commitTransaction()
        Gui.Control.closeDialog()
        return True


class FramePanel(_Panel):
    title = "Feature Control Frame"

    def __init__(self):
        super().__init__()
        self.characteristic = QtWidgets.QComboBox()
        self.characteristic.setObjectName("characteristic")
        self.characteristic.addItems([c.title() for c in gdt.CHARACTERISTICS])
        self.diameter = QtWidgets.QCheckBox("Ø zone")
        self.diameter.setObjectName("zoneDiameter")
        self.tolerance = QtWidgets.QLineEdit("0.1")
        self.tolerance.setObjectName("tolerance")
        self.modifier = self._modifier("materialCondition")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.diameter)
        row.addWidget(self.tolerance)
        row.addWidget(self.modifier)
        self.layout.addRow("Characteristic", self.characteristic)
        self.layout.addRow("Tolerance", row)
        self.datums = []
        for i, name in enumerate(("Primary", "Secondary", "Tertiary"), start=1):
            letter = QtWidgets.QLineEdit()
            letter.setObjectName(f"datum{i}")
            letter.setMaxLength(2)
            mod = self._modifier(f"datum{i}Modifier")
            r = QtWidgets.QHBoxLayout()
            r.addWidget(letter)
            r.addWidget(mod)
            self.layout.addRow(f"{name} datum", r)
            self.datums.append((letter, mod))
        self.layout.addRow(QtWidgets.QLabel(f"Placed {self.where()}."))

    @staticmethod
    def _modifier(name):
        c = QtWidgets.QComboBox()
        c.setObjectName(name)
        c.addItems(["None", "MMC", "LMC"])
        return c

    def params(self):
        mod = {"None": ""}.get(self.modifier.currentText(), self.modifier.currentText())
        datums = []
        for letter, m in self.datums:
            if letter.text().strip():
                datums.append((letter.text().strip().upper(), {"None": ""}.get(m.currentText(), m.currentText())))
        return {"characteristic": gdt.CHARACTERISTICS[self.characteristic.currentIndex()],
                "tolerance": self.tolerance.text().strip(), "diameter": self.diameter.isChecked(),
                "modifier": mod, "datums": datums}

    def accept(self):
        if self.page is None:
            App.Console.PrintError("Feature Control Frame: no drawing sheet\n")
            return False
        App.ActiveDocument.openTransaction("Feature Control Frame")
        place_frame(self.params(), self.page, self.kind, self.data)
        App.ActiveDocument.commitTransaction()
        Gui.Control.closeDialog()
        return True


class FeatureControlFrame:
    def GetResources(self):
        return {"MenuText": "Feature Control Frame",
                "ToolTip": "NX Drafting: a GD&T feature control frame (characteristic, tolerance, material "
                           "condition, datums). Select an edge or dimension first to place it there.",
                "Pixmap": config.resource("icons", "feature_control_frame.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and active_page() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(FramePanel())


class DatumFeatureSymbol:
    def GetResources(self):
        return {"MenuText": "Datum Feature Symbol",
                "ToolTip": "NX Drafting: a datum feature symbol. Select the datum edge first; the symbol is "
                           "placed against it from outside the view.",
                "Pixmap": config.resource("icons", "datum_feature_symbol.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and active_page() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(DatumPanel())


def register():
    Gui.addCommand("NXStyle_FeatureControlFrame", FeatureControlFrame())
    Gui.addCommand("NXStyle_DatumFeatureSymbol", DatumFeatureSymbol())
    return ["NXStyle_FeatureControlFrame", "NXStyle_DatumFeatureSymbol"]

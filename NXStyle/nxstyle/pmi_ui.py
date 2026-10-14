# SPDX-License-Identifier: LGPL-2.1-or-later
"""PMI: NX's Product and Manufacturing Information, 3D annotations that belong to the model.

FreeCAD has no PMI. These are document objects (App::FeaturePython) in a PMI folder of the Part
Navigator, as in NX:

- PMI Dimension: a distance between two faces, or the diameter or radius of a cylinder, measured
  from the model (it follows design changes), with deviations, Basic, and a count (4X);
- PMI Feature Control Frame: characteristic, Ø zone, tolerance, material condition, datums;
- PMI Datum Feature Symbol: a letter on a face.

Each is attached to faces by a link that FreeCAD's topological naming keeps on the same face.
They are drawn in the graphics window at constant screen size with a leader to the face; feature
control frames and datum symbols use the same drawing as NXStyle's Drafting dialogs (gdt.py).
The semantic content (pmi.py) feeds the inspection plan, the functional gauge sizes, the ASME
checks, the tolerance stack-up (Add from PMI), Drafting's Inherit PMI and the technical data
package.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, gdt, iso, pmi, refs
from .qt import QtCore, QtGui, QtWidgets

TYPES = ["Dimension", "Feature Control Frame", "Datum Feature"]
DIM_TYPES = ["Distance", "Diameter", "Radius"]
MODIFIERS = ["None", "MMC", "LMC"]
PX_PER_MM = 4.0           # label images: 7 mm frame height = 28 px


def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


# ------------------------------------------------------------------ the document object
class PMIFeature:
    def __init__(self, obj, kind):
        obj.Proxy = self
        self.setup(obj, kind)

    def setup(self, obj, kind=None):
        g = "PMI"
        _prop(obj, "App::PropertyEnumeration", "PMIType", g, "What this PMI is")
        if kind is not None:
            obj.PMIType = TYPES
            obj.PMIType = kind
        obj.setEditorMode("PMIType", 1)
        _prop(obj, "App::PropertyLinkSubList", "References", g, "The faces (or edges) it is attached to")
        _prop(obj, "App::PropertyInteger", "Number", g, "Characteristic number (balloon) in the inspection plan", 0)
        _prop(obj, "App::PropertyVector", "LabelOffset", g, "Where the label sits, from the attachment point (mm)")
        _prop(obj, "App::PropertyVector", "Anchor", g, "Attachment point on the model", mode=1)
        _prop(obj, "App::PropertyVector", "Anchor2", g, "Second attachment point (distance)", mode=2)
        _prop(obj, "App::PropertyString", "FeatureType", g, "plane, hole, pin, width or other", mode=1)
        _prop(obj, "App::PropertyString", "Callout", g, "The annotation as text", mode=1)
        k = obj.PMIType
        if k == "Dimension":
            d = "Dimension"
            _prop(obj, "App::PropertyEnumeration", "DimensionType", d, "Distance, Diameter or Radius")
            if kind is not None:
                obj.DimensionType = DIM_TYPES
            _prop(obj, "App::PropertyFloat", "Nominal", d, "Measured from the model (mm)", mode=1)
            _prop(obj, "App::PropertyFloat", "UpperDeviation", d, "Plus tolerance (mm)", 0.0)
            _prop(obj, "App::PropertyFloat", "LowerDeviation", d, "Minus tolerance, as a positive number (mm)", 0.0)
            _prop(obj, "App::PropertyString", "Fit", d, "ISO 286 tolerance class, e.g. H7 (hole) or g6 (shaft); "
                  "it gives the deviations", "")
            _prop(obj, "App::PropertyBool", "Envelope", d, "ISO 14405 envelope (E): perfect form at MMC", False)
            _prop(obj, "App::PropertyBool", "Basic", d, "Theoretically exact (boxed), no tolerance", False)
            _prop(obj, "App::PropertyInteger", "Quantity", d, "Number of like features (4X)", 1)
        elif k == "Feature Control Frame":
            f = "Feature Control Frame"
            _prop(obj, "App::PropertyEnumeration", "Characteristic", f, "Geometric characteristic")
            if kind is not None:
                obj.Characteristic = [c.title() for c in gdt.CHARACTERISTICS]
            _prop(obj, "App::PropertyFloat", "Tolerance", f, "Tolerance zone (mm)", 0.1)
            _prop(obj, "App::PropertyBool", "ZoneDiameter", f, "Ø: a cylindrical zone", False)
            _prop(obj, "App::PropertyEnumeration", "MaterialCondition", f, "Modifier on the tolerance")
            if kind is not None:
                obj.MaterialCondition = MODIFIERS
            _prop(obj, "App::PropertyStringList", "DatumReferences", f,
                  "Primary, secondary, tertiary datum, e.g. A, D(M), B")
        elif k == "Datum Feature":
            _prop(obj, "App::PropertyString", "Letter", "Datum Feature", "Datum letter", "A")

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        picks = [(o, s) for o, subs in obj.References for s in (subs or [""])]
        if not picks:
            return
        try:
            shapes = [refs.resolve(o, s) for o, s in picks]
        except Exception as e:
            obj.Callout = f"error: {e}"
            return
        obj.Anchor = refs.anchor(shapes[0])
        obj.FeatureType = classify(shapes)
        if obj.PMIType == "Dimension":
            measure_dimension(obj, shapes)
        try:
            obj.Callout = pmi.text(semantic(obj))
        except ValueError as e:                  # e.g. a fit class ISO 286 does not cover
            obj.Callout = f"error: {e}"


def classify(shapes):
    if len(shapes) == 1:
        return refs.feature_type(shapes[0])
    a, b = shapes[0], shapes[1]
    if refs.surface_kind(a) == "plane" and refs.surface_kind(b) == "plane":
        na, nb = refs.plane_normal(a), refs.plane_normal(b)
        if na.dot(nb) < -1 + 1e-9:                    # opposed: a slot or a tab
            towards = na.dot(refs.anchor(b) - refs.anchor(a)) > 0
            return "width" if not towards else "slot"
    return "other"


def measure_dimension(obj, shapes):
    kind = obj.DimensionType
    if kind in ("Diameter", "Radius"):
        k = refs.surface_kind(shapes[0])
        if k not in ("cylinder", "circle"):
            obj.Callout = "error: a diameter needs a cylindrical face or a circular edge"
            return
        r = shapes[0].Surface.Radius if k == "cylinder" else shapes[0].Curve.Radius
        obj.Nominal = 2 * r if kind == "Diameter" else r
        obj.Anchor2 = obj.Anchor
        return
    if len(shapes) < 2:
        obj.Callout = "error: a distance needs two faces"
        return
    a, b = shapes[0], shapes[1]
    axis = refs.default_axis(a, b)
    d = refs.signed_distance(a, b, axis)
    obj.Nominal = abs(d)
    obj.Anchor2 = obj.Anchor + axis * d


def feature_key(obj):
    picks = [(o, s) for o, subs in obj.References for s in (subs or [""])]
    return " | ".join(refs.describe(o, s) for o, s in picks)


def semantic(obj):
    """The PMI as a pmi.py annotation dict."""
    ft = obj.FeatureType or "other"
    a = {"id": obj.Name, "label": obj.Label, "feature": feature_key(obj),
         "feature_type": "width" if ft == "slot" else ft, "number": obj.Number}
    if ft == "slot":
        a["internal"] = True
    elif ft == "width":
        a["internal"] = False
    k = obj.PMIType
    if k == "Dimension":
        a.update(kind="dimension", dim_type=obj.DimensionType.lower(), nominal=float(obj.Nominal),
                 plus=0.0 if obj.Basic else float(obj.UpperDeviation),
                 minus=0.0 if obj.Basic else float(obj.LowerDeviation), basic=bool(obj.Basic),
                 count=max(1, int(obj.Quantity)), fit=(getattr(obj, "Fit", "") or "").strip(),
                 envelope=bool(getattr(obj, "Envelope", False)))
    elif k == "Feature Control Frame":
        mod = {"None": ""}.get(obj.MaterialCondition, obj.MaterialCondition)
        a.update(kind="fcf", characteristic=obj.Characteristic.lower(), tolerance=float(obj.Tolerance),
                 diameter=bool(obj.ZoneDiameter), modifier=mod, datums=[parse_datum(d) for d in obj.DatumReferences
                                                                       if d.strip()])
    else:
        a.update(kind="datum", letter=(obj.Letter or "").strip().upper())
    return a


def parse_datum(text):
    t = text.strip().upper().replace(" ", "")
    for tag, mod in (("(M)", "MMC"), ("(L)", "LMC"), ("MMC", "MMC"), ("LMC", "LMC"), ("MMB", "MMC"), ("LMB", "LMC")):
        if t.endswith(tag):
            return [t[: -len(tag)], mod]
    return [t, ""]


def folder(doc):
    """The Part Navigator's PMI folder; it also holds the part's tolerancing standard and general
    tolerance note (what the title block of a drawing says)."""
    g = doc.getObject("PMI")
    if g is None or not g.isDerivedFrom("App::DocumentObjectGroup"):
        g = doc.addObject("App::DocumentObjectGroup", "PMI")
        g.Label = "PMI"
    if "Standard" not in g.PropertiesList:
        g.addProperty("App::PropertyEnumeration", "Standard", "Tolerancing",
                      "ISO GPS (ISO 8015 independency, ISO 2768) or ASME Y14.5 (Rule #1)")
        g.Standard = ["ISO GPS", "ASME Y14.5"]
        g.Standard = "ISO GPS"
    if "GeneralTolerance" not in g.PropertiesList:
        g.addProperty("App::PropertyString", "GeneralTolerance", "Tolerancing",
                      "General tolerances for dimensions without their own, e.g. ISO 2768-mK (add -E for the "
                      "envelope on every feature of size)")
    return g


def settings(doc):
    """(standard 'ISO' or 'ASME', general tolerance note or None) of a part."""
    g = doc.getObject("PMI")
    if g is None or "Standard" not in g.PropertiesList:
        return "ISO", None
    return ("ASME" if str(g.Standard).startswith("ASME") else "ISO"), (g.GeneralTolerance.strip() or None)


def all_pmi(doc):
    return [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), PMIFeature)]


def create(kind, picks, doc=None, **values):
    doc = doc or App.ActiveDocument
    name = {"Dimension": "PMI_Dimension", "Feature Control Frame": "PMI_FCF", "Datum Feature": "PMI_Datum"}[kind]
    obj = doc.addObject("App::FeaturePython", name)
    PMIFeature(obj, kind)
    obj.References = list(picks)
    for k, v in values.items():
        setattr(obj, k, v)
    folder(doc).addObject(obj)
    if App.GuiUp:
        PMIView(obj.ViewObject)
    doc.recompute()
    if obj.LabelOffset.Length < 1e-9:
        obj.LabelOffset = default_offset(obj)
    obj.Label = default_label(obj)
    return obj


def default_label(obj):
    k = obj.PMIType
    if k == "Datum Feature":
        return f"Datum {obj.Letter}"
    if k == "Feature Control Frame":
        return obj.Characteristic
    return f"{obj.DimensionType} {obj.Nominal:.3f}"


def model_size(obj):
    try:
        bb = None
        for o, _ in obj.References:
            b = o.Shape.BoundBox
            bb = b if bb is None else bb.united(b)
        return max(bb.DiagonalLength, 10.0) if bb else 50.0
    except Exception:
        return 50.0


def model_box(obj):
    bb = None
    for o, _ in obj.References:
        try:
            b = o.Shape.BoundBox
        except Exception:
            continue
        bb = b if bb is None else bb.united(b)
    return bb


def label_position(obj, row):
    """Where the row-th PMI label of the part sits: one column beside the part (towards -X), top down in
    creation order, so labels never cover each other or the part; leaders run to the faces."""
    size = model_size(obj)
    bb = model_box(obj)
    if bb is None:
        return App.Vector(-size, 0, -0.14 * size * row)
    return App.Vector(bb.XMin - 0.35 * size, bb.Center.y, bb.ZMax + 0.1 * size - 0.14 * size * row)


def default_offset(obj):
    """The label's place, as an offset from the attachment point (see label_position)."""
    row = len([p for p in all_pmi(obj.Document) if p is not obj])
    return label_position(obj, row) - App.Vector(obj.Anchor)


# ------------------------------------------------------------------ the labels
def label_svg(obj):
    """(svg, width mm, height mm) of the label drawn in the graphics window."""
    a = semantic(obj)
    if a["kind"] == "fcf":
        svg, w = gdt.feature_control_frame(a["characteristic"], f"{a['tolerance']:g}", a["diameter"], a["modifier"],
                                           [tuple(d) for d in a["datums"]])
        return svg, w, gdt.H
    if a["kind"] == "datum":
        svg, (w, h) = gdt.datum_feature_symbol(a["letter"] or "?", "bottom")
        return svg, w, h
    text = pmi.dimension_text(a)
    if a.get("basic"):
        text = text.replace("[", "").replace("]", "")
    w = gdt.text_width(text) + 3.0
    h = gdt.H
    frame = (f'<rect x="0.2" y="0.2" width="{w - 0.4:.3f}" height="{h - 0.4:.3f}" fill="white" stroke="black" '
             f'stroke-width="0.35"/>' if a.get("basic") else
             f'<rect x="0" y="0" width="{w:.3f}" height="{h:.3f}" fill="white" fill-opacity="0.85" stroke="none"/>')
    from xml.sax.saxutils import escape
    body = frame + (f'<text x="{w / 2:.3f}" y="{h / 2 + gdt.TEXT / 2 - 0.3:.3f}" font-family="{gdt.FONT}" '
                    f'font-size="{gdt.TEXT}" text-anchor="middle">{escape(text)}</text>')
    return gdt._svg(w, h, body), w, h


def _qtsvg():
    for mod in ("PySide6", "PySide2", "PySide"):
        try:
            return __import__(mod, fromlist=["QtSvg"]).QtSvg
        except ImportError:
            continue
    return None


def label_font():
    f = QtGui.QFont("DejaVu Sans")
    f.setPixelSize(int(gdt.TEXT * PX_PER_MM))
    return f


def render_label(obj, number=0):
    """The label as a QImage (RGBA), with the characteristic number in a balloon when given. Frames and
    datum symbols come from gdt.py's SVG; a dimension's text is measured with the font it is drawn in."""
    a = semantic(obj)
    QtSvg = _qtsvg()
    text = None
    if a["kind"] == "dimension":
        text = pmi.dimension_text(a).replace("[", "").replace("]", "")
        fm = QtGui.QFontMetricsF(label_font())
        W, H = int(fm.horizontalAdvance(text) + 14), int(gdt.H * PX_PER_MM) + 2
    else:
        svg, w, h = label_svg(obj)
        W, H = int(w * PX_PER_MM) + 2, int(h * PX_PER_MM) + 2
    extra = int(H * 1.05) if number else 0
    img = QtGui.QImage(W + extra, H, QtGui.QImage.Format_RGBA8888)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    if text is not None:
        box = QtCore.QRectF(extra + 1, 1, W - 3, H - 3)
        p.setBrush(QtGui.QColor(255, 255, 255, 230))
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1.4) if a.get("basic") else QtCore.Qt.NoPen)
        p.drawRect(box)
        p.setPen(QtGui.QColor("#000000"))
        p.setFont(label_font())
        p.drawText(box, QtCore.Qt.AlignCenter, text)
    elif QtSvg is not None:
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
        r.render(p, QtCore.QRectF(extra, 0, W - 2, H - 2))
    if number:
        p.setPen(QtGui.QPen(QtGui.QColor("#0b6e79"), 2))
        p.setBrush(QtGui.QColor("#ffffff"))
        d = H - 4
        p.drawEllipse(1, 1, d, d)
        f = p.font()
        f.setPixelSize(int(d * 0.55))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor("#0b6e79"))
        p.drawText(QtCore.QRectF(1, 1, d, d), QtCore.Qt.AlignCenter, str(number))
    p.end()
    return img


class PMIView:
    """Leader from the face to the label; the label is an image at constant screen size."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.vobj = vobj
        self.root = coin.SoSeparator()
        self.geo = coin.SoSeparator()
        self.root.addChild(self.geo)
        vobj.addDisplayMode(self.root, "PMI")
        self.update(vobj.Object)

    def getDisplayModes(self, vobj):
        return ["PMI"]

    def getDefaultDisplayMode(self):
        return "PMI"

    def setDisplayMode(self, mode):
        return mode

    def getIcon(self):
        obj = getattr(getattr(self, "vobj", None), "Object", None)
        k = getattr(obj, "PMIType", "")
        name = {"Feature Control Frame": "feature_control_frame", "Datum Feature": "datum_feature_symbol"}.get(
            k, "pmi_dimension")
        return config.resource("icons", f"{name}.svg")

    def updateData(self, obj, prop):
        if prop in ("Callout", "Anchor", "Anchor2", "LabelOffset", "Number"):
            self.update(obj)

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def update(self, obj):
        from pivy import coin
        try:
            self.geo.removeAllChildren()
        except Exception:
            return
        if "Anchor" not in obj.PropertiesList:
            return
        a, off = App.Vector(obj.Anchor), App.Vector(obj.LabelOffset)
        if off.Length < 1e-9:
            return
        at = a + off
        col = coin.SoBaseColor()
        col.rgb = (0.05, 0.05, 0.05)
        style = coin.SoDrawStyle()
        style.lineWidth = 1.5
        self.geo += [col, style]
        pts = [a, at]
        if obj.PMIType == "Dimension" and obj.DimensionType == "Distance":
            b = App.Vector(obj.Anchor2)
            d = b - a
            if d.Length > 1e-9:
                # the dimension line stays beside the measured faces, moved a little towards the label column;
                # the leader runs from its middle to the label
                u = App.Vector(d).normalize()
                toward = at - (a + b) * 0.5
                perp = toward - u * toward.dot(u)
                reach = min(model_size(obj) * 0.12, perp.Length)
                perp = App.Vector(perp).normalize() * reach if perp.Length > 1e-9 else App.Vector()
                pa, pb = a + perp, b + perp
                pts = [a, pa, b, pb, pa, pb, (pa + pb) * 0.5, at]
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(pts) // 2, [2] * (len(pts) // 2))
        self.geo += [coords, ls]
        dot = coin.SoSeparator()
        tr = coin.SoTranslation()
        tr.translation = (a.x, a.y, a.z)
        mk = coin.SoMarkerSet()
        mk.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_5_5
        mc = coin.SoCoordinate3()
        mc.point.setValue(0, 0, 0)
        dot += [tr, mc, mk]
        self.geo.addChild(dot)
        lab = coin.SoSeparator()
        lt = coin.SoTranslation()
        lt.translation = (at.x, at.y, at.z)
        lab.addChild(lt)
        try:
            img = render_label(obj, obj.Number)
            node = coin.SoImage()
            node.vertAlignment = coin.SoImage.HALF
            node.horAlignment = coin.SoImage.RIGHT       # the label ends where its leader starts
            flipped = img.mirrored(False, True)
            data = bytes(flipped.constBits())[: flipped.width() * flipped.height() * 4]
            node.image.setValue(coin.SbVec2s(flipped.width(), flipped.height()), 4, data)
            lab.addChild(node)
        except Exception as e:                    # no image support: the callout as text
            App.Console.PrintLog(f"NXStyle PMI: label image failed ({e}); text instead\n")
            font = coin.SoFont()
            font.size = 13
            txt = coin.SoText2()
            txt.string = obj.Callout
            lab += [font, txt]
        self.geo.addChild(lab)


# ------------------------------------------------------------------ dialogs
class _Panel:
    title = ""
    kind = ""

    def __init__(self):
        self.picks = refs.selection_refs()
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(self.title)
        self.layout = QtWidgets.QFormLayout(self.form)
        self.where = QtWidgets.QLabel()
        self.where.setWordWrap(True)
        self.where.setObjectName("pmiAttachment")
        self.layout.addRow(self.where)
        self.describe()

    def describe(self):
        if self.picks:
            self.where.setText("Attached to " + ", ".join(refs.describe(o, s) for o, s in self.picks))
        else:
            self.where.setText("Select the face(s) first, then start the command.")

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def accept(self):
        if not self.picks:
            QtWidgets.QMessageBox.information(self.form, self.title, "Select the face(s) the PMI belongs to first.")
            return False
        doc = App.ActiveDocument
        doc.openTransaction(self.title)
        obj = create(self.kind, self.picks, doc, **self.values())
        doc.recompute()
        doc.commitTransaction()
        Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        if obj.Callout.startswith("error"):
            App.Console.PrintError(f"{self.title}: {obj.Callout}\n")
        return True


class DimensionPanel(_Panel):
    title = "PMI Rapid Dimension"
    kind = "Dimension"

    def __init__(self):
        super().__init__()
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName("dimensionType")
        self.type.addItems(DIM_TYPES)
        shapes = []
        try:
            shapes = [refs.resolve(o, s) for o, s in self.picks]
        except Exception:
            pass
        if len(shapes) == 1 and refs.surface_kind(shapes[0]) in ("cylinder", "circle"):
            self.type.setCurrentIndex(1)
        self.nominal = QtWidgets.QLabel(self.measure(shapes))
        self.nominal.setObjectName("nominal")
        self.fit = QtWidgets.QLineEdit()
        self.fit.setObjectName("fit")
        self.fit.setPlaceholderText("e.g. H7 or g6 (ISO 286)")
        self.limits = QtWidgets.QLabel()
        self.limits.setObjectName("fitLimits")
        self.upper = self._spin("upperDeviation")
        self.lower = self._spin("lowerDeviation")
        self.envelope = QtWidgets.QCheckBox("Envelope Ⓔ (ISO 14405)")
        self.envelope.setObjectName("envelope")
        self.basic = QtWidgets.QCheckBox("Theoretically exact (basic)")
        self.basic.setObjectName("basic")
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("quantity")
        self.count.setRange(1, 999)
        self.count.setPrefix("× ")
        std, general = settings(App.ActiveDocument)
        self.layout.addRow("Method", self.type)
        self.layout.addRow("Nominal", self.nominal)
        self.layout.addRow("Tolerance class", self.fit)
        self.layout.addRow("", self.limits)
        self.layout.addRow("Upper (+)", self.upper)
        self.layout.addRow("Lower (−)", self.lower)
        self.layout.addRow("", self.envelope)
        self.layout.addRow("", self.basic)
        self.layout.addRow("Quantity", self.count)
        note = QtWidgets.QLabel(f"Standard: {'ISO GPS' if std == 'ISO' else 'ASME Y14.5'}; without a tolerance the "
                                f"dimension takes {general or 'no general tolerance (set one: PMI › Tolerancing)'}")
        note.setWordWrap(True)
        self.layout.addRow(note)
        self.shapes = shapes
        self.type.currentIndexChanged.connect(lambda *_: self.nominal.setText(self.measure(shapes)))
        self.fit.textChanged.connect(self.show_fit)

    def show_fit(self, *_):
        t = self.fit.text().strip()
        if not t:
            self.limits.setText("")
            return
        try:
            n = float(self.nominal.text().split()[0])
            up, lo = iso.deviations(t, n)
            self.limits.setText(f"{t}: {up:+.3f} / {lo:+.3f} mm  ({n + lo:.3f} to {n + up:.3f})")
        except (ValueError, IndexError) as e:
            self.limits.setText(str(e))

    def measure(self, shapes):
        try:
            if self.type.currentText() == "Distance" and len(shapes) == 2:
                return f"{abs(refs.signed_distance(shapes[0], shapes[1], refs.default_axis(*shapes))):.4f} mm"
            if len(shapes) == 1 and refs.surface_kind(shapes[0]) in ("cylinder", "circle"):
                r = shapes[0].Surface.Radius if shapes[0].ShapeType == "Face" else shapes[0].Curve.Radius
                return f"{(2 * r if self.type.currentText() == 'Diameter' else r):.4f} mm"
        except Exception as e:
            return f"cannot measure: {e}"
        return "select one cylinder (diameter) or two faces (distance)"

    @staticmethod
    def _spin(name):
        s = QtWidgets.QDoubleSpinBox()
        s.setObjectName(name)
        s.setRange(0.0, 1000.0)
        s.setDecimals(4)
        s.setSingleStep(0.01)
        s.setSuffix(" mm")
        return s

    def values(self):
        return {"DimensionType": self.type.currentText(), "UpperDeviation": self.upper.value(),
                "LowerDeviation": self.lower.value(), "Fit": self.fit.text().strip(),
                "Envelope": self.envelope.isChecked(), "Basic": self.basic.isChecked(), "Quantity": self.count.value()}


class FramePanel(_Panel):
    """The same fields (and object names) as Drafting's Feature Control Frame dialog."""
    title = "PMI Feature Control Frame"
    kind = "Feature Control Frame"

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

    @staticmethod
    def _modifier(name):
        c = QtWidgets.QComboBox()
        c.setObjectName(name)
        c.addItems(MODIFIERS)
        return c

    def values(self):
        try:
            tol = float(self.tolerance.text().replace(",", "."))
        except ValueError:
            tol = 0.0
        ds = []
        for letter, m in self.datums:
            t = letter.text().strip().upper()
            if t:
                ds.append(t + {"MMC": "(M)", "LMC": "(L)"}.get(m.currentText(), ""))
        return {"Characteristic": self.characteristic.currentText(), "Tolerance": tol,
                "ZoneDiameter": self.diameter.isChecked(), "MaterialCondition": self.modifier.currentText(),
                "DatumReferences": ds}


class DatumPanel(_Panel):
    title = "PMI Datum Feature Symbol"
    kind = "Datum Feature"

    def __init__(self):
        super().__init__()
        used = {getattr(o, "Letter", "") for o in all_pmi(App.ActiveDocument)} if App.ActiveDocument else set()
        nxt = next((c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in used), "A")
        self.letter = QtWidgets.QLineEdit(nxt)
        self.letter.setObjectName("datumLetter")
        self.letter.setMaxLength(2)
        self.layout.addRow("Letter", self.letter)

    def values(self):
        return {"Letter": self.letter.text().strip().upper() or "A"}


# ------------------------------------------------------------------ reports
def annotations(doc):
    """pmi.py dicts of every PMI in the document, numbered in creation order (numbers written back)."""
    objs = all_pmi(doc)
    anns = [semantic(o) for o in objs]
    pmi.number(anns, general=settings(doc)[1])
    for o, a in zip(objs, anns):
        if o.Number != a["number"]:
            o.Number = a["number"]
    return anns


def plan_text(doc):
    anns = annotations(doc)
    doc.recompute()
    std, general = settings(doc)
    return pmi.report(anns, title=f"PMI of {doc.Label}: inspection plan, functional gauge, checks", standard=std,
                      general=general)


def stack_values(o, part="tolerance"):
    """(nominal, plus, minus) a stack-up row takes from a PMI object (Fischer's conversions): a
    dimension's deviations, from its ISO 286 class or the part's ISO 2768 general tolerance if it
    has none of its own."""
    a = semantic(o)
    general = settings(o.Document)[1]
    if a["kind"] == "dimension":
        try:
            p, m, _ = pmi.deviations(a, general)
        except ValueError:
            p = m = 0.0
        return a["nominal"], p, m
    if a["kind"] == "fcf":
        if part == "bonus":
            size = next((s for s in (semantic(p) for p in all_pmi(o.Document)) if s["kind"] == "dimension"
                         and not s.get("basic") and s["feature"] == a["feature"]), None)
            if size is None or not a.get("modifier"):
                return 0.0, 0.0, 0.0
            lo, hi = pmi.size_limits(size, general)
            return 0.0, (hi - lo) / 2, (hi - lo) / 2
        return 0.0, a["tolerance"] / 2, a["tolerance"] / 2
    return None


def stack_rows(o, axis=None):
    """Stack-up rows (and picks for measured ones) for a selected PMI object."""
    if not isinstance(getattr(o, "Proxy", None), PMIFeature):
        return []
    a = semantic(o)
    picks = [(p, s) for p, subs in o.References for s in (subs or [""])]
    if a["kind"] == "dimension" and a["dim_type"] == "distance" and len(picks) == 2:
        return [({"name": f"{o.Label}", "part": picks[0][0].Label, "measured": True, "pmi": o.Name,
                  "kind": "dimension", "source": f"PMI {pmi.text(a)}"}, picks)]
    if a["kind"] == "dimension":
        return [({"name": o.Label, "part": picks[0][0].Label if picks else "", "pmi": o.Name, "direction": 1,
                  "kind": "dimension", "source": f"PMI {pmi.text(a)}"}, [])]
    if a["kind"] == "fcf":
        kind = {"position": "position"}.get(a["characteristic"],
                                            "profile" if "profile" in a["characteristic"] else
                                            "orientation" if a["characteristic"] in pmi.ORIENTATION else
                                            "runout" if a["characteristic"] in pmi.RUNOUT else "other")
        rows = [({"name": f"{a['characteristic'].title()} {o.Label}", "part": picks[0][0].Label if picks else "",
                  "pmi": o.Name, "nominal": 0.0, "direction": 1, "kind": kind,
                  "source": f"PMI {pmi.text(a)}: zone / 2"}, [])]
        if a.get("modifier"):
            rows.append(({"name": f"Bonus {o.Label}", "part": picks[0][0].Label if picks else "", "pmi": o.Name,
                          "pmi_part": "bonus", "nominal": 0.0, "direction": 1, "kind": "bonus",
                          "source": "PMI size tolerance / 2"}, []))
        return rows
    return []


# ------------------------------------------------------------------ Drafting: Inherit PMI
def project(view, p):
    """A model point on the sheet (mm, relative to the page), through the view's projection: in the
    view's own (unscaled, centred) coordinates like its edges, then scaled onto the sheet."""
    # (TechDraw's projectPoint gives the projection without the view's centring: measured, FreeCAD 1.1.4,
    # the top of a part 0..38 high projects to y 38 in a front view whose edges run from -19 to 19)
    s = float(view.Scale)
    q = view_xy(view, p)
    return float(view.X) + q.x * s, float(view.Y) + q.y * s


def view_frame(view):
    """The view's paper axes in the model: x along XDirection, y = Direction x XDirection."""
    d = App.Vector(view.Direction).normalize()
    x = App.Vector(view.XDirection).normalize()
    return x, d.cross(x), d


_centres = {}


def view_centre(view):
    """Where TechDraw centres a view: the middle of the source's exact bounding box in the view's own
    axes. (A plain BoundBox is padded around curved faces: the axis of a Ø25 body came out 0.019 mm off.)"""
    import Part
    key = (view.Name, tuple(view.Direction), tuple(view.XDirection), tuple(id(s) for s in view.Source),
           tuple(float(s.Shape.Volume) if hasattr(s, "Shape") else 0.0 for s in view.Source))
    if key in _centres:
        return _centres[key]
    x, y, d = view_frame(view)
    m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, d.x, d.y, d.z, 0, 0, 0, 0, 1)
    shape = Part.makeCompound([s.Shape for s in view.Source if hasattr(s, "Shape")]).copy()
    shape.transformShape(m)
    try:
        bb = shape.optimalBoundingBox(False, False)
    except Exception:
        bb = shape.BoundBox
    _centres[key] = (bb.Center.x, bb.Center.y)
    return _centres[key]


def view_xy(view, p):
    """A model point in the view's own coordinates: centred and unscaled, like its edges."""
    x, y, _ = view_frame(view)
    cx, cy = view_centre(view)
    return App.Vector(p.dot(x) - cx, p.dot(y) - cy, 0)


def _line_dist(p, a, b):
    """Distance of 2D point p from the infinite line through a and b."""
    d = b - a
    if d.Length < 1e-12:
        return (p - a).Length
    d.normalize()
    w = p - a
    return (w - d * w.dot(d)).Length


def edge_for_face(view, shape):
    """(index, edge) of the view edge that shows a face edge-on: a plane square to the paper as a line on
    its trace, a cylinder seen from the side as a silhouette line a radius from its axis. None when the
    view does not show the face that way."""
    d = App.Vector(view.Direction).normalize()
    k = refs.surface_kind(shape)
    lines = [(i, e) for i, e in _view_edges(view) if not hasattr(e.Curve, "Radius") and len(e.Vertexes) >= 2]
    if k == "plane":
        n = refs.plane_normal(shape)
        if abs(n.dot(d)) > 0.05:
            return None
        p0 = refs.anchor(shape)
        t = n.cross(d).normalize()
        a, b = view_xy(view, p0), view_xy(view, p0 + t * 10.0)
        cands = [(i, e) for i, e in lines
                 if _line_dist(e.Vertexes[0].Point, a, b) < 1e-3 and _line_dist(e.Vertexes[-1].Point, a, b) < 1e-3]
        P = view_xy(view, p0)
        return min(cands, key=lambda ie: ((ie[1].Vertexes[0].Point + ie[1].Vertexes[-1].Point) * 0.5 - P).Length,
                   default=None)
    if k in ("cylinder", "circle"):
        c, ax = refs.cylinder_axis(shape)
        if abs(ax.dot(d)) > 0.05:
            why["last"] = f"cylinder axis at {abs(ax.dot(d)):.3f} to the view direction"
            return None
        r = shape.Surface.Radius if shape.ShapeType == "Face" else shape.Curve.Radius
        a, b = view_xy(view, c), view_xy(view, c + ax * 10.0)
        u = (b - a).normalize()
        cands, seen = [], []
        for i, e in lines:
            v = e.Vertexes[-1].Point - e.Vertexes[0].Point
            if v.Length < 1e-9 or abs(abs(App.Vector(v).normalize().dot(u)) - 1) > 1e-6:
                continue
            gap = _line_dist(e.Vertexes[0].Point, a, b)
            seen.append(round(gap, 4))
            if abs(gap - r) < 1e-3:
                cands.append((i, e))
        why["last"] = (f"r {r:g}, axis in the view {a} -> {b}, {len(lines)} lines, parallel ones at "
                       f"{sorted(seen)} from the axis")
        return min(cands, key=lambda ie: ie[1].Vertexes[0].Point.x, default=None)     # the left silhouette
    why["last"] = f"a {k}"
    return None


why = {}


def inherit(view, objs=None):
    """Put the model's PMI on a drawing view: diameters and distances as TechDraw dimensions on the edges
    that show their faces, with the PMI's ISO class or tolerance, stacked outside the view; datum symbols on
    the edge that shows their face; a frame under its feature's size dimension, or against that edge.
    Returns (created objects, skipped PMI with the reason)."""
    from . import gdt_ui
    page = gdt_ui.owning_page(view)
    doc = view.Document
    made, skipped = [], []
    anns = {a["id"]: a for a in annotations(doc)}
    on_sheet = {getattr(v, "NX_Pmi", "") for v in page.Views}
    objs = objs if objs is not None else all_pmi(doc)
    # dimensions first, so a frame can go under its feature's size dimension
    for o in sorted(objs, key=lambda o: o.PMIType != "Dimension"):
        if o.Name in on_sheet:                  # one PMI is shown once on a sheet, in the first view that shows it
            skipped.append((o.Label, "already on this sheet"))
            continue
        a = anns.get(o.Name) or semantic(o)
        if a["kind"] == "dimension":
            dim = inherit_dimension(view, page, o, a)
            if dim is None:
                skipped.append((o.Label, "no matching edge in this view"))
            else:
                made.append(dim)
                on_sheet.add(o.Name)
            continue
        picks = [(p, s) for p, subs in o.References for s in (subs or [""])]
        try:
            shape = refs.resolve(*picks[0])
        except Exception as e:
            skipped.append((o.Label, str(e)))
            continue
        if a["kind"] == "fcf":
            size_dim = size_dimension_on(page, o)
            params = {"characteristic": a["characteristic"], "tolerance": f"{a['tolerance']:g}",
                      "diameter": a["diameter"], "modifier": a["modifier"], "datums": [tuple(d) for d in a["datums"]]}
            if size_dim is not None:
                sym = gdt_ui.place_frame(params, page, "dimension", size_dim)
            else:
                hit = edge_for_face(view, shape)
                if hit is None:
                    skipped.append((o.Label, "its face is not seen edge-on in this view"))
                    continue
                sym = gdt_ui.place_frame(params, page, "edge", (view, hit[1]))
        else:
            hit = edge_for_face(view, shape)
            if hit is None:
                skipped.append((o.Label, f"its face is not seen edge-on in this view ({why.get('last', '')})"))
                continue
            sym = gdt_ui.place_datum(a["letter"], page, "edge", (view, hit[1]))
        gdt_ui.tag(sym, pmi=o.Name)
        made.append(sym)
        on_sheet.add(o.Name)
    note = tolerancing_note(page)
    if note is not None:
        made.append(note)
    doc.recompute()
    last_inherit[view.Name] = skipped
    return made, skipped


last_inherit = {}


def size_dimension_on(page, o):
    """The inherited TechDraw dimension of the same feature's size, if the sheet has one."""
    key = feature_key(o)
    for v in page.Views:
        name = getattr(v, "NX_Pmi", "")
        if not name or not v.isDerivedFrom("TechDraw::DrawViewDimension"):
            continue
        p = o.Document.getObject(name)
        if p is not None and getattr(p, "PMIType", "") == "Dimension" and not p.Basic and feature_key(p) == key \
                and p.DimensionType in ("Diameter", "Radius"):
            return v
    return None


def tolerancing_note(page):
    """The drawing's tolerancing note near the title block (ISO: 'Tolerancing ISO 8015', 'General
    tolerances ISO 2768-mK'); one per sheet, updated in place."""
    doc = page.Document
    std, general = settings(doc)
    lines = (["Tolerancing ISO 8015"] if std == "ISO" else ["Dimensioning and tolerancing per ASME Y14.5"])
    if general:
        lines.append(f"General tolerances {general}")
    note = next((v for v in page.Views if getattr(v, "NX_Pmi", "") == "tolerancing-note"), None)
    if note is None:
        note = doc.addObject("TechDraw::DrawViewAnnotation", "TolerancingNote")
        page.addView(note)
        note.addProperty("App::PropertyString", "NX_Pmi", "NX", "What this annotation is")
        note.NX_Pmi = "tolerancing-note"
        try:
            w, h = float(page.Template.Width), float(page.Template.Height)
        except Exception:
            w, h = 297.0, 210.0
        note.X, note.Y = w - 95.0, 62.0 if h < 300 else 80.0
        note.TextSize = 3.5
    note.Text = lines
    return note


def _view_edges(view):
    out = []
    for i in range(len(view.getVisibleEdges())):
        try:
            out.append((i, view.getEdgeByIndex(i)))
        except Exception:
            continue
    return out


def inherit_dimension(view, page, o, a):
    """A TechDraw dimension for a PMI diameter or distance, on the view edges that show its faces."""
    doc = view.Document
    s = edge_scale(view)
    edges = _view_edges(view)
    refs_2d = []
    dtype = None
    if a["dim_type"] in ("diameter", "radius"):
        r = a["nominal"] / (2 if a["dim_type"] == "diameter" else 1)
        for i, e in edges:
            if hasattr(e.Curve, "Radius") and abs(e.Curve.Radius - r * s) < 1e-4 * max(1, r):
                refs_2d = [(view, f"Edge{i}")]
                dtype = "Diameter" if a["dim_type"] == "diameter" else "Radius"
                break
        if not refs_2d:
            # a cylinder seen from the side: two parallel lines a diameter apart
            lines = [(i, e) for i, e in edges if not hasattr(e.Curve, "Radius")]
            for k, (i, e) in enumerate(lines):
                for j, f in lines[k + 1:]:
                    if _parallel_gap(e, f) is not None and abs(_parallel_gap(e, f) - 2 * r * s) < 1e-3:
                        v = e.Vertexes[-1].Point - e.Vertexes[0].Point
                        refs_2d = [(view, f"Edge{i}"), (view, f"Edge{j}")]
                        dtype = "DistanceX" if abs(v.y) > abs(v.x) else "DistanceY"
                        break
                if refs_2d:
                    break
    else:
        lines = [(i, e) for i, e in edges if not hasattr(e.Curve, "Radius")]
        target = a["nominal"] * s
        pa = project(view, App.Vector(o.Anchor))
        pb = project(view, App.Vector(o.Anchor2))
        best = None
        for k, (i, e) in enumerate(lines):
            for j, f in lines[k + 1:]:
                g = _parallel_gap(e, f)
                if g is None or abs(g - target) > 1e-3:
                    continue
                # prefer the pair nearest the PMI's own attachment points
                ce, cf = _centre(view, e), _centre(view, f)
                score = min(_d(ce, pa) + _d(cf, pb), _d(ce, pb) + _d(cf, pa))
                if best is None or score < best[0]:
                    best = (score, i, j, e)
        if best is not None:
            _, i, j, e = best
            v = e.Vertexes[-1].Point - e.Vertexes[0].Point
            dtype = "DistanceX" if abs(v.y) > abs(v.x) else "DistanceY"
            refs_2d = [(view, f"Edge{i}"), (view, f"Edge{j}")]
    if not refs_2d:
        return None
    dim = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
    dim.Type = dtype
    dim.References2D = refs_2d
    dim.MeasureType = "Projected"
    page.addView(dim)
    # the dimension's own tolerance or ISO 286 class; one covered by the general tolerance shows none
    # (the title block note covers it)
    try:
        plus, minus, _ = pmi.deviations(a)
    except ValueError:
        plus, minus = 0.0, 0.0
    if a.get("basic"):
        dim.TheoreticalExact = True
    elif plus or minus:
        dim.EqualTolerance = abs(plus - minus) < 1e-12
        dim.OverTolerance = plus
        dim.UnderTolerance = -minus
        dim.FormatSpecOverTolerance = "%+.3w"
        dim.FormatSpecUnderTolerance = "%+.3w"
    count = f"{a['count']}X " if a.get("count", 1) > 1 else ""
    fit = f" {a['fit']}" if a.get("fit") else ""
    env = f" {pmi.ENVELOPE}" if a.get("envelope") else ""
    if count or fit or env:
        dim.FormatSpec = count + ("⌀" if dtype == "Diameter" or a["dim_type"] == "diameter" else "") + "%.3w" + fit + env
    try:
        dim.addProperty("App::PropertyString", "NX_Pmi", "NX", "The PMI this dimension was inherited from")
        dim.NX_Pmi = o.Name
    except Exception:
        pass
    place_dimension(view, page, dim, dtype, [view.getEdgeByIndex(int(n[4:])) for _, n in refs_2d])
    return dim


def place_dimension(view, page, dim, dtype, edges):
    """Move an inherited dimension outside its view, as a drafter drags it: vertical ones to the right,
    horizontal ones below, diameters out at an angle, each further out than the ones before."""
    s = float(view.Scale)
    bb = None
    for _, e in _view_edges(view):
        bb = e.BoundBox if bb is None else bb.united(e.BoundBox)
    if bb is None:
        return
    mine = [v for v in page.Views if v is not dim and v.isDerivedFrom("TechDraw::DrawViewDimension")
            and getattr(v, "NX_Pmi", "") and v.References2D and v.References2D[0][0] is view]
    same = sum(1 for v in mine if v.Type == dtype)
    pts = [p.Point for e in edges for p in e.Vertexes]
    if dtype == "DistanceY":
        dim.X = (bb.XMax * s) + 10.0 + 9.0 * same
        dim.Y = sum(p.y for p in pts) / len(pts) * s
    elif dtype == "DistanceX":
        dim.Y = (bb.YMin * s) - 10.0 - 9.0 * same
        dim.X = sum(p.x for p in pts) / len(pts) * s
    else:
        import math
        ang = math.radians(40.0 + 28.0 * same)
        R = max(bb.XMax, bb.YMax) * s + 8.0 + 4.0 * same
        dim.X, dim.Y = R * math.cos(ang), R * math.sin(ang)


def edge_scale(view):
    """Factor from model mm to the view's edge coordinates. TechDraw's getEdgeByIndex returns the
    projected edges unscaled (measured, FreeCAD 1.1.4: circles of a 2:1 view report the model's radii);
    the view's Scale applies only on the way to the sheet."""
    return 1.0


def _centre(view, e):
    m = (e.Vertexes[0].Point + e.Vertexes[-1].Point) * 0.5
    s = float(view.Scale)
    return float(view.X) + m.x * s, float(view.Y) + m.y * s


def _d(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _parallel_gap(e, f):
    """Distance between two parallel straight edges (None if not parallel)."""
    try:
        if len(e.Vertexes) < 2 or len(f.Vertexes) < 2:
            return None
        u = e.Vertexes[-1].Point - e.Vertexes[0].Point
        v = f.Vertexes[-1].Point - f.Vertexes[0].Point
        if u.Length < 1e-9 or v.Length < 1e-9:
            return None
        u.normalize()
        v.normalize()
        if abs(abs(u.dot(v)) - 1) > 1e-6:
            return None
        w = f.Vertexes[0].Point - e.Vertexes[0].Point
        return (w - u * w.dot(u)).Length
    except Exception:
        return None


# ------------------------------------------------------------------ commands
def _part_document():
    doc = App.ActiveDocument
    return doc is not None and not Gui.Control.activeDialog()


class PMICommand:
    def __init__(self, panel, menu, tip, icon):
        self.panel, self.menu, self.tip, self.icon = panel, menu, tip, icon

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tip, "Pixmap": config.resource("icons", self.icon)}

    def IsActive(self):
        return _part_document()

    def Activated(self):
        Gui.Control.showDialog(self.panel())


class TolerancingPanel:
    """The part's tolerancing standard and general tolerance note (a drawing's title block entries)."""

    def __init__(self):
        self.doc = App.ActiveDocument
        std, general = settings(self.doc)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Tolerancing")
        lay = QtWidgets.QFormLayout(self.form)
        self.standard = QtWidgets.QComboBox()
        self.standard.setObjectName("standard")
        self.standard.addItems(["ISO GPS", "ASME Y14.5"])
        self.standard.setCurrentIndex(0 if std == "ISO" else 1)
        self.general = QtWidgets.QComboBox()
        self.general.setObjectName("generalTolerance")
        self.general.setEditable(True)
        self.general.addItems(["", "ISO 2768-fH", "ISO 2768-mK", "ISO 2768-cL", "ISO 2768-mK-E"])
        self.general.setCurrentText(general or "")
        lay.addRow("Standard", self.standard)
        lay.addRow("General tolerances", self.general)
        help_ = QtWidgets.QLabel("ISO GPS: a size controls local sizes only (ISO 8015 independency); a fit needs the "
                                 "envelope Ⓔ. ISO 2768-mK: medium linear and angular tolerances, class K geometrical "
                                 "tolerances; -E puts every feature of size in its envelope.")
        help_.setWordWrap(True)
        lay.addRow(help_)

    def accept(self):
        g = self.general.currentText().strip()
        if g and iso.parse_general(g) is None:
            QtWidgets.QMessageBox.information(self.form, "Tolerancing", f"'{g}' is not an ISO 2768 note "
                                              "(e.g. ISO 2768-mK).")
            return False
        self.doc.openTransaction("Tolerancing")
        f = folder(self.doc)
        f.Standard = self.standard.currentText()
        f.GeneralTolerance = g
        for o in all_pmi(self.doc):
            o.touch()
        self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class Tolerancing:
    def GetResources(self):
        return {"MenuText": "Tolerancing",
                "ToolTip": "The part's tolerancing standard (ISO GPS or ASME Y14.5) and general tolerances "
                           "(ISO 2768), as a drawing's title block states them",
                "Pixmap": config.resource("icons", "tolerancing.svg")}

    def IsActive(self):
        return _part_document()

    def Activated(self):
        Gui.Control.showDialog(TolerancingPanel())


class InspectionPlan:
    def GetResources(self):
        return {"MenuText": "Inspection Plan",
                "ToolTip": "Number the PMI characteristics (balloons) and list them with their limits and how to "
                           "measure them, the functional gauge sizes (virtual condition, datums at MMB) and the "
                           "ASME Y14.5 checks",
                "Pixmap": config.resource("icons", "inspection_plan.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and bool(all_pmi(App.ActiveDocument))

    def Activated(self):
        from .commands import show_information
        doc = App.ActiveDocument
        doc.openTransaction("Inspection Plan")
        text = plan_text(doc)
        doc.commitTransaction()
        show_information(text)


class InheritPMI:
    def GetResources(self):
        return {"MenuText": "Inherit PMI",
                "ToolTip": "Put the model's PMI on the selected drawing view: dimensions with their tolerances, "
                           "feature control frames and datum feature symbols",
                "Pixmap": config.resource("icons", "inherit_pmi.svg")}

    @staticmethod
    def _view():
        for o in Gui.Selection.getSelection():
            if o.isDerivedFrom("TechDraw::DrawViewPart"):
                return o
        return None

    def IsActive(self):
        return self._view() is not None

    def Activated(self):
        view = self._view()
        doc = view.Document
        doc.openTransaction("Inherit PMI")
        made, skipped = inherit(view)
        doc.commitTransaction()
        msg = f"Inherit PMI: {len(made)} annotation(s) on {view.Label}"
        for label, why in skipped:
            msg += f"\n  {label}: not placed ({why})"
        App.Console.PrintMessage(msg + "\n")


COMMANDS = {
    "NXStyle_PMIRapidDimension": PMICommand(DimensionPanel, "Rapid Dimension",
                                            "PMI: a dimension on the model. Select a cylinder (diameter) or two "
                                            "faces (distance) first; it is measured from the model and keeps up "
                                            "with design changes", "pmi_dimension.svg"),
    "NXStyle_PMIFeatureControlFrame": PMICommand(FramePanel, "Feature Control Frame",
                                                 "PMI: a feature control frame on the selected face",
                                                 "feature_control_frame.svg"),
    "NXStyle_PMIDatumFeatureSymbol": PMICommand(DatumPanel, "Datum Feature Symbol",
                                                "PMI: a datum feature symbol on the selected face",
                                                "datum_feature_symbol.svg"),
    "NXStyle_PMIInspectionPlan": InspectionPlan(),
    "NXStyle_PMITolerancing": Tolerancing(),
    "NXStyle_InheritPMI": InheritPMI(),
}

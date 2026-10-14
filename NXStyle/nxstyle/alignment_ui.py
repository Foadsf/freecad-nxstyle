# SPDX-License-Identifier: LGPL-2.1-or-later
"""Analysis > Pin Location: how precisely two pins locate one part on another (alignment.py).

The pins and the holes (or the hole and the slot) are given by their PMI dimensions, so the ISO 286
classes and tolerances of the model are what is analysed: two diameter dimensions on the pins and two
on the holes, or one diameter and one width (a slot) on the located part. Spacings are measured
between the features' axes in the model; their tolerances are entered here, as are the distance to
a target (an optical axis's pointing error) and the assembly temperature. The parts' materials give
the expansion coefficients. The feature recomputes when the PMI or the model changes.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import alignment, config, pmi, refs
from .qt import QtWidgets

GROUP = "Pin Location"


def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


def cte_of(obj):
    """Thermal expansion (1/K) of the material assigned to obj or the body it is in, or None."""
    chain = [obj]
    try:
        chain += [p for p in obj.InListRecursive if p.isDerivedFrom("PartDesign::Body")]
    except Exception:
        pass
    for o in chain:
        mat = getattr(o, "ShapeMaterial", None)
        if mat is None:
            continue
        try:
            q = mat.getPhysicalValue("ThermalExpansionCoefficient")
        except Exception:
            q = None
        if q is None:
            continue
        v = getattr(q, "Value", None)
        if v is None:
            try:
                v = float(str(q).split()[0])
            except ValueError:
                continue
        return float(v)
    return None


def feature_of(dim):
    """(kind, centre point, axis direction or None, owner object) of a PMI dimension's feature:
    kind 'hole', 'pin' or 'slot' (an internal width)."""
    picks = [(o, s) for o, subs in dim.References for s in (subs or [""])]
    shapes = [refs.resolve(o, s) for o, s in picks]
    owner = picks[0][0] if picks else None
    if dim.DimensionType in ("Diameter", "Radius"):
        c, d = refs.cylinder_axis(shapes[0])
        return dim.FeatureType or "hole", c, d, owner
    if len(shapes) >= 2:
        c = (shapes[0].CenterOfMass + shapes[1].CenterOfMass) * 0.5
        return ("slot" if dim.FeatureType == "slot" else "width"), c, None, owner
    raise ValueError(f"{dim.Label}: not a diameter or a width")


def size_limits(dim, general=None):
    from . import pmi_ui
    a = pmi_ui.semantic(dim)
    lo, hi = pmi.size_limits(a, general)
    if a.get("dim_type") == "radius":
        lo, hi = 2 * lo, 2 * hi
    return (lo, hi), a


def spacing(c1, c2, axis):
    """Distance between two feature centres across the pins' axis direction."""
    d = c2 - c1
    if axis is not None:
        d = d - axis * d.dot(axis)
    return d.Length


class PinLocationFeature:
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g = GROUP
        _prop(obj, "App::PropertyEnumeration", "Layout", g, "Two round pins in two holes, or in a hole and a slot")
        if not obj.Layout:
            obj.Layout = list(alignment.LAYOUTS)
            obj.Layout = alignment.TWO_HOLES
        _prop(obj, "App::PropertyLink", "Hole1", g, "PMI diameter of the hole that locates (the slot's partner)")
        _prop(obj, "App::PropertyLink", "Hole2", g, "PMI diameter of the second hole, or PMI width of the slot")
        _prop(obj, "App::PropertyLink", "Pin1", g, "PMI diameter of the pin in Hole1")
        _prop(obj, "App::PropertyLink", "Pin2", g, "PMI diameter of the pin in Hole2")
        _prop(obj, "App::PropertyFloat", "HoleSpacingTolerance", g, "± on the distance between the holes (mm)", 0.005)
        _prop(obj, "App::PropertyFloat", "PinSpacingTolerance", g, "± on the distance between the pins (mm)", 0.005)
        _prop(obj, "App::PropertyFloat", "SlotLength", g, "Length of the slot along the line of centres (mm); "
              "0 = not checked", 0.0)
        _prop(obj, "App::PropertyFloat", "TargetDistance", g, "Distance to the target of the located axis, for its "
              "pointing error (mm); 0 = none", 0.0)
        _prop(obj, "App::PropertyFloat", "PointingLimit", g, "Largest pointing error allowed at the target (mm); "
              "0 = none", 0.0)
        _prop(obj, "App::PropertyFloat", "DeltaT", g, "Assembly temperature minus the reference temperature (K)", 0.0)
        _prop(obj, "App::PropertyFloat", "CTEHoles", g, "Expansion of the part with the holes (µm/m/K), from its "
              "material", 0.0)
        _prop(obj, "App::PropertyFloat", "CTEPins", g, "Expansion of the part with the pins (µm/m/K), from its material",
              0.0)
        r = "Result"
        for name, doc in (("HoleSpacing", "Measured distance between the holes (mm)"),
                          ("PinSpacing", "Measured distance between the pins (mm)"),
                          ("Clearance", "Worst-case fit clearance (mm); negative: does not assemble"),
                          ("Translation", "Largest translation of the located part (mm)"),
                          ("Rotation", "Largest rotation of the located part (mrad)"),
                          ("Pointing", "Largest pointing error at the target (mm)")):
            _prop(obj, "App::PropertyFloat", name, r, doc, mode=1)
        _prop(obj, "App::PropertyString", "Verdict", r, "Assembles, meets the pointing limit", mode=1)
        _prop(obj, "App::PropertyString", "Report", r, "The full analysis", mode=1)
        _prop(obj, "App::PropertyLinkList", "PMI", r, "The PMI it reads (keeps it up to date)", mode=2)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        try:
            analyse(obj)
        except Exception as e:
            obj.Verdict = f"error: {e}"
            obj.Report = obj.Verdict


def analyse(obj):
    from . import pmi_ui
    dims = [obj.Hole1, obj.Pin1, obj.Hole2, obj.Pin2]
    if any(d is None for d in dims):
        raise ValueError("needs the PMI of two holes (or a hole and a slot) and two pins")
    obj.PMI = dims
    _, general = pmi_ui.settings(obj.Document)
    (h1, _), (p1, _), (h2, _), (p2, _) = [size_limits(d, general) for d in dims]
    f = [feature_of(d) for d in dims]
    axis = f[1][2] or f[0][2]
    dh = spacing(f[0][1], f[2][1], axis)
    dp = spacing(f[1][1], f[3][1], axis)
    obj.HoleSpacing, obj.PinSpacing = dh, dp
    slot = f[2][0] in ("slot", "width")
    layout = alignment.HOLE_SLOT if slot else alignment.TWO_HOLES
    if obj.Layout != layout:
        obj.Layout = layout
    th, tp = float(obj.HoleSpacingTolerance), float(obj.PinSpacingTolerance)
    r = alignment.analyse(layout, h1, p1, h2, p2, (dh - th, dh + th), (dp - tp, dp + tp),
                          slot_length=(float(obj.SlotLength) or None) if slot else None, dT=float(obj.DeltaT),
                          cte_holes=float(obj.CTEHoles) * 1e-6, cte_pins=float(obj.CTEPins) * 1e-6,
                          distance=float(obj.TargetDistance) or None)
    obj.Clearance = r["clearance"]
    obj.Translation = r["translation"]
    obj.Rotation = (r["rotation"] or 0.0) * 1e3
    obj.Pointing = r.get("pointing") or 0.0
    verdict = "assembles" if r["assembles"] else "does NOT assemble"
    limit = float(obj.PointingLimit)
    if limit and r.get("pointing") is not None:
        verdict += "; pointing " + ("within" if r["pointing"] <= limit else "EXCEEDS") + f" ±{limit:g} mm"
    obj.Verdict = verdict
    names = (f"holes {dims[0].Callout} and {dims[2].Callout} {dh:.3f} ±{th:g} apart; pins {dims[1].Callout} and "
             f"{dims[3].Callout} {dp:.3f} ±{tp:g} apart")
    temp = (f"; {obj.DeltaT:g} K from the reference, expansion {obj.CTEHoles:g} (holes) and {obj.CTEPins:g} (pins) "
            "µm/m/K" if obj.DeltaT else "")
    obj.Report = alignment.report(r, title=obj.Label) + f"\n  {names}{temp}\n  verdict: {verdict}"
    last.update(report=obj.Report, result=r)


last = {}


def pair(dims):
    """Hole1, Pin1, Hole2, Pin2 from four PMI dimensions: located-part features (holes, a slot) with the
    nearest pin each; a slot (a width) is always Hole2."""
    feats = [(d,) + feature_of(d) for d in dims]
    holes = [x for x in feats if x[1] in ("hole", "slot", "width")]
    pins = [x for x in feats if x[1] == "pin"]
    if len(holes) != 2 or len(pins) != 2:
        raise ValueError("select the PMI of two pins and of two holes (or a hole and a slot)")
    holes.sort(key=lambda x: x[1] != "hole")             # the round hole first
    out = []
    left = list(pins)
    for h in holes:
        p = min(left, key=lambda x: (x[2] - h[2]).Length)
        left.remove(p)
        out += [h, p]
    return [x[0] for x in out], out


class PinLocationPanel:
    FIELDS = (("HoleSpacingTolerance", "Hole spacing ±", " mm", 4), ("PinSpacingTolerance", "Pin spacing ±", " mm", 4),
              ("SlotLength", "Slot length", " mm", 3), ("TargetDistance", "Distance to target", " mm", 1),
              ("PointingLimit", "Pointing limit ±", " mm", 3), ("DeltaT", "Temperature difference", " K", 1),
              ("CTEHoles", "Expansion, part with holes", " µm/m/K", 2), ("CTEPins", "Expansion, part with pins",
                                                                          " µm/m/K", 2))

    def __init__(self, obj, new=False):
        self.obj, self.new = obj, new
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Pin Location")
        lay = QtWidgets.QFormLayout(self.form)
        lay.addRow("Layout", QtWidgets.QLabel(f"{obj.Layout}: {obj.Hole1.Label} / {obj.Pin1.Label}, "
                                              f"{obj.Hole2.Label} / {obj.Pin2.Label}"))
        self.spins = {}
        for prop, label, suffix, decimals in self.FIELDS:
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName(prop)
            s.setDecimals(decimals)
            s.setRange(-1000.0 if prop == "DeltaT" else 0.0, 1e6)
            s.setSuffix(suffix)
            s.setValue(float(getattr(obj, prop)))
            lay.addRow(label, s)
            self.spins[prop] = s
        note = QtWidgets.QLabel("Sizes and their ISO 286 classes come from the PMI; spacings are measured between the "
                                "axes. Drake, Dimensioning and Tolerancing Handbook, ch. 24.")
        note.setWordWrap(True)
        lay.addRow(note)

    def accept(self):
        from .commands import show_information
        doc = self.obj.Document
        for prop, s in self.spins.items():
            setattr(self.obj, prop, s.value())
        self.obj.touch()
        doc.recompute()
        doc.commitTransaction()
        Gui.Control.closeDialog()
        show_information(self.obj.Report)
        return True

    def reject(self):
        doc = self.obj.Document
        if self.new:
            doc.abortTransaction()
        Gui.Control.closeDialog()
        return True


class PinLocationView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return config.resource("icons", "pin_location.svg")

    def setEdit(self, vobj, mode=0):
        vobj.Object.Document.openTransaction("Pin Location")
        Gui.Control.showDialog(PinLocationPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        return self.setEdit(vobj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create(dims, doc=None, **values):
    doc = doc or App.ActiveDocument
    ordered, feats = pair(dims)
    obj = doc.addObject("App::FeaturePython", "PinLocation")
    PinLocationFeature(obj)
    obj.Label = "Pin Location"
    obj.Hole1, obj.Pin1, obj.Hole2, obj.Pin2 = ordered
    holes_cte = cte_of(feats[0][4]) if feats[0][4] is not None else None
    pins_cte = cte_of(feats[1][4]) if feats[1][4] is not None else None
    obj.CTEHoles = (holes_cte or 0.0) * 1e6
    obj.CTEPins = (pins_cte or 0.0) * 1e6
    for k, v in values.items():
        setattr(obj, k, v)
    if App.GuiUp:
        PinLocationView(obj.ViewObject)
    doc.recompute()
    return obj


class PinLocation:
    def GetResources(self):
        return {"MenuText": "Pin Location",
                "ToolTip": "How precisely two pins locate a part: fit, translation, rotation and pointing error, from "
                           "the PMI of two pins and two holes (or a hole and a slot). Select the four PMI dimensions "
                           "first",
                "Pixmap": config.resource("icons", "pin_location.svg")}

    @staticmethod
    def _dims():
        from . import pmi_ui
        return [o for o in Gui.Selection.getSelection()
                if isinstance(getattr(o, "Proxy", None), pmi_ui.PMIFeature) and o.PMIType == "Dimension"]

    def IsActive(self):
        return len(self._dims()) == 4 and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        doc.openTransaction("Pin Location")
        try:
            obj = create(self._dims(), doc)
        except ValueError as e:
            doc.abortTransaction()
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Pin Location", str(e))
            return
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(PinLocationPanel(obj, new=True))


COMMANDS = {"NXStyle_PinLocation": PinLocation()}

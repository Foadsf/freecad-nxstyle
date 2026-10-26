# SPDX-License-Identifier: LGPL-2.1-or-later
"""Analysis > Gauge Study: is a gauge good enough for a PMI characteristic (msa.py)?

The characteristic is a PMI dimension or frame; its tolerance comes from the PMI (the size limits, a fit
class, the general tolerance, or the frame's zone). The readings are typed in, one line per part with
its repeated readings, and the study gives the gauge's repeatability as a share of that tolerance
(range method, Drake ch. 25). The study is a document object kept with the part: an inspection record
that recomputes when the PMI changes.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, msa, pmi
from .qt import QtWidgets

GROUP = "Gauge Study"
SPREADS = {"6 sigma (AIAG MSA)": 6.0, "3 sigma (Drake ch. 25)": 3.0}


def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


def tolerance_of(p):
    """(tolerance span, its text) of a PMI characteristic, from the inspection plan."""
    from . import pmi_ui
    pmi_ui.require_valid(p)
    general = pmi_ui.settings(p.Document)[1]
    anns = pmi.number([pmi_ui.semantic(o) for o in pmi_ui.all_pmi(p.Document)], general=general)   # no write-back
    rows = [r for r in pmi.inspection_plan(anns, general=general) if r["id"] == p.Name]
    if not rows:
        raise ValueError(f"{p.Label} is not a characteristic: it has no tolerance")
    r = rows[0]
    return r["upper"] - r["lower"], r["requirement"]


def parse(lines):
    out = []
    for ln in lines:
        if ln.strip():
            out.append([float(v) for v in ln.replace(",", " ").replace(";", " ").split()])
    return out


class GaugeStudyFeature:
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g = GROUP
        _prop(obj, "App::PropertyLink", "Characteristic", g, "The PMI dimension or frame the gauge checks")
        _prop(obj, "App::PropertyString", "Gauge", g, "The gauge or instrument studied", "")
        _prop(obj, "App::PropertyStringList", "Readings", g, "One line per part: its repeated readings (mm)")
        _prop(obj, "App::PropertyEnumeration", "Spread", g, "The gauge spread compared with the tolerance")
        if not obj.getEnumerationsOfProperty("Spread"):
            obj.Spread = list(SPREADS)
            obj.Spread = "6 sigma (AIAG MSA)"
        r = "Result"
        _prop(obj, "App::PropertyFloat", "Tolerance", r, "Tolerance span of the characteristic (mm)", mode=1)
        _prop(obj, "App::PropertyFloat", "Sigma", r, "Gauge standard deviation, average range / d2 (mm)", mode=1)
        _prop(obj, "App::PropertyFloat", "Percent", r, "Gauge spread as a share of the tolerance (%)", mode=1)
        _prop(obj, "App::PropertyString", "Verdict", r, "Acceptable, marginal or unacceptable", mode=1)
        _prop(obj, "App::PropertyString", "Report", r, "The full study", mode=1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        try:
            study(obj)
        except Exception as e:
            obj.Verdict = f"error: {e}"
            obj.Report = obj.Verdict


def study(obj):
    if obj.Characteristic is None:
        raise ValueError("needs a PMI characteristic")
    tol, req = tolerance_of(obj.Characteristic)
    obj.Tolerance = tol
    r = msa.repeatability(parse(obj.Readings), tol, SPREADS[obj.Spread])
    obj.Sigma, obj.Percent, obj.Verdict = r["sigma"], r["percent"], r["verdict"]
    title = f"{obj.Label}: {obj.Gauge or 'gauge'} on {obj.Characteristic.Label} ({req})"
    obj.Report = msa.report(r, tol, title=title)
    last.update(report=obj.Report, result=r)


last = {}


class GaugeStudyPanel:
    def __init__(self, obj, new=False):
        self.obj, self.new = obj, new
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Gauge Study")
        lay = QtWidgets.QFormLayout(self.form)
        try:
            tol, req = tolerance_of(obj.Characteristic)
            lay.addRow("Characteristic", QtWidgets.QLabel(f"{req}: tolerance {tol:.4f} mm"))
        except ValueError as e:
            lay.addRow(QtWidgets.QLabel(str(e)))
        self.gauge = QtWidgets.QLineEdit(obj.Gauge)
        self.gauge.setObjectName("gauge")
        lay.addRow("Gauge", self.gauge)
        self.readings = QtWidgets.QPlainTextEdit("\n".join(obj.Readings))
        self.readings.setObjectName("readings")
        self.readings.setPlaceholderText("one line per part, its repeated readings, e.g.\n10.012 10.014\n10.009 10.009")
        lay.addRow("Readings (mm)", self.readings)
        self.spread = QtWidgets.QComboBox()
        self.spread.setObjectName("spread")
        self.spread.addItems(list(SPREADS))
        self.spread.setCurrentText(obj.Spread)
        lay.addRow("Spread", self.spread)
        note = QtWidgets.QLabel("Range method: σ = average range / d2. Under 10 % of the tolerance the gauge is "
                                "acceptable, over 30 % it is not (Drake, Dimensioning and Tolerancing Handbook, "
                                "ch. 25).")
        note.setWordWrap(True)
        lay.addRow(note)

    def accept(self):
        from .commands import show_information
        doc = self.obj.Document
        self.obj.Gauge = self.gauge.text().strip()
        self.obj.Readings = [ln.strip() for ln in self.readings.toPlainText().splitlines() if ln.strip()]
        self.obj.Spread = self.spread.currentText()
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


class GaugeStudyView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return config.resource("icons", "gauge_study.svg")

    def setEdit(self, vobj, mode=0):
        vobj.Object.Document.openTransaction("Gauge Study")
        Gui.Control.showDialog(GaugeStudyPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        return self.setEdit(vobj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create(characteristic, doc=None, **values):
    doc = doc or App.ActiveDocument
    obj = doc.addObject("App::FeaturePython", "GaugeStudy")
    GaugeStudyFeature(obj)
    obj.Label = "Gauge Study"
    obj.Characteristic = characteristic
    for k, v in values.items():
        setattr(obj, k, v)
    if App.GuiUp:
        GaugeStudyView(obj.ViewObject)
    doc.recompute()
    return obj


class GaugeStudy:
    def GetResources(self):
        return {"MenuText": "Gauge Study",
                "ToolTip": "Is the gauge good enough for a PMI characteristic? Its repeatability as a share of the "
                           "tolerance (range method). Select the PMI dimension or frame first",
                "Pixmap": config.resource("icons", "gauge_study.svg")}

    @staticmethod
    def _pmi():
        from . import pmi_ui
        sel = [o for o in Gui.Selection.getSelection() if isinstance(getattr(o, "Proxy", None), pmi_ui.PMIFeature)
               and o.PMIType != "Datum Feature"]
        return sel[0] if len(sel) == 1 else None

    def IsActive(self):
        return self._pmi() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        p = self._pmi()
        try:
            tolerance_of(p)
        except ValueError as e:
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Gauge Study", str(e))
            return
        doc.openTransaction("Gauge Study")
        obj = create(p, doc)
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(GaugeStudyPanel(obj, new=True))


COMMANDS = {"NXStyle_GaugeStudy": GaugeStudy()}

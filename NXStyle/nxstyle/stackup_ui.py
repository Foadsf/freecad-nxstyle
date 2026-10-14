# SPDX-License-Identifier: LGPL-2.1-or-later
"""Analysis > Tolerance Stackup: a one-dimensional stack-up that lives in the part.

Each dimension of the loop is either measured from the model (two picked faces, edges, cylinder
axes or vertices: its nominal and its direction come from the geometry and follow every design
change), taken from a PMI dimension (its tolerance too), or typed in (a geometric tolerance, a
bonus, an assembly shift). The stack-up object recomputes with the model; its results are
properties (WorstCaseMin, RSSMax, Verdict ...) that expressions and the release package
can use, and the graphics window shows the loop as dimension lines along the stack direction.
The numbers come from nxstyle.stackup (worst case, RSS, adjusted RSS, MRSS, Monte Carlo).
"""

import json

import FreeCAD as App
import FreeCADGui as Gui

from . import config, refs, stackup
from .qt import QtCore, QtGui, QtWidgets

COLUMNS = ["Description", "Part", "Nominal", "Dir", "Upper dev.", "Below nominal", "ISO class", "Kind", "Source"]
C_NAME, C_PART, C_NOM, C_DIR, C_PLUS, C_MINUS, C_FIT, C_KIND, C_SRC = range(len(COLUMNS))


# ------------------------------------------------------------------ the document object
def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


class StackupFeature:
    """Proxy of a ToleranceStackup (App::FeaturePython)."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g, r = "Stack-up", "Results"
        _prop(obj, "App::PropertyStringList", "Rows", g, "One contributor per line (JSON): description, part, "
              "kind, nominal, plus, minus, direction; measured rows take nominal and direction from References")
        _prop(obj, "App::PropertyLinkSubList", "References", g, "The picks of the measured rows, two per row, in order")
        # the PMI the rows follow, as links: a change of a PMI's class or tolerance recomputes the stack-up
        # (the rows name them, but a name alone puts nothing in FreeCAD's dependency graph)
        _prop(obj, "App::PropertyLinkList", "PMI", g, "The PMI annotations rows take their tolerances from", mode=1)
        _prop(obj, "App::PropertyVector", "Direction", g, "The stack direction (from A towards B)")
        _prop(obj, "App::PropertyBool", "CheckMinimum", g, "The result has a minimum requirement", False)
        _prop(obj, "App::PropertyFloat", "Minimum", g, "Smallest acceptable result (mm)", 0.0)
        _prop(obj, "App::PropertyBool", "CheckMaximum", g, "The result has a maximum requirement", False)
        _prop(obj, "App::PropertyFloat", "Maximum", g, "Largest acceptable result (mm)", 0.0)
        _prop(obj, "App::PropertyFloat", "RSSFactor", g, "Adjusted RSS = factor x RSS (Fischer: 1.5)", 1.5)
        _prop(obj, "App::PropertyInteger", "Samples", g, "Monte Carlo assemblies (0: no simulation)", 100000)
        _prop(obj, "App::PropertyInteger", "Seed", g, "Monte Carlo random seed (repeatable runs)", 1)
        _prop(obj, "App::PropertyFloatList", "Measured", r, "Signed measured value of each row (0 for typed rows)",
              mode=1)
        _prop(obj, "App::PropertyVectorList", "Anchors", r, "Start and end point of each measured row", mode=2)
        for name, doc in (("Nominal", "Nominal result"), ("WorstCaseMin", "Worst case minimum"),
                          ("WorstCaseMax", "Worst case maximum"), ("RSSMin", "RSS minimum"), ("RSSMax", "RSS maximum"),
                          ("AdjustedMin", "Adjusted RSS minimum"), ("AdjustedMax", "Adjusted RSS maximum"),
                          ("MonteCarloPPM", "Monte Carlo share out of the requirement, ppm")):
            _prop(obj, "App::PropertyFloat", name, r, doc, mode=1)
        _prop(obj, "App::PropertyString", "Verdict", r, "Worst case and adjusted RSS against the requirement", mode=1)
        _prop(obj, "App::PropertyString", "Report", r, "The stack-up report", mode=2)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        try:
            cs, measured, anchors, problems = evaluate(obj)
        except Exception as e:
            obj.Verdict = f"error: {e}"
            return
        obj.Measured = measured
        obj.Anchors = anchors
        if not cs:
            obj.Verdict = "no contributors"
            obj.Report = ""
            return
        lsl = obj.Minimum if obj.CheckMinimum else None
        usl = obj.Maximum if obj.CheckMaximum else None
        r = stackup.analyse(cs, lsl, usl, factor=obj.RSSFactor, samples=max(0, obj.Samples), seed=obj.Seed)
        adj = next(m for m in r.methods if m.startswith("adjusted"))
        obj.Nominal = r.mean
        obj.WorstCaseMin, obj.WorstCaseMax = r.limits["worst case"]
        obj.RSSMin, obj.RSSMax = r.limits["RSS"]
        obj.AdjustedMin, obj.AdjustedMax = r.limits[adj]
        obj.MonteCarloPPM = r.mc["ppm"] if r.mc else 0.0
        verdict = f"worst case {r.verdicts['worst case'] or '-'}, adjusted RSS {r.verdicts[adj] or '-'}"
        if problems:
            verdict += "; " + "; ".join(problems)
        obj.Verdict = verdict
        d = obj.Direction
        obj.Report = stackup.report(cs, r, f"Tolerance stack-up: {obj.Label}",
                                    direction=f"({d.x:.3f}, {d.y:.3f}, {d.z:.3f})")


def rows_of(obj):
    out = []
    for line in obj.Rows:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def flat_refs(obj):
    return [(o, s) for o, subs in obj.References for s in (subs or [""])]


def pmi_values(row, doc):
    """Nominal, plus, minus of the PMI annotation a row follows (or None): a dimension gives its
    deviations, a feature control frame half its zone (Fischer: a zone T is +/- T/2), its bonus
    row half the size tolerance of the feature."""
    name = row.get("pmi")
    o = doc.getObject(name) if name else None
    if o is None:
        return None
    from . import pmi_ui
    return pmi_ui.stack_values(o, row.get("pmi_part", "tolerance"))


def evaluate(obj):
    """(contributors, measured values, anchor points, problems) of a stack-up object."""
    rows = rows_of(obj)
    picks = flat_refs(obj)
    axis = App.Vector(obj.Direction)
    if axis.Length < 1e-12:
        axis = App.Vector(1, 0, 0)
    axis.normalize()
    cs, measured, anchors, problems, k = [], [], [], [], 0
    for i, row in enumerate(rows):
        nominal, direction = float(row.get("nominal", 0.0)), int(row.get("direction", 1))
        plus, minus = float(row.get("plus", 0.0)), float(row.get("minus", row.get("plus", 0.0)))
        value = 0.0
        if row.get("measured"):
            if k + 1 >= len(picks):
                problems.append(f"row {i + 1}: picks missing")
                k += 2
                measured.append(0.0)
                continue
            (oa, sa), (ob, sb) = picks[k], picks[k + 1]
            k += 2
            try:
                a, b = refs.resolve(oa, sa), refs.resolve(ob, sb)
                value = refs.signed_distance(a, b, axis)
                p = refs.anchor(a)
                anchors += [p, p + axis * value]
                nominal, direction = abs(value), (1 if value >= 0 else -1)
            except Exception as e:
                problems.append(f"row {i + 1}: {e}")
        pv = pmi_values(row, obj.Document)
        if pv is not None:
            if not row.get("measured"):
                nominal = pv[0]
            plus, minus = pv[1], pv[2]
        if row.get("fit"):                       # an ISO 286 class gives the deviations at the nominal
            try:
                from . import iso
                up, lo = iso.deviations(row["fit"], nominal)
                plus, minus = up, -lo
            except ValueError as e:
                problems.append(f"row {i + 1}: {e}")
        measured.append(value)
        cs.append(stackup.Contributor(row.get("name", f"Row {i + 1}"), nominal, plus, minus, direction,
                                      row.get("kind", "dimension"), row.get("part", ""), row.get("source", ""),
                                      row.get("distribution", "normal")))
    return cs, measured, anchors, problems


# ------------------------------------------------------------------ the 3D display
class StackupView:
    """Draws each measured row as a dimension line along the stack direction, stepped out from the
    part, with its number and value; the result last, green when the verdict is OK."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.vobj = vobj
        self.root = coin.SoSeparator()
        self.lines = coin.SoSeparator()
        self.root.addChild(self.lines)
        vobj.addDisplayMode(self.root, "Loop")
        self.update(vobj.Object)

    def getDisplayModes(self, vobj):
        return ["Loop"]

    def getDefaultDisplayMode(self):
        return "Loop"

    def setDisplayMode(self, mode):
        return mode

    def updateData(self, obj, prop):
        # Report is the last property execute() writes: by then the results drawn with the loop are new
        # (on Anchors alone the A-B label kept the previous result after a model change)
        if prop in ("Anchors", "Rows", "Report", "Nominal", "WorstCaseMin", "WorstCaseMax"):
            self.update(obj)

    def onChanged(self, vobj, prop):
        pass

    def getIcon(self):
        return config.resource("icons", "stackup.svg")

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(StackupPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        return None

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def update(self, obj):
        try:
            self.lines.removeAllChildren()
        except Exception:
            return
        pts = list(getattr(obj, "Anchors", []))
        if len(pts) < 2:
            return
        axis = App.Vector(obj.Direction)
        if axis.Length < 1e-12:
            return
        axis.normalize()
        side = axis.cross(App.Vector(0, 0, 1))
        if side.Length < 1e-6:
            side = axis.cross(App.Vector(0, 1, 0))
        side.normalize()
        # the dimension lines step out beyond the parts, like a drawing's: from the parts' outer
        # boundary on that side, one step per row
        far, span = max(p.dot(side) for p in pts), max((p - pts[0]).Length for p in pts) or 1.0
        try:
            bb = None
            for o, _ in obj.References:
                b_ = o.Shape.BoundBox
                bb = b_ if bb is None else bb.united(b_)
            if bb is not None:
                corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
                           for z in (bb.ZMin, bb.ZMax)]
                far = max(far, max(c.dot(side) for c in corners))
                span = max(span, bb.DiagonalLength * 0.5)
        except Exception:
            pass
        step = max(span * 0.09, 2.0)
        rows = rows_of(obj)
        try:
            cs = evaluate(obj)[0]
        except Exception:
            cs = []
        measured = [(i, r) for i, r in enumerate(rows) if r.get("measured")]
        n = len(pts) // 2
        for k in range(n):
            a, b = pts[2 * k], pts[2 * k + 1]
            base = side * (far - a.dot(side) + step * 0.25)
            off = side * (far - a.dot(side) + step * (k + 1))
            label = f"{k + 1}"
            if k < len(measured):
                i = measured[k][0]
                tol = cs[i].tolerance if i < len(cs) and len(cs) == len(rows) else 0.0
                label = f"{i + 1}:  {(b - a).Length:.3f} ±{tol:.3g}"
            # labels a third of the way from each row's start: rows that run over one another in a loop
            # (A to the head, the head to the tip) then keep their texts apart
            self._dimension(a, b, off, label, (0.04, 0.43, 0.47), base=base, where=0.3)
        # the result: from the loop's start A to its end B
        a = pts[0]
        ok = "FAILS" not in (obj.Verdict or "")
        base = side * (far - a.dot(side) + step * 0.25)
        off = side * (far - a.dot(side) + step * (n + 1.4))
        self._dimension(a, a + axis * float(obj.Nominal), off,
                        f"A-B  {obj.Nominal:.3f}  [{obj.WorstCaseMin:.3f} .. {obj.WorstCaseMax:.3f}]",
                        (0.10, 0.55, 0.20) if ok else (0.80, 0.10, 0.10), width=3, base=base)

    def _dimension(self, a, b, off, label, rgb, width=2, base=None, where=0.5):
        """A dimension line between a and b moved out by off; its extension lines start at base
        (outside the part) rather than at the measured points themselves."""
        from pivy import coin
        sep = coin.SoSeparator()
        mat = coin.SoBaseColor()
        mat.rgb = rgb
        style = coin.SoDrawStyle()
        style.lineWidth = width
        sep += [mat, style]
        pa, pb = a + off, b + off
        sa, sb = (a + base, b + base) if base is not None else (a, b)
        coords = coin.SoCoordinate3()
        pts = [sa, pa, sb, pb, pa, pb]
        coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, 3, [2, 2, 2])
        sep += [coords, lines]
        # arrow heads as short ticks across the line
        d = pb - pa
        if d.Length > 1e-9:
            t = App.Vector(off).normalize() * min(d.Length * 0.15, 1.5)
            tick = coin.SoCoordinate3()
            tp = [pa - t, pa + t, pb - t, pb + t]
            tick.point.setValues(0, 4, [(p.x, p.y, p.z) for p in tp])
            tl = coin.SoLineSet()
            tl.numVertices.setValues(0, 2, [2, 2])
            sep += [tick, tl]
        txt = coin.SoSeparator()
        mid = pa + (pb - pa) * where + App.Vector(off).normalize() * 0.6
        tr = coin.SoTranslation()
        tr.translation = (mid.x, mid.y, mid.z)
        font = coin.SoFont()
        font.size = 13
        text = coin.SoText2()
        text.string = label
        txt += [tr, font, text]
        sep.addChild(txt)
        self.lines.addChild(sep)


def create(doc=None, label="ToleranceStackup"):
    doc = doc or App.ActiveDocument
    obj = doc.addObject("App::FeaturePython", "ToleranceStackup")
    StackupFeature(obj)
    obj.Label = label
    if App.GuiUp:
        StackupView(obj.ViewObject)
    return obj


def set_rows(obj, rows, picks):
    obj.Rows = [json.dumps(r, sort_keys=True) for r in rows]
    obj.References = list(picks)
    linked = []
    for r in rows:
        o = obj.Document.getObject(r["pmi"]) if r.get("pmi") else None
        if o is not None and o not in linked:
            linked.append(o)
    if "PMI" in obj.PropertiesList:
        obj.PMI = linked


# ------------------------------------------------------------------ the dialog
def _num(text, default=0.0):
    try:
        return float(str(text).replace(",", ".").replace("±", "").strip() or default)
    except ValueError:
        return default


class StackupPanel:
    """Tolerance Stackup dialog: the loop as a table, the requirement, the live result."""

    def __init__(self, obj=None):
        self.created = obj is None
        self.doc = App.ActiveDocument if obj is None else obj.Document
        self.doc.openTransaction("Tolerance Stackup")     # Cancel undoes every change made in the dialog
        if obj is None:
            obj = create(self.doc)
        self.obj = obj
        self.rows = rows_of(obj)
        self.picks = flat_refs(obj)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Tolerance Stackup")
        self.form.setObjectName("ToleranceStackup")
        lay = QtWidgets.QVBoxLayout(self.form)
        hint = QtWidgets.QLabel("Pick two faces (or edges, axes, vertices) and press Add Measured: the loop runs "
                                "from point A, the first pick of the first row, to point B. Geometric tolerances, "
                                "bonus and assembly shift are typed rows (nominal 0).")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        buttons = QtWidgets.QHBoxLayout()
        self.add_measured = QtWidgets.QPushButton("Add Measured")
        self.add_measured.setObjectName("addMeasured")
        self.add_typed = QtWidgets.QPushButton("Add Typed")
        self.add_typed.setObjectName("addTyped")
        self.add_pmi = QtWidgets.QPushButton("Add from PMI")
        self.add_pmi.setObjectName("addFromPMI")
        self.remove = QtWidgets.QPushButton("Remove")
        self.remove.setObjectName("removeRow")
        self.reverse = QtWidgets.QPushButton("Reverse Direction")
        self.reverse.setObjectName("reverseDirection")
        for b in (self.add_measured, self.add_typed, self.add_pmi, self.remove, self.reverse):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("stackTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(True)
        self.table.setMinimumHeight(170)
        lay.addWidget(self.table)
        req = QtWidgets.QGridLayout()
        self.check_min = QtWidgets.QCheckBox("Minimum")
        self.check_min.setObjectName("checkMinimum")
        self.minimum = QtWidgets.QDoubleSpinBox()
        self.minimum.setObjectName("minimum")
        self.check_max = QtWidgets.QCheckBox("Maximum")
        self.check_max.setObjectName("checkMaximum")
        self.maximum = QtWidgets.QDoubleSpinBox()
        self.maximum.setObjectName("maximum")
        for s in (self.minimum, self.maximum):
            s.setRange(-1e6, 1e6)
            s.setDecimals(4)
            s.setSuffix(" mm")
        self.factor = QtWidgets.QDoubleSpinBox()
        self.factor.setObjectName("rssFactor")
        self.factor.setRange(1.0, 3.0)
        self.factor.setDecimals(2)
        self.samples = QtWidgets.QSpinBox()
        self.samples.setObjectName("samples")
        self.samples.setRange(0, 2000000)
        self.samples.setSingleStep(10000)
        req.addWidget(QtWidgets.QLabel("Requirement on A-B"), 0, 0, 1, 4)
        req.addWidget(self.check_min, 1, 0)
        req.addWidget(self.minimum, 1, 1)
        req.addWidget(self.check_max, 1, 2)
        req.addWidget(self.maximum, 1, 3)
        req.addWidget(QtWidgets.QLabel("Adjusted RSS factor"), 2, 0)
        req.addWidget(self.factor, 2, 1)
        req.addWidget(QtWidgets.QLabel("Monte Carlo assemblies"), 2, 2)
        req.addWidget(self.samples, 2, 3)
        lay.addLayout(req)
        self.result = QtWidgets.QPlainTextEdit()
        self.result.setObjectName("stackResult")
        self.result.setReadOnly(True)
        self.result.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.result.setMinimumHeight(220)
        self.result.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        lay.addWidget(self.result)
        self.check_min.setChecked(bool(obj.CheckMinimum))
        self.minimum.setValue(float(obj.Minimum))
        self.check_max.setChecked(bool(obj.CheckMaximum))
        self.maximum.setValue(float(obj.Maximum))
        self.factor.setValue(float(obj.RSSFactor))
        self.samples.setValue(int(obj.Samples))
        self.fill()
        self.add_measured.clicked.connect(self.on_add_measured)
        self.add_typed.clicked.connect(self.on_add_typed)
        self.add_pmi.clicked.connect(self.on_add_pmi)
        self.remove.clicked.connect(self.on_remove)
        self.reverse.clicked.connect(self.on_reverse)
        self.table.itemChanged.connect(self.on_item)
        for w in (self.check_min, self.check_max):
            w.toggled.connect(self.apply)
        for w in (self.minimum, self.maximum, self.factor):
            w.valueChanged.connect(self.apply)
        self.samples.valueChanged.connect(self.apply)
        self.apply()

    # ---- table <-> rows
    def fill(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        try:
            cs = evaluate(self.obj)[0]
        except Exception:
            cs = []
        effective = cs if len(cs) == len(self.rows) else [None] * len(self.rows)
        for i, r in enumerate(self.rows):
            c_ = effective[i]
            nominal = c_.nominal if c_ is not None else r.get("nominal", 0.0)
            direction = c_.direction if c_ is not None else r.get("direction", 1)
            plus = c_.plus if c_ is not None else float(r.get("plus", 0))
            minus = c_.minus if c_ is not None else float(r.get("minus", r.get("plus", 0)))
            values = [r.get("name", ""), r.get("part", ""), f"{float(nominal):.4f}", "+" if direction > 0 else "-",
                      f"{plus:+g}", f"{minus:g}", r.get("fit", ""), r.get("kind", "dimension"), r.get("source", "")]
            for c, v in enumerate(values):
                it = QtWidgets.QTableWidgetItem(str(v))
                locked = ((c in (C_NOM, C_DIR) and r.get("measured")) or c == C_SRC
                          or (c in (C_NOM, C_PLUS, C_MINUS, C_FIT) and r.get("pmi"))
                          or (c in (C_PLUS, C_MINUS) and r.get("fit")))
                if locked:
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    it.setForeground(QtGui.QBrush(QtGui.QColor("#5f6b7a")))
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

    def on_item(self, item):
        i, c = item.row(), item.column()
        if i >= len(self.rows):
            return
        r = self.rows[i]
        t = item.text()
        if c == C_NAME:
            r["name"] = t
        elif c == C_PART:
            r["part"] = t
        elif c == C_NOM:
            r["nominal"] = _num(t)
        elif c == C_DIR:
            r["direction"] = -1 if t.strip().startswith("-") else 1
        elif c == C_PLUS:
            # typing one value gives an equal-bilateral +/- tolerance until "Below nominal" is typed too
            r["plus"] = _num(t)
            if "minus" not in r or r.get("_equal", True):
                r["minus"] = abs(r["plus"])
        elif c == C_MINUS:
            r["minus"] = _num(t)
            r["_equal"] = False
        elif c == C_FIT:
            r["fit"] = t.strip()
            if not r["fit"]:
                del r["fit"]
        elif c == C_KIND:
            r["kind"] = t.strip() if t.strip() in stackup.KINDS else "other"
        self.apply()

    # ---- buttons
    def on_add_measured(self):
        picks = refs.selection_refs()
        if len(picks) != 2:
            QtWidgets.QMessageBox.information(self.form, "Tolerance Stackup",
                                              "Select exactly two faces, edges, cylinder axes or vertices.")
            return
        (oa, sa), (ob, sb) = picks
        try:
            a, b = refs.resolve(oa, sa), refs.resolve(ob, sb)
            if not any(r.get("measured") for r in self.rows):
                self.obj.Direction = refs.default_axis(a, b)
            refs.signed_distance(a, b, self.obj.Direction)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self.form, "Tolerance Stackup", f"Cannot measure along the stack: {e}")
            return
        n = len(self.rows) + 1
        part = oa.Label if oa is ob else f"{oa.Label} / {ob.Label}"
        self.rows.append({"name": f"Dimension {n}", "part": part, "measured": True, "plus": 0.0, "minus": 0.0,
                          "kind": "dimension", "source": f"{refs.describe(oa, sa)} -> {refs.describe(ob, sb)}"})
        self.picks += [(oa, sa), (ob, sb)]
        Gui.Selection.clearSelection()
        self.apply()

    def on_add_typed(self):
        n = len(self.rows) + 1
        self.rows.append({"name": f"Tolerance {n}", "part": "", "nominal": 0.0, "direction": 1, "plus": 0.0,
                          "minus": 0.0, "kind": "position", "source": "typed"})
        self.apply()

    def on_add_pmi(self):
        """Rows from the selected PMI: a dimension between two faces is measured and keeps the PMI's
        tolerance; a feature control frame becomes 0 +/- tol/2, plus a bonus row at MMC."""
        from . import pmi_ui
        added = 0
        for o in Gui.Selection.getSelection():
            for row, picks in pmi_ui.stack_rows(o, self.obj.Direction if any(r.get("measured") for r in self.rows)
                                                else None):
                if picks and not any(r.get("measured") for r in self.rows):
                    a, b = refs.resolve(*picks[0]), refs.resolve(*picks[1])
                    self.obj.Direction = refs.default_axis(a, b)
                self.rows.append(row)
                self.picks += picks
                added += 1
        if not added:
            QtWidgets.QMessageBox.information(self.form, "Tolerance Stackup", "Select PMI dimensions or feature "
                                              "control frames in the Part Navigator or the graphics window.")
            return
        Gui.Selection.clearSelection()
        self.apply()

    def on_remove(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self.rows)):
            return
        k = sum(2 for r in self.rows[:i] if r.get("measured"))
        if self.rows[i].get("measured"):
            del self.picks[k:k + 2]
        del self.rows[i]
        self.apply()

    def on_reverse(self):
        self.obj.Direction = App.Vector(self.obj.Direction) * -1
        self.apply()

    # ---- apply and show
    def write(self):
        o = self.obj
        clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in self.rows]
        set_rows(o, clean, self.picks)
        o.CheckMinimum = self.check_min.isChecked()
        o.Minimum = self.minimum.value()
        o.CheckMaximum = self.check_max.isChecked()
        o.Maximum = self.maximum.value()
        o.RSSFactor = self.factor.value()
        o.Samples = self.samples.value()

    def apply(self, *_):
        self.write()
        self.obj.touch()
        self.doc.recompute()
        self.fill()
        self.result.setPlainText(self.obj.Report or self.obj.Verdict)

    def accept(self):
        self.apply()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        Gui.ActiveDocument.resetEdit()
        from .commands import show_information
        show_information(self.obj.Report or self.obj.Verdict)
        return True

    def reject(self):
        name = self.obj.Name
        self.doc.abortTransaction()
        if self.created and self.doc.getObject(name) is not None:
            self.doc.removeObject(name)
        Gui.Control.closeDialog()
        Gui.ActiveDocument.resetEdit()
        self.doc.recompute()
        return True


class ToleranceStackup:
    def GetResources(self):
        return {"MenuText": "Tolerance Stackup",
                "ToolTip": "One-dimensional tolerance stack-up: dimensions measured from the model or taken from "
                           "PMI, geometric tolerances, bonus and assembly shift; worst case, RSS, adjusted RSS, "
                           "MRSS and Monte Carlo against a requirement. Select a stack-up to edit it.",
                "Pixmap": config.resource("icons", "stackup.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        sel = [o for o in Gui.Selection.getSelection() if isinstance(getattr(o, "Proxy", None), StackupFeature)]
        if sel:
            Gui.Selection.clearSelection()
            Gui.ActiveDocument.setEdit(sel[0].Name, 0)
            return
        Gui.Control.showDialog(StackupPanel())


def stackups(doc):
    return [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), StackupFeature)]


def csv_rows(obj):
    cs, _, _, _ = evaluate(obj)
    lsl = obj.Minimum if obj.CheckMinimum else None
    usl = obj.Maximum if obj.CheckMaximum else None
    r = stackup.analyse(cs, lsl, usl, factor=obj.RSSFactor, samples=max(0, obj.Samples), seed=obj.Seed)
    return stackup.to_csv_rows(cs, r)

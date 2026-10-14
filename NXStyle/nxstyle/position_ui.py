# SPDX-License-Identifier: LGPL-2.1-or-later
"""Analysis > Position Evaluation: does a measured pattern of holes or pins meet its position frame
(position_eval.py)? What a CMM report or a paper gauge decides (Cogorno ch. 13).

The frame is a PMI position Feature Control Frame on the pattern's cylindrical faces, single or
two-row (composite or stacked). The true positions come from the model, measured in the frame's datum
reference frame: from datum B and from datum C, in the plane of the primary datum A. The sizes and
their MMC come from the PMI diameter on the same faces. The measured positions and sizes are typed in
(or pasted from a CMM report), one row per feature. The evaluation is a document object, an inspection
record kept with the part; it recomputes when the model or the PMI changes.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, pmi, position_eval, refs
from .qt import QtCore, QtWidgets

GROUP = "Position Evaluation"
MOTIONS = ["From datums", "Translate and turn", "Translate only", "Fixed"]


def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


def picks(obj):
    return [(o, s) for o, subs in obj.References for s in (subs or [""])]


def size_dimension(frame):
    """The PMI diameter on the same faces as the frame (its MMC gives the bonus), or None."""
    from . import pmi_ui
    mine = {(o.Name, s) for o, s in picks(frame)}
    for p in pmi_ui.all_pmi(frame.Document):
        if p.PMIType == "Dimension" and p.DimensionType == "Diameter" and mine & {(o.Name, s) for o, s in picks(p)}:
            return p
    return None


def datum_planes(frame):
    """{letter: (point, outward normal)} of the plane datum features the frame refers to."""
    from . import pmi_ui
    letters = [pmi_ui.parse_datum(d)[0] for d in frame.DatumReferences if d.strip()]
    out = {}
    for p in pmi_ui.all_pmi(frame.Document):
        if p.PMIType == "Datum Feature" and p.Letter.strip().upper() in letters:
            f = pmi_ui.datum_feature(p)
            if f is not None and f[0] == "plane":
                out[p.Letter.strip().upper()] = (App.Vector(*f[1]), App.Vector(*f[2]))
    return letters, out


def coordinates(frame):
    """(axes names, [(u, v)] true positions of the frame's features): u from the secondary datum, v from
    the tertiary, both measured into the material, in the plane of the primary."""
    letters, planes = datum_planes(frame)
    if len(letters) < 3 or any(x not in planes for x in letters[:3]):
        raise ValueError(f"{frame.Label}: needs three plane datums (primary, secondary, tertiary) with datum feature "
                         f"symbols; it has {'|'.join(letters) or 'none'}")
    (_, na), (b0, nb), (c0, nc) = (planes[x] for x in letters[:3])
    u = -(nb - na * nb.dot(na))
    u.normalize()
    w = -(nc - na * nc.dot(na) - u * nc.dot(u))
    w.normalize()
    out = []
    for o, s in picks(frame):
        shape = refs.resolve(o, s)
        if refs.surface_kind(shape) not in ("cylinder", "circle"):
            raise ValueError(f"{frame.Label}: {refs.describe(o, s)} is not a hole or a pin")
        c, _ = refs.cylinder_axis(shape)
        out.append(((c - b0).dot(u), (c - c0).dot(w)))
    return (f"from {letters[1]}", f"from {letters[2]}"), out


def parse_rows(lines):
    rows = []
    for ln in lines:
        vals = [float(v) for v in ln.replace(",", " ").replace(";", " ").split()]
        if len(vals) != 3:
            raise ValueError(f"'{ln}': give the two positions and the size")
        rows.append(tuple(vals))
    return rows


class PositionEvaluationFeature:
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g = GROUP
        _prop(obj, "App::PropertyLink", "Frame", g, "The PMI position frame of the pattern")
        _prop(obj, "App::PropertyLink", "Size", g, "The PMI diameter of the features (found on the same faces)")
        _prop(obj, "App::PropertyStringList", "Measured", g, "One row per feature, in the frame's order: the two "
              "measured positions (from the secondary and the tertiary datum) and the size, mm")
        _prop(obj, "App::PropertyEnumeration", "LowerMotion", g, "How the lower row's zones may move to fit the "
              "measured pattern (from its datums: a composite row repeating only the primary translates and turns)")
        if not obj.getEnumerationsOfProperty("LowerMotion"):
            obj.LowerMotion = MOTIONS
            obj.LowerMotion = "From datums"
        r = "Result"
        _prop(obj, "App::PropertyStringList", "Basic", r, "True positions from the model (mm)", mode=1)
        _prop(obj, "App::PropertyFloat", "UpperUsed", r, "Share of the pattern-locating zone used (%)", mode=1)
        _prop(obj, "App::PropertyFloat", "LowerUsed", r, "Share of the feature-relating zone used after the best "
              "fit (%)", mode=1)
        _prop(obj, "App::PropertyString", "Verdict", r, "Accept or reject", mode=1)
        _prop(obj, "App::PropertyString", "Report", r, "The full evaluation", mode=1)
        _prop(obj, "App::PropertyLinkList", "PMI", r, "The PMI it reads (keeps it up to date)", mode=2)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        try:
            evaluate(obj)
        except Exception as e:
            obj.Verdict = f"error: {e}"
            obj.Report = obj.Verdict


def motions(obj, a):
    m = obj.LowerMotion
    if m == "Translate and turn":
        return position_eval.TRANSLATE_ROTATE
    if m == "Translate only":
        return position_eval.TRANSLATE
    if m == "Fixed":
        return ()
    low = pmi.lower(a) or {}
    return position_eval.motions_for(low.get("datums", []), a.get("frame", "composite"))


def evaluate(obj):
    from . import pmi_ui
    frame = obj.Frame
    if frame is None or getattr(frame, "PMIType", "") != "Feature Control Frame" or frame.Characteristic != "Position":
        raise ValueError("needs a PMI position frame")
    if obj.Size is None:
        obj.Size = size_dimension(frame)
    obj.PMI = [x for x in (frame, obj.Size) if x is not None]
    a = pmi_ui.semantic(frame)
    axes, basics = coordinates(frame)
    obj.Basic = [f"{u:.4f} {v:.4f}" for u, v in basics]
    measured = parse_rows([ln for ln in obj.Measured if ln.strip()])
    if len(measured) != len(basics):
        raise ValueError(f"{len(basics)} features in the frame, {len(measured)} measured rows")
    _, general = pmi_ui.settings(obj.Document)
    mmc = lmc = None
    internal = True
    if obj.Size is not None:
        sa = pmi_ui.semantic(obj.Size)
        mmc, lmc = pmi.mmc_lmc(sa, general)
        internal = pmi.internal(sa)
    elif a.get("modifier") or (pmi.lower(a) or {}).get("modifier"):
        raise ValueError("the frame is at MMC or LMC but its features have no PMI diameter: the bonus is unknown")
    feats = [{"basic": b, "actual": (m[0], m[1]), "size": m[2]} for b, m in zip(basics, measured)]
    low = pmi.lower(a)
    r = position_eval.evaluate(feats, a["tolerance"], a.get("modifier", ""), mmc=mmc, lmc=lmc, internal=internal,
                               lower=low, lower_motions=motions(obj, a) if low else None)
    obj.UpperUsed = 100 * r["upper_utilisation"]
    obj.LowerUsed = 100 * r.get("lower_utilisation", 0.0)
    bad_size = [i + 1 for i, f in enumerate(r["features"]) if not f["size_ok"]]
    obj.Verdict = ("ACCEPT" if r["pass"] else "REJECT") + (f" (size out of limits: feature {bad_size})" if bad_size
                                                          else "")
    primary = pmi_ui.parse_datum(frame.DatumReferences[0])[0]
    head = [obj.Label, f"Frame: {frame.Callout}",
            f"Positions {axes[0]} and {axes[1]} (mm), in the plane of datum {primary}"]
    if obj.Size is not None:
        head.append(f"Size: {obj.Size.Callout} (MMC {mmc:.4f}, LMC {lmc:.4f})")
    if low:
        moves = {position_eval.TRANSLATE_ROTATE: "translate and turn", position_eval.TRANSLATE: "translate only",
                 (): "fixed"}.get(tuple(motions(obj, a)), str(motions(obj, a)))
        head.append(f"Lower row zones may {moves} ({obj.LowerMotion.lower()})")
    obj.Report = "\n".join(head + ["", position_eval.report(r)])
    last.update(report=obj.Report, result=r)


last = {}


class PositionEvaluationPanel:
    def __init__(self, obj, new=False):
        self.obj, self.new = obj, new
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Position Evaluation")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.addWidget(QtWidgets.QLabel(f"Frame: {obj.Frame.Callout}"))
        try:
            axes, basics = coordinates(obj.Frame)
        except ValueError as e:
            axes, basics = ("u", "v"), []
            lay.addWidget(QtWidgets.QLabel(str(e)))
        self.table = QtWidgets.QTableWidget(len(basics), 5)
        self.table.setObjectName("measurements")
        self.table.setHorizontalHeaderLabels([f"True {axes[0]}", f"True {axes[1]}", f"Measured {axes[0]}",
                                              f"Measured {axes[1]}", "Size"])
        try:
            measured = parse_rows([ln for ln in obj.Measured if ln.strip()])
        except ValueError:
            measured = []
        size0 = ""
        if obj.Frame is not None and (obj.Size or size_dimension(obj.Frame)) is not None:
            from . import pmi_ui
            size0 = f"{pmi.mmc_lmc(pmi_ui.semantic(obj.Size or size_dimension(obj.Frame)))[0]:.4f}"
        for i, (u, v) in enumerate(basics):
            row = measured[i] if i < len(measured) else (u, v, float(size0) if size0 else 0.0)
            for j, val in enumerate((u, v) + tuple(row)):
                item = QtWidgets.QTableWidgetItem(f"{val:.4f}")
                if j < 2:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(i, j, item)
        lay.addWidget(self.table)
        form = QtWidgets.QFormLayout()
        self.motion = QtWidgets.QComboBox()
        self.motion.setObjectName("lowerMotion")
        self.motion.addItems(MOTIONS)
        self.motion.setCurrentText(obj.LowerMotion)
        form.addRow("Lower row zones", self.motion)
        lay.addLayout(form)
        note = QtWidgets.QLabel("Measured positions from the datums, in the plane of the primary, as a CMM reports "
                                "them; sizes give the bonus at MMC. Cogorno, GD&T for Mechanical Design, ch. 13.")
        note.setWordWrap(True)
        lay.addWidget(note)

    def rows(self):
        out = []
        for i in range(self.table.rowCount()):
            vals = []
            for j in (2, 3, 4):
                it = self.table.item(i, j)
                vals.append((it.text() if it else "0").strip().replace(",", "."))
            out.append(" ".join(vals))
        return out

    def accept(self):
        from .commands import show_information
        doc = self.obj.Document
        self.obj.Measured = self.rows()
        self.obj.LowerMotion = self.motion.currentText()
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


class PositionEvaluationView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return config.resource("icons", "position_evaluation.svg")

    def setEdit(self, vobj, mode=0):
        vobj.Object.Document.openTransaction("Position Evaluation")
        Gui.Control.showDialog(PositionEvaluationPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        return self.setEdit(vobj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create(frame, doc=None, **values):
    doc = doc or App.ActiveDocument
    obj = doc.addObject("App::FeaturePython", "PositionEvaluation")
    PositionEvaluationFeature(obj)
    obj.Label = "Position Evaluation"
    obj.Frame = frame
    obj.Size = size_dimension(frame)
    try:
        _, basics = coordinates(frame)
    except ValueError:
        basics = []
    if "Measured" not in values and obj.Size is not None:      # start from perfect features at MMC
        from . import pmi_ui
        mmc = pmi.mmc_lmc(pmi_ui.semantic(obj.Size))[0]
        obj.Measured = [f"{u:.4f} {v:.4f} {mmc:.4f}" for u, v in basics]
    for k, v in values.items():
        setattr(obj, k, v)
    if App.GuiUp:
        PositionEvaluationView(obj.ViewObject)
    doc.recompute()
    return obj


class PositionEvaluation:
    def GetResources(self):
        return {"MenuText": "Position Evaluation",
                "ToolTip": "Does a measured hole or pin pattern meet its position frame? The upper row against the "
                           "datums, the lower row of a composite frame best-fit; with the bonus from the sizes. "
                           "Select the PMI position frame first",
                "Pixmap": config.resource("icons", "position_evaluation.svg")}

    @staticmethod
    def _frame():
        from . import pmi_ui
        sel = [o for o in Gui.Selection.getSelection() if isinstance(getattr(o, "Proxy", None), pmi_ui.PMIFeature)
               and o.PMIType == "Feature Control Frame" and o.Characteristic == "Position"]
        return sel[0] if len(sel) == 1 else None

    def IsActive(self):
        return self._frame() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        frame = self._frame()
        doc.openTransaction("Position Evaluation")
        try:
            coordinates(frame)
        except ValueError as e:
            doc.abortTransaction()
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Position Evaluation", str(e))
            return
        obj = create(frame, doc)
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(PositionEvaluationPanel(obj, new=True))


COMMANDS = {"NXStyle_PositionEvaluation": PositionEvaluation()}

# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's Assembly Clearance and Simple Interference.

A Clearance Set is saved in the assembly (or layout) document, so the same check runs again after
every design change: the objects to analyse (all solids, the selected ones, or two collections
checked against each other), a default clearance zone, and pair rules (exclude a pair, or give it its
own zone). Perform Analysis classifies every pair as hard, containment, touching or soft interference
(clearance_core) and the Clearance Browser lists them with distance, penetration depth and status
against the previous run (New, Unchanged, Changed, Gone). Study Interference isolates one pair with
its interference volume; Restore Visibility brings the rest back.

Penetration depth here is the smallest extent of the interference volume, measured along its
principal axes: for two overlapping blocks, how far one has to move out of the other.
"""

import json

import FreeCAD as App
import FreeCADGui as Gui

from . import clearance_core as cc
from . import config
from .qt import QtCore, QtWidgets

COLUMNS = ["Object 1", "Object 2", "Interference", "Distance", "Zone", "Penetration", "Volume mm³", "Status"]
RESULT = "ClearanceInterferences"


def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


class ClearanceSet:
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g = "Clearance Set"
        _prop(obj, "App::PropertyLinkList", "Objects", g, "Objects to analyse (empty: every solid in the document)")
        _prop(obj, "App::PropertyLinkList", "SecondObjects", g,
              "With objects here, Objects are checked against these only (two collections)")
        _prop(obj, "App::PropertyLength", "ClearanceZone", g, "Default clearance zone: closer pairs are soft "
              "interferences", 0.0)
        _prop(obj, "App::PropertyStringList", "PairRules", g,
              "One per line: 'A|B=exclude' leaves a pair out, 'A|B=0.5' gives it its own zone (object labels)")
        _prop(obj, "App::PropertyBool", "IgnoreTouching", g, "Do not report touching pairs (mating faces)", False)
        _prop(obj, "App::PropertyStringList", "Results", "Results", "One JSON line per interference", mode=2)
        _prop(obj, "App::PropertyStringList", "Previous", "Results", "The run before (for New / Gone)", mode=2)
        for k in cc.KINDS:
            _prop(obj, "App::PropertyInteger", k.capitalize(), "Results", f"{k} interferences found", 0, mode=1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass                       # analysis runs on request (Perform Analysis), as in NX

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ClearanceSetView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return config.resource("icons", "clearance.svg")

    def doubleClicked(self, vobj):
        Gui.Control.showDialog(BrowserPanel(vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def sets(doc):
    return [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), ClearanceSet)]


def create(doc=None, objects=(), second=(), zone=0.0, label="Clearance Set"):
    doc = doc or App.ActiveDocument
    obj = doc.addObject("App::FeaturePython", "ClearanceSet")
    ClearanceSet(obj)
    obj.Objects = list(objects)
    obj.SecondObjects = list(second)
    obj.ClearanceZone = zone
    obj.Label = label
    if App.GuiUp:
        ClearanceSetView(obj.ViewObject)
    return obj


# ------------------------------------------------------------------ geometry
def solid_of(o):
    from . import claims
    s = claims.global_shape(o)
    return s if not s.isNull() and s.Solids else None


def candidates(doc):
    """Every solid of the document a clearance check is about (see claims.parts)."""
    from . import claims
    return [o for o, _ in claims.parts(doc) if not o.Name.startswith((RESULT, "Interference"))]


def penetration(common):
    """Smallest extent of the interference volume along its principal axes (mm): the volume is turned
    so those axes are X, Y, Z and its exact (optimal) bounding box measured. Sampling points on its edges
    instead came out short on round interferences (3.94 for a Ø4 one)."""
    try:
        solid = common.Solids[0] if len(common.Solids) == 1 else common
        props = solid.PrincipalProperties
        x, y = App.Vector(props["FirstAxisOfInertia"]), App.Vector(props["SecondAxisOfInertia"])
        z = x.cross(y)
        m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, z.x, z.y, z.z, 0, 0, 0, 0, 1)   # rows: the axes
        s = common.copy()
        s.transformShape(m)
        try:
            bb = s.optimalBoundingBox(False, False)
        except Exception:
            bb = s.BoundBox
        return min(bb.XLength, bb.YLength, bb.ZLength)
    except Exception:
        bb = common.BoundBox
        return min(bb.XLength, bb.YLength, bb.ZLength)


def analyse_pair(a, b, sa, sb, zone):
    """dict for one pair, or None when they are clear."""
    if sa.BoundBox.isValid() and sb.BoundBox.isValid():
        ga = App.BoundBox(sa.BoundBox)
        ga.enlarge(zone + 1e-3)
        if not ga.intersect(sb.BoundBox):
            return None
    common = sa.common(sb)
    cv = common.Volume if not common.isNull() else 0.0
    dist = 0.0 if cv > cc.VOLUME_TOL else sa.distToShape(sb)[0]
    kind = cc.classify(dist, cv, sa.Volume, sb.Volume, zone)
    if kind is None:
        return None
    row = {"a": a.Label, "b": b.Label, "a_name": a.Name, "b_name": b.Name, "kind": kind, "distance": dist,
           "zone": zone, "volume": cv, "penetration": penetration(common) if cv > cc.VOLUME_TOL else 0.0}
    return row, (common if cv > cc.VOLUME_TOL else None)


def perform(cset):
    """Run the analysis of a clearance set; writes its Results and returns (rows, interference solids)."""
    import Part
    doc = cset.Document
    doc.recompute()
    first = list(cset.Objects) or candidates(doc)
    second = list(cset.SecondObjects)
    rules = cc.parse_rules(cset.PairRules)
    shapes = {o.Name: solid_of(o) for o in first + second}
    pairs = []
    if second:
        pairs = [(a, b) for a in first for b in second if a is not b]
    else:
        pairs = [(a, b) for i, a in enumerate(first) for b in first[i + 1:]]
    rows, solids = [], []
    for a, b in pairs:
        sa, sb = shapes.get(a.Name), shapes.get(b.Name)
        if sa is None or sb is None:
            continue
        rule = rules.get(cc.pair_key(a.Label, b.Label))
        if rule == "exclude":
            continue
        zone = float(rule) if isinstance(rule, float) else float(cset.ClearanceZone)
        res = analyse_pair(a, b, sa, sb, zone)
        if res is None:
            continue
        row, common = res
        if row["kind"] == "touching" and cset.IgnoreTouching:
            continue
        rows.append(row)
        if common is not None:
            solids.append(common)
    previous = {}
    for line in cset.Results:
        try:
            r = json.loads(line)
            previous[cc.pair_key(r["a_name"], r["b_name"])] = r["kind"]
        except (ValueError, KeyError):
            continue
    current = {cc.pair_key(r["a_name"], r["b_name"]): r["kind"] for r in rows}
    st = cc.status(previous, current)
    for r in rows:
        r["status"] = st[cc.pair_key(r["a_name"], r["b_name"])]
    gone = [k for k, s in st.items() if s == "Gone"]
    cset.Previous = list(cset.Results)
    cset.Results = [json.dumps(r, sort_keys=True) for r in rows] + \
        [json.dumps({"gone": k}) for k in gone]
    for k in cc.KINDS:
        setattr(cset, k.capitalize(), sum(1 for r in rows if r["kind"] == k))
    res = doc.getObject(RESULT)
    if solids:
        res = res or doc.addObject("Part::Feature", RESULT)
        res.Label = "Clearance interferences"
        res.Shape = Part.makeCompound(solids)
        if getattr(res, "ViewObject", None) is not None:
            res.ViewObject.ShapeColor = (0.92, 0.05, 0.05)
            res.ViewObject.LineColor = (0.6, 0.0, 0.0)
    elif res is not None:
        doc.removeObject(res.Name)
    return rows, solids


def results_of(cset):
    rows, gone = [], []
    for line in cset.Results:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        (gone if "gone" in r else rows).append(r)
    return rows, gone


def report(cset):
    rows, gone = results_of(cset)
    lines = [f"Assembly clearance: {cset.Label}",
             f"Default clearance zone {float(cset.ClearanceZone):g} mm; " + ", ".join(
                 f"{getattr(cset, k.capitalize())} {k}" for k in cc.KINDS), ""]
    lines.append(f"{'Object 1':<22} {'Object 2':<22} {'Interference':<12} {'Distance':>9} {'Penetration':>11} "
                 f"{'Volume mm³':>11}  Status")
    for r in sorted(rows, key=lambda r: (cc.KINDS.index(r["kind"]), -r["volume"], r["distance"])):
        lines.append(f"{r['a'][:22]:<22} {r['b'][:22]:<22} {r['kind']:<12} {r['distance']:>9.3f} "
                     f"{r['penetration']:>11.3f} {r['volume']:>11.1f}  {r['status']}")
    for k in gone:
        lines.append(f"  gone since the last run: {k}")
    if not rows:
        lines.append("No interferences.")
    return "\n".join(lines)


# ------------------------------------------------------------------ the browser
class BrowserPanel:
    """Clearance Browser: the set's settings, Perform Analysis, the interferences by kind."""

    def __init__(self, cset):
        self.cset = cset
        self.doc = cset.Document
        self.hidden = []
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Clearance Browser")
        self.form.setObjectName("ClearanceBrowser")
        lay = QtWidgets.QVBoxLayout(self.form)
        top = QtWidgets.QFormLayout()
        self.zone = QtWidgets.QDoubleSpinBox()
        self.zone.setObjectName("clearanceZone")
        self.zone.setRange(0, 1000)
        self.zone.setDecimals(3)
        self.zone.setSuffix(" mm")
        self.zone.setValue(float(cset.ClearanceZone))
        self.touching = QtWidgets.QCheckBox("Ignore touching pairs")
        self.touching.setObjectName("ignoreTouching")
        self.touching.setChecked(bool(cset.IgnoreTouching))
        what = (f"{len(cset.Objects)} selected objects" if cset.Objects else "every solid in the document")
        if cset.SecondObjects:
            what += f" against {len(cset.SecondObjects)} others"
        top.addRow("Set", QtWidgets.QLabel(f"{cset.Label}: {what}"))
        top.addRow("Default clearance zone", self.zone)
        top.addRow("", self.touching)
        lay.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        for name, text, fn in (("performAnalysis", "Perform Analysis", self.run),
                               ("studyInterference", "Study Interference", self.study),
                               ("restoreVisibility", "Restore Visibility", self.restore),
                               ("excludePair", "Exclude Pair", self.exclude)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setObjectName("clearanceTree")
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setMinimumHeight(260)
        self.tree.setRootIsDecorated(True)
        lay.addWidget(self.tree)
        self.summary = QtWidgets.QLabel()
        self.summary.setObjectName("clearanceSummary")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.fill()

    def fill(self):
        self.tree.clear()
        rows, gone = results_of(self.cset)
        for k in cc.KINDS:
            mine = [r for r in rows if r["kind"] == k]
            top = QtWidgets.QTreeWidgetItem([f"{k.capitalize()} interference ({len(mine)})"])
            self.tree.addTopLevelItem(top)
            for r in sorted(mine, key=lambda r: (-r["volume"], r["distance"])):
                it = QtWidgets.QTreeWidgetItem([r["a"], r["b"], k, f"{r['distance']:.3f}", f"{r['zone']:g}",
                                                f"{r['penetration']:.3f}", f"{r['volume']:.1f}", r["status"]])
                it.setData(0, QtCore.Qt.UserRole, json.dumps(r))
                top.addChild(it)
            top.setExpanded(True)
        for i in range(len(COLUMNS)):
            self.tree.resizeColumnToContents(i)
        self.summary.setText(", ".join(f"{getattr(self.cset, k.capitalize())} {k}" for k in cc.KINDS) +
                             (f"; {len(gone)} gone since the last run" if gone else ""))

    def run(self, *_):
        self.cset.ClearanceZone = self.zone.value()
        self.cset.IgnoreTouching = self.touching.isChecked()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            perform(self.cset)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.doc.recompute()
        self.fill()

    def current(self):
        it = self.tree.currentItem()
        data = it.data(0, QtCore.Qt.UserRole) if it is not None else None
        return json.loads(data) if data else None

    def study(self, *_):
        """Show only the selected pair and the interference volume between them (NX: Study Interference)."""
        r = self.current()
        if r is None:
            return
        keep = {r["a_name"], r["b_name"], RESULT}
        for o in self.doc.Objects:
            vo = getattr(o, "ViewObject", None)
            if vo is None or not vo.Visibility or o.Name in keep or not o.isDerivedFrom("App::GeoFeature"):
                continue
            container = o.isDerivedFrom("App::Part") or o.isDerivedFrom("PartDesign::Body") or o.TypeId == "App::Link"
            if container and any(p.Name in keep for p in o.OutList):     # hiding it would hide the pair too
                continue
            vo.Visibility = False
            self.hidden.append(o.Name)
        Gui.Selection.clearSelection()
        for n in (r["a_name"], r["b_name"]):
            Gui.Selection.addSelection(self.doc.Name, n)
        try:
            Gui.SendMsgToActiveView("ViewSelection")
        except Exception:
            pass

    def restore(self, *_):
        for n in self.hidden:
            o = self.doc.getObject(n)
            if o is not None and getattr(o, "ViewObject", None) is not None:
                o.ViewObject.Visibility = True
        self.hidden = []

    def exclude(self, *_):
        r = self.current()
        if r is None:
            return
        self.cset.PairRules = list(self.cset.PairRules) + [f"{r['a']}|{r['b']}=exclude"]
        self.run()

    def accept(self):
        self.restore()
        Gui.Control.closeDialog()
        from .commands import show_information
        show_information(report(self.cset))
        return True

    def reject(self):
        self.restore()
        Gui.Control.closeDialog()
        return True


# ------------------------------------------------------------------ commands
class ClearanceAnalysis:
    def GetResources(self):
        return {"MenuText": "Clearance Analysis",
                "ToolTip": "NX Assembly Clearance: a clearance set saved in the part (selected objects, or every "
                           "solid), a clearance zone, hard, containment, touching and soft interferences, and the "
                           "Clearance Browser. Select a clearance set to run it again",
                "Pixmap": config.resource("icons", "clearance.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        sel = Gui.Selection.getSelection()
        chosen = [o for o in sel if isinstance(getattr(o, "Proxy", None), ClearanceSet)]
        if chosen:
            cset = chosen[0]
        else:
            objs = [o for o in sel if solid_of_safe(o)]
            doc.openTransaction("Clearance Set")
            cset = create(doc, objs, label=f"Clearance Set {len(sets(doc)) + 1}")
            doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(BrowserPanel(cset))


def solid_of_safe(o):
    try:
        return solid_of(o) is not None
    except Exception:
        return False


last = {}


class SimpleInterference:
    def GetResources(self):
        return {"MenuText": "Simple Interference",
                "ToolTip": "Do the two selected bodies interfere? Hard interference makes a body of the common "
                           "volume (NX: Analysis > Simple Interference)",
                "Pixmap": config.resource("icons", "simple_interference.svg")}

    def IsActive(self):
        return len([o for o in Gui.Selection.getSelection() if solid_of_safe(o)]) == 2

    def Activated(self):
        from .commands import show_information
        a, b = [o for o in Gui.Selection.getSelection() if solid_of_safe(o)][:2]
        res = analyse_pair(a, b, solid_of(a), solid_of(b), 0.0)
        doc = a.Document
        if res is None:
            text = f"{a.Label} and {b.Label}: no interference (distance {solid_of(a).distToShape(solid_of(b))[0]:.3f} mm)"
        else:
            r, common = res
            text = (f"{a.Label} and {b.Label}: {r['kind']} interference" +
                    (f", volume {r['volume']:.2f} mm³, penetration {r['penetration']:.3f} mm" if common is not None else ""))
            if common is not None:
                doc.openTransaction("Simple Interference")
                body = doc.addObject("Part::Feature", "Interference")
                body.Shape = common
                if getattr(body, "ViewObject", None) is not None:
                    body.ViewObject.ShapeColor = (0.92, 0.05, 0.05)
                doc.commitTransaction()
        last["text"] = text
        show_information(text)


COMMANDS = {"NXStyle_ClearanceAnalysis": ClearanceAnalysis(), "NXStyle_SimpleInterference": SimpleInterference()}

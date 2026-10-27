# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's primitive solids: Block, Cylinder, Cone and Sphere, with NX's dialog and Boolean.

Each is a PartDesign primitive (AdditiveBox, SubtractiveCylinder, ...): a feature in a Body, so the part stays
history-based and Edit Parameters reopens the same dialog. The NX point and axis become the feature's Placement;
the Boolean picks the backend (primitive_core.plan):

- None: an additive primitive in a new Body (in the work Body while it has no solid yet);
- Unite / Subtract: an additive / subtractive primitive in the target Body;
- Intersect: an additive primitive in a new tool Body, and a PartDesign Boolean (Common) in the target Body.

The panel holds the whole command in one undo transaction: OK (or MB2) commits one step named after the
command, Apply commits it and starts the next, Cancel or Esc leaves nothing. The Point dialog's type and its
XC, YC, ZC fields are part of the panel; a pick in the graphics window goes to the highlighted step (the point,
or the target body) and snaps by the Point type. Typed lengths keep their decimals (precise_input).
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, precise_input, primitive_core as core, selection_filter as sf
from .qt import QtCore, QtWidgets
from .quantity_core import decimals_needed

HISTORY = []                     # one dict per ended command (read by the self-test and the tutorial replay)
TRACE = []                       # the last lifecycle events, for the self-test and bug reports
_remembered = {}                 # command -> the values NX keeps for the next time the dialog opens
_current = {"panel": None}

ACTIVE_STYLE = "background-color: #FBE7A1; border-radius: 3px;"
STYLE = {"error": "color: #B00020;", "warning": "color: #8A5A00;", "ok": "color: #0B6E79;"}

TIPS = {
    "Block": "Block: a box from an origin and edge lengths, two diagonal points, or a height and two points; "
             "Boolean None, Unite, Subtract or Intersect (NX: More > Design Feature > Block)",
    "Cylinder": "Cylinder: an axis vector, a point, a diameter and a height; Boolean None, Unite, Subtract or "
                "Intersect (NX: More > Design Feature > Cylinder)",
    "Cone": "Cone: an axis vector, a point, base and top diameters and a height; Boolean None, Unite, Subtract or "
            "Intersect (NX: More > Design Feature > Cone)",
    "Sphere": "Sphere: a centre point and a diameter; Boolean None, Unite, Subtract or Intersect "
              "(NX: More > Design Feature > Sphere)",
}


def current():
    """The open primitive panel, or None."""
    return _current["panel"]


def log(text):
    import time
    TRACE.append(f"{time.strftime('%H:%M:%S')} {text}")
    del TRACE[:-80]


def _int(e):
    try:
        return int(e)
    except TypeError:
        return e.value


def _alive(w):
    from .controller import _alive as alive
    return alive(w)


def solid_tip(body):
    from .controller import solid_tip as tip
    return tip(body)


def body_of(obj):
    from .controller import body_of as of
    return of(obj)


# ------------------------------------------------------------------ fields
def quantity_field(name, minimum=-1e7):
    """FreeCAD's quantity field in mm (typed inches are converted; precise_input keeps the decimals)."""
    w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    w.setObjectName(name)
    w.setProperty("unit", "mm")
    w.setProperty("minimum", float(minimum))
    w.setProperty("maximum", 1e7)
    return w


def set_mm(w, value):
    """Show value with the decimals it needs (FreeCAD reads its own text back as the value)."""
    q = App.Units.Quantity(float(value), App.Units.Length)
    need = min(max(decimals_needed(value), precise_input.preference_decimals()), precise_input.RESTORE_DECIMALS)
    precise_input.show_with(w, q, need)


def mm(w):
    v = w.property("rawValue")
    return float(v) if isinstance(v, (int, float)) else None


# ------------------------------------------------------------------ point snapping
def center_of(shape, picked):
    """The centre of a circle, arc or ellipse edge, of a sphere face, or of the circular edge of a planar face
    nearest to the picked point; None for anything else."""
    import Part
    if shape.ShapeType == "Edge":
        curve = getattr(shape, "Curve", None)
        if type(curve).__name__ in ("Circle", "Ellipse", "ArcOfCircle", "ArcOfEllipse"):
            return curve.Center
        return None
    if shape.ShapeType == "Face":
        surface = shape.Surface
        if type(surface).__name__ == "Sphere":
            return surface.Center
        if type(surface).__name__ == "Plane":
            circles = [e for e in shape.Edges if type(getattr(e, "Curve", None)).__name__ in ("Circle", "Ellipse")]
            if circles:
                v = Part.Vertex(picked)
                return min(circles, key=lambda e: e.distToShape(v)[0]).Curve.Center
    return None


def snap(kind, shape, picked):
    """The point a pick gives for the NX Point type, or CommandError with the reason."""
    import Part
    st = shape.ShapeType
    if kind == "Existing Point":
        if st == "Vertex":
            return shape.Point
        raise core.CommandError("Existing Point takes a point: pick a vertex")
    if kind == "End Point":
        if st == "Vertex":
            return shape.Point
        if st == "Edge":
            return min((v.Point for v in shape.Vertexes), key=lambda p: (p - picked).Length)
        raise core.CommandError("End Point takes an edge or a vertex")
    if kind == "Arc/Ellipse/Sphere Center":
        c = center_of(shape, picked)
        if c is None:
            raise core.CommandError("Arc/Ellipse/Sphere Center takes an arc, a circle, an ellipse, a sphere, "
                                    "or a flat face bounded by a circle")
        return c
    if kind == "Point on Curve/Edge":
        if st != "Edge":
            raise core.CommandError("Point on Curve/Edge takes an edge")
        return shape.distToShape(Part.Vertex(picked))[1][0][0]
    if kind == "Point on Face":
        if st != "Face":
            raise core.CommandError("Point on Face takes a face")
        return shape.distToShape(Part.Vertex(picked))[1][0][0]
    # Inferred Point (and each pick of Between Two Points): what the pick most likely means
    if st == "Vertex":
        return shape.Point
    c = center_of(shape, picked) if st == "Edge" or type(getattr(shape, "Surface", None)).__name__ == "Sphere" \
        else None
    if c is not None:
        return c
    if st == "Edge" and shape.Vertexes:
        return min((v.Point for v in shape.Vertexes), key=lambda p: (p - picked).Length)
    if st == "Face":
        return shape.distToShape(Part.Vertex(picked))[1][0][0]
    raise core.CommandError("pick a point, an edge or a face")


# ------------------------------------------------------------------ widgets
class Step(QtWidgets.QFrame):
    """A selection step (NX's 'Specify Point', 'Select Body'): the highlighted one takes the next pick."""

    def __init__(self, panel, key, label):
        super().__init__()
        self.panel, self.key = panel, key
        self.setObjectName(f"nxStep_{key}")
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(4, 3, 4, 3)
        row = QtWidgets.QHBoxLayout()
        self.button = QtWidgets.QToolButton()
        self.button.setObjectName(f"{key}Select")
        self.button.setText(label)
        self.button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.button.setAutoRaise(True)
        self.button.setToolTip("Make this the step that takes the next pick in the graphics window")
        self.button.clicked.connect(lambda: panel.activate(key))
        self.status = QtWidgets.QLabel()
        self.status.setObjectName(f"{key}Status")
        row.addWidget(self.button)
        row.addWidget(self.status, 1)
        self.lay.addLayout(row)

    def set_active(self, on):
        self.setStyleSheet(f"#{self.objectName()} {{ {ACTIVE_STYLE} }}" if on else "")


class PointStep(Step):
    """NX's Point dialog in the panel: the type, what was picked, and the XC, YC, ZC output coordinates."""

    def __init__(self, panel, key, label):
        super().__init__(panel, key, label)
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName(f"{key}PointType")
        self.type.setAccessibleName("Point type")
        self.type.addItems(core.POINT_TYPES)
        self.type.activated.connect(lambda _i: self._type_changed())
        form = QtWidgets.QFormLayout()
        form.addRow("Type", self.type)
        self.fields = []
        for axis in ("XC", "YC", "ZC"):
            w = quantity_field(f"{key}{axis}")
            set_mm(w, 0.0)
            form.addRow(axis, w)
            self.fields.append(w)
        self.lay.addLayout(form)
        self.pending = []                # Between Two Points: the first point, waiting for the second
        self.picked = 0
        self.message = ""
        self.refresh()

    def _type_changed(self):
        self.pending = []
        self.message = ""
        self.panel.activate(self.key)
        self.refresh()

    def point(self):
        vals = [mm(w) for w in self.fields]
        return tuple(vals) if all(v is not None for v in vals) else None

    def set_point(self, p):
        for w, v in zip(self.fields, (p[0], p[1], p[2])):
            set_mm(w, float(v))

    def take(self, shape, picked):
        """A pick for this step: the snapped point goes into XC, YC, ZC. Returns (ok, reason)."""
        kind = self.type.currentText()
        try:
            p = snap("Inferred Point" if kind == "Between Two Points" else kind, shape, picked)
        except core.CommandError as e:
            self.message = str(e)
            self.refresh(error=True)
            return False, str(e)
        p = (p.x, p.y, p.z)
        if kind == "Between Two Points":
            self.pending.append(p)
            if len(self.pending) < 2:
                self.message = "first point taken: pick the second"
                self.refresh()
                return True, ""
            p = core.midpoint(*self.pending[:2])
            self.pending = []
        self.set_point(p)
        self.picked += 1
        self.message = f"{kind}: {p[0]:g}, {p[1]:g}, {p[2]:g}"
        self.refresh()
        return True, ""

    def refresh(self, error=False):
        n = len(self.pending) if self.type.currentText() == "Between Two Points" else min(self.picked, 1)
        self.status.setText(f"Select Object ({n})" + (f"  {self.message}" if self.message else ""))
        self.status.setStyleSheet(STYLE["error"] if error else "")


class BodyStep(Step):
    """The Boolean's target body: chosen from the list, or picked in the graphics window."""

    def __init__(self, panel):
        super().__init__(panel, "body", "Select Body")
        self.combo = QtWidgets.QComboBox()
        self.combo.setObjectName("nxTargetBody")
        self.combo.setAccessibleName("Target body")
        self.combo.activated.connect(lambda _i: panel.activate("body"))
        self.lay.addWidget(self.combo)

    def fill(self, bodies, chosen):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("-", None)
        for b in bodies:
            self.combo.addItem(b.Label, b.Name)
        i = self.combo.findData(chosen)
        self.combo.setCurrentIndex(i if i >= 0 else 0)
        self.combo.blockSignals(False)

    def chosen(self):
        return self.combo.currentData()

    def choose(self, name):
        i = self.combo.findData(name)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        return i >= 0

    def refresh(self):
        self.status.setText(f"({1 if self.chosen() else 0})")


# ------------------------------------------------------------------ the panel
class PrimitivePanel:
    """The command's task panel and its session: the preview feature lives in an open transaction."""

    def __init__(self, command, feature=None):
        self.command = command
        self.prim = core.PRIMITIVES[command][0]
        self.edit = feature is not None
        self.doc = feature.Document if feature is not None else App.ActiveDocument
        self.name = ("Edit " if self.edit else "") + command
        self.feature_name = feature.Name if feature is not None else None
        self.body_name = self.boolean_name = None
        self.made_body = False
        self.open = False
        self.busy = False
        self.error = None
        self.warnings = []
        self.visibility = {}
        self.base_volume, self.base_solids = 0.0, 0
        self.mode, self.target = "none", None
        self.built = None                 # (mode, target) of the preview that exists
        self.state = None                 # the values last applied to the preview
        self.rotation = None              # Block and Sphere keep the rotation of the feature being edited
        self.committed = []               # features this panel committed (OK and Apply)
        self.work_body = self._work_body()
        self.token = None
        self.timer = None
        self.candidates = []
        self.selection = []
        self.undo_names = list(self.doc.UndoNames) if self.doc is not None else []
        self._form()
        if self.edit:
            self._load(feature)
        else:
            self._defaults()
        self.layer = sf.Layer(command, verdict=self.verdict, alive=lambda: self.open)

    # ------------------------------------------------------------ form
    def _form(self):
        c = self.command
        self.form = QtWidgets.QWidget()
        self.form.setObjectName(f"NX{c}Panel")
        self.form.setWindowTitle(self.name)
        lay = QtWidgets.QVBoxLayout(self.form)
        box = QtWidgets.QGroupBox("Type")
        bl = QtWidgets.QVBoxLayout(box)
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName("nxType")
        self.type.setAccessibleName("Type")
        self.type.addItems(core.PRIMITIVES[c][1])
        not_offered = core.PRIMITIVES[c][2]
        if not_offered:
            self.type.setToolTip("Not offered: " + "; ".join(not_offered))
        self.type.activated.connect(lambda _i: self._type_changed())
        bl.addWidget(self.type)
        lay.addWidget(box)

        self.steps = {}
        self.vector = self.reverse = None
        if c in ("Cylinder", "Cone"):
            box = QtWidgets.QGroupBox("Axis")
            bl = QtWidgets.QVBoxLayout(box)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Specify Vector"))
            self.vector = QtWidgets.QComboBox()
            self.vector.setObjectName("nxVector")
            self.vector.setAccessibleName("Specify Vector")
            for key, d in core.VECTORS:
                self.vector.addItem(key, d)
            row.addWidget(self.vector, 1)
            self.reverse = QtWidgets.QToolButton()
            self.reverse.setObjectName("nxReverse")
            self.reverse.setText("Reverse Direction")
            self.reverse.setCheckable(True)
            row.addWidget(self.reverse)
            bl.addLayout(row)
            self.steps["origin"] = PointStep(self, "origin", "Specify Point")
            bl.addWidget(self.steps["origin"])
            lay.addWidget(box)
        else:
            box = QtWidgets.QGroupBox("Center Point" if c == "Sphere" else "Origin")
            bl = QtWidgets.QVBoxLayout(box)
            self.steps["origin"] = PointStep(self, "origin", "Specify Point")
            bl.addWidget(self.steps["origin"])
            if c == "Block":
                self.point2_box = QtWidgets.QLabel("Point from Origin Corner")
                bl.addWidget(self.point2_box)
                self.steps["point2"] = PointStep(self, "point2", "Specify Point")
                bl.addWidget(self.steps["point2"])
            lay.addWidget(box)

        box = QtWidgets.QGroupBox("Dimension" if c == "Sphere" else "Dimensions")
        self.dim_form = QtWidgets.QFormLayout(box)
        self.dims = {}
        for key, label in core.DIMENSIONS[c]:
            w = quantity_field(key, minimum=0.0)
            self.dim_form.addRow(label, w)
            self.dims[key] = w
        lay.addWidget(box)

        box = QtWidgets.QGroupBox("Boolean")
        bl = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Boolean"))
        self.boolean = QtWidgets.QComboBox()
        self.boolean.setObjectName("nxBoolean")
        self.boolean.setAccessibleName("Boolean")
        for key, label in core.BOOLEANS:
            self.boolean.addItem(label, key)
        self.boolean.activated.connect(lambda _i: self._boolean_changed())
        row.addWidget(self.boolean, 1)
        bl.addLayout(row)
        self.steps["body"] = BodyStep(self)
        bl.addWidget(self.steps["body"])
        lay.addWidget(box)
        if self.edit:
            self.boolean.setEnabled(False)
            self.boolean.setToolTip("Changing the Boolean of an existing primitive is not supported: delete it "
                                    "and make it again")
            self.steps["body"].combo.setEnabled(False)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("nxStatus")
        self.status.setWordWrap(True)
        self.status.setToolTip("\n".join(f"{n}: {s}" + (f" ({how})" if how else "")
                                         for n, s, how in core.OPTIONS))
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.active = "origin"

    def _defaults(self):
        vals = dict(core.DEFAULTS[self.command])
        kept = _remembered.get(self.command, {})
        vals.update(kept.get("dims", {}))
        for key, w in self.dims.items():
            set_mm(w, vals[key])
        if kept.get("type"):
            i = self.type.findText(kept["type"])
            self.type.setCurrentIndex(max(i, 0))
        if self.vector is not None:
            i = self.vector.findText(kept.get("vector", "ZC"))
            self.vector.setCurrentIndex(max(i, 0))
            self.reverse.setChecked(bool(kept.get("reverse")))
        self.candidates = self._candidates()
        self.target = self._default_target()
        self.steps["body"].fill(self.candidates, self.target)
        self._type_changed(rebuild=False)

    def _load(self, feature):
        """Edit Parameters: the dialog shows the feature as it is."""
        body = body_of(feature)
        sense = core.command_of(feature.TypeId)[1]
        props = {p: getattr(feature, p).Value for p in ("Length", "Width", "Height", "Radius", "Radius1", "Radius2")
                 if p in feature.PropertiesList}
        for key, value in core.dimensions_of(self.command, props).items():
            set_mm(self.dims[key], value)
        glob = body.getGlobalPlacement().multiply(feature.Placement)
        self.steps["origin"].set_point((glob.Base.x, glob.Base.y, glob.Base.z))
        if self.vector is not None:
            d = glob.Rotation.multVec(App.Vector(0, 0, 1))
            key = core.vector_key((d.x, d.y, d.z))
            if key is None:
                self.vector.addItem("As built", (d.x, d.y, d.z))
                self.vector.setCurrentIndex(self.vector.count() - 1)
            else:
                self.vector.setCurrentIndex(self.vector.findText(key))
        else:
            self.rotation = glob.Rotation
        boolean = self._common_of(body)
        if sense == "subtractive":
            self.mode, target = "subtract", body
        elif boolean is not None:
            self.mode, target = "intersect", body_of(boolean)
            self.boolean_name = boolean.Name
        elif getattr(feature, "BaseFeature", None) is not None:
            self.mode, target = "unite", body
        else:
            self.mode, target = "none", None
        self.target = target.Name if target is not None else None
        self.body_name = body.Name
        self.candidates = [target] if target is not None else []
        self.steps["body"].fill(self.candidates, self.target)
        self.boolean.setCurrentIndex(self.boolean.findData(self.mode))
        self.built = (self.mode, self.target)
        self._type_changed(rebuild=False)

    @staticmethod
    def _common_of(body):
        return next((o for o in body.InList if o.TypeId == "PartDesign::Boolean" and o.Type == "Common"), None)

    # ------------------------------------------------------------ bodies
    def _work_body(self):
        try:
            b = Gui.getDocument(self.doc.Name).ActiveView.getActiveObject("pdbody")
        except Exception:
            b = None
        if b is None:
            bodies = [o for o in self.doc.Objects if o.isDerivedFrom("PartDesign::Body")]
            b = bodies[0] if len(bodies) == 1 else None
        return b

    def _candidates(self):
        """Bodies a Boolean can work on: those with a solid, not the preview's own."""
        mine = {self.body_name} if self.made_body else set()
        return [o for o in self.doc.Objects if o.isDerivedFrom("PartDesign::Body") and o.Name not in mine
                and o.Visibility is not False and solid_tip(o) is not None]

    def _default_target(self):
        """The only body there is, as NX selects it by itself; with several, the target is asked for."""
        return self.candidates[0].Name if len(self.candidates) == 1 else None

    # ------------------------------------------------------------ steps
    def activate(self, key):
        if key not in self.steps or self.steps[key].isHidden():
            return
        self.active = key
        for k, s in self.steps.items():
            s.set_active(k == key)

    def _type_changed(self, rebuild=True):
        kind = self.type.currentText()
        need = core.TYPE_DIMENSIONS.get(kind)
        for key, w in self.dims.items():
            shown = need is None or key in need
            w.setVisible(shown)
            label = self.dim_form.labelForField(w)
            if label is not None:
                label.setVisible(shown)
        if "point2" in self.steps:
            two = kind != "Origin and Edge Lengths"
            self.steps["point2"].setVisible(two)
            self.point2_box.setVisible(two)
            if not two and self.active == "point2":
                self.activate("origin")
        self.steps["body"].setVisible(self.mode != "none")
        self.activate(self.active)
        if rebuild:
            self._poll(force=True)

    def _boolean_changed(self):
        self.mode = self.boolean.currentData()
        self.steps["body"].setVisible(self.mode != "none")
        if self.mode != "none" and self.target is None:
            self.activate("body")
        elif self.mode == "none" and self.active == "body":
            self.activate("origin")
        self._poll(force=True)

    # ------------------------------------------------------------ selection
    def verdict(self, pick):
        """The selection gate while the panel is open: what the highlighted step can take."""
        if self.active == "body":
            names = [b.Name for b in self.candidates]
            if pick.body is None:
                return False, f"the target must be a body; {pick.label} is not in one"
            if pick.body.Name not in names:
                return False, f"{pick.body.Label} has no solid to combine with"
            return True, ""
        if pick.kind not in ("vertex", "edge", "face"):
            return False, f"{self.steps[self.active].button.text()} takes a point, an edge or a face"
        return True, ""

    def addSelection(self, doc, obj, sub, pnt=None):
        if self.busy or not self.open:
            return
        try:
            pick = sf.Resolved(doc, obj, sub)
        except Exception:
            return
        ok, why = self.verdict(pick)
        if ok and self.active == "body":
            self.steps["body"].choose(pick.body.Name)
            self.steps["body"].refresh()
        elif ok:
            try:
                top = App.getDocument(doc).getObject(obj)
                shape = top.getSubObject(sf.core.plain(sub))
                picked = App.Vector(*pnt) if pnt else App.Vector()
                ok, why = self.steps[self.active].take(shape, picked)
            except Exception as e:
                ok, why = False, str(e)
            if ok and self.active == "origin" and "point2" in self.steps and not self.steps["point2"].isHidden() \
                    and not self.steps["origin"].pending:
                self.activate("point2")
        if not ok:
            self.warnings = [f"Refused {pick.label}: {why}"]
        QtCore.QTimer.singleShot(0, self._clear_selection)
        self._poll(force=True)

    def removeSelection(self, doc, obj, sub):
        pass

    def clearSelection(self, doc):
        pass

    def _clear_selection(self):
        self.busy = True
        try:
            Gui.Selection.clearSelection()
        finally:
            self.busy = False

    # ------------------------------------------------------------ values
    def values(self):
        v = {"type": self.type.currentText(), "dims": {k: mm(w) for k, w in self.dims.items()},
             "origin": self.steps["origin"].point(), "mode": self.boolean.currentData(),
             "target": self.steps["body"].chosen()}
        if "point2" in self.steps:
            v["point2"] = self.steps["point2"].point()
        if self.vector is not None:
            d = self.vector.currentData()
            v["vector"] = tuple(-c for c in d) if self.reverse.isChecked() else tuple(d)
        return v

    def _key(self, v):
        return repr(sorted((k, repr(x)) for k, x in v.items()))

    def _poll(self, force=False):
        if not self.open:
            return
        try:
            dialog = bool(Gui.Control.activeDialog())
        except Exception:
            dialog = False
        if not dialog or self.doc.Name not in App.listDocuments():
            self._end("cancelled", "the dialog or the document closed", abort=True)
            return
        v = self.values()
        key = self._key(v)
        if key == self.state and not force:
            return
        self.state = key
        self.mode, self.target = v["mode"], v["target"]
        self.steps["body"].refresh()
        try:
            if not self.edit and self.built != (self.mode, self.target if self.mode != "none" else None):
                self._rebuild()
            f = self.feature()
            if f is not None:
                self._set_parameters(f, v)
                self.doc.recompute()
            self.error = None if f is not None else self.error
        except core.CommandError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            log(f"{self.command}: {self.error}")
        self._validate()

    def _set_parameters(self, f, v):
        if self.command == "Block":
            corner, size = core.block_box(v["type"], v["origin"] or (0, 0, 0), v["dims"], v.get("point2"))
            params = dict(zip(("Length", "Width", "Height"), size))
            base, rot = corner, self.rotation or App.Rotation()
        else:
            params = core.check_dimensions(self.command, v["dims"])
            base = v["origin"] or (0, 0, 0)
            rot = App.Rotation(*core.rotation_to(v["vector"])) if "vector" in v else (self.rotation or App.Rotation())
        for k, x in params.items():
            if abs(getattr(f, k).Value - x) > 1e-12:
                setattr(f, k, x)
        body = body_of(f)
        f.Placement = body.getGlobalPlacement().inverse().multiply(App.Placement(App.Vector(*base), rot))

    def feature(self):
        try:
            return self.doc.getObject(self.feature_name) if self.feature_name else None
        except Exception:
            return None

    # ------------------------------------------------------------ build
    def _rebuild(self):
        """Replace the preview for a new Boolean or target: the transaction so far is aborted, so nothing of
        the previous backend is left, and a new one is opened."""
        if self.built is not None:
            self._restore_visibility()
            if App.getActiveTransaction():
                App.closeActiveTransaction(True)
            self.doc.recompute()
            App.setActiveTransaction(self.name, True)
        self.feature_name = self.body_name = self.boolean_name = None
        self.made_body = False
        self.built = (self.mode, self.target if self.mode != "none" else None)
        work_empty = self.work_body is not None and self.work_body.Document is self.doc \
            and solid_tip(self.work_body) is None
        log(f"{self.command}: rebuild {self.mode} target {self.target} (work body empty {work_empty})")
        plan = core.plan(self.mode, self.target is not None, work_empty)
        self._build(plan)
        log(f"{self.command}: built {self.feature_name} in {self.body_name}"
            + (f", Boolean {self.boolean_name}" if self.boolean_name else ""))

    def _build(self, plan):
        doc = self.doc
        target = doc.getObject(self.target) if self.target else None
        if plan["body"] == "work":
            body = self.work_body
        elif plan["body"] == "new":
            body = doc.addObject("PartDesign::Body", "Body")
            self.made_body = True
        else:
            body = target
        prev = solid_tip(body)
        self._remember_visibility(prev)
        feature = body.newObject(f"PartDesign::{plan['feature']}{self.prim}", self.command)
        self.feature_name, self.body_name = feature.Name, body.Name
        result = feature
        if plan["common"]:
            prev = solid_tip(target)
            self._remember_visibility(prev, body)
            b = target.newObject("PartDesign::Boolean", "Intersect")
            b.Type = "Common"
            b.addObject(body)
            self.boolean_name = b.Name
            result = b
            if getattr(body, "ViewObject", None) is not None:
                body.ViewObject.Visibility = False
        self.base_volume = sum(s.Volume for s in prev.Shape.Solids) if prev is not None else 0.0
        self.base_solids = len(prev.Shape.Solids) if prev is not None else 0
        if prev is not None and getattr(prev, "ViewObject", None) is not None:
            for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                try:
                    setattr(result.ViewObject, prop, getattr(prev.ViewObject, prop))
                except Exception:
                    pass
            prev.ViewObject.Visibility = False
        doc.recompute()

    def _remember_visibility(self, *objs):
        for o in objs:
            if o is not None and getattr(o, "ViewObject", None) is not None and o.Name not in self.visibility:
                self.visibility[o.Name] = o.ViewObject.Visibility

    def _restore_visibility(self):
        for name, shown in self.visibility.items():
            o = self.doc.getObject(name)
            if o is not None and getattr(o, "ViewObject", None) is not None:
                o.ViewObject.Visibility = shown
        self.visibility = {}

    def result(self):
        try:
            return self.doc.getObject(self.boolean_name) if self.boolean_name else self.feature()
        except Exception:
            return None

    # ------------------------------------------------------------ validate
    def _validate(self):
        warnings = [w for w in self.warnings if w.startswith("Refused")]
        self.warnings = []
        f, r = self.feature(), self.result()
        if self.error is None and f is None:
            self.error = "nothing to build yet"
        if self.error is None:
            if not f.isValid() or (r is not None and not r.isValid()):
                bad = f if not f.isValid() else r
                why = bad.getStatusString() or "invalid parameters"
                if self.mode == "unite" and "multiple solids" in why.lower():
                    # FreeCAD refuses the disjoint result that NX reports as a tool body missing the target
                    self.error = core.result_issue("unite", 0.0, 1.0, 0, 1, self.command)[1]
                else:
                    self.error = f"FreeCAD cannot build it: {why}"
            else:
                try:
                    solids = r.Shape.Solids if not r.Shape.isNull() else []
                except Exception:
                    solids = []
                issue = core.result_issue(self.mode, self.base_volume, sum(s.Volume for s in solids),
                                          self.base_solids, len(solids), self.command)
                if issue and issue[0] == "error":
                    self.error = issue[1]
                elif issue:
                    self.warnings.append(issue[1])
        self.warnings += warnings
        self._show()

    def _show(self):
        if self.error:
            kind, text = "error", self.error
        elif self.warnings:
            kind, text = "warning", "; ".join(self.warnings)
        else:
            what = "None (a new body)" if self.mode == "none" else core.LABELS[self.mode]
            target = self.doc.getObject(self.target) if self.target and self.mode != "none" else None
            kind, text = "ok", (f"{what}" + (f" with {target.Label}" if target is not None else "")
                                + ": ready (OK or MB2 commits one undo step)")
        if _alive(self.status):
            self.status.setText(text)
            self.status.setStyleSheet(STYLE[kind])
        ok = _dialog_button(QtWidgets.QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(self.error is None)
            ok.setToolTip(self.error or "")
        apply = _dialog_button(QtWidgets.QDialogButtonBox.Apply)
        if apply is not None:
            apply.setEnabled(self.error is None)

    # ------------------------------------------------------------ life cycle
    def begin(self):
        self.open = True
        self.esc = _EscFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self.esc)
        self.token = sf.manager().push(self.layer)
        Gui.Selection.addObserver(self)
        self.selection = [(x.DocumentName, x.ObjectName, sub) for x in Gui.Selection.getSelectionEx("", 0)
                          for sub in (x.SubElementNames or ("",))]
        Gui.Selection.clearSelection()
        self.undo_names = list(self.doc.UndoNames)
        App.setActiveTransaction(self.name, True)
        if self.edit:
            f = self.feature()
            base = getattr(f, "BaseFeature", None)
            r = self.result()
            if self.boolean_name:
                base = getattr(r, "BaseFeature", None)
            self.base_volume = sum(s.Volume for s in base.Shape.Solids) if base is not None else 0.0
            self.base_solids = len(base.Shape.Solids) if base is not None else 0
        self.activate("body" if self.mode != "none" and self.target is None else "origin")
        self.timer = QtCore.QTimer()
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._poll(force=True)
        _current["panel"] = self

    def getStandardButtons(self):
        b = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        if not self.edit:
            b = b | QtWidgets.QDialogButtonBox.Apply
        return _int(b)

    def clicked(self, button):
        log(f"{self.command}: button {button}")
        # FreeCAD 1.1 with PySide6 passes the StandardButton enum here, not an int
        if _int(button) == _int(QtWidgets.QDialogButtonBox.Apply):
            self.apply()

    def accept(self):
        log(f"{self.command}: OK (open {self.open})")
        if not self.open:
            return True
        self._poll(force=True)          # the field that still had the focus
        if self.error is not None:
            log(f"{self.command}: OK refused: {self.error}")
            self._show()
            return False
        self._commit()
        self._end("committed")
        return True

    def reject(self):
        if self.open:
            self._end("cancelled", abort=True)
        return True

    def cancel(self):
        """Esc: as the Cancel button."""
        if self.open:
            self.reject()
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()

    def apply(self):
        """NX's Apply: commit this primitive and start the next one with the same values."""
        self._poll(force=True)
        if self.error is not None or not self.open:
            self._show()
            return False
        self._commit()
        self._record("committed")
        self.visibility = {}
        self.feature_name = self.body_name = self.boolean_name = None
        self.made_body = False
        self.built = None
        self.undo_names = list(self.doc.UndoNames)
        self.work_body = self._work_body()
        self.candidates = self._candidates()
        if self.target not in [b.Name for b in self.candidates]:
            self.target = self._default_target()
        self.steps["body"].fill(self.candidates, self.target)
        App.setActiveTransaction(self.name, True)
        self._poll(force=True)
        return True

    def _commit(self):
        App.closeActiveTransaction(False)
        f = self.feature()
        if f is not None:
            self.committed.append(f)
        v = self.values()
        _remembered[self.command] = {"type": v["type"], "dims": dict(v["dims"]),
                                     "vector": self.vector.currentText() if self.vector is not None else None,
                                     "reverse": self.reverse.isChecked() if self.reverse is not None else False}

    def _end(self, outcome, note="", abort=False):
        if not self.open:
            return
        if abort:
            try:
                self._restore_visibility()
                if App.getActiveTransaction():
                    App.closeActiveTransaction(True)
                if self.doc.Name in App.listDocuments():
                    self.doc.recompute()
            except Exception as e:
                note = (note + "; " if note else "") + f"abort failed: {e}"
        self.open = False
        if self.timer is not None:
            self.timer.stop()
        if getattr(self, "esc", None) is not None:
            QtWidgets.QApplication.instance().removeEventFilter(self.esc)
            self.esc = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        sf.manager().pop(self.token)
        if _current["panel"] is self:
            _current["panel"] = None
        self._record(outcome, note)
        if outcome == "cancelled" and self.doc.Name in App.listDocuments():
            for d, o, sub in self.selection:
                try:
                    Gui.Selection.addSelection(d, o, sub)
                except Exception:
                    pass
        QtCore.QTimer.singleShot(0, _update_commands)

    def _record(self, outcome, note=""):
        log(f"{self.name}: {outcome} {self.mode} {self.feature_name} {note}".rstrip())
        from .command_core import undo_steps_added
        doc_open = self.doc.Name in App.listDocuments()
        f = self.feature() if doc_open and outcome == "committed" else None
        HISTORY.append({"command": self.command, "edit": self.edit, "outcome": outcome, "mode": self.mode,
                        "type": self.type.currentText(), "feature": f.Name if f is not None else None,
                        "body": self.body_name if f is not None else None, "target": self.target,
                        "boolean": self.boolean_name if f is not None else None,
                        "undo": self.doc.UndoNames[0] if doc_open and self.doc.UndoNames else None,
                        "undo_steps": undo_steps_added(self.undo_names, self.doc.UndoNames) if doc_open else None,
                        "error": self.error, "warnings": list(self.warnings), "note": note})
        del HISTORY[:-50]


class _EscFilter(QtCore.QObject):
    """Esc anywhere in the main window cancels, as NX's Esc does. A shortcut on Esc would take the key before the
    task panel sees it, so the shortcut override is claimed as well (as controller._CancelFilter does)."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t != QtCore.QEvent.ShortcutOverride and t != QtCore.QEvent.KeyPress:
            return False
        if ev.key() != QtCore.Qt.Key_Escape or not self.panel.open:
            return False
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is not None and isinstance(obj, QtWidgets.QWidget) and (obj is popup or popup.isAncestorOf(obj)):
            return False                       # Esc closes the open list first
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            ev.accept()
        else:
            QtCore.QTimer.singleShot(0, self.panel.cancel)
        return True


def _dialog_button(which):
    dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
    for box in dock.findChildren(QtWidgets.QDialogButtonBox) if dock is not None else []:
        b = box.button(which)
        if b is not None:
            return b
    return None


def _update_commands():
    try:
        Gui.updateCommands()
    except Exception:
        pass


# ------------------------------------------------------------------ start, edit
def _ensure_partdesign():
    try:
        import PartDesignGui  # noqa: F401  (view providers for the PartDesign objects)
    except ImportError:
        pass


def start(command, feature=None):
    """Open the command's panel (on feature: Edit Parameters). Returns the panel, or None."""
    doc = feature.Document if feature is not None else App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    _ensure_partdesign()
    panel = PrimitivePanel(command, feature)
    Gui.Control.showDialog(panel)
    try:
        panel.begin()
    except Exception as e:
        import traceback
        App.Console.PrintError(f"NXStyle: {command} could not start: {e}\n{traceback.format_exc()}")
        panel.error = f"{command} could not start: {type(e).__name__}: {e}"
        panel._end("failed", panel.error, abort=True)
        Gui.Control.closeDialog()
        return None
    return panel


def editable(obj):
    """(command, primitive feature) that Edit Parameters reopens in the NX dialog for obj, else None: a PartDesign
    primitive, or the Boolean (Common) an Intersect made, whose tool Body holds the primitive."""
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Boolean" and getattr(obj, "Type", "") == "Common" and len(obj.Group) == 1:
        tool = obj.Group[0]
        feats = [o for o in getattr(tool, "Group", []) if core.command_of(o.TypeId)]
        if len(feats) == 1 and feats[0] is getattr(tool, "Tip", None):
            return core.command_of(feats[0].TypeId)[0], feats[0]
        return None
    hit = core.command_of(obj.TypeId)
    if hit is None or body_of(obj) is None:
        return None
    return hit[0], obj


# ------------------------------------------------------------------ commands
class PrimitiveCommand:
    def __init__(self, command):
        self.command = command

    def GetResources(self):
        nx = config.get().get("labels") != "freecad"
        return {"MenuText": self.command if nx else core.FREECAD_NAMES[self.command],
                "ToolTip": TIPS[self.command],
                "Pixmap": config.resource("icons", f"{self.command.lower()}.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        start(self.command)


COMMANDS = {f"NXStyle_{c}": PrimitiveCommand(c) for c in core.PRIMITIVES}

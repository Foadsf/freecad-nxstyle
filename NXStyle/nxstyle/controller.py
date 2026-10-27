# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command controller: one lifecycle for NX commands, however they are started.

    select -> parameterize -> preview -> validate -> commit / cancel -> edit

The ribbon, the shortcut, the Command Finder, the radial menu and the Part Navigator's MB3 menu all run a
command by its name; the command hands over to this controller. The controller owns:

- the document and the target body the command works on;
- the selection scope: the selection when the command started (put back on Cancel), and the Type Filter,
  whose gate is lifted while the command picks its own inputs and restored afterwards;
- one undo transaction per command, opened before the first object is made and closed by the panel's OK
  (commit) or Cancel (abort), so Cancel leaves no preview objects and OK leaves one undo step;
- validation and error state: what cannot be built is shown in the panel and OK is unavailable until it can;
- typed lengths read back from the backend's fields (a misread decimal separator is reported).

The geometry is made by a backend adapter. Extrude is FreeCAD's PartDesign Pad and Pocket, Revolve its
Revolution and Groove; their own parameter panel stays the place where limits are typed. The controller adds
the NX command box above it with the section, the body and the Boolean (New Body, Unite, Subtract; Intersect
shown and refused), and for Revolve the axis (Specify Vector, Specify Point) and the Start and End angle.

The section is NX's Section collector: a whole sketch, or curves of one sketch picked with the Selection bar's
Curve Rule (Single, Tangent or Connected Curves; Inferred Curves takes the whole sketch). Curves can be picked
before the command or while it runs; the feature's Profile is those curves only.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import command_core as core
from . import selection_core
from . import selection_filter
from .qt import QtCore, QtWidgets, Qt


def _alive(w):
    """False once Qt has deleted the widget behind a Python wrapper."""
    if w is None:
        return False
    try:
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        return shiboken.isValid(w)
    except Exception:
        try:
            w.objectName()
            return True
        except RuntimeError:
            return False


def body_of(obj):
    try:
        g = obj.getParentGeoFeatureGroup()
    except Exception:
        return None
    return g if g is not None and g.isDerivedFrom("PartDesign::Body") else None


def solid_tip(body):
    """The body's tip when it holds a solid, else None."""
    tip = getattr(body, "Tip", None) if body is not None else None
    try:
        if tip is not None and tip.isDerivedFrom("PartDesign::Feature") and tip.Shape.Solids:
            return tip
    except Exception:
        pass
    return None


def _solids(obj):
    try:
        return obj.Shape.Solids if obj is not None and not obj.Shape.isNull() else []
    except Exception:
        return []


def _volume(obj):
    return sum(s.Volume for s in _solids(obj))


def _update_commands():
    try:
        Gui.updateCommands()
    except Exception:
        pass


def _status(text, ms=6000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        pass
    App.Console.PrintMessage(text + "\n")


def _tasks_dock():
    return Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")


def _sketch_in_edit():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument else None
        return vp is not None and vp.Object.isDerivedFrom("Sketcher::SketchObject")
    except Exception:
        return False


# --------------------------------------------------------------------------
# Sections: a whole sketch, or curves of one sketch
# --------------------------------------------------------------------------
class Section:
    """What the Section collector holds: a sketch and its picked curves (edges None: the whole sketch)."""

    def __init__(self, sketch, edges=None, refused=()):
        self.sketch, self.edges, self.refused = sketch, edges, list(refused)


def sketch_pick(doc, obj, sub):
    """(sketch, element) for a pick of a sketch or one of its curves, else None; element '' is the whole sketch.
    Outside sketch edit a curve's 'EdgeN' follows the sketch shape's edge order, as the Profile's names do."""
    try:
        pick = selection_filter.Resolved(doc, obj, sub)
    except Exception:
        return None
    leaf = pick.leaf
    if leaf is None or not leaf.isDerivedFrom("Sketcher::SketchObject"):
        return None
    if pick.element and not pick.element.startswith("Edge"):
        return None                                  # a point of the sketch
    return leaf, pick.element


def edge_records(sketch):
    from .collector_ui import edge_records as records
    try:
        return records(sketch.Shape)
    except Exception:
        return {}


def expand(sketch, element, rule):
    """The curves one pick adds to a section under the curve rule; None for the whole sketch."""
    if not element or rule == "inferred":
        return None
    if rule == "single":
        return [element]
    return selection_core.chain(edge_records(sketch), element, rule) or [element]


def section_of_selection(rule=None):
    """The Section the selection gives, or None when it holds no sketch and no sketch curve (a face or a plane:
    the command sketches on it). Picks of a second sketch are refused (FreeCAD's Profile is one object)."""
    rule = rule or selection_filter.manager().curve_rule
    picks = []
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in (s.SubElementNames or ("",)):
            sp = sketch_pick(s.DocumentName, s.ObjectName, sub)
            if sp is not None:
                picks.append(sp)
    if not picks:
        return None
    objs = {sk.Name: sk for sk, _ in picks}
    named = []
    for sk, el in picks:
        curves = expand(sk, el, rule)
        named += [(sk.Name, "")] if curves is None else [(sk.Name, e) for e in curves]
    name, edges, refused = core.section_from_picks(named)
    return Section(objs[name], edges, sorted({objs[n].Label for n, _ in refused}))


def _origin_axis(body, axis):
    for o in body.Origin.OriginFeatures:
        if getattr(o, "Role", "") == f"{axis}_Axis" or o.Name.startswith(f"{axis}_Axis"):
            return o
    raise core.CommandError(f"{body.Label} has no {axis} axis")


def _sketch_line(sketch, sub):
    """(point, direction) of a sketch axis or line, in global coordinates."""
    pl = sketch.getGlobalPlacement()
    if sub in ("H_Axis", "V_Axis"):
        local = App.Vector(1, 0, 0) if sub == "H_Axis" else App.Vector(0, 1, 0)
        return pl.Base, pl.Rotation.multVec(local)
    e = sketch.Shape.getElement(sub)                 # the shape is placed already
    a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
    d = b - a
    d.normalize()
    return a, d


def is_line(sketch, sub):
    try:
        return sketch.Shape.getElement(sub).Curve.TypeId == "Part::GeomLine"
    except Exception:
        return False


# --------------------------------------------------------------------------
# Adapters: Extrude (Pad, Pocket) and Revolve (Revolution, Groove)
# --------------------------------------------------------------------------
class SectionAdapter:
    """What Extrude and Revolve share: a section, the Boolean, a feature in the sketch's Body or a new one."""
    name = ""
    TYPES = ()
    CARRY = ()                       # kept when the Boolean changes the backend
    LENGTH_FIELDS = ()               # backend fields whose typed text is read back
    KEY_PROPS = ()                   # properties whose change is validated again
    NOUN = ""
    OPTIONS = core.EXTRUDE_OPTIONS
    NOTE = core.SHORT_NOTE
    TIP_NOTE = core.DIRECTION_NOTE

    def accepts(self, obj):
        return obj is not None and obj.TypeId in self.TYPES and body_of(obj) is not None

    @staticmethod
    def preselected_section():
        return section_of_selection()

    def mode_of(self, feature):
        return core.mode_of(feature.TypeId, getattr(feature, "BaseFeature", None) is not None)

    def carry(self, feature):
        out = {}
        for p in self.CARRY:
            if p in feature.PropertiesList:
                v = getattr(feature, p)
                out[p] = getattr(v, "Value", v)
        return out

    def plan(self, mode, has_body, has_solid, label):
        raise NotImplementedError

    def setup(self, s, feature, body, profile):
        """Adapter properties before the first recompute."""

    def read(self, s, feature):
        """Session state from an existing feature (Edit Parameters)."""

    def rows(self, box, form, s):
        """The adapter's own rows in the command box."""

    def refresh(self, box, s):
        pass

    def problem(self, s):
        """An adapter input that cannot be built (shown as the error), or None."""
        return None

    def sync(self, s, feature):
        """The box's state from what FreeCAD's panel changed."""

    @staticmethod
    def binder_support(s):
        body, sk = s.sketch_body, s.sketch
        if s.edges is None:
            # the sketch through its own Body, as FreeCAD's binder command links it: placement stays global
            return [(body, (sk.Name + ".",))] if body is not None else [(sk, ("",))]
        return [(body, tuple(f"{sk.Name}.{e}" for e in s.edges))] if body is not None else [(sk, tuple(s.edges))]

    def build(self, s, plan):
        """Make the feature for plan inside the open transaction; returns it."""
        doc = s.doc
        if plan["body"] == "new":
            body = doc.addObject("PartDesign::Body", "Body")
            profile = body.newObject("PartDesign::SubShapeBinder", "Section")
            profile.Support = self.binder_support(s)
        else:
            body = s.sketch_body
            profile = s.sketch
        prev = solid_tip(body)
        feature = body.newObject(plan["feature"], plan["feature"].split("::")[-1])
        feature.Profile = (profile, list(s.edges) if profile is s.sketch and s.edges else [""])
        self.setup(s, feature, body, profile)
        for k, v in s.carried.items():
            if k not in feature.PropertiesList:
                continue
            if k == "Type" and v not in feature.getEnumerationsOfProperty("Type"):
                continue
            try:
                setattr(feature, k, v)
            except Exception:
                pass
        # a whole sketch goes out of sight, as FreeCAD's commands do; a sketch used in part stays shown (NX keeps
        # it, and its other curves are still to be picked)
        hide = [profile] if profile is not s.sketch else []
        if s.edges is None:
            hide.append(s.sketch)
        for o in hide:
            if getattr(o, "ViewObject", None) is not None:
                o.ViewObject.Visibility = False
        if prev is not None and getattr(prev, "ViewObject", None) is not None:
            for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                try:
                    setattr(feature.ViewObject, prop, getattr(prev.ViewObject, prop))
                except Exception:
                    pass
            prev.ViewObject.Visibility = False
        doc.recompute()
        return feature

    def apply_section(self, s, feature):
        """The section changed while the panel is open: the Profile (or the new Body's binder) follows."""
        prof = feature.Profile[0] if feature.Profile else None
        if prof is not None and prof.TypeId == "PartDesign::SubShapeBinder":
            prof.Support = self.binder_support(s)
        else:
            feature.Profile = (s.sketch, list(s.edges) if s.edges else [""])
        s.doc.recompute()


class ExtrudeAdapter(SectionAdapter):
    name = "Extrude"
    TYPES = ("PartDesign::Pad", "PartDesign::Pocket")
    CARRY = ("Type", "Length", "Length2", "Midplane")
    LENGTH_FIELDS = ("length", "offset")
    KEY_PROPS = ("Type", "Length", "Length2", "Midplane", "Reversed", "UpToFace", "TaperAngle")
    NOUN = "extrusion"

    def plan(self, mode, has_body, has_solid, label):
        return core.plan_extrude(mode, has_body, has_solid, label)

    def setup(self, s, feature, body, profile):
        if profile is not s.sketch:
            # a binder's face may point either way (measured: opposite to the sketch normal on XZ); NX
            # extrudes along the section's normal, so say so as the Pad's custom direction
            normal = s.sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            feature.UseCustomVector = True
            feature.Direction = body.getGlobalPlacement().Rotation.inverted().multVec(normal)


class RevolveAdapter(SectionAdapter):
    """NX Revolve on PartDesign Revolution (None, Unite) and Groove (Subtract). The NX box's Axis and Limits drive
    FreeCAD's panel, whose own values are what its OK writes (measured: a property set while the panel is open is
    overwritten on OK). An axis FreeCAD's axis list does not hold is set before the panel opens: the command is
    rebuilt for it, as for a change of Boolean."""
    name = "Revolve"
    TYPES = ("PartDesign::Revolution", "PartDesign::Groove")
    CARRY = ("Midplane",)
    KEY_PROPS = ("Type", "Angle", "Angle2", "Midplane", "Reversed", "ReferenceAxis", "UpToFace")
    NOUN = "revolved section"
    OPTIONS = core.REVOLVE_OPTIONS
    NOTE = core.REVOLVE_NOTE
    TIP_NOTE = ""

    def plan(self, mode, has_body, has_solid, label):
        return core.plan_revolve(mode, has_body, has_solid, label)

    # ------------------------------------------------------------ axis
    def reference(self, s, body, ref):
        """The ReferenceAxis link for an axis of core.revolve_axis in the feature's Body."""
        if ref["kind"] == "origin":
            return (_origin_axis(body, ref["axis"]), [""])
        if ref["kind"] == "sketch" and body is s.sketch_body:
            return (s.sketch, [ref["sub"]])
        if ref["kind"] == "sketch":
            # a new Body cannot link the other Body's sketch: the same line as a datum line of its own
            point, direction = _sketch_line(s.sketch, ref["sub"])
        else:
            point, direction = App.Vector(*ref["point"]), App.Vector(*ref["direction"])
        line = body.newObject("PartDesign::Line", "RevolveAxis")
        line.MapMode = "Deactivated"
        line.Placement = body.getGlobalPlacement().inverse().multiply(
            App.Placement(point, App.Rotation(App.Vector(0, 0, 1), direction)))
        return (line, [""])

    def carry(self, feature):
        out = super().carry(feature)
        if self.axis_of(None, feature)[0] is None and getattr(feature, "ReferenceAxis", None):
            out["ReferenceAxis"] = feature.ReferenceAxis    # one from FreeCAD's list the box has no entry for
            out["Reversed"] = feature.Reversed
        return out

    def setup(self, s, feature, body, profile):
        lim = core.revolve_limits(*s.limits)
        feature.Type = lim["Type"]
        feature.Angle = lim["Angle"]
        if "Angle2" in feature.PropertiesList:
            feature.Angle2 = lim["Angle2"]
        if s.axis["vector"] == "other":
            return                                       # carried as it was
        ref = core.revolve_axis(s.axis["vector"], s.axis["point"])
        feature.ReferenceAxis = self.reference(s, body, ref)
        feature.Reversed = ref["reversed"] != lim["flip"]

    def axis_reversed(self, s):
        try:
            return core.revolve_axis(s.axis["vector"], s.axis["point"])["reversed"]
        except core.CommandError:
            return False

    def axis_of(self, s, feature):
        """The Specify Vector entry and point the feature's ReferenceAxis stands for."""
        ref = getattr(feature, "ReferenceAxis", None)
        if not ref or ref[0] is None:
            return None, (0.0, 0.0, 0.0)
        obj, subs = ref[0], ref[1]
        sub = subs[0] if subs else ""
        body = body_of(feature)
        if body is not None and obj in body.Origin.OriginFeatures:
            return core.vector_of("origin", getattr(obj, "Role", obj.Name), False), (0.0, 0.0, 0.0)
        if obj.isDerivedFrom("Sketcher::SketchObject"):
            return core.vector_of("sketch", sub, False), (0.0, 0.0, 0.0)
        if obj.isDerivedFrom("PartDesign::Line"):
            pl = obj.getGlobalPlacement()
            d = pl.Rotation.multVec(App.Vector(0, 0, 1))
            p = pl.Base
            for key, _l, axis, rev in core.VECTORS:
                v = core.AXIS_DIRS[axis]
                if (App.Vector(*v) * (-1 if rev else 1) - d).Length < 1e-9:
                    return key, (p.x, p.y, p.z)
        return None, (0.0, 0.0, 0.0)

    @staticmethod
    def _limits(feature, flip):
        angle2 = feature.Angle2.Value if "Angle2" in feature.PropertiesList else 0.0
        return core.limits_of(feature.Type, feature.Angle.Value, angle2, flip, feature.Midplane)

    def read(self, s, feature):
        vector, point = self.axis_of(s, feature)
        s.axis = {"vector": vector or "other", "point": point}
        s.limits = self._limits(feature, feature.Reversed) or s.limits

    @staticmethod
    def _same_axis(a, b):
        try:
            ra, rb = core.revolve_axis(a["vector"], a["point"]), core.revolve_axis(b["vector"], b["point"])
        except core.CommandError:
            return False
        key = ("kind", "axis", "sub")
        if any(ra.get(k) != rb.get(k) for k in key):
            return False
        return all(abs(x - y) < 1e-6 for x, y in zip(ra.get("point", ()), rb.get("point", ())))

    def sync(self, s, feature):
        """FreeCAD's panel may have changed the axis or the angles: the box follows. A reversed vector and a
        reversed sweep are one Reversed property: the box keeps its vector while the axis is the one it set."""
        vector, point = self.axis_of(s, feature)
        if not (vector and self._same_axis(s.axis, {"vector": vector, "point": point})):
            s.axis = {"vector": vector or "other", "point": point}
        lim = self._limits(feature, feature.Reversed != self.axis_reversed(s))
        if lim is not None and not s.limit_error:
            s.limits = lim

    # ------------------------------------------------------------ the box
    def rows(self, box, form, s):
        box.vector = QtWidgets.QComboBox()
        box.vector.setObjectName("nxSpecifyVector")
        box.vector.setToolTip("Specify Vector: the direction of the axis; with Specify Point it is the axis")
        for key, label, _a, _r in core.VECTORS:
            box.vector.addItem(label, key)
        for key, label, _sub in core.SKETCH_AXES:
            box.vector.addItem(label, key)
        box.pick_line = QtWidgets.QToolButton()
        box.pick_line.setObjectName("nxPickAxisLine")
        box.pick_line.setText("Line…")
        box.pick_line.setCheckable(True)
        box.pick_line.setToolTip("Pick a line of the sketch as the axis")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(box.vector, 1)
        row.addWidget(box.pick_line)
        form.addRow("Specify Vector", row)
        box.point = []
        prow = QtWidgets.QHBoxLayout()
        for c in "XYZ":
            sb = QtWidgets.QDoubleSpinBox()
            sb.setObjectName(f"nxPoint{c}")
            sb.setRange(-1e7, 1e7)
            sb.setDecimals(6)
            sb.setSuffix(" mm")
            sb.setKeyboardTracking(False)
            sb.setToolTip(f"Specify Point {c} (absolute, mm): the axis passes through this point")
            box.point.append(sb)
            prow.addWidget(sb)
        form.addRow("Specify Point", prow)
        box.start, box.end = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
        for sb, name, tip in ((box.start, "nxLimitStart", "Start angle"), (box.end, "nxLimitEnd", "End angle")):
            sb.setObjectName(name)
            sb.setRange(-360.0, 360.0)
            sb.setDecimals(6)
            sb.setSuffix(" °")
            sb.setKeyboardTracking(False)
            sb.setToolTip(f"{tip}, degrees about the axis (right hand rule)")
        lrow = QtWidgets.QHBoxLayout()
        lrow.addWidget(QtWidgets.QLabel("Start"))
        lrow.addWidget(box.start, 1)
        lrow.addWidget(QtWidgets.QLabel("End"))
        lrow.addWidget(box.end, 1)
        form.addRow("Limits", lrow)
        ctl = box.ctl
        box.vector.activated.connect(lambda i: ctl.change_axis(box.vector.itemData(i), None))
        for sb in box.point:
            sb.editingFinished.connect(lambda: ctl.change_axis(None, tuple(w.value() for w in box.point)))
        box.start.editingFinished.connect(lambda: ctl.change_limits(box.start.value(), box.end.value()))
        box.end.editingFinished.connect(lambda: ctl.change_limits(box.start.value(), box.end.value()))
        box.pick_line.toggled.connect(ctl.pick_axis_line)
        if s.edit:
            for w in [box.vector, box.pick_line] + box.point:
                w.setEnabled(False)
                w.setToolTip("Change the axis of an existing Revolve in FreeCAD's axis list below")

    def refresh(self, box, s):
        vector = s.axis["vector"]
        i = box.vector.findData(vector)
        if i < 0 and vector:
            label = (f"Line {vector[5:]}" if vector.startswith("line:") else "Datum or edge (FreeCAD's axis list)")
            box.vector.addItem(label, vector)
            i = box.vector.findData(vector)
        for w, value in [(box.vector, None)] + list(zip(box.point, s.axis["point"])) + \
                [(box.start, s.limits[0]), (box.end, s.limits[1])]:
            w.blockSignals(True)
            if value is None:
                w.setCurrentIndex(i)
            elif not w.hasFocus():
                w.setValue(value)
            w.blockSignals(False)
        box.pick_line.blockSignals(True)
        box.pick_line.setChecked(s.axis_pick)
        box.pick_line.blockSignals(False)

    def problem(self, s):
        return s.limit_error or s.axis_error

    # ------------------------------------------------------------ FreeCAD's panel
    @staticmethod
    def _panel_widgets(s):
        a = _tasks_dock()                                # FreeCAD's names; the NX box's own differ
        if a is None:
            return None
        found = {"mode": a.findChild(QtWidgets.QComboBox, "changeMode"),
                 "angle": a.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle"),
                 "angle2": a.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle2"),
                 "reversed": a.findChild(QtWidgets.QCheckBox, "checkBoxReversed")}
        return found if all(found.values()) else None

    def drive(self, s, feature, lim, reversed_):
        """Type, angles and Reversed into FreeCAD's panel, as typed there; False when its fields are not found."""
        w = self._panel_widgets(s)
        if w is None:
            return False
        from . import precise_input
        from .quantity_core import decimals_needed
        types = feature.getEnumerationsOfProperty("Type")
        idx = types.index(lim["Type"])
        if w["mode"].currentIndex() != idx:
            w["mode"].setCurrentIndex(idx)
            try:
                w["mode"].activated.emit(idx)            # FreeCAD 1.1 dialogs react to 'activated'
            except Exception:
                w["mode"].activated[int].emit(idx)
        for field, value in ((w["angle"], lim["Angle"]), (w["angle2"], lim["Angle2"])):
            q = App.Units.Quantity(f"{value!r} deg")
            precise_input.show_with(field, q, max(decimals_needed(value), precise_input.preference_decimals()))
        if w["reversed"].isChecked() != reversed_:
            w["reversed"].setChecked(reversed_)
        return True


ADAPTERS = {"Extrude": ExtrudeAdapter(), "Revolve": RevolveAdapter()}


def adapter_for(obj):
    return next((a for a in ADAPTERS.values() if a.accepts(obj)), None)


# --------------------------------------------------------------------------
# Session state and the NX command box
# --------------------------------------------------------------------------
class Session:
    def __init__(self, adapter, requested=None, feature=None):
        self.adapter = adapter
        self.requested = requested
        self.edit = feature is not None
        self.stage = "select"            # select (-> switching) -> build -> parameterize -> committed | cancelled | failed
        self.doc = feature.Document if feature is not None else App.ActiveDocument
        self.sketch = self.sketch_body = self.body = None
        self.edges = None                # the section's curves of the sketch; None: the whole sketch
        self.picks = []                  # picks waiting for the controller: ('add' | 'remove', sketch, element)
        self.picking = False             # the controller is selecting the section itself (not a user's pick)
        self.axis = {"vector": "sketch_v", "point": (0.0, 0.0, 0.0)}   # Revolve: FreeCAD's default axis
        self.limits = (0.0, 360.0)
        self.axis_pick = False           # Revolve: the next sketch line picked is the axis
        self.limit_error = self.axis_error = None
        self.has_body = self.has_solid = False
        self.feature_name = feature.Name if feature is not None else None
        self.mode = None
        self.carried = {}
        self.base_volume, self.base_solids = 0.0, 0
        self.error = self.notice = None
        self.warnings = []
        self.field_issues = {}
        self.typed = {}
        self.swapping = False
        self.cancelled = False           # Cancel or Esc, which the controller handles itself
        self.result_body = None          # the Body that holds the committed feature
        self.box = self.anchor = None
        self.filtered = []               # the application (Esc), then the panel's Cancel buttons
        self.key = None
        self.undo_names = list(self.doc.UndoNames) if self.doc is not None else []
        self.selection = [(x.DocumentName, x.ObjectName, sub) for x in Gui.Selection.getSelectionEx("", 0)
                          for sub in (x.SubElementNames or ("",))]
        self.active_body = None
        try:
            self.active_body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        except Exception:
            pass
        self.visibility = {}
        self.gate_kind = None

    def remember_visibility(self, *objs):
        for o in objs:
            if o is not None and getattr(o, "ViewObject", None) is not None and o.Name not in self.visibility:
                self.visibility[o.Name] = o.ViewObject.Visibility

    def feature(self):
        try:
            return self.doc.getObject(self.feature_name) if self.feature_name else None
        except Exception:
            return None

    def section_text(self):
        if self.sketch is None:
            return "-"
        if self.edges is None:
            return self.sketch.Label
        return f"{self.sketch.Label}: {len(self.edges)} curve{'s' if len(self.edges) != 1 else ''}"


STYLE = {"error": "color: #B00020;", "warning": "color: #8A5A00;", "ok": "color: #0B6E79;"}


class CommandBox(QtWidgets.QGroupBox):
    """NX's command dialog header: section, body, Boolean, the adapter's rows, what is not supported, and the
    error state."""

    def __init__(self, ctl, s):
        super().__init__(s.adapter.name)
        from .collector_ui import CollectorWidget
        self.ctl = ctl
        self.setObjectName("NXCommandBox")
        form = QtWidgets.QFormLayout(self)
        self.section = QtWidgets.QLabel()
        self.section.setObjectName("nxSection")
        self.collector = selection_core.Collector("Select Curve", ["curve", "sketch"], minimum=1,
                                                  command=s.adapter.name)
        self.curves = CollectorWidget(self.collector, rules=selection_core.SECTION_RULES)
        self.curves.setObjectName("nxSectionCurves")
        self.curves.rule.setToolTip("Curve Rule (as on the Selection bar): what one pick adds to the section")
        self.curves.rule.activated.connect(
            lambda i: selection_filter.manager().set_curve_rule(self.curves.rule.itemData(i)))
        self.body = QtWidgets.QLabel()
        self.body.setObjectName("nxBody")
        self.boolean = QtWidgets.QComboBox()
        self.boolean.setObjectName("nxBoolean")
        for i, (key, label) in enumerate(core.BOOLEANS):
            self.boolean.addItem(label, key)
            if key in core.UNSUPPORTED:
                self.boolean.setItemData(i, core.UNSUPPORTED[key], Qt.ToolTipRole)
                try:
                    self.boolean.model().item(i).setEnabled(False)
                except Exception:
                    self.boolean.setItemData(i, 0, Qt.UserRole - 1)
        if s.edit:
            self.boolean.setEnabled(False)
            self.boolean.setToolTip(dict((n, why) for n, _, why in s.adapter.OPTIONS)[
                "Change the Boolean when editing"])
        self.boolean.activated.connect(self._activated)
        self.note = QtWidgets.QLabel(s.adapter.NOTE)
        self.note.setToolTip(core.options_tooltip(s.adapter.OPTIONS, s.adapter.TIP_NOTE))
        self.note.setObjectName("nxUnsupported")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #5A5A5A;")
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("nxStatus")
        self.status.setWordWrap(True)
        form.addRow("Section", self.section)
        form.addRow(self.curves)
        form.addRow("Body", self.body)
        form.addRow("Boolean", self.boolean)
        s.adapter.rows(self, form, s)
        form.addRow(self.note)
        form.addRow(self.status)
        self.refresh(s)

    def _activated(self, index):
        self.ctl.change_boolean(self.boolean.itemData(index))

    def refresh(self, s):
        self.section.setText(s.section_text())
        c = self.collector
        c.items = []
        if s.sketch is not None:
            subs = [""] if s.edges is None else s.edges
            for e in subs:
                label = f"{e} of {s.sketch.Label}" if e else f"{s.sketch.Label} (all curves)"
                c.items.append(selection_core.Pick(s.doc.Name, s.sketch.Name, e, "curve" if e else "sketch",
                                                   label=label))
        self.curves.set_rule(selection_filter.manager().curve_rule)
        self.curves.refresh()
        f = s.feature()
        body = body_of(f) if f is not None else None
        new = " (new)" if s.mode == "new_body" and body is not None and body is not s.sketch_body else ""
        self.body.setText((body.Label if body is not None else "-") + new)
        i = self.boolean.findData(s.mode)
        if i >= 0 and self.boolean.currentIndex() != i:
            self.boolean.setCurrentIndex(i)
        s.adapter.refresh(self, s)
        if s.error:
            kind, text = "error", s.error
        elif s.warnings:
            kind, text = "warning", "; ".join(s.warnings)
        else:
            label = "None (a new body)" if s.mode == "new_body" else core.LABELS.get(s.mode, s.mode)
            kind, text = "ok", f"{label}: ready (OK or MB2 commits one undo step)"
        self.status.setText(text)
        self.status.setStyleSheet(STYLE[kind])


class _CancelFilter(QtCore.QObject):
    """Cancel and Esc go to the controller, not to PartDesign's reject().

    FreeCAD 1.1.0's TaskDlgFeatureParameters::reject() takes the feature's Body before it aborts the
    transaction and reads that Body's Tip afterwards when the feature had no previous one. For a New Body
    extrude the abort has just deleted that Body. The controller aborts the same way, without that read."""

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl

    @staticmethod
    def _in_popup(obj):
        """Esc meant for an open list or menu (it closes that): only when the key goes to the popup itself. A
        popup left registered elsewhere (measured: the Command Finder's completer) must not swallow Cancel."""
        popup = QtWidgets.QApplication.activePopupWidget()
        if popup is None or not isinstance(obj, QtWidgets.QWidget):
            return False
        return obj is popup or popup.isAncestorOf(obj)

    EVENTS = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonRelease,
              QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in self.EVENTS:                          # on the application: every event passes here
            return False
        s = self.ctl.session
        if s is None or s.stage != "parameterize" or s.swapping:
            return False
        if any(obj is b for b in s.filtered[1:]):        # the panel's Cancel button
            if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
                return True
            if t == QtCore.QEvent.MouseButtonRelease or (t == QtCore.QEvent.KeyRelease and ev.key() == Qt.Key_Space):
                QtCore.QTimer.singleShot(0, self.ctl.cancel)
                return True
            return False
        # Esc anywhere in the main window, as NX's Esc = Cancel. A shortcut on Esc would take the key before the
        # panel sees it (measured: the edit was committed), so the shortcut override is claimed as well.
        if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and ev.key() == Qt.Key_Escape \
                and not self._in_popup(obj) and QtWidgets.QApplication.activeModalWidget() is None:
            if t == QtCore.QEvent.ShortcutOverride:
                ev.accept()
            else:
                QtCore.QTimer.singleShot(0, self.ctl.cancel)
            return True
        return False


class _Observer:
    """Validate as soon as the backend recomputes the feature, before a following OK can be pressed."""

    def __init__(self, ctl):
        self.ctl = ctl

    def slotRecomputedObject(self, obj):
        s = self.ctl.session
        try:
            if s is not None and s.stage == "parameterize" and obj.Name == s.feature_name \
                    and obj.Document.Name == s.doc.Name:
                self.ctl.validate(force=True)
        except Exception:
            pass


class _SectionPicks:
    """The Section collector's ears: sketch curves picked while the command runs. The picks are handled after
    FreeCAD has finished the selection change (its panel may take a pick as its own reference first)."""

    def __init__(self, ctl):
        self.ctl = ctl

    def _queue(self, what, doc, obj, sub):
        s = self.ctl.session
        if s is None or s.picking or s.stage in ("committed", "cancelled", "failed") or _sketch_in_edit():
            return
        sp = sketch_pick(doc, obj, sub)
        self.ctl.log(f"pick {what} {obj}.{selection_core.plain(sub)} at {s.stage}: "
                     f"{(sp[0].Name, sp[1]) if sp is not None else 'not a sketch curve'}")
        if sp is None:
            return
        s.picks.append((what, sp[0], sp[1]))
        QtCore.QTimer.singleShot(0, self.ctl.take_picks)

    def addSelection(self, doc, obj, sub, _pnt=None):
        self._queue("add", doc, obj, sub)

    def removeSelection(self, doc, obj, sub):
        self._queue("remove", doc, obj, sub)

    # a cleared selection is no deselection: FreeCAD clears it on a plain click and when a panel opens
    def setSelection(self, doc):
        pass

    def clearSelection(self, doc):
        pass


# --------------------------------------------------------------------------
# The controller
# --------------------------------------------------------------------------
class Controller:
    def __init__(self):
        self.session = None
        self.history = []                # one dict per ended command (read by the tutorial replay)
        self.timer = None
        self.observer = None
        self.cancel_filter = None
        self.picks = None
        self.trace = []                  # the last lifecycle events, for the Report view and the replay

    def log(self, text):
        import time
        self.trace = self.trace[-79:] + [f"{time.strftime('%H:%M:%S')} {text}"]

    # ---------------------------------------------------------- start
    def busy(self):
        return self.session is not None

    def _settle(self):
        """A command whose panel has just closed (OK, before the next poll) is finished first."""
        s = self.session
        if s is not None and s.stage == "parameterize" and not s.swapping and not self._dialog_open():
            self.log("settle: the previous panel closed before the poll noticed")
            self._finish(force=True)

    def begin(self, adapter, requested=None):
        """select: with a section selected go straight on; otherwise sketch first (NX: sketch in the command), and
        a sketch curve picked meanwhile is taken as the section instead."""
        self._settle()
        if self.session is not None:
            self._end("cancelled", "replaced by a new command")
        s = Session(adapter, requested)
        if s.doc is None:
            return False
        self.session = s
        return self._guarded(s, self._begin)

    def _guarded(self, s, start):
        """Run a command's start; a failure before its panel opens ends the command (failed, with the reason)
        instead of leaving the controller busy with a command that never opened."""
        try:
            return start(s)
        except Exception as e:
            import traceback
            reason = f"{s.adapter.name} could not start: {type(e).__name__}: {e}"
            App.Console.PrintError(f"NXStyle: {reason}\n{traceback.format_exc()}")
            self.log(reason)
            if self.session is s:
                try:
                    if App.getActiveTransaction():
                        App.closeActiveTransaction(True)       # nothing of a command that never opened stays
                except Exception:
                    pass
                s.error = reason
                if s.stage == "parameterize":                # the panel it opened goes too
                    self._close_panel()
                from . import commands
                if commands.pending_feature["command"] == self._section_done:
                    commands.pending_feature["command"] = None
                self._end("failed", reason)
            return False

    def _begin(self, s):
        adapter = s.adapter
        self._suspend_gate()
        self._start_timer()
        self._listen()
        section = adapter.preselected_section()
        self.log(f"begin {adapter.name} ({s.requested or 'inferred'}): {len(s.selection)} selected, "
                 f"section {section.sketch.Name if section is not None else None} "
                 f"{'whole' if section is None or section.edges is None else len(section.edges)}")
        if section is not None:
            if section.refused:
                s.notice = f"{', '.join(section.refused)} left out: {core.SECTION_ONE_SKETCH}"
            return self._parameterize(section.sketch, section.edges)
        from . import commands
        commands.pending_feature["command"] = self._section_done
        commands.pending_feature["sketch"] = None
        self._ensure_work_body(s)
        Gui.runCommand("PartDesign_NewSketch")
        try:
            edited = Gui.ActiveDocument.getInEdit()
        except Exception:
            edited = None
        self.log(f"select: PartDesign_NewSketch gave {edited.Object.Name if edited is not None else 'no edit'}, "
                 f"dialog {bool(Gui.Control.activeDialog())}")
        return True

    def _ensure_work_body(self, s):
        """FreeCAD's sketch command needs an active Body once a part has several, and stops with an 'Active Body
        Required' message otherwise (after an undo removed the active one, for example). NX has no such step:
        take the Body this controller last worked on in the part, else the first."""
        try:
            view = Gui.getDocument(s.doc.Name).ActiveView
            if view.getActiveObject("pdbody") is not None:
                return
        except Exception:
            return
        bodies = [o for o in s.doc.Objects if o.isDerivedFrom("PartDesign::Body")]
        if len(bodies) < 2:
            return                       # FreeCAD takes a lone Body by itself
        names = [r.get("body") for r in reversed(self.history) if r.get("document") == s.doc.Name]
        body = next((s.doc.getObject(n) for n in names if n and s.doc.getObject(n) is not None), bodies[0])
        view.setActiveObject("pdbody", body)
        s.active_body = body
        self.log(f"no active Body: {body.Name} made active for the sketch")
        _status(f"{s.adapter.name}: no Body was active; {body.Label} is now")

    def _section_done(self, sketch):
        """Called when the sketch made inside the command is finished (None: cancelled or left empty)."""
        self.log(f"section done: {sketch.Name if sketch is not None else None}")
        if self.session is None or self.session.stage != "select":
            return False
        if sketch is None:
            self._end("cancelled", "no section: the sketch was cancelled or left empty")
            return False
        return self._guarded(self.session, lambda s: self._parameterize(sketch))

    def _parameterize(self, sketch, edges=None):
        s = self.session
        s.sketch, s.doc, s.edges = sketch, sketch.Document, (list(edges) if edges is not None else None)
        s.sketch_body = body_of(sketch)
        s.has_body = s.sketch_body is not None
        s.has_solid = solid_tip(s.sketch_body) is not None
        s.remember_visibility(sketch, solid_tip(s.sketch_body))
        s.mode = core.infer_boolean(s.requested, s.has_body, s.has_solid)
        label = s.sketch_body.Label if s.sketch_body is not None else "the Body"
        try:
            plan = s.adapter.plan(s.mode, s.has_body, s.has_solid, label)
        except core.CommandError as e:
            # the requested Boolean cannot be built (Subtract with nothing to cut): start with what NX would
            # infer, and say so in the panel
            s.notice = f"{e}; started as {core.LABELS[core.infer_boolean(None, s.has_body, s.has_solid)]}"
            s.mode = core.infer_boolean(None, s.has_body, s.has_solid)
            plan = s.adapter.plan(s.mode, s.has_body, s.has_solid, label)
        return self._build(plan)

    def _build(self, plan):
        s = self.session
        # The backend's recompute runs the event loop (FreeCAD's progress bar), so the poll can fire before the
        # panel opens. In 'select' it read the section handed over as missing (measured: tutorial AJ's Subtract
        # ended 'cancelled ... no section' in 4 of 6 runs, and the build then opened a panel for the ended command);
        # in 'parameterize' it would read the panel as closed.
        s.stage = "build"
        s.undo_names = list(s.doc.UndoNames)     # the sketch made inside the command has its own undo steps
        App.setActiveTransaction(s.adapter.name, True)
        try:
            feature = s.adapter.build(s, plan)
        except Exception as e:
            App.closeActiveTransaction(True)
            self._end("failed", f"{s.adapter.name} could not start: {e}")
            return False
        s.feature_name = feature.Name
        s.body = body_of(feature)
        base = getattr(feature, "BaseFeature", None)
        s.base_volume, s.base_solids = _volume(base), len(_solids(base))
        s.stage = "parameterize"
        s.key = None
        self._watch()
        Gui.getDocument(s.doc.Name).setEdit(feature, 0)
        QtCore.QTimer.singleShot(0, self._attach)
        return True

    def edit(self, adapter, feature):
        """edit: reopen an existing feature in the same panel, in its own undo transaction."""
        self._settle()
        if self.session is not None:
            return False
        s = Session(adapter, feature=feature)
        self.session = s
        return self._guarded(s, lambda s: self._edit(s, feature))

    def _edit(self, s, feature):
        adapter = s.adapter
        s.body = s.sketch_body = body_of(feature)
        prof = feature.Profile[0] if getattr(feature, "Profile", None) else None
        subs = [e for e in (feature.Profile[1] if prof is not None else []) if e]
        s.sketch = prof
        if prof is not None and prof.TypeId == "PartDesign::SubShapeBinder" and prof.Support:
            try:
                parent, bsubs = prof.Support[0]
                s.sketch = parent.getSubObject(bsubs[0], 1) if bsubs and bsubs[0] else parent
                subs = [b.split(".")[-1] for b in bsubs if b.split(".")[-1]]
                s.sketch_body = body_of(s.sketch)
            except Exception:
                pass
        s.edges = core.sort_edges(subs) if subs else None
        s.mode = adapter.mode_of(feature)
        adapter.read(s, feature)
        base = getattr(feature, "BaseFeature", None)
        s.base_volume, s.base_solids = _volume(base), len(_solids(base))
        s.remember_visibility(feature, base, prof, s.sketch)
        self._suspend_gate()
        self._start_timer()
        self._listen()
        App.setActiveTransaction("Edit " + adapter.name, True)
        s.stage = "parameterize"
        self._watch()
        Gui.getDocument(s.doc.Name).setEdit(feature, 0)
        QtCore.QTimer.singleShot(0, self._attach)
        return True

    # ---------------------------------------------------------- section picks
    def _listen(self):
        if self.picks is None:
            self.picks = _SectionPicks(self)
            Gui.Selection.addObserver(self.picks)

    def _unlisten(self):
        if self.picks is not None:
            try:
                Gui.Selection.removeObserver(self.picks)
            except Exception:
                pass
            self.picks = None

    def take_picks(self):
        """Sketch curves picked while the command runs: into the section (or, for Revolve's Line…, the axis)."""
        s = self.session
        if s is None or not s.picks:
            return
        if s.stage == "select":
            what, sketch, element = s.picks[0]
            if what != "add":
                s.picks.pop(0)
                return
            s.picks.pop(0)
            self._switch_to_section(s, sketch, expand(sketch, element, selection_filter.manager().curve_rule))
            return
        if s.stage != "parameterize" or s.swapping or not _alive(s.box):
            return                                       # kept until the panel is up (_attach takes them)
        f = s.feature()
        rule = selection_filter.manager().curve_rule
        changed, refused, rehighlight = False, [], False
        while s.picks:
            what, sketch, element = s.picks.pop(0)
            if s.axis_pick and what == "add" and element:
                self._axis_line(s, sketch, element)
                return
            ref = getattr(f, "ReferenceAxis", None) if f is not None else None
            if ref and ref[0] is sketch and element and list(ref[1]) == [element]:
                continue                                 # FreeCAD's 'Select reference…' took it as the axis
            if sketch is not s.sketch:
                if what == "add":
                    refused.append(sketch.Label)
                continue
            if what == "add":
                if not element and rule != "inferred" and s.edges:
                    # the whole sketch picked while collecting curves: a click on a curve that is already selected
                    # (the section's highlight) selects FreeCAD's whole object (measured: 'clear', 'add Sketch.').
                    # Only Inferred Curves turns a curve section into the whole sketch; the highlight comes back
                    self.log("whole sketch picked during a curve section: left out (Curve Rule is not Inferred)")
                    _status(f"{s.adapter.name}: the whole sketch is taken with the Curve Rule on Inferred Curves")
                    rehighlight = True
                    continue
                curves = expand(sketch, element, rule)
                new = None if curves is None else core.add_to_section(s.edges, curves)
                if new == s.edges:
                    continue
                s.edges, changed = new, True
            elif s.edges is not None and element in s.edges:
                s.edges, changed = core.remove_from_section(s.edges, [element]), True
        for label in refused:
            self.box_reject(s, f"a curve of {label}", core.SECTION_ONE_SKETCH)
        if changed:
            self.log(f"section: {s.section_text()} {s.edges if s.edges is not None else 'whole'}")
            if s.edges is None or s.edges:
                s.adapter.apply_section(s, f)
                if s.edges is None and s.sketch.ViewObject is not None:
                    s.sketch.ViewObject.Visibility = False
            self._highlight(s)
            s.key = None
            self.validate(force=True)
        elif rehighlight:
            self._highlight(s)

    def box_reject(self, s, label, reason):
        if _alive(s.box):
            s.box.collector.reject(label, reason)
            s.box.curves.refresh()
        _status(f"{s.adapter.name}: {label} refused: {reason}")

    def _highlight(self, s):
        """The section's curves stay selected, so they show as NX's section does; a sketch used whole is hidden."""
        if s.edges is None or s.sketch is None:
            return
        s.picking = True
        try:
            if s.sketch.ViewObject is not None and not s.sketch.ViewObject.Visibility:
                s.sketch.ViewObject.Visibility = True
            Gui.Selection.clearSelection()
            for e in s.edges:
                if s.sketch_body is not None:
                    Gui.Selection.addSelection(s.doc.Name, s.sketch_body.Name, f"{s.sketch.Name}.{e}")
                else:
                    Gui.Selection.addSelection(s.doc.Name, s.sketch.Name, e)
        except Exception as e:
            self.log(f"highlight: {e}")
        finally:
            s.picking = False

    @staticmethod
    def _highlighted(s):
        """The selection is the section's highlight and nothing else."""
        try:
            got = set()
            for x in Gui.Selection.getSelectionEx("", 0):
                for sub in (x.SubElementNames or ("",)):
                    sp = sketch_pick(x.DocumentName, x.ObjectName, sub)
                    if sp is None or sp[0] is not s.sketch:
                        return False
                    got.add(sp[1])
            return got == set(s.edges)
        except Exception:
            return False

    def _switch_to_section(self, s, sketch, edges):
        """A sketch curve picked while FreeCAD asks for the plane of a new sketch: it is NX's Section collector
        taking a curve, not a plane. FreeCAD's plane pick is cancelled and the command builds from the curves."""
        from . import commands
        s.stage = "switching"
        commands.pending_feature["command"] = None
        self.log(f"select: {sketch.Name} {edges if edges is not None else 'whole'} picked instead of a plane")
        self._press_cancel()
        self._after_panel(lambda: self._guarded(s, lambda s: self._parameterize(sketch, edges)))

    @staticmethod
    def _press_cancel():
        dock = _tasks_dock()
        for box in dock.findChildren(QtWidgets.QDialogButtonBox) if dock is not None else []:
            b = box.button(QtWidgets.QDialogButtonBox.Cancel)
            if b is not None and b.isVisible() and b.isEnabled():
                b.click()
                return
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        except Exception:
            pass

    def _after_panel(self, then, tries=0):
        """then(), once no task panel is open and nothing is in edit (at most two seconds)."""
        s = self.session
        if s is None:
            return
        try:
            busy = bool(Gui.Control.activeDialog()) or Gui.getDocument(s.doc.Name).getInEdit() is not None
        except Exception:
            busy = False
        if busy and tries < 40:
            QtCore.QTimer.singleShot(50, lambda: self._after_panel(then, tries + 1))
            return
        then()

    # ---------------------------------------------------------- Boolean, axis, limits
    def change_boolean(self, mode):
        """New Body, Unite or Subtract chosen in the box: rebuild with the matching backend feature, in a new
        transaction (the first one is aborted, so nothing of it is left)."""
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping or mode == s.mode:
            return False
        if s.edit:
            s.error = f"Changing the Boolean of an existing {s.adapter.name} is not supported"
            self._show()
            return False
        label = s.sketch_body.Label if s.sketch_body is not None else "the Body"
        try:
            plan = s.adapter.plan(mode, s.has_body, s.has_solid, label)
        except core.CommandError as e:
            s.notice = f"{core.LABELS.get(mode, mode)} refused: {e}"
            s.key = None
            self.validate(force=True)
            return False
        self._restart(mode, plan)
        return True

    def _restart(self, mode, plan):
        s = self.session
        f = s.feature()
        s.carried = s.adapter.carry(f) if f is not None else {}
        s.swapping = True
        self._remove_box()
        self._abort()                                    # nothing of the first backend is left
        self._close_panel()
        self._restore_visibility(s)
        self._rebuild(mode, plan, 0)

    def change_axis(self, vector=None, point=None):
        """Revolve: Specify Vector or Specify Point changed in the box. FreeCAD's panel takes an axis only from
        its own list or from the feature it opens with, so the command is rebuilt with the new axis."""
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping or s.edit or vector == "other":
            return False
        axis = {"vector": vector or s.axis["vector"], "point": tuple(point) if point is not None else s.axis["point"]}
        if axis == s.axis:
            return False
        try:
            core.revolve_axis(axis["vector"], axis["point"])
        except core.CommandError as e:
            s.axis_error = str(e)
            self.validate(force=True)
            return False
        s.axis, s.axis_error, s.axis_pick = axis, None, False
        self.log(f"axis: {axis}")
        self._restart(s.mode, s.adapter.plan(s.mode, s.has_body, s.has_solid,
                                             s.sketch_body.Label if s.sketch_body is not None else "the Body"))
        return True

    def change_limits(self, start, end):
        """Revolve: Start or End angle typed in the box; they go into FreeCAD's panel as typed there."""
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping:
            return False
        if (start, end) == tuple(s.limits) and not s.limit_error:
            return False
        try:
            lim = core.revolve_limits(start, end)
        except core.CommandError as e:
            s.limit_error = str(e)
            s.key = None
            self.validate(force=True)
            return False
        s.limit_error, s.limits = None, (float(start), float(end))
        f = s.feature()
        reversed_ = s.adapter.axis_reversed(s) != lim["flip"]
        if f is None or not s.adapter.drive(s, f, lim, reversed_):
            s.limit_error = "FreeCAD's angle fields were not found: type the angles in its panel below"
        self.log(f"limits: {start:g}..{end:g} -> {lim}")
        s.key = None
        self.validate(force=True)
        return True

    def pick_axis_line(self, on):
        s = self.session
        if s is None or s.stage != "parameterize":
            return
        s.axis_pick = bool(on)
        if on:
            _status("Revolve: pick a line of the sketch as the axis")

    def _axis_line(self, s, sketch, element):
        if sketch is not s.sketch or not is_line(sketch, element):
            s.axis_pick = False
            self.box_reject(s, f"{element} of {sketch.Label}", "the axis is a straight line of the section's sketch")
            self._show()
            return
        self.change_axis(f"line:{element}", (0.0, 0.0, 0.0))

    def cancel(self):
        """cancel: abort the command's transaction (previews and new bodies go), then close the panel."""
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping:
            return
        s.cancelled = True
        self._remove_box()
        self._abort()
        self._close_panel()
        self._finish()

    def _abort(self):
        """Abort before resetEdit(): leaving edit mode commits the transaction that was open when editing
        began (that is how PartDesign's own OK commits). PartDesign's Cancel aborts first too."""
        s = self.session
        try:
            if App.getActiveTransaction():
                App.closeActiveTransaction(True)
            s.doc.recompute()
        except Exception as e:
            s.error = f"abort failed: {e}"

    def _close_panel(self):
        s = self.session
        self._remove_box()
        try:
            gdoc = Gui.getDocument(s.doc.Name)
            if gdoc.getInEdit() is not None:
                gdoc.resetEdit()
        except Exception:
            pass
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        except Exception:
            pass

    @staticmethod
    def _restore_visibility(s):
        for name, shown in s.visibility.items():
            o = s.doc.getObject(name)
            if o is not None and getattr(o, "ViewObject", None) is not None:
                o.ViewObject.Visibility = shown

    def _rebuild(self, mode, plan, tries):
        s = self.session
        if s is None:
            return
        busy = False
        try:
            busy = bool(Gui.Control.activeDialog()) or Gui.getDocument(s.doc.Name).getInEdit() is not None
        except Exception:
            pass
        if busy and tries < 40:
            QtCore.QTimer.singleShot(50, lambda: self._rebuild(mode, plan, tries + 1))
            return
        s.mode, s.swapping, s.notice, s.error, s.warnings = mode, False, None, None, []
        self._guarded(s, lambda s: self._build(plan))

    # ---------------------------------------------------------- panel
    def _dialog_content(self):
        try:
            dlg = Gui.Control.activeTaskDialog()
            return list(dlg.getDialogContent()) if dlg is not None else []
        except Exception:
            return []

    def _attach(self):
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping or _alive(s.box):
            return
        content = [w for w in self._dialog_content() if w is not None]
        if not content:
            return
        anchor = content[0]
        parent = anchor.parentWidget()
        lay = parent.layout() if parent is not None else None
        if lay is None:
            return
        s.anchor = anchor
        f = s.feature()
        if f is not None:
            s.adapter.sync(s, f)
        s.box = CommandBox(self, s)
        lay.insertWidget(max(lay.indexOf(anchor), 0), s.box)
        if self.cancel_filter is None:
            self.cancel_filter = _CancelFilter(self)
        try:
            Gui.Control.activeTaskDialog().setEscapeButtonEnabled(False)
        except Exception:
            pass
        dock = _tasks_dock()
        s.filtered = [QtWidgets.QApplication.instance()]
        if dock is not None:
            s.filtered += [bb.button(QtWidgets.QDialogButtonBox.Cancel)
                           for bb in dock.findChildren(QtWidgets.QDialogButtonBox)
                           if bb.button(QtWidgets.QDialogButtonBox.Cancel) is not None]
        for w in s.filtered:
            w.installEventFilter(self.cancel_filter)
        for w in anchor.findChildren(QtWidgets.QAbstractSpinBox):
            name = w.objectName().lower()
            if any(n in name for n in s.adapter.LENGTH_FIELDS) and w.lineEdit() is not None:
                w.lineEdit().textEdited.connect(lambda text, n=w.objectName(): s.typed.__setitem__(n, text))
                w.editingFinished.connect(lambda w=w: self._read_back(w))
        self._highlight(s)
        s.key = None
        self.validate(force=True)
        if s.picks:                                      # picked while the panel was opening
            QtCore.QTimer.singleShot(0, self.take_picks)

    def _read_back(self, w):
        s = self.session
        if s is None or not _alive(w):
            return
        name = w.objectName()
        text = s.typed.get(name)
        read = w.property("rawValue")
        if text is None or not isinstance(read, (int, float)):
            return
        issue = core.read_back_issue(text, float(read), w.locale().decimalPoint())
        if issue:
            s.field_issues[name] = issue
        else:
            s.field_issues.pop(name, None)
        s.key = None
        self.validate(force=True)

    def _ok_button(self):
        dock = _tasks_dock()
        for box in dock.findChildren(QtWidgets.QDialogButtonBox) if dock is not None else []:
            b = box.button(QtWidgets.QDialogButtonBox.Ok)
            if b is not None:
                return b
        return None

    def validate(self, force=False):
        """validate: the error state (blocks OK) and warnings (shown, do not block)."""
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping:
            return
        f = s.feature()
        if f is None:
            return
        props = s.adapter.KEY_PROPS + ("Profile",)
        key = (tuple(str(getattr(f, p, "")) for p in props), str(f.State), tuple(s.edges or ()), s.limit_error,
               s.axis_error)
        if key == s.key and not force:
            self._show()
            return
        s.key = key
        s.adapter.sync(s, f)
        error, warnings = None, []
        section = core.section_problem(edge_records(s.sketch), s.edges) if s.sketch is not None else ""
        if section:
            error = f"Section: {section}"
        elif s.adapter.problem(s):
            error = s.adapter.problem(s)
        elif not f.isValid() or "Invalid" in f.State:
            error = f"FreeCAD cannot build it: {f.getStatusString() or 'invalid parameters'}"
        elif s.mode in ("unite", "subtract"):
            solids = _solids(f)
            if s.mode == "unite" and len(solids) > s.base_solids:
                error = (f"Unite would leave a separate solid: the {s.adapter.NOUN} does not touch the part "
                         "(choose None for a new body)")
            else:
                w = core.result_warning(s.mode, s.base_volume, _volume(f), noun=s.adapter.NOUN)
                if w:
                    warnings.append(w)
        if s.notice:
            warnings.insert(0, s.notice)
        warnings += list(s.field_issues.values())
        s.error, s.warnings = error, warnings
        self._show()

    def _show(self):
        s = self.session
        if s is None:
            return
        if _alive(s.box):
            s.box.refresh(s)
        ok = self._ok_button()
        if ok is not None and _alive(ok):
            ok.setEnabled(s.error is None)
            ok.setToolTip(s.error or "")

    def _remove_box(self, s=None):
        s = s or self.session
        if s is None:
            return
        if _alive(s.box):
            s.box.setParent(None)
            s.box.deleteLater()
        for w in s.filtered:
            if _alive(w) and self.cancel_filter is not None:
                w.removeEventFilter(self.cancel_filter)
        s.box = s.anchor = None
        s.filtered = []

    # ---------------------------------------------------------- watching
    def _start_timer(self):
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.setInterval(150)
            self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _watch(self):
        if self.observer is None:
            self.observer = _Observer(self)
            App.addDocumentObserver(self.observer)

    def _unwatch(self):
        if self.observer is not None:
            try:
                App.removeDocumentObserver(self.observer)
            except Exception:
                pass
            self.observer = None

    def _dialog_open(self):
        s = self.session
        try:
            if not Gui.Control.activeDialog():
                return False
        except Exception:
            return False
        return s.anchor is None or _alive(s.anchor)

    def _poll(self):
        s = self.session
        if s is None:
            if self.timer is not None:
                self.timer.stop()
            return
        if s.doc is None or s.doc.Name not in App.listDocuments():
            self._end("cancelled", "the document was closed")
            return
        if s.stage == "select":
            from . import commands
            if commands.pending_feature["command"] != self._section_done:
                self._end("cancelled", "no section: the plane pick or the sketch was cancelled")
                return
            # the plane pick cancelled: no task panel and no sketch open for ten polls (the shell's own check
            # waits for its idle ticks, which a panel elsewhere can keep resetting)
            try:
                busy = bool(Gui.Control.activeDialog()) or Gui.getDocument(s.doc.Name).getInEdit() is not None
            except Exception:
                busy = False
            s.idle = 0 if busy else getattr(s, "idle", 0) + 1
            if s.idle > 10:
                commands.pending_feature["command"] = None
                self._end("cancelled", "no section: the plane pick was cancelled")
            return
        if s.stage != "parameterize" or s.swapping:
            return
        if not self._dialog_open():
            self._finish()
            return
        if not _alive(s.box):
            self._attach()
        else:
            self.validate()

    # ---------------------------------------------------------- commit / cancel
    def _finish(self, force=False):
        s = self.session
        name = s.adapter.name if not s.edit else "Edit " + s.adapter.name
        note = ""
        try:
            pending = App.getActiveTransaction() is not None
        except Exception:
            pending = False
        if pending and not s.cancelled:
            # PartDesign's OK leaves edit mode before it commits, and leaving edit mode lets the event loop run
            # (the workbench switches back), so the panel can be gone a moment before the commit. Never abort
            # here (measured: that threw away committed extrudes); wait for the commit, then report.
            s.waits = getattr(s, "waits", 0) + 1
            if s.waits < 14 and not force:
                return
            note = "the panel closed with the transaction still open; left to FreeCAD"
        f = s.feature()
        # not from the undo count: FreeCAD's undo list has a size limit, and a full one stops growing
        outcome = "cancelled" if s.cancelled or f is None else "committed"
        grew = bool(core.undo_steps_added(s.undo_names, s.doc.UndoNames))
        if outcome == "committed" and grew and s.doc.UndoNames and s.doc.UndoNames[0] != name:
            note = (note + "; " if note else "") + f"undo step is '{s.doc.UndoNames[0]}', not '{name}'"
        self._end(outcome, note)

    def _end(self, outcome, note=""):
        s = self.session
        self.session = None
        if self.timer is not None:
            self.timer.stop()
        self._unwatch()
        self._unlisten()
        if s is None:
            return
        self._remove_box(s)
        s.stage = outcome
        doc_open = s.doc is not None and s.doc.Name in App.listDocuments()
        f = s.feature() if doc_open else None
        if outcome == "committed" and f is not None:
            # The active Body stays the one the user works in: a New Body is a result, not a change of the
            # work body (making it active left no active Body once its extrude was undone, and FreeCAD then
            # refused the next sketch). The selection is left alone too: the next command may already have
            # been given one (a face picked right after OK reaches here before this command noticed).
            s.result_body = body_of(f).Name if body_of(f) is not None else None
            if s.edges is not None:
                if self._highlighted(s):
                    Gui.Selection.clearSelection()       # only the section's highlight: a next X must not reuse it
                # PartDesign's OK hides the profile; a sketch used in part stays as it was (NX), its other curves
                # are still to be picked
                vo = getattr(s.sketch, "ViewObject", None)
                if vo is not None and s.visibility.get(s.sketch.Name):
                    vo.Visibility = True
        elif outcome in ("cancelled", "failed") and doc_open:
            self._restore_visibility(s)
            if s.edges is not None:
                Gui.Selection.clearSelection()           # the section's highlight, not a pick of the user's
            if not Gui.Selection.getSelectionEx("", 0):       # nothing picked since: put the old selection back
                for d, o, sub in s.selection:
                    try:
                        if App.getDocument(d).getObject(o) is not None:
                            Gui.Selection.addSelection(d, o, sub)
                    except Exception:
                        pass
            try:
                if s.active_body is not None:
                    Gui.getDocument(s.doc.Name).ActiveView.setActiveObject("pdbody", s.active_body)
            except Exception:
                pass
        self._restore_gate(s)
        result = {"command": s.adapter.name, "edit": s.edit, "outcome": outcome, "mode": s.mode,
                  "document": s.doc.Name if doc_open else None, "body": s.result_body,
                  "feature": s.feature_name if f is not None else None,
                  "section": (s.sketch.Name if s.sketch is not None and doc_open else None,
                              list(s.edges) if s.edges is not None else None),
                  "undo": (s.doc.UndoNames[0] if doc_open and s.doc.UndoNames else None),
                  # from the names: a full undo list keeps its count when a step is added
                  "undo_steps": core.undo_steps_added(s.undo_names, s.doc.UndoNames) if doc_open else None,
                  "error": s.error, "warnings": list(s.warnings), "note": note}
        self.history.append(result)
        self.log(f"end {result['command']}{' edit' if s.edit else ''}: {outcome} {s.mode} {note}".rstrip())
        # FreeCAD refreshed the commands' enabled state when the panel closed, while this command still counted
        # as running: refresh again, or X and Edit Parameters stay greyed out until something else changes
        QtCore.QTimer.singleShot(0, _update_commands)
        label = ("Edit " if s.edit else "") + s.adapter.name
        _status(f"{label}: {outcome}" + (f" ({core.LABELS.get(s.mode, s.mode)})" if s.mode else "")
                + (f"; {note}" if note else ""))

    # ---------------------------------------------------------- selection scope
    @staticmethod
    def _type_filter_widget():
        try:
            from . import shell
            return getattr(shell.instance(), "type_filter", None)
        except Exception:
            return None

    def _suspend_gate(self):
        """Lift the user's Type Filter (the selection manager's global layer) while the command picks its own
        inputs; the Selection Scope stays in force. The Top Border Bar's filter is greyed out meanwhile."""
        s = self.session
        m = selection_filter.manager()
        if m.global_kind is None:
            return
        s.gate_kind = m.global_kind
        m.set_global(kind=None)
        tf = self._type_filter_widget()
        if tf is not None:
            tf.setEnabled(False)
            tf.setToolTip("Type Filter: off while the command picks its own inputs")
        self.log(f"Type Filter {selection_filter.TYPE_LABELS.get(s.gate_kind, s.gate_kind)} lifted")

    def _restore_gate(self, s):
        if s.gate_kind is None:
            return
        tf = self._type_filter_widget()
        try:
            # the filter the Top Border Bar shows: the user's choice, which lifting it did not change
            kind = tf.itemData(tf.currentIndex()) if tf is not None else s.gate_kind
            m = selection_filter.manager()
            if m.global_kind != kind:
                # while FreeCAD's panel is still closing the manager waits for it, then installs the gate
                m.set_global(kind=kind)
        except Exception as e:
            self.log(f"Type Filter not restored: {e}")
        if tf is not None:
            tf.setEnabled(True)
            tf.setToolTip("Type Filter: limit what can be selected")


CONTROLLER = Controller()


# --------------------------------------------------------------------------
# Part Navigator / graphics window MB3 menu
# --------------------------------------------------------------------------
class ContextMenu:
    """Adds Edit Parameters (through the controller) to the MB3 menu of a feature it can edit."""

    def modifyContextMenu(self, recipient):
        try:
            sel = Gui.Selection.getSelection()
        except Exception:
            return []
        if len(sel) == 1 and adapter_for(sel[0]) is not None and not CONTROLLER.busy():
            return [{"insert": "NXStyle_EditParameters", "menuItem": "Std_ToggleVisibility"}]
        return []


_menu = None


def install_context_menu():
    global _menu
    if _menu is None and hasattr(Gui, "addWorkbenchManipulator"):
        _menu = ContextMenu()
        Gui.addWorkbenchManipulator(_menu)

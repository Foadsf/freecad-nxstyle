# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's Move Object (Edit > Move Object, Ctrl+T): move the selected objects, or copies of them, by a rigid motion.

Objects are what NX selects as a body or an object: a pick on a solid's face takes its PartDesign Body; a pick on
a component in an assembly takes the link; a Part object outside a Body is itself; a sketch or a datum picked as
itself is moved alone (attached ones through their Attachment Offset, so they stay attached).

Transform, Motion (move_core):
- Distance: Specify Vector (XC ... -ZC, Reverse Direction) and the Distance;
- Angle: the same vector as the axis, Specify Axis Point, and the Angle;
- Point to Point: Specify From Point and Specify To Point, typed or picked (snapped as the Point type says);
- Dynamic: FreeCAD's Transform dragger (Std_TransformManip) in its own dialog.

Result: Move Original changes the objects' Placement; Copy Original leaves them and makes Number of Copies copies,
copy i moved i times (a Body copy is a new Body on a static copy of the solid, a Part object's copy a static Part
feature, a link's copy another link to the same object). Distance/Angle Divisions divides the motion.

The panel holds the command in one undo transaction, as the primitives do: the preview is the real move, OK (or
MB2) commits one step named Move Object, Apply commits it and keeps the dialog open with the same objects, Cancel
or Esc leaves nothing.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, move_core as core, selection_filter as sf
from .primitive_ui import (STYLE, PointStep, Step, _EscFilter, _alive, _dialog_button, _int, _update_commands, mm,
                           quantity_field, set_mm)
from .qt import QtCore, QtWidgets

HISTORY = []                     # one dict per ended command (read by the self-test and the tutorial replay)
TRACE = []                       # the last lifecycle events, for the self-test and bug reports
_remembered = {}                 # what NX keeps for the next time the dialog opens
_current = {"panel": None}

NAME = "Move Object"
TIP = ("Move Object: move the selected bodies or objects, or copies of them, by a distance along a vector, an "
       "angle about an axis, or from a point to a point (NX: Edit > Move Object, Ctrl+T)")
POINT_STEPS = {"Angle": ["point"], "Point to Point": ["from", "to"]}


def current():
    """The open Move Object panel, or None."""
    return _current["panel"]


def log(text):
    import time
    TRACE.append(f"{time.strftime('%H:%M:%S')} {text}")
    del TRACE[:-80]


def angle_field(name):
    w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    w.setObjectName(name)
    w.setProperty("unit", "deg")
    w.setProperty("minimum", -36000.0)
    w.setProperty("maximum", 36000.0)
    return w


def set_deg(w, value):
    from . import precise_input
    q = App.Units.Quantity(float(value), App.Units.Angle)
    precise_input.show_with(w, q, max(precise_input.preference_decimals(), 2))


# ------------------------------------------------------------------ placements
def pair(p):
    """A FreeCAD Placement as move_core's (t, q)."""
    return (p.Base.x, p.Base.y, p.Base.z), tuple(p.Rotation.Q)


def placement(m):
    return App.Placement(App.Vector(*m[0]), App.Rotation(*m[1]))


def parent_frame(obj):
    """The global placement of the frame obj's Placement is in (its container's)."""
    try:
        return obj.getGlobalPlacement().multiply(obj.Placement.inverse())
    except Exception:
        return App.Placement()


def local_motion(obj, m):
    """The global motion m in the frame of obj's Placement."""
    g = pair(parent_frame(obj))
    return core.compose(core.inverse(g), core.compose(m, g))


# ------------------------------------------------------------------ objects
def _attached(obj):
    return "MapMode" in obj.PropertiesList and obj.MapMode != "Deactivated"


def _is_sketch_or_datum(o):
    return o.isDerivedFrom("Sketcher::SketchObject") or o.isDerivedFrom("Part::Datum") \
        or o.TypeId in ("App::Plane", "App::Line", "App::Point")


def _in_origin(o):
    return any(p.TypeId == "App::Origin" for p in getattr(o, "InList", []))


def _placement_bound(o):
    return any(path.split(".")[0] in ("Placement", ".Placement") for path, _ in getattr(o, "ExpressionEngine", []))


def classify(pick, doc):
    """(object, kind) that a pick moves, or (None, reason). kind is a move_core.KINDS key."""
    leaf = pick.leaf
    if leaf is None:
        return None, "nothing to move"
    in_doc = [o for o in pick.objects if o is not None and o.Document is doc]
    links = [o for o in in_doc if o.isDerivedFrom("App::Link")]
    if links:                                         # a component: the innermost link of this part
        obj, kind = links[-1], "link"
    elif leaf.Document is not doc:
        return None, f"{leaf.Label} belongs to another part"
    elif _is_sketch_or_datum(leaf):
        if _in_origin(leaf):
            return None, "the origin's planes and axes do not move"
        obj, kind = leaf, ("attached" if _attached(leaf) else "placed")
    elif sf.body_of(leaf) is not None:
        obj, kind = sf.body_of(leaf), "body"
    elif leaf.isDerivedFrom("App::Part"):
        obj, kind = leaf, "link"
    elif leaf.isDerivedFrom("Part::Feature") or (hasattr(leaf, "Placement") and hasattr(leaf, "Shape")):
        obj, kind = leaf, "part"
    else:
        return None, f"{leaf.Label} has no placement to move"
    if _placement_bound(obj):
        return None, f"{obj.Label}'s Placement is set by an expression"
    return obj, kind


# ------------------------------------------------------------------ widgets
class ObjectsStep(Step):
    """NX's Select Object: picks add an object, a second pick on it takes it out again."""

    def __init__(self, panel):
        super().__init__(panel, "objects", "Select Object")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("nxObjects")
        self.list.setAccessibleName("Objects")
        self.list.setMaximumHeight(90)
        self.lay.addWidget(self.list)

    def refresh(self):
        self.list.clear()
        for name, kind in self.panel.objects:
            o = self.panel.doc.getObject(name)
            self.list.addItem(f"{o.Label if o is not None else name}  ({kind})")
        self.status.setText(f"({len(self.panel.objects)})")


# ------------------------------------------------------------------ the panel
class MovePanel:
    """The command's task panel and its session: the preview (the moved objects and their copies) lives in an
    open transaction."""

    def __init__(self, doc):
        self.doc = doc
        self.name = NAME
        self.open = False
        self.busy = False
        self.error = None
        self.warnings = []
        self.objects = []                 # [(name, kind)]
        self.copies = []                  # names of the copies the preview made
        self.previewed = False            # the open transaction holds a preview
        self.state = None
        self.applied = 0                  # Apply presses committed in this dialog
        self.token = None
        self.timer = None
        self.esc = None
        self.selection = []
        self.undo_names = list(doc.UndoNames)
        self._form()
        self._defaults()
        self.layer = sf.Layer(NAME, verdict=self.verdict, alive=lambda: self.open)

    # ------------------------------------------------------------ form
    def _form(self):
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("NXMoveObjectPanel")
        self.form.setWindowTitle(NAME)
        lay = QtWidgets.QVBoxLayout(self.form)
        box = QtWidgets.QGroupBox("Objects")
        bl = QtWidgets.QVBoxLayout(box)
        self.steps = {"objects": ObjectsStep(self)}
        bl.addWidget(self.steps["objects"])
        lay.addWidget(box)

        box = QtWidgets.QGroupBox("Transform")
        self.transform_form = QtWidgets.QFormLayout(box)
        self.motion = QtWidgets.QComboBox()
        self.motion.setObjectName("nxMotion")
        self.motion.setAccessibleName("Motion")
        self.motion.addItems(core.MOTIONS)
        self.motion.activated.connect(lambda _i: self._motion_changed())
        self.transform_form.addRow("Motion", self.motion)
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.vector = QtWidgets.QComboBox()
        self.vector.setObjectName("nxVector")
        self.vector.setAccessibleName("Specify Vector")
        for key, d in core.VECTORS:
            self.vector.addItem(key, d)
        self.vector.activated.connect(lambda _i: self._poll(force=True))
        rl.addWidget(self.vector, 1)
        self.reverse = QtWidgets.QToolButton()
        self.reverse.setObjectName("nxReverse")
        self.reverse.setText("Reverse Direction")
        self.reverse.setCheckable(True)
        self.reverse.toggled.connect(lambda _on: self._poll(force=True))
        rl.addWidget(self.reverse)
        self.vector_row = row
        self.transform_form.addRow("Specify Vector", row)
        self.steps["point"] = PointStep(self, "point", "Specify Axis Point")
        self.transform_form.addRow(self.steps["point"])
        self.steps["from"] = PointStep(self, "from", "Specify From Point")
        self.transform_form.addRow(self.steps["from"])
        self.steps["to"] = PointStep(self, "to", "Specify To Point")
        self.transform_form.addRow(self.steps["to"])
        self.distance = quantity_field("distance")
        self.transform_form.addRow("Distance", self.distance)
        self.angle = angle_field("angle")
        self.transform_form.addRow("Angle", self.angle)
        self.dynamic_note = QtWidgets.QLabel("OK hands the object to FreeCAD's Transform dragger "
                                             "(drag its arrows and rings, then close it)")
        self.dynamic_note.setWordWrap(True)
        self.transform_form.addRow(self.dynamic_note)
        lay.addWidget(box)

        box = QtWidgets.QGroupBox("Result")
        rf = QtWidgets.QFormLayout(box)
        self.result = QtWidgets.QComboBox()
        self.result.setObjectName("nxResult")
        self.result.setAccessibleName("Result")
        self.result.addItems(core.RESULTS)
        self.result.activated.connect(lambda _i: self._result_changed())
        rf.addRow(self.result)
        self.divisions = QtWidgets.QSpinBox()
        self.divisions.setObjectName("divisions")
        self.divisions.setRange(1, 1000)
        self.divisions.valueChanged.connect(lambda _v: self._poll(force=True))
        rf.addRow("Distance/Angle Divisions", self.divisions)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("copies")
        self.count.setRange(1, 1000)
        self.count.valueChanged.connect(lambda _v: self._poll(force=True))
        rf.addRow("Number of Copies", self.count)
        self.result_form = rf
        lay.addWidget(box)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("nxStatus")
        self.status.setWordWrap(True)
        self.status.setToolTip("\n".join(f"{n}: {s}" + (f" ({how})" if how else "") for n, s, how in core.OPTIONS))
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.active = "objects"

    def _defaults(self):
        vals = dict(core.DEFAULTS)
        vals.update(_remembered)
        self.motion.setCurrentIndex(max(self.motion.findText(vals["motion"]), 0))
        self.vector.setCurrentIndex(max(self.vector.findText(vals["vector"]), 0))
        self.reverse.setChecked(bool(vals.get("reverse")))
        set_mm(self.distance, vals["distance"])
        set_deg(self.angle, vals["angle"])
        self.result.setCurrentIndex(max(self.result.findText(vals["result"]), 0))
        self.count.setValue(int(vals["copies"]))
        self.divisions.setValue(int(vals["divisions"]))
        self._motion_changed(poll=False)
        self._result_changed(poll=False)

    def _show_row(self, w, shown):
        w.setVisible(shown)
        label = self.transform_form.labelForField(w)
        if label is None:
            label = self.result_form.labelForField(w)
        if label is not None:
            label.setVisible(shown)

    def _motion_changed(self, poll=True):
        m = self.motion.currentText()
        self._show_row(self.vector_row, m in ("Distance", "Angle"))
        self._show_row(self.distance, m == "Distance")
        self._show_row(self.angle, m == "Angle")
        for key in ("point", "from", "to"):
            self.steps[key].setVisible(key in POINT_STEPS.get(m, []))
        self.dynamic_note.setVisible(m == "Dynamic")
        self._show_row(self.divisions, m != "Dynamic")
        if self.active not in ("objects",) and self.steps[self.active].isHidden():
            self.active = "objects"
        if self.objects and self.active == "objects" and POINT_STEPS.get(m):
            self.active = POINT_STEPS[m][0]
        self.activate(self.active)
        if poll:
            self._poll(force=True)

    def _result_changed(self, poll=True):
        self._show_row(self.count, self.result.currentText() == "Copy Original")
        if poll:
            self._poll(force=True)

    # ------------------------------------------------------------ steps
    def activate(self, key):
        if key not in self.steps or self.steps[key].isHidden():
            return
        self.active = key
        for k, s in self.steps.items():
            s.set_active(k == key)

    def add_object(self, obj, kind, toggle=True):
        names = [n for n, _ in self.objects]
        if obj.Name in names:
            if toggle:
                self.objects = [(n, k) for n, k in self.objects if n != obj.Name]
        else:
            self.objects.append((obj.Name, kind))
        self.steps["objects"].refresh()

    # ------------------------------------------------------------ selection
    def verdict(self, pick):
        """The selection gate while the panel is open: what the highlighted step can take."""
        if self.active == "objects":
            obj, why = classify(pick, self.doc)
            return (True, "") if obj is not None else (False, why)
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
        if ok and self.active == "objects":
            target, kind = classify(pick, self.doc)
            self.add_object(target, kind)
        elif ok:
            step = self.steps[self.active]
            try:
                top = App.getDocument(doc).getObject(obj)
                shape = top.getSubObject(sf.core.plain(sub))
                picked = App.Vector(*pnt) if pnt else App.Vector()
                ok, why = step.take(shape, picked)
            except Exception as e:
                ok, why = False, str(e)
            if ok and self.active == "from" and not step.pending:
                self.activate("to")
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
        d = self.vector.currentData()
        d = tuple(-c for c in d) if self.reverse.isChecked() else tuple(d)
        v = {"motion": self.motion.currentText(), "vector": d, "axis": d, "distance": mm(self.distance),
             "angle": self.angle.property("rawValue"), "divisions": self.divisions.value(),
             "result": self.result.currentText(), "copies": self.count.value(),
             "objects": [n for n, _ in self.objects]}
        for key in ("point", "from", "to"):
            v[key] = self.steps[key].point()
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
        self.steps["objects"].refresh()
        self.error = None
        self.warnings = [w for w in self.warnings if w.startswith("Refused")]
        try:
            self._preview(v)
        except core.CommandError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            log(f"preview: {self.error}")
        self._show()

    def check(self, v):
        """The motions the values give, or CommandError with the reason; warnings go to self.warnings."""
        if not self.objects:
            raise core.CommandError("select the objects to move")
        if v["motion"] == "Dynamic":
            if len(self.objects) != 1:
                raise core.CommandError("Dynamic moves one object: select only one")
            return []
        issue = core.copy_issue({k for _, k in self.objects}, v["result"])
        if issue:
            raise core.CommandError(issue)
        if v["motion"] == "Angle" and v["point"] is None:
            raise core.CommandError("specify the axis point")
        error, warnings = core.issues(v["motion"], v, v["result"], v["copies"])
        if error:
            raise core.CommandError(error)
        self.warnings += warnings
        return core.motions(v["result"], core.step(v["motion"], v), v["copies"])

    def _preview(self, v):
        """Undo what the preview did so far (the transaction is aborted and reopened), then move or copy anew."""
        self._reset()
        motions = self.check(v)
        if not motions:
            return
        self.previewed = True
        if v["result"] == "Move Original":
            for name, kind in self.objects:
                move(self.doc.getObject(name), kind, motions[0])
        else:
            for name, kind in self.objects:
                obj = self.doc.getObject(name)
                for m in motions:
                    self.copies.append(copy(obj, kind, m).Name)
        self.doc.recompute()
        log(f"preview {v['motion']} {v['result']} on {[n for n, _ in self.objects]}"
            + (f": copies {self.copies}" if self.copies else ""))

    def _reset(self):
        """Take the preview back: the open transaction holds only the preview, so aborting it is exact."""
        if self.previewed:
            if App.getActiveTransaction():
                App.closeActiveTransaction(True)
            self.doc.recompute()
            App.setActiveTransaction(self.name, True)
        self.previewed = False
        self.copies = []

    # ------------------------------------------------------------ show
    def _show(self):
        if self.error:
            kind, text = "error", self.error
        elif self.warnings:
            kind, text = "warning", "; ".join(self.warnings)
        else:
            v = self.values()
            what = {"Distance": lambda: f"{mm(self.distance):g} mm along {self.vector.currentText()}"
                    + (" reversed" if self.reverse.isChecked() else ""),
                    "Angle": lambda: f"{v['angle']:g} deg about {self.vector.currentText()}",
                    "Point to Point": lambda: "from point to point",
                    "Dynamic": lambda: "with FreeCAD's dragger (after OK)"}[v["motion"]]()
            n = len(self.objects)
            result = (f"{v['copies']} cop{'y' if v['copies'] == 1 else 'ies'} of" if v["result"] == "Copy Original"
                      else "moves")
            kind, text = "ok", f"{result} {n} object{'s' if n != 1 else ''} {what}: ready (OK or MB2 commits one " \
                               "undo step)"
        if _alive(self.status):
            self.status.setText(text)
            self.status.setStyleSheet(STYLE[kind])
        ok = _dialog_button(QtWidgets.QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(self.error is None)
            ok.setToolTip(self.error or "")
        apply = _dialog_button(QtWidgets.QDialogButtonBox.Apply)
        if apply is not None:
            apply.setEnabled(self.error is None and self.motion.currentText() != "Dynamic")

    # ------------------------------------------------------------ life cycle
    def begin(self):
        self.open = True
        self.esc = _EscFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self.esc)
        self.token = sf.manager().push(self.layer)
        self.selection = [(x.DocumentName, x.ObjectName, sub) for x in Gui.Selection.getSelectionEx("", 0)
                          for sub in (x.SubElementNames or ("",))]
        for d, o, sub in self.selection:              # NX takes the selection as the objects
            try:
                target, kind = classify(sf.Resolved(d, o, sub), self.doc)
            except Exception:
                target = None
            if target is not None:
                self.add_object(target, kind, toggle=False)
        Gui.Selection.addObserver(self)
        Gui.Selection.clearSelection()
        self.undo_names = list(self.doc.UndoNames)
        App.setActiveTransaction(self.name, True)
        self.activate("objects")
        self._motion_changed(poll=False)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        _current["panel"] = self
        self._poll(force=True)

    def getStandardButtons(self):
        return _int(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Apply
                    | QtWidgets.QDialogButtonBox.Cancel)

    def clicked(self, button):
        log(f"button {button}")
        # FreeCAD 1.1 with PySide6 passes the StandardButton enum here, not an int
        if _int(button) == _int(QtWidgets.QDialogButtonBox.Apply):
            self.apply()

    def accept(self):
        log(f"OK (open {self.open})")
        if not self.open:
            return True
        self._poll(force=True)          # the field that still had the focus
        if self.error is not None:
            log(f"OK refused: {self.error}")
            self._show()
            return False
        if self.motion.currentText() == "Dynamic":
            name = self.objects[0][0]
            self._end("dynamic", f"handed {name} to FreeCAD's Transform dragger", abort=True)
            QtCore.QTimer.singleShot(0, lambda: dynamic(self.doc, name))
            return True
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
        """NX's Apply: commit this move and keep the dialog open with the same objects (Apply again moves them
        again, or makes more copies)."""
        self._poll(force=True)
        if self.error is not None or not self.open or self.motion.currentText() == "Dynamic":
            self._show()
            return False
        self._commit()
        self._record("committed")
        self.applied += 1
        self.copies = []
        self.previewed = False                    # committed: no longer the preview's to take back
        self.undo_names = list(self.doc.UndoNames)
        App.setActiveTransaction(self.name, True)
        self.state = None
        self._poll(force=True)
        return True

    def _commit(self):
        App.closeActiveTransaction(False)
        v = self.values()
        _remembered.update({"motion": v["motion"], "vector": self.vector.currentText(),
                            "reverse": self.reverse.isChecked(), "distance": v["distance"], "angle": v["angle"],
                            "result": v["result"], "copies": v["copies"], "divisions": v["divisions"]})

    def _end(self, outcome, note="", abort=False):
        if not self.open:
            return
        if abort:
            try:
                if App.getActiveTransaction():
                    App.closeActiveTransaction(True)
                if self.doc.Name in App.listDocuments():
                    self.doc.recompute()
            except Exception as e:
                note = (note + "; " if note else "") + f"abort failed: {e}"
            self.copies = []
        self.open = False
        if self.timer is not None:
            self.timer.stop()
        if self.esc is not None:
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
        log(f"{outcome} {self.motion.currentText()} {self.result.currentText()} {note}".rstrip())
        from .command_core import undo_steps_added
        doc_open = self.doc.Name in App.listDocuments()
        placements = {}
        if doc_open:
            for name in [n for n, _ in self.objects] + self.copies:
                o = self.doc.getObject(name)
                if o is not None:
                    p = o.Placement
                    placements[name] = (tuple(p.Base), tuple(p.Rotation.Q))
        HISTORY.append({"command": NAME, "outcome": outcome, "motion": self.motion.currentText(),
                        "result": self.result.currentText(), "objects": [n for n, _ in self.objects],
                        "kinds": [k for _, k in self.objects],
                        "copies": list(self.copies) if outcome == "committed" else [],
                        "placements": placements,
                        "undo": self.doc.UndoNames[0] if doc_open and self.doc.UndoNames else None,
                        "undo_steps": undo_steps_added(self.undo_names, self.doc.UndoNames) if doc_open else None,
                        "error": self.error, "warnings": list(self.warnings), "note": note})
        del HISTORY[:-50]


# ------------------------------------------------------------------ moving and copying
def move(obj, kind, m):
    """Move obj by the global motion m: its Placement, or its Attachment Offset when it is attached."""
    local = local_motion(obj, m)
    if _attached(obj):
        obj.AttachmentOffset = placement(core.moved_offset(local, pair(obj.Placement), pair(obj.AttachmentOffset)))
    else:
        obj.Placement = placement(core.moved(local, pair(obj.Placement)))


def _container(obj):
    try:
        return obj.getParentGeoFeatureGroup()
    except Exception:
        return None


def _copy_look(src, dst):
    if getattr(src, "ViewObject", None) is None or getattr(dst, "ViewObject", None) is None:
        return
    for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
        try:
            setattr(dst.ViewObject, prop, getattr(src.ViewObject, prop))
        except Exception:
            pass


def copy(obj, kind, m):
    """A copy of obj moved by the global motion m, in obj's container; returns the copy.

    - body: a new PartDesign Body whose base feature is a static copy of the solid (NX's copy is not associative
      either), so the copy is a body NX-Style's commands can keep modelling;
    - part: a static Part feature with the shape (Part's Simple Copy);
    - link: another link to the same object (a component's copy in an assembly)."""
    doc = obj.Document
    local = local_motion(obj, m)
    where = placement(core.moved(local, pair(obj.Placement)))
    parent = _container(obj)
    if kind == "body":
        shape = obj.Shape.copy()
        shape.transformShape(obj.Placement.inverse().toMatrix())       # into the body's own coordinates
        base = doc.addObject("Part::Feature", "MovedSolid")
        base.Label = f"{obj.Label} solid"
        base.Shape = shape
        new = doc.addObject("PartDesign::Body", "Body")
        if parent is not None:
            parent.addObject(base)
            parent.addObject(new)
        new.BaseFeature = base
        new.Placement = where
        if getattr(base, "ViewObject", None) is not None:
            base.ViewObject.Visibility = False
        _copy_look(obj, new)
        tip = getattr(obj, "Tip", None)
        if tip is not None:
            _copy_look(tip, new.Tip if new.Tip is not None else new)
        return new
    if kind == "part":
        new = doc.addObject("Part::Feature", obj.Name)
        new.Label = f"{obj.Label} copy"
        new.Shape = obj.Shape.copy()
        new.Placement = where
        if parent is not None:
            parent.addObject(new)
        _copy_look(obj, new)
        return new
    if kind == "link":
        target = obj.LinkedObject if obj.isDerivedFrom("App::Link") else obj
        new = doc.addObject("App::Link", obj.Name)
        new.LinkedObject = target
        new.Label = f"{obj.Label} copy"
        new.Placement = where
        if parent is not None:
            parent.addObject(new)
        return new
    raise core.CommandError(f"{obj.Label} cannot be copied ({core.KINDS.get(kind, kind)})")


def dynamic(doc, name):
    """Motion Dynamic: FreeCAD's Transform dragger (what Std_TransformManip opens) on the object."""
    obj = doc.getObject(name)
    if obj is None or Gui.Control.activeDialog():
        return False
    gdoc = Gui.getDocument(doc.Name)
    if gdoc.getInEdit() is not None:
        gdoc.resetEdit()
    return bool(gdoc.setEdit(obj, 1))                 # ViewProvider::Transform


# ------------------------------------------------------------------ start, command
def start(doc=None):
    """Open the Move Object panel on the selection. Returns the panel, or None."""
    doc = doc or App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    panel = MovePanel(doc)
    Gui.Control.showDialog(panel)
    try:
        panel.begin()
    except Exception as e:
        import traceback
        App.Console.PrintError(f"NXStyle: Move Object could not start: {e}\n{traceback.format_exc()}")
        panel.error = f"Move Object could not start: {type(e).__name__}: {e}"
        panel._end("failed", panel.error, abort=True)
        Gui.Control.closeDialog()
        return None
    return panel


class MoveObjectCommand:
    def GetResources(self):
        nx = config.get().get("labels") != "freecad"
        return {"MenuText": NAME if nx else core.FREECAD_NAME, "ToolTip": TIP,
                "Pixmap": "Std_TransformManip"}

    def IsActive(self):
        # NX opens Move Object with nothing selected too (it asks for the objects): the command does not wait for
        # FreeCAD's timer to see the selection, so Ctrl+T right after a pick still runs
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        start()


COMMANDS = {"NXStyle_MoveObject": MoveObjectCommand()}

# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX's Thread (Home > Feature, Insert > Design Feature > Thread): a thread on a picked cylindrical face.

- Detailed: a PartDesign SubtractiveHelix of a thread profile, so the thread is real geometry and stays a feature
  that Edit Parameters reopens (thread_feature.make_detailed).
- Symbolic: the cylinder keeps its shape; a feature in the Body records the thread (thread_feature.make_symbolic).

Picking the cylinder fills Major Diameter, Minor Diameter, Pitch, Angle and Length from the nearest standard
thread (thread_core.nearest) and puts the start at the cylinder's end nearest the pick; Select Start takes the
other end's face, Reverse Thread Direction flips it. The panel holds the command in one undo transaction: OK (or
MB2) commits one step named Thread, Apply commits it and starts the next, Cancel or Esc leaves nothing.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, precise_input, selection_filter as sf, thread_core as core, thread_feature as tf
from .primitive_ui import (STYLE, Step, _EscFilter, _alive, _dialog_button, _ensure_partdesign, _int,
                           _update_commands, body_of, mm, quantity_field, set_mm, solid_tip)
from .qt import QtCore, QtWidgets

HISTORY = []                     # one dict per ended command (read by the self-test and the tutorial replay)
TRACE = []                       # the last lifecycle events, for the self-test and bug reports
_remembered = {}                 # what NX keeps for the next time the dialog opens: the Thread Type and Rotation
_current = {"panel": None}

NAME = "Thread"
TIP = ("Thread: a Detailed (helical) or Symbolic (recorded) thread on a cylindrical face; the values come from the "
       "nearest standard thread (NX: Insert > Design Feature > Thread)")
FIELDS = [("majorDiameter", "Major Diameter"), ("minorDiameter", "Minor Diameter"), ("pitch", "Pitch"),
          ("angle", "Angle"), ("length", "Length")]
KEYS = {"majorDiameter": "major", "minorDiameter": "minor", "pitch": "pitch", "angle": "angle", "length": "length"}
CUSTOM = "Custom"


def current():
    """The open Thread panel, or None."""
    return _current["panel"]


def log(text):
    import time
    TRACE.append(f"{time.strftime('%H:%M:%S')} {text}")
    del TRACE[:-80]


def set_deg(w, value):
    q = App.Units.Quantity(float(value), App.Units.Angle)
    precise_input.show_with(w, q, max(precise_input.preference_decimals(), 2))


def angle_field(name):
    w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    w.setObjectName(name)
    w.setProperty("unit", "deg")
    w.setProperty("minimum", 0.0)
    w.setProperty("maximum", 180.0)
    return w


def _face(pick):
    try:
        return pick.top_obj.getSubObject(pick.sub)
    except Exception:
        return None


class ThreadPanel:
    """The command's task panel and its session: the preview feature lives in an open transaction."""

    def __init__(self, feature=None):
        self.edit = feature is not None
        self.doc = feature.Document if feature is not None else App.ActiveDocument
        self.name = ("Edit " if self.edit else "") + NAME
        self.feature_name = feature.Name if feature is not None else None
        self.sketch_name = None
        self.body_name = None
        self.open = False
        self.busy = False
        self.error = None
        self.warnings = []
        self.visibility = {}
        self.base_volume, self.base_solids = 0.0, 0
        self.built = None                 # the Thread Type of the preview that exists
        self.state = None
        self.cyl = None                   # the picked cylinder: thread_feature.cylinder() in global coordinates
        self.picked = None                # the picked point (global)
        self.start_s = None               # Select Start: the end the picked face is on
        self.place = None                 # (start, direction) in Body coordinates, Edit Parameters
        self.available = None
        self.committed = []
        self.token = None
        self.timer = None
        self.selection = []
        self.undo_names = list(self.doc.UndoNames) if self.doc is not None else []
        self._form()
        if self.edit:
            self._load(feature)
        else:
            self._defaults()
        self.layer = sf.Layer(NAME, verdict=self.verdict, alive=lambda: self.open)

    # ------------------------------------------------------------ form
    def _form(self):
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("NXThreadPanel")
        self.form.setWindowTitle(self.name)
        lay = QtWidgets.QVBoxLayout(self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Thread Type"))
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName("threadType")
        self.type.setAccessibleName("Thread Type")
        self.type.addItems(core.THREAD_TYPES)
        self.type.activated.connect(lambda _i: self._poll(force=True))
        row.addWidget(self.type, 1)
        lay.addLayout(row)

        self.steps = {"cylinder": Step(self, "cylinder", "Select Cylinder")}
        lay.addWidget(self.steps["cylinder"])

        box = QtWidgets.QGroupBox("Thread")
        form = QtWidgets.QFormLayout(box)
        self.table = QtWidgets.QComboBox()
        self.table.setObjectName("threadTable")
        self.table.setAccessibleName("Standard thread")
        self.table.setToolTip("The standard thread the values come from (ISO 261 coarse, ASME B1.1 UNC); choosing "
                              "one fills in the diameters, the pitch and the angle")
        self.table.addItems([t.callout for t in core.table()] + [CUSTOM])
        self.table.activated.connect(lambda _i: self._table_chosen())
        form.addRow("Standard", self.table)
        self.fields = {}
        for key, label in FIELDS:
            w = angle_field(key) if key == "angle" else quantity_field(key, minimum=0.0)
            form.addRow(label, w)
            self.fields[key] = w
        self.rotation = QtWidgets.QComboBox()
        self.rotation.setObjectName("rotation")
        self.rotation.setAccessibleName("Rotation")
        self.rotation.addItems(core.ROTATIONS)
        self.rotation.activated.connect(lambda _i: self._poll(force=True))
        form.addRow("Rotation", self.rotation)
        lay.addWidget(box)

        box = QtWidgets.QGroupBox("Start")
        bl = QtWidgets.QVBoxLayout(box)
        self.steps["start"] = Step(self, "start", "Select Start")
        bl.addWidget(self.steps["start"])
        self.reverse = QtWidgets.QToolButton()
        self.reverse.setObjectName("nxReverse")
        self.reverse.setText("Reverse Thread Direction")
        self.reverse.setCheckable(True)
        self.reverse.toggled.connect(lambda _on: self._poll(force=True))
        bl.addWidget(self.reverse)
        lay.addWidget(box)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("nxStatus")
        self.status.setWordWrap(True)
        self.status.setToolTip("\n".join(f"{n}: {s}" + (f" ({how})" if how else "") for n, s, how in core.OPTIONS))
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.active = "cylinder"

    def _defaults(self):
        kept = _remembered
        self.type.setCurrentIndex(max(self.type.findText(kept.get("type", "Symbolic")), 0))
        self.rotation.setCurrentIndex(max(self.rotation.findText(kept.get("rotation", "Right Hand")), 0))
        for key, w in self.fields.items():
            set_deg(w, 60.0) if key == "angle" else set_mm(w, 0.0)
        self.table.setCurrentIndex(self.table.findText(CUSTOM))
        self._refresh_steps()

    def _load(self, feature):
        """Edit Parameters: the dialog shows the thread as it is. The cylinder and the type stay; the values,
        the rotation and the direction can change."""
        rec = tf.read_record(feature)
        body = body_of(feature)
        self.body_name = body.Name
        if rec["NX_ThreadType"] == "Detailed":
            prof = getattr(feature, "Profile", None)
            self.sketch_name = prof[0].Name if prof else None
        self.type.setCurrentIndex(self.type.findText(rec["NX_ThreadType"]))
        self.type.setEnabled(False)
        self.type.setToolTip("Changing the Thread Type of an existing thread is not supported: delete it and make "
                             "it again")
        self.rotation.setCurrentIndex(max(self.rotation.findText(rec["NX_Rotation"]), 0))
        for key, prop in (("majorDiameter", "NX_MajorDiameter"), ("minorDiameter", "NX_MinorDiameter"),
                          ("pitch", "NX_Pitch"), ("length", "NX_Length")):
            set_mm(self.fields[key], rec[prop])
        set_deg(self.fields["angle"], rec["NX_Angle"])
        self.place = (App.Vector(rec["NX_Start"]), App.Vector(rec["NX_Direction"]))
        self.available = rec["NX_Available"]
        self.surface, self.internal = rec["NX_Surface"], bool(rec["NX_Internal"])
        self.built = rec["NX_ThreadType"]
        self._sync_table()
        for s in self.steps.values():
            s.button.setEnabled(False)
        self.steps["cylinder"].status.setText("(1) as built")
        self.steps["start"].status.setText("(1) as built")

    # ------------------------------------------------------------ steps
    def activate(self, key):
        if key not in self.steps or self.edit:
            return
        self.active = key
        for k, s in self.steps.items():
            s.set_active(k == key)

    def _refresh_steps(self):
        if self.edit:
            return
        n = 1 if self.cyl is not None else 0
        what = ""
        if self.cyl is not None:
            what = f"  {'hole' if self.cyl['internal'] else 'shaft'}, diameter {2 * self.cyl['radius']:g}"
        self.steps["cylinder"].status.setText(f"({n}){what}")
        self.steps["start"].status.setText("(1) picked face" if self.start_s is not None else
                                           ("(0) the end nearest the pick" if self.cyl is not None else "(0)"))
        self.activate(self.active)

    # ------------------------------------------------------------ selection
    def verdict(self, pick):
        """The selection gate while the panel is open: what the highlighted step can take."""
        if pick.kind != "face":
            return False, f"{self.steps[self.active].button.text()} takes a face"
        if pick.body is None or solid_tip(pick.body) is None:
            return False, f"{pick.label} is not on a body with a solid"
        face = _face(pick)
        kind = type(getattr(face, "Surface", None)).__name__
        if self.active == "cylinder" and kind != "Cylinder":
            return False, "Select Cylinder takes a cylindrical face"
        if self.active == "start":
            if self.cyl is None:
                return False, "select the cylinder first"
            if kind != "Plane":
                return False, "Select Start takes a planar face at an end of the cylinder"
        return True, ""

    def addSelection(self, doc, obj, sub, pnt=None):
        if self.busy or not self.open or self.edit:
            return
        try:
            pick = sf.Resolved(doc, obj, sub)
        except Exception:
            return
        ok, why = self.verdict(pick)
        if ok:
            try:
                face = _face(pick)
                if self.active == "cylinder":
                    self._take_cylinder(pick, face, App.Vector(*pnt) if pnt else None)
                else:
                    self.start_s = tf.start_from_face(self.cyl, face)
                    self.reverse.blockSignals(True)
                    self.reverse.setChecked(False)
                    self.reverse.blockSignals(False)
            except core.CommandError as e:
                ok, why = False, str(e)
            except Exception as e:
                ok, why = False, f"{type(e).__name__}: {e}"
        self.warnings = [] if ok else [f"Refused {pick.label}: {why}"]
        self._refresh_steps()
        QtCore.QTimer.singleShot(0, self._clear_selection)
        self._poll(force=True)

    def _take_cylinder(self, pick, face, point):
        cyl = tf.cylinder(face)
        if self.body_name is not None and self.built is not None and pick.body.Name != self.body_name:
            self._abort_preview()
        self.cyl, self.body_name = cyl, pick.body.Name
        self.picked = point if point is not None else cyl["center"] + cyl["axis"] * cyl["extent"][1]
        self.start_s = None
        t = core.nearest(2 * cyl["radius"], cyl["internal"])
        set_mm(self.fields["majorDiameter"], t.major)
        set_mm(self.fields["minorDiameter"], t.minor)
        set_mm(self.fields["pitch"], t.pitch)
        set_deg(self.fields["angle"], t.angle)
        set_mm(self.fields["length"], cyl["extent"][1] - cyl["extent"][0])
        self.table.setCurrentIndex(self.table.findText(t.callout))
        log(f"cylinder {pick.label}: diameter {2 * cyl['radius']:g}, {t.callout}, internal {cyl['internal']}")

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
    def _table_chosen(self):
        t = core.find(self.table.currentText())
        if t is not None:
            set_mm(self.fields["majorDiameter"], t.major)
            set_mm(self.fields["minorDiameter"], t.minor)
            set_mm(self.fields["pitch"], t.pitch)
            set_deg(self.fields["angle"], t.angle)
        self._poll(force=True)

    def _sync_table(self):
        v = self.values()
        callout, _ = core.callout_for(v["major"] or 0, v["minor"] or 0, v["pitch"] or 0, v["angle"] or 0)
        i = self.table.findText(callout)
        self.table.setCurrentIndex(i if i >= 0 else self.table.findText(CUSTOM))

    def values(self):
        v = {KEYS[k]: (w.property("rawValue") if k == "angle" else mm(w)) for k, w in self.fields.items()}
        v["angle"] = float(v["angle"]) if isinstance(v["angle"], (int, float)) else None
        v.update(type=self.type.currentText(), rotation=self.rotation.currentText(),
                 reverse=self.reverse.isChecked())
        return v

    def _placement(self, v, body):
        """(start, direction) in Body coordinates and the available length."""
        if self.edit:
            start, d = self.place
            if v["reverse"]:
                start, d = start + d * self.available, -d
            return (start, d), self.available
        cyl = self.cyl
        if self.start_s is not None:
            s0, s1 = sorted(cyl["extent"])
            near_first = abs(self.start_s - s0) <= abs(self.start_s - s1)
            picked = cyl["center"] + cyl["axis"] * (s0 if near_first else s1)
        else:
            picked = self.picked
        start, direction, available = tf.placement_from(cyl, picked, v["reverse"])
        inv = body.getGlobalPlacement().inverse()
        return (inv.multVec(start), inv.Rotation.multVec(direction)), available

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
        key = repr(sorted((k, repr(x)) for k, x in v.items())) + repr((self.cyl is not None, self.start_s,
                                                                        self.body_name))
        if key == self.state and not force:
            return
        self.state = key
        self._sync_table()
        self.error = None
        try:
            self._update(v)
        except core.CommandError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            log(f"Thread: {self.error}")
        self._validate(v)

    def _update(self, v):
        if not self.edit and self.cyl is None:
            raise core.CommandError("select the cylinder to thread")
        core.check(v["major"], v["minor"], v["pitch"], v["angle"], v["length"])
        body = self.doc.getObject(self.body_name)
        place, available = self._placement(v, body)
        core.check_length(v["length"], available)
        surface = self.surface if self.edit else self.cyl["radius"]
        internal = self.internal if self.edit else self.cyl["internal"]
        p = tf.thread_parameters(v, place, surface, internal)
        core.profile(p["major"], p["minor"], p["pitch"], p["angle"], internal, surface)   # its errors first
        if not self.edit and self.built != v["type"]:
            self._rebuild(v["type"], body, p)
        f = self.feature()
        if f is None:
            raise core.CommandError("nothing to build yet")
        if v["type"] == "Detailed":
            tf.apply_detailed(f, self.doc.getObject(self.sketch_name), p)
        callout, standard = core.callout_for(v["major"], v["minor"], v["pitch"], v["angle"])
        rec = core.record(v["type"], core.Thread(callout, standard, v["major"], v["minor"], v["pitch"],
                                                 v["angle"]), v["length"], v["rotation"], internal)
        rec.update(NX_Start=tuple(place[0]), NX_Direction=tuple(place[1]), NX_Surface=surface,
                   NX_Available=available)
        tf.write_record(f, rec)
        self.doc.recompute()
        self.params = p

    def feature(self):
        try:
            return self.doc.getObject(self.feature_name) if self.feature_name else None
        except Exception:
            return None

    # ------------------------------------------------------------ build
    def _abort_preview(self):
        self._restore_visibility()
        if App.getActiveTransaction():
            App.closeActiveTransaction(True)
        self.doc.recompute()
        App.setActiveTransaction(self.name, True)
        self.feature_name = self.sketch_name = None
        self.built = None

    def _rebuild(self, kind, body, p):
        """Replace the preview for a new Thread Type: the transaction so far is aborted, so nothing of the
        previous one is left, and a new one is opened."""
        if self.built is not None:
            self._abort_preview()
        prev = solid_tip(body)
        if prev is None:
            raise core.CommandError(f"{body.Label} has no solid to thread")
        self._remember_visibility(prev)
        self.base_volume = tf.volume(prev)
        self.base_solids = len(prev.Shape.Solids)
        if kind == "Detailed":
            sketch, f = tf.make_detailed(body, p)
            self.sketch_name = sketch.Name
        else:
            f = tf.make_symbolic(body)
        self.feature_name = f.Name
        self.built = kind
        if getattr(prev, "ViewObject", None) is not None and getattr(f, "ViewObject", None) is not None:
            for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                try:
                    setattr(f.ViewObject, prop, getattr(prev.ViewObject, prop))
                except Exception:
                    pass
            prev.ViewObject.Visibility = False
            f.ViewObject.Visibility = True
        log(f"Thread: built {kind} {f.Name} in {body.Name}")

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

    # ------------------------------------------------------------ validate
    def _validate(self, v):
        refused = [w for w in self.warnings if w.startswith("Refused")]
        self.warnings = []
        f = self.feature()
        if self.error is None and f is not None:
            if not f.isValid():
                self.error = f"FreeCAD cannot build it: {f.getStatusString() or 'invalid parameters'}"
            else:
                try:
                    solids = f.Shape.Solids if not f.Shape.isNull() else []
                except Exception:
                    solids = []
                vol = sum(s.Volume for s in solids)
                if len(solids) != 1:
                    self.error = f"the thread leaves {len(solids)} solids"
                elif v["type"] == "Detailed" and vol >= self.base_volume - 1e-9 * max(1.0, self.base_volume):
                    self.error = "the thread removes nothing: it does not reach the cylinder"
                elif v["type"] == "Symbolic" and abs(vol - self.base_volume) > 1e-9 * max(1.0, self.base_volume):
                    self.error = "a symbolic thread must not change the solid"
        if self.error is None:
            surface = self.surface if self.edit else self.cyl["radius"]
            internal = self.internal if self.edit else self.cyl["internal"]
            issue = core.surface_issue(v["major"], v["minor"], 2 * surface, internal)
            if issue:
                self.warnings.append(issue)
        self.warnings += refused
        self._show()

    def _show(self):
        if self.error:
            kind, text = "error", self.error
        elif self.warnings:
            kind, text = "warning", "; ".join(self.warnings)
        else:
            v = self.values()
            callout = core.callout_for(v["major"], v["minor"], v["pitch"], v["angle"])[0]
            kind, text = "ok", (f"{v['type']} {callout}, {v['rotation']}, length {v['length']:g}: ready "
                                "(OK or MB2 commits one undo step)")
        if _alive(self.status):
            self.status.setText(text)
            self.status.setStyleSheet(STYLE[kind])
        for which in (QtWidgets.QDialogButtonBox.Ok, QtWidgets.QDialogButtonBox.Apply):
            b = _dialog_button(which)
            if b is not None:
                b.setEnabled(self.error is None)
                b.setToolTip(self.error or "")

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
            base = getattr(self.feature(), "BaseFeature", None)
            self.base_volume = tf.volume(base) if base is not None else 0.0
            self.base_solids = len(base.Shape.Solids) if base is not None else 0
        self.activate("cylinder")
        self.timer = QtCore.QTimer()
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._poll(force=True)
        _current["panel"] = self
        if not self.edit:
            self._take_preselected()

    def _take_preselected(self):
        """A cylindrical face selected before the command is taken as the cylinder (NX's preselection)."""
        for d, o, sub in self.selection:
            if sub:
                self.addSelection(d, o, sub, None)
                if self.cyl is not None:
                    break

    def getStandardButtons(self):
        b = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        if not self.edit:
            b = b | QtWidgets.QDialogButtonBox.Apply
        return _int(b)

    def clicked(self, button):
        log(f"Thread: button {button}")
        # FreeCAD 1.1 with PySide6 passes the StandardButton enum here, not an int
        if _int(button) == _int(QtWidgets.QDialogButtonBox.Apply):
            self.apply()

    def accept(self):
        log(f"Thread: OK (open {self.open})")
        if not self.open:
            return True
        self._poll(force=True)          # the field that still had the focus
        if self.error is not None:
            log(f"Thread: OK refused: {self.error}")
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
        """NX's Apply: commit this thread and start the next one with the same type and rotation."""
        self._poll(force=True)
        if self.error is not None or not self.open:
            self._show()
            return False
        self._commit()
        self._record("committed")
        self.visibility = {}
        self.feature_name = self.sketch_name = self.body_name = None
        self.built = None
        self.cyl = self.picked = self.start_s = None
        self.undo_names = list(self.doc.UndoNames)
        App.setActiveTransaction(self.name, True)
        self.activate("cylinder")
        self._refresh_steps()
        self._poll(force=True)
        return True

    def _commit(self):
        App.closeActiveTransaction(False)
        f = self.feature()
        if f is not None:
            self.committed.append(f)
        if not self.edit:
            _remembered.update(type=self.type.currentText(), rotation=self.rotation.currentText())

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
        log(f"{self.name}: {outcome} {self.built} {self.feature_name} {note}".rstrip())
        from .command_core import undo_steps_added
        doc_open = self.doc.Name in App.listDocuments()
        f = self.feature() if doc_open and outcome == "committed" else None
        v = self.values()
        HISTORY.append({"command": NAME, "edit": self.edit, "outcome": outcome, "type": v["type"],
                        "feature": f.Name if f is not None else None, "sketch": self.sketch_name if f else None,
                        "body": self.body_name if f is not None else None,
                        "callout": core.callout_for(v["major"] or 0, v["minor"] or 0, v["pitch"] or 0,
                                                    v["angle"] or 0)[0],
                        "values": {k: v[k] for k in ("major", "minor", "pitch", "angle", "length", "rotation")},
                        "undo": self.doc.UndoNames[0] if doc_open and self.doc.UndoNames else None,
                        "undo_steps": undo_steps_added(self.undo_names, self.doc.UndoNames) if doc_open else None,
                        "error": self.error, "warnings": list(self.warnings), "note": note})
        del HISTORY[:-50]


# ------------------------------------------------------------------ start, edit
def start(feature=None):
    """Open the Thread panel (on a thread feature: Edit Parameters). Returns the panel, or None."""
    doc = feature.Document if feature is not None else App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    _ensure_partdesign()
    panel = ThreadPanel(feature)
    Gui.Control.showDialog(panel)
    try:
        panel.begin()
    except Exception as e:
        import traceback
        App.Console.PrintError(f"NXStyle: Thread could not start: {e}\n{traceback.format_exc()}")
        panel.error = f"Thread could not start: {type(e).__name__}: {e}"
        panel._end("failed", panel.error, abort=True)
        Gui.Control.closeDialog()
        return None
    return panel


def editable(obj):
    """The thread feature Edit Parameters reopens in the Thread dialog for obj (the helix, the symbolic thread,
    or the Detailed thread's profile sketch), else None."""
    if obj is None:
        return None
    if tf.is_thread(obj) and body_of(obj) is not None:
        return obj
    if obj.TypeId == "Sketcher::SketchObject":
        users = [o for o in obj.InList if tf.is_thread(o)]
        return users[0] if len(users) == 1 else None
    return None


# ------------------------------------------------------------------ the command
class ThreadCommand:
    def GetResources(self):
        nx = config.get().get("labels") != "freecad"
        return {"MenuText": NAME if nx else core.FREECAD_NAME, "ToolTip": TIP,
                "Pixmap": config.resource("icons", "thread.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        start()


COMMANDS = {"NXStyle_Thread": ThreadCommand()}

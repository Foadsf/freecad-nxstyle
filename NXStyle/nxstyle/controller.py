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

The geometry is made by a backend adapter. Extrude is the first: FreeCAD's PartDesign Pad and Pocket, whose
own parameter panel stays the place where limits are typed. The controller adds the NX command box above
it with the section, the body and the Boolean (New Body, Unite, Subtract; Intersect shown and refused).
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import command_core as core
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


# --------------------------------------------------------------------------
# Extrude adapter: PartDesign Pad (New Body, Unite) and Pocket (Subtract)
# --------------------------------------------------------------------------
class ExtrudeAdapter:
    name = "Extrude"
    TYPES = ("PartDesign::Pad", "PartDesign::Pocket")
    CARRY = ("Type", "Length", "Length2", "Midplane")       # kept when the Boolean changes the backend
    LENGTH_FIELDS = ("length", "offset")                    # backend fields whose typed text is read back

    def accepts(self, obj):
        return obj is not None and obj.TypeId in self.TYPES and body_of(obj) is not None

    @staticmethod
    def preselected_section():
        from .commands import _selected_sketch
        return _selected_sketch()

    def mode_of(self, feature):
        return core.mode_of(feature.TypeId, getattr(feature, "BaseFeature", None) is not None)

    def carry(self, feature):
        out = {}
        for p in self.CARRY:
            if p in feature.PropertiesList:
                v = getattr(feature, p)
                out[p] = getattr(v, "Value", v)
        return out

    def build(self, s, plan):
        """Make the feature for plan inside the open transaction; returns it."""
        doc = s.doc
        if plan["body"] == "new":
            body = doc.addObject("PartDesign::Body", "Body")
            profile = body.newObject("PartDesign::SubShapeBinder", "Section")
            # the sketch through its own Body, as FreeCAD's binder command links it: placement stays global
            profile.Support = [(s.sketch_body, (s.sketch.Name + ".",))] if s.sketch_body is not None \
                else [(s.sketch, ("",))]
        else:
            body = s.sketch_body
            profile = s.sketch
        prev = solid_tip(body)
        feature = body.newObject(plan["feature"], "Pocket" if plan["feature"].endswith("Pocket") else "Pad")
        feature.Profile = (profile, [""])
        if profile is not s.sketch:
            # a binder's face may point either way (measured: opposite to the sketch normal on XZ); NX
            # extrudes along the section's normal, so say so as the Pad's custom direction
            normal = s.sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            feature.UseCustomVector = True
            feature.Direction = body.getGlobalPlacement().Rotation.inverted().multVec(normal)
        for k, v in s.carried.items():
            if k not in feature.PropertiesList:
                continue
            if k == "Type" and v not in feature.getEnumerationsOfProperty("Type"):
                continue
            try:
                setattr(feature, k, v)
            except Exception:
                pass
        for o in (profile, s.sketch) if profile is not s.sketch else (profile,):
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


ADAPTERS = {"Extrude": ExtrudeAdapter()}


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
        self.stage = "select"            # select -> parameterize -> committed | cancelled | failed
        self.doc = feature.Document if feature is not None else App.ActiveDocument
        self.sketch = self.sketch_body = self.body = None
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


STYLE = {"error": "color: #B00020;", "warning": "color: #8A5A00;", "ok": "color: #0B6E79;"}


class CommandBox(QtWidgets.QGroupBox):
    """NX's command dialog header: section, body, Boolean, what is not supported, and the error state."""

    def __init__(self, ctl, s):
        super().__init__(s.adapter.name)
        self.ctl = ctl
        self.setObjectName("NXCommandBox")
        form = QtWidgets.QFormLayout(self)
        self.section = QtWidgets.QLabel()
        self.section.setObjectName("nxSection")
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
            self.boolean.setToolTip(dict((n, why) for n, _, why in core.EXTRUDE_OPTIONS)[
                "Change the Boolean when editing"])
        self.boolean.activated.connect(self._activated)
        self.note = QtWidgets.QLabel(core.SHORT_NOTE)
        self.note.setToolTip(core.options_tooltip())
        self.note.setObjectName("nxUnsupported")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #5A5A5A;")
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("nxStatus")
        self.status.setWordWrap(True)
        form.addRow("Section", self.section)
        form.addRow("Body", self.body)
        form.addRow("Boolean", self.boolean)
        form.addRow(self.note)
        form.addRow(self.status)
        self.refresh(s)

    def _activated(self, index):
        self.ctl.change_boolean(self.boolean.itemData(index))

    def refresh(self, s):
        self.section.setText(s.sketch.Label if s.sketch is not None else "-")
        f = s.feature()
        body = body_of(f) if f is not None else None
        new = " (new)" if s.mode == "new_body" and body is not None and body is not s.sketch_body else ""
        self.body.setText((body.Label if body is not None else "-") + new)
        i = self.boolean.findData(s.mode)
        if i >= 0 and self.boolean.currentIndex() != i:
            self.boolean.setCurrentIndex(i)
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
        """select: with a sketch selected go straight on; otherwise sketch first (NX: sketch in the command)."""
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
        sketch = adapter.preselected_section()
        self.log(f"begin {adapter.name} ({s.requested or 'inferred'}): {len(s.selection)} selected, "
                 f"section {sketch.Name if sketch is not None else None}")
        if sketch is not None:
            return self._parameterize(sketch)
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

    def _parameterize(self, sketch):
        s = self.session
        s.sketch, s.doc = sketch, sketch.Document
        s.sketch_body = body_of(sketch)
        s.has_body = s.sketch_body is not None
        s.has_solid = solid_tip(s.sketch_body) is not None
        s.remember_visibility(sketch, solid_tip(s.sketch_body))
        s.mode = core.infer_boolean(s.requested, s.has_body, s.has_solid)
        label = s.sketch_body.Label if s.sketch_body is not None else "the Body"
        try:
            plan = core.plan_extrude(s.mode, s.has_body, s.has_solid, label)
        except core.CommandError as e:
            # the requested Boolean cannot be built (Subtract with nothing to cut): start with what NX would
            # infer, and say so in the panel
            s.notice = f"{e}; started as {core.LABELS[core.infer_boolean(None, s.has_body, s.has_solid)]}"
            s.mode = core.infer_boolean(None, s.has_body, s.has_solid)
            plan = core.plan_extrude(s.mode, s.has_body, s.has_solid, label)
        return self._build(plan)

    def _build(self, plan):
        s = self.session
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
        s.sketch = prof
        if prof is not None and prof.TypeId == "PartDesign::SubShapeBinder" and prof.Support:
            try:
                parent, subs = prof.Support[0]
                s.sketch = parent.getSubObject(subs[0], 1) if subs and subs[0] else parent
            except Exception:
                pass
        s.mode = adapter.mode_of(feature)
        base = getattr(feature, "BaseFeature", None)
        s.base_volume, s.base_solids = _volume(base), len(_solids(base))
        s.remember_visibility(feature, base, prof, s.sketch)
        self._suspend_gate()
        self._start_timer()
        App.setActiveTransaction("Edit " + adapter.name, True)
        s.stage = "parameterize"
        self._watch()
        Gui.getDocument(s.doc.Name).setEdit(feature, 0)
        QtCore.QTimer.singleShot(0, self._attach)
        return True

    # ---------------------------------------------------------- Boolean
    def change_boolean(self, mode):
        """New Body, Unite or Subtract chosen in the box: rebuild with the matching backend feature, in a new
        transaction (the first one is aborted, so nothing of it is left)."""
        s = self.session
        if s is None or s.stage != "parameterize" or s.swapping or mode == s.mode:
            return False
        if s.edit:
            s.error = "Changing the Boolean of an existing Extrude is not supported"
            self._show()
            return False
        label = s.sketch_body.Label if s.sketch_body is not None else "the Body"
        try:
            plan = core.plan_extrude(mode, s.has_body, s.has_solid, label)
        except core.CommandError as e:
            s.notice = f"{core.LABELS.get(mode, mode)} refused: {e}"
            s.key = None
            self.validate(force=True)
            return False
        f = s.feature()
        s.carried = s.adapter.carry(f) if f is not None else {}
        s.swapping = True
        self._remove_box()
        self._abort()                                    # nothing of the first backend is left
        self._close_panel()
        self._restore_visibility(s)
        self._rebuild(mode, plan, 0)
        return True

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
        s.box = CommandBox(self, s)
        lay.insertWidget(max(lay.indexOf(anchor), 0), s.box)
        s.anchor = anchor
        if self.cancel_filter is None:
            self.cancel_filter = _CancelFilter(self)
        try:
            Gui.Control.activeTaskDialog().setEscapeButtonEnabled(False)
        except Exception:
            pass
        dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
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
        s.key = None
        self.validate(force=True)

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
        dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")
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
        key = (tuple(str(getattr(f, p, "")) for p in ("Type", "Length", "Length2", "Midplane", "Reversed",
                                                       "UpToFace", "TaperAngle")), str(f.State))
        if key == s.key and not force:
            self._show()
            return
        s.key = key
        error, warnings = None, []
        if not f.isValid() or "Invalid" in f.State:
            error = f"FreeCAD cannot build it: {f.getStatusString() or 'invalid parameters'}"
        elif s.mode in ("unite", "subtract"):
            solids = _solids(f)
            if s.mode == "unite" and len(solids) > s.base_solids:
                error = "Unite would leave a separate solid: the extrusion does not touch the part (choose None for a new body)"
            else:
                w = core.result_warning(s.mode, s.base_volume, _volume(f))
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
        elif outcome in ("cancelled", "failed") and doc_open:
            self._restore_visibility(s)
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

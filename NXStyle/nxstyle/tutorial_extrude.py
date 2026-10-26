# SPDX-License-Identifier: LGPL-2.1-or-later
"""Acceptance case for the command controller (controller.py): one Extrude, every way it is used.

  AE  New -> Sketch -> Extrude (New Body) -> Extrude Unite -> Extrude Subtract (Boolean changed in the panel)
      -> Extrude into a separate New Body -> Edit Parameters from the MB3 menu, Cancel -> Edit Parameters from
      the ribbon, OK -> Undo, Redo -> save, reopen, edit and Esc

Our design, not a book exercise: a 40 x 30 block, a boss on top, a pocket in the top, a separate cylinder.
Every solid is compared with the same solid made with the Part API (nxstyle/geomcheck.py), and every command
must leave exactly one undo step, or none when cancelled.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtGui, QtWidgets, Qt

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


class ExtrudeTutorials:
    """Mixin for tutorial.Replay."""

    AE_W, AE_D, AE_H, AE_H2 = 40.0, 30.0, 20.0, 25.0      # block, its height before and after the edit
    AE_BOSS = (20.0, 15.0, 8.0, 10.0)                     # boss centre x, y, radius, height
    AE_POCKET = (2.0, 2.0, 10.0, 8.0, 5.0)                # pocket x0, y0, x1, y1, depth
    AE_CYL = (100.0, 10.0, 6.0, 15.0)                     # separate cylinder: sketch x, y on XZ, radius, length

    def AE_STEPS(self):
        return [self.p_modeling, self.ae_new, self.ae_extrude, self.ae_plane, self.ae_sketch, self.ae_finish,
                self.ae_first_dialog, self.ae_boss, self.ae_boss_sketch, self.ae_boss_finish, self.ae_boss_dialog,
                self.ae_pocket, self.ae_pocket_sketch, self.ae_pocket_finish, self.ae_pocket_dialog,
                self.ae_cyl, self.ae_cyl_plane, self.ae_cyl_sketch, self.ae_cyl_finish, self.ae_cyl_dialog,
                self.ae_edit_menu, self.ae_edit_cancel, self.ae_edit_ribbon, self.ae_edit_ok, self.ae_undo,
                self.ae_finder, self.ae_finder_cancel, self.ae_save, self.ae_reopen_edit, self.ae_fit, self.ae_show]

    # ------------------------------------------------------------- helpers
    def ae_ctl(self):
        from . import controller
        return controller.CONTROLLER

    def ae_box(self):
        dock = self.tasks_dock()
        return dock.findChild(QtWidgets.QGroupBox, "NXCommandBox") if dock is not None else None

    def ae_panel(self):
        """(Boolean shown, Boolean enabled, status text, OK enabled) of the open command panel."""
        box = self.ae_box()
        if box is None:
            return None, None, "no NX command box", None
        combo = box.findChild(QtWidgets.QComboBox, "nxBoolean")
        status = box.findChild(QtWidgets.QLabel, "nxStatus")
        ok = None
        for bb in self.tasks_dock().findChildren(QtWidgets.QDialogButtonBox):
            b = bb.button(QtWidgets.QDialogButtonBox.Ok)
            if b is not None and b.isVisible():
                ok = b.isEnabled()
        return combo.currentText(), combo.isEnabled(), status.text(), ok

    def ae_ref(self, h, boss=True, pocket=True):
        import Part
        ref = Part.makeBox(self.AE_W, self.AE_D, h)
        if boss:
            x, y, r, bh = self.AE_BOSS
            ref = ref.fuse(Part.makeCylinder(r, bh, App.Vector(x, y, h))).removeSplitter()
        if pocket:
            x0, y0, x1, y1, d = self.AE_POCKET
            ref = ref.cut(Part.makeBox(x1 - x0, y1 - y0, d, App.Vector(x0, y0, h - d))).removeSplitter()
        return ref

    def ae_cyl_ref(self):
        import Part
        x, y, r, length = self.AE_CYL
        pl = self._ae_cyl_place
        return Part.makeCylinder(r, length, pl.multVec(App.Vector(x, y, 0)), pl.Rotation.multVec(App.Vector(0, 0, 1)))

    def ae_bodies(self):
        return [o for o in App.ActiveDocument.Objects if o.isDerivedFrom("PartDesign::Body")]

    def ae_compare(self, body, ref):
        from . import geomcheck
        return geomcheck.compare(body.Shape if body is not None else None, ref)

    def ae_last(self):
        h = self.ae_ctl().history
        return h[-1] if h else {}

    def ae_one_step(self, mode, undo_name):
        r = self.ae_last()
        ok = r.get("outcome") == "committed" and r.get("mode") == mode and r.get("undo") == undo_name \
            and r.get("undo_steps") == 1
        return ok, (f"controller: {r.get('outcome')} {r.get('mode')}, undo step '{r.get('undo')}', "
                    f"{r.get('undo_steps')} step(s) added")

    def ae_top_face(self, z):
        tip = self.body().Tip
        return tip, self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - z) < 1e-6
                                 and f.Area > 300)

    def ae_type(self, value):
        """Type the distance into the shown Length field. After a Boolean change the previous panel's field can
        still exist, hidden, until Qt deletes it: a user can only type into the one on screen."""
        fields = [w for w in self.tasks_dock().findChildren(QtWidgets.QAbstractSpinBox)
                  if w.objectName().lower() == "lengthedit" and w.isVisible()]
        if not fields:
            return None
        self.type_into(fields[0], value)
        QtWidgets.QApplication.processEvents()
        return fields[0].objectName()

    def ae_ok_shown(self):
        return any(bb.button(QtWidgets.QDialogButtonBox.Ok) is not None and bb.button(QtWidgets.QDialogButtonBox.Ok).isVisible()
                   for bb in self.tasks_dock().findChildren(QtWidgets.QDialogButtonBox))

    def ae_wait_box(self, what, test=lambda: True):
        """Wait as a user waits for the dialog: the command box and the panel's OK on screen."""
        return self.wait_for(what, lambda: self.ae_box() is not None and self.ae_box().isVisible()
                             and bool(Gui.Control.activeDialog()) and self.ae_ok_shown() and test(), timeout_ms=5000)

    def ae_touched(self):
        return [o.Name for o in App.ActiveDocument.Objects if "Touched" in o.State]

    # ------------------------------------------------------------- New, sketch, first Extrude
    def ae_new(self):
        self.tutorial = "AE: One Extrude, every way (command controller acceptance)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ae_extrude(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N", SAME if new and self.body() else FAIL,
                  f"new document {sorted(new)}")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def ae_plane(self):
        busy = self.ae_ctl().busy()
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude (X) with nothing selected, pick the XC-YC plane", "X key, plane row + MB2",
                  SAME if picked and busy else FAIL, f"picked {picked}; command controller started: {busy}")
        self.wait = 1500

    def ae_sketch(self):
        import Part
        sk = self.ae_sketch_in_edit("block")
        _, tool, n, ended = self.draw_clicks("R", [(0, 0), (self.AE_W, self.AE_D)])
        P = [App.Vector(x, y, 0) for (x, y) in ((0, 0), (self.AE_W, 0), (self.AE_W, self.AE_D), (0, self.AE_D))]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.step("Rectangle (R) 40 x 30 from the origin, MB2", "R key + 2 MB1 clicks + MB2; sizes applied",
                  SAME if tool and n >= 4 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self.wait = 300

    def ae_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def ae_first_dialog(self):
        self.ae_wait_box("ae_first_dialog")
        shown, enabled, status, ok = self.ae_panel()
        combo = self.ae_box().findChild(QtWidgets.QComboBox, "nxBoolean") if self.ae_box() else None
        inter = combo.findText("Intersect") if combo is not None else -1
        item = combo.model().item(inter) if combo is not None and inter >= 0 and hasattr(combo.model(), "item") else None
        inter_off = item is not None and not item.isEnabled()
        note = self.ae_box().findChild(QtWidgets.QLabel, "nxUnsupported").text() if self.ae_box() else ""
        self.step("Finish Sketch: the Extrude dialog, Boolean inferred None (New Body)",
                  "Ctrl+Q; the NX command box above FreeCAD's Pad panel",
                  SAME if shown == "None" and ok and inter_off and "Intersect" in note else FAIL,
                  f"Boolean '{shown}' (list enabled {enabled}); Intersect offered but disabled {inter_off}; status "
                  f"'{status}'; OK enabled {ok}; not supported shown: {'Intersect' in note and 'Offset' in note}")
        self.shot("AE1_new_body_panel.png")
        field = self.ae_type(self.AE_H)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("ae_first_dialog closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H, boss=False, pocket=False))
        one, steps = self.ae_one_step("new_body", "Extrude")
        self.step("End = Value 20, OK", f"'{field}' = 20 mm, MB2 = OK", SAME if same and one else FAIL,
                  f"{how}; {steps}")
        self.wait = 600

    # ------------------------------------------------------------- Unite: a boss on the top face
    def ae_face_extrude(self, z, what):
        """Select the top face at height z, press X: the sketch opens on the face."""
        tip, face = self.ae_top_face(z)
        self.select_sub(tip, face)
        sel = [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)]
        self.key("X")
        QtWidgets.QApplication.processEvents()
        self.info[f"AE {what}: X on a face"] = {"face": f"{tip.Name}.{face}", "selection": sel,
                                                "controller busy": self.ae_ctl().busy(),
                                                "dialog": bool(Gui.Control.activeDialog()),
                                                "history": self.ae_ctl().history[-1:]}
        self.wait = 1500

    def ae_sketch_in_edit(self, what):
        self.wait_for(f"{what}: sketch in edit", lambda: self.edited_sketch() is not None)
        sk = self.edited_sketch()
        if sk is None:
            self.info[f"AE {what}: no sketch"] = {"controller busy": self.ae_ctl().busy(),
                                                  "dialog": bool(Gui.Control.activeDialog()),
                                                  "history": self.ae_ctl().history[-2:],
                                                  "dialog widgets": self.task_widgets()[:40]}
            raise RuntimeError(f"no sketch for the {what}")
        return sk

    def ae_boss(self):
        self.ae_face_extrude(self.AE_H, "boss")

    def ae_boss_sketch(self):
        import Part
        sk = self.ae_sketch_in_edit("boss")
        x, y, r, _ = self.AE_BOSS
        c = self.g2s_mm(sk, x, y, self.AE_H)
        e = self.g2s_mm(sk, x + r, y, self.AE_H)
        _, tool, n, ended = self.draw_clicks("O", [c, e])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), r)])
        self.step("Top face selected, Extrude (X): circle 8 mm radius", "select face + X; O key + 2 MB1 clicks "
                  "+ MB2; size applied", SAME if tool and n >= 1 and ended else FAIL,
                  f"sketch on {sk.AttachmentSupport if hasattr(sk, 'AttachmentSupport') else sk.Support}")
        self.wait = 300

    def ae_boss_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def ae_boss_dialog(self):
        self.ae_wait_box("ae_boss_dialog")
        shown, _, status, ok = self.ae_panel()
        pads = [o.Name for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad"]
        self.step("Boolean inferred Unite (the part has a solid)", "the NX command box",
                  SAME if shown == "Unite" and ok else FAIL, f"Boolean '{shown}'; status '{status}'; OK {ok}")
        # Intersect is listed but refused: the panel says why and nothing changes
        picked = self.set_combo("nxBoolean", "Intersect")
        QtWidgets.QApplication.processEvents()
        shown2, _, status2, ok2 = self.ae_panel()
        pads2 = [o.Name for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad"]
        refused = shown2 == "Unite" and "Intersect is not offered" in status2 and pads2 == pads
        self.step("Boolean Intersect", f"chose '{picked}' in the Boolean list", DIFFERS if refused else FAIL,
                  f"refused in the panel, not approximated: '{status2}'; Boolean back to '{shown2}', the Pad "
                  f"unchanged {pads2 == pads}" if refused else f"Boolean '{shown2}', status '{status2}', pads {pads2}")
        self.shot("AE2_unite_panel.png")
        field = self.ae_type(self.AE_BOSS[3])
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("ae_boss_dialog closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H, pocket=False))
        one, steps = self.ae_one_step("unite", "Extrude")
        self.step("End = Value 10, Boolean Unite, OK", f"'{field}' = 10 mm, MB2 = OK", SAME if same and one else FAIL,
                  f"{how}; {steps}")
        self.wait = 600

    # ------------------------------------------------------------- Subtract: chosen in the panel
    def ae_pocket(self):
        self.ae_face_extrude(self.AE_H, "pocket")

    def ae_pocket_sketch(self):
        import Part
        sk = self.ae_sketch_in_edit("pocket")
        x0, y0, x1, y1, _ = self.AE_POCKET
        corners = [self.g2s_mm(sk, x, y, self.AE_H) for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        _, tool, n, ended = self.draw_clicks("R", [corners[0], corners[2]])
        P = [App.Vector(u, v, 0) for (u, v) in corners]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.step("Top face, Extrude (X): rectangle 8 x 6 near the corner", "select face + X; R key + 2 MB1 clicks "
                  "+ MB2; sizes applied", SAME if tool and n >= 4 and ended else FAIL, f"tool {tool}; {n} curves")
        self.wait = 300

    def ae_pocket_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def ae_pocket_dialog(self):
        doc = App.ActiveDocument
        self.ae_wait_box("ae_pocket_dialog")
        undo = doc.UndoCount
        shown, _, _, _ = self.ae_panel()
        picked = self.set_combo("nxBoolean", "Subtract")
        ready = self.ae_wait_box("ae_pocket_dialog: Subtract", lambda: any(
            o.TypeId == "PartDesign::Pocket" for o in doc.Objects))
        shown2, _, status, ok = self.ae_panel()
        pads = [o.Name for o in doc.Objects if o.TypeId == "PartDesign::Pad"]
        swapped = ready and shown2 == "Subtract" and len(pads) == 2 and doc.UndoCount == undo
        self.step("Boolean Subtract (was inferred Unite)", f"'{picked}' in the Boolean list",
                  SAME if swapped and ok else FAIL,
                  f"Boolean '{shown}' -> '{shown2}'; the preview Pad replaced by a Pocket ({len(pads)} Pads left), "
                  f"no undo step added ({doc.UndoCount - undo}); status '{status}'")
        field = self.ae_type(self.AE_POCKET[4])
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("ae_pocket_dialog closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H))
        one, steps = self.ae_one_step("subtract", "Extrude")
        self.step("End = Value 5 into the part, OK", f"'{field}' = 5 mm, MB2 = OK", SAME if same and one else FAIL,
                  f"{how}; {steps}; Subtract cuts against the sketch normal unless Reversed (NX keeps the direction "
                  "and you reverse it)")
        self.wait = 600

    # ------------------------------------------------------------- New Body away from the part
    def ae_type_filter(self):
        """(filter shown, the kind in force, enabled) of the Type Filter on the Top Border Bar; the kind in
        force is the selection manager's global layer, which the gate applies."""
        from . import selection_filter
        tf = getattr(self.shell, "type_filter", None)
        if tf is None:
            return None, None, None
        return tf.currentText(), selection_filter.manager().global_kind, tf.isEnabled()

    def ae_cyl(self):
        Gui.Selection.clearSelection()
        tf = getattr(self.shell, "type_filter", None)
        if tf is not None:                       # a user's Type Filter: the command lifts it and puts it back
            tf.setCurrentIndex(tf.findText("Edge"))
        QtWidgets.QApplication.processEvents()
        b, _, _ = self.ribbon_button("Extrude")
        self.info["AE cylinder: before X"] = {"Extrude active": Gui.Command.get("NXStyle_Extrude").isActive(),
                                              "ribbon button enabled": b.isEnabled() if b is not None else None}
        self.key("X")
        self.wait = 1500

    def ae_cyl_plane(self):
        during = self.ae_type_filter()
        picked = self.pick_in_feature_list("XZ")
        self.mb2_click()
        self.step("Extrude (X), pick the XC-ZC plane (Type Filter set to Edge before)", "X key, plane row + MB2",
                  SAME if picked and during[1] is None and during[2] is False else FAIL,
                  f"picked {picked}; Type Filter during the command: '{during[0]}', gate {during[1]}, "
                  f"enabled {during[2]}")
        self.wait = 1500

    def ae_cyl_sketch(self):
        import Part
        sk = self.ae_sketch_in_edit("cylinder")
        x, y, r, _ = self.AE_CYL
        _, tool, n, ended = self.draw_clicks("O", [(x, y), (x + r, y)])
        self.add_geometry(sk, [Part.Circle(App.Vector(x, y, 0), App.Vector(0, 0, 1), r)])
        self._ae_cyl_place = sk.getGlobalPlacement()
        self.step("Circle 6 mm radius, 100 mm from the part", "O key + 2 MB1 clicks + MB2; size applied",
                  SAME if tool and n >= 1 and ended else FAIL, f"tool {tool}; {n} curves")
        self.wait = 300

    def ae_cyl_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def ae_cyl_dialog(self):
        doc = App.ActiveDocument
        self.ae_wait_box("ae_cyl_dialog")
        shown, _, status, ok = self.ae_panel()
        self.mb2_click()          # refused: OK is not available while the panel shows an error
        QtWidgets.QApplication.processEvents()
        still = bool(Gui.Control.activeDialog()) and self.ae_ctl().busy()
        self.step("Inferred Unite with a section that misses the part; MB2", "MB2 = OK",
                  SAME if shown == "Unite" and ok is False and still else FAIL,
                  f"error shown: '{status}'; OK enabled {ok}; dialog still open after MB2 {still} (NX: 'tool body "
                  "does not intersect the target')")
        picked = self.set_combo("nxBoolean", "None")
        ready = self.ae_wait_box("ae_cyl_dialog: New Body", lambda: len(self.ae_bodies()) == 2)
        shown2, _, status2, ok2 = self.ae_panel()
        self.step("Boolean None (a new body)", f"'{picked}' in the Boolean list", SAME if ready and shown2 == "None" and ok2
                  else FAIL, f"bodies {[b.Label for b in self.ae_bodies()]}; status '{status2}'; OK {ok2}")
        from .tutorial import qtest
        qtest().qWait(800)              # the rebuilt panel lays itself out after a Boolean change
        self.shot("AE3_new_body_panel.png")
        field = self.ae_type(self.AE_CYL[3])
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("ae_cyl_dialog closed", lambda: not self.ae_ctl().busy())
        bodies = self.ae_bodies()
        new = bodies[-1] if len(bodies) == 2 else None
        same, how = self.ae_compare(new, self.ae_cyl_ref())
        part, how_part = self.ae_compare(bodies[0], self.ae_ref(self.AE_H))
        one, steps = self.ae_one_step("new_body", "Extrude")
        binder = [o.TypeId for o in (new.Group if new is not None else [])]
        after = self.ae_type_filter()
        tf = getattr(self.shell, "type_filter", None)
        if tf is not None:
            tf.setCurrentIndex(0)
        active = self.view().getActiveObject("pdbody")
        work = active is not None and bodies and active.Name == bodies[0].Name
        self.step("End = Value 15, Boolean None (a new body), OK", f"'{field}' = 15 mm, MB2 = OK",
                  SAME if same and part and one and work and after[1:] == ("edge", True) else FAIL,
                  f"new body {new.Label if new else None}: {how}; the first body unchanged: {how_part}; {steps}; "
                  f"made of {[t.split('::')[-1] for t in binder if 'Origin' not in t]}; active Body still "
                  f"{active.Label if active is not None else None}; Type Filter afterwards '{after[0]}', gate "
                  f"{after[1]}, enabled {after[2]}")
        self._ae_doc = doc.Name
        self.wait = 600

    # ------------------------------------------------------------- edit, cancel, edit, OK
    def ae_open_context_menu(self, label, item_text):
        """MB3 on the Part Navigator row, then the menu entry, as a user clicks it. Returns (entries, chosen)."""
        tw = self.select_row(label)
        if tw is None:
            return [], None
        idx = tw.currentIndex()
        p = tw.visualRect(idx).center()
        seen = {"entries": [], "chosen": None}

        def pick(tries=0):
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                if tries < 20:
                    QtCore.QTimer.singleShot(100, lambda: pick(tries + 1))
                return
            acts = [a for a in menu.actions() if a.text()]
            seen["entries"] = [a.text().replace("&", "") for a in acts]
            act = next((a for a in acts if a.text().replace("&", "") == item_text), None)
            menu.close()
            if act is not None:
                seen["chosen"] = act.text().replace("&", "")
                act.trigger()

        QtCore.QTimer.singleShot(200, pick)
        ev = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, p, tw.viewport().mapToGlobal(p))
        QtWidgets.QApplication.sendEvent(tw.viewport(), ev)
        QtWidgets.QApplication.processEvents()
        return seen["entries"], seen["chosen"]

    def ae_pad(self):
        return next(o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad"
                    and o.getParentGeoFeatureGroup() is self.ae_bodies()[0] and o.BaseFeature is None)

    def ae_edit_menu(self):
        doc = App.ActiveDocument
        pad = self.ae_pad()
        self._ae_undo = doc.UndoCount
        Gui.Selection.clearSelection()
        entries, chosen = self.ae_open_context_menu(pad.Label, "Edit Parameters")
        opened = self.ae_wait_box("ae_edit_menu")
        shown, enabled, status, _ = self.ae_panel()
        self.step("MB3 on the first Extrude in the Part Navigator > Edit Parameters", "MB3 menu entry",
                  SAME if chosen and opened and enabled is False else FAIL,
                  f"menu entries {entries[:12]}; panel open {opened}; Boolean '{shown}' locked {enabled is False} "
                  "(changing it would replace the feature)")
        field = self.ae_type(35.0)
        self._ae_preview = (pad.Length.Value, pad.Shape.BoundBox.ZMax)     # the panel recomputes this feature
        self._ae_field = field
        self.wait = 300

    def ae_edit_cancel(self):
        doc = App.ActiveDocument
        pad = self.ae_pad()
        cancel = None
        for bb in self.tasks_dock().findChildren(QtWidgets.QDialogButtonBox):
            b = bb.button(QtWidgets.QDialogButtonBox.Cancel)
            if b is not None and b.isVisible():
                cancel = b
        if cancel is not None:
            from .tutorial import qtest
            qtest().mouseClick(cancel, Qt.LeftButton)
        self.wait_for("ae_edit_cancel", lambda: not self.ae_ctl().busy())
        length, zmax = self._ae_preview
        same, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H))
        r = self.ae_last()
        touched = self.ae_touched()
        ok = (cancel is not None and abs(length - 35) < 1e-6 and abs(zmax - 35) < 1e-6 and same
              and abs(pad.Length.Value - self.AE_H) < 1e-9 and doc.UndoCount == self._ae_undo
              and r.get("outcome") == "cancelled" and not touched and not Gui.Control.activeDialog())
        self.step("Preview 35 mm, then Cancel", f"'{self._ae_field}' = 35 mm, Cancel button",
                  SAME if ok else FAIL,
                  f"preview showed Length {length:g} mm (top at {zmax:g} mm); after Cancel Length "
                  f"{pad.Length.Value:g} mm, {how}; undo steps added {doc.UndoCount - self._ae_undo}; objects left "
                  f"to recompute {touched}")
        self.wait = 400

    def ae_edit_ribbon(self):
        pad = self.ae_pad()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.ae_bodies()[0].Name, f"{pad.Name}.")
        self._ae_undo = App.ActiveDocument.UndoCount
        b, where = self.click_ribbon("Edit Parameters")
        self._ae_where = where
        self.wait = 1500

    def ae_edit_ok(self):
        opened = self.ae_wait_box("ae_edit_ok")
        field = self.ae_type(self.AE_H2)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        self.wait_for("ae_edit_ok closed", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H2))
        cyl, _ = self.ae_compare(self.ae_bodies()[1], self.ae_cyl_ref())
        one, steps = self.ae_one_step("new_body", "Edit Extrude")
        self.step("Design change: Edit Parameters, End 20 -> 25, OK",
                  f"ribbon '{self._ae_where} > Edit Parameters' (panel {opened}), '{field}' = 25 mm, MB2 = OK",
                  SAME if same and cyl and one else FAIL,
                  f"{how}; the boss and the pocket follow the top face; the separate body unchanged {cyl}; {steps}")
        self.wait = 400

    def ae_undo(self):
        doc = App.ActiveDocument
        self.key("Ctrl+Z")
        QtWidgets.QApplication.processEvents()
        doc.recompute()
        back, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H))
        self.key("Ctrl+Z")
        QtWidgets.QApplication.processEvents()
        n_after = len(self.ae_bodies())
        left = [o.Name for o in doc.Objects if o.TypeId == "PartDesign::SubShapeBinder"]
        self.key("Ctrl+Y")
        self.key("Ctrl+Y")
        QtWidgets.QApplication.processEvents()
        doc.recompute()
        redo, how2 = self.ae_compare(self.body(), self.ae_ref(self.AE_H2))
        cyl, _ = self.ae_compare(self.ae_bodies()[1] if len(self.ae_bodies()) == 2 else None, self.ae_cyl_ref())
        self.step("Undo (Ctrl+Z) twice, Redo (Ctrl+Y) twice", "Ctrl+Z, Ctrl+Z, Ctrl+Y, Ctrl+Y",
                  SAME if back and n_after == 1 and not left and redo and cyl else FAIL,
                  f"first undo takes back the edit ({how}); the second the whole New Body extrude ({n_after} body "
                  f"left, binders left {left}); redo restores both ({how2}; cylinder {cyl})")
        self.wait = 400

    def ae_finder(self):
        from .tutorial import qtest
        from .smoke import decode
        doc = App.ActiveDocument
        self._ae_before = (len(doc.Objects), doc.UndoCount, len(self.ae_ctl().history))
        Gui.Selection.clearSelection()
        cf = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "NXCommandFinder")
        self._ae_finder = cf is not None
        if cf is not None:
            cf.setFocus()
            cf.clear()
            qtest().keyClicks(cf, "Extrude (Subtract)")
            qtest().keyClick(cf, *decode("Return"))
        self.wait = 1500

    def ae_finder_cancel(self):
        from .tutorial import qtest
        doc = App.ActiveDocument
        started = self.ae_ctl().busy() and bool(Gui.Control.activeDialog())
        cancel = None
        for bb in self.tasks_dock().findChildren(QtWidgets.QDialogButtonBox):
            b = bb.button(QtWidgets.QDialogButtonBox.Cancel)
            if b is not None and b.isVisible():
                cancel = b
        if cancel is not None:
            qtest().mouseClick(cancel, Qt.LeftButton)
        ended = self.wait_for("ae_finder_cancel", lambda: not self.ae_ctl().busy(), timeout_ms=8000)
        if not ended:
            gdoc = Gui.ActiveDocument
            self.info["AE finder: after Cancel"] = {
                "cancel button found": cancel is not None, "dialog": bool(Gui.Control.activeDialog()),
                "in edit": getattr(getattr(gdoc.getInEdit() if gdoc else None, "Object", None), "Name", None),
                "dialog widgets": self.task_widgets()[:30], "trace": self.ae_ctl().trace[-4:]}
        n, undo, hist = self._ae_before
        r = self.ae_ctl().history[-1] if len(self.ae_ctl().history) > hist else {}
        ok = self._ae_finder and started and ended and r.get("outcome") == "cancelled" \
            and len(doc.Objects) == n and doc.UndoCount == undo and not Gui.Control.activeDialog()
        self.step("Command Finder: 'Extrude (Subtract)', Enter; Cancel the plane pick",
                  "typed into the Command Finder + Enter; Cancel button", SAME if ok else FAIL,
                  f"command started {started} (Boolean asked: {self.ae_ctl().history[-1].get('mode') if r else '-'}); "
                  f"ended {r.get('outcome')}: {r.get('note') or ''}; objects {len(doc.Objects) - n:+d}, undo steps "
                  f"{doc.UndoCount - undo:+d}")
        self.wait = 400

    def ae_save(self):
        outcome, how, detail, path = self.save_ctrl_s("ExtrudeAE.FCStd")
        self.step("Save (Ctrl+S)", how, outcome, detail)
        doc = App.ActiveDocument
        App.closeDocument(doc.Name)
        App.openDocument(path)
        QtWidgets.QApplication.processEvents()
        doc = App.ActiveDocument
        doc.recompute()
        from . import controller
        a = controller.ADAPTERS["Extrude"]
        modes = [a.mode_of(o) for o in doc.Objects if a.accepts(o)]
        bodies = self.ae_bodies()
        part, how_part = self.ae_compare(bodies[0] if bodies else None, self.ae_ref(self.AE_H2))
        cyl, how_cyl = self.ae_compare(bodies[1] if len(bodies) == 2 else None, self.ae_cyl_ref())
        self.step("Reopen the part", "close, File > Open (by script)",
                  SAME if part and cyl and modes == ["new_body", "unite", "subtract", "new_body"] else FAIL,
                  f"part: {how_part}; cylinder: {how_cyl}; Extrudes read back as {modes}")
        self.wait = 600

    def ae_reopen_edit(self):
        from .tutorial import qtest
        from .smoke import decode
        doc = App.ActiveDocument
        pocket = next(o for o in doc.Objects if o.TypeId == "PartDesign::Pocket")
        undo = doc.UndoCount
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self.ae_bodies()[0].Name, f"{pocket.Name}.")
        b, where = self.click_ribbon("Edit Parameters")
        opened = self.ae_wait_box("ae_reopen_edit")
        shown, _, _, _ = self.ae_panel()
        w = None
        for sb in self.tasks_dock().findChildren(QtWidgets.QAbstractSpinBox):
            if "length" in sb.objectName().lower() and sb.isVisible():
                w = sb
                break
        popup = None
        if w is not None:
            self.type_into(w, 12.0)
            w.setFocus()
            p = QtWidgets.QApplication.activePopupWidget()
            popup = f"{type(p).__name__} {p.objectName()} visible {p.isVisible()}" if p is not None else None
            qtest().keyClick(w, *decode("Escape"))
        self.wait_for("ae_reopen_edit: Esc", lambda: not self.ae_ctl().busy())
        same, how = self.ae_compare(self.body(), self.ae_ref(self.AE_H2))
        r = self.ae_last()
        ok = opened and shown == "Subtract" and same and abs(pocket.Length.Value - self.AE_POCKET[4]) < 1e-9 \
            and doc.UndoCount == undo and r.get("outcome") == "cancelled" and not Gui.Control.activeDialog()
        self.step("Reopened part: Edit Parameters on the pocket, 12 mm, Esc", f"ribbon '{where}', typed 12, Esc",
                  SAME if ok else FAIL, f"Boolean read back '{shown}'; after Esc depth {pocket.Length.Value:g} mm, "
                  f"{how}; undo steps added {doc.UndoCount - undo}" + (f"; popup open at Esc: {popup}" if popup else ""))
        self.wait = 400

    def ae_fit(self):
        self.fit()

    def ae_show(self):
        self.show("AE_extrude")

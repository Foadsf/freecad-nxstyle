# SPDX-License-Identifier: LGPL-2.1-or-later
"""Replay NX textbook tutorials through the NX-style UI (``launch_nx.py --tutorial OUTDIR``).

Each step is done the way the book tells an NX user to do it: the same key,
the same ribbon button (found by its NX name), MB1 clicks in the graphics
window for sketch curves, MB2 to end a tool or accept a dialog. Where the
FreeCAD flow differs, the step says so. Typed dimension values are applied to
the sketch through FreeCAD's API (the equivalent of typing them into Rapid
Dimension), and every feature is checked by its volume.

Tutorial steps paraphrase four exercises found through the NX notebook:
  A  "The Adjuster"  - Shih, Parametric Modeling with Siemens NX, ch. 2
  B  "First part"    - hollow cylinder plus revolved cone (NX course exercise)
  C  "Rod-Guide"     - Shih ch. 9: datum planes and a hole on a datum
  D  "Pulley"        - Shih ch. 11: revolve, mirror, circular pattern, drawing

Each step start is appended to OUTDIR/progress.log with the process's
committed memory, so a run stopped by the launcher's memory ceiling still
shows where it was.
"""

import math
import os
import re
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtWidgets, Qt, mouse_event
from .ribbon import CommandButton, clean_text
from .tutorial_extrude import ExtrudeTutorials
from .tutorial_inspection import InspectionTutorials
from .tutorial_katydid import KatydidTutorials
from .tutorial_lasercut import LaserCutTutorials
from .tutorial_mst import (MstCasingTutorials, MstCircularBaseTutorials, MstHolderTutorials, MstImpellerTutorials,
                           MstTutorials)
from .tutorial_precision import PrecisionTutorials

OUT = os.environ.get("NXSTYLE_TUTORIAL_OUT", "")
ALL_TUTORIALS = "A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF,AG,AH,AJ,AK"
IN = 25.4
SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"
LIMIT = "limit"   # the NX way fails in FreeCAD itself (shown by the same call through the Part API); a workaround follows


def qtest():
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest
    return QtTest.QTest


def camera_state(view):
    cam = view.getCameraNode()
    h = cam.height.getValue() if hasattr(cam, "height") else cam.heightAngle.getValue()
    return tuple(round(v, 6) for v in (*cam.position.getValue(), *cam.orientation.getValue().getValue(), h))


def settle_view(view, timeout=4.0):
    """Wait for the camera to stop: FreeCAD turns the view to a sketch with an animation when the sketch
    opens. A point computed while the camera still moves is not where the click lands (seconds waited)."""
    t0 = time.monotonic()
    last, still = camera_state(view), 0
    while still < 3 and time.monotonic() - t0 < timeout:
        qtest().qWait(60)
        now = camera_state(view)
        still = still + 1 if now == last else 0
        last = now
    return round(time.monotonic() - t0, 2)


class ModalWatcher(QtCore.QObject):
    """Closes unexpected modal dialogs (and records them) so a replay never hangs."""

    def __init__(self):
        super().__init__()
        self.seen = []
        self.accept = False      # True: answer Yes/OK (e.g. a delete confirmation the step expects)
        self.handler = None      # callable(widget) -> True when it handled a dialog the step expects
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)

    def poll(self):
        w = QtWidgets.QApplication.activeModalWidget()
        if w is None:
            return
        if self.handler is not None:
            try:
                if self.handler(w):
                    return
            except Exception as e:
                self.seen.append(f"{w.windowTitle()}: handler error {e}")
        text = w.windowTitle()
        if isinstance(w, QtWidgets.QMessageBox):
            text += ": " + w.text()
            if self.accept:
                for role in (QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Ok):
                    b = w.button(role)
                    if b is not None:
                        self.seen.append(text + " -> accepted")
                        b.click()
                        return
        self.seen.append(text)
        try:
            w.reject()
        except Exception:
            w.close()


class SaveWatch:
    """Document observer: which documents FreeCAD saved, to which file, and whether it was the one watched."""

    def __init__(self, path):
        self.path = os.path.normcase(os.path.abspath(path))
        self.seen = []

    def slotFinishSaveDocument(self, doc, filename):
        mine = os.path.normcase(os.path.abspath(filename)) == self.path
        self.seen.append(f"{doc.Name} -> {'this file' if mine else filename}")


class Replay(KatydidTutorials, PrecisionTutorials, InspectionTutorials, LaserCutTutorials, ExtrudeTutorials,
             MstTutorials, MstCasingTutorials, MstImpellerTutorials, MstCircularBaseTutorials, MstHolderTutorials):
    def __init__(self, shell):
        self.shell = shell
        self.rows = []
        self.info = {}
        self.tutorial = ""
        self.retries = []          # actions a user would have had to repeat (reported, never hidden)
        self.misread = []          # typed numbers a field read back as another value (fail the next step)
        self.modals = ModalWatcher()
        self.steps = list(self.plan())
        self.planned = [fn.__name__ for fn in self.steps]
        self.ran, self.dropped = [], []      # run, and skipped after a failure in their tutorial

    # ------------------------------------------------------------- report
    def step(self, nx, how, outcome, detail=""):
        if self.misread:
            outcome, detail = FAIL, "; ".join(self.misread) + f" | {detail}"
            self.misread = []
        self.rows.append({"tutorial": self.tutorial, "n": sum(1 for r in self.rows if r["tutorial"] == self.tutorial) + 1,
                          "nx": nx, "replay": how, "outcome": outcome, "detail": str(detail)})

    def shot(self, name):
        try:
            Gui.getMainWindow().grab().save(os.path.join(OUT, name))
        except Exception as e:
            self.info[name] = str(e)

    # ------------------------------------------------------------- UI helpers
    def nav(self):
        return self.shell.navigation.filter_for_active_view()

    def view(self):
        return Gui.ActiveDocument.ActiveView

    def key(self, seq):
        from .smoke import decode
        f = self.nav()
        app = QtWidgets.QApplication.instance()
        mw = Gui.getMainWindow()
        if app.activeWindow() is None and hasattr(app, "setActiveWindow"):
            app.setActiveWindow(mw)   # hidden desktop: no foreground window
        target = f.widget if f is not None else mw
        target.setFocus()
        k, m = decode(seq)
        qtest().keyClick(target, k, m)

    def ribbon_button(self, label, tab=None):
        """The button with this NX label; with tab given, that tab is searched first
        (the Sketch tab's Perpendicular, not the Assemblies tab's)."""
        r = self.shell.ribbon
        order = list(range(r.stack.count()))
        if tab:
            order.sort(key=lambda i: r.tabs.tabText(i) != tab)
        for i in order:
            page = r.stack.widget(i)
            for b in page.findChildren(CommandButton):
                if b.nx_label == label:
                    return b, r.tabs.tabText(i), r.locations.get(b.command, "")
        return None, "", ""

    def click_ribbon(self, label, tab=None):
        b, tab, where = self.ribbon_button(label, tab)
        if b is None:
            return None, ""
        self.shell.ribbon.select(tab)
        QtWidgets.QApplication.processEvents()
        # FreeCAD refreshes command states on a timer after the selection changes;
        # a user's click comes later than a script's, so wait for the button like a user would
        for _ in range(20):
            if b.isEnabled():
                break
            qtest().qWait(100)
        self.info.setdefault("ribbon clicks while disabled", []).extend([] if b.isEnabled() else [label])
        how, _via = self.shell.ribbon.reach(b)
        if how in ("group", "overflow"):
            # the window is too narrow for the group: a user opens the collapsed group's (or More) menu
            self.info.setdefault("ribbon clicks through a menu", []).append(label)
            act = self.shell.ribbon.menu_action(b)
            if act is not None:
                act.trigger()
                return b, where
        qtest().mouseClick(b, Qt.LeftButton)
        return b, where

    def send(self, kind, p, button, buttons):
        f = self.nav()
        QtWidgets.QApplication.sendEvent(f.widget, mouse_event(kind, p, button, buttons, Qt.NoModifier))

    def mb2_click(self, p=None):
        f = self.nav()
        p = p or QtCore.QPoint(f.widget.width() - 40, f.widget.height() - 40)
        self.send(QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)
        self.send(QtCore.QEvent.MouseButtonRelease, p, Qt.MiddleButton, Qt.NoButton)

    def mb1_click(self, p):
        self.send(QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        self.send(QtCore.QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton)
        self.send(QtCore.QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()

    def sketch_tool_running(self, p):
        """Is a sketcher tool still running? A running tool puts its cursor back when the pointer moves."""
        self.send(QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        return self.nav().sketch_tool_active()

    def screen_point(self, sketch, x, y):
        """Sketch-plane coordinates -> widget pixel position."""
        g = sketch.getGlobalPlacement().multVec(App.Vector(x, y, 0))
        sx, sy = self.view().getPointOnViewport(g)
        w = self.nav().widget
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        return QtCore.QPoint(int(round(sx / dpr)), int(round(w.height() - sy / dpr)))

    def camera_state(self):
        return camera_state(self.view())

    def frame_sketch(self, sketch, cx, cy, height):
        """Zoom the sketch view so the points to click are on screen (once the view has stopped turning)."""
        from pivy import coin
        self.info.setdefault("sketch view settled after s", []).append(settle_view(self.view()))
        cam = self.view().getCameraNode()
        g = sketch.getGlobalPlacement().multVec(App.Vector(cx, cy, 0))
        d = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        fd = cam.focalDistance.getValue()
        cam.position.setValue(coin.SbVec3f(g.x, g.y, g.z) - d * fd)
        if hasattr(cam, "height"):
            cam.height.setValue(height)

    def tasks_dock(self):
        return Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Tasks")

    def pick_in_feature_list(self, text):
        """FreeCAD's 'select a plane' task: choose the list row, as a click in the list would."""
        dock = self.tasks_dock()
        for lst in dock.findChildren(QtWidgets.QListWidget):
            for i in range(lst.count()):
                if text.lower() in lst.item(i).text().lower().replace("-", "_"):
                    lst.setCurrentRow(i)
                    lst.item(i).setSelected(True)
                    return lst.item(i).text()
        return None

    def _field(self, cls, name_part):
        """Task-panel widget whose objectName equals name_part, else contains it."""
        widgets = [w for w in self.tasks_dock().findChildren(cls) if w.objectName()]
        exact = [w for w in widgets if w.objectName().lower() == name_part.lower()]
        return (exact or [w for w in widgets if name_part.lower() in w.objectName().lower()] or [None])[0]

    def set_quantity(self, name_part, value):
        """Type a value into a task-panel quantity field (e.g. Length) the way a user does.

        The number is typed in the field's own unit (mm, °), and read back after the field loses
        focus, so 3.175 must stay 3.175. Setting the field's rawValue from Python instead rounds it
        to the Decimals preference (3.17), which once made a 0.125 in shell fail. The features'
        volume checks are what confirm the value FreeCAD used."""
        w = self._field(QtWidgets.QAbstractSpinBox, name_part)
        if w is None:
            return None
        self.type_into(w, value)
        return w.objectName()

    @staticmethod
    def typed_number(w, value):
        """value as a user types it into w: with the decimal separator of the field's locale.

        Qt's QDoubleSpinBox and FreeCAD's QuantitySpinBox both read numbers in the locale
        (LC_NUMERIC on Linux): under nl_NL '.' is the group separator, so '0.05' is 5 and
        '3.175' is 3175, while a Dutch user types '0,05'."""
        return f"{float(value):.6g}".replace(".", w.locale().decimalPoint())

    def check_typed(self, w, value, text):
        """Read the field back: a typed number it took as another value fails the step."""
        got = w.value() if isinstance(w, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)) else w.property("rawValue")
        if not isinstance(got, (int, float)):
            return
        # a QDoubleSpinBox holds its value rounded to its decimals; FreeCAD's QuantitySpinBox must hold what was
        # typed (it rounded to the Decimals preference on focus-out until nxstyle/precise_input.py)
        tol = 1e-9 * max(1.0, abs(float(value)))
        if isinstance(w, QtWidgets.QDoubleSpinBox):
            tol += 0.5 * 10 ** -w.decimals()
        if abs(got - float(value)) > tol:
            self.misread.append(f"typed '{text}' into {w.objectName() or type(w).__name__}, the field read {got:g} "
                                f"(locale {w.locale().name()}, decimal '{w.locale().decimalPoint()}')")

    def type_into(self, w, value):
        """Replace a quantity field's text with value, typed in the field's unit, then Tab out.

        Some FreeCAD dialogs only take the text when the field finishes editing, as a
        user's Tab or click elsewhere does."""
        from .smoke import decode
        w.setFocus()
        ed = w.lineEdit()
        ed.selectAll()
        text = self.typed_number(w, value)
        qtest().keyClicks(ed, text)
        qtest().keyClick(ed, *decode("Tab"))
        QtWidgets.QApplication.processEvents()
        self.check_typed(w, value, text)

    @staticmethod
    def _matches(part, text):
        """'x axis' matches 'Base X-axis' (1.1) as well as 'Base X axis'."""
        def norm(s):
            return s.lower().replace("-", " ")
        return norm(part) in norm(text)

    def set_combo(self, name_part, option_part):
        """Choose a list entry the way a user does: FreeCAD 1.1 dialogs react to 'activated'."""
        c = self._field(QtWidgets.QComboBox, name_part)
        if c is None:
            return None
        for i in range(c.count()):
            if self._matches(option_part, c.itemText(i)):
                c.setCurrentIndex(i)
                try:
                    c.activated.emit(i)
                except Exception:
                    try:
                        c.activated[int].emit(i)
                    except Exception:
                        pass
                QtWidgets.QApplication.processEvents()
                return c.itemText(i)
        return None

    def body(self):
        return next((o for o in App.ActiveDocument.Objects if o.isDerivedFrom("PartDesign::Body")), None)

    def solid_volume(self):
        b = self.body()
        try:
            return b.Shape.Volume if b is not None and not b.Shape.isNull() else 0.0
        except Exception:
            return 0.0

    def edited_sketch(self):
        return self.shell._edited_sketch()

    @staticmethod
    def rebuild(sketch, lines=(), circles=(), constraints=()):
        """Exact geometry with the dimensions the book types (Rapid Dimension values)."""
        import Part
        import Sketcher
        sketch.deleteAllGeometry()
        for (a, b) in lines:
            sketch.addGeometry(Part.LineSegment(App.Vector(*a, 0), App.Vector(*b, 0)), False)
        for (c, r) in circles:
            sketch.addGeometry(Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), r), False)
        n = len(lines)
        for i in range(n):   # close the profile
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))
        for c in constraints:
            sketch.addConstraint(Sketcher.Constraint(*c))
        App.ActiveDocument.recompute()

    # ------------------------------------------------------------- plan
    def plan(self):
        A = [self.a_new, self.a_extrude, self.a_plane, self.a_profile_clicks, self.a_mb2_end,
             self.a_dimensions, self.a_finish, self.a_extrude_dialog, self.a_face_pick, self.a_rectangle,
             self.a_finish_cut, self.a_cut_dialog, self.a_fit, self.a_show, self.a_save]
        B = [self.b_new, self.b_extrude, self.b_plane, self.b_circles, self.b_finish, self.b_extrude_dialog,
             self.b_revolve, self.b_plane_yz, self.b_lines, self.b_finish_revolve, self.b_revolve_dialog,
             self.b_fit, self.b_show, self.b_inspect, self.b_snap]
        C = [self.c_new, self.c_extrude, self.c_plane, self.c_sketch, self.c_finish, self.c_extrude_dialog,
             self.c_datum_angle, self.c_datum_angle_ok, self.c_upper_feature, self.c_datum_offset,
             self.c_datum_offset_ok, self.c_hole, self.c_hole_sketch, self.c_finish_hole, self.c_hole_dialog,
             self.c_fit, self.c_show]
        D = [self.d_new, self.d_revolve, self.d_plane, self.d_profile, self.d_finish, self.d_revolve_dialog,
             self.d_mirror, self.d_mirror_dialog, self.d_leader, self.d_leader_sketch, self.d_finish_leader,
             self.d_leader_dialog, self.d_pattern, self.d_pattern_dialog, self.d_fit, self.d_show,
             self.d_drafting, self.d_sheet, self.d_base_view, self.d_base_view_check, self.d_extra_view,
             self.d_delete_view, self.d_section, self.d_section_dialog, self.d_section_check,
             self.d_section_edges, self.d_back]
        E = [self.e_new, self.e_csys, self.e_csys_ok, self.e_extrude, self.e_plane, self.e_profile, self.e_finish,
             self.e_extrude_dialog, self.e_end, self.e_end_sketch, self.e_end_finish, self.e_end_dialog,
             self.e_rename, self.e_width, self.e_width_dialog, self.e_hole, self.e_hole_sketch, self.e_hole_finish,
             self.e_hole_dialog, self.e_cut, self.e_cut_sketch, self.e_cut_finish, self.e_cut_dialog,
             self.e_rollback, self.e_rollback_dialog, self.e_fillet, self.e_fillet_finish, self.e_material,
             self.e_material_check, self.e_measure, self.e_fit, self.e_show]
        F = [self.f_new, self.f_revolve, self.f_plane, self.f_profile, self.f_finish, self.f_revolve_dialog,
             self.f_handle, self.f_handle_plane, self.f_handle_sketch, self.f_handle_finish, self.f_handle_dialog,
             self.f_nozzle, self.f_nozzle_plane, self.f_nozzle_sketch, self.f_nozzle_leave, self.f_nozzle_extrude,
             self.f_nozzle_dialog, self.f_blend, self.f_blend_dialog, self.f_shell, self.f_shell_dialog,
             self.f_vent, self.f_vent_sketch, self.f_vent_finish, self.f_vent_dialog, self.f_pattern,
             self.f_pattern_dialog, self.f_swept, self.f_fit, self.f_show]
        G = [self.g_new, self.g_app, self.g_new_file, self.g_template, self.g_plate, self.g_bearing,
             self.g_bearing_face, self.g_bearing_axis, self.g_bearing_axis2, self.g_collar, self.g_collar_axis,
             self.g_collar_parallel, self.g_screw1, self.g_screw2, self.g_explode, self.g_edit, self.g_bom,
             self.g_show, self.g_save,
             self.g_back]
        H = [self.h_new, self.h_part, self.h_drafting, self.h_sheet, self.h_view, self.h_view_check, self.h_side,
             self.h_side_check, self.h_centres, self.h_basic, self.h_hole_note, self.h_datums, self.h_frames,
             self.h_show, self.h_back]
        J = [self.j_new, self.j_extrude, self.j_plane, self.j_profile, self.j_perpendicular, self.j_dimensions,
             self.j_fix, self.j_undo_fix, self.j_location, self.j_relax, self.j_height, self.j_circle, self.j_figure,
             self.j_finish, self.j_extrude_dialog, self.j_relations, self.j_resize1, self.j_resize2, self.j_show]
        K = [self.k_new, self.k_sheet, self.k_names, self.k_bar, self.k_plane, self.k_profile, self.k_finish,
             self.k_pad, self.k_hole, self.k_hole_sketch, self.k_hole_finish, self.k_hole_dialog, self.k_pattern,
             self.k_pattern_dialog, self.k_config_b, self.k_show, self.k_save]
        I = [self.i_new, self.i_extrude, self.i_plane, self.i_outline, self.i_extend, self.i_trim, self.i_align, self.i_fillets,  # noqa: E741
             self.i_finish, self.i_extrude_dialog, self.i_cut, self.i_offset, self.i_offset_check, self.i_cut_finish,
             self.i_cut_dialog, self.i_height, self.i_show, self.i_save]
        L = [self.l_new, self.l_app, self.l_extrude, self.l_plane, self.l_rect, self.l_finish, self.l_extrude_dialog,
             self.l_boss, self.l_boss_sketch, self.l_boss_finish, self.l_boss_dialog, self.l_bore, self.l_bore_sketch,
             self.l_bore_finish, self.l_bore_dialog, self.l_hole, self.l_hole_sketch, self.l_hole_finish,
             self.l_hole_dialog, self.l_slot, self.l_slot_sketch, self.l_slot_finish, self.l_slot_dialog,
             self.l_slot_fix, self.l_slot_fix_dialog, self.l_show, self.l_save]
        M = [self.m_new, self.m_extrude, self.m_plane, self.m_profile, self.m_finish, self.m_extrude_dialog,
             self.m_body, self.m_body_plane, self.m_body_sketch, self.m_body_finish, self.m_body_dialog,
             self.m_rect, self.m_rect_sketch, self.m_rect_finish, self.m_rect_dialog, self.m_drill,
             self.m_drill_sketch, self.m_drill_finish, self.m_drill_dialog, self.m_rename, self.m_dependencies,
             self.m_suppress_rect, self.m_suppress_drill, self.m_unsuppress_drill, self.m_delete_drill, self.m_born,
             self.m_born_sketch, self.m_born_finish, self.m_born_dialog, self.m_born_check, self.m_circ,
             self.m_circ_sketch, self.m_circ_finish, self.m_circ_dialog, self.m_show, self.m_save]
        N = [self.n_drafting, self.n_sheet, self.n_base, self.n_top, self.n_b_size, self.n_iso, self.n_csys,
             self.n_text, self.n_feature_params, self.n_smooth, self.n_arrows, self.n_hide_show, self.n_center_marks,
             self.n_radial, self.n_decimals, self.n_change, self.n_update]
        O = [self.o_new, self.o_names, self.o_sphere, self.o_point, self.o_radius, self.o_two, self.o_bake,
             self.o_cylinder, self.o_warning, self.o_save]
        P = [self.p_new, self.p_curve, self.p_points, self.p_mirror, self.p_ends, self.p_arches, self.p_surface,
             self.p_contour, self.p_ribs, self.p_extrude, self.p_bake]
        Q = [self.q_new, self.q_polygon, self.q_lift, self.q_explode, self.q_facets, self.q_solid, self.q_shell,
             self.q_shell_dialog]
        R = [self.r_new, self.r_tube, self.r_grid, self.r_weaverbird, self.r_attractor, self.r_openings, self.r_bake]
        S = [self.p_modeling, self.s_new, self.s_revolve, self.s_plane, self.s_profile, self.s_finish, self.s_revolve_dialog,
             self.s_stack, self.s_rows, self.s_tolerances, self.s_requirement, self.s_report, self.s_redesign,
             self.s_change, self.s_show]
        T = list(getattr(self, "T_STEPS", lambda: [])())
        U = list(getattr(self, "U_STEPS", lambda: [])())
        V = list(getattr(self, "V_STEPS", lambda: [])())
        W = list(getattr(self, "W_STEPS", lambda: [])())
        X = list(getattr(self, "X_STEPS", lambda: [])())
        Y = list(getattr(self, "Y_STEPS", lambda: [])())
        Z = list(getattr(self, "Z_STEPS", lambda: [])())
        AA, AB, AC, AD, AE, AF, AG, AH, AJ, AK = (list(getattr(self, f"{k}_STEPS", lambda: [])())
                                      for k in ("AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AJ", "AK"))
        wanted = [w.strip() for w in (os.environ.get("NXSTYLE_TUTORIALS") or ALL_TUTORIALS).upper().split(",")]
        if "N" in wanted and "M" not in wanted:      # the drawing is of tutorial M's U-Bracket
            wanted.insert(wanted.index("N"), "M")
        if "AC" in wanted and "V" not in wanted:     # AC's sheet is the guide bush V released
            wanted.insert(wanted.index("AC"), "V")
        if "V" in wanted and "T" not in wanted:      # V releases tutorial T's guide bush
            wanted.insert(wanted.index("V"), "T")
        if "KatydidWorkbench" not in Gui.listWorkbenches():
            wanted = [w for w in wanted if w not in "OPQR"]   # Katydid off (--no-katydid): nothing to replay on
        if "SMWorkbench" not in Gui.listWorkbenches():
            wanted = [w for w in wanted if w != "W"]          # SheetMetal off (--no-sheetmetal)
        if "LCInterlockingWorkbench" not in Gui.listWorkbenches():
            wanted = [w for w in wanted if w != "AD"]         # LCInterlocking off (--no-lcinterlocking)
        for key, steps in (("A", A), ("B", B), ("C", C), ("D", D), ("E", E), ("F", F), ("G", G), ("H", H),
                           ("I", I), ("J", J), ("K", K), ("L", L), ("M", M), ("N", N), ("O", O), ("P", P),
                           ("Q", Q), ("R", R), ("S", S), ("T", T), ("U", U), ("V", V), ("W", W), ("X", X), ("Y", Y), ("Z", Z),
                           ("AA", AA), ("AB", AB), ("AC", AC), ("AD", AD), ("AE", AE), ("AF", AF), ("AG", AG), ("AH", AH), ("AJ", AJ),
                           ("AK", AK)):
            if key in wanted:
                yield from steps

    # ---------------------------------------------------------- tutorial A
    def units_step(self):
        """The books choose inches in NX's New dialog. NXStyle parts are metric: the book's sizes are typed in mm."""
        doc = App.ActiveDocument
        shown = App.Units.Quantity("25.4 mm").UserString
        unit = getattr(doc, "UnitSystem", "")
        self.step("Units in the New dialog (the book picks inches)", "metric part kept; book sizes typed in mm",
                  DIFFERS if "mm" in shown else FAIL,
                  f"FreeCAD sets units in Preferences, not in the New dialog; NXStyle defaults to millimetres "
                  f"(document: {unit or 'preference'}; 25.4 mm shows as {shown})")

    def a_new(self):
        self.tutorial = "A: The Adjuster (book in inches, typed in mm)"
        before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200
        self._docs_before = before

    def a_extrude(self):
        new = set(App.listDocuments()) - self._docs_before
        body = self.body()
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N", SAME if new and body else FAIL,
                  f"new document {sorted(new)} with a Body; its datum planes appear when a plane is "
                  "picked (kept hidden otherwise: FreeCAD 1.1.4 hides the part when they stay on)")
        self.units_step()
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def a_plane(self):
        dialog = bool(Gui.Control.activeDialog())
        self.step("Extrude (X) with nothing selected", "X key", SAME if dialog else FAIL,
                  "FreeCAD asks for the sketch plane in the Dialog panel; NX asks in the graphics window"
                  if dialog else f"no dialog opened; modals: {self.modals.seen}")
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.wait = 1500
        self._picked = picked

    def a_profile_clicks(self):
        sk = self.edited_sketch()
        self.step("Pick the XY plane, accept with MB2", "plane row in the Dialog panel + MB2 click",
                  SAME if sk is not None else FAIL,
                  f"picked {self._picked}; sketch in edit: {sk.Label if sk else None}")
        if sk is None:
            raise RuntimeError("no sketch in edit; tutorial A cannot continue")
        self._sk = sk
        self.frame_sketch(sk, 1.25 * IN, 1.25 * IN, 4.5 * IN)
        QtWidgets.QApplication.processEvents()
        self.key("Z")
        QtWidgets.QApplication.processEvents()
        self._tool_on = self.nav().sketch_tool_active()
        pts = [(0, 0), (2.5, 0), (2.5, 0.75), (0.75, 0.75), (0.75, 2.5), (0, 2.5), (0, 0)]
        for (x, y) in pts:
            self.mb1_click(self.screen_point(sk, x * IN, y * IN))
        self.wait = 400

    def a_mb2_end(self):
        n = len(self._sk.Geometry)
        self.step("Profile (Z), six MB1 clicks for the L outline", "Z key + MB1 clicks in the graphics window",
                  SAME if self._tool_on and n >= 6 else FAIL, f"tool active {self._tool_on}; {n} curves drawn")
        self.mb2_click(self.screen_point(self._sk, 1.25 * IN, 1.25 * IN))
        self.wait = 400

    def a_dimensions(self):
        ended = not self.nav().sketch_tool_active()
        self.step("MB2 ends Profile", "MB2 click", SAME if ended else FAIL, f"tool ended = {ended}")
        self.key("D")
        QtWidgets.QApplication.processEvents()
        dim_tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(self._sk, 1.25 * IN, 1.25 * IN))
        self.step("Rapid Dimension (D): 2.5 width, 2.5 height, 0.75 legs", "D key, values applied",
                  DIFFERS if dim_tool else FAIL,
                  "D starts FreeCAD's Dimension tool. FreeCAD does not show NX's dynamic dimensions on click, "
                  "and there is no 'scale the whole sketch to the first dimension?' prompt")
        L = [((0, 0), (2.5 * IN, 0)), ((2.5 * IN, 0), (2.5 * IN, 0.75 * IN)),
             ((2.5 * IN, 0.75 * IN), (0.75 * IN, 0.75 * IN)), ((0.75 * IN, 0.75 * IN), (0.75 * IN, 2.5 * IN)),
             ((0.75 * IN, 2.5 * IN), (0, 2.5 * IN)), ((0, 2.5 * IN), (0, 0))]
        self.rebuild(self._sk, lines=L, constraints=[
            ("Horizontal", 0), ("Vertical", 1), ("Horizontal", 2), ("Vertical", 3), ("Horizontal", 4),
            ("Vertical", 5), ("Coincident", 0, 1, -1, 1), ("DistanceX", 0, 1, 0, 2, 2.5 * IN),
            ("DistanceY", 5, 2, 5, 1, 2.5 * IN), ("DistanceY", 1, 1, 1, 2, 0.75 * IN),
            ("DistanceX", 4, 2, 4, 1, 0.75 * IN)])
        self.info["A sketch dof"] = self._sk.solve()
        self.wait = 300

    def a_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def a_extrude_dialog(self):
        self.wait_dialog("a_extrude_dialog")
        pad = next((o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad"), None)
        open_ = bool(Gui.Control.activeDialog()) and pad is not None
        self.step("Finish Sketch (Ctrl+Q) returns to the Extrude dialog", "Ctrl+Q",
                  SAME if open_ else FAIL, f"Extrude dialog open = {open_}; modals {self.modals.seen}")
        field = self.set_quantity("length", 2.5 * IN)
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        time.sleep(0.2)
        App.ActiveDocument.recompute()
        want = (2.5 * 2.5 - 1.75 * 1.75) * 2.5 * IN ** 3
        got = self.solid_volume()
        same, how_same = self.a_compare(slot=False)
        ok = abs(got - want) < 1e-3 * want and same and not Gui.Control.activeDialog()
        self.step("Extrude: End = Value 2.5, Boolean None, OK", f"typed into '{field}', MB2 = OK",
                  SAME if ok else FAIL, f"volume {got:.1f} mm^3, expected {want:.1f}; {how_same}")
        self.shot("A1_extrude.png")
        self.wait = 600

    def a_face_pick(self):
        # top face of the vertical leg (normal +Y at y = 63.5 mm); the slot is cut down into it.
        # (NotebookLM's step list leaves the slot's place open; this keeps the part one solid.)
        doc = App.ActiveDocument
        body = self.body()
        tip = body.Tip
        face = None
        for i, f in enumerate(tip.Shape.Faces, start=1):
            n = f.normalAt(0, 0)
            if abs(n.y - 1) < 1e-6 and abs(f.CenterOfMass.y - 2.5 * IN) < 1e-6:
                face = f"Face{i}"
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, body.Name, f"{tip.Name}.{face}")
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, pick the top face as sketch plane, Boolean Subtract",
                  f"select face + ribbon '{where} > Extrude (Subtract)'",
                  DIFFERS if b is not None else MISSING,
                  "the Extrude dialog's Boolean list has Subtract (tutorial AE uses it); this replay uses the "
                  "Extrude (Subtract) button, which starts the same command with Subtract chosen")
        self.wait = 1800

    def a_rectangle(self):
        sk = self.edited_sketch()
        if sk is None:
            self.step("Rectangle on the face", "-", FAIL, f"no sketch in edit; modals {self.modals.seen}")
            raise RuntimeError("tutorial A: no sketch on the face")
        self._sk2 = sk
        inv = sk.getGlobalPlacement().inverse()
        # 1.00 in wide (along Z, 0.75 in from the end), across the whole 0.75 in leg
        c1 = inv.multVec(App.Vector(-0.2 * IN, 2.5 * IN, 0.75 * IN))
        c2 = inv.multVec(App.Vector(0.95 * IN, 2.5 * IN, 1.75 * IN))
        self.frame_sketch(sk, (c1.x + c2.x) / 2, (c1.y + c2.y) / 2, 4.5 * IN)
        QtWidgets.QApplication.processEvents()
        self.key("R")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        self.mb1_click(self.screen_point(sk, c1.x, c1.y))
        self.mb1_click(self.screen_point(sk, c2.x, c2.y))
        drawn = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, (c1.x + c2.x) / 2, (c1.y + c2.y) / 2))
        self.step("Rectangle (R), two MB1 clicks, MB2", "R key + MB1 clicks + MB2",
                  SAME if tool and drawn >= 4 else FAIL, f"tool active {tool}; {drawn} curves")
        x0, x1, y0, y1 = min(c1.x, c2.x), max(c1.x, c2.x), min(c1.y, c2.y), max(c1.y, c2.y)
        L = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        self.rebuild(sk, lines=L, constraints=[("Horizontal", 0), ("Vertical", 1), ("Horizontal", 2),
                                               ("Vertical", 3)])
        self.step("Rapid Dimension: 0.50 from edge, 1.00 wide, 0.75 deep", "values applied",
                  DIFFERS, "as in step 6: same tool, no NX dynamic dimensions")
        self.wait = 300

    def a_finish_cut(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def a_cut_dialog(self):
        self.wait_dialog("a_cut_dialog")
        pocket = next((o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pocket"), None)
        open_ = bool(Gui.Control.activeDialog()) and pocket is not None
        self.step("Finish Sketch returns to the (subtract) Extrude dialog", "Ctrl+Q",
                  SAME if open_ else FAIL, f"dialog open = {open_}")
        field = self.set_quantity("length", 0.75 * IN)
        self.step("Reverse Direction into the solid", "-", DIFFERS,
                  "not needed: FreeCAD's subtracting extrude cuts into the solid by default")
        self.mb2_click()
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        base = (2.5 * 2.5 - 1.75 * 1.75) * 2.5
        want = (base - 0.75 * 1.0 * 0.75) * IN ** 3
        got = self.solid_volume()
        solids = len(self.body().Shape.Solids)
        same, how_same = self.a_compare(slot=True)
        ok = abs(got - want) < 1e-3 * want and solids == 1 and same and not Gui.Control.activeDialog()
        self.step("Slot depth 0.75, OK", f"'{field}' = 19.05 mm, MB2 = OK", SAME if ok else FAIL,
                  f"volume {got:.1f} mm^3, expected {want:.1f}; {solids} solid(s); {how_same}")
        self.wait = 400

    def a_compare(self, slot):
        """The Adjuster against the same part made with the Part API: the L section (legs 0.75 thick, 2.5
        long) extruded 2.5 along Z, and the slot 0.75 x 1.0 (Z 0.75 to 1.75), 0.75 deep, in the top of the
        vertical leg. Equal volume alone would pass a slot cut in the wrong place."""
        import Part
        from . import geomcheck
        pts = [(0, 0), (2.5, 0), (2.5, 0.75), (0.75, 0.75), (0.75, 2.5), (0, 2.5), (0, 0)]
        wire = Part.makePolygon([App.Vector(x * IN, y * IN, 0) for x, y in pts])
        ref = Part.Face(wire).extrude(App.Vector(0, 0, 2.5 * IN))
        if slot:
            ref = ref.cut(Part.makeBox(0.75 * IN, 0.75 * IN, 1.0 * IN, App.Vector(0, 1.75 * IN, 0.75 * IN)))
        body = self.body()
        return geomcheck.compare(body.Shape if body is not None else None, ref)

    def fit(self):
        Gui.Selection.clearSelection()
        Gui.runCommand("Std_ViewTrimetric")
        Gui.SendMsgToActiveView("ViewFit")
        self.wait = 2000   # animated view changes must finish before the next action

    def show(self, name):
        rows = []
        for o in App.ActiveDocument.Objects:
            vo = getattr(o, "ViewObject", None)
            if vo is None:
                continue
            row = {"name": o.Name, "type": o.TypeId, "visible": vo.Visibility}
            for prop in ("DisplayMode", "Transparency", "ShapeColor", "ShapeAppearance", "LineColor"):
                if hasattr(vo, prop):
                    try:
                        val = getattr(vo, prop)
                        row[prop] = str(val[0].DiffuseColor) if prop == "ShapeAppearance" else str(val)
                    except Exception as e:
                        row[prop] = f"? {e}"
            rows.append(row)
        self.info[f"display {name}"] = rows
        self.shot(name + ".png")
        try:
            self.view().saveImage(os.path.join(OUT, name + "_3d.png"), 1200, 800, "Current")
        except Exception as e:
            self.info[name] = str(e)
        self.wait = 300

    def a_fit(self):
        self.fit()

    def a_show(self):
        self.show("A_adjuster")

    def b_fit(self):
        self.fit()

    def b_show(self):
        self.show("B_first_part")

    @staticmethod
    def drawn_fraction(png):
        """Share of sampled pixels that are not the light background gradient."""
        from .qt import QtGui
        img = QtGui.QImage(png)
        if img.isNull():
            return 0.0
        hits = total = 0
        for y in range(0, img.height(), 6):
            for x in range(0, img.width(), 6):
                c = img.pixelColor(x, y)
                total += 1
                if min(c.red(), c.green(), c.blue()) < 165 or max(c.red(), c.green(), c.blue()) - \
                        min(c.red(), c.green(), c.blue()) > 60:
                    hits += 1
        return hits / max(total, 1)

    def check_drawn(self, label, name):
        png = os.path.join(OUT, name)
        self.view().saveImage(png, 900, 600, "Current")
        frac = self.drawn_fraction(png)
        self.step(label, "render of the graphics window", SAME if frac > 0.02 else FAIL,
                  f"{frac:.1%} of the view shows the part (an occupancy check: something is drawn; the shape "
                  "itself is checked by its geometry)")

    @staticmethod
    def saved_comment(path):
        """The Comment stored in an .FCStd on disk, or None when the file cannot be read."""
        import xml.etree.ElementTree as ET
        import zipfile
        try:
            with zipfile.ZipFile(path) as z:
                root = ET.fromstring(z.read("Document.xml"))
        except Exception:
            return None
        for prop in root.findall("./Properties/Property"):     # the document's own, not its objects'
            if prop.get("name") == "Comment":
                s = prop.find("String")
                return s.get("value") if s is not None else None
        return None

    def save_ctrl_s(self, name):
        """Save the way the book does, with Ctrl+S. A new part's first save opens the operating system's
        file dialog, which the replay cannot drive, so the file name is given once by script; then the part's
        Comment is set to a marker unique to this save and Ctrl+S is pressed. Ctrl+S has saved when the file
        on disk holds the marker and the part is left unmodified. The file's time is no witness: FreeCAD
        writes a temporary file and renames it over the old one, and in the replays the new file came back
        with the replaced file's last-write time in 4 of 10 saves, the change in it.
        Returns (outcome, how, detail, path): FAIL when Ctrl+S did not save, whatever the scripted save did."""
        import uuid
        doc = App.ActiveDocument
        path = os.path.join(OUT, name)
        doc.saveAs(path)
        st0 = os.stat(path)
        time.sleep(1.1)                     # so the recorded file times show whether the time moved
        marker = f"saved with Ctrl+S by the replay {uuid.uuid4().hex[:12]}"
        doc.Comment = marker
        gdoc = Gui.getDocument(doc.Name)
        modified = getattr(gdoc, "Modified", True)
        on_disk_before = self.saved_comment(path)
        saves = SaveWatch(path)
        App.addDocumentObserver(saves)
        try:
            self.key("Ctrl+S")
            QtWidgets.QApplication.processEvents()
            self.wait_for("Ctrl+S: the file holds the change", lambda: self.saved_comment(path) == marker,
                          timeout_ms=10000)
        finally:
            App.removeDocumentObserver(saves)
        on_disk = self.saved_comment(path)
        st1 = os.stat(path)
        still = getattr(gdoc, "Modified", "?")
        self.info[f"save {name}"] = {
            "modified before the key": modified, "saves seen": saves.seen,
            "file time moved ms": (st1.st_mtime_ns - st0.st_mtime_ns) // 10 ** 6,
            "size before, after": [st0.st_size, st1.st_size],
            "Ctrl+S owners": sorted(Gui.Command.listByShortcut("Ctrl+S")),
            "focus": type(QtWidgets.QApplication.focusWidget()).__name__}
        saved = on_disk_before != marker and on_disk == marker and still is False
        how = ("file name given once by script (the system file dialog is not driven); a change, then the "
               "Ctrl+S key")
        detail = (f"{name} rewritten by Ctrl+S: the file holds the change and the part is unmodified afterwards "
                  f"(modified before the key: {modified}); FreeCAD format, not .prt" if saved else
                  f"Ctrl+S did not save: the change {'is' if on_disk == marker else 'is not'} in the file "
                  f"(it {'was' if on_disk_before == marker else 'was not'} before the key), still modified "
                  f"{still}; FreeCAD saves seen during the key: {saves.seen or 'none'}")
        return (SAME if saved else FAIL), how, detail, path

    def a_save(self):
        self.check_drawn("The finished part is shown in the graphics window", "A_live_check.png")
        outcome, how, detail, path = self.save_ctrl_s("Adjuster.FCStd")
        doc = App.ActiveDocument
        App.closeDocument(doc.Name)
        App.openDocument(path)
        QtWidgets.QApplication.processEvents()
        Gui.SendMsgToActiveView("ViewFit")
        QtWidgets.QApplication.processEvents()
        self.step("Save (Ctrl+S)", how, outcome, detail)
        self.check_drawn("Reopened part is shown", "A_reopened_check.png")
        self.wait = 300

    # ---------------------------------------------------------- tutorial B
    def b_new(self):
        self.tutorial = "B: First part, cylinder and cone (mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def b_extrude(self):
        new = set(App.listDocuments()) - self._docs_before
        self.step("File > New (Ctrl+N), Model template, mm", "Ctrl+N",
                  SAME if new and self.body() else FAIL, f"new document {sorted(new)}")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def b_plane(self):
        dialog = bool(Gui.Control.activeDialog())
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude (X), pick the XC-YC plane", "X key, plane row + MB2", SAME if dialog else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def b_circles(self):
        sk = self.edited_sketch()
        if sk is None:
            self.step("Circle tool", "-", FAIL, "no sketch in edit")
            raise RuntimeError("tutorial B: no sketch")
        self._sk = sk
        self.frame_sketch(sk, 0, 0, 80)
        QtWidgets.QApplication.processEvents()
        self.key("O")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for r in (25, 15):
            self.mb1_click(self.screen_point(sk, 0, 0))
            self.mb1_click(self.screen_point(sk, r, 0))
        n = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, 30, 30))
        ended = not self.nav().sketch_tool_active()
        self.step("Circle (O): two circles at the origin, MB2", "O key + MB1 clicks + MB2",
                  SAME if tool and n >= 2 and ended else FAIL, f"tool {tool}; {n} circles; ended {ended}")
        self.rebuild(sk, circles=[((0, 0), 25), ((0, 0), 15)],
                     constraints=[("Coincident", 0, 3, -1, 1), ("Coincident", 1, 3, -1, 1),
                                  ("Diameter", 0, 50), ("Diameter", 1, 30)])
        self.step("Rapid Dimension: diameters 50 and 30", "values applied", DIFFERS,
                  "same tool; values typed in FreeCAD's dimension field")
        self.wait = 300

    def b_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def b_extrude_dialog(self):
        self.wait_dialog("b_extrude_dialog")
        open_ = bool(Gui.Control.activeDialog())
        field = self.set_quantity("length", 50)
        self.mb2_click()
        App.ActiveDocument.recompute()
        want = math.pi * (25 ** 2 - 15 ** 2) * 50
        got = self.solid_volume()
        ok = open_ and abs(got - want) < 1e-3 * want
        self.step("Finish Sketch, Extrude 0 to 50 mm, OK", f"Ctrl+Q, '{field}' = 50, MB2 = OK",
                  SAME if ok else FAIL, f"volume {got:.1f} mm^3, expected {want:.1f}")
        self.wait = 600

    def b_revolve(self):
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Revolve")
        self.step("Revolve (ribbon)", f"ribbon '{where} > Revolve'", SAME if b is not None else MISSING,
                  "nothing selected: sketch first, as with Extrude")
        self.wait = 1500

    def b_plane_yz(self):
        picked = self.pick_in_feature_list("YZ")
        self.mb2_click()
        self.step("Pick the YC-ZC plane", "plane row + MB2", SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def b_lines(self):
        sk = self.edited_sketch()
        if sk is None:
            self.step("Line tool", "-", FAIL, "no sketch in edit")
            raise RuntimeError("tutorial B: no revolve sketch")
        self._sk2 = sk
        self.frame_sketch(sk, 12, 75, 90)
        QtWidgets.QApplication.processEvents()
        self.key("L")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for (a, b) in (((0, 50), (25, 50)), ((25, 50), (0, 100)), ((0, 100), (0, 50))):
            self.mb1_click(self.screen_point(sk, *a))
            self.mb1_click(self.screen_point(sk, *b))
        n = len(sk.Geometry)
        self.mb2_click(self.screen_point(sk, 40, 90))
        self.step("Line (L): right triangle on the axis, MB2", "L key + MB1 clicks + MB2",
                  SAME if tool and n >= 3 else FAIL, f"tool {tool}; {n} lines")
        self.rebuild(sk, lines=[((0, 50), (25, 50)), ((25, 50), (0, 100)), ((0, 100), (0, 50))],
                     constraints=[("Horizontal", 0), ("Vertical", 2), ("PointOnObject", 0, 1, -2),
                                  ("DistanceX", 0, 1, 0, 2, 25), ("DistanceY", 2, 2, 2, 1, 50),
                                  ("DistanceY", -1, 1, 0, 1, 50)])
        self.step("Rapid Dimension: height 50, radius 25", "values applied", DIFFERS, "same tool")
        self.wait = 300

    def b_finish_revolve(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def b_revolve_dialog(self):
        self.wait_dialog("b_revolve_dialog")
        rev = next((o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Revolution"), None)
        open_ = bool(Gui.Control.activeDialog()) and rev is not None
        axis = rev.ReferenceAxis[1] if rev is not None and rev.ReferenceAxis else None
        self.step("Finish Sketch returns to Revolve; axis = Z, 0..360 deg", "Ctrl+Q",
                  SAME if open_ else FAIL, f"dialog open {open_}; default axis {axis} (sketch V axis = Z)")
        self.mb2_click()
        App.ActiveDocument.recompute()
        want = math.pi * (25 ** 2 - 15 ** 2) * 50 + math.pi * 25 ** 2 * 50 / 3
        got = self.solid_volume()
        ok = abs(got - want) < 1e-3 * want and not Gui.Control.activeDialog()
        self.step("Boolean Unite, OK", "MB2 = OK", SAME if ok else FAIL,
                  f"volume {got:.1f} mm^3, expected {want:.1f}; features in one Body unite automatically")
        self.wait = 400

    def b_inspect(self):
        f = self.nav()
        cam = self.view().getCameraNode()
        o0 = cam.orientation.getValue().getValue()
        p = QtCore.QPoint(f.widget.width() // 2, f.widget.height() // 2)
        self.send(QtCore.QEvent.MouseButtonPress, p, Qt.MiddleButton, Qt.MiddleButton)
        for i in range(1, 11):
            self.send(QtCore.QEvent.MouseMove, QtCore.QPoint(p.x() + 7 * i, p.y() + 3 * i), Qt.NoButton,
                      Qt.MiddleButton)
        self.send(QtCore.QEvent.MouseButtonRelease, QtCore.QPoint(p.x() + 70, p.y() + 30), Qt.MiddleButton,
                  Qt.NoButton)
        o1 = cam.orientation.getValue().getValue()
        self.step("Hold MB2 and drag to rotate", "MB2 drag", SAME if o1 != o0 else FAIL, "")
        self.key("F8")
        self.wait = 900

    def b_snap(self):
        def snapped():
            v = self.view().getViewDirection()
            return max(abs(v.x), abs(v.y), abs(v.z)) > 0.999
        ok = self.wait_for("b_snap: view animation", snapped)      # the snap animates; slower under load
        d = self.view().getViewDirection()
        self.step("F8 snaps to the nearest standard view", "F8 key", SAME if ok else FAIL, f"view {d}")
        self.check_drawn("The finished part is shown in the graphics window", "B_live_check.png")
        outcome, how, detail, _ = self.save_ctrl_s("FirstPart.FCStd")
        self.step("Save (Ctrl+S)", how, outcome, detail)
        self.shot("B2_snapped.png")
        self.wait = 200

    # ------------------------------------------------------- more helpers
    def set_spin(self, name_part, value):
        """Type a value into an integer or quantity field in the task panel.

        Integer fields get the text typed and interpreted, as a user's typing is:
        FreeCAD's Gui::UIntSpinBox keeps unsigned values offset by 2^31 inside a
        QSpinBox, so QSpinBox.setValue(5) from Python stores 5 + 2^31 (clamped
        to INT_MAX). On a pattern's Occurrences that asked for ~19 GB."""
        for w in self.tasks_dock().findChildren(QtWidgets.QAbstractSpinBox):
            if name_part.lower() in w.objectName().lower():
                if isinstance(w, QtWidgets.QSpinBox):
                    w.lineEdit().setText(str(int(value)))
                    w.interpretText()
                else:
                    self.type_into(w, value)
                return w.objectName()   # no processEvents: callers check the value before a recompute
        return None

    def choose(self, option_part, name_part=""):
        """Pick a list entry in whichever task-panel combo offers it (names differ between versions)."""
        # a dialog that has just opened may not be laid out yet: prefer visible lists, keep the rest
        combos = self.tasks_dock().findChildren(QtWidgets.QComboBox)
        combos.sort(key=lambda c: (name_part.lower() not in c.objectName().lower(), not c.isVisible()))
        for c in combos:
            if any(self._matches(option_part, c.itemText(i)) for i in range(c.count())):
                return self.set_combo(c.objectName(), option_part) if c.objectName() else None
        self.progress(f"choose '{option_part}': not offered; combos " + str(
            {c.objectName(): [c.itemText(i) for i in range(c.count())]
             for c in self.tasks_dock().findChildren(QtWidgets.QComboBox)}))
        return None

    def task_widgets(self):
        """objectName: class of everything in the Dialog panel (for the report)."""
        return sorted({f"{w.objectName()}:{type(w).__name__}" for w in self.tasks_dock().findChildren(QtWidgets.QWidget)
                       if w.objectName() and not w.objectName().startswith("qt_")})

    def ribbon_dropdown(self, drop_label, tab=None):
        """(button, tab index) of a ribbon drop-down: an NX drop-down (DropdownButton) or a FreeCAD group command's
        button (its menu lists the group's entries); with tab given, that tab is searched first."""
        from .ribbon import DropdownButton
        r = self.shell.ribbon
        order = sorted(range(r.stack.count()), key=lambda i: tab is not None and r.tabs.tabText(i) != tab)
        for i in order:
            for b in r.stack.widget(i).findChildren(QtWidgets.QToolButton):
                label = b.text() if isinstance(b, DropdownButton) else getattr(b, "nx_label", None)
                if isinstance(b, (DropdownButton, CommandButton)) and label == drop_label and b.menu() is not None:
                    return b, i
        return None, -1

    def dropdown_entries(self, drop_label, tab=None):
        b, _i = self.ribbon_dropdown(drop_label, tab)
        return [clean_text(a.text()) for a in b.menu().actions() if not a.isSeparator()] if b is not None else []

    def click_dropdown(self, drop_label, item_label, tab=None):
        """Open a ribbon drop-down and pick an entry, as a user does; returns the tab or None."""
        b, i = self.ribbon_dropdown(drop_label, tab)
        if b is None:
            return None
        r = self.shell.ribbon
        for a in b.menu().actions():
            if clean_text(a.text()) == item_label:
                r.tabs.setCurrentIndex(i)
                QtWidgets.QApplication.processEvents()
                for _ in range(20):               # FreeCAD refreshes the entries' state on a timer, as a user waits
                    if a.isEnabled():
                        break
                    qtest().qWait(100)
                self.info.setdefault("ribbon clicks while disabled", []).extend(
                    [] if a.isEnabled() else [f"{drop_label} > {item_label}"])
                a.trigger()
                return r.tabs.tabText(i)
        return None

    def newest(self, type_id):
        objs = [o for o in App.ActiveDocument.Objects if o.TypeId == type_id]
        return objs[-1] if objs else None

    def face_of(self, obj, test):
        for i, f in enumerate(obj.Shape.Faces, start=1):
            try:
                if test(f):
                    return f"Face{i}"
            except Exception:
                continue
        return None

    def select_sub(self, obj, sub):
        doc = App.ActiveDocument
        body = self.body()
        Gui.Selection.clearSelection()
        if obj.isDerivedFrom("PartDesign::Feature") or obj.isDerivedFrom("Part::Datum"):
            Gui.Selection.addSelection(doc.Name, body.Name, f"{obj.Name}.{sub}" if sub else f"{obj.Name}.")
        else:
            Gui.Selection.addSelection(doc.Name, obj.Name, sub or "")

    def draw_clicks(self, key, pts):
        """Start a sketch tool by key, click the given sketch points, end it with MB2."""
        sk = self.edited_sketch()
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        self.frame_sketch(sk, (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, span * 1.8)
        QtWidgets.QApplication.processEvents()
        self.key(key)
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for (x, y) in pts:
            self.mb1_click(self.screen_point(sk, x, y))
        n = len(sk.Geometry)
        away = self.screen_point(sk, min(xs) - span * 0.6, max(ys) + span * 0.6)
        self.mb2_click(away)
        ended = not self.sketch_tool_running(away)
        return sk, tool, n, ended

    @staticmethod
    def add_geometry(sketch, geos):
        sketch.deleteAllGeometry()
        for g in geos:
            sketch.addGeometry(g, False)
        App.ActiveDocument.recompute()

    def check_volume(self, label, how, want, extra=""):
        App.ActiveDocument.recompute()
        got = self.solid_volume()
        solids = len(self.body().Shape.Solids) if self.body() is not None else 0
        ok = abs(got - want) < 1e-3 * max(want, 1e-9) and solids == 1 and not Gui.Control.activeDialog()
        self.step(label, how, SAME if ok else FAIL,
                  f"volume {got:.1f} mm^3, expected {want:.1f}; {solids} solid(s){extra}")
        return ok

    # ---------------------------------------------------------- tutorial C
    # Rod-Guide (Shih ch. 9). The book gives the block's size only in figures;
    # 3.00 x 2.00 in is NotebookLM's reading. The upper angled feature's profile
    # is figure-only and is not replayed.
    def c_new(self):
        self.tutorial = "C: Rod-Guide (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def c_extrude(self):
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def c_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude (X), pick the XY plane", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def c_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        _, tool, n, ended = self.draw_clicks("R", [(-1.5 * IN, -1.0 * IN), (1.5 * IN, 1.0 * IN)])
        self.step("Rectangle (R) by 2 points around the origin", "R key + 2 MB1 clicks + MB2",
                  SAME if tool and n >= 4 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self.key("F")
        QtWidgets.QApplication.processEvents()
        fillet_tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, 2.5 * IN, 2.0 * IN))
        self.step("Sketch Fillet (F), R0.25 on the four corners", "F key; corners applied as values",
                  DIFFERS if fillet_tool else FAIL,
                  "F starts FreeCAD's sketch fillet; the radius is typed after picking, not before as in NX")
        self.key("O")
        QtWidgets.QApplication.processEvents()
        circle_tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, 2.5 * IN, 2.0 * IN))
        r, w, h = 0.25 * IN, 1.5 * IN, 1.0 * IN
        V = App.Vector
        Z = V(0, 0, 1)
        geos = [Part.LineSegment(V(-w + r, -h, 0), V(w - r, -h, 0)),
                Part.LineSegment(V(w, -h + r, 0), V(w, h - r, 0)),
                Part.LineSegment(V(w - r, h, 0), V(-w + r, h, 0)),
                Part.LineSegment(V(-w, h - r, 0), V(-w, -h + r, 0))]
        for (cx, cy, a0) in ((w - r, -h + r, -90), (w - r, h - r, 0), (-w + r, h - r, 90), (-w + r, -h + r, 180)):
            geos.append(Part.ArcOfCircle(Part.Circle(V(cx, cy, 0), Z, r), math.radians(a0), math.radians(a0 + 90)))
        for (cx, cy) in ((w - r, -h + r), (w - r, h - r), (-w + r, h - r), (-w + r, -h + r)):
            geos.append(Part.Circle(V(cx, cy, 0), Z, 0.125 * IN))
        self.add_geometry(sk, geos)
        import Sketcher
        for i in (9, 10, 11):
            sk.addConstraint(Sketcher.Constraint("Equal", 8, i))
        App.ActiveDocument.recompute()
        self.step("Circle (O): four Ø0.25 circles on the arc centres, Equal Radius", "O key; values applied",
                  SAME if circle_tool else FAIL, "Equal constraint exists in both")
        self.wait = 300

    def c_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def c_extrude_dialog(self):
        self.wait_dialog("c_extrude_dialog")
        field = self.set_quantity("length", 0.75 * IN)
        self.mb2_click()
        r = 0.25
        area = 3.0 * 2.0 - 4 * (r * r - math.pi * r * r / 4) - 4 * math.pi * 0.125 ** 2
        self._c_base = area * 0.75 * IN ** 3
        self.check_volume("Finish Sketch, Extrude 0.75, OK", f"Ctrl+Q, '{field}' = 19.05 mm, MB2 = OK", self._c_base)
        self.wait = 600

    def c_datum_angle(self):
        pad = self.body().Tip
        face = self.face_of(pad, lambda f: abs(f.normalAt(0, 0).y + 1) < 1e-6)
        self.select_sub(pad, face)
        where = self.click_dropdown("Datum", "Datum Plane")
        self._before_planes = len([o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Plane"])
        self.step("Datum Plane, At Angle: front face", f"select face + ribbon '{where} > Datum > Datum Plane'",
                  SAME if where and Gui.Control.activeDialog() else FAIL,
                  "the datum is attached to the face; FreeCAD's attachment dialog opens")
        self.wait = 1200

    def c_datum_angle_ok(self):
        self.wait_dialog("c_datum_angle_ok")
        plane = self.newest("PartDesign::Plane")
        used = None
        for axis in ("yaw", "pitch", "roll"):
            name = self.set_quantity(f"attachmentoffset{axis}", -30)
            QtWidgets.QApplication.processEvents()
            App.ActiveDocument.recompute()
            n = plane.Placement.Rotation.multVec(App.Vector(0, 0, 1))
            if name and abs(n.z) < 1e-6 and abs(abs(n.dot(App.Vector(0, -1, 0))) - math.cos(math.radians(30))) < 1e-4:
                used = name
                break
            if name:
                self.set_quantity(f"attachmentoffset{axis}", 0)
        self.mb2_click()
        App.ActiveDocument.recompute()
        n = plane.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        ang = math.degrees(math.acos(min(1.0, abs(n.dot(App.Vector(0, -1, 0))))))
        ok = used and abs(ang - 30) < 0.01 and not Gui.Control.activeDialog()
        self.step("Angle -30° about the vertical axis, OK", f"'{used}' = -30°, MB2 = OK",
                  DIFFERS if ok else FAIL,
                  f"plane at {ang:.2f}° to the face. NX picks the Z axis as hinge; FreeCAD rotates in the "
                  "attachment offset about the face's own axes")
        self.wait = 500

    def c_upper_feature(self):
        self.step("Extrude the angled upper block on the datum plane (Unite, Symmetric 1.0)", "-", "skipped",
                  "the profile's dimensions are only in the book's figures")

    def c_datum_offset(self):
        pad = next(o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Pad")
        face = self.face_of(pad, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 0.75 * IN) < 1e-6)
        self.select_sub(pad, face)
        where = self.click_dropdown("Datum", "Datum Plane")
        self.step("Datum Plane, At Distance: top face", f"select face + ribbon '{where} > Datum > Datum Plane'",
                  SAME if where and Gui.Control.activeDialog() else FAIL, "")
        self.wait = 1200

    def c_datum_offset_ok(self):
        self.wait_dialog("c_datum_offset_ok")
        plane = self.newest("PartDesign::Plane")
        field = self.set_quantity("attachmentoffsetz", 0.75 * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        z = plane.Placement.Base.z / IN
        self._c_plane = plane
        self.step("Distance 0.75, OK", f"'{field}' = 19.05 mm, MB2 = OK",
                  SAME if abs(z - 1.5) < 1e-6 and not Gui.Control.activeDialog() else FAIL,
                  f"datum plane at z = {z * IN:.2f} mm (top face 19.05 + 19.05)")
        self.wait = 500

    def c_hole(self):
        self.select_sub(self._c_plane, "")
        b, where = self.click_ribbon("Hole")
        sk = None
        QtWidgets.QApplication.processEvents()
        self.step("Hole, placed on the offset datum plane", f"select plane + ribbon '{where} > Hole'",
                  DIFFERS if b is not None else MISSING,
                  "FreeCAD's Hole drills at circle centres in a sketch, so Hole starts a sketch on the plane "
                  "(NX picks the point directly)")
        self._sk = sk
        self.wait = 1500

    def c_hole_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError(f"no hole sketch in edit; modals {self.modals.seen}")
        _, tool, n, ended = self.draw_clicks("O", [(0, 0), (0.125 * IN, 0)])
        self.add_geometry(sk, [Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 0.125 * IN)])
        self.step("Place the hole centre at the WCS origin", "O key + MB1 at the origin + MB2",
                  SAME if tool and n >= 1 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self.wait = 300

    def c_finish_hole(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def c_hole_dialog(self):
        self.wait_dialog("c_hole_dialog")
        hole = self.newest("PartDesign::Hole")
        open_ = bool(Gui.Control.activeDialog()) and hole is not None
        dia = self.set_quantity("diameter", 0.25 * IN)
        depth = self.set_combo("depthtype", "through")
        self.info["C hole dialog widgets"] = self.task_widgets()
        self.mb2_click()
        want = self._c_base - math.pi * 0.125 ** 2 * 0.75 * IN ** 3
        ok = self.check_volume("Hole: Simple, Ø0.25, Through Body, OK",
                               f"dialog open {open_}; '{dia}' = 6.35 mm, '{depth}', MB2 = OK", want)
        if not ok and hole is not None:
            self.info["C hole state"] = {"Diameter": str(hole.Diameter), "DepthType": hole.DepthType,
                                         "Reversed": getattr(hole, "Reversed", None)}
        self.wait = 500

    def c_fit(self):
        self.fit()

    def c_show(self):
        self.show("C_rod_guide")
        self.check_drawn("The finished part is shown in the graphics window", "C_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Rod-Guide.FCStd"))

    # ---------------------------------------------------------- tutorial D
    # Pulley (Shih ch. 11). The book's profile dimensions are in figures; the
    # values below are NotebookLM's (Ø4.00, 1.00 wide, hub Ø1.50, bore Ø0.75,
    # web 0.25, 5 x Ø0.50 holes on a 2.50 pitch circle), halved for the half
    # model that Mirror Feature completes.
    HALF = [(0, 0.375), (0.5, 0.375), (0.5, 0.75), (0.125, 0.75), (0.125, 1.75), (0.5, 1.75), (0.5, 2.0), (0, 2.0)]

    def d_volume_half(self):
        rects = [(0.5, 0.375, 0.75), (0.125, 0.75, 1.75), (0.5, 1.75, 2.0)]   # (width, r0, r1)
        return sum(w * math.pi * (r1 ** 2 - r0 ** 2) for (w, r0, r1) in rects) * IN ** 3

    def d_new(self):
        self.tutorial = "D: Pulley with drawing (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def d_revolve(self):
        self.step("File > New (Ctrl+N), Model template", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Revolve")
        self.step("Revolve, nothing selected", f"ribbon '{where} > Revolve'", SAME if b is not None else MISSING, "")
        self.wait = 1500

    def d_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Pick the XY plane of the datum CSYS", "plane row + MB2", SAME if picked else FAIL, f"{picked}")
        self.wait = 1500

    def d_profile(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        pts = [(x * IN, y * IN) for (x, y) in self.HALF] + [(self.HALF[0][0] * IN, self.HALF[0][1] * IN)]
        _, tool, n, ended = self.draw_clicks("Z", pts)
        self.step("Profile (Z): closed half cross-section, MB2", "Z key + 9 MB1 clicks + MB2",
                  SAME if tool and n >= 8 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        P = [App.Vector(x * IN, y * IN, 0) for (x, y) in self.HALF]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % len(P)]) for i in range(len(P))])
        self.step("Rapid Dimension: profile sizes", "values applied", DIFFERS, "same tool; no dynamic dimensions")
        self.wait = 300

    def d_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def d_revolve_dialog(self):
        self.wait_dialog("d_revolve_dialog")
        rev = self.newest("PartDesign::Revolution")
        axis = self.set_combo("axis", "x axis") or self.set_combo("axis", "horizontal")
        self.mb2_click()
        self.check_volume("Specify Vector = X axis through the origin, 0..360°, OK",
                          f"axis '{axis}', MB2 = OK", self.d_volume_half(),
                          "; NX picks the axis in the graphics window, FreeCAD lists it in the dialog")
        self._d_rev = rev
        self.wait = 600

    def d_mirror(self):
        self.select_sub(self._d_rev, "")
        b, where = self.click_ribbon("Mirror Feature")
        self.step("Mirror Feature: select the revolved feature, MB2 to proceed",
                  f"feature selected + ribbon '{where} > Mirror Feature'",
                  DIFFERS if b is not None and Gui.Control.activeDialog() else FAIL,
                  "selecting first and then starting Mirror Feature replaces NX's 'select, then MB2'")
        self.wait = 1500

    def d_mirror_dialog(self):
        self.wait_dialog("d_mirror_dialog")
        plane = self.set_combo("plane", "yz")
        self.info["D mirror dialog widgets"] = self.task_widgets()
        self.mb2_click()
        self.check_volume("Plane = the back face (on the YZ plane), OK; Unite",
                          f"plane '{plane}', MB2 = OK", 2 * self.d_volume_half(),
                          "; inside a Body the mirror unites by itself, so NX's separate Unite step is not needed")
        self.wait = 600

    def d_leader(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).x - 1) < 1e-6
                            and abs(f.CenterOfMass.x - 0.125 * IN) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Pattern leader: Extrude on the front face of the web, Subtract",
                  f"select face + ribbon '{where} > Extrude (Subtract)'", DIFFERS if b is not None else MISSING,
                  "subtracting extrude is its own button in FreeCAD")
        self.wait = 1500

    def d_leader_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no leader sketch in edit")
        inv = sk.getGlobalPlacement().inverse()
        c = inv.multVec(App.Vector(0.125 * IN, 0, 1.25 * IN))
        e = inv.multVec(App.Vector(0.125 * IN, 0, 1.5 * IN))
        _, tool, n, ended = self.draw_clicks("O", [(c.x, c.y), (e.x, e.y)])
        self.add_geometry(sk, [Part.Circle(App.Vector(c.x, c.y, 0), App.Vector(0, 0, 1), 0.25 * IN)])
        self.step("Circle Ø0.50 on the 2.50 pitch circle", "O key + MB1 clicks + MB2; values applied",
                  SAME if tool and n >= 1 and ended else FAIL, f"tool {tool}; {n} curves")
        self.wait = 300

    def d_finish_leader(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def d_leader_dialog(self):
        self.wait_dialog("d_leader_dialog")
        mode = self.choose("through all", "mode")
        self.info["D leader dialog widgets"] = self.task_widgets()
        self.mb2_click()
        self._d_hole = math.pi * 0.25 ** 2 * 0.25 * IN ** 3
        self.check_volume("Reverse Direction, End = Through All, OK", f"'{mode}', MB2 = OK",
                          2 * self.d_volume_half() - self._d_hole, "; no Reverse needed in FreeCAD")
        self.wait = 600

    def d_pattern(self):
        pocket = self.newest("PartDesign::Pocket")
        self.select_sub(pocket, "")
        b, where = self.click_ribbon("Circular Pattern")
        self.step("Pattern Feature, Layout = Circular", f"leader selected + ribbon '{where} > Circular Pattern'",
                  DIFFERS if b is not None and Gui.Control.activeDialog() else FAIL,
                  "NX has one Pattern Feature with a Layout list; FreeCAD has separate linear and circular buttons")
        self.wait = 1500

    def pattern_state(self):
        pat = self.newest("PartDesign::PolarPattern")
        if pat is None:
            return "no PolarPattern"
        return {p: str(getattr(pat, p)) for p in pat.PropertiesList
                if p in ("Axis", "Angle", "Occurrences", "Offset", "Mode", "Originals", "Reversed")}

    def d_pattern_dialog(self):
        self.wait_dialog("d_pattern_dialog")
        axis = self.choose("x axis", "axis") or self.choose("x axis", "direction")
        count = self.set_spin("occurrences", 5)
        state = self.pattern_state()
        self.progress(f"d_pattern_dialog: axis '{axis}', count '{count}' -> {state}")
        self.info["D pattern dialog widgets"] = self.task_widgets()
        pat = self.newest("PartDesign::PolarPattern")
        if pat is None or pat.Occurrences != 5:
            # never confirm (or let recompute) a pattern with a count nobody asked for
            if pat is not None:
                pat.Occurrences = 2
            Gui.Control.closeDialog()
            raise RuntimeError(f"pattern count not set: {state}")
        used = f"axis '{axis}'" if axis else f"default axis {pat.Axis[1]} of {pat.Axis[0].Label}"
        self.mb2_click()
        self.check_volume("Axis X, Count and Span: 5 over 360°, OK", f"{used}, '{count}' = 5, MB2 = OK",
                          2 * self.d_volume_half() - 5 * self._d_hole,
                          "" if axis else "; the leader sketch's normal is the pulley's X axis here")
        self.wait = 600

    def d_fit(self):
        self.fit()

    def d_show(self):
        self.show("D_pulley")
        self.check_drawn("The finished part is shown in the graphics window", "D_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Pulley.FCStd"))
        self._d_doc = App.ActiveDocument.Name

    def d_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def d_sheet(self):
        wb = Gui.activeWorkbench().name()
        self.step("File > Drafting (Ctrl+Shift+D)", "Ctrl+Shift+D",
                  SAME if wb == "TechDrawWorkbench" and self.shell.ribbon.has_tab("Home") else FAIL, wb)
        b, where = self.click_ribbon("New Sheet")
        QtWidgets.QApplication.processEvents()
        page = self.newest("TechDraw::DrawPage")
        tmpl = page.Template.Template if page is not None and page.Template else ""
        self.step("New sheet, A-size, 1:1", f"ribbon '{where} > New Sheet'", DIFFERS if page else FAIL,
                  f"FreeCAD's default template {os.path.basename(str(tmpl))}; an ANSI A sheet is one "
                  "template choice away (Sheet from Template)")
        self._page = page
        self.wait = 1200

    def d_base_view(self):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self.body().Name)
        b, where = self.click_ribbon("Base View")
        self.wait = 1500
        self._views_before = len(self._page.Views)
        self._base_where = where

    def d_base_view_check(self):
        views = [v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        dialog = bool(Gui.Control.activeDialog())
        base = views[-1] if views else None
        if base is not None:
            base.Direction = App.Vector(1, 0, 0)
            base.XDirection = App.Vector(0, -1, 0)
        if dialog:
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        self._base = base
        self.step("Base View: Right view of the pulley", f"body selected + ribbon '{self._base_where} > Base View'"
                  f"{'; dialog closed with MB2' if dialog else ''}",
                  SAME if base is not None and not Gui.Control.activeDialog() else FAIL,
                  f"{len(views)} view(s) on the sheet; direction set to Right (+X)")
        self.wait = 800

    def mb2_click_on_sheet(self):
        """Middle click in the middle of the active drawing sheet (not a 3D view)."""
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi else None
        views = sub.widget().findChildren(QtWidgets.QGraphicsView) if sub else []
        if not views:
            return False
        target = views[0].viewport()
        p = QtCore.QPoint(target.width() // 2, target.height() // 2)
        for kind, buttons in ((QtCore.QEvent.MouseButtonPress, Qt.MiddleButton),
                              (QtCore.QEvent.MouseButtonRelease, Qt.NoButton)):
            QtWidgets.QApplication.sendEvent(target, mouse_event(kind, p, Qt.MiddleButton, buttons, Qt.NoModifier))
        return True

    def d_extra_view(self):
        doc = App.ActiveDocument
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self.body().Name)
        self.click_ribbon("Base View")
        self.wait = 1500

    def d_delete_view(self):
        views = [v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        if Gui.Control.activeDialog():
            from .navigation import accept_task_dialog
            accept_task_dialog()
        extra = views[-1] if len(views) > 1 else None
        n0 = len(views)
        if extra is not None:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, extra.Name)
            self.modals.accept = True
            self.key("Delete")
            QtWidgets.QApplication.processEvents()
            self.modals.accept = False
        App.ActiveDocument.recompute()
        n1 = len([v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")])
        self.step("Add a projected view, select it, Delete key", "Base View again + Delete key",
                  DIFFERS if extra is not None and n1 == n0 - 1 else FAIL,
                  f"views {n0} -> {n1}. NX drags projected views off the base view; FreeCAD's Projected View "
                  "is a projection group, so a second Base View stood in for it")
        self.wait = 800

    def d_section(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self._base.Name)
        b, where = self.click_ribbon("Section View")
        self._sec_where = where
        self.wait = 1500

    def d_section_dialog(self):
        self.wait_dialog("d_section_dialog")
        dock = self.tasks_dock()
        pressed = None
        for btn in dock.findChildren(QtWidgets.QAbstractButton):
            if btn.objectName().lower() in ("pbright", "pbleft") and btn.isVisible():
                btn.click()
                pressed = btn.objectName()
                break
        self.info["D section dialog widgets"] = self.task_widgets()
        QtWidgets.QApplication.processEvents()
        buttons = [(b.text(), b.isVisible(), b.isEnabled()) for box in dock.findChildren(QtWidgets.QDialogButtonBox)
                   for b in box.buttons()]
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi else None
        sent = self.mb2_click_on_sheet()
        self.progress(f"d_section_dialog: direction {pressed}; buttons {buttons}; "
                      f"active window '{sub.windowTitle() if sub else None}'; MB2 sent {sent}; "
                      f"filter: {self.shell.navigation.mb2_anywhere.trace}")
        self._sec_pressed = pressed
        self.wait = 1500

    def d_section_check(self):
        if Gui.Control.activeDialog():   # MB2 on the sheet did not close it
            self.step("Section View: OK with MB2 on the sheet", "MB2 click", FAIL, "dialog still open")
            from .navigation import accept_task_dialog
            accept_task_dialog()
        App.ActiveDocument.recompute()
        self.wait = 3000   # TechDraw computes hidden lines in a worker thread

    def d_section_edges(self):
        secs = [v for v in self._page.Views if v.TypeId == "TechDraw::DrawViewSection"]
        if secs:    # TechDraw's worker thread can take longer than the fixed wait when the machine is busy
            self.wait_for("d_section_edges: hidden-line worker", lambda: len(secs[-1].getVisibleEdges()) > 0, 15000)
        edges = len(secs[-1].getVisibleEdges()) if secs else 0
        if secs:
            s = secs[-1]
            self.progress(f"d_section_edges: {s.Name} normal {s.SectionNormal} origin {s.SectionOrigin} "
                          f"direction {s.Direction} base {s.BaseView.Name if s.BaseView else None} "
                          f"valid {s.isValid()}; at ({s.X}, {s.Y}), base at ({self._base.X}, {self._base.Y})")
        self.step("Section View through the centre of the base view",
                  f"base view selected + ribbon '{self._sec_where} > Section View', direction "
                  f"'{self._sec_pressed}', MB2 = OK", SAME if secs and edges > 0 else FAIL,
                  f"{len(secs)} section view(s), {edges} visible edges")
        if secs:
            # NX: drag the section off the base view and MB1 to place it. FreeCAD puts it
            # on top of the base view; a FreeCAD user drags it aside afterwards.
            s, base = secs[-1], self._base
            scale = float(base.getScale()) if hasattr(base, "getScale") else float(base.Scale)
            s.X = float(base.X) + 3.0 * IN * scale
            s.Y = float(base.Y)
            App.ActiveDocument.recompute()
            QtWidgets.QApplication.processEvents()
            self.step("Drag the section to the right of the base view, MB1 to place", "X/Y of the section set",
                      DIFFERS, "FreeCAD places the section on top of the base view; it is moved afterwards "
                      f"(placed at x = {float(s.X):.1f} mm, base at {float(base.X):.1f} mm)")
        self.shot("D_drawing.png")
        App.ActiveDocument.save()
        self.wait = 400

    def d_back(self):
        self.key("Ctrl+M")
        self.wait = 1500

    # ---------------------------------------------------------- tutorial E
    # Saddle Bracket (Shih ch. 4): BORN technique, renaming, design changes,
    # material and physical properties. The book's text gives 2.5 (Symmetric
    # Value), 0.5, 2.0, Ø0.75, R0.25 and the operations; the profile and cut
    # sizes are figure-only, so the L-profile below is this replay's own:
    # 3.00 long, 0.50 base, 0.75 x 2.00 upright, a 1.00 x 0.75 notch.
    E_PROFILE = [(0, 0), (3.0, 0), (3.0, 0.5), (0.75, 0.5), (0.75, 2.0), (0, 2.0)]   # (X, Z) on the XZ plane
    E_AREA = 3.0 * 0.5 + 0.75 * 1.5

    def g2s(self, sk, x, y, z):
        """Global inches -> sketch coordinates (mm)."""
        p = sk.getGlobalPlacement().inverse().multVec(App.Vector(x * IN, y * IN, z * IN))
        return p.x, p.y

    def checkbox(self, name_part, state=True):
        for b in self.tasks_dock().findChildren(QtWidgets.QCheckBox):
            if name_part.lower() in b.objectName().lower():
                if b.isChecked() != state:
                    b.click()
                QtWidgets.QApplication.processEvents()
                return b.objectName()
        return None

    def tree_item(self, label):
        """The Part Navigator row for label, inside the active document only (other parts have a 'Pad' too)."""
        # Model indexes, not QTreeWidgetItem wrappers: items are not QObjects, so PySide is not told when
        # FreeCAD deletes rows, and a reused address can hand back a dead wrapper ("already deleted").
        doc_label = App.ActiveDocument.Label
        trees = Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget)
        trees.sort(key=lambda t: not t.isVisible())      # the Part Navigator the user sees first
        for tw in trees:
            m = tw.model()
            if m is None or m.rowCount() == 0:
                continue
            hits = m.match(m.index(0, 0), Qt.DisplayRole, label, -1, Qt.MatchExactly | Qt.MatchRecursive)
            for idx in hits:
                p = idx.parent()
                while p.isValid():
                    if p.data(Qt.DisplayRole) == doc_label:
                        return tw, QtCore.QPersistentModelIndex(idx)
                    p = p.parent()
        return None, None

    def select_row(self, label):
        """Make label's Part Navigator row current and focused; returns the tree or None."""
        tw, pidx = self.tree_item(label)
        if tw is None or not pidx.isValid():
            return None
        if not tw.isVisible():      # the Dialog tab is in front: click the Part Navigator tab first
            w = tw
            while w is not None and not isinstance(w, QtWidgets.QDockWidget):
                w = w.parentWidget()
            if w is not None:
                w.raise_()
            QtWidgets.QApplication.processEvents()
            self.progress(f"rename: Part Navigator brought to front ({tw.isVisible()})")
            tw, pidx = self.tree_item(label)
            if tw is None:
                return None
        m = tw.model()
        tw.setCurrentIndex(m.index(pidx.row(), pidx.column(), pidx.parent()))
        tw.setFocus()
        QtWidgets.QApplication.processEvents()
        return tw

    def rename(self, obj, new):
        """Part Navigator: select the feature, F2, type the name, Enter (as a user does)."""
        from .smoke import decode
        Gui.Selection.clearSelection()     # a selection change can rebuild the rows: settle first, then look up
        QtWidgets.QApplication.processEvents()
        editors, attempt = [], 0
        for attempt in range(3):
            tw = self.select_row(obj.Label)
            if tw is None:
                return f"'{obj.Label}' not in the Part Navigator"
            qtest().keyClick(tw, *decode("F2"))
            for _ in range(10):
                QtWidgets.QApplication.processEvents()
                editors = [e for e in tw.findChildren(QtWidgets.QLineEdit) if e.isVisible()]
                if editors:
                    break
                qtest().qWait(100)
            if editors:
                break
            self.progress(f"rename '{obj.Label}': no name editor after F2 (try {attempt + 1}); focus "
                          f"{type(QtWidgets.QApplication.focusWidget()).__name__}")
        if not editors:
            return "F2 opened no name editor"
        if attempt:
            self.retries.append(f"rename '{obj.Label}': F2 pressed {attempt + 1} times")
        ed = editors[0]
        ed.selectAll()
        qtest().keyClicks(ed, new)
        qtest().keyClick(ed, *decode("Return"))
        QtWidgets.QApplication.processEvents()
        return None if obj.Label == new else f"label is '{obj.Label}'"


    def fillet_corner(self, sk, corner, radius):
        """Sketch fillet at the corner where two lines meet (what the F tool does after two picks)."""
        lines = [i for i, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomLineSegment"
                 and min((g.StartPoint - corner).Length, (g.EndPoint - corner).Length) < 1e-6]
        if len(lines) != 2:
            self.info.setdefault("fillet errors", []).append(f"{len(lines)} lines meet at {corner}")
            return None
        a, b = (sk.Geometry[i] for i in lines)
        # a point 2 mm along each line from the corner (the far end minus the corner)
        pa = corner + (a.StartPoint + a.EndPoint - corner * 2).normalize() * 2.0
        pb = corner + (b.StartPoint + b.EndPoint - corner * 2).normalize() * 2.0
        for args in ((lines[0], lines[1], pa, pb, radius, True, False), (lines[0], 2, radius)):
            try:
                sk.fillet(*args)
                return args
            except Exception as e:
                self.info.setdefault("fillet errors", []).append(str(e))
        return None

    def wait_dialog(self, what, timeout_ms=4000):
        """Wait for FreeCAD's task dialog the way a user waits for it to appear; log if it never does."""
        t0 = time.monotonic()
        while not Gui.Control.activeDialog() and (time.monotonic() - t0) * 1000 < timeout_ms:
            qtest().qWait(100)
        waited = int((time.monotonic() - t0) * 1000)
        if not Gui.Control.activeDialog():
            doc = App.ActiveDocument
            self.progress(f"{what}: no task dialog after {waited} ms; sketch in edit "
                          f"{getattr(self.edited_sketch(), 'Name', None)}; objects "
                          f"{[o.Name for o in doc.Objects][-6:] if doc else None}")
            return False
        # ...and until its OK button is shown: a user cannot click before the panel is drawn,
        # and NXStyle's MB2 = OK rightly ignores an OK that is not visible yet
        def ok_visible():
            for box in self.tasks_dock().findChildren(QtWidgets.QDialogButtonBox):
                b = box.button(QtWidgets.QDialogButtonBox.Ok)
                if b is not None and b.isVisible():
                    return True
            return False
        t1 = time.monotonic()
        while not ok_visible() and (time.monotonic() - t1) < 2.0:
            qtest().qWait(50)
        waited = int((time.monotonic() - t0) * 1000)
        if waited > 300:
            self.progress(f"{what}: task dialog ready after {waited} ms (OK shown {ok_visible()})")
        return True

    def e_volume(self, width, end=True, hole=False, notch=False, fillet=False):
        v = self.E_AREA * width
        if fillet:
            v += (0.25 ** 2 - math.pi * 0.25 ** 2 / 4) * width
        if end:
            v += math.pi * (width / 2) ** 2 / 2 * 0.5      # half of the end disc sticks out
        if hole:
            v -= math.pi * 0.375 ** 2 * 0.5
        if notch:
            v -= 1.0 * 0.75 * 0.75
        return v * IN ** 3

    def e_new(self):
        self.tutorial = "E: Saddle Bracket (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def e_csys(self):
        self.step("File > New", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        self._csys_where = self.click_dropdown("Datum", "Datum CSYS")
        self.wait = 1200

    def e_csys_ok(self):
        dialog = bool(Gui.Control.activeDialog())
        n_seen = len(self.modals.seen)
        self.modals.accept = True     # FreeCAD asks whether to keep a datum without references
        self.mb2_click()
        qtest().qWait(400)
        self.modals.accept = False
        asked = [s for s in self.modals.seen[n_seen:] if "Incompatible" in s]
        App.ActiveDocument.recompute()
        cs = self.newest("PartDesign::CoordinateSystem")
        self.step("BORN: Datum CSYS at the WCS, OK", f"ribbon '{self._csys_where} > Datum > Datum CSYS', MB2 = OK"
                  + (", Yes to FreeCAD's question" if asked else ""),
                  DIFFERS if cs is not None and dialog and not Gui.Control.activeDialog() else FAIL,
                  "a FreeCAD Body already starts with its own origin (the BORN idea built in). "
                  + ("With nothing selected FreeCAD asks 'no attachment mode fits the references, continue?'; "
                     "NX places the CSYS at the WCS without asking" if asked else ""))
        self.wait = 500

    def e_extrude(self):
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def e_plane(self):
        picked = self.pick_in_feature_list("XZ")
        self.mb2_click()
        self.step("Extrude (X), XZ plane, OK", "X key, plane row + MB2", SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def e_profile(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        pts = [self.g2s(sk, x, 0, z) for (x, z) in self.E_PROFILE]
        _, tool, n, ended = self.draw_clicks("Z", pts + [pts[0]])
        P = [App.Vector(u, v, 0) for (u, v) in pts]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % len(P)]) for i in range(len(P))])
        self.step("Profile (Z): the L-shaped outline, MB2", "Z key + 7 MB1 clicks + MB2; sizes applied",
                  SAME if tool and n >= 6 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self._e_sketch = sk
        self.wait = 300

    def e_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def e_extrude_dialog(self):
        self.wait_dialog("e_extrude_dialog")
        sym = self.choose("symmetric", "sidesmode") or self.checkbox("midplane")
        field = self.set_quantity("length", 2.5 * IN)
        self.info["E extrude dialog widgets"] = self.task_widgets()
        self.mb2_click()
        App.ActiveDocument.recompute()
        bb = self.body().Shape.BoundBox
        ok = self.check_volume("Start = Symmetric Value, distance 2.5, OK", f"'{sym}', '{field}' = 63.5 mm, MB2 = OK",
                               self.e_volume(2.5, end=False),
                               f"; width {bb.YMin:.2f} .. {bb.YMax:.2f} mm (NX 1926+ and FreeCAD both "
                               "treat the symmetric distance as the total)")
        self._e_base = self.body().Tip
        if ok and (abs(bb.YMin + 1.25 * IN) > 1e-6 or abs(bb.YMax - 1.25 * IN) > 1e-6):
            self.rows[-1]["outcome"] = FAIL   # right volume, but not symmetric about the sketch plane
        if not ok or self.rows[-1]["outcome"] == FAIL:
            raise RuntimeError("base feature wrong; the rest of the tutorial would measure the wrong part")
        self.wait = 600

    def e_end(self):
        base = self._e_base
        face = self.face_of(base, lambda f: abs(f.normalAt(0, 0).z + 1) < 1e-6 and abs(f.CenterOfMass.z) < 1e-6)
        self.select_sub(base, face)
        b, where = self.click_ribbon("Extrude")
        self.step("Extrude, bottom face as the sketch plane", f"select face + ribbon '{where} > Extrude'",
                  SAME if b is not None and self.edited_sketch() is not None else FAIL, f"{face}")
        self.wait = 1500

    def e_end_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on the bottom face")
        base = self._e_base
        edge = None
        for i, e in enumerate(base.Shape.Edges, start=1):
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if all(abs(p.x - 3.0 * IN) < 1e-6 and abs(p.z) < 1e-6 for p in (a, b)) and abs(a.y - b.y) > 1:
                edge = f"Edge{i}"
        # Project Curve: start the tool, MB1 on the edge, MB2
        b, _ = self.click_ribbon("Project Curve")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        before = len(sk.ExternalGeometry)
        self.mb1_click(self.screen_point(sk, *self.g2s(sk, 3.0, 0.6, 0)))
        self.mb2_click(self.screen_point(sk, *self.g2s(sk, 4.5, 2.0, 0)))
        new = [sub for (_, subs) in sk.ExternalGeometry[before:] for sub in subs]
        picked = new == [edge]
        if not picked:
            for i in reversed(range(before, len(sk.ExternalGeometry))):
                sk.delExternal(i)
            if edge:
                sk.addExternal(base.Name, edge)
        self.step("Project Curve: the bottom right edge, OK", "ribbon 'Project Curve' + MB1 on the edge + MB2",
                  SAME if tool and picked else (DIFFERS if edge else FAIL),
                  f"picked {edge} in the graphics window" if picked else
                  f"MB1 projected {new or 'nothing'} instead of {edge}; {edge} added through the API")
        c = self.g2s(sk, 3.0, 0, 0)
        r = self.g2s(sk, 3.0, 1.25, 0)
        _, tool, n, ended = self.draw_clicks("O", [c, r])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), 1.25 * IN)])
        ext = -3   # the first projected curve
        sk.addConstraint(Sketcher.Constraint("Symmetric", ext, 1, ext, 2, 0, 3))   # centre = edge midpoint
        sk.addConstraint(Sketcher.Constraint("PointOnObject", ext, 1, 0))          # through the corner
        App.ActiveDocument.recompute()
        # FreeCAD 1.1 projects picked edges as defining geometry: the line across the circle
        # then belongs to the profile and the Pad sees an open wire. NX makes regions from the
        # circle and its diameter. A FreeCAD user turns the projected line into construction.
        n_profile = len(sk.Shape.Edges)
        toggled = False
        if n_profile > 1:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, "ExternalEdge1")
            b, _ = self.click_ribbon("Convert To/From Reference")
            if b is None:
                Gui.runCommand("Sketcher_ToggleConstruction")
            App.ActiveDocument.recompute()
            Gui.Selection.clearSelection()
            toggled = len(sk.Shape.Edges) == 1
        self._e_projection = (n_profile, toggled)
        self.step("Circle: centre at the edge midpoint, through the top corner", "O key + 2 MB1 clicks + MB2; "
                  "midpoint and corner as constraints", SAME if tool and n >= 1 and ended else FAIL,
                  f"solver result {sk.solve()} (0 = solved); NX snaps to the midpoint and corner while "
                  "drawing, FreeCAD records them as constraints")
        n_profile, toggled = self._e_projection
        if n_profile > 1:
            self.step("Finish the section: circle and projected edge", "select the projected line + ribbon "
                      "'Convert To/From Reference'", DIFFERS if toggled else FAIL,
                      f"FreeCAD 1.1 projects a picked edge as defining geometry, so the profile had {n_profile} "
                      "curves and Extrude would report 'Wire is not closed'. NX builds regions from the circle and "
                      "its diameter; in FreeCAD the projected line has to become construction geometry first")
        self.wait = 300

    def e_end_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def e_end_dialog(self):
        self.wait_dialog("e_end_dialog")
        rev = self.checkbox("reverse")
        field = self.set_quantity("length", 0.5 * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        zmin = self.body().Shape.BoundBox.ZMin / IN
        ok = self.check_volume("Reverse Direction, distance 0.5, Boolean Unite, OK",
                               f"'{rev}' on, '{field}' = 12.7 mm, MB2 = OK", self.e_volume(2.5),
                               f"; lowest point z = {zmin * IN:.2f} mm")
        if not ok:
            tip = self.body().Tip
            sk = tip.Profile[0] if getattr(tip, "Profile", None) else None
            self.info["E circular end state"] = {
                "dialog open": bool(Gui.Control.activeDialog()), "tip": tip.Name, "tip valid": tip.isValid(),
                "sketch external": str(getattr(sk, "ExternalGeometry", None)),
                "sketch geometry": [str(g) for g in getattr(sk, "Geometry", [])]}
            raise RuntimeError("Circular_End wrong; later steps would measure the wrong part")
        self._e_end = self.body().Tip
        self.wait = 600

    def e_rename(self):
        e1 = self.rename(self._e_base, "Base")
        e2 = self.rename(self._e_end, "Circular_End")
        self.step("Rename in the Part Navigator: Base, Circular_End", "select + F2, type, Enter",
                  DIFFERS if not (e1 or e2) else FAIL,
                  "NX: click the name twice or MB3 > Rename; FreeCAD: F2 or MB3 > Rename" + (f"; {e1 or e2}" if
                                                                                          e1 or e2 else ""))

    def e_width(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{self._e_base.Name}.")
        b, where = self.click_ribbon("Edit Parameters")
        self._e_where = where
        self.wait = 1500

    def e_width_dialog(self):
        self.wait_dialog("e_width_dialog")
        open_ = bool(Gui.Control.activeDialog())
        field = self.set_quantity("length", 2.0 * IN)
        self.mb2_click()
        self.key("F5")
        self.check_volume("Design change: Base distance 2.5 -> 2.0, OK, F5",
                          f"Base selected + ribbon '{self._e_where} > Edit Parameters' (dialog {open_}), "
                          f"'{field}' = 50.8 mm, MB2 = OK, F5", self.e_volume(2.0),
                          "; NX edits the value from MB3 > Show Dimensions, FreeCAD reopens the Extrude dialog. "
                          "Circular_End follows the narrower base (its circle is tied to the projected edge)")

    def e_hole(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 0.5 * IN) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Hole")
        self.step("Hole: Simple, Normal to Face, on the top face", f"select face + ribbon '{where} > Hole'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  "FreeCAD's Hole drills at circle centres in a sketch on the face")
        self.wait = 1500

    def e_hole_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no hole sketch in edit")
        tip = self.body().Tip
        arc = next((f"Edge{i}" for i, e in enumerate(tip.Shape.Edges, start=1)     # the end's top arc
                    if hasattr(e.Curve, "Radius") and e.Curve.Radius > 0.5 * IN
                    and abs(e.Curve.Center.z - 0.5 * IN) < 1e-6 and abs(e.Curve.Center.x - 3.0 * IN) < 1e-6), None)
        c = self.g2s(sk, 3.0, 0, 0.5)
        e = self.g2s(sk, 3.375, 0, 0.5)
        _, tool, n, ended = self.draw_clicks("O", [c, e])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), 0.375 * IN)])
        if arc:
            sk.addExternal(tip.Name, arc)
            sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -3, 3))   # centre on the arc's centre
        App.ActiveDocument.recompute()
        self.step("Point: the centre of the top arc", "O key + MB1 clicks + MB2; centre tied to the arc",
                  DIFFERS if tool and n >= 1 and ended and arc else FAIL,
                  f"NX picks the arc centre directly; FreeCAD sketches a circle on it ({arc} projected)")
        self.wait = 300

    def e_hole_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def e_hole_dialog(self):
        self.wait_dialog("e_hole_dialog")
        dia = self.set_quantity("diameter", 0.75 * IN)
        depth = self.choose("through", "depthtype")
        self.mb2_click()
        self.check_volume("Diameter 0.75, Depth Limit = Through Body, OK", f"'{dia}' = 19.05 mm, '{depth}', MB2 = OK",
                          self.e_volume(2.0, hole=True))
        self.wait = 600

    def e_cut(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).x - 1) < 1e-6 and abs(f.CenterOfMass.x - 0.75 * IN) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude on the right vertical face of the upright", f"select face + ribbon '{where} > "
                  "Extrude (Subtract)'", DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  f"{face}; the button starts Extrude with Boolean Subtract chosen")
        self.wait = 1500

    def e_cut_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no cut sketch in edit")
        corners = [self.g2s(sk, 0.75, y, z) for (y, z) in ((-0.5, 1.25), (0.5, 1.25), (0.5, 2.0), (-0.5, 2.0))]
        _, tool, n, ended = self.draw_clicks("R", [corners[0], corners[2]])
        P = [App.Vector(u, v, 0) for (u, v) in corners]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.step("Rectangle at the upper edge, MB2; three dimensions", "R key + 2 MB1 clicks + MB2; sizes applied",
                  SAME if tool and n >= 4 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        self.wait = 300

    def e_cut_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def e_cut_dialog(self):
        self.wait_dialog("e_cut_dialog")
        mode = self.choose("to first", "mode")
        self.info["E cut dialog widgets"] = self.task_widgets()
        self.mb2_click()
        ok = self.check_volume("Boolean Subtract, End = Until Next, OK", f"'{mode}', MB2 = OK",
                               self.e_volume(2.0, hole=True, notch=True), "; FreeCAD calls Until Next 'To first'")
        self._e_cut = self.body().Tip
        err = self.rename(self._e_cut, "Rect_Cut") if ok else "skipped"
        self.step("Rename the cut Rect_Cut", "select + F2, type, Enter", DIFFERS if not err else FAIL, err or "")
        self.wait = 600

    def e_rollback(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{self._e_cut.Name}.")
        b, where = self.click_ribbon("Edit Parameters")
        self._e_where = where
        self.wait = 1500

    def e_rollback_dialog(self):
        self.wait_dialog("e_rollback_dialog")
        mode = self.choose("through all", "mode")
        self.mb2_click()
        self.check_volume("Edit with Rollback: End = Through All, OK",
                          f"Rect_Cut selected + ribbon '{self._e_where} > Edit Parameters', '{mode}', MB2 = OK",
                          self.e_volume(2.0, hole=True, notch=True),
                          "; FreeCAD's edit shows the model before the feature, like NX's rollback")
        self.wait = 600

    def e_fillet(self):
        sk = self._e_sketch
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{sk.Name}.")
        self.click_ribbon("Edit Parameters")
        QtWidgets.QApplication.processEvents()
        in_edit = self.edited_sketch() is sk
        self.key("F")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, *self.g2s(sk, 2.0, 0, 1.5)))
        done = self.fillet_corner(sk, App.Vector(*self.g2s(sk, 0.75, 0, 0.5), 0), 0.25 * IN)
        App.ActiveDocument.recompute()
        self.step("Edit the Base sketch: Fillet (F) R0.25 on the inside corner, MB2",
                  "sketch selected + ribbon 'Edit Parameters', F key; corner filleted at 0.25",
                  DIFFERS if in_edit and tool and done else FAIL,
                  "NX: Edit with Rollback > Sketch Section; FreeCAD opens the sketch directly. The radius is "
                  "typed after picking the corner")
        self.wait = 300

    def e_fillet_finish(self):
        self.key("Ctrl+Q")
        QtWidgets.QApplication.processEvents()
        self.check_volume("Finish Sketch, OK: the whole part updates", "Ctrl+Q",
                          self.e_volume(2.0, hole=True, notch=True, fillet=True),
                          "; later features (Circular_End, hole, Rect_Cut) follow the edited sketch")
        self.wait = 1200

    def material_dialog(self, w):
        """Pick Steel in FreeCAD's material dialog and press OK."""
        views = [v for v in w.findChildren(QtWidgets.QAbstractItemView) if not isinstance(v, QtWidgets.QHeaderView)]
        best, seen = None, []
        for v in views:
            m = v.model()
            if m is None:
                continue
            stack = [QtCore.QModelIndex()]
            while stack:
                parent = stack.pop()
                for r in range(m.rowCount(parent)):
                    idx = m.index(r, 0, parent)
                    t = str(m.data(idx) or "")
                    if m.hasChildren(idx):          # a library or folder, not a material
                        stack.append(idx)
                    elif "steel" in t.lower():
                        seen.append(t)
                        # a plain carbon steel first ("Steel-Generic"), not stainless or tool steel
                        rank = (0 if "generic" in t.lower() else 1, len(t))
                        if best is None or rank < best[3]:
                            best = (v, idx, t, rank)
        self.info["E material dialog"] = {"title": w.windowTitle(), "class": type(w).__name__,
                                          "views": [type(v).__name__ for v in views], "steels": seen[:20],
                                          "picked": best[2] if best else None}
        if best is None:
            return False
        v, idx = best[0], best[1]
        v.scrollTo(idx)
        v.setCurrentIndex(idx)
        for sig in ("clicked", "activated", "doubleClicked"):
            try:
                getattr(v, sig).emit(idx)
            except Exception:
                pass
        QtWidgets.QApplication.processEvents()
        # OK where there is one; FreeCAD 1.1's material panel applies at once and only has Close
        for role in (QtWidgets.QDialogButtonBox.Ok, QtWidgets.QDialogButtonBox.Close):
            for box in w.findChildren(QtWidgets.QDialogButtonBox):
                b = box.button(role)
                if b is not None and b.isEnabled():
                    self.info["E material dialog"]["closed with"] = b.text()
                    b.click()
                    self.modals.handler = None
                    QtWidgets.QApplication.processEvents()
                    return True
        return False

    def e_material(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name)
        self.modals.handler = self.material_dialog
        b, where = self.click_ribbon("Assign Material")
        self._e_where = where
        QtWidgets.QApplication.processEvents()
        if self.modals.handler is not None:     # not a modal dialog: a task panel or a plain window
            if Gui.Control.activeDialog():
                self.material_dialog(self.tasks_dock())
            else:
                for w in QtWidgets.QApplication.topLevelWidgets():
                    if isinstance(w, QtWidgets.QDialog) and w.isVisible() and w.objectName() != "NXInformation":
                        if self.material_dialog(w):
                            break
        self.wait = 1500

    def e_material_check(self):
        from .commands import density_of
        self.modals.handler = None
        name, rho = density_of(self.body())
        md = self.info.get("E material dialog") or {}
        still_open = bool(Gui.Control.activeDialog())
        self.step("Tools > Assign Materials: Steel, select the body, OK",
                  f"body selected + ribbon '{self._e_where} > Assign Material', '{md.get('picked')}', "
                  f"{md.get('closed with', 'not closed')}",
                  (SAME if md.get("closed with") == "OK" else DIFFERS)
                  if name and "steel" in name.lower() and rho and not still_open else FAIL,
                  f"material {name}, density {rho} kg/m^3" + ("; the panel applies the choice at once and has "
                                                               "Close instead of OK" if md.get("closed with") != "OK"
                                                               else "") + ("; panel still open" if still_open else ""))
        vo = self.body().ViewObject
        try:
            col = vo.ShapeAppearance[0].DiffuseColor[:3]
        except Exception:
            col = getattr(vo, "ShapeColor", (0, 0, 0))[:3]
        # an observation, not an NX comparison (the book's text does not say what NX shows)
        self.info["E colour after Assign Material"] = (
            f"diffuse colour {tuple(round(c, 2) for c in col)}" + (": FreeCAD 1.1 also applies the material's "
                                                                   "appearance, steel renders nearly black"
                                                                   if sum(col) <= 1.2 else ""))

    def e_measure(self):
        from . import commands
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name)
        b, where = self.click_ribbon("Measure Bodies")
        QtWidgets.QApplication.processEvents()
        rows = commands.last_measure
        dlg = Gui.getMainWindow().findChild(QtWidgets.QDialog, "NXInformation")
        name, rho = commands.density_of(self.body())
        want = self.body().Shape.Volume * 1e-9 * rho if rho else None
        got = rows[0]["mass_kg"] if rows else None
        ok = b is not None and dlg is not None and dlg.isVisible() and got and want and abs(got - want) < 1e-9
        text = dlg.findChild(QtWidgets.QPlainTextEdit).toPlainText() if dlg else ""
        self.info["E measure text"] = text
        ok = ok and "mm³" in text and " kg" in text      # metric part: NX-style mm³ and kg
        self.step("Analysis > Measure, Solid Body, physical properties in the Information window",
                  f"body selected + ribbon '{where} > Measure Bodies'", DIFFERS if ok else FAIL,
                  f"mass {got:.4f} kg from {rho:g} kg/m^3; FreeCAD's own Measure has no "
                  "mass, so NXStyle adds Measure Bodies" if ok else f"rows {rows}, dialog {dlg is not None}")
        self.wait = 600

    def e_fit(self):
        if self.modals.handler is None:
            dlg = Gui.getMainWindow().findChild(QtWidgets.QDialog, "NXInformation")
            if dlg is not None:
                dlg.close()
        self.fit()

    def e_show(self):
        self.show("E_saddle_bracket")
        self.check_drawn("The finished part is shown in the graphics window", "E_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Saddle-Bracket.FCStd"))

    # ---------------------------------------------------------- tutorial F
    # Dryer Housing (Shih ch. 12): revolve, extrudes, Edge Blend, Shell, a
    # pattern leader and a two-direction rectangular pattern. The text gives
    # R0.25, 0.5, 5.5, R0.15, 0.125, 0.15 and the pattern (5 x -0.58, 10 x
    # -0.25); every profile is figure-only, so the shapes are this replay's own
    # simplified housing (a R2.00 x 1.25 drum, a 0.75 wide handle, a R0.75 half
    # nozzle). Each feature is checked against the same operation done directly
    # with FreeCAD's Part API, so the check is independent of the UI path.
    def f_vec(self, x, y, z):
        return App.Vector(x * IN, y * IN, z * IN)

    def f_check(self, label, how, expected, extra=""):
        App.ActiveDocument.recompute()
        ok = self.check_volume(label, how, expected.Volume, extra)
        self._f_exp = expected
        return ok

    def faces_where(self, shape, test):
        out = []
        for i, f in enumerate(shape.Faces, start=1):
            try:
                if test(f):
                    out.append(f"Face{i}")
            except Exception:
                pass
        return out

    def select_subs(self, obj, subs):
        doc, body = App.ActiveDocument, self.body()
        Gui.Selection.clearSelection()
        for s in subs:
            Gui.Selection.addSelection(doc.Name, body.Name, f"{obj.Name}.{s}")

    @staticmethod
    def arc_through(c, p0, pm, p1):
        """Arc from p0 to p1 through pm around centre c (sketch coordinates)."""
        import Part
        a0, am, a1 = (math.atan2(p.y - c.y, p.x - c.x) for p in (p0, pm, p1))
        r = (p0 - c).Length
        circ = Part.Circle(c, App.Vector(0, 0, 1), r)

        def ccw(a, b):
            return (b - a) % (2 * math.pi)
        if ccw(a0, am) < ccw(a0, a1):
            return Part.ArcOfCircle(circ, a0, a0 + ccw(a0, a1))
        return Part.ArcOfCircle(circ, a1, a1 + ccw(a1, a0))

    def f_new(self):
        self.tutorial = "F: Dryer Housing (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def f_revolve(self):
        self.wait_for("f_revolve: new part's Body", lambda: self.body() is not None)
        self.step("File > New, Model template", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Revolve")
        self._f_where = where
        self.wait = 1500

    def f_plane(self):
        picked = self.pick_in_feature_list("YZ")
        self.mb2_click()
        self.step("Revolve, YZ plane of the datum CSYS", f"ribbon '{self._f_where} > Revolve', plane row + MB2",
                  SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def f_profile(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        pts = [self.g2s(sk, 0, y, z) for (y, z) in ((0, 0), (2.0, 0), (2.0, 1.25), (0, 1.25))]
        _, tool, n, ended = self.draw_clicks("Z", pts + [pts[0]])
        P = [App.Vector(u, v, 0) for (u, v) in pts]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.key("F")
        QtWidgets.QApplication.processEvents()
        ftool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, *self.g2s(sk, 0, 3.0, 2.0)))
        done = self.fillet_corner(sk, P[2], 0.25 * IN)
        App.ActiveDocument.recompute()
        self.step("Profile, then Fillet R0.25 between the top line and the side", "Z key + MB1 clicks + MB2, F key; "
                  "sizes applied", DIFFERS if tool and n >= 4 and ended and ftool and done else FAIL,
                  "the book's profile (an arc and stepped lines) is figure-only; a filleted rectangle stands in. "
                  "The fillet radius is typed after picking in FreeCAD")
        self.wait = 300

    def f_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def f_revolve_dialog(self):
        import Part
        self.wait_dialog("f_revolve_dialog")
        axis = self.choose("z axis", "axis")
        self.mb2_click()
        cyl = Part.makeCylinder(2.0 * IN, 1.25 * IN)
        top = [e for e in cyl.Edges if hasattr(e.Curve, "Radius") and abs(e.Curve.Center.z - 1.25 * IN) < 1e-6]
        ok = self.f_check("Specify Vector = Z axis, 0..360°, OK", f"axis '{axis}', MB2 = OK",
                          cyl.makeFillet(0.25 * IN, top))
        if not ok:
            raise RuntimeError("base revolve wrong")
        self.wait = 600

    def f_handle(self):
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def f_handle_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Dryer handle: Extrude (X), XY plane", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def f_handle_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no handle sketch in edit")
        corners = [self.g2s(sk, x, y, 0) for (x, y) in ((-0.375, 1.5), (0.375, 1.5), (0.375, 5.0), (-0.375, 5.0))]
        _, tool, n, ended = self.draw_clicks("R", [corners[0], corners[2]])
        P = [App.Vector(u, v, 0) for (u, v) in corners]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.step("Handle outline, seven dimensions", "R key + 2 MB1 clicks + MB2; sizes applied",
                  DIFFERS if tool and n >= 4 and ended else FAIL,
                  "the book's handle (three inclined lines, seven dimensions) is figure-only; a 0.75 x 3.5 bar "
                  "stands in")
        self.wait = 300

    def f_handle_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def f_handle_dialog(self):
        import Part
        self.wait_dialog("f_handle_dialog")
        field = self.set_quantity("length", 0.5 * IN)
        self.mb2_click()
        box = Part.makeBox(0.75 * IN, 3.5 * IN, 0.5 * IN, self.f_vec(-0.375, 1.5, 0))
        self.f_check("Boolean Unite, End = 0.5, OK", f"'{field}' = 12.7 mm, MB2 = OK",
                     self._f_exp.fuse(box).removeSplitter())
        self.wait = 600

    def f_nozzle(self):
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Sketch")
        self._f_where = where
        self.wait = 1500

    def f_nozzle_plane(self):
        picked = self.pick_in_feature_list("YZ")
        self.mb2_click()
        self.step("Sketch on the YZ plane", f"ribbon '{self._f_where} > Sketch', plane row + MB2",
                  SAME if picked and self.edited_sketch() is not None else FAIL, f"picked {picked}")
        self.wait = 1500

    def f_nozzle_sketch(self):
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no nozzle sketch in edit")
        c, p0, pm, p1 = (App.Vector(*self.g2s(sk, 0, y, z), 0) for (y, z) in ((0, 0), (0.75, 0), (0, 0.75), (-0.75, 0)))
        self.frame_sketch(sk, c.x, c.y + 0.4 * IN, 3 * IN)
        self.key("A")
        QtWidgets.QApplication.processEvents()
        atool = self.nav().sketch_tool_active()
        for p in (c, p0, p1):
            self.mb1_click(self.screen_point(sk, p.x, p.y))
        self.mb2_click(self.screen_point(sk, c.x + 1.5 * IN, c.y + 1.5 * IN))
        n_arc = len(sk.Geometry)
        self.key("L")
        QtWidgets.QApplication.processEvents()
        ltool = self.nav().sketch_tool_active()
        for p in (p1, p0):
            self.mb1_click(self.screen_point(sk, p.x, p.y))
        self.mb2_click(self.screen_point(sk, c.x + 1.5 * IN, c.y + 1.5 * IN))
        import Part
        self.add_geometry(sk, [self.arc_through(c, p0, pm, p1), Part.LineSegment(p1, p0)])
        self.step("Arc by centre and endpoints (180°), then a Line closing it", "A key + 3 MB1 clicks + MB2, "
                  "L key + 2 MB1 clicks + MB2; sizes applied", SAME if atool and ltool and n_arc >= 1 else FAIL,
                  f"arc tool {atool}, line tool {ltool}; the book projects the bottom edge first (shown in "
                  "tutorial E); here the arc sits on the bottom line by its coordinates")
        self._f_nozzle_sketch = sk
        self.wait = 300

    def f_nozzle_leave(self):
        self.key("Ctrl+Q")
        self.wait = 1500

    def f_nozzle_extrude(self):
        sk = self._f_nozzle_sketch
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{sk.Name}.")
        b, where = self.click_ribbon("Extrude")
        self._f_where = where
        self.wait = 1500

    def f_nozzle_dialog(self):
        import Part
        self.wait_dialog("f_nozzle_dialog")
        rev = self.checkbox("reverse")
        field = self.set_quantity("length", 5.5 * IN)
        self.mb2_click()
        cyl = Part.makeCylinder(0.75 * IN, 5.5 * IN, App.Vector(0, 0, 0), App.Vector(-1, 0, 0))
        half = cyl.common(Part.makeBox(6 * IN, 2 * IN, 1 * IN, self.f_vec(-6, -1, 0)))
        ok = self.f_check("Reverse Direction, End 5.5, Boolean Unite, OK",
                          f"sketch selected + ribbon '{self._f_where} > Extrude', '{rev}' on, '{field}' = 139.7 mm, "
                          "MB2 = OK", self._f_exp.fuse(half).removeSplitter())
        xmin = self.body().Shape.BoundBox.XMin / IN
        if ok and abs(xmin + 5.5) > 1e-6:
            self.rows[-1]["outcome"] = FAIL
            self.rows[-1]["detail"] += f"; nozzle went the wrong way (x min {xmin * IN:.2f} mm)"
        self.wait = 600

    @staticmethod
    def handle_end_edges(shape):
        """The handle's outer end edges (top and two sides of the y = 5 face; the bottom one is open)."""
        end = [f for f in shape.Faces if abs(f.normalAt(0, 0).y - 1) < 1e-6 and abs(f.CenterOfMass.y - 5 * IN) < 1e-6]
        if not end:
            return []
        out = []
        for e in end[0].Edges:     # after a shell the end face also has inner edges: keep the outer three
            bb = e.BoundBox
            side = abs(abs(bb.XMin) - 0.375 * IN) < 1e-6 and abs(abs(bb.XMax) - 0.375 * IN) < 1e-6
            top = abs(bb.ZMin - 0.5 * IN) < 1e-6 and abs(bb.ZMax - 0.5 * IN) < 1e-6
            if side or top:
                out.append(e)
        return out

    def blend_handle(self, label):
        tip = self.body().Tip
        want = self.handle_end_edges(tip.Shape)
        subs = [f"Edge{i}" for i, e in enumerate(tip.Shape.Edges, start=1) if any(e.isSame(x) for x in want)]
        self.select_subs(tip, subs)
        b, where = self.click_ribbon("Edge Blend")
        self.step(label, f"{len(subs)} edges selected + ribbon '{where} > Edge Blend'",
                  DIFFERS if b is not None and len(subs) >= 3 else FAIL,
                  "the book's 13 edges are picked from a figure; the outer edges of the handle's end stand in "
                  "(FreeCAD's unrefined shape may split one). FreeCAD takes the edges selected before the command")
        self.wait = 1500

    def blend_dialog(self, what, label, radius=0.15):
        self.wait_dialog(what)
        field = self.set_quantity("radius", radius * IN)
        self.mb2_click()
        exp = self._f_exp
        how = f"'{field}' = {radius * IN:g} mm, MB2 = OK"
        try:
            reference = exp.makeFillet(radius * IN, self.handle_end_edges(exp))
        except Exception as e:
            reference, err = None, str(e)
        if reference is not None:
            self.f_check(label, how, reference)
        else:      # measure instead: a valid round that removes a little material and stays inside the old box
            App.ActiveDocument.recompute()
            tip, shape = self.body().Tip, self.body().Shape
            v0, v1 = exp.Volume, shape.Volume if not shape.isNull() else 0
            inside = all((a >= b - 0.005 * IN) if k % 2 == 0 else (a <= b + 0.005 * IN)
                         for k, (a, b) in enumerate(zip(self.tight_box(shape), self.tight_box(exp))))
            ok = (tip.TypeId == "PartDesign::Fillet" and tip.isValid() and not Gui.Control.activeDialog()
                  and 0 < v0 - v1 < 0.01 * v0 and inside)
            self.step(label, how, SAME if ok else FAIL,
                      f"volume {v1:.1f} mm^3, {v0 - v1:.2f} mm^3 rounded off; inside the "
                      f"previous box {inside}; feature valid {tip.isValid()}; no Part API reference (it failed: {err})")
            if not ok:
                self.cancel_failed("PartDesign::Fillet")
            self._f_exp = self.body().Shape.copy()
        self.wait = 600

    def cancel_failed(self, type_id):
        """What a user does after a feature fails: Cancel its dialog; Ctrl+Z if the broken feature stays."""
        dock = self.tasks_dock()
        if Gui.Control.activeDialog():
            for box in dock.findChildren(QtWidgets.QDialogButtonBox):
                b = box.button(QtWidgets.QDialogButtonBox.Cancel)
                if b is not None and b.isVisible():
                    b.click()
                    break
            QtWidgets.QApplication.processEvents()
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        presses = 0
        while presses < 3:
            tip = self.body().Tip
            if tip.TypeId != type_id or tip.isValid():
                break
            self.key("Ctrl+Z")
            QtWidgets.QApplication.processEvents()
            presses += 1
        self.progress(f"cancel_failed {type_id}: Ctrl+Z x{presses}; tip now {self.body().Tip.Name}")

    def f_blend(self):
        self._f_pre_blend = self._f_exp
        self.blend_handle("Edge Blend, Circular, select the handle's edges")

    def f_blend_dialog(self):
        self.blend_dialog("f_blend_dialog", "Radius 1 = 0.15, OK")

    @staticmethod
    def open_faces(shape):
        """The housing's open faces: the bottom (z = 0) and the nozzle's end (x = -5.5)."""
        return [f for f in shape.Faces if (abs(f.normalAt(0, 0).z + 1) < 1e-6 and abs(f.CenterOfMass.z) < 1e-6)
                or (abs(f.normalAt(0, 0).x + 1) < 1e-6 and abs(f.CenterOfMass.x + 5.5 * IN) < 1e-6)]

    def shell_select(self, label):
        tip = self.body().Tip
        bottom = self.faces_where(tip.Shape, lambda f: abs(f.normalAt(0, 0).z + 1) < 1e-6 and abs(f.CenterOfMass.z) < 1e-6)
        nozzle = self.faces_where(tip.Shape, lambda f: abs(f.normalAt(0, 0).x + 1) < 1e-6
                                  and abs(f.CenterOfMass.x + 5.5 * IN) < 1e-6)
        self.select_subs(tip, bottom + nozzle)
        b, where = self.click_ribbon("Shell")
        self.step(label, f"bottom {bottom} + nozzle end {nozzle} selected + ribbon '{where} > Shell'",
                  SAME if b is not None and bottom and len(nozzle) == 1 else FAIL,
                  "FreeCAD calls Shell 'Thickness'" + (f"; the unrefined bottom is {len(bottom)} faces, all picked"
                                                       if len(bottom) > 1 else ""))
        self.wait = 2000

    # (x, y, z) in inches: points 1/16 in inside each wall must be material, points deeper in must be hollow.
    # Walls: drum side (y = -2), drum top (z = 1.25), nozzle top (z = 0.75), handle top (z = 0.5); the bottom is open.
    SHELL_SOLID = [(0, -1.9375, 0.6), (0.5, -0.5, 1.1875), (-4.0, 0, 0.6875), (0, 4.0, 0.4375)]
    SHELL_HOLLOW = [(0, -1.75, 0.6), (0.5, -0.5, 1.0), (-4.0, 0, 0.5), (0, 4.0, 0.3), (0.5, -0.5, 0.0625)]

    @staticmethod
    def tight_box(shape):
        try:
            b = shape.optimalBoundingBox(False, False)   # exact; True measures the mesh and undershoots curves
        except Exception:
            b = shape.BoundBox
        return (b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax)

    def shell_probe(self, shape):
        solid = [shape.isInside(self.f_vec(*p), 1e-6, True) for p in self.SHELL_SOLID]
        hollow = [not shape.isInside(self.f_vec(*p), 1e-6, True) for p in self.SHELL_HOLLOW]
        return all(solid) and all(hollow), solid, hollow

    def shell_dialog(self, what, label):
        """Type 0.125, OK. Returns 'ok', 'limit' (FreeCAD refuses) or 'fail'.

        No Part API reference here: Part.makeThickness on this housing returned shapes reaching
        outside the original part, so the result is measured directly (outer box, probe points)."""
        self.wait_dialog(what)
        self.info["F shell dialog widgets"] = self.task_widgets()
        field = self.set_quantity("value", 0.125 * IN) or self.set_quantity("thickness", 0.125 * IN)
        box = next((b for b in self.tasks_dock().findChildren(QtWidgets.QCheckBox)
                    if b.objectName() == "checkReverse"), None)
        # read the box now: OK closes the dialog and deletes its widgets
        how = f"'{field}' = 3.175 mm" + (f", '{box.text()}' {'on' if box.isChecked() else 'off'} (default)"
                                        if box is not None else "") + ", MB2 = OK"
        self.mb2_click()
        qtest().qWait(500)
        App.ActiveDocument.recompute()
        tip, shape = self.body().Tip, self.body().Shape
        solid0 = self._f_exp
        ui_ok = (tip.TypeId == "PartDesign::Thickness" and tip.isValid() and not Gui.Control.activeDialog()
                 and not shape.isNull() and 0 < shape.Volume < 0.5 * solid0.Volume)
        if not ui_ok:
            said = [s for s in self.modals.seen if "thick" in s.lower() or "brep" in s.lower()]
            err = said[-1] if said else (tip.getStatusString() if hasattr(tip, "getStatusString") else "")
            self.step(label, how, LIMIT, f"FreeCAD 1.1.4 does not shell the part after the edge blend "
                      f"(FreeCAD: '{err or 'feature failed'}'); the same faces and thickness work before the blend "
                      "(next steps). NX shells it in the book's order")
            self._f_limit_row = len(self.rows) - 1
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            return "limit"
        b0, b1 = self.tight_box(solid0), self.tight_box(shape)
        same_box = all(abs(a - b) < 0.005 * IN for a, b in zip(b0, b1))   # BoundBox of curved faces is not tight
        probes_ok, solid, hollow = self.shell_probe(shape)
        ok = same_box and probes_ok and len(shape.Solids) == 1
        if not same_box:
            self.progress(f"{what}: boxes in inches, before {[round(v / IN, 4) for v in b0]}, after "
                          f"{[round(v / IN, 4) for v in b1]}")
        self.step(label, how, SAME if ok else FAIL,
                  f"volume {shape.Volume:.1f} mm^3 (solid {solid0.Volume:.1f}); outer box kept "
                  f"{same_box}; 1.6 mm inside each wall is material {solid}, deeper in is hollow {hollow}")
        self._f_exp = shape.copy()      # later references build on the measured shell
        return "ok" if ok else "fail"

    def f_shell(self):
        self.shell_select("Shell: pick the two flat open faces")

    def f_shell_dialog(self):
        if self.shell_dialog("f_shell_dialog", "Thickness 0.125, OK") == "limit":
            # what a FreeCAD user does: undo back to before the blend, shell first, blend afterwards
            self.insert_steps([self.f_undo, self.f_shell2, self.f_shell2_dialog, self.f_blend2, self.f_blend2_dialog])
        self.wait = 800

    def f_undo(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            QtWidgets.QApplication.processEvents()
        presses = 0
        doc = App.ActiveDocument
        while presses < 4 and any(o.TypeId in ("PartDesign::Thickness", "PartDesign::Fillet") for o in doc.Objects):
            self.key("Ctrl+Z")
            QtWidgets.QApplication.processEvents()
            presses += 1
        left = [o.Name for o in doc.Objects if o.TypeId in ("PartDesign::Thickness", "PartDesign::Fillet")]
        self._f_exp = self._f_pre_blend
        self.step("Workaround: undo the shell and the blend", f"Ctrl+Z x{presses}", DIFFERS if not left else FAIL,
                  f"left over: {left}" if left else "back to the part before the edge blend")
        self.wait = 800

    def f_shell2(self):
        self.shell_select("Workaround: Shell first, the same two faces")

    def f_shell2_dialog(self):
        result = self.shell_dialog("f_shell2_dialog", "Thickness 0.125, OK (before the blend)")
        row = getattr(self, "_f_limit_row", None)
        if result != "ok" and row is not None:
            # the same faces and value fail without the blend too: not a FreeCAD limit of the order
            self.rows[row]["outcome"] = FAIL
            self.rows[row]["detail"] += "; but the shell also failed without the blend"
        self.wait = 800

    def f_blend2(self):
        self.blend_handle("Workaround: Edge Blend after the shell, the handle's outer end edges")

    def f_blend2_dialog(self):
        self.blend_dialog("f_blend2_dialog", "Radius 1 = 0.15, OK (after the shell)")
        if self.rows[-1]["outcome"] == FAIL:
            # observed: FreeCAD 1.1.4 cannot round these edges of the 0.125 walls at 0.15 either; try smaller
            self.rows[-1]["outcome"] = LIMIT
            self.rows[-1]["detail"] += "; FreeCAD 1.1.4 refuses this round on the shelled walls"
            self.insert_steps([self.f_blend3, self.f_blend3_dialog])

    def f_blend3(self):
        self.blend_handle("Workaround: Edge Blend again with a smaller radius")

    def f_blend3_dialog(self):
        self.blend_dialog("f_blend3_dialog", "Radius 1 = 0.10, OK (after the shell)", 0.10)
        if self.rows[-1]["outcome"] == SAME:
            self.rows[-1]["outcome"] = DIFFERS
            self.rows[-1]["detail"] += "; the workaround changes the design: R0.10 instead of the book's R0.15"

    def f_vent(self):
        tip = self.body().Tip
        top = self.faces_where(tip.Shape, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6
                               and abs(f.CenterOfMass.z - 1.25 * IN) < 1e-6)
        self.select_subs(tip, top[:1])
        self.progress(f"f_vent: tip {tip.Name} valid {tip.isValid()}, top faces {top}, dialog open "
                      f"{bool(Gui.Control.activeDialog())}, selection {Gui.Selection.getSelectionEx()[0].SubElementNames if Gui.Selection.getSelectionEx() else None}")
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Pattern leader: Extrude on the top face, Subtract", f"select {top[:1]} + ribbon '{where} > "
                  "Extrude (Subtract)'", DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  "the book orients the view to Top first; FreeCAD's sketch opens looking at the face")
        self.wait = 1500

    VENT = (1.16, 1.125, 0.20, 0.08)        # leader centre x, y and size (x, y), inches

    def f_vent_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no leader sketch in edit")
        x, y, w, h = self.VENT
        corners = [self.g2s(sk, x + dx * w / 2, y + dy * h / 2, 1.25) for (dx, dy) in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        _, tool, n, ended = self.draw_clicks("R", [corners[0], corners[2]])
        P = [App.Vector(u, v, 0) for (u, v) in corners]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.step("Rectangle to the right of the CSYS: the small vent", "R key + 2 MB1 clicks + MB2; sizes applied",
                  SAME if tool and n >= 4 and ended else FAIL, "the slot size is figure-only: 0.20 x 0.08 here")
        self.wait = 300

    def f_vent_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def vent_box(self, i=0, j=0):
        import Part
        x, y, w, h = self.VENT
        return Part.makeBox(w * IN, h * IN, 0.15 * IN, self.f_vec(x - 0.58 * i - w / 2, y - 0.25 * j - h / 2, 1.10))

    def f_vent_dialog(self):
        self.wait_dialog("f_vent_dialog")
        field = self.set_quantity("length", 0.15 * IN)
        self.mb2_click()
        self._f_before_vents = self._f_exp
        self.f_check("Reverse Direction into the solid, End 0.15, OK", f"'{field}' = 3.81 mm, MB2 = OK",
                     self._f_exp.cut(self.vent_box()), "; no Reverse needed: the subtracting extrude cuts inwards")
        self._f_leader = self.body().Tip
        self.wait = 600

    def f_pattern(self):
        self.select_sub(self._f_leader, "")
        b, where = self.click_ribbon("Pattern Feature")
        self.step("Pattern Feature, Layout = Linear, select the cut, MB2", f"leader selected + ribbon '{where} > "
                  "Pattern Feature'", DIFFERS if b is not None and Gui.Control.activeDialog() else FAIL,
                  "FreeCAD's Linear Pattern is the Linear layout of NX's Pattern Feature")
        self.wait = 1500

    def pattern_dirs(self):
        """The direction panels of FreeCAD 1.1's pattern dialog, Direction 1 first."""
        return [w for w in self.tasks_dock().findChildren(QtWidgets.QWidget)
                if w.objectName() == "PartGui__PatternParametersWidget"]

    def in_panel(self, panel, cls, name_part):
        ws = [w for w in panel.findChildren(cls) if name_part.lower() in w.objectName().lower()]
        return ws[0] if ws else None

    def set_direction(self, panel, axis, count, pitch):
        """Direction n of a rectangular pattern: axis, count and a (signed) NX pitch distance."""
        got = {}
        c = self.in_panel(panel, QtWidgets.QComboBox, "direction")
        if c is not None:      # this panel's own list (both directions use the same widget names)
            for i in range(c.count()):
                if self._matches(axis, c.itemText(i)):
                    c.setCurrentIndex(i)
                    c.activated.emit(i)
                    got["axis"] = c.itemText(i)
                    break
        m = self.in_panel(panel, QtWidgets.QComboBox, "mode")
        if m is not None:
            for i in range(m.count()):
                if "spacing" in m.itemText(i).lower():
                    m.setCurrentIndex(i)
                    m.activated.emit(i)
                    got["mode"] = m.itemText(i)
        QtWidgets.QApplication.processEvents()
        occ = self.in_panel(panel, QtWidgets.QSpinBox, "occurrences")
        if occ is not None:
            occ.lineEdit().setText(str(int(count)))
            occ.interpretText()
            got["count typed"] = int(count)   # occ.value() is the UIntSpinBox's offset storage, not the count
        sp = self.in_panel(panel, QtWidgets.QAbstractSpinBox, "spacing")
        if sp is not None:
            self.type_into(sp, abs(pitch) * IN)
            got["spacing"] = abs(pitch)
        if pitch < 0:
            rev = self.in_panel(panel, QtWidgets.QToolButton, "reverse") or self.in_panel(
                panel, QtWidgets.QAbstractButton, "reverse")
            if rev is not None:
                rev.click()
                got["reversed"] = True
        return got

    def f_pattern_dialog(self):
        self.wait_dialog("f_pattern_dialog")
        # in a long session FreeCAD can take a few seconds to build the pattern and its direction panels
        self.wait_for("f_pattern_dialog: direction panels", lambda: bool(self.pattern_dirs())
                      and self.newest("PartDesign::LinearPattern") is not None, 10000)
        self.info["F pattern dialog widgets"] = self.task_widgets()
        panels = self.pattern_dirs()
        d1 = self.set_direction(panels[0], "x axis", 5, -0.58) if panels else {}
        enable = None
        if len(panels) > 1:
            for b in self.tasks_dock().findChildren(QtWidgets.QCheckBox):
                if "enable" in b.objectName().lower() or "direction 2" in b.text().lower():
                    if not b.isChecked():
                        b.click()
                    enable = b.objectName() or b.text()
            QtWidgets.QApplication.processEvents()
        d2 = self.set_direction(panels[1], "y axis", 10, -0.25) if len(panels) > 1 else {}
        pat = self.newest("PartDesign::LinearPattern")
        counts = {p: getattr(pat, p) for p in pat.PropertiesList if p.startswith("Occurrences")} if pat else {}
        self.progress(f"f_pattern_dialog: {len(panels)} direction panels; d1 {d1}; enable {enable}; d2 {d2}; "
                      f"counts {counts}")
        if not pat or any(v > 100 for v in counts.values()):
            for p in counts:                  # never let a runaway count recompute
                setattr(pat, p, 2)
            Gui.Control.closeDialog()
            raise RuntimeError(f"pattern counts not as typed: {counts}")
        spacing = {}
        for p in pat.PropertiesList:
            if p.startswith("Offset") or "Spacing" in p:
                v = getattr(pat, p)
                try:
                    spacing[p] = round(float(getattr(v, "Value", v)), 4)
                except (TypeError, ValueError):
                    spacing[p] = str(v)
        self.mb2_click()
        counts = dict(counts, **spacing)
        boxes = [self.vent_box(i, j) for i in range(5) for j in range(10)]
        cutter = boxes[0].fuse(boxes[1:])
        self.f_check("Direction 1: X, Count 5, Pitch -0.58; Use Direction 2: Y, Count 10, Pitch -0.25; OK",
                     f"X axis {d1}; '{enable}'; Y axis {d2}; MB2 = OK", self._f_before_vents.cut(cutter),
                     f"; feature counts {counts}; NX's negative pitch is FreeCAD's spacing with Reverse")
        self.wait = 800

    def f_swept(self):
        self.step("Swept cut along the rim (section rectangle, Line-Arc guide), Subtract", "-", "skipped",
                  "the guide curves and section sizes are figure-only")

    def f_fit(self):
        self.fit()

    def f_show(self):
        self.show("F_dryer_housing")
        self.check_drawn("The finished part is shown in the graphics window", "F_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "DryerHousing.FCStd"))

    # ---------------------------------------------------------- tutorial G
    # Shaft Support assembly (Shih ch. 14). The text gives the constraint sequence and its
    # results (still free to rotate after a face and one axis; fixed after the second axis;
    # Align/Lock leaves one DOF), the explosion distances and a part edit; every part size is
    # figure-only, so the four parts are this replay's own (metric).
    G_SCREW_HEAD = 5.0

    def g_new(self):
        self.tutorial = "G: Shaft Support assembly (metric parts of the replay's own)"
        self.g_parts()

    def g_parts(self):
        """Base-Plate, Bearing, Collar, Cap-Screw: parametric Part features in a Body each, saved."""
        import Part  # noqa: F401  (Part feature types)
        made = {}

        def new(name):
            doc = App.newDocument(name.replace("-", "_"))
            doc.Label = name
            return doc

        def finish(doc, name, solid):
            body = doc.addObject("PartDesign::Body", "Body")
            body.BaseFeature = solid
            body.Label = name
            doc.recompute()
            doc.saveAs(os.path.join(OUT, f"{name}.FCStd"))
            made[name] = (doc, body)

        def box(doc, n, x, y, z, at):
            b = doc.addObject("Part::Box", n)
            b.Length, b.Width, b.Height = x, y, z
            b.Placement.Base = App.Vector(*at)
            return b

        def cyl(doc, n, r, h, at, d=(0, 0, 1)):
            c = doc.addObject("Part::Cylinder", n)
            c.Radius, c.Height = r, h
            c.Placement = App.Placement(App.Vector(*at), App.Rotation(App.Vector(0, 0, 1), App.Vector(*d)))
            return c

        def cut(doc, n, base, tools):
            tool = tools[0]
            if len(tools) > 1:
                tool = doc.addObject("Part::MultiFuse", n + "Tools")
                tool.Shapes = tools
            c = doc.addObject("Part::Cut", n)
            c.Base, c.Tool = base, tool
            for o in [base] + list(tools):
                o.Visibility = False
            return c

        # Base-Plate: 100 x 60 x 10, top face at z = 0, two Ø8 holes at x = ±15; front face y = -30
        d = new("Base-Plate")
        finish(d, "Base-Plate", cut(d, "PlateSolid", box(d, "Block", 100, 60, 10, (-50, -30, -10)),
                                    [cyl(d, "HoleRight", 4, 10, (15, 0, -10)), cyl(d, "HoleLeft", 4, 10, (-15, 0, -10))]))
        # Bearing: origin at the bottom centre; 50 x 40 x 20 block, R12 boss to z = 35, Ø10 bore,
        # two Ø8 holes at x = ±15 with Ø13 x 5 counterbores from the top (z = 15 .. 20)
        d = new("Bearing")
        blk = box(d, "Block", 50, 40, 20, (-25, -20, 0))
        boss = d.addObject("Part::Fuse", "Body1")
        boss.Base, boss.Tool = blk, cyl(d, "Boss", 12, 15, (0, 0, 20))
        blk.Visibility = False
        finish(d, "Bearing", cut(d, "BearingSolid", boss, [cyl(d, "Bore", 5, 35, (0, 0, 0)),
                                                       cyl(d, "HoleRight", 4, 20, (15, 0, 0)),
                                                       cyl(d, "HoleLeft", 4, 20, (-15, 0, 0)),
                                                       cyl(d, "CounterboreRight", 6.5, 5, (15, 0, 15)),
                                                       cyl(d, "CounterboreLeft", 6.5, 5, (-15, 0, 15))]))
        # Collar: ring OD 24 / ID 10 x 8, a set-screw flat at x = 11
        d = new("Collar")
        finish(d, "Collar", cut(d, "CollarSolid", cyl(d, "Ring", 12, 8, (0, 0, 0)),
                                [cyl(d, "Hole", 5, 8, (0, 0, 0)), box(d, "Flat", 5, 30, 8, (11, -15, 0))]))
        # Cap-Screw: head Ø12 x 5 above z = 0, shank Ø7.8 x 30 below (origin at the head's underside)
        d = new("Cap-Screw")
        screw = d.addObject("Part::Fuse", "ScrewSolid")
        screw.Base = cyl(d, "Head", 6, self.G_SCREW_HEAD, (0, 0, 0))
        screw.Tool = cyl(d, "Shank", 3.9, 30, (0, 0, -30))
        screw.Base.Visibility = screw.Tool.Visibility = False
        finish(d, "Cap-Screw", screw)
        self._g_parts = made
        ok = all(b.Shape.isValid() and b.Shape.Volume > 0 for _, b in made.values())
        self.step("Create the parts Collar, Bearing, Base-Plate, Cap-Screw and save them", "modelled by script "
                  "(the book's sizes are figure-only; earlier tutorials cover modelling)", SAME if ok else FAIL,
                  ", ".join(f"{n} {b.Shape.Volume:.0f} mm^3" for n, (_, b) in made.items()))

    def g_app(self):
        b, where = self.click_ribbon("Assemblies")         # Application > Assemblies
        self._g_app_where = where
        self.wait = 1200

    def g_new_file(self):
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1500

    def g_template(self):
        ok = self.wait_for("g_template: new assembly", lambda: self.assembly() is not None)
        doc = App.ActiveDocument
        if not ok:
            sh = self.shell
            gdoc = Gui.getDocument(doc.Name) if doc else None
            self.progress(f"g_template: app {(sh.current_app or {}).get('id')}, ticks {sh._ticks}, timer active "
                          f"{sh.watch.isActive()}, known {sorted(sh._known_docs)}, docs {App.listDocuments().keys()}, "
                          f"active {doc.Name if doc else None} objects {len(doc.Objects) if doc else '-'} file "
                          f"{doc.FileName if doc else '-'}, 3D views "
                          f"{len(gdoc.mdiViewsOfType('Gui::View3DInventor')) if gdoc else '-'}, "
                          f"new_part_datum {sh.cfg.get('new_part_datum', True)}")
        doc.saveAs(os.path.join(OUT, "Shaft-Support.FCStd"))
        self.step("File > New, Assembly template, name Shaft-Support", f"ribbon '{self._g_app_where} > "
                  "Assemblies', Ctrl+N; saved as Shaft-Support", DIFFERS if ok else FAIL,
                  "NXStyle's Assembly template starts the document with an empty Assembly (like NX's); NX names the "
                  "file in the New dialog, FreeCAD on the first save")

    def assembly(self):
        doc = App.ActiveDocument
        return next((o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"), None) if doc else None

    def g_links(self):
        return [o for o in self.assembly().Group if o.TypeId == "App::Link"]

    def answer_ground(self, w):
        """FreeCAD's 'Ground Part?' question after the first insertion: Yes."""
        for b in w.findChildren(QtWidgets.QAbstractButton):
            if b.text().replace("&", "") == "Yes":
                self.info["G ground question"] = w.windowTitle()
                b.click()
                return True
        return False

    def insert(self, part_label):
        """Add Component: click the part in the dialog's list, MB2 = OK."""
        before = {o.Name for o in self.g_links()}
        self.modals.handler = self.answer_ground
        b, where = self.click_ribbon("Add Component")
        self.wait_dialog("insert")
        tree = self.tasks_dock().findChild(QtWidgets.QTreeWidget, "partList")
        item = None
        if tree is not None:
            hits = tree.findItems(part_label, Qt.MatchStartsWith | Qt.MatchRecursive, 0)
            item = next((h for h in hits if h.data(0, Qt.UserRole) is not None), None)
        if item is not None:
            tree.scrollToItem(item)
            r = tree.visualItemRect(item)
            qtest().mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, r.center())
            QtWidgets.QApplication.processEvents()
        qtest().qWait(300)
        self.modals.handler = None
        self.mb2_click()
        App.ActiveDocument.recompute()
        new = [o for o in self.g_links() if o.Name not in before]
        return (new[-1] if new else None), where

    @staticmethod
    def lshape(link):
        """A component's shape where it sits in the assembly."""
        import Part
        return Part.getShape(link)

    def element(self, link, kind, test):
        """('FaceN' or 'EdgeN', a point on it) of the link's shape, in assembly coordinates."""
        shape = self.lshape(link)
        items = shape.Faces if kind == "Face" else shape.Edges
        for i, x in enumerate(items, start=1):
            try:
                if test(x):
                    p = x.CenterOfMass if kind == "Face" and not hasattr(x.Surface, "Radius") else \
                        x.valueAt(x.ParameterRange[0], x.ParameterRange[2]) if kind == "Face" else \
                        x.valueAt(x.FirstParameter)
                    return f"{kind}{i}", p
            except Exception:
                continue
        return None, None

    def plane_face(self, link, nz, z):
        return self.element(link, "Face", lambda f: not hasattr(f.Surface, "Radius")
                            and abs(f.normalAt(0, 0).z - nz) < 1e-6 and abs(f.CenterOfMass.z - z) < 1e-6)

    def cyl_face(self, link, r, cx, cy):
        return self.element(link, "Face", lambda f: hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - r) < 1e-6
                            and abs(f.Surface.Center.x - cx) < 1e-6 and abs(f.Surface.Center.y - cy) < 1e-6)

    def joint(self, label, picks, distance=None):
        """Assembly Constraints: the NX-named button, two picks in the graphics window, MB2 = OK."""
        jg = next((o for o in self.assembly().Group if o.TypeId == "Assembly::JointGroup"), None)
        before = {o.Name for o in jg.Group} if jg else set()
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon(label)
        self.wait_dialog(f"joint {label}")
        asm = self.assembly()
        for link, sub, p in picks:
            Gui.Selection.addSelection(App.ActiveDocument.Name, asm.Name, f"{link.Name}.{sub}", p.x, p.y, p.z)
            QtWidgets.QApplication.processEvents()
        if distance is not None:
            self.set_quantity("distance", distance)
        self.mb2_click()
        App.ActiveDocument.recompute()
        jg = next((o for o in self.assembly().Group if o.TypeId == "Assembly::JointGroup"), None)
        new = [o for o in jg.Group if o.Name not in before] if jg else []
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        return (new[-1] if new else None), where

    def solve(self):
        asm = self.assembly()
        try:
            return asm.solve()
        except Exception as e:
            return f"error {e}"

    def free_to_move(self, link, how):
        """Constrained-move probe: displace the part, solve, and see whether it stays displaced."""
        p0 = App.Placement(link.Placement)
        link.Placement = how(App.Placement(p0))
        moved = App.Placement(link.Placement)
        self.solve()
        App.ActiveDocument.recompute()
        now = App.Placement(link.Placement)
        stayed = self.same_place(now, moved)
        back = self.same_place(now, p0)
        self.progress(f"move probe {link.Label}: before {self.angle_z(p0):.2f}° {p0.Base}, displaced "
                      f"{self.angle_z(moved):.2f}°, after solve {self.angle_z(now):.2f}° {now.Base}")
        if stayed:                          # put it back where it was
            link.Placement = p0
            self.solve()
        return stayed, back

    @staticmethod
    def same_place(a, b, tol=1e-4):
        """Same pose: compare where points land (a rotation's quaternion may come back negated)."""
        pts = (App.Vector(0, 0, 0), App.Vector(10, 0, 0), App.Vector(0, 10, 0), App.Vector(0, 0, 10))
        return all((a.multVec(p) - b.multVec(p)).Length < tol for p in pts)

    @staticmethod
    def angle_z(plc):
        v = plc.Rotation.multVec(App.Vector(1, 0, 0))
        return math.degrees(math.atan2(v.y, v.x))

    @staticmethod
    def rotate_about(axis_point, deg):
        def f(plc):
            r = App.Rotation(App.Vector(0, 0, 1), deg)
            return App.Placement(axis_point, r).multiply(App.Placement(-axis_point, App.Rotation())).multiply(plc)
        return f

    @staticmethod
    def shift(dz):
        def f(plc):
            plc.Base = plc.Base + App.Vector(0, 0, dz)
            return plc
        return f

    def g_plate(self):
        link, where = self.insert("Base-Plate")
        grounded = any(hasattr(o, "ObjectToGround") and o.ObjectToGround == link
                       for o in App.ActiveDocument.Objects) if link else False
        self._g = {"plate": link}
        self.step("Add Component: Base-Plate at the origin; Yes to the Fixed constraint", f"ribbon '{where} > Add "
                  "Component', click Base-Plate in the list, Yes, MB2 = OK",
                  SAME if link is not None and grounded else FAIL,
                  f"grounded {grounded}; FreeCAD asks 'Ground Part?' like NX's question about the Fixed constraint")

    def g_bearing(self):
        link, where = self.insert("Bearing")
        self._g["bearing"] = link
        self.step("Add Component: Bearing, placed with Move", f"ribbon '{where} > Add Component', click Bearing, MB2",
                  DIFFERS if link is not None else FAIL, "FreeCAD places it beside the last part; NX lets you drag it "
                  "to a spot first")

    def g_bearing_face(self):
        plate, bear = self._g["plate"], self._g["bearing"]
        z0 = self.lshape(bear).BoundBox.ZMin
        a = self.plane_face(bear, -1, z0)
        b = self.plane_face(plate, 1, 0.0)
        j, where = self.joint("Touch Align", [(bear,) + a, (plate,) + b], 0.0)
        App.ActiveDocument.recompute()
        zmin = self.lshape(bear).BoundBox.ZMin
        self.step("Touch Align: Bearing bottom face to the Base-Plate top face", f"ribbon '{where} > Touch Align', "
                  f"{a[0]} + {b[0]}, MB2 = OK", SAME if j is not None and abs(zmin) < 1e-4 else FAIL,
                  f"joint {getattr(j, 'JointType', None)}; Bearing now from z = {zmin:.3f} mm")

    def g_bearing_axis(self):
        plate, bear = self._g["plate"], self._g["bearing"]
        pl = bear.Placement
        a = self.cyl_face(bear, 4, *(pl.multVec(App.Vector(15, 0, 0)).x, pl.multVec(App.Vector(15, 0, 0)).y))
        b = self.cyl_face(plate, 4, 15, 0)
        j, where = self.joint("Align Axes", [(bear,) + a, (plate,) + b])
        c = bear.Placement.multVec(App.Vector(15, 0, 0))
        on_axis = abs(c.x - 15) < 1e-4 and abs(c.y) < 1e-4
        stayed, _ = self.free_to_move(bear, self.rotate_about(App.Vector(15, 0, 0), 25))
        self.step("Touch Align: the right hole axes (Bearing counterbore hole, Base-Plate hole)", f"ribbon '{where} > "
                  f"Align Axes', {a[0]} + {b[0]}, MB2 = OK", SAME if j is not None and on_axis and stayed else FAIL,
                  f"hole axes coincide {on_axis}; rotated 25° about that axis and solved: it stays "
                  f"{'(still free to rotate, as the book says)' if stayed else 'NOT free'}. NX's Show Degrees of "
                  "Freedom has no FreeCAD equivalent: the replay moves the part and solves")

    def g_bearing_axis2(self):
        plate, bear = self._g["plate"], self._g["bearing"]
        pl = bear.Placement
        q = pl.multVec(App.Vector(-15, 0, 0))
        a = self.cyl_face(bear, 4, q.x, q.y)
        b = self.cyl_face(plate, 4, -15, 0)
        j, where = self.joint("Align Axes", [(bear,) + a, (plate,) + b])
        stayed, back = self.free_to_move(bear, self.rotate_about(App.Vector(15, 0, 0), 25))
        self.step("Touch Align: the left hole axes; Move: it cannot move", f"ribbon '{where} > Align Axes', {a[0]} + "
                  f"{b[0]}, MB2 = OK", SAME if j is not None and back else FAIL,
                  f"rotated 25° and solved: back in place {back} (fully constrained, as in the book)")

    def g_collar(self):
        link, where = self.insert("Collar")
        self._g["collar"] = link
        bear, col = self._g["bearing"], link
        a = self.plane_face(col, -1, self.lshape(col).BoundBox.ZMin)
        b = self.plane_face(bear, 1, 35.0)
        j, w2 = self.joint("Touch Align", [(col,) + a, (bear,) + b], 0.0)
        zmin = self.lshape(col).BoundBox.ZMin
        self.step("Add Component: Collar, Constrain, Touch Align on the boss's top face", f"ribbon '{where} > Add "
                  f"Component' + '{w2} > Touch Align', {a[0]} + {b[0]}", SAME if j is not None and
                  abs(zmin - 35) < 1e-4 else FAIL, f"Collar from z = {zmin:.3f} mm")

    def g_collar_axis(self):
        bear, col = self._g["bearing"], self._g["collar"]
        c0 = col.Placement.Base
        a = self.cyl_face(col, 12, c0.x, c0.y)
        b = self.cyl_face(bear, 12, 0, 0)
        j, where = self.joint("Align Axes", [(col,) + a, (bear,) + b])
        c = col.Placement.Base
        stayed, _ = self.free_to_move(col, self.rotate_about(App.Vector(0, 0, 0), 30))
        self.step("Touch Align: the outer cylinders of Collar and Bearing", f"ribbon '{where} > Align Axes', {a[0]} + "
                  f"{b[0]}", SAME if j is not None and abs(c.x) < 1e-4 and abs(c.y) < 1e-4 and stayed else FAIL,
                  f"centred {abs(c.x) < 1e-4 and abs(c.y) < 1e-4}; still free to rotate {stayed}")

    def g_collar_parallel(self):
        plate, col = self._g["plate"], self._g["collar"]
        flat = self.element(col, "Face", lambda f: not hasattr(f.Surface, "Radius") and abs(f.normalAt(0, 0).z) < 1e-6
                            and f.Area < 300)
        front = self.element(plate, "Face", lambda f: abs(f.normalAt(0, 0).y + 1) < 1e-6
                             and abs(f.CenterOfMass.y + 30) < 1e-6)
        j, where = self.joint("Parallel", [(col,) + flat, (plate,) + front])
        res = self.solve()
        nflat = None
        sub = flat[0]
        if sub:
            f = self.lshape(col).Faces[int(sub[4:]) - 1]
            nflat = f.normalAt(0, 0)
        self.progress(f"g_collar_parallel: joint {getattr(j, 'Name', None)} {getattr(j, 'JointType', None)} refs "
                      f"{getattr(j, 'Reference1', None)} / {getattr(j, 'Reference2', None)}; solve {res}; collar "
                      f"angle {self.angle_z(col.Placement):.2f}°; flat normal now {nflat}; joint props "
                      f"{ {p: str(getattr(j, p))[:60] for p in getattr(j, 'PropertiesList', []) if p in ('Activated', 'Detach1', 'Detach2', 'Offset1', 'Offset2', 'Placement1', 'Placement2', 'Rotation', 'Distance', 'Angle', 'EnableAngleMin')} }")
        stayed, back = self.free_to_move(col, self.rotate_about(App.Vector(0, 0, 0), 30))
        parallel = nflat is not None and abs(abs(nflat.y) - 1) < 1e-6
        how = f"ribbon '{where} > Parallel', {flat[0]} (the collar's flat) + {front[0]}"
        note = ("The book uses the Collar's datum plane (Replace Reference Set > Entire Part); here the flat on the "
                "collar stands in")
        if j is not None and parallel and back:
            self.step("Parallel: Collar to the Base-Plate front face", how, DIFFERS, note)
            return
        self.step("Parallel: Collar to the Base-Plate front face", how, LIMIT,
                  f"joint made, solver 'converged', but the collar did not turn (flat normal {nflat}). FreeCAD 1.1.4's "
                  "solver drops a Parallel constraint whose faces start exactly perpendicular ('ParallelAxesJoint ... "
                  "constraint(s) removed: RedundantConstraintDirectionCosineConstraintIzJy'); reproduced without "
                  f"NXStyle; the same joint works when the faces start 20° apart. {note}")
        # the workaround a FreeCAD user finds: delete the joint, turn the collar a little, Parallel again
        jname = j.Name                         # read before the delete: a deleted object has no name
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, jname)
        self.modals.accept = True
        self.key("Delete")
        QtWidgets.QApplication.processEvents()
        self.modals.accept = False
        gone = App.ActiveDocument.getObject(jname) is None
        col.Placement = self.rotate_about(App.Vector(0, 0, 0), 20)(App.Placement(col.Placement))
        self.solve()
        j2, where = self.joint("Parallel", [(col,) + self.element(col, "Face", lambda f: not hasattr(f.Surface, "Radius")
                                                                 and abs(f.normalAt(0, 0).z) < 1e-6 and f.Area < 300),
                                            (plate,) + front])
        self.solve()
        App.ActiveDocument.recompute()
        n = self.lshape(col).Faces[int(self.element(col, "Face", lambda f: not hasattr(f.Surface, "Radius") and
                                                     abs(f.normalAt(0, 0).z) < 1e-6 and f.Area < 300)[0][4:]) - 1]
        n = n.normalAt(0, 0)
        stayed, back = self.free_to_move(col, self.rotate_about(App.Vector(0, 0, 0), 30))
        self.step("Workaround: delete the joint, turn the Collar 20°, Parallel again", f"joint selected + Delete "
                  f"({'gone' if gone else 'NOT deleted'}), Collar turned, ribbon '{where} > Parallel'",
                  DIFFERS if j2 is not None and abs(abs(n.y) - 1) < 1e-6 and back else FAIL,
                  f"flat normal now ({n.x:.3f}, {n.y:.3f}, {n.z:.3f}); rotated 30° and solved: back {back}. NX drags "
                  "the part with Move Component; here it is turned by its placement")

    def g_screw(self, key, hole_x):
        link, where = self.insert("Cap-Screw")
        self._g[key] = link
        bear = self._g["bearing"]
        c0 = link.Placement.Base
        a = self.cyl_face(link, 3.9, c0.x, c0.y)
        q = bear.Placement.multVec(App.Vector(hole_x, 0, 0))
        b = self.cyl_face(bear, 4, q.x, q.y)
        j, w2 = self.joint("Align/Lock", [(link,) + a, (bear,) + b])
        c = link.Placement.Base
        on_axis = abs(c.x - q.x) < 1e-4 and abs(c.y - q.y) < 1e-4
        stayed, _ = self.free_to_move(link, self.shift(7.0))
        rot, _ = self.free_to_move(link, self.rotate_about(App.Vector(q.x, q.y, 0), 40))
        self.step(f"Add Component: Cap-Screw, Align/Lock on the {'right' if hole_x > 0 else 'left'} hole axis",
                  f"ribbon '{where} > Add Component' + '{w2} > Align/Lock', {a[0]} + {b[0]}",
                  SAME if j is not None and on_axis and stayed and not rot else FAIL,
                  f"on the axis {on_axis}; slides along it {stayed}; turns {rot} (the book: one DOF, along the axis)")
        head = self.plane_face(link, -1, link.Placement.Base.z)
        seat = self.plane_face(bear, 1, 15.0)
        j2, w3 = self.joint("Touch Align", [(link,) + head, (bear,) + seat], 0.0)
        stayed, back = self.free_to_move(link, self.shift(7.0))
        self.step("Touch Align: the head on the counterbore's seat", f"'{w3} > Touch Align', {head[0]} + {seat[0]}",
                  SAME if j2 is not None and back and abs(link.Placement.Base.z - 15) < 1e-4 else FAIL,
                  f"head underside at z = {link.Placement.Base.z:.3f} mm; moved 7 mm and solved: back {back}")

    def g_screw1(self):
        self.g_screw("screw1", 15)

    def g_screw2(self):
        self.g_screw("screw2", -15)

    def g_edit(self):
        """Open the Bearing in its window, change the bore to Ø6.35 (0.25 in), save; the assembly follows."""
        doc, body = self._g_parts["Bearing"]
        bore = doc.getObject("Bore")
        bore.Radius = 6.35 / 2
        doc.recompute()
        doc.save()
        asm_doc = self.assembly().Document
        asm_doc.recompute()
        bear = self._g["bearing"]
        radii = sorted({round(f.Surface.Radius, 3) for f in self.lshape(bear).Faces if hasattr(f.Surface, "Radius")})
        self.step("Edit the Bearing: hole Ø0.25 in (6.35 mm), save; the assembly updates", "Bearing document: the "
                  "bore's Radius in its properties, recompute, save", DIFFERS if 3.175 in radii else FAIL,
                  f"cylinder radii in the assembly's Bearing {radii}; NX: Open in Window, double-click the hole, edit "
                  "the sketch value. The replay's parts are scripted, so the value is a property here")

    def g_explode(self):
        self.step("Exploded view: New Explosion, Collar 1.5 in and a Cap-Screw 2.0 in up; Auto-explode", "-",
                  "skipped", "FreeCAD 1.1's New Explosion moves parts only by dragging a 3D handle (no distance "
                  "field like NX's); the replay does not drag 3D handles")

    def g_bom(self):
        b, where = self.click_ribbon("Bill of Materials")
        self.wait_dialog("bom")
        self.mb2_click()
        qtest().qWait(300)
        mb2_closed = not Gui.Control.activeDialog()
        if not mb2_closed:          # the user would click OK: do that, and report it
            from .navigation import accept_task_dialog
            self.progress(f"g_bom: MB2 did not close the dialog; OK clicked {accept_task_dialog()}")
            qtest().qWait(300)
        App.ActiveDocument.recompute()
        sheets = [o for o in App.ActiveDocument.Objects if o.isDerivedFrom("Spreadsheet::Sheet")]
        self.progress(f"g_bom: sheets {[(o.Name, o.TypeId) for o in sheets]}; dialog open {bool(Gui.Control.activeDialog())}")
        sheet = sheets[-1] if sheets else None
        rows = {}
        if sheet is not None:
            for r in range(1, 30):
                try:
                    vals = [str(sheet.get(f"{c}{r}")) for c in "ABCDEF"]
                except Exception:
                    vals = []
                    for c in "ABCDEF":
                        try:
                            vals.append(str(sheet.get(f"{c}{r}")))
                        except Exception:
                            vals.append("")
                if any(vals):
                    rows[r] = vals
        self.info["G bom"] = rows
        flat = " ".join(" ".join(v) for v in rows.values())
        screws = next((v for v in rows.values() if any("Cap-Screw" in x for x in v)), [])
        header = rows.get(min(rows), []) if rows else []
        qcol = next((i for i, h in enumerate(header) if "quant" in h.lower()), None)
        qty = screws[qcol] if qcol is not None and len(screws) > qcol else None
        ok = sheet is not None and all(n in flat for n in ("Base-Plate", "Bearing", "Collar", "Cap-Screw")) \
            and qty in ("2", "2.0") and not Gui.Control.activeDialog()
        screws = [x for x in screws if not x.endswith(".FCStd")]       # keep the report short
        screws.append(f"quantity {qty}")
        self.step("Parts List", f"ribbon '{where} > Bill of Materials', " + ("MB2 = OK" if mb2_closed else
                                                                            "OK (MB2 did not close this dialog)"),
                  DIFFERS if ok else FAIL,
                  f"spreadsheet rows {len(rows)}; Cap-Screw row {screws}; NX puts the parts list on the drawing, "
                  "FreeCAD makes a spreadsheet (a drawing can show it as a Tabular Note)")

    def g_show(self):
        # OK on the Bill of Materials opens its spreadsheet; click back to the assembly's 3D view tab
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sub in (mdi.subWindowList() if mdi else []):
            if sub.windowTitle().startswith("Shaft-Support") and "Bill" not in sub.windowTitle() \
                    and sub.widget() is not None and sub.widget().inherits("Gui::View3DInventor"):
                mdi.setActiveSubWindow(sub)
                break
        QtWidgets.QApplication.processEvents()
        self.fit()

    def g_save(self):
        self.show("G_shaft_support")
        self.check_drawn("The assembly is shown in the graphics window", "G_live_check.png")
        App.ActiveDocument.save()

    def g_back(self):
        self.key("Ctrl+M")
        self.wait = 1500

    # ---------------------------------------------------------- tutorial H
    # GD&T drawing (Cogorno, GD&T for Mechanical Design 3e, ch. 12.2 and 8): a plate with
    # datum features A (back face), B (bottom edge), C (left edge); 4X holes .510-.540 with
    # position Ø.010 at MMC to A|B|C; datum B perpendicular .004 to A; flatness .002 on A
    # (Prob. 12-3); basic 1.000 / 3.000 from B and C (ch. 8). Inches converted to mm. The
    # plate size and thickness are figure-only: 4.00 x 4.00 x 0.50 in here.
    H_PLATE = (101.6, 101.6, 12.7)
    H_HOLES = [(25.4, 25.4), (25.4, 76.2), (76.2, 25.4), (76.2, 76.2)]
    H_HOLE = (12.954, 13.716)            # .510-.540 in

    def h_new(self):
        self.tutorial = "H: GD&T plate drawing (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def wait_for(self, what, test, timeout_ms=4000):
        """Wait for a condition the way a user waits for the screen; log how long it took."""
        t0 = time.monotonic()
        while not test() and (time.monotonic() - t0) * 1000 < timeout_ms:
            qtest().qWait(100)
        waited = int((time.monotonic() - t0) * 1000)
        if waited > 300 or not test():
            self.progress(f"{what}: {'ready' if test() else 'NOT ready'} after {waited} ms")
        return test()

    def h_part(self):
        import Part
        self.wait_for("h_part: new part's Body", lambda: self.body() is not None)
        doc = App.ActiveDocument
        body = self.body()
        sk = body.newObject("Sketcher::SketchObject", "Sketch")
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        sk.MapMode = "FlatFace"
        L, W, T = self.H_PLATE
        V = App.Vector
        P = [V(0, 0, 0), V(L, 0, 0), V(L, W, 0), V(0, W, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(P[i], P[(i + 1) % 4]), False)
        r = sum(self.H_HOLE) / 4
        for (x, y) in self.H_HOLES:
            sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sk
        pad.Length = T
        sk.Visibility = False
        doc.recompute()
        want = L * W * T - 4 * math.pi * r * r * T
        ok = abs(pad.Shape.Volume - want) < 1e-6 * want
        doc.saveAs(os.path.join(OUT, "GDT-Plate.FCStd"))
        self._h_body = body
        self.step("The plate: 101.6 x 101.6 x 12.7 mm, 4 holes on a 50.8 mm square", "modelled by script (the "
                  "exercise is the drawing)", SAME if ok else FAIL, f"volume {pad.Shape.Volume:.1f} mm^3; back face "
                  "(z = 0) is datum A, bottom edge (y = 0) B, left edge (x = 0) C")

    def h_drafting(self):
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def h_sheet(self):
        b, where = self.click_ribbon("New Sheet")
        QtWidgets.QApplication.processEvents()
        self._page = self.newest("TechDraw::DrawPage")
        self.step("File > Drafting, New Sheet", f"Ctrl+Shift+D + ribbon '{where} > New Sheet'",
                  SAME if self._page is not None else FAIL, "")
        # The book's drawings follow ASME Y14.5: hole notes read horizontally. TechDraw's default
        # standard is ISO Oriented (text along the leader); a drafter picks ASME in the preferences.
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Dimensions")
        before = p.GetInt("StandardAndStyle", 0)
        p.SetInt("StandardAndStyle", 2)          # 0 ISO Oriented, 1 ISO Referencing, 2 ASME Inlined, 3 ASME Referencing
        self.step("Drafting Preferences: ASME standard", "Preferences > TechDraw > Dimensions > Standard and Style "
                  "= ASME Inlined", DIFFERS, f"was {['ISO Oriented', 'ISO Referencing', 'ASME Inlined', 'ASME Referencing'][before] if 0 <= before < 4 else before}; "
                  "NX sets the drafting standard in Drafting Preferences")
        self.wait = 1200

    def h_view(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self._h_body.Name)
        b, where = self.click_ribbon("Base View")
        self._h_where = where
        self.wait = 1500

    def h_view_check(self):
        views = [v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        front = views[-1] if views else None
        if front is not None:
            front.Direction = App.Vector(0, 0, 1)
            front.XDirection = App.Vector(1, 0, 0)
            front.ScaleType = "Custom"
            front.Scale = 1.0
            front.X, front.Y = 105.0, 115.0
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        self._h_front = front
        self.step("Base View: the plate's face, scale 1:1", f"body selected + ribbon '{self._h_where} > Base View'"
                  ", MB2 on the sheet", SAME if front is not None and not Gui.Control.activeDialog() else FAIL,
                  "direction set to look at the face (the book's front view)")
        self.wait = 800

    def h_side(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self._h_body.Name)
        self.click_ribbon("Base View")
        self.wait = 1500

    def h_side_check(self):
        views = [v for v in self._page.Views if v.isDerivedFrom("TechDraw::DrawViewPart") and v is not self._h_front]
        side = views[-1] if views else None
        if side is not None:
            # third-angle right view: Y up as in the face view, thickness across; back face A on the right
            side.Direction = App.Vector(1, 0, 0)
            side.XDirection = App.Vector(0, 0, -1)
            side.ScaleType = "Custom"
            side.Scale = 1.0
            side.X, side.Y = float(self._h_front.X) + 120.0, float(self._h_front.Y)
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        self._h_side = side
        self.step("Projected view to the right: the plate's edge, back face A", "second Base View, MB2",
                  DIFFERS if side is not None else FAIL, "as in tutorial D, a second Base View stands in for a "
                  "view projected off the base view")
        self.wait = 800

    # -- view geometry helpers (edge coordinates: relative to the view centre, Y up, unscaled)
    def view_edges(self, view):
        out = []
        for i in range(len(view.getVisibleEdges())):
            try:
                out.append((i, view.getEdgeByIndex(i)))
            except Exception:
                continue
        return out

    def outer_edge(self, view, side):
        """Index of the view's bounding edge on side 'bottom', 'top', 'left' or 'right'."""
        best = None
        for i, e in self.view_edges(view):
            if hasattr(e.Curve, "Radius"):
                continue
            bb = e.BoundBox
            if side in ("bottom", "top") and bb.YLength < 1e-6 and bb.XLength > 1:
                key = bb.YMin if side == "bottom" else -bb.YMax
            elif side in ("left", "right") and bb.XLength < 1e-6 and bb.YLength > 1:
                key = bb.XMin if side == "left" else -bb.XMax
            else:
                continue
            if best is None or key < best[0]:
                best = (key, i)
        return best[1] if best else None

    def hole_edges(self, view):
        return [(i, e) for i, e in self.view_edges(view) if hasattr(e.Curve, "Radius")]

    def select_view_subs(self, view, subs):
        Gui.Selection.clearSelection()
        for s in subs:
            Gui.Selection.addSelection(App.ActiveDocument.Name, view.Name, s)
        QtWidgets.QApplication.processEvents()

    def h_centres(self):
        """TechDraw dimensions need vertices: put cosmetic vertices on the hole centres
        (NX picks arc centres directly)."""
        v = self._h_front
        holes = self.hole_edges(v)
        made = []
        for i, e in holes:
            c = e.Curve.Center
            try:
                made.append(v.makeCosmeticVertex(App.Vector(c.x, c.y, 0)))
            except Exception as ex:
                self.info.setdefault("H cosmetic vertex errors", []).append(str(ex))
        App.ActiveDocument.recompute()
        self._h_centre_vertices = self.vertices_at(v, [e.Curve.Center for _, e in holes])
        if len(self._h_centre_vertices) != len(holes):
            pts = []
            for k in range(60):
                try:
                    q = v.getVertexByIndex(k).Point
                    pts.append((k, round(q.x, 2), round(q.y, 2)))
                except Exception:
                    break
            self.progress(f"h_centres: centres {[(round(e.Curve.Center.x, 2), round(e.Curve.Center.y, 2)) for _, e in holes]}"
                          f"; cosmetic tags {made}; view vertices {pts}")
        self.step("Arc centres for the dimensions", "cosmetic vertex on each hole centre",
                  DIFFERS if len(self._h_centre_vertices) == 4 else FAIL,
                  f"{len(holes)} holes, {len(made)} cosmetic vertices, found as {self._h_centre_vertices}; NX "
                  "snaps dimensions to arc centres, TechDraw needs vertices there first")

    def vertices_at(self, view, points):
        """Vertex names of the view at the given view coordinates."""
        names = []
        for p in points:
            for k in range(200):
                try:
                    vx = view.getVertexByIndex(k)
                except Exception:
                    break
                q = vx.Point
                if abs(q.x - p.x) < 1e-3 and abs(q.y - p.y) < 1e-3:
                    names.append(f"Vertex{k}")
                    break
        return names

    def corner_vertex(self, view, corner):
        """Vertex name of a corner of the view's outline: 'bl', 'tl', 'br' or 'tr'."""
        bb = None
        for _, e in self.view_edges(view):
            bb = e.BoundBox if bb is None else bb.united(e.BoundBox)
        x = bb.XMin if corner[1] == "l" else bb.XMax
        y = bb.YMin if corner[0] == "b" else bb.YMax
        names = self.vertices_at(view, [App.Vector(x, y, 0)])
        return names[0] if names else None

    def basic_dimension(self, kind, subs, want, at=None):
        """Select two vertices, Horizontal / Vertical Dimension, then make it basic (boxed).
        at: (x or None, y or None) to drag the dimension to, relative to the view centre."""
        before = {d.Name for d in self._page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension")}
        self.select_view_subs(self._h_front, subs)
        b, where = self.click_ribbon(kind)
        QtWidgets.QApplication.processEvents()
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        new = [d for d in self._page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension") and d.Name not in before]
        if not new:
            return None, where, None
        d = new[-1]
        d.TheoreticalExact = True
        d.FormatSpec = "%.1w"
        if at is not None:      # where a drafter drags the dimension: outside the view, clear of the datums
            if at[0] is not None:
                d.X = at[0]
            if at[1] is not None:
                d.Y = at[1]
        App.ActiveDocument.recompute()
        got = d.getRawValue() if hasattr(d, "getRawValue") else None
        return d, where, got

    def h_basic(self):
        tl, bl = self.corner_vertex(self._h_front, "tl"), self.corner_vertex(self._h_front, "bl")
        cv = self._h_centre_vertices
        pts = [e.Curve.Center for _, e in self.hole_edges(self._h_front)]
        if None in (tl, bl) or len(cv) != 4 or len(pts) != 4:
            raise RuntimeError(f"vertices for the dimensions not found: corners {tl} {bl}, centres {cv}")

        def hole(left, low):
            k = min(range(4), key=lambda i: (pts[i].x if left else -pts[i].x) + (pts[i].y if low else -pts[i].y))
            return cv[k]
        out = self.H_PLATE[0] / 2 + 14.0          # just outside the view
        rows = []
        # horizontal ones above the view, vertical ones left (from B) and right (the spacing),
        # clear of the datum symbols on the bottom and left edges
        for kind, subs, want, label, at in (
                ("Horizontal", [tl, hole(True, False)], 25.4, "C to the hole", (None, out)),
                ("Horizontal", [hole(True, False), hole(False, False)], 50.8, "hole spacing", (None, out)),
                ("Vertical", [bl, hole(True, True)], 25.4, "B to the hole", (-out, None)),
                ("Vertical", [hole(False, True), hole(False, False)], 50.8, "hole spacing", (out, None))):
            d, where, got = self.basic_dimension(kind, subs, want, at)
            ok = d is not None and got is not None and abs(abs(got) - want) < 1e-3 and d.TheoreticalExact
            rows.append(ok)
            self.step(f"Basic dimension {want:g} ({label})", f"two vertices + ribbon '{where} > {kind}', then basic",
                      DIFFERS if ok else FAIL, f"measured {got}; NX: Basic is a Tolerance type in the dimension "
                      "dialog, TechDraw: the Theoretical Exact property draws the box")
        self.wait = 600

    def h_hole_note(self):
        holes = self.hole_edges(self._h_front)
        top_right = max(holes, key=lambda h: h[1].Curve.Center.x + h[1].Curve.Center.y)
        before = {d.Name for d in self._page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension")}
        self.select_view_subs(self._h_front, [f"Edge{top_right[0]}"])
        b, where = self.click_ribbon("Diameter")
        QtWidgets.QApplication.processEvents()
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        new = [d for d in self._page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension") and d.Name not in before]
        d = new[-1] if new else None
        lo, hi = self.H_HOLE
        if d is not None:
            d.FormatSpec = "4X ⌀%.3w"            # the format replaces TechDraw's own ⌀ prefix
            d.EqualTolerance = False
            d.OverTolerance = (hi - lo) / 2
            d.UnderTolerance = -(hi - lo) / 2
            d.FormatSpecOverTolerance = "%+.3w"
            d.FormatSpecUnderTolerance = "%+.3w"
            d.X, d.Y = 70.0, 72.0          # up and right of the hole: its frame then clears the view outline
            App.ActiveDocument.recompute()
        got = d.getRawValue() if d is not None and hasattr(d, "getRawValue") else None
        ok = d is not None and got is not None and abs(got - (lo + hi) / 2) < 1e-3
        self._h_note = d
        self.step("Hole note: 4X Ø12.954-13.716 (.510-.540 in)", f"hole edge + ribbon '{where} > Diameter'; "
                  "4X and ±0.381 in the dimension's properties", DIFFERS if ok else FAIL,
                  f"diameter {got}; FreeCAD shows Ø13.335 ±0.381 (NX can also show the limits 13.716/12.954)")
        self.wait = 600

    def datum_symbol(self, view, side, letter):
        idx = self.outer_edge(view, side)
        if idx is None:
            return None, f"no {side} edge found", None
        self.select_view_subs(view, [f"Edge{idx}"])
        b, where = self.click_ribbon("Datum Feature Symbol")
        QtWidgets.QApplication.processEvents()
        field = self.tasks_dock().findChild(QtWidgets.QLineEdit, "datumLetter")
        if field is not None:
            field.selectAll()
            qtest().keyClicks(field, letter)
        self.mb2_click_on_sheet()
        QtWidgets.QApplication.processEvents()
        sym = next((o for o in reversed(self._page.Views) if getattr(o, "NX_Datum", "") == letter), None)
        # the triangle's base must sit on the edge
        e = view.getEdgeByIndex(idx)
        s = float(view.Scale)
        ey = float(view.Y) + e.BoundBox.YMin * s
        ex = float(view.X) + e.BoundBox.XMin * s
        touch = None
        if sym is not None:
            from . import gdt
            _, (w, h) = gdt.datum_feature_symbol(letter, {"bottom": "top", "top": "bottom", "left": "right",
                                                          "right": "left"}[side])
            if side in ("bottom", "top"):
                base = float(sym.Y) + (h / 2 if side == "bottom" else -h / 2)
                touch = abs(base - ey)
            else:
                base = float(sym.X) + (w / 2 if side == "left" else -w / 2)
                touch = abs(base - ex)
        return sym, f"edge Edge{idx} + ribbon '{where} > Datum Feature Symbol', '{letter}', MB2 = OK", touch

    def h_datums(self):
        for view, side, letter, what in ((self._h_side, "right", "A", "the back face (right edge of the edge view)"),
                                         (self._h_front, "bottom", "B", "the bottom edge"),
                                         (self._h_front, "left", "C", "the left edge")):
            sym, how, touch = self.datum_symbol(view, side, letter)
            ok = sym is not None and touch is not None and touch < 0.05 and list(sym.EditableTexts) == [letter]
            self.step(f"Datum Feature Symbol {letter} on {what}", how, DIFFERS if ok else FAIL,
                      f"triangle {touch if touch is None else round(touch, 3)} mm from the edge; editable letter "
                      f"{list(sym.EditableTexts) if sym else None}; FreeCAD 1.1 has no datum feature symbol, "
                      "NXStyle adds NX's")
        self.wait = 600

    def frame(self, select, characteristic, tolerance, diameter, modifier, datums, label):
        """Feature Control Frame dialog: characteristic, tolerance, material condition, datums, MB2 = OK."""
        select()
        b, where = self.click_ribbon("Feature Control Frame")
        QtWidgets.QApplication.processEvents()
        dock = self.tasks_dock()
        combo = dock.findChild(QtWidgets.QComboBox, "characteristic")
        if combo is not None:
            i = next((k for k in range(combo.count()) if combo.itemText(k).lower() == characteristic), -1)
            combo.setCurrentIndex(i)
        box = dock.findChild(QtWidgets.QCheckBox, "zoneDiameter")
        if box is not None and box.isChecked() != diameter:
            box.click()
        for name, text in [("tolerance", tolerance)] + [(f"datum{k + 1}", d) for k, (d, _) in enumerate(datums)]:
            f = dock.findChild(QtWidgets.QLineEdit, name)
            if f is not None:
                f.selectAll()
                qtest().keyClicks(f, text)
        for name, mod in [("materialCondition", modifier)] + [(f"datum{k + 1}Modifier", m)
                                                              for k, (_, m) in enumerate(datums)]:
            c = dock.findChild(QtWidgets.QComboBox, name)
            if c is not None and mod:
                c.setCurrentIndex(max(0, c.findText(mod)))
        self.mb2_click_on_sheet()
        QtWidgets.QApplication.processEvents()
        from . import gdt
        want = gdt.callout(characteristic, tolerance, diameter, modifier, datums)
        sym = next((o for o in reversed(self._page.Views) if getattr(o, "NX_Callout", "") == want), None)
        texts = list(sym.EditableTexts) if sym is not None else None
        ok = sym is not None and texts == [tolerance] + [d for d, _ in datums] and not Gui.Control.activeDialog()
        self.step(label, f"selection + ribbon '{where} > Feature Control Frame'; dialog filled; MB2 = OK",
                  DIFFERS if ok else FAIL, f"frame '{want}'; editable values {texts}; FreeCAD 1.1 has only fixed "
                  "GD&T pictures, NXStyle adds NX's Feature Control Frame dialog")
        return sym

    def h_frames(self):
        side, front = self._h_side, self._h_front
        a = self.outer_edge(side, "right")
        b = self.outer_edge(front, "bottom")
        self.frame(lambda: self.select_view_subs(side, [f"Edge{a}"]), "flatness", "0.051", False, "", [],
                   "Flatness 0.051 on datum A (.002 in, Prob. 12-3)")
        self.frame(lambda: self.select_view_subs(front, [f"Edge{b}"]), "perpendicularity", "0.102", False, "",
                   [("A", "")], "Perpendicularity 0.102 to A on datum B (.004 in)")

        def pick_note():
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(App.ActiveDocument.Name, self._h_note.Name)
        self.frame(pick_note, "position", "0.254", True, "MMC", [("A", ""), ("B", ""), ("C", "")],
                   "Position Ø0.254 (M) to A, B, C under the hole note (.010 in at MMC)")
        self.wait = 800

    def h_show(self):
        App.ActiveDocument.recompute()
        QtWidgets.QApplication.processEvents()
        self.shot("H_gdt_drawing.png")
        App.ActiveDocument.save()

    def h_back(self):
        self.key("Ctrl+M")
        self.wait = 1500

    # ---------------------------------------------------------- tutorial I
    # The Gasket (Shih ch. 6, millimetres): sketch construction tools (Extend, Quick Trim,
    # Fillet R20), extrude 5 mm, then an associative offset cut (project the face, offset
    # 15 mm inwards, subtract through all) and a height change to 150 mm that the offset must
    # follow. The outline's sizes are figure-only: an 80 mm high left side, an R30 boss whose
    # centre the book aligns with the top line ("adjust the dimension to 0.0"), here.
    I_TOP, I_C, I_R = 80.0, (125.0, 80.0), 30.0

    def i_new(self):
        self.tutorial = "I: The Gasket (millimetres)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def i_extrude(self):
        self.wait_for("i: new part's Body", lambda: self.body() is not None)
        self.step("File > New, Model template, millimetres", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def i_plane(self):
        picked = self.pick_in_feature_list("YZ")
        self.mb2_click()
        self.step("Extrude (X), YZ plane", "X key, plane row + MB2", SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def i_outline(self):
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        self._i_sk = sk
        top = self.I_TOP
        (cx, cy), r = self.I_C, self.I_R
        # the top line stops short of the circle; Extend takes it there next
        _, tool, n, ended = self.draw_clicks("Z", [(80, top), (0, top), (0, 0), (160, 0)])
        _, ctool, cn, cended = self.draw_clicks("O", [(cx, cy - 1.5), (cx + r, cy - 1.5)])
        # the tangent line: from the circle's lower right down to the bottom line
        a = math.radians(-45)
        t0 = (cx + r * math.cos(a), cy - 1.5 + r * math.sin(a))
        t1 = (t0[0] - t0[1], 0.0)                 # along (-1, -1): tangent to the circle at t0
        _, ltool, ln, lended = self.draw_clicks("L", [t0, t1])
        kinds = sorted(g.TypeId.split("::")[-1] for g in sk.Geometry)
        tangent = any(c.Type == "Tangent" for c in sk.Constraints)
        self.i_dump(sk, "i_outline drawn")
        self.step("Profile (outline), Circle, Line ending on the bottom line, tangent to the circle",
                  "Z key + 4 MB1 clicks, O key + 2 clicks, L key + 2 clicks, MB2 after each",
                  SAME if tool and ctool and ltool and len(sk.Geometry) >= 5 else FAIL,
                  f"geometry {kinds}; tangent picked up while drawing {tangent}")
        if not tangent:
            import Sketcher
            line = len(sk.Geometry) - 1
            circ = next(i for i, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomCircle")
            try:
                sk.addConstraint(Sketcher.Constraint("Tangent", line, circ))
            except Exception as e:
                self.info["I tangent"] = str(e)
        App.ActiveDocument.recompute()
        self.wait = 300

    @staticmethod
    def i_horizontal(sk, highest):
        """Index of the highest (or lowest) horizontal line: the drawn sizes are pixel-rounded."""
        rows = [(g.StartPoint.y, i) for i, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomLineSegment"
                and abs(g.StartPoint.y - g.EndPoint.y) < 0.5 and not sk.getConstruction(i)]
        return (max(rows) if highest else min(rows))[1] if rows else None

    @staticmethod
    def i_round(sk):
        return next((i for i, g in enumerate(sk.Geometry) if g.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle")
                     and abs(g.Radius - 20) > 1e-3), None)

    def i_extend(self):
        """Extend (E): the top line to the circle - pick near its right end, then on the circle."""
        sk = self._i_sk
        ti, ci = self.i_horizontal(sk, True), self.i_round(sk)
        y = sk.Geometry[ti].StartPoint.y
        c, r = sk.Geometry[ci].Center, sk.Geometry[ci].Radius
        hit = c.x - math.sqrt(max(r * r - (y - c.y) ** 2, 0.0))           # where the top line meets the circle
        self.frame_sketch(sk, 90, 70, 100)
        self.key("E")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        self.mb1_click(self.screen_point(sk, 77.0, y))
        self.send(QtCore.QEvent.MouseMove, self.screen_point(sk, hit, y), Qt.NoButton, Qt.NoButton)
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, hit, y))
        self.mb2_click(self.screen_point(sk, 30, 40))
        App.ActiveDocument.recompute()
        self.i_dump(sk, "i_extend after")
        g = sk.Geometry[self.i_horizontal(sk, True)]
        end = max(g.StartPoint.x, g.EndPoint.x)
        self.step("Extend: the top line up to the circle, MB2", "E key, MB1 near the line's end, MB1 on the circle, "
                  "MB2", SAME if tool and abs(end - hit) < 0.5 else FAIL,
                  f"line now ends at x = {end:.3f} (meets the circle at {hit:.3f})")

    def i_trim(self):
        """Quick Trim (T): the bottom line's end past the slanted line, then the lower part of the circle."""
        sk = self._i_sk
        ci = self.i_round(sk)
        c, r = sk.Geometry[ci].Center, sk.Geometry[ci].Radius
        slanted = next(g for i, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomLineSegment"
                       and abs(g.StartPoint.y - g.EndPoint.y) > 1e-6 and abs(g.StartPoint.x - g.EndPoint.x) > 1e-6)
        foot = min((slanted.StartPoint, slanted.EndPoint), key=lambda p: p.y).x
        self.frame_sketch(sk, 100, 50, 150)
        self.key("T")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        n0 = len(sk.Geometry)
        self.mb1_click(self.screen_point(sk, 150.0, 0.0))                  # bottom line beyond the slanted line
        a = math.radians(250)
        self.mb1_click(self.screen_point(sk, c.x + r * math.cos(a), c.y + r * math.sin(a)))   # lower part of the circle
        self.mb2_click(self.screen_point(sk, 30, 40))
        App.ActiveDocument.recompute()
        self.i_dump(sk, "i_trim after")
        g = sk.Geometry[self.i_horizontal(sk, False)]
        right = max(g.StartPoint.x, g.EndPoint.x)
        arcs = [x for x in sk.Geometry if x.TypeId == "Part::GeomArcOfCircle"]
        circles = [x for x in sk.Geometry if x.TypeId == "Part::GeomCircle"]
        closed, _ = self.i_closed(sk)
        ok = tool and abs(right - foot) < 0.5 and len(arcs) == 1 and not circles and closed
        self.step("Quick Trim: the bottom line past the slanted line, the lower part of the circle, MB2",
                  "T key, MB1 on each part to remove, MB2", SAME if ok else FAIL,
                  f"bottom line now ends at x = {right:.3f} (slanted line at {foot:.3f}); {len(arcs)} arc, "
                  f"{len(circles)} full circle; outline closed {closed}; geometry {n0} -> {len(sk.Geometry)}")

    def i_align(self):
        """The book's dimensions (its steps 1-13): the centre in line with the top line (vertical location
        0), its horizontal location, the radius, the left and bottom edges on the origin. The book's
        sketch is then fully defined; the sizes are the figure's (as drawn here)."""
        import Sketcher
        sk = self._i_sk
        added = self.i_hv(sk)
        ti, bi, ci = self.i_horizontal(sk, True), self.i_horizontal(sk, False), self.i_round(sk)
        lines = [k for k, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomLineSegment" and not sk.getConstruction(k)]
        left = next(k for k in lines if abs(sk.Geometry[k].StartPoint.x - sk.Geometry[k].EndPoint.x) < 0.5)
        slanted = next(k for k in lines if k not in (ti, bi, left))
        before = sk.Geometry[ci].Center.y - sk.Geometry[ti].StartPoint.y
        c, g = sk.Geometry[ci].Center, sk.Geometry[slanted]
        d = g.EndPoint - g.StartPoint
        dims = (("centre on the top line", Sketcher.Constraint("PointOnObject", ci, 3, ti)),
                ("left edge on the origin", Sketcher.Constraint("PointOnObject", left, 1, -2)),
                ("bottom edge on the origin", Sketcher.Constraint("PointOnObject", bi, 1, -1)),
                ("radius", Sketcher.Constraint("Radius", ci, sk.Geometry[ci].Radius)),
                ("horizontal location of the centre", Sketcher.Constraint("DistanceX", -1, 1, ci, 3, c.x)),
                ("height of the centre", Sketcher.Constraint("DistanceY", -1, 1, ci, 3, c.y)),
                ("angle of the slanted line", Sketcher.Constraint("Angle", slanted, math.atan2(d.y, d.x))))
        made, skipped = [], []
        for name, con in dims:
            k = sk.addConstraint(con)
            if sk.solve() != 0:                  # implied by what is there already: FreeCAD calls it redundant
                sk.delConstraint(k)
                skipped.append(name)
            else:
                made.append(name)
        App.ActiveDocument.recompute()
        ti, ci = self.i_horizontal(sk, True), self.i_round(sk)
        after = sk.Geometry[ci].Center.y - sk.Geometry[ti].StartPoint.y
        closed, _ = self.i_closed(sk)
        dof, fully, msg = self.sk_state(sk)
        self.info["I dimensions"] = {"made": made, "skipped (implied)": skipped, "H/V": added, "solver": msg}
        self.step("The book's dimensions: centre in line with the top line (0.0), its horizontal location, the "
                  "radius, the corner on the origin; horizontal/vertical constraints confirmed; fully defined",
                  f"constraints: {', '.join(made)}; H/V: {', '.join(added) or 'none'}",
                  (SAME if fully else DIFFERS) if abs(after) < 1e-6 and closed else FAIL,
                  f"centre {before:+.3f} -> {after:+.3f} mm from the top line; outline closed {closed}; solver: "
                  f"'{msg}' ({dof} DoF). NX sets a 0.0 location dimension; FreeCAD has a point-on-object "
                  "constraint for it" + (f"; implied already: {', '.join(skipped)}" if skipped else ""))

    @staticmethod
    def i_hv(sk):
        """The book's step 11: "confirm that proper constraints are applied to the horizontal and vertical lines"."""
        import Sketcher
        have = {(c.Type, c.First) for c in sk.Constraints if c.Type in ("Horizontal", "Vertical")}
        added = []
        for i, g in enumerate(sk.Geometry):
            if g.TypeId != "Part::GeomLineSegment" or sk.getConstruction(i):
                continue
            d = g.EndPoint - g.StartPoint
            kind = "Horizontal" if abs(d.y) < 0.5 else "Vertical" if abs(d.x) < 0.5 else None
            if kind and (kind, i) not in have:
                k = sk.addConstraint(Sketcher.Constraint(kind, i))
                if sk.solve() != 0:              # already implied (e.g. a right angle): FreeCAD calls it redundant
                    sk.delConstraint(k)
                    added.append(f"{kind} {i} implied")
                else:
                    added.append(f"{kind} {i}")
        App.ActiveDocument.recompute()
        return added

    def i_closed(self, sk):
        try:
            import Part
            w = Part.Wire(Part.__sortEdges__([e for e in sk.Shape.Edges]))
            return w.isClosed(), w
        except Exception as e:
            return False, str(e)

    def i_corners(self, sk):
        """Where two outline curves meet at an angle (not tangent): (point, i, pos_i, j, pos_j)."""
        ends = []
        for i, g in enumerate(sk.Geometry):
            if sk.getConstruction(i) or not hasattr(g, "StartPoint"):
                continue
            e = g.toShape()
            for pos, p, par in ((1, g.StartPoint, e.FirstParameter), (2, g.EndPoint, e.LastParameter)):
                t = e.tangentAt(par)
                ends.append((p, i, pos, t))
        out = []
        for k, (p, i, pi, ti) in enumerate(ends):
            for (q, j, pj, tj) in ends[k + 1:]:
                if j != i and (p - q).Length < 1e-4 and abs(abs(ti.normalize().dot(tj.normalize())) - 1) > 1e-6:
                    out.append((p, i, pi, j, pj))
        return out

    def i_fillet_at(self, sk, corner, radius):
        """The F tool's two picks near the corner, one on each curve, then the radius."""
        p, i, pi, j, pj = corner

        def near(k, pos):
            e = sk.Geometry[k].toShape()
            d = min(3.0, e.Length / 3)
            return e.valueAt(e.getParameterByLength(d if pos == 1 else e.Length - d))
        try:
            sk.fillet(i, j, near(i, pi), near(j, pj), radius, True, False)
            return True
        except Exception as e:
            self.info.setdefault("fillet errors", []).append(f"{p}: {e}")
            return False

    def i_fillets(self):
        sk = self._i_sk
        self.key("F")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        self.mb2_click(self.screen_point(sk, 30, 40))
        made, tried = 0, []
        for _ in range(8):
            todo = [c for c in self.i_corners(sk) if all((c[0] - t).Length > 1e-3 for t in tried)]
            if not todo:
                break
            tried.append(todo[0][0])
            made += self.i_fillet_at(sk, todo[0], 20.0)
            App.ActiveDocument.recompute()
        # a fillet replaces its corner, and with it the right angle that held a side vertical: confirm again
        again = [a for a in self.i_hv(sk) if not a.endswith("implied")]
        # the same for the corner the first click snapped onto the origin: lock the edges to the axes
        import Sketcher
        bi = self.i_horizontal(sk, False)
        left = next(k for k, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomLineSegment"
                    and not sk.getConstruction(k) and abs(g.StartPoint.x - g.EndPoint.x) < 1e-6
                    and abs(g.StartPoint.x) < 0.5)
        for name, con in (("left edge on the origin", Sketcher.Constraint("PointOnObject", left, 1, -2)),
                          ("bottom edge on the origin", Sketcher.Constraint("PointOnObject", bi, 1, -1))):
            k = sk.addConstraint(con)
            if sk.solve() != 0:
                sk.delConstraint(k)
            else:
                again.append(name)
        import Sketcher
        dims = 0
        for i, g in enumerate(sk.Geometry):
            if g.TypeId == "Part::GeomArcOfCircle" and abs(g.Radius - 20) < 1e-6 and not any(
                    c.Type == "Radius" and c.First == i for c in sk.Constraints):
                k = sk.addConstraint(Sketcher.Constraint("Radius", i, 20.0))
                if sk.solve() != 0:
                    sk.delConstraint(k)
                else:
                    dims += 1
        App.ActiveDocument.recompute()
        closed, _ = self.i_closed(sk)
        left = self.i_corners(sk)
        dof, fully, msg = self.sk_state(sk)
        self.step("Fillet R20 at the corners", "F key; radius 20 at each corner where two curves meet at an angle",
                  DIFFERS if tool and made == len(tried) and not left and closed and fully else FAIL,
                  f"{made} fillets of {len(tried)} corners ({', '.join(f'({c.x:.0f}, {c.y:.0f})' for c in tried)}); "
                  f"outline closed {closed}; constraints re-confirmed after the fillets: {', '.join(again) or 'none'}; "
                  f"{dims} R20 dimensions added (FreeCAD's sketch fillet constrains tangency, not the radius); "
                  f"solver '{msg}' ({dof} DoF). "
                  "The book makes five, the arc-to-slanted-line join being tangent here "
                  "leaves four; the radius is typed after picking in FreeCAD")

    def i_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def i_extrude_dialog(self):
        import Part
        self.wait_dialog("i_extrude_dialog")
        field = self.set_quantity("length", 5.0)
        sk = self._i_sk
        closed, w = self.i_closed(sk)
        area = Part.Face(w).Area if closed else 0.0
        self.mb2_click()
        self.check_volume("Finish Sketch, End 5 mm, OK", f"Ctrl+Q, '{field}' = 5 mm, MB2 = OK", area * 5.0,
                          f"; outline area {area:.1f} mm^2")
        self._i_pad = self.body().Tip
        self._i_area = area
        self.wait = 600

    def i_cut(self):
        tip = self.body().Tip
        front = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).x - 1) < 1e-6 and abs(f.CenterOfMass.x - 5) < 1e-6)
        self.select_sub(tip, front)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, Sketch Section on the front face", f"select {front} + ribbon '{where} > Extrude (Subtract)'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  "subtracting extrude is its own button")
        self._i_front = front
        self.wait = 1500

    def i_offset(self):
        """Project Curve: the whole face; Offset Curve 15 mm inwards."""
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on the front face")
        tip = self.body().Tip
        face = tip.Shape.getElement(self._i_front)
        # the face's edges by where they are (isSame is unreliable on 1.1's renamed shapes)
        edges = [f"Edge{i}" for i, e in enumerate(tip.Shape.Edges, start=1)
                 if any((e.CenterOfMass - x.CenterOfMass).Length < 1e-6 and abs(e.Length - x.Length) < 1e-6
                        for x in face.Edges)]
        for e in edges:
            sk.addExternal(tip.Name, e)
        App.ActiveDocument.recompute()
        n_ext = len(sk.ExternalGeo) - 2                      # the first two are the sketch axes
        # the projected curves come in as defining geometry (FreeCAD 1.1): select them, Offset Curve
        Gui.Selection.clearSelection()
        for k in range(n_ext):
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"ExternalEdge{k + 1}")
        n0, c0 = len(sk.Geometry), len(sk.Constraints)
        b, where = self.click_ribbon("Offset Curve", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        qtest().qWait(300)
        # NX's "associative" offset: FreeCAD's "Add offset constraint" option
        box = next((c for c in self.tasks_dock().findChildren(QtWidgets.QCheckBox)
                    if c.isVisible() and "offset constraint" in c.text().lower()), None)
        if box is not None and not box.isChecked():
            qtest().mouseClick(box, Qt.LeftButton)
        # the offset goes where MB1 clicks: 15 mm inside the longest straight edge of the outline
        lines = [g for g in sk.ExternalGeo[2:] if g.TypeId == "Part::GeomLineSegment"]
        far = max(lines, key=lambda g: (g.EndPoint - g.StartPoint).Length)
        mid = (far.StartPoint + far.EndPoint) * 0.5
        d = (far.EndPoint - far.StartPoint).normalize()
        n = App.Vector(-d.y, d.x, 0)
        import Part
        c = Part.Compound([g.toShape() for g in sk.ExternalGeo[2:]]).BoundBox.Center
        if n.dot(App.Vector(c.x, c.y, 0) - mid) < 0:
            n = n * -1
        target = mid + n * 15.0
        self.frame_sketch(sk, target.x, target.y, 200)
        QtWidgets.QApplication.processEvents()
        self.mb1_click(self.screen_point(sk, target.x, target.y))
        qtest().qWait(300)
        if self.nav().sketch_tool_active():
            self.key("Escape")
        App.ActiveDocument.recompute()
        made = len(sk.Geometry) - n0
        new_c = [(i, c.Type) for i, c in enumerate(sk.Constraints) if i >= c0]
        # the click lands on a pixel: type the exact distance into the offset dimension(s), as a user would
        gap0 = self.i_gap(sk)
        # FreeCAD's offset constraints on a closed loop include one redundant tangency (measured: removing
        # any one geometric constraint lets the sketch solve). The solver panel says so; a user picks
        # Sketch > Select Redundant Constraints and presses Delete.
        solved = sk.solve()
        status = self.sk_state(sk)[2]
        redundant = None
        if solved != 0:
            Gui.runCommand("Sketcher_SelectRedundantConstraints")
            QtWidgets.QApplication.processEvents()
            sel = Gui.Selection.getSelectionEx()
            picked = list(sel[0].SubElementNames) if sel else []
            self.key("Delete")
            App.ActiveDocument.recompute()
            redundant = {"solver said": status, "selected": picked, "solve after": sk.solve()}
            new_c = [(i, c.Type) for i, c in enumerate(sk.Constraints) if i >= c0]
        typed = []
        for i, t in new_c:
            if t == "Distance" and abs(sk.Constraints[i].Value - 15) > 1e-6:
                desc = (i, round(sk.Constraints[i].Value, 4))
                try:
                    sk.setDatum(i, App.Units.Quantity("15 mm"))
                    typed.append(desc)
                except Exception as e:
                    self.info.setdefault("I offset datum errors", []).append(f"{desc}: {e}")
        App.ActiveDocument.recompute()
        self.info["I offset tool"] = {"constraint option": box.isChecked() if box else None, "made": made,
                                      "new constraints": [(i, t) for i, t in new_c], "gap after click": gap0,
                                      "redundant": redundant, "typed": typed}
        self._i_cut_sk = sk
        fixed = redundant is None or redundant["solve after"] == 0
        self.step("Project Curve (the whole face), Offset 15 mm, Reverse Direction to the inside, OK",
                  f"{len(edges)} edges projected; ribbon '{where} > Offset Curve', 'Add offset constraint', MB1 "
                  "15 mm inside" + ("; Select Redundant Constraints + Delete" if redundant else "") +
                  "; offset dimension typed 15", DIFFERS if made > 0 and fixed and typed else FAIL,
                  f"{n_ext} projected curves, {made} offset curves; the click gave "
                  f"{gap0 if gap0 is None else round(gap0, 3)} mm. " +
                  (f"FreeCAD's own offset constraints left the sketch unsolvable (solver: '{redundant['solver said']}'"
                   f"; selected {redundant['selected']}); after deleting it the sketch solves "
                   f"({redundant['solve after'] == 0}). " if redundant else "") +
                  "NX types the distance and flips the side with Reverse Direction; FreeCAD takes the side and "
                  "distance from the click, the exact value from its offset dimension")

    @staticmethod
    def i_profile(sk):
        return [g.toShape() for i, g in enumerate(sk.Geometry) if not sk.getConstruction(i)]

    def i_gap(self, sk):
        import Part
        try:
            loop = Part.Wire(Part.__sortEdges__(self.i_profile(sk)))
            outer = Part.Wire(Part.__sortEdges__([g.toShape() for g in sk.ExternalGeo[2:]]))
            return loop.distToShape(outer)[0]
        except Exception:
            return None

    def i_dump(self, sk, tag):
        rows = []
        for i, g in enumerate(sk.Geometry):
            if hasattr(g, "StartPoint"):
                rows.append(f"{i}:{g.TypeId.split('::')[-1][4:]} ({g.StartPoint.x:.2f},{g.StartPoint.y:.2f})-"
                            f"({g.EndPoint.x:.2f},{g.EndPoint.y:.2f})")
            else:
                rows.append(f"{i}:{g.TypeId.split('::')[-1][4:]}")
        self.progress(f"{tag}: " + "; ".join(rows))

    def i_offset_check(self):
        """The inner loop must sit 15 mm inside the outline; turn the projected outline into reference."""
        import Part
        sk = self._i_cut_sk
        gap = self.i_gap(sk)
        try:
            closed = Part.Wire(Part.__sortEdges__(self.i_profile(sk))).isClosed()
        except Exception as e:
            closed = False
            self.info["I offset check"] = str(e)
        profile = len(self.i_profile(sk))
        edges = len(sk.Shape.Edges)
        self.step("Offset loop: 15 mm inside the outline; only the inside loop is the section",
                  f"measured in the sketch; profile edges {edges}, offset curves {profile}: the projected outline "
                  "is reference geometry, as the book selects only the inside loop",
                  SAME if closed and gap is not None and abs(gap - 15) < 1e-3 and edges == profile else FAIL,
                  f"closed {closed}; nearest distance to the projected outline {gap if gap is None else round(gap, 4)} mm")

    def i_cut_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def i_cut_dialog(self):
        import Part
        self.wait_dialog("i_cut_dialog")
        mode = self.choose("through all", "mode")
        self.mb2_click()
        prof = self.i_profile(self._i_cut_sk)
        inner = Part.Face(Part.Wire(Part.__sortEdges__(prof))).Area if prof else 0.0
        self.check_volume("Boolean Subtract, Reverse Direction, Through All, inner loop only, OK",
                          f"'{mode}', MB2 = OK", (self._i_area - inner) * 5.0,
                          "; the projected outline is reference geometry here, so only the inner loop cuts")
        self.wait = 600

    def i_height(self):
        """The book: change the overall height to 150 mm; the offset geometry follows."""
        sk = self._i_sk
        ci = self.i_round(sk)
        r = sk.Geometry[ci].Radius
        h0 = sk.Geometry[ci].Center.y + r - sk.Geometry[self.i_horizontal(sk, False)].StartPoint.y
        k = next((n for n, c in enumerate(sk.Constraints) if c.Type == "DistanceY" and c.First == -1
                  and c.Second == ci), None)
        if k is None:
            raise RuntimeError("no height dimension on the centre")
        sk.setDatum(k, App.Units.Quantity(f"{150 - r} mm"))      # the overall height: centre + R
        App.ActiveDocument.recompute()
        # the cut's sketch projects the pad's edges: one pass can leave it behind (Refresh, F5, in the GUI)
        touched = [o.Name for o in App.ActiveDocument.Objects if "Touched" in o.State]
        if touched:
            App.ActiveDocument.recompute()
        self.info["I height"] = {"solve": sk.solve(), "touched after one recompute": touched}
        self.i_dump(sk, "i_height after")
        shape = self.body().Shape
        # exact extents: BoundBox is padded, and optimalBoundingBox() by default reads the display mesh
        height = shape.optimalBoundingBox(False, False).ZLength
        front = [f for f in shape.Faces if abs(f.normalAt(0, 0).x - 1) < 1e-6 and abs(f.CenterOfMass.x - 5) < 1e-6]
        gap = None
        if front and len(front[0].Wires) > 1:
            gap = front[0].OuterWire.distToShape([w for w in front[0].Wires if not w.isSame(front[0].OuterWire)][0])[0]
        self.step("Change the overall height to 150 mm: the offset follows",
                  f"the centre's height dimension: {h0 - r:.2f} -> {150 - r:.2f} (+ R{r:.2f} = 150)",
                  SAME if shape.isValid() and gap is not None and abs(gap - 15) < 1e-3
                  and abs(height - 150) < 1e-3 else FAIL,
                  f"overall height {h0:.3f} -> {height:.4f} mm; inner loop {gap if gap is None else round(gap, 4)} "
                  "mm inside the outline")

    def i_show(self):
        self.fit()

    def i_save(self):
        self.show("I_gasket")
        self.check_drawn("The part is shown in the graphics window", "I_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Gasket.FCStd"))

    # ---------------------------------------------------------- tutorial J
    # Parametric constraints (Shih ch. 5): a triangle constrained step by step, NX's
    # "fully constrained" messages compared with FreeCAD's solver panel, then dimensions
    # driven by formulas (p8/5*1.6, p10/4*1.2, hole = 1/3 of the height) and a size change.
    # The book's triangle sizes are figure-only; the formulas, 25 x 15, 25 x 20 and the
    # 3.5 thick plate are in the text (inches, typed in mm).
    def j_new(self):
        self.tutorial = "J: Parametric constraints and relations (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def j_extrude(self):
        self.wait_for("j: new part's Body", lambda: self.body() is not None)
        self.step("File > New, Model template", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL, "")
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def j_plane(self):
        picked = self.pick_in_feature_list("YZ")
        self.mb2_click()
        self.step("Extrude (X), YZ plane of the datum CSYS", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    # -- sketch helpers
    def sk_state(self, sk):
        """(DoF, fully constrained, FreeCAD's solver message as the user reads it)."""
        sk.solve()
        msg = []
        for lab in self.tasks_dock().findChildren(QtWidgets.QLabel):
            t = lab.text().strip()
            if lab.isVisible() and t and any(k in t.lower() for k in ("constrain", "dof", "degree")):
                msg.append(re.sub("<[^>]+>", "", t))
        return int(sk.DoF), bool(sk.FullyConstrained), " / ".join(dict.fromkeys(msg))

    def datum_dialog(self, value):
        """Answer FreeCAD's 'Insert length/angle' dialog: type the value, Tab (as a click on OK moves the focus),
        read the field back (a field that took 28.095 as 28.09 fails the step), OK."""
        def handle(w):
            spins = w.findChildren(QtWidgets.QAbstractSpinBox)
            if not spins:
                return False
            self.type_into(spins[0], value)
            for box in w.findChildren(QtWidgets.QDialogButtonBox):
                b = box.button(QtWidgets.QDialogButtonBox.Ok)
                if b is not None:
                    self.info.setdefault("J datum dialogs", []).append(f"{w.windowTitle()}: {value:g}")
                    b.click()
                    return True
            return False
        return handle

    def sk_constrain(self, sk, label, subs, value=None, entry=None):
        """Select sketch elements, click the NX-named constraint button (or pick an entry of its drop-down); type a
        value if asked."""
        n0 = len(sk.Constraints)
        Gui.Selection.clearSelection()
        for s in subs:
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, s)
        QtWidgets.QApplication.processEvents()
        if value is not None:
            self.modals.handler = self.datum_dialog(value)
        if entry is not None:
            where = self.ribbon_button(label, "Sketch")[2] if self.click_dropdown(label, entry, tab="Sketch") else ""
        else:
            b, where = self.click_ribbon(label, tab="Sketch")
        QtWidgets.QApplication.processEvents()
        qtest().qWait(200)
        self.modals.handler = None
        App.ActiveDocument.recompute()
        return len(sk.Constraints) - n0, where

    def sk_vertex(self, sk, geo, pos):
        """FreeCAD's VertexN name of a geometry's start (1) or end (2) point."""
        n = 0
        for i, g in enumerate(sk.Geometry):
            if g.TypeId == "Part::GeomLineSegment":
                for p in (1, 2):
                    n += 1
                    if i == geo and p == pos:
                        return f"Vertex{n}"
            elif g.TypeId == "Part::GeomCircle":
                n += 1                       # the centre
                if i == geo and pos == 3:
                    return f"Vertex{n}"
        return None

    def j_profile(self):
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        pts = [(10.0, 10.0), (110.0, 10.0), (80.0, 60.0)]
        _, tool, n, ended = self.draw_clicks("Z", pts + [pts[0]])
        self._j_sk = sk
        lines = [i for i, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomLineSegment"]
        horiz = [c for c in sk.Constraints if c.Type == "Horizontal"]
        dof, full, msg = self.sk_state(sk)
        self.step("Profile: a triangle with a horizontal base", "Z key + 4 MB1 clicks + MB2",
                  SAME if tool and len(lines) == 3 and horiz and ended else FAIL,
                  f"{len(lines)} lines; implicit constraints {sorted({c.Type for c in sk.Constraints})}; DoF {dof}; "
                  f"FreeCAD says '{msg}'")
        self._j_lines = lines
        self.wait = 300

    def j_perpendicular(self):
        sk = self._j_sk
        right, left = self._j_lines[1], self._j_lines[2]
        d, where = self.sk_constrain(sk, "Perpendicular", [f"Edge{left + 1}", f"Edge{right + 1}"])
        a, b = sk.Geometry[left], sk.Geometry[right]
        u = (a.EndPoint - a.StartPoint).normalize()
        v = (b.EndPoint - b.StartPoint).normalize()
        dof, full, msg = self.sk_state(sk)
        self.step("Perpendicular: the two inclined lines, OK", f"both lines selected + ribbon '{where} > "
                  "Perpendicular'", SAME if d == 1 and abs(u.dot(v)) < 1e-6 else FAIL,
                  f"angle between them {90 - math.degrees(math.asin(max(-1, min(1, abs(u.dot(v)))))):.3f}° "
                  f"(90 wanted); DoF {dof}; '{msg}'")

    def j_dimensions(self):
        sk = self._j_sk
        base, right = self._j_lines[0], self._j_lines[1]
        d1, w1 = self.sk_constrain(sk, "Distance", [f"Edge{base + 1}"], 120.0)
        d2, w2 = self.sk_constrain(sk, "Angle", [f"Edge{base + 1}", f"Edge{right + 1}"], 60.0)
        g = sk.Geometry[base]
        length = (g.EndPoint - g.StartPoint).Length
        dof, full, msg = self.sk_state(sk)
        self._j_angle = len(sk.Constraints) - 1 if d2 else None
        self.step("Dimensions: base length, angle to the right line; the triangle still moves", f"line + ribbon "
                  f"'{w1} > Distance' = 120 mm, two lines + 'Angle' = 60° (typed in FreeCAD's dimension dialog)",
                  SAME if d1 == 1 and d2 == 1 and abs(length - 120) < 1e-6 and dof == 2 else FAIL,
                  f"base {length:.3f} mm; DoF {dof} (size fixed, position free, as in the book); '{msg}'")

    def j_fix(self):
        sk = self._j_sk
        d, where = self.sk_constrain(sk, "Fully Fixed", [f"Edge{self._j_lines[0] + 1}"])
        dof, full, msg = self.sk_state(sk)
        self.step("Fix Curve on one line: fully defined", f"line + ribbon '{where} > Fully Fixed'",
                  SAME if d == 1 and dof == 0 and full else FAIL,
                  f"DoF {dof}, fully constrained {full}; NX turns the sketch black and says it is fully "
                  f"defined, FreeCAD says '{msg}'")

    def j_undo_fix(self):
        sk = self._j_sk
        self.key("Ctrl+Z")
        QtWidgets.QApplication.processEvents()
        dof, full, msg = self.sk_state(sk)
        left_corner = self.sk_vertex(sk, self._j_lines[0], 1)
        d, where = self.sk_constrain(sk, "Coincident", [left_corner, "RootPoint"])
        dof2, full2, msg2 = self.sk_state(sk)
        p = sk.Geometry[self._j_lines[0]].StartPoint
        self.step("Undo, then Coincident: the left corner on the sketch origin", f"Ctrl+Z (DoF back to {dof}); "
                  f"{left_corner} + origin + ribbon '{where} > Coincident'",
                  SAME if dof == 2 and d == 1 and dof2 == 0 and p.Length < 1e-6 else FAIL,
                  f"corner at ({p.x:.3f}, {p.y:.3f}); DoF {dof2}; '{msg2}'")

    def j_location(self):
        sk = self._j_sk
        self.key("Ctrl+Z")
        QtWidgets.QApplication.processEvents()
        dof, _, _ = self.sk_state(sk)
        left_corner = self.sk_vertex(sk, self._j_lines[0], 1)
        d1, w1 = self.sk_constrain(sk, "Distance", [left_corner, "V_Axis"], 25.4)
        d2, w2 = self.sk_constrain(sk, "Distance", [left_corner, "H_Axis"], 25.4)
        dof2, full2, msg2 = self.sk_state(sk)
        p = sk.Geometry[self._j_lines[0]].StartPoint
        self.step("Undo, then location dimensions from the Y axis and the X axis", f"Ctrl+Z (DoF {dof}); "
                  f"corner + Y axis, corner + X axis, ribbon '{w2} > Distance', 25.4 each",
                  SAME if dof == 2 and d1 and d2 and dof2 == 0 else FAIL,
                  f"corner at ({p.x:.3f}, {p.y:.3f}); DoF {dof2}; '{msg2}'")

    def constraint_index(self, sk, kind, test=lambda c: True):
        return next((i for i, c in enumerate(sk.Constraints) if c.Type == kind and test(c)), None)

    def j_relax(self):
        sk = self._j_sk
        ang = self.constraint_index(sk, "Angle")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"Constraint{ang + 1}")
        self.key("Delete")
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        dof1, _, _ = self.sk_state(sk)
        perp = self.constraint_index(sk, "Perpendicular")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"Constraint{perp + 1}")
        b, where = self.click_ribbon("Relax Constraint")
        QtWidgets.QApplication.processEvents()
        App.ActiveDocument.recompute()
        relaxed = not sk.Constraints[perp].IsActive
        dof2, _, _ = self.sk_state(sk)
        d, w2 = self.sk_constrain(sk, "Vertical", [f"Edge{self._j_lines[1] + 1}"])
        dof3, full3, msg3 = self.sk_state(sk)
        self.step("Delete the angle, relax Perpendicular, Vertical on the right line", f"angle + Delete; "
                  f"Perpendicular + ribbon '{where} > Relax Constraint'; line + '{w2} > Vertical'",
                  SAME if ang is not None and relaxed and d == 1 and (dof1, dof2, dof3) == (1, 2, 1) else FAIL,
                  f"DoF after each: {dof1}, {dof2}, {dof3} (the book: one more constraint needed); '{msg3}'")

    def j_height(self):
        sk = self._j_sk
        right = self._j_lines[1]
        d, where = self.sk_constrain(sk, "Distance", [f"Edge{right + 1}"], 72.0)
        dof, full, msg = self.sk_state(sk)
        self.step("Vertical dimension: fully constrained", f"right line + ribbon '{where} > Distance' = 72 mm",
                  SAME if d == 1 and dof == 0 and full else FAIL, f"DoF {dof}; '{msg}'")

    def j_circle(self):
        import Part
        sk = self._j_sk
        c0 = (95.0, 40.0)
        _, tool, n, ended = self.draw_clicks("O", [c0, (c0[0] + 6, c0[1])])
        circ = next((i for i, g in enumerate(sk.Geometry) if g.TypeId == "Part::GeomCircle"), None)
        if circ is None:
            sk.addGeometry(Part.Circle(App.Vector(*c0, 0), App.Vector(0, 0, 1), 6), False)
            circ = len(sk.Geometry) - 1
        d, where = self.sk_constrain(sk, "Tangent", [f"Edge{circ + 1}", f"Edge{self._j_lines[2] + 1}"])
        dof, _, msg = self.sk_state(sk)
        self._j_circ = circ
        self.step("Circle inside, Tangent to the left inclined line", f"O key + 2 MB1 clicks + MB2; circle + line + "
                  f"ribbon '{where} > Tangent'", SAME if tool and d == 1 and dof == 2 else FAIL,
                  f"DoF {dof} (centre still slides along the line); '{msg}'")

    def j_figure(self):
        """'Modify the sketch as shown': the circle located from the right side and the base, with a diameter."""
        import Sketcher
        sk = self._j_sk
        tan = self.constraint_index(sk, "Tangent")
        if tan is not None:
            sk.delConstraint(tan)
        right, base, circ = self._j_lines[1], self._j_lines[0], self._j_circ
        sk.addConstraint(Sketcher.Constraint("DistanceX", circ, 3, right, 1, 30.0))
        sk.addConstraint(Sketcher.Constraint("DistanceY", base, 1, circ, 3, 20.0))
        sk.addConstraint(Sketcher.Constraint("Diameter", circ, 20.0))
        App.ActiveDocument.recompute()
        dof, full, msg = self.sk_state(sk)
        self.step("Match the figure: circle located from the right side and the base, a diameter", "values applied",
                  DIFFERS if dof == 0 else FAIL, f"DoF {dof}; '{msg}'; the figure's values are not in the text")

    def j_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def j_extrude_dialog(self):
        self.wait_dialog("j_extrude_dialog")
        field = self.set_quantity("length", 3.5 * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        sk = self._j_sk
        ok = self.solid_volume() > 0 and abs(self.body().Shape.BoundBox.XLength - 3.5 * IN) < 1e-6
        self.step("Extrude, plate thickness 3.5 in", f"Ctrl+Q, '{field}' = 88.9 mm, MB2 = OK", SAME if ok else FAIL,
                  f"thickness {self.body().Shape.BoundBox.XLength:.3f} mm; sketch {sk.Name}")
        self.wait = 600

    def j_relations(self):
        """NX: Edit Annotation > Expression shows p-names; a dimension's value becomes a formula."""
        sk = self._j_sk
        idx = {}
        for i, c in enumerate(sk.Constraints):
            if c.Type == "DistanceX" and c.First == self._j_circ:
                idx["hx"] = i
            elif c.Type == "DistanceY" and c.Second == self._j_circ:
                idx["vy"] = i
            elif c.Type == "Diameter":
                idx["dia"] = i
            elif c.Type == "Distance" and c.First == self._j_lines[0] and c.FirstPos == 0:
                idx["width"] = i          # the base line's length (not a point-to-axis distance)
            elif c.Type == "Distance" and c.First == self._j_lines[1] and c.FirstPos == 0:
                idx["height"] = i
        for n, i in idx.items():
            sk.renameConstraint(i, n)
        # the book: hx = p8/5*1.6, vy = p10/4*1.2 (p8, p10 the overall sizes); hole = 1/3 of the height
        exprs = {"hx": "Constraints.width / 5 * 1.6", "vy": "Constraints.height / 4 * 1.2",
                 "dia": "Constraints.height / 3"}
        for n, e in exprs.items():
            sk.setExpression(f"Constraints.{n}", e)
        App.ActiveDocument.recompute()
        self.step("Show the dimension names; enter p8/5*1.6 and p10/4*1.2; hole = 1/3 of the height",
                  "constraints renamed (width, height, hx, vy, dia) and given formulas",
                  DIFFERS if len(idx) == 5 else FAIL,
                  f"FreeCAD names a dimension in its properties (NX: p0, p1 ... automatically) and takes a formula "
                  f"after '=' in the dimension dialog: {exprs}")

    def j_resize(self, w_in, h_in, label):
        sk = self._j_sk
        sk.setDatum("width", App.Units.Quantity(f"{w_in * IN} mm"))
        sk.setDatum("height", App.Units.Quantity(f"{h_in * IN} mm"))
        App.ActiveDocument.recompute()
        c = sk.Geometry[self._j_circ]
        right_x = sk.Geometry[self._j_lines[1]].StartPoint.x
        base_y = sk.Geometry[self._j_lines[0]].StartPoint.y
        W, H = w_in * IN, h_in * IN
        want = (W / 5 * 1.6, H / 4 * 1.2, H / 3)
        got = (right_x - c.Center.x, c.Center.y - base_y, 2 * c.Radius)
        ok = all(abs(a - b) < 1e-6 for a, b in zip(want, got)) and self.body().Shape.isValid()
        self.step(label, f"width = {W:g} mm, height = {H:g} mm",
                  SAME if ok else FAIL, "circle from the right side, from the base, diameter: "
                  + ", ".join(f"{g:.3f}" for g in got) + " mm (formulas: " + ", ".join(f"{w:.3f}" for w in want) + ")")

    def j_resize1(self):
        self.j_resize(25, 15, "Change the triangle to 25 x 15 in: the hole follows")

    def j_resize2(self):
        self.j_resize(25, 20, "Change it to 25 x 20 in: location and size follow")
        self.fit()

    def j_show(self):
        self.show("J_parametric")
        self.check_drawn("The part is shown in the graphics window", "J_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Constraints.FCStd"))

    # ---------------------------------------------------------- tutorial K
    # Parameter-driven part (Leake & Borgerson, Engineering Design Graphics, ch. 7, Fig. 7-30;
    # second notebook): a flat bar with N equally spaced holes, driven by L, N, D and
    # hole_spacing = (L - 2 D) / (N - 1). Configuration A: L 48, N 5, D 2; B: L 36, N 8, D 1
    # (inches). Bar width, thickness and hole size are not given: 2.0 x 0.5 in, Ø0.5 here.
    K_W, K_T, K_R = 2.0 * 25.4, 0.5 * 25.4, 0.25 * 25.4

    def k_new(self):
        self.tutorial = "K: Parameter-driven flat bar (Leake, book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def type_cell(self, _view, cell, text):
        """Go to a cell, type its content, Enter (as a user fills in the expression sheet).

        FreeCAD 1.1 draws the table inside a graphics scene that Python cannot walk, so the cell
        is chosen through the sheet view's own API and the keys go to the focused widget."""
        from .smoke import decode
        sv = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if sv is None or not hasattr(sv, "setCurrentIndex"):
            return False
        sv.setCurrentIndex(cell)
        QtWidgets.QApplication.processEvents()
        # the sheet's content line above the grid (like a formula bar): click it, type, Enter
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi else None
        line = next((w for w in (sub.widget().findChildren(QtWidgets.QLineEdit) if sub and sub.widget() else [])
                     if w.metaObject().className() == "Gui::ExpressionLineEdit" and w.isVisible()), None)
        if line is None:
            self.progress(f"type_cell {cell}: no content line in '{sub.windowTitle() if sub else None}'")
            return False
        line.setFocus()
        line.selectAll()
        qtest().keyClicks(line, text)
        qtest().keyClick(line, *decode("Return"))
        QtWidgets.QApplication.processEvents()
        return True

    def k_sheet(self):
        self.wait_for("k: new part's Body", lambda: self.body() is not None)
        self.key("Ctrl+E")
        QtWidgets.QApplication.processEvents()
        qtest().qWait(500)
        doc = App.ActiveDocument
        sheet = doc.getObject("Expressions")
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi else None
        self.progress(f"k_sheet: sheet {getattr(sheet, 'Name', None)}; active window '{sub.windowTitle() if sub else None}'")
        typed = {}
        if sheet is not None:
            # the book's 48 in and 2 in, typed in mm
            for cell, text in (("A2", "L"), ("B2", "=1219.2 mm"), ("A3", "N"), ("B3", "5"), ("A4", "D"),
                               ("B4", "=50.8 mm")):
                self.type_cell(None, cell, text)
            doc.recompute()
            typed = {c: str(sheet.getContents(c)) for c in ("A2", "B2", "A3", "B3", "A4", "B4")}
        self._k_sheet = sheet
        ok = typed.get("B2", "").replace(" ", "") == "=1219.2mm" and typed.get("B3") == "5"
        self.step("Tools > Expressions (Ctrl+E): L = 48, N = 5, D = 2 (in)", "Ctrl+E opens NXStyle's Expressions sheet; "
                  "names and values typed into its cells", DIFFERS if ok else FAIL,
                  f"cells {typed}; NX lists expressions in a dialog, FreeCAD keeps them in a spreadsheet")

    def k_names(self):
        """Give the value cells their names. FreeCAD refuses names that are unit symbols."""
        sheet = self._k_sheet
        result = {}
        for cell, name in (("B2", "L"), ("B3", "N"), ("B4", "D")):
            try:
                sheet.setAlias(cell, name)
                result[name] = "ok"
            except Exception as e:
                result[name] = str(e)
        refused = [n for n, r in result.items() if r != "ok"]
        for n in refused:                                  # the workaround: another name
            sheet.setAlias({"L": "B2", "N": "B3", "D": "B4"}[n], f"{n}_holes" if n == "N" else f"{n}_")
        self._k_names = {n: (n if result[n] == "ok" else (f"{n}_holes" if n == "N" else f"{n}_")) for n in result}
        L, N, D = (self._k_names[k] for k in ("L", "N", "D"))
        self.type_cell(None, "A5", "hole_spacing")
        self.type_cell(None, "B5", f"=({L} - 2 * {D}) / ({N} - 1)")
        sheet.setAlias("B5", "hole_spacing")
        App.ActiveDocument.recompute()
        hs = sheet.get("hole_spacing")
        hs = float(getattr(hs, "Value", hs))
        self.step("Names L, N, D and the equation hole_spacing = (L - 2D)/(N - 1)", "alias per value cell (cell "
                  "properties); equation typed into B5", (DIFFERS if refused else SAME) if abs(hs - 11 * IN) < 1e-6
                  else FAIL, f"hole_spacing = {hs:.3f} mm ({11 * IN:.3f} expected, the book's 11 in); names refused: "
                  + (", ".join(f"{n} ({result[n]}: a unit symbol, newton)" if n == "N" else f"{n} ({result[n]})"
                               for n in refused) or "none") + f"; used {self._k_names}")

    def k_bar(self):
        self.mdi_3d()
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def mdi_3d(self):
        """Click back to the part's 3D view tab (the sheet window is in front)."""
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sub in (mdi.subWindowList() if mdi else []):
            if sub.widget() is not None and sub.widget().inherits("Gui::View3DInventor") \
                    and sub.windowTitle().startswith(App.ActiveDocument.Label):
                mdi.setActiveSubWindow(sub)
                break
        QtWidgets.QApplication.processEvents()

    def k_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Create the flat bar: Extrude (X), XY plane", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def k_profile(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        L = 48 * IN
        P = [App.Vector(0, 0, 0), App.Vector(L, 0, 0), App.Vector(L, self.K_W, 0), App.Vector(0, self.K_W, 0)]
        _, tool, n, ended = self.draw_clicks("R", [(0, 0), (L, self.K_W)])
        sk.deleteAllGeometry()
        for i in range(4):
            sk.addGeometry(Part.LineSegment(P[i], P[(i + 1) % 4]), False)
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", 3))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        i = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, L))
        sk.renameConstraint(i, "length")
        sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, self.K_W))
        sk.setExpression("Constraints.length", f"Expressions.{self._k_names['L']}")
        App.ActiveDocument.recompute()
        self._k_sk = sk
        self.step("Rectangle, its length = L", "R key + 2 MB1 clicks + MB2; length tied to the expression",
                  DIFFERS if tool and int(sk.DoF) == 0 else FAIL,
                  f"DoF {sk.DoF}; NX types 'L' in the dimension, FreeCAD types '=Expressions.L' (f(x)) in it")

    def k_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def k_pad(self):
        self.wait_dialog("k_pad")
        field = self.set_quantity("length", self.K_T)
        self.mb2_click()
        App.ActiveDocument.recompute()
        want = 48 * IN * self.K_W * self.K_T
        self.check_volume("Extrude the bar, 0.5 in thick", f"Ctrl+Q, '{field}' = 12.7 mm, MB2 = OK", want)
        self.wait = 600

    def k_hole(self):
        tip = self.body().Tip
        top = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - self.K_T) < 1e-6)
        self.select_sub(tip, top)
        b, where = self.click_ribbon("Hole")
        self.step("Create a hole at one end of the bar", f"top face + ribbon '{where} > Hole'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  "FreeCAD's Hole drills at circle centres in a sketch on the face")
        self.wait = 1500

    def k_hole_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no hole sketch in edit")
        tip = self.body().Tip
        # project the bar's left end (top edge) so the hole is located from it
        end_i, end_e = next(((i, e) for i, e in enumerate(tip.Shape.Edges, start=1)
                             if all(abs(v.Point.x) < 1e-6 and abs(v.Point.z - self.K_T) < 1e-6 for v in e.Vertexes)),
                            (None, None))
        sk.addExternal(tip.Name, f"Edge{end_i}")
        c = self.g2s(sk, 2, self.K_W / 2 / IN, self.K_T / IN)
        _, tool, n, ended = self.draw_clicks("O", [c, (c[0] + self.K_R, c[1])])
        sk.deleteAllGeometry()
        sk.addGeometry(Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), self.K_R), False)
        sk.addConstraint(Sketcher.Constraint("Diameter", 0, 2 * self.K_R))
        # the projected end runs across the bar: the other sketch axis is along the bar
        s0 = App.Vector(*self.g2s(sk, end_e.Vertexes[0].Point.x / IN, end_e.Vertexes[0].Point.y / IN, self.K_T / IN), 0)
        s1 = App.Vector(*self.g2s(sk, end_e.Vertexes[-1].Point.x / IN, end_e.Vertexes[-1].Point.y / IN, self.K_T / IN), 0)
        across_is_y = abs(s1.y - s0.y) > abs(s1.x - s0.x)
        along_kind, across_kind = ("DistanceX", "DistanceY") if across_is_y else ("DistanceY", "DistanceX")
        d_along = (c[0] - s0.x) if across_is_y else (c[1] - s0.y)
        d_across = (c[1] - s0.y) if across_is_y else (c[0] - s0.x)

        def signed(kind, value):
            # keep the stored value positive so an expression (D) cannot flip the hole to the other side
            if value >= 0:
                return Sketcher.Constraint(kind, -3, 1, 0, 3, value)
            return Sketcher.Constraint(kind, 0, 3, -3, 1, -value)
        i = sk.addConstraint(signed(along_kind, d_along))
        sk.renameConstraint(i, "end_distance")
        sk.addConstraint(signed(across_kind, d_across))
        App.ActiveDocument.recompute()
        self._k_hole_sk = sk
        self.step("Hole centre at D from the end, on the centre line", "O key + 2 MB1 clicks + MB2; distance from "
                  "the projected end tied to D", SAME if tool and abs(abs(d_along) - 2 * IN) < 1e-6 else FAIL,
                  f"DoF {sk.DoF}; {abs(d_along):.3f} mm from the end, {abs(d_across):.3f} mm from the "
                  "edge")


    def k_hole_finish(self):
        sk = self._k_hole_sk
        try:
            sk.setExpression("Constraints.end_distance", f"Expressions.{self._k_names['D']}")
            App.ActiveDocument.recompute()
        except Exception as e:
            self.info["K hole expression"] = str(e)
        self.key("Ctrl+Q")
        self.wait = 1800

    def k_hole_dialog(self):
        self.wait_dialog("k_hole_dialog")
        dia = self.set_quantity("diameter", 2 * self.K_R)
        depth = self.choose("through", "depthtype")
        self.mb2_click()
        want = (48 * IN * self.K_W - math.pi * self.K_R ** 2) * self.K_T
        self.check_volume("Hole Ø0.5 through", f"'{dia}' = 12.7 mm, '{depth}', MB2 = OK", want)
        self._k_hole = self.body().Tip
        self.wait = 600

    def k_pattern(self):
        self.select_sub(self._k_hole, "")
        b, where = self.click_ribbon("Pattern Feature")
        self._k_where = where
        self.wait = 1500

    def k_pattern_dialog(self):
        self.wait_dialog("k_pattern_dialog")
        panels = self.pattern_dirs()
        got = self.set_direction(panels[0], "x axis", 5, 11.0) if panels else {}     # configuration A's pitch
        pat = self.newest("PartDesign::LinearPattern")
        counts = {p: getattr(pat, p) for p in pat.PropertiesList if p.startswith("Occurrences")} if pat else {}
        if not pat or any(v > 100 for v in counts.values()):
            for p in counts:
                setattr(pat, p, 2)
            Gui.Control.closeDialog()
            raise RuntimeError(f"pattern count not as typed: {counts}")
        self.mb2_click()
        App.ActiveDocument.recompute()
        pat.setExpression("Occurrences", f"Expressions.{self._k_names['N']}")
        pat.setExpression("Offset", "Expressions.hole_spacing")
        App.ActiveDocument.recompute()
        self._k_pat = pat
        ok = self.k_check(48, 5, 2)
        self.step("Rectangular array of the hole: count N, spacing hole_spacing", f"hole + ribbon '{self._k_where} > "
                  f"Pattern Feature', X axis, {got}; count and spacing tied to N and hole_spacing (f(x))",
                  DIFFERS if ok[0] else FAIL, ok[1] + "; NX: the array's count and pitch fields take the "
                  "expression names directly")

    def k_check(self, L, N, D):
        """Measure the bar: length, hole count, first and last hole centres, pitch; and its volume."""
        shape = self.body().Shape
        xs = sorted({round(e.Curve.Center.x, 4) for e in shape.Edges if hasattr(e.Curve, "Radius")
                     and abs(e.Curve.Radius - self.K_R) < 1e-6 and abs(e.Curve.Center.z - self.K_T) < 1e-6})
        length = shape.BoundBox.XLength
        pitch = [round(b - a, 4) for a, b in zip(xs, xs[1:])]
        want_pitch = (L - 2 * D) / (N - 1) * IN
        want_vol = (L * IN * self.K_W - N * math.pi * self.K_R ** 2) * self.K_T
        ok = (abs(length - L * IN) < 1e-4 and len(xs) == N and xs and abs(xs[0] - D * IN) < 1e-4
              and abs(xs[-1] - (L - D) * IN) < 1e-4 and all(abs(p - want_pitch) < 1e-4 for p in pitch)
              and abs(shape.Volume - want_vol) < 1e-3 * want_vol)
        return ok, (f"length {length:.3f} mm, {len(xs)} holes, first at {xs[0] if xs else 0:.3f} mm, last "
                    f"{xs[-1] if xs else 0:.3f} mm, pitch {pitch[0] if pitch else 0:.4f} mm "
                    f"({want_pitch:.4f} wanted); volume {shape.Volume:.0f} mm^3 ({want_vol:.0f} wanted)")

    def k_config_b(self):
        """Configuration B: type L 36, N 8, D 1 into the sheet; the part regenerates."""
        doc = App.ActiveDocument
        sheet = self._k_sheet
        sheet.ViewObject.doubleClicked()
        QtWidgets.QApplication.processEvents()
        for cell, text in (("B2", "=914.4 mm"), ("B3", "8"), ("B4", "=25.4 mm")):     # 36 in, 8, 1 in
            self.type_cell(None, cell, text)
        doc.recompute()
        self.mdi_3d()
        ok, detail = self.k_check(36, 8, 1)
        self.step("Configuration B: L 36, N 8, D 1", "values typed into the sheet's cells", SAME if ok else FAIL,
                  detail)

    def k_show(self):
        self.fit()

    def k_save(self):
        self.show("K_flat_bar")
        self.check_drawn("The part is shown in the graphics window", "K_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "FlatBar.FCStd"))

    # ---------------------------------------------------------- tutorial L
    # The Locator (Shih ch. 3, a millimetre part): Constructive Solid Geometry with sketched and placed
    # features. The text gives 75 x 50 x 15, the boss's circle through the edge midpoint and corner
    # (R25), 40 high, a Ø30 bore, a Ø20 hole with 25 and 30 location dimensions, and a 15 / 20 slot
    # from the right face cut Until Next. Where the hole and the slot sit is in the figures: here the
    # hole is 25 mm from the right edge on the slot's centre line, the slot 15 mm from the front edge
    # and 20 wide, so it runs into the hole. The boss is on the left short edge.
    L_HOLE, L_R_HOLE = (50.0, 25.0), 10.0
    L_SLOT = (15.0, 20.0)                       # offset from the front edge, width

    def g2s_mm(self, sk, x, y, z):
        """Global millimetres -> sketch coordinates."""
        p = sk.getGlobalPlacement().inverse().multVec(App.Vector(x, y, z))
        return p.x, p.y

    def l_ref(self, stage):
        """The same part built with the Part API, up to a stage (1 block ... 5 slot)."""
        import Part
        V = App.Vector
        s = Part.makeBox(75, 50, 15)
        if stage >= 2:
            s = s.fuse(Part.makeCylinder(25, 40, V(0, 25, 0)))
        if stage >= 3:
            s = s.cut(Part.makeCylinder(15, 40, V(0, 25, 0)))
        if stage >= 4:
            s = s.cut(Part.makeCylinder(self.L_R_HOLE, 15, V(*self.L_HOLE, 0)))
        if stage >= 5:
            y0, w = self.L_SLOT
            s = s.cut(Part.makeBox(75 - self.L_HOLE[0], w, 15, V(self.L_HOLE[0], y0, 0)))
        return s.Volume

    def l_new(self):
        self.tutorial = "L: The Locator (millimetres)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def l_app(self):
        self.wait_for("l: new part", lambda: bool(set(App.listDocuments()) - self._docs_before))
        new = set(App.listDocuments()) - self._docs_before
        self.step("File > New, Millimeters, Blank template, name Locator", "Ctrl+N", DIFFERS if new else FAIL,
                  "NXStyle's New is NX's Model template (a part with a Body to sketch on); there is no Blank "
                  "template, so the part is in Modeling already; the name is given at the first save")
        def where_am_i():
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            sub = mdi.activeSubWindow() if mdi else None
            return {"active doc": App.ActiveDocument.Name if App.ActiveDocument else None,
                    "window": sub.windowTitle() if sub else None,
                    "bodies": {d: [o.Name for o in App.getDocument(d).Objects if o.isDerivedFrom("PartDesign::Body")]
                               for d in App.listDocuments()}}
        self.info["L after Ctrl+N"] = where_am_i()
        b, where = self.click_ribbon("Modeling", tab="Application")
        QtWidgets.QApplication.processEvents()
        qtest().qWait(200)
        after = where_am_i()
        self.info["L after Application > Modeling"] = after
        app = (self.shell.current_app or {}).get("id")
        stays = after["active doc"] in new
        self.step("File > Applications > Modeling", f"ribbon '{where} > Modeling'",
                  SAME if b is not None and app == "modeling" and stays else FAIL,
                  f"application {app}; the new part stays the active one: {stays} ({after['window']})")
        if not stays:
            raise RuntimeError("the new part is not the active document")
        self.wait = 800

    def l_extrude(self):
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def l_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude, Sketch Section, the default XY plane, OK", "X key, plane row + MB2",
                  SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def l_rect(self):
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        _, tool, n, ended = self.draw_clicks("R", [(6.0, 4.0), (68.0, 43.0)])
        self.step("Rectangle (R): two corners, MB2", "R key + 2 MB1 clicks + MB2",
                  SAME if tool and n >= 4 and ended else FAIL, f"tool {tool}; {n} curves; ended {ended}")
        L = [((0, 0), (75, 0)), ((75, 0), (75, 50)), ((75, 50), (0, 50)), ((0, 50), (0, 0))]
        self.rebuild(sk, lines=L, constraints=[
            ("Horizontal", 0), ("Vertical", 1), ("Horizontal", 2), ("Vertical", 3), ("Coincident", 0, 1, -1, 1),
            ("DistanceX", 0, 1, 0, 2, 75.0), ("DistanceY", 1, 1, 1, 2, 50.0)])
        self.step("Dimensions 75 and 50 ('scale the sketch?': Yes)", "values applied", DIFFERS,
                  f"DoF {sk.DoF}; FreeCAD has no prompt to scale the whole sketch to the first dimension; the "
                  "corner is put on the origin here (the book leaves the rectangle where it was drawn)")
        self.wait = 300

    def l_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def l_extrude_dialog(self):
        self.wait_dialog("l_extrude_dialog")
        field = self.set_quantity("length", 15)
        self.mb2_click()
        ok = self.check_volume("Finish Sketch, distance 15, OK", f"Ctrl+Q, '{field}' = 15 mm, MB2 = OK", self.l_ref(1))
        self._l_base = self.body().Tip
        if not ok:
            pad, prof = self._l_base, getattr(self._l_base, "Profile", None)
            sk = prof[0] if prof else None
            self.info["L base pad"] = {p: str(getattr(pad, p, None)) for p in ("Type", "SideType", "Length", "Length2",
                                                                               "Midplane", "Reversed", "TaperAngle")}
            self.info["L base sketch"] = {"name": getattr(sk, "Name", None), "geometry": len(getattr(sk, "Geometry", [])),
                                          "edges": len(sk.Shape.Edges) if sk else None,
                                          "bbox": str(sk.Shape.BoundBox) if sk else None,
                                          "doc": App.ActiveDocument.Name, "bodies": [o.Name for o in App.ActiveDocument.Objects
                                                                                    if o.isDerivedFrom("PartDesign::Body")]}
            raise RuntimeError("base feature wrong")
        self.wait = 600

    def ext_count(self, sk):
        return len(sk.ExternalGeo) - 2          # the first two are the sketch axes

    def project_edges(self, sk, picks, edges, label):
        """Project Curve: start the tool, MB1 on each edge (global mm points on them), MB2.
        Falls back to the API for an edge the click did not pick, and says so."""
        n0 = self.ext_count(sk)
        b, _ = self.click_ribbon("Project Curve", tab="Sketch")
        QtWidgets.QApplication.processEvents()
        tool = self.nav().sketch_tool_active()
        for p in picks:
            self.mb1_click(self.screen_point(sk, *self.g2s_mm(sk, *p)))
        far = self.g2s_mm(sk, *picks[0])
        self.mb2_click(self.screen_point(sk, far[0] + 40, far[1] + 40))
        made = self.ext_count(sk) - n0
        if made != len(edges):
            for _ in range(self.ext_count(sk) - n0):
                sk.delExternal(n0)
            for obj, sub in edges:
                sk.addExternal(obj.Name, sub)
            App.ActiveDocument.recompute()
        ok = made == len(edges)
        self.step(label, "ribbon 'Project Curve' + MB1 on each edge + MB2", SAME if tool and ok else DIFFERS,
                  f"{made} of {len(edges)} edges picked in the graphics window" + ("" if ok else
                                                                                   "; the rest added through the API"))
        return n0

    def to_reference(self, sk, first, count):
        """FreeCAD 1.1 projects picked edges as defining geometry: turn them into reference (construction)."""
        n0 = len(sk.Shape.Edges)
        Gui.Selection.clearSelection()
        for k in range(count):
            Gui.Selection.addSelection(App.ActiveDocument.Name, sk.Name, f"ExternalEdge{first + k + 1}")
        b, _ = self.click_ribbon("Convert To/From Reference", tab="Sketch")
        App.ActiveDocument.recompute()
        Gui.Selection.clearSelection()
        return n0, len(sk.Shape.Edges)

    def l_boss(self):
        base = self._l_base
        face = self.face_of(base, lambda f: abs(f.normalAt(0, 0).z + 1) < 1e-6 and abs(f.CenterOfMass.z) < 1e-6)
        self.select_sub(base, face)
        b, where = self.click_ribbon("Extrude")
        self.step("Extrude, the bottom face as the sketch plane", f"select {face} + ribbon '{where} > Extrude'",
                  SAME if b is not None and self.edited_sketch() is not None else FAIL, "")
        self.wait = 1500

    def l_boss_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on the bottom face")
        base = self._l_base
        edge = next((f"Edge{i}" for i, e in enumerate(base.Shape.Edges, start=1)
                     if all(abs(v.Point.x) < 1e-6 and abs(v.Point.z) < 1e-6 for v in e.Vertexes)
                     and abs(e.Length - 50) < 1e-6), None)
        self.frame_sketch(sk, *self.g2s_mm(sk, 10, 25, 0), 140)
        first = self.project_edges(sk, [(0, 18, 0)], [(base, edge)], "More > Project Curve: the bottom left edge, OK")
        c, r = self.g2s_mm(sk, 0, 25, 0), self.g2s_mm(sk, 0, 0, 0)
        _, tool, n, ended = self.draw_clicks("O", [c, r])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), 25.0)])
        ext = -3 - first
        sk.addConstraint(Sketcher.Constraint("Symmetric", ext, 1, ext, 2, 0, 3))      # centre = the edge's midpoint
        sk.addConstraint(Sketcher.Constraint("PointOnObject", ext, 1, 0))             # through the corner
        App.ActiveDocument.recompute()
        self.step("Circle: centre on the edge's midpoint, through the left corner, MB2", "O key + 2 MB1 clicks + "
                  "MB2; midpoint and corner as constraints", SAME if tool and n >= 1 and ended else FAIL,
                  f"DoF {sk.DoF}; the book: no dimension needed, the circle is defined by the midpoint and the "
                  "corner. NX snaps while drawing, FreeCAD records the same as constraints")
        before, after = self.to_reference(sk, first, 1)
        self.step("(FreeCAD) the projected edge to reference", "ribbon 'Convert To/From Reference'",
                  DIFFERS if after == 1 else FAIL, f"profile edges {before} -> {after}. FreeCAD 1.1 projects "
                  "a picked edge as defining geometry, which would leave an open wire; NX makes regions")
        self.wait = 300

    def l_boss_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def l_boss_dialog(self):
        self.wait_dialog("l_boss_dialog")
        field = self.set_quantity("length", 40)
        rev = self.checkbox("reverse")
        self.mb2_click()
        App.ActiveDocument.recompute()
        bb = self.body().Shape.BoundBox
        ok = self.check_volume("End 40, Boolean Unite, Flip (upward), OK", f"'{field}' = 40 mm, '{rev}' on, MB2 = OK",
                               self.l_ref(2), f"; height {bb.ZMin:.1f} .. {bb.ZMax:.1f} mm. Features in a Body "
                               "unite by themselves (no Boolean option)")
        if not ok:
            raise RuntimeError("boss wrong")
        self.wait = 600

    def l_bore(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 40) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, the top face of the cylinder", f"select {face} + ribbon '{where} > Extrude (Subtract)'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  "the subtracting extrude is its own button")
        self._l_bore_face = face
        self.wait = 1500

    def l_bore_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on the cylinder top")
        centre = App.Vector(0, 25, 40)
        origin = sk.getGlobalPlacement().multVec(App.Vector(0, 0, 0))
        at_origin = (origin - centre).Length < 1e-6
        c, r = self.g2s_mm(sk, 0, 25, 40), self.g2s_mm(sk, 9, 25, 40)
        _, tool, n, ended = self.draw_clicks("O", [c, r])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), 15.0)])
        if at_origin:
            sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
            how = "centre on the sketch origin (FreeCAD puts it at the face's centre too)"
        else:
            tip = self.body().Tip
            arc = next(f"Edge{i}" for i, e in enumerate(tip.Shape.Edges, start=1)
                       if hasattr(e.Curve, "Radius") and abs(e.Curve.Radius - 25) < 1e-6
                       and abs(e.Curve.Center.z - 40) < 1e-6)
            sk.addExternal(tip.Name, arc)
            sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -3, 3))
            how = f"centre tied to the cylinder's edge ({arc}): the sketch origin is not at the centre"
        sk.addConstraint(Sketcher.Constraint("Diameter", 0, 30.0))
        App.ActiveDocument.recompute()
        self.step("Circle on the sketch origin, MB2; diameter 30", "O key + 2 MB1 clicks + MB2; diameter applied",
                  SAME if tool and n >= 1 and ended and at_origin else (DIFFERS if tool and n >= 1 else FAIL),
                  f"{how}; DoF {sk.DoF}")
        self.wait = 300

    def l_bore_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def l_bore_dialog(self):
        self.wait_dialog("l_bore_dialog")
        mode = self.choose("through all", "mode")
        self.mb2_click()
        self.check_volume("Boolean Subtract, Through All, Flip (downward), OK", f"'{mode}', MB2 = OK", self.l_ref(3),
                          "; FreeCAD's subtracting extrude goes into the part without a flip")
        self.wait = 600

    def l_hole(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - 15) < 1e-6
                            and f.CenterOfMass.x > 25)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Hole")
        self.step("Hole (a placed feature): Simple, a point on the base's top face",
                  f"select {face} + ribbon '{where} > Hole'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL,
                  "FreeCAD's Hole drills at circle centres in a sketch on the face: not placed without a sketch")
        self.wait = 1500

    def l_hole_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no hole sketch")
        x, y = self.L_HOLE
        c, r = self.g2s_mm(sk, x, y, 15), self.g2s_mm(sk, x + 6, y, 15)
        _, tool, n, ended = self.draw_clicks("O", [c, r])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), self.L_R_HOLE)])
        self.step("Location dimensions 25 and 30", "O key + 2 MB1 clicks + MB2; centre placed by values",
                  DIFFERS if tool and n >= 1 else FAIL, f"centre at ({x:g}, {y:g}): 25 from the right edge, on "
                  "the slot's centre line. NX adds the two location dimensions by itself")
        self.wait = 300

    def l_hole_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def l_hole_dialog(self):
        self.wait_dialog("l_hole_dialog")
        dia = self.set_quantity("diameter", 2 * self.L_R_HOLE)
        depth = self.choose("through", "depthtype")
        self.mb2_click()
        self.check_volume("Diameter 20, Depth Limit = Through Body, OK", f"'{dia}' = 20 mm, '{depth}', MB2 = OK",
                          self.l_ref(4))
        self._l_hole = self.body().Tip
        self.wait = 600

    def l_slot(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).x - 1) < 1e-6 and abs(f.CenterOfMass.x - 75) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, the right vertical face of the base", f"select {face} + ribbon '{where} > "
                  "Extrude (Subtract)'", DIFFERS if b is not None and self.edited_sketch() is not None else FAIL, "")
        self.wait = 1500

    def l_slot_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no slot sketch")
        tip = self.body().Tip
        edges = [(tip, f"Edge{i}") for i, e in enumerate(tip.Shape.Edges, start=1)
                 if all(abs(v.Point.x - 75) < 1e-6 for v in e.Vertexes) and abs(e.Length - 50) < 1e-6]
        edges.sort(key=lambda oe: -oe[0].Shape.getElement(oe[1]).Vertexes[0].Point.z)      # top, then bottom
        self.frame_sketch(sk, *self.g2s_mm(sk, 75, 25, 7.5), 90)
        first = self.project_edges(sk, [(75, 42, 15), (75, 42, 0)], edges,
                                   "More > Project Curve: the top and bottom edges, OK")
        y0, w = self.L_SLOT
        corners = [self.g2s_mm(sk, 75, y, z) for (y, z) in ((y0, 0), (y0 + w, 0), (y0 + w, 15), (y0, 15))]
        _, tool, n, ended = self.draw_clicks("R", [corners[0], corners[2]])
        P = [App.Vector(u, v, 0) for (u, v) in corners]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        # top and bottom lines on the projected edges (the book aligns the rectangle to them)
        top_bottom = []
        for k in range(2):
            g = sk.ExternalGeo[2 + first + k]
            top_bottom.append((-3 - first - k, g))
        for line in (0, 2):
            y_line = sk.Geometry[line].StartPoint.y
            ext = min(top_bottom, key=lambda t: abs(t[1].StartPoint.y - y_line))[0]
            sk.addConstraint(Sketcher.Constraint("PointOnObject", line, 1, ext))
            sk.addConstraint(Sketcher.Constraint("PointOnObject", line, 2, ext))
        App.ActiveDocument.recompute()
        self.step("Rectangle aligned to the top and bottom edges; dimensions 15 and 20",
                  "R key + 2 MB1 clicks + MB2; on the projected edges; values applied",
                  SAME if tool and n >= 4 and ended else FAIL,
                  f"15 from the front edge, 20 wide, full height; DoF {sk.DoF}")
        before, after = self.to_reference(sk, first, 2)
        self.step("(FreeCAD) the projected edges to reference", "ribbon 'Convert To/From Reference'",
                  DIFFERS if after == 4 else FAIL, f"profile edges {before} -> {after}")
        self.wait = 300

    def l_slot_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def l_slot_dialog(self):
        self.wait_dialog("l_slot_dialog")
        mode = self.choose("to first", "mode")
        self.mb2_click()
        App.ActiveDocument.recompute()
        want = self.l_ref(4) - self.l_ref(5)
        got = self._l_hole.Shape.Volume - self.solid_volume()
        self._l_slot = self.body().Tip
        if abs(got - want) < 1e-3 * want:
            self.check_volume("Subtract, End = Until Next (into the hole), OK", f"'{mode}', MB2 = OK", self.l_ref(5))
            self._l_slot_ok = True
        else:
            self.step("Subtract, End = Until Next (into the hole), OK", f"'{mode}' (FreeCAD's Until Next), MB2 = OK",
                      LIMIT, f"removed {got:.1f} mm^3 of the {want:.1f} the slot holds: FreeCAD 1.1.4's 'To first' "
                      "stops 1 mm into the part instead of at the hole's wall (measured headless too, the same with "
                      "'Up to face' on the hole's face); NX stops at the next face. Workaround next")
            self._l_slot_ok = False
        self.wait = 400

    def l_slot_fix(self):
        if self._l_slot_ok:
            self.wait = 100
            return
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{self._l_slot.Name}.")
        b, where = self.click_ribbon("Edit Parameters")
        self._l_where = where
        self.wait = 1500

    def l_slot_fix_dialog(self):
        if self._l_slot_ok:
            self.wait = 100
            return
        self.wait_dialog("l_slot_fix_dialog")
        mode = self.choose("dimension", "mode")
        field = self.set_quantity("length", 75 - self.L_HOLE[0])
        self.mb2_click()
        self.check_volume("Workaround: the slot's depth = 25 (to the hole's axis)", f"slot selected + ribbon "
                          f"'{self._l_where} > Edit Parameters', '{mode}', '{field}' = 25 mm, MB2 = OK",
                          self.l_ref(5), "; the same part as NX's Until Next here, because the slot is as wide as "
                          "the hole and on its centre line")
        self.wait = 600

    def l_show(self):
        self.fit()

    def l_save(self):
        self.show("L_locator")
        self.check_drawn("The finished Locator is shown in the graphics window", "L_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "Locator.FCStd"))

    # ---------------------------------------------------------- tutorial M
    # The U-Bracket (Shih ch. 7, inches typed in mm): parent/child relations. A base plate with two
    # holes, a half-round main body across it, a 2.0 x 1.0 rectangular cut under it, a Ø0.25 drill
    # sketched on the cut's face; then Suppress, the drill's dependence on the cut, the BORN way
    # (the drill sketched on the datum XY plane instead) and a circular cut R1.25 replacing the
    # rectangular one. The text gives 0.5, Ø0.75, ±1.25, 2.0 x 1.0, Ø0.25 and R1.25; the drawing
    # chapter gives 5 and 2.5. The base's end radius (R1.00) and the body's radius (R1.75) are
    # NotebookLM's reading of the figures (uncited).
    M_C, M_R, M_HOLE, M_T = 2.5, 1.0, 0.75, 0.5          # centres at ±2.5, end radius, holes, thickness
    M_BODY_R, M_BODY_W = 1.75, 1.25                      # body radius, half width (extruded -1.25 .. 1.25)
    M_RECT, M_DRILL, M_CIRC = (2.0, 1.0), 0.25, 1.25

    def m_ref(self, body=True, rect=False, drill_on_cut=False, drill_born=False, circ=False, hole=None):
        """The same bracket built with the Part API (inches in, mm out)."""
        import Part
        V = App.Vector
        s, r, c, t = IN, self.M_R, self.M_C, self.M_T
        hole = self.M_HOLE if hole is None else hole
        base = Part.makeBox(2 * c * s, 2 * r * s, t * s, V(-c * s, -r * s, 0))
        for x in (-c, c):
            base = base.fuse(Part.makeCylinder(r * s, t * s, V(x * s, 0, 0)))
        for x in (-c, c):
            base = base.cut(Part.makeCylinder(hole / 2 * s, t * s, V(x * s, 0, 0)))
        shape = base
        if body:
            half = Part.makeCylinder(self.M_BODY_R * s, 2 * self.M_BODY_W * s, V(0, -self.M_BODY_W * s, 0), V(0, 1, 0))
            half = half.common(Part.makeBox(4 * s, 4 * s, 4 * s, V(-2 * s, -2 * s, 0)))
            shape = shape.fuse(half)
        if rect:
            w, h = self.M_RECT
            shape = shape.cut(Part.makeBox(w * s, 10 * s, h * s, V(-w / 2 * s, -5 * s, 0)))
        if drill_on_cut:
            shape = shape.cut(Part.makeCylinder(self.M_DRILL / 2 * s, 5 * s, V(0, 0, self.M_RECT[1] * s)))
        if drill_born:
            shape = shape.cut(Part.makeCylinder(self.M_DRILL / 2 * s, 5 * s, V(0, 0, 0)))
        if circ:
            shape = shape.cut(Part.makeCylinder(self.M_CIRC * s, 10 * s, V(0, -5 * s, 0), V(0, 1, 0)))
        return shape.Volume

    def add_constraints(self, sk, cons):
        """Add constraints one by one; one the solver calls redundant (implied already) is left out."""
        skipped = []
        for k in cons:
            i = sk.addConstraint(k)
            if sk.solve() != 0:
                sk.delConstraint(i)
                skipped.append(k.Type)
        return skipped

    def m_feature_select(self, feat):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{feat.Name}.")
        QtWidgets.QApplication.processEvents()

    def m_new(self):
        self.tutorial = "M: The U-Bracket, parent/child relations (book in inches, typed in mm)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def m_extrude(self):
        self.wait_for("m: new part's Body", lambda: self.body() is not None)
        self.step("File > New, Model template, name U-Bracket", "Ctrl+N",
                  SAME if set(App.listDocuments()) - self._docs_before and self.body() else FAIL,
                  "named at the first save")
        self.units_step()
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def m_plane(self):
        picked = self.pick_in_feature_list("XY")
        self.mb2_click()
        self.step("Extrude, the XY plane of the WCS", "X key, plane row + MB2", SAME if picked else FAIL,
                  f"picked {picked}")
        self.wait = 1500

    def m_profile(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch in edit")
        s, c, r = IN, self.M_C, self.M_R
        pts = [(-c * s, -r * s), (c * s, -r * s), (c * s, r * s), (-c * s, r * s)]
        _, tool, n, ended = self.draw_clicks("Z", pts + [pts[0]])
        self.step("Profile: two horizontal lines and two tangent arcs, MB2 twice",
                  "Z key + MB1 clicks + MB2; the arcs and sizes applied", DIFFERS if tool and n >= 3 else FAIL,
                  f"{n} curves clicked; NX switches Profile to an arc by dragging MB1, FreeCAD's polyline by "
                  "pressing M while drawing")
        V = App.Vector
        geos = [Part.LineSegment(V(-c * s, -r * s, 0), V(c * s, -r * s, 0)),
                Part.LineSegment(V(c * s, r * s, 0), V(-c * s, r * s, 0)),
                Part.ArcOfCircle(Part.Circle(V(c * s, 0, 0), V(0, 0, 1), r * s), -math.pi / 2, math.pi / 2),
                Part.ArcOfCircle(Part.Circle(V(-c * s, 0, 0), V(0, 0, 1), r * s), math.pi / 2, 3 * math.pi / 2)]
        self.add_geometry(sk, geos)
        # circles on the arcs' centres (the book: O, two clicks each); the clicked ones are replaced
        cn = []
        for x in (c, -c):
            _, ctool, k, cended = self.draw_clicks("O", [(x * s, 0), ((x + 0.3) * s, 0)])
            cn.append(ctool and cended)
        for g in range(len(sk.Geometry) - 1, 3, -1):
            sk.delGeometry(g)
        for x in (c, -c):
            sk.addGeometry(Part.Circle(V(x * s, 0, 0), V(0, 0, 1), self.M_HOLE / 2 * s), False)
        C = Sketcher.Constraint
        skipped = self.add_constraints(sk, [
            C("Horizontal", 0), C("Horizontal", 1), C("Tangent", 0, 2, 2, 1), C("Tangent", 2, 2, 1, 1),
            C("Tangent", 1, 2, 3, 1), C("Tangent", 3, 2, 0, 1), C("Coincident", 4, 3, 2, 3),
            C("Coincident", 5, 3, 3, 3), C("Equal", 2, 3), C("Equal", 4, 5), C("Radius", 2, r * s),
            C("Diameter", 4, self.M_HOLE * s), C("DistanceX", 3, 3, 2, 3, 2 * c * s),
            C("DistanceX", -1, 1, 2, 3, c * s), C("PointOnObject", 2, 3, -1)])
        App.ActiveDocument.recompute()
        self.info["M base sketch: implied constraints left out"] = skipped
        dof, fully, msg = self.sk_state(sk)
        self.step("Two circles on the arcs' centres; dimensions (Equal Radius if needed)",
                  "O key + 2 MB1 clicks + MB2, twice; centres, Equal and the sizes applied",
                  SAME if all(cn) and fully else (DIFFERS if all(cn) else FAIL),
                  f"solver '{msg}' ({dof} DoF); R1.00 ends 5.00 apart, Ø0.75 holes, centred on the origin")
        self.wait = 300

    def m_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def m_extrude_dialog(self):
        self.wait_dialog("m_extrude_dialog")
        field = self.set_quantity("length", self.M_T * IN)
        self.mb2_click()
        ok = self.check_volume("Extrude 0.5 in, OK", f"Ctrl+Q, '{field}' = 12.7 mm, MB2 = OK", self.m_ref(body=False))
        self._m_base = self.body().Tip
        if not ok:
            raise RuntimeError("base wrong")
        self.wait = 600

    def m_body(self):
        Gui.Selection.clearSelection()
        self.key("X")
        self.wait = 1500

    def m_body_plane(self):
        picked = self.pick_in_feature_list("XZ")
        self.mb2_click()
        self.step("Extrude, the XZ plane of the datum coordinate system", "X key, plane row + MB2",
                  SAME if picked else FAIL, f"picked {picked}")
        self.wait = 1500

    def m_body_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on XZ")
        R = self.M_BODY_R
        c, a, b = self.g2s(sk, 0, 0, 0), self.g2s(sk, R, 0, 0), self.g2s(sk, -R, 0, 0)
        top = self.g2s(sk, 0, 0, R)
        _, tool, n, ended = self.draw_clicks("A", [c, a, top])
        _, ltool, ln, lended = self.draw_clicks("L", [b, a])
        V = App.Vector
        # the half above the X axis, whichever way the sketch's axes run: 90° either side of 'up'
        up = math.atan2(top[1] - c[1], top[0] - c[0])
        arc = Part.ArcOfCircle(Part.Circle(V(*c, 0), V(0, 0, 1), R * IN), up - math.pi / 2, up + math.pi / 2)
        self.add_geometry(sk, [arc, Part.LineSegment(arc.EndPoint, arc.StartPoint)])
        C = Sketcher.Constraint
        for k in (C("Coincident", 0, 3, -1, 1), C("Coincident", 1, 1, 0, 2), C("Coincident", 1, 2, 0, 1),
                  C("PointOnObject", 0, 1, -1), C("PointOnObject", 0, 2, -1), C("Radius", 0, R * IN)):
            sk.addConstraint(k)
        App.ActiveDocument.recompute()
        dof, fully, msg = self.sk_state(sk)
        self.step("Arc: centre on the sketch origin, end points on the edge; Line closing it; one radius "
                  "dimension: fully constrained", "A key + 3 MB1 clicks + MB2, L key + 2 clicks + MB2; R1.75",
                  SAME if tool and ltool and fully else FAIL,
                  f"solver '{msg}' ({dof} DoF); the book asks why one dimension is enough: the centre and the "
                  "end points sit on the datum axes")
        self.wait = 300

    def m_body_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def m_body_dialog(self):
        self.wait_dialog("m_body_dialog")
        mode = self.choose("two sided", "sidesmode")
        f1 = self.set_quantity("lengthEdit", self.M_BODY_W * IN)
        f2 = self.set_quantity("lengthEdit2", self.M_BODY_W * IN)
        self.mb2_click()
        App.ActiveDocument.recompute()
        bb = self.body().Shape.BoundBox
        ok = self.check_volume("Limits: Start -1.25, End 1.25, Boolean Unite, OK",
                               f"'{mode}', '{f1}' = '{f2}' = 31.75 mm, MB2 = OK", self.m_ref(),
                               f"; across {bb.YMin:.2f} .. {bb.YMax:.2f} mm. NX's two limits are FreeCAD's 'Two "
                               "sided' (a length each way); features in a Body unite by themselves")
        self._m_main = self.body().Tip
        if not ok:
            raise RuntimeError("main body wrong")
        self.wait = 600

    def m_front_face(self, tip):
        return self.face_of(tip, lambda f: abs(f.normalAt(0, 0).y + 1) < 1e-6
                            and abs(f.CenterOfMass.y + self.M_BODY_W * IN) < 1e-6)

    def m_rect(self):
        tip = self.body().Tip
        face = self.m_front_face(tip)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, the front vertical face", f"select {face} + ribbon '{where} > Extrude (Subtract)'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL, "")
        self.wait = 1500

    def m_rect_sketch(self):
        import Part
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on the front face")
        w, h = self.M_RECT
        y = -self.M_BODY_W
        corners = [self.g2s(sk, x, y, z) for (x, z) in ((-w / 2, 0), (w / 2, 0), (w / 2, h), (-w / 2, h))]
        _, tool, n, ended = self.draw_clicks("R", [corners[0], corners[2]])
        P = [App.Vector(u, v, 0) for (u, v) in corners]
        self.add_geometry(sk, [Part.LineSegment(P[i], P[(i + 1) % 4]) for i in range(4)])
        self.step("Rectangle, dimensions 2.0 x 1.0", "R key + 2 MB1 clicks + MB2; sizes applied",
                  SAME if tool and n >= 4 and ended else FAIL, "centred on the body, on the base plane")
        self.wait = 300

    def m_rect_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def m_rect_dialog(self):
        self.wait_dialog("m_rect_dialog")
        mode = self.choose("through all", "mode")
        self.mb2_click()
        ok = self.check_volume("Subtract, Through All both ways, OK", f"'{mode}', MB2 = OK", self.m_ref(rect=True),
                               "; from the front face one way is all of it")
        self._m_rect = self.body().Tip
        if not ok:
            raise RuntimeError("rectangular cut wrong")
        self.wait = 600

    def m_drill(self):
        tip = self.body().Tip
        face = self.face_of(tip, lambda f: abs(f.normalAt(0, 0).z + 1) < 1e-6
                            and abs(f.CenterOfMass.z - self.M_RECT[1] * IN) < 1e-6)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, the underside face of the cut", f"select {face} + ribbon '{where} > Extrude (Subtract)'",
                  DIFFERS if b is not None and self.edited_sketch() is not None else FAIL, "")
        self.wait = 1500

    def m_drill_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no drill sketch")
        origin = next(o for o in self.body().Origin.OriginFeatures if o.TypeId == "App::Point")
        n0 = self.ext_count(sk)
        projected = None
        for sub in ("", "Vertex1"):
            try:
                sk.addExternal(origin.Name, sub)
                App.ActiveDocument.recompute()
                if self.ext_count(sk) > n0:
                    projected = sub
                    break
            except Exception as e:
                self.info.setdefault("M origin projection", []).append(f"{sub!r}: {e}")
        c = self.g2s(sk, 0, 0, self.M_RECT[1])
        _, tool, n, ended = self.draw_clicks("O", [c, (c[0] + 0.3 * IN, c[1])])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), self.M_DRILL / 2 * IN)])
        if projected is not None:
            sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -3 - n0, 1))
        sk.addConstraint(Sketcher.Constraint("Diameter", 0, self.M_DRILL * IN))
        App.ActiveDocument.recompute()
        self.step("More > Project Curve: the datum origin; Circle Ø0.25 on it", "the origin point projected (API: "
                  "it is hidden in the view); O key + 2 clicks + MB2; Ø applied",
                  DIFFERS if tool and n >= 1 and projected is not None else (DIFFERS if tool else FAIL),
                  f"origin projected: {projected is not None}; NX picks the datum origin in the graphics window, "
                  "FreeCAD's origin point is hidden unless the Body's origin is shown")
        self.wait = 300

    def m_drill_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def m_drill_dialog(self):
        self.wait_dialog("m_drill_dialog")
        mode = self.choose("through all", "mode")
        self.mb2_click()
        ok = self.check_volume("Subtract, Through All, OK", f"'{mode}', MB2 = OK",
                               self.m_ref(rect=True, drill_on_cut=True))
        self._m_drill = self.body().Tip
        if not ok:
            raise RuntimeError("centre drill wrong")
        self.wait = 600

    def m_rename(self):
        errs = [self.rename(f, n) for f, n in ((self._m_base, "Base"), (self._m_main, "Main-Body"),
                                               (self._m_rect, "Rect-Cut"), (self._m_drill, "CenterDrill"))]
        bad = [e for e in errs if e]
        self.step("Rename the features: Base, Main-Body, Rect-Cut, CenterDrill", "select + F2, type, Enter (4 times)",
                  DIFFERS if not bad else FAIL, "; ".join(bad) or "NX: click the name twice; FreeCAD: F2")

    def parents(self, feat):
        """What a feature was built from: its sketch's attachment and the feature it was cut from."""
        prof = feat.Profile[0] if getattr(feat, "Profile", None) else None
        att = [o.Label for o, _ in getattr(prof, "AttachmentSupport", []) or []] if prof is not None else []
        base = getattr(feat, "BaseFeature", None)
        return att, base.Label if base is not None else None

    def m_dependencies(self):
        att, base = self.parents(self._m_drill)
        self.step("Part Navigator > Dependencies: the parents of CenterDrill", "the feature's links (sketch "
                  "attachment, base feature)", DIFFERS if "Rect-Cut" in att else FAIL,
                  f"sketched on {att}, cut from {base}: Rect-Cut is its parent, as in the book. FreeCAD shows these "
                  "in the feature's properties (Attachment, Base Feature) rather than a Dependencies panel")

    def m_suppress_rect(self):
        self.m_feature_select(self._m_rect)
        b, where = self.click_ribbon("Suppress")
        self.info["M suppress button"] = {"command": getattr(b, "command", None), "selection": [
            (s.ObjectName, s.SubElementNames) for s in Gui.Selection.getSelectionEx()],
            "commands": [c for c in Gui.listCommands() if "uppress" in c.lower() or "freeze" in c.lower()]}
        App.ActiveDocument.recompute()
        states = self.doc_states()
        sketch = self._m_drill.Profile[0]
        broken = sketch.Label in states and "Invalid" in states[sketch.Label][0]
        self.step("Suppress Rect-Cut: NX warns that CenterDrill cannot be placed", f"Rect-Cut selected + ribbon "
                  f"'{where} > Suppress'", DIFFERS if b is not None and self._m_rect.Suppressed and broken else FAIL,
                  f"Rect-Cut suppressed {self._m_rect.Suppressed}; FreeCAD cannot place the child either: its sketch "
                  f"says '{states.get(sketch.Label, ('', ''))[1]}'. No message box: the error marks the sketch in the "
                  f"Part Navigator, and the part keeps its last shape (volume {self.solid_volume():.1f} mm^3). "
                  "NXStyle's Suppress is new: FreeCAD 1.1 has the property but no command (its Freeze is different)")
        self.wait = 600

    def doc_states(self):
        """Objects not up to date (FreeCAD's 'Touched', 'Invalid', 'Error') with their messages."""
        out = {}
        for o in App.ActiveDocument.Objects:
            st = [s for s in o.State if s in ("Touched", "Invalid", "Error")]
            if st:
                out[o.Label] = (st, o.getStatusString())
        return out

    def m_suppress_drill(self):
        self.info["M states after suppressing Rect-Cut"] = self.doc_states()
        self.m_feature_select(self._m_drill)
        b, where = self.click_ribbon("Suppress")
        App.ActiveDocument.recompute()
        states = self.doc_states()
        self.info["M states after suppressing CenterDrill"] = states
        ok = self._m_drill.Suppressed and abs(self.solid_volume() - self.m_ref()) < 1e-3 * self.m_ref()
        sketch = self._m_drill.Profile[0]
        stuck = self._m_drill.Suppressed and sketch.Label in states
        self.step("Suppress CenterDrill as well: the part shows the plate and the body only",
                  f"CenterDrill selected + ribbon '{where} > Suppress'", SAME if ok else (LIMIT if stuck else FAIL),
                  f"volume {self.solid_volume():.1f} mm^3 (the plate and the body: {self.m_ref():.1f})" +
                  ("" if ok else f". FreeCAD 1.1.4 still recomputes the suppressed drill's sketch, which cannot find "
                   f"its face, and stops there: {', '.join(states)} stay out of date. NX leaves a suppressed child "
                   "alone. Unsuppressing the parent (the book's next steps) brings the model back"))
        self.wait = 600

    def m_unsuppress_drill(self):
        self.m_feature_select(self._m_drill)
        b, where = self.click_ribbon("Suppress")
        App.ActiveDocument.recompute()
        rect_back = not self._m_rect.Suppressed
        self.step("Unsuppress CenterDrill: NX brings its parent Rect-Cut back too", f"CenterDrill selected + "
                  f"ribbon '{where} > Suppress' (a toggle)", DIFFERS if not self._m_drill.Suppressed else FAIL,
                  f"Rect-Cut back by itself: {rect_back}. FreeCAD unsuppresses only the selected feature")
        if not rect_back:
            self.m_feature_select(self._m_rect)
            self.click_ribbon("Suppress")
            App.ActiveDocument.recompute()
        self.check_volume("Unsuppress Rect-Cut too: both back", "Rect-Cut selected + ribbon 'Suppress'",
                          self.m_ref(rect=True, drill_on_cut=True))
        self.wait = 600

    def m_delete_drill(self):
        self.m_feature_select(self._m_drill)
        name, sketch = self._m_drill.Name, self._m_drill.Profile[0]
        self.modals.accept = True
        self.key("Delete")
        QtWidgets.QApplication.processEvents()
        self.modals.accept = False
        App.ActiveDocument.recompute()
        gone = App.ActiveDocument.getObject(name) is None
        left = App.ActiveDocument.getObject(sketch.Name) is not None if gone else None
        if left:
            App.ActiveDocument.removeObject(sketch.Name)       # NX deletes the feature's sketch with it
            App.ActiveDocument.recompute()
        self.check_volume("Delete CenterDrill (MB3 > Delete)", "CenterDrill selected + Delete key"
                          + ("; its sketch deleted too" if left else ""), self.m_ref(rect=True),
                          f"; feature gone {gone}; FreeCAD keeps the feature's sketch ({left}), NX removes it")
        self.wait = 600

    def m_born(self):
        xy = next(o for o in self.body().Origin.OriginFeatures if o.Role == "XY_Plane")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(App.ActiveDocument.Name, self.body().Name, f"{self.body().Origin.Name}.{xy.Name}.")
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("A different approach (BORN): Extrude on the datum XY plane", f"XY plane selected + ribbon "
                  f"'{where} > Extrude (Subtract)'", DIFFERS if b is not None and self.edited_sketch() is not None
                  else FAIL, "")
        self.wait = 1500

    def m_born_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no sketch on XY")
        _, tool, n, ended = self.draw_clicks("O", [(0, 0), (0.3 * IN, 0)])
        self.add_geometry(sk, [Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), self.M_DRILL / 2 * IN)])
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Diameter", 0, self.M_DRILL * IN))
        App.ActiveDocument.recompute()
        self.step("Circle Ø0.25 on the datum origin", "O key + 2 MB1 clicks + MB2; on the origin, Ø applied",
                  SAME if tool and n >= 1 and ended else FAIL, f"DoF {sk.DoF}")
        self.wait = 300

    def m_born_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def m_born_dialog(self):
        self.wait_dialog("m_born_dialog")
        mode = self.choose("through all", "mode")
        rev = self.checkbox("reverse")
        self.mb2_click()
        ok = self.check_volume("Subtract, Through All, OK", f"'{mode}', '{rev}' on (up from the plane), MB2 = OK",
                               self.m_ref(rect=True, drill_born=True),
                               "; FreeCAD cuts away from the plane's normal by default, so it is reversed to go up")
        self._m_born = self.body().Tip
        if ok:
            self.rename(self._m_born, "CenterDrill")
        self.wait = 600

    def m_born_check(self):
        att, base = self.parents(self._m_born)
        self.m_feature_select(self._m_rect)
        b, where = self.click_ribbon("Suppress")
        App.ActiveDocument.recompute()
        ok = self._m_rect.Suppressed and self._m_born.isValid() and \
            abs(self.solid_volume() - self.m_ref(drill_born=True)) < 1e-3 * self.m_ref(drill_born=True)
        self.step("Dependencies: the new drill's parents are the XY plane and the base; Suppress Rect-Cut: the "
                  "drill stays", f"Rect-Cut selected + ribbon '{where} > Suppress'", SAME if ok else FAIL,
                  f"sketched on {att}; drill valid {self._m_born.isValid()}; volume {self.solid_volume():.1f} mm^3 "
                  f"(expected {self.m_ref(drill_born=True):.1f}). In FreeCAD each feature is cut from the one "
                  f"before ({base}); a suppressed feature passes its input on, so that link does not break")
        self.wait = 600

    def m_circ(self):
        tip = self.body().Tip
        face = self.m_front_face(tip)
        self.select_sub(tip, face)
        b, where = self.click_ribbon("Extrude (Subtract)")
        self.step("Extrude, the front vertical face (circular cut)", f"select {face} + ribbon '{where} > "
                  "Extrude (Subtract)'", DIFFERS if b is not None and self.edited_sketch() is not None else FAIL, "")
        self.wait = 1500

    def m_circ_sketch(self):
        import Part
        import Sketcher
        sk = self.edited_sketch()
        if sk is None:
            raise RuntimeError("no circular cut sketch")
        c = self.g2s(sk, 0, -self.M_BODY_W, 0)
        _, tool, n, ended = self.draw_clicks("O", [c, (c[0] + 0.8 * IN, c[1])])
        self.add_geometry(sk, [Part.Circle(App.Vector(*c, 0), App.Vector(0, 0, 1), self.M_CIRC * IN)])
        sk.addConstraint(Sketcher.Constraint("Radius", 0, self.M_CIRC * IN))
        App.ActiveDocument.recompute()
        self.step("Circle R1.25 centred on the datum origin", "O key + 2 MB1 clicks + MB2; R applied",
                  SAME if tool and n >= 1 and ended else FAIL, "the book's text says 'rectangle', its figure and "
                  "the design change a circle of radius 1.25")
        self.wait = 300

    def m_circ_finish(self):
        self.key("Ctrl+Q")
        self.wait = 1800

    def m_circ_dialog(self):
        self.wait_dialog("m_circ_dialog")
        mode = self.choose("through all", "mode")
        self.mb2_click()
        self.check_volume("Subtract, Through All, OK: the bracket with a round opening",
                          f"'{mode}', MB2 = OK", self.m_ref(drill_born=True, circ=True),
                          "; two design options now live in one model (Rect-Cut suppressed)")
        self._m_circ = self.body().Tip
        self.wait = 600

    def m_show(self):
        self.fit()

    def m_save(self):
        self.show("M_u_bracket")
        self.check_drawn("The U-Bracket is shown in the graphics window", "M_live_check.png")
        App.ActiveDocument.saveAs(os.path.join(OUT, "U-Bracket.FCStd"))
        self._m_doc = App.ActiveDocument

    # ---------------------------------------------------------- tutorial N
    # The U-Bracket drawing (Shih ch. 8): an A-size, third-angle sheet changed to B size; front, top and
    # isometric views; hidden lines; ANSI horizontal text; the model's dimensions on the views; center
    # marks; a radial dimension; two decimals; then the associative change Ø0.750 -> Ø0.625 in the model
    # that the drawing must follow. Runs on the U-Bracket from tutorial M (in the same session).
    def n_template(self, name):
        import glob
        root = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")
        hits = glob.glob(os.path.join(root, "**", name), recursive=True)
        return hits[0] if hits else None

    def n_body(self):
        return next(o for o in self._m_doc.Objects if o.isDerivedFrom("PartDesign::Body"))

    def n_new_view(self, direction, xdir, x, y):
        """Body selected + Base View, MB2 on the sheet; the view's direction set (TechDraw asks no view list)."""
        before = {v.Name for v in self._n_page.Views}
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self._m_doc.Name, self.n_body().Name)
        b, where = self.click_ribbon("Base View")
        QtWidgets.QApplication.processEvents()
        self.wait_for("n: base view", lambda: any(v.Name not in before for v in self._n_page.Views), 4000)
        new = [v for v in self._n_page.Views if v.Name not in before and v.isDerivedFrom("TechDraw::DrawViewPart")]
        v = new[-1] if new else None
        if v is not None:
            v.Direction, v.XDirection = App.Vector(*direction), App.Vector(*xdir)
            v.ScaleType = "Custom"
            v.Scale = 1.0
            v.X, v.Y = x, y
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        return v, where

    def n_wait_edges(self, view, what):
        return self.wait_for(f"n: {what} hidden-line worker", lambda: len(view.getVisibleEdges()) > 0, 15000)

    def n_drafting(self):
        self.tutorial = "N: The U-Bracket drawing, associative (book in inches, typed in mm)"
        App.setActiveDocument(self._m_doc.Name)
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def n_sheet(self):
        wb = Gui.activeWorkbench().name()
        self.step("File > Drafting", "Ctrl+Shift+D", SAME if wb == "TechDrawWorkbench" else FAIL, wb)
        b, where = self.click_ribbon("New Sheet")
        QtWidgets.QApplication.processEvents()
        page = self.newest("TechDraw::DrawPage")
        a = self.n_template("ANSIA_Landscape.svg")
        if page is not None and a:
            page.Template.Template = a
            page.ProjectionType = next(e for e in page.getEnumerationsOfProperty("ProjectionType") if "third" in e.lower())
            page.Scale = 1.0
        App.ActiveDocument.recompute()
        self._n_page = page
        self.step("Sheet: Inches, Third Angle, A-8.5X11, scale 1:1, OK", f"ribbon '{where} > New Sheet'; the sheet's "
                  "template, projection and scale", DIFFERS if page is not None and a else FAIL,
                  f"template {os.path.basename(a or '?')}, projection {getattr(page, 'ProjectionType', '?')}. NX asks "
                  "in one Sheet dialog; FreeCAD's New Sheet uses the default template, and size, projection and scale "
                  "are the sheet's properties. Units follow the preferences (mm here)")
        self.wait = 1200

    def n_base(self):
        v, where = self.n_new_view((0, -1, 0), (1, 0, 0), 120.0, 85.0)
        if v is not None:
            v.HardHidden = True
            vo = v.ViewObject
            for prop, val in (("LineWidth", 0.7), ("HiddenWidth", 0.35)):
                if prop in vo.PropertiesList:
                    setattr(vo, prop, val)
            App.ActiveDocument.recompute()
            self.n_wait_edges(v, "front")
        self._n_front = v
        self.step("Base View: Front; View Style: hidden lines dashed 0.35, visible lines 0.70; place it low on the "
                  "sheet", f"body selected + ribbon '{where} > Base View', MB2; the view's style properties",
                  DIFFERS if v is not None and len(v.getVisibleEdges()) > 0 else FAIL,
                  f"{len(v.getVisibleEdges()) if v else 0} visible, {len(v.getHiddenEdges()) if v else 0} hidden "
                  "edges. NX sets the style in the view's Settings dialog; TechDraw has Hard Hidden and the line "
                  "widths in the view's properties")
        self.wait = 600

    def n_top(self):
        v, where = self.n_new_view((0, 0, 1), (1, 0, 0), float(self._n_front.X), float(self._n_front.Y) + 95.0)
        if v is not None:
            v.HardHidden = True
            self.n_wait_edges(v, "top")
        self._n_top = v
        self.step("Projected Top view above the Front view", "a second Base View, direction Top, aligned above",
                  DIFFERS if v is not None and len(v.getVisibleEdges()) > 0 else FAIL,
                  "as in tutorials D and H: NX drags projected views off the base view; FreeCAD's Projected View is "
                  "a projection group, so a Base View looking down stands in, lined up with the front view")
        self.wait = 600

    def n_b_size(self):
        b = self.n_template("ANSIB_Landscape.svg")
        if b:
            self._n_page.Template.Template = b
        App.ActiveDocument.recompute()
        self.step("MB3 > Edit Sheet: B-11X17", "the sheet's template set to ANSI B", DIFFERS if b else FAIL,
                  f"template {os.path.basename(b or '?')}; the views keep their places. NX changes the size in Edit "
                  "Sheet; FreeCAD swaps the template")
        self.wait = 600

    def n_iso(self):
        s = 1 / math.sqrt(3)
        v, where = self.n_new_view((s, -s, s), (1 / math.sqrt(2), 1 / math.sqrt(2), 0),
                                   float(self._n_front.X) + 200.0, float(self._n_front.Y) + 105.0)
        if v is not None:
            self.n_wait_edges(v, "isometric")
        self._n_iso = v
        self.step("Base View: Isometric, to the right", f"body selected + ribbon '{where} > Base View', isometric "
                  "direction", SAME if v is not None and len(v.getVisibleEdges()) > 0 else FAIL, "")
        self.wait = 600

    def n_csys(self):
        origin = self.n_body().Origin
        shown = origin.ViewObject.Visibility
        self.step("Hide the Datum Coordinate System and the view's cross hair", "-", SAME if not shown else DIFFERS,
                  "nothing to hide: TechDraw draws only the solid, and NXStyle keeps the Body's origin hidden "
                  f"(origin shown: {shown})")

    def n_text(self):
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Dimensions")
        before = p.GetInt("StandardAndStyle", 0)
        p.SetInt("StandardAndStyle", 2)
        self.step("Drafting Preferences: dimension text Horizontal (ANSI)", "Preferences > TechDraw > Dimensions > "
                  "Standard and Style = ASME Inlined", DIFFERS,
                  f"was {['ISO Oriented', 'ISO Referencing', 'ASME Inlined', 'ASME Referencing'][before] if 0 <= before < 4 else before}")

    def n_vertices_at(self, view, points):
        """Cosmetic vertices at view points (view coordinates, mm); their vertex names."""
        for q in points:
            view.makeCosmeticVertex(App.Vector(q.x, q.y, 0))
        App.ActiveDocument.recompute()
        return self.vertices_at(view, points)

    def n_circles(self, view, radius_in):
        out = []
        for i, e in self.view_edges(view):
            if hasattr(e.Curve, "Radius") and abs(e.Curve.Radius - radius_in * IN) < 1e-3:
                out.append((i, e))
        return out

    def n_dim(self, view, kind, subs):
        before = {d.Name for d in self._n_page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension")}
        self.select_view_subs(view, subs)
        b, where = self.click_ribbon(kind)
        QtWidgets.QApplication.processEvents()
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        new = [d for d in self._n_page.Views if d.isDerivedFrom("TechDraw::DrawViewDimension") and d.Name not in before]
        return (new[-1] if new else None), where

    def n_feature_params(self):
        self.step("Command Finder > Feature Parameters: the model's dimensions on the views", "-", MISSING,
                  "TechDraw has no command that brings a feature's sketch dimensions onto a view; its dimensions "
                  "are reference dimensions measured from the view (next steps). NX's feature dimensions also drive "
                  "the model from the drawing")
        v = self._n_top
        holes = self.n_circles(v, self.M_HOLE / 2)
        names = self.n_vertices_at(v, [e.Curve.Center for _, e in holes]) if len(holes) == 2 else []
        made = []
        if len(names) == 2:
            d, where = self.n_dim(v, "Horizontal", names)
            if d is not None:
                d.X, d.Y = 0.0, 52.0                 # above the top view, clear of the plate
                made.append(("centres", d))
            # 2.5: from the left hole's centre to the drill's centre (the part's middle)
            drill = self.n_circles(v, self.M_DRILL / 2)
            if drill:
                mid = self.n_vertices_at(v, [drill[0][1].Curve.Center])
                left = min(names, key=lambda n: v.getVertexByIndex(int(n[6:])).Point.x)
                if mid:
                    d2, _ = self.n_dim(v, "Horizontal", [left, mid[0]])
                    if d2 is not None:
                        d2.X, d2.Y = -31.75, 38.0
                        made.append(("to the middle", d2))
            left_hole = min(holes, key=lambda h: h[1].Curve.Center.x)
            d3, _ = self.n_dim(v, "Diameter", [f"Edge{left_hole[0]}"])
            if d3 is not None:
                c = left_hole[1].Curve.Center
                d3.X, d3.Y = c.x - 22.0, c.y - 36.0              # below left, off the plate
                made.append(("hole", d3))
        App.ActiveDocument.recompute()
        self._n_dims = dict(made)
        vals = {k: round(float(d.getRawValue()) / IN, 3) for k, d in made}
        ok = len(made) == 3 and abs(vals.get("centres", 0) - 2 * self.M_C) < 1e-3 and \
            abs(vals.get("hole", 0) - self.M_HOLE) < 1e-3
        mm = {k: round(float(d.getRawValue()), 2) for k, d in made}
        self.step("Instead: reference dimensions on the top view (5.000, 2.500, Ø0.750 in)", "cosmetic vertices on "
                  "the hole centres; ribbon 'Horizontal' (twice) and 'Diameter'", DIFFERS if ok else FAIL,
                  f"measured (mm): {mm}, the book's 127.00, 63.50 and Ø19.05. TechDraw dimensions need vertices at "
                  "arc centres (as in tutorial H)")
        self.wait = 800

    def n_smooth(self):
        v = self._n_iso
        before = v.SmoothVisible
        v.SmoothVisible = False
        App.ActiveDocument.recompute()
        self.step("Isometric view: Settings > Smooth Edges off", "the view's Smooth Visible property",
                  SAME if before else DIFFERS,
                  "smooth (tangent) edges were shown, as in NX, and are now off" if before else
                  "smooth (tangent) edges were already off here; NX shows them by default")

    def n_arrows(self):
        d = self._n_dims.get("hole")
        vo = d.ViewObject if d is not None else None
        props = [p for p in (vo.PropertiesList if vo else []) if "arrow" in p.lower() or "flip" in p.lower()]
        flip = next((p for p in props if "flip" in p.lower()), None)
        if flip:
            setattr(vo, flip, True)
            App.ActiveDocument.recompute()
        self.step("Edit the diameter dimension: Arrow Out", f"the dimension's '{flip}' property" if flip else "-",
                  DIFFERS if flip else MISSING, f"arrow properties: {props}")

    def n_hide_show(self):
        dims = [d for k, d in self._n_dims.items() if k in ("centres", "hole")]
        Gui.Selection.clearSelection()
        for d in dims:
            Gui.Selection.addSelection(App.ActiveDocument.Name, d.Name)
        self.key("Ctrl+B")
        QtWidgets.QApplication.processEvents()
        hidden = [not d.ViewObject.Visibility for d in dims]
        self.step("Immediate Hide: the two dimensions in the top view", "both selected + Ctrl+B (Hide)",
                  SAME if dims and all(hidden) else FAIL, f"hidden {hidden}")
        Gui.Selection.clearSelection()
        for d in dims:
            Gui.Selection.addSelection(App.ActiveDocument.Name, d.Name)
        self.key("Ctrl+Shift+K")
        QtWidgets.QApplication.processEvents()
        shown = [d.ViewObject.Visibility for d in dims]
        self.step("Show (Ctrl+Shift+K): the two dimensions back", "selected in the Part Navigator + Ctrl+Shift+K",
                  SAME if dims and all(shown) else FAIL, f"shown {shown}; NX picks hidden objects in a list, here "
                  "they are picked in the Part Navigator")
        Gui.Selection.clearSelection()

    def n_center_marks(self):
        v = self._n_top
        arcs = self.n_circles(v, self.M_R) + self.n_circles(v, self.M_DRILL / 2)
        before = (len(v.CenterLines), len(getattr(v, "CosmeticEdges", []) or []))
        self.select_view_subs(v, [f"Edge{i}" for i, _ in arcs])
        b, where = self.click_ribbon("Center Mark")
        QtWidgets.QApplication.processEvents()
        if Gui.Control.activeDialog():
            self.mb2_click_on_sheet()
        App.ActiveDocument.recompute()
        after = (len(v.CenterLines), len(getattr(v, "CosmeticEdges", []) or []))
        made = (after[0] - before[0]) + (after[1] - before[1])
        self.step("Center Mark: the two outer arcs and the drill in the top view", f"{len(arcs)} arcs selected + "
                  f"ribbon '{where} > Center Mark'", SAME if made > 0 else FAIL,
                  f"center lines {before[0]} -> {after[0]}, cosmetic edges {before[1]} -> {after[1]}; the book "
                  "deletes NX's automatic centre lines first: TechDraw adds none by itself")

    def n_radial(self):
        v = self._n_front
        arc = self.n_circles(v, self.M_CIRC)
        d, where = (self.n_dim(v, "Radial", [f"Edge{arc[0][0]}"]) if arc else (None, ""))
        if d is not None:
            d.X, d.Y = 30.0, 52.0                                 # up and right, outside the body
        val = float(d.getRawValue()) / IN if d is not None else None
        self.step("Radial dimension on the bottom arc of the front view", f"arc selected + ribbon '{where} > Radial'",
                  SAME if val is not None and abs(val - self.M_CIRC) < 1e-3 else FAIL,
                  f"R{val * IN:.2f} mm (the book's R1.250 in)" if val is not None else "no radial dimension")
        self.wait = 600

    def n_decimals(self):
        dims = [d for k, d in self._n_dims.items() if k in ("centres", "to the middle")]
        for d in dims:
            d.FormatSpec = "%.2f"
        App.ActiveDocument.recompute()
        self.step("Edit Settings: the 5 and 2.5 dimensions with 2 decimals and trailing zeros",
                  "the dimensions' Format Spec = %.2f", DIFFERS if dims else FAIL,
                  "NX: Edit Settings > Text > decimals; TechDraw: the format spec (shown in the preferences units)")

    def n_change(self):
        """Modeling: the base sketch's hole diameter 0.750 -> 0.625; back to Drafting."""
        self.key("Ctrl+M")
        QtWidgets.QApplication.processEvents()
        base = next(o for o in self._m_doc.Objects if o.Label == "Base")
        sk = base.Profile[0]
        k = next(i for i, c in enumerate(sk.Constraints) if c.Type == "Diameter")
        sk.setDatum(k, App.Units.Quantity(f"{0.625 * IN} mm"))
        self._m_doc.recompute()
        ok = abs(self.solid_volume() - self.m_ref(drill_born=True, circ=True, hole=0.625)) < 1e-3 * self.solid_volume()
        self.step("Modeling: Base feature > Sketch Section, the diameter 0.750 -> 0.625, Finish Sketch, OK",
                  "Ctrl+M; the base sketch's diameter typed (0.625 in = 15.875 mm)", SAME if ok else FAIL,
                  f"volume {self.solid_volume():.1f} mm^3 (expected "
                  f"{self.m_ref(drill_born=True, circ=True, hole=0.625):.1f})")
        self.key("Ctrl+Shift+D")
        self.wait = 2500

    def n_update(self):
        d = self._n_dims.get("hole")
        App.ActiveDocument.recompute()
        self.wait_for("n: drawing update", lambda: d is not None and abs(float(d.getRawValue()) / IN - 0.625) < 1e-3,
                      15000)
        val = float(d.getRawValue()) / IN if d is not None else None
        shown = f"Ø{val * IN:.3f} mm" if val is not None else "no dimension"
        self.step("Drafting: MB3 on the drawing > Update; the diameter shows 0.625 in",
                  "Ctrl+Shift+D; the sheet updates by itself", SAME if val is not None and abs(val - 0.625) < 1e-3
                  else FAIL, f"diameter dimension now {shown}; TechDraw keeps the sheet up to date (the page's Keep "
                  "Updated), NX marks it out of date and asks for Update")
        self.shot("N_drawing.png")
        App.ActiveDocument.save()

    # ------------------------------------------------------------- runner
    def insert_steps(self, fns):
        """Run fns next (a workaround found during the run). They join the plan, so the launcher, which
        requires every run step to have been planned and every planned one run, accepts the result."""
        self.steps[0:0] = fns
        self.planned += [fn.__name__ for fn in fns]

    def next(self):
        if not self.steps:
            self.finish()
            return
        fn = self.steps.pop(0)
        self.wait = 400
        self.progress(fn.__name__)
        if fn.__name__.endswith("_new"):
            self.clean_slate()
        try:
            fn()
        except Exception:
            tb = traceback.format_exc()
            self.info[f"traceback {fn.__name__}"] = tb
            self.step(fn.__name__, "-", FAIL, tb.splitlines()[-1])
            # skip the rest of this tutorial: the steps that follow with its prefix (aa_ for aa_part, not a_),
            # up to the next tutorial's first step; a shared helper (p_modeling) is followed by another
            # tutorial's steps, so it drops nothing (fn.__name__[:2] made "p_" drop tutorial P)
            prefix = fn.__name__.split("_")[0] + "_"
            while self.steps and self.steps[0].__name__.startswith(prefix):
                self.dropped.append(self.steps.pop(0).__name__)
        self.ran.append(fn.__name__)
        QtCore.QTimer.singleShot(self.wait, self.next)

    def clean_slate(self):
        """Before a new tutorial: no dialog or edit mode left over from a previous one that stopped early."""
        left = []
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                left.append("task dialog")
            if Gui.ActiveDocument is not None and Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
                left.append("edit mode")
            dlg = Gui.getMainWindow().findChild(QtWidgets.QDialog, "NXInformation")
            if dlg is not None and dlg.isVisible():
                dlg.close()
            QtWidgets.QApplication.processEvents()
        except Exception as e:
            left.append(f"error {e}")
        if left:
            self.progress(f"clean slate: closed {left}")

    @staticmethod
    def commit_mb():
        """This process's committed memory (Windows PrivateUsage), or -1 elsewhere."""
        if os.name != "nt":
            return -1
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                                               "PrivateUsage")]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return -1
        return c.PrivateUsage // 2 ** 20

    def progress(self, name):
        """One flushed line per step, so a run killed mid-step still says where it was."""
        try:
            mb = self.commit_mb()
        except Exception as e:
            mb = f"? {e}"
        try:
            last = self.rows[-1] if self.rows else {}
            with open(os.path.join(OUT, "progress.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {mb:>6} MB  start {name}"
                        f"  (last row: {last.get('tutorial', '').split(':', 1)[0]}{last.get('n', '')} {last.get('outcome', '')}"
                        f" {last.get('detail', '')[:200]})\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass

    def finish(self):
        self.progress("finish")
        self.info["unexpected modal dialogs"] = self.modals.seen
        from . import controller
        self.info["command controller trace"] = controller.CONTROLLER.trace
        self.info["actions repeated"] = self.retries
        self.info["typed numbers misread after the last step"] = self.misread
        self.info["decimal separator"] = QtCore.QLocale().decimalPoint()
        self.info["FreeCAD"] = App.Version()[:4]
        from . import harness_result
        harness_result.write(os.path.join(OUT, "tutorial.json"), "tutorial",
                             {"steps": self.rows, "info": self.info, "dropped": self.dropped},
                             self.planned, self.ran + self.dropped)
        if os.environ.get("NXSTYLE_SMOKE_EXIT", "1") == "1":
            for name in list(App.listDocuments()):
                App.closeDocument(name)
            QtCore.QTimer.singleShot(300, Gui.getMainWindow().close)


_replay = None


def start(shell):
    global _replay
    _replay = Replay(shell)
    QtCore.QTimer.singleShot(2000, _replay.next)

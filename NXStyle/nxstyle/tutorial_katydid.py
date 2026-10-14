# SPDX-License-Identifier: LGPL-2.1-or-later
"""Grasshopper tutorials replayed on the Katydid canvas (Algorithmic Modeling).

The steps follow written step-by-step versions of four YouTube tutorials. Each component is placed the way a Grasshopper user does it: double-click
the empty canvas, type its name, Enter. Wires are dragged from grip to grip with MB1 (Shift adds a
wire), slider ranges and values are typed into the slider's own dialog (double-click the slider).
Every step's result is checked on the solved graph or in the FreeCAD document, and a screenshot
of the window with the floating canvas is saved after it.

  O  Rhino/Grasshopper basics (Bastian Wibranek): sphere, sliders, two spheres, bake, cylinder
  P  waffle canopy (Rhino Grasshopper, q0rWnXPHeFQ): mirrored profile, arches, surface, contour ribs
  Q  faceted planter (Rhino Grasshopper, 5WAzp1-SHh4): rotated polygons, triangle facets, solid, shell
  R  beginner masterclass (Rhino Grasshopper, Y66bSN4QFUE): swept tube, panel grid, attractor openings
"""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtGui, QtWidgets, Qt

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"
SHOT_WIDTH = 1600            # screenshots for the docs: wide enough to read, small enough to commit


class KatydidTutorials:
    """Mixin for tutorial.Replay: the Katydid (Grasshopper-style) tutorials."""

    # ------------------------------------------------------------- canvas helpers
    def k_dock(self):
        return Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "KatydidDock")

    def k_panel(self):
        dock = self.k_dock()
        return dock.widget() if dock is not None else None

    def k_view(self):
        return self.k_panel().view

    def k_scene(self):
        return self.k_panel().scene

    def k_solve(self):
        QtWidgets.QApplication.processEvents()
        self.k_scene().solve_now()
        QtWidgets.QApplication.processEvents()

    def k_add(self, name, x, y):
        """Double-click the empty canvas at scene (x, y), type the component's name, pick it, Enter."""
        from .tutorial import qtest
        view, scene = self.k_view(), self.k_scene()
        # empty canvas under the cursor, as a user picks it (a double-click on a component edits it instead)
        # (checked with the view's own hit test, the one the double-click uses)
        for dy in (0, 60, -60, 120, -120, 180, -180, 240, -240, 300, -300, 360):
            spot = QtCore.QPointF(x, y + dy)
            view.centerOn(spot)
            QtWidgets.QApplication.processEvents()
            pos = view.mapFromScene(spot)
            if not view.items(QtCore.QRect(pos - QtCore.QPoint(130, 30), QtCore.QSize(260, 60))):
                break
        before = set(scene.graph.components)
        rects0 = {repr(i.comp): i.sceneBoundingRect().getRect() for i in scene.items()
                  if i.parentItem() is None and hasattr(i, "comp")}
        scroll0 = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
        qtest().qWait(QtWidgets.QApplication.doubleClickInterval() + 60)   # not part of the last double-click
        qtest().mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        if view._search is None:
            self.info.setdefault("k_add before click", []).append(
                {"rects": rects0, "scroll before": scroll0,
                 "scroll after": (view.horizontalScrollBar().value(), view.verticalScrollBar().value()),
                 "spot to view now": (view.mapFromScene(spot).x(), view.mapFromScene(spot).y())})
        QtWidgets.QApplication.processEvents()
        popup = view._search
        if popup is None:
            under = [type(i).__name__ for i in view.items(pos)]
            rects = {getattr(i, "comp", i).__repr__(): i.sceneBoundingRect().getRect()
                     for i in scene.items() if i.parentItem() is None and hasattr(i, "comp")}
            self.info.setdefault("k_add misses", []).append(
                {"name": name, "spot": (spot.x(), spot.y()), "pos": (pos.x(), pos.y()),
                 "back to scene": (view.mapToScene(pos).x(), view.mapToScene(pos).y()), "items": rects,
                 "view size": (view.viewport().width(), view.viewport().height()),
                 "zoom": view.transform().m11()})
            raise RuntimeError(f"no search box after a double-click on the canvas (adding {name}) at view {pos}, "
                               f"under it {under}, focus {QtWidgets.QApplication.focusWidget()}, "
                               f"modal {QtWidgets.QApplication.activeModalWidget()}")
        qtest().keyClicks(popup.edit, name)
        QtWidgets.QApplication.processEvents()
        rows = [popup.list.item(i).text().split("   ·")[0] for i in range(popup.list.count())]
        if name not in rows:
            popup.close()
            raise RuntimeError(f"search '{name}' does not list it: {rows[:8]}")
        for _ in range(rows.index(name)):
            qtest().keyClick(popup.edit, Qt.Key_Down)
        qtest().keyClick(popup.edit, Qt.Key_Return)
        QtWidgets.QApplication.processEvents()
        added = [c for c in scene.graph.components if c not in before]
        self._k_recent = getattr(self, "_k_recent", []) + added
        if len(added) != 1:
            raise RuntimeError(f"adding {name} placed {len(added)} components")
        return added[0]

    def k_grip_pos(self, param):
        view, scene = self.k_view(), self.k_scene()
        return view.mapFromScene(scene.grip(param).scenePos())

    def k_wire(self, src, out_i, dst, in_i, add=False):
        """MB1 drag from an output grip to an input grip (Shift held to add instead of replace)."""
        from .tutorial import qtest
        view, scene = self.k_view(), self.k_scene()
        a, b = src.outputs[out_i], dst.inputs[in_i]
        # both ends on screen, as a user would scroll them into view
        mid = (scene.grip(a).scenePos() + scene.grip(b).scenePos()) / 2
        view.centerOn(mid)
        QtWidgets.QApplication.processEvents()
        mods = Qt.ShiftModifier if add else Qt.NoModifier
        vp = view.viewport()
        margin = vp.rect().adjusted(12, 12, -12, -12)
        for _ in range(12):            # zoom out until both grips are on screen, as a user would
            p1, p2 = self.k_grip_pos(a), self.k_grip_pos(b)
            if margin.contains(p1) and margin.contains(p2) or view.transform().m11() < 0.12:
                break
            view.scale(0.8, 0.8)
            view.centerOn(mid)
            QtWidgets.QApplication.processEvents()
        p1, p2 = self.k_grip_pos(a), self.k_grip_pos(b)
        if not (vp.rect().contains(p1) and vp.rect().contains(p2)):
            raise RuntimeError(f"grips not both visible: {p1} {p2} in {vp.rect()}")
        qtest().mousePress(vp, Qt.LeftButton, mods, p1)
        qtest().mouseMove(vp, (p1 + p2) / 2)
        qtest().mouseMove(vp, p2)
        qtest().mouseRelease(vp, Qt.LeftButton, mods, p2)
        QtWidgets.QApplication.processEvents()
        self._k_recent = getattr(self, "_k_recent", []) + [src, dst]
        return a in b.sources

    def k_slider(self, comp, name, lo, hi, value, decimals=1):
        """Double-click the slider and type its name, range and value into the slider dialog, OK."""
        from .tutorial import qtest
        view, scene = self.k_view(), self.k_scene()
        item = scene.items_by_comp[comp]
        view.centerOn(item)
        QtWidgets.QApplication.processEvents()
        label = item.mapToScene(QtCore.QPointF(10, item.h / 2))    # the name band, not the rail (diagnostics)
        self.modals.handler = lambda w: w is getattr(view, "dialog", None)   # the dialog this step expects
        try:
            # what the slider's double-click handler does (SliderItem.mouseDoubleClickEvent). A synthetic
            # double-click works on the first slider only: its dialog opens before the button is released,
            # the release is blocked, and later synthetic double-clicks on a slider never reach the handler
            dlg = view.edit_slider(comp)
            QtWidgets.QApplication.processEvents()
            if dlg is None or not dlg.isVisible():
                p = view.mapFromScene(label)
                raise RuntimeError(f"no slider dialog after a double-click on the slider {comp!r}: under the click "
                                   f"{[type(i).__name__ for i in view.items(p)]} at {p}, search open "
                                   f"{view._search is not None}, grabber {scene.mouseGrabberItem()}, "
                                   f"modal {QtWidgets.QApplication.activeModalWidget()}, "
                                   f"item at {item.sceneBoundingRect().getRect()}, label {label}")
            for edit, text in ((dlg.name, name), (dlg.minimum, f"{lo:g}"), (dlg.maximum, f"{hi:g}"),
                               (dlg.value, f"{value:g}")):
                edit.selectAll()
                qtest().keyClicks(edit, text)
            dlg.decimals.setValue(decimals)
            dlg.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
            QtWidgets.QApplication.processEvents()
            # The dialog opens on the double-click, before the button is released, so the release never
            # reaches the canvas and the slider stays the mouse grabber: the next move drags it along
            # (measured 2026-10-13: the slider jumped to the next place clicked). Reported to Katydid.
            grabber = scene.mouseGrabberItem()
            if grabber is not None:
                self.info.setdefault("slider still grabbing the mouse after its dialog", []).append(repr(comp))
                grabber.ungrabMouse()
        finally:
            self.modals.handler = None
        return abs(comp.value - value) < 1e-9 and comp.nickname == name

    def k_out(self, comp, i=0):
        return list(comp.outputs[i].data)

    def k_menu(self, at_scene, text):
        """Right-click (press and release without moving) and click a menu entry by its text."""
        from .tutorial import qtest
        view = self.k_view()
        view.centerOn(at_scene)
        QtWidgets.QApplication.processEvents()
        p = view.mapFromScene(at_scene)
        qtest().mousePress(view.viewport(), Qt.RightButton, Qt.NoModifier, p)
        qtest().mouseRelease(view.viewport(), Qt.RightButton, Qt.NoModifier, p)
        QtWidgets.QApplication.processEvents()
        menu = view.menu
        if menu is None or not menu.isVisible():
            raise RuntimeError(f"no menu after a right-click for '{text}'")
        act = next((a for a in menu.actions() if a.text() == text), None)
        if act is None:
            menu.close()
            raise RuntimeError(f"menu has no '{text}': {[a.text() for a in menu.actions()]}")
        qtest().mouseClick(menu, Qt.LeftButton, Qt.NoModifier, menu.actionGeometry(act).center())
        QtWidgets.QApplication.processEvents()
        if menu.isVisible():
            menu.close()

    def k_grip(self, param):
        return self.k_scene().grip(param).scenePos()

    def k_modifier(self, param, label):
        """Right-click a grip > Flatten / Graft / Simplify / Reverse."""
        self.k_menu(self.k_grip(param), label)
        return param.modifier == label.lower() or (label == "Reverse" and param.reverse)

    def k_set(self, param, text):
        """Right-click an input grip > Set value…, type the value, OK."""
        from .tutorial import qtest
        view = self.k_view()
        self.modals.handler = lambda w: w is getattr(view, "dialog", None)
        try:
            self.k_menu(self.k_grip(param), "Set value…")
            dlg = view.dialog
            combo = dlg.findChild(QtWidgets.QComboBox) if dlg is not None else None
            edit = dlg.findChild(QtWidgets.QLineEdit) if dlg is not None else None
            if combo is not None and combo.isVisible() and not combo.isEditable():     # True / False
                i = combo.findText(text)
                if i < 0:
                    raise RuntimeError(f"'{text}' is not a choice: {[combo.itemText(k) for k in range(combo.count())]}")
                combo.setCurrentIndex(i)
            elif edit is not None:
                edit.selectAll()
                qtest().keyClicks(edit, text)
            else:
                raise RuntimeError(f"no value dialog for {param.owner.nickname}.{param.nickname}")
            box = dlg.findChild(QtWidgets.QDialogButtonBox)
            box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
            QtWidgets.QApplication.processEvents()
        finally:
            self.modals.handler = None
        return view.last_error is None or text not in str(view.last_error)

    def k_preview_off(self, *comps):
        """Right-click a component > Preview (off): only the result is drawn."""
        scene = self.k_scene()
        for c in comps:
            if not c.preview:          # the menu entry toggles: leave one that is off already
                continue
            item = scene.items_by_comp[c]
            self.k_menu(item.mapToScene(QtCore.QPointF(item.w / 2, 6)), "Preview")
        return all(not c.preview for c in comps)

    def k_build(self, spec):
        """Place components (name, x, y) by search; returns them by key."""
        return {key: self.k_add(name, x, y) for key, (name, x, y) in spec.items()}

    def k_sliders(self, c, spec):
        """Type each slider's name, range and value: {key: (name, lo, hi, value, decimals)}."""
        return all(self.k_slider(c[k], *v) for k, v in spec.items())

    def k_wires(self, c, wires):
        """Drag each wire (src, out, dst, in[, add]); False if any did not connect."""
        ok = True
        for w in wires:
            a, ai, b, bi = w[:4]
            ok = self.k_wire(c[a], ai, c[b], bi, add=len(w) > 4 and w[4]) and ok
        return ok

    def k_shot(self, name):
        """Main window with the floating canvas painted where it is on screen (a window grab misses it)."""
        mw, dock = Gui.getMainWindow(), self.k_dock()
        try:
            from .tutorial import qtest
            self.k_layout()
            self.k_fit_3d()
            if dock is not None:
                # the components this step placed or wired, at a zoom where their names can be read; the
                # whole graph only when it fits that way
                v = self.k_view()
                items = v.scene().items_by_comp
                recent = [items[c] for c in getattr(self, "_k_recent", []) if c in items]
                rect = QtCore.QRectF()
                for it in recent or [i for i in items.values()]:
                    rect = rect.united(it.sceneBoundingRect())
                if not rect.isNull():
                    v.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)
                    zoom = min(max(v.transform().m11(), 0.75), 1.3)
                    v.resetTransform()
                    v.scale(zoom, zoom)
                    v.centerOn(rect.center())
                self._k_recent = []
            try:
                self.view().redraw()
            except Exception:
                pass
            qtest().qWait(400)              # the 3D view draws the new camera before it is grabbed
            QtWidgets.QApplication.processEvents()
            try:                            # FreeCAD's own render of the view, to compare with the grab
                self.view().saveImage(os.path.join(self.out_dir(), name.replace(".png", "_3d.png")), 900, 500)
            except Exception as e:
                self.info[f"saveImage {name}"] = str(e)
            img = mw.grab()
            if dock is not None and dock.isVisible():
                p = QtGui.QPainter(img)
                p.drawPixmap(mw.mapFromGlobal(dock.mapToGlobal(QtCore.QPoint(0, 0))), dock.grab())
                p.end()
            img = img.scaledToWidth(min(SHOT_WIDTH, img.width()), Qt.SmoothTransformation)
            img.save(os.path.join(self.out_dir(), name))
            self.info.setdefault("katydid shots", []).append(name)
        except Exception as e:
            self.info[f"screenshot {name}"] = str(e)

    @staticmethod
    def out_dir():
        return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")

    def k_layout(self):
        """For the pictures: the floating canvas over the lower half of the graphics window, so the 3D
        result above it stays in sight (a user arranges the two the same way)."""
        dock, mw = self.k_dock(), Gui.getMainWindow()
        mdi = mw.findChild(QtWidgets.QMdiArea)
        if dock is None or mdi is None or not dock.isFloating():
            return
        top_left = mdi.mapToGlobal(QtCore.QPoint(0, 0))
        w, h = mdi.width(), mdi.height()
        dock.setGeometry(top_left.x() + 8, top_left.y() + int(h * 0.47), w - 16, int(h * 0.53) - 8)
        QtWidgets.QApplication.processEvents()

    def k_fit_3d(self):
        """Isometric, fitted, then zoomed out and shifted so the result sits in the upper half of the
        graphics window, above the canvas."""
        try:
            direction = getattr(self, "_k_view_dir", None)
            if direction:              # a tutorial's own direction, where isometric hides the result
                self.view().setViewDirection(direction)
            else:
                self.view().viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
            cam = self.view().getCameraNode()
            bb = self.k_result_box()
            if hasattr(cam, "height") and bb is not None:   # orthographic, FreeCAD's default
                from pivy import coin
                rot = cam.orientation.getValue()
                right, up = rot.multVec(coin.SbVec3f(1, 0, 0)), rot.multVec(coin.SbVec3f(0, 1, 0))
                dot = lambda p, d: p[0] * d[0] + p[1] * d[1] + p[2] * d[2]          # noqa: E731
                corners = [(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
                           for z in (bb.ZMin, bb.ZMax)]
                us, vs = [dot(p, right) for p in corners], [dot(p, up) for p in corners]
                w = self.view().getSize()
                aspect = w[0] / max(w[1], 1)
                # the canvas covers the lower 53 %: fit the result into the upper 43 %, centred there
                h = max((max(vs) - min(vs)) / 0.43, (max(us) - min(us)) / (0.92 * aspect), 1.0)
                uc, vc = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2 - 0.265 * h
                p = cam.position.getValue()
                du, dv = uc - dot(p, right), vc - dot(p, up)
                cam.height.setValue(h)
                cam.position.setValue(p[0] + right[0] * du + up[0] * dv, p[1] + right[1] * du + up[1] * dv,
                                      p[2] + right[2] * du + up[2] * dv)
        except Exception as e:
            self.info["k_fit_3d"] = str(e)

    def k_result_box(self):
        """Bounding box of what is shown: the canvas's previewed shapes and the visible document solids."""
        boxes = []
        panel = self.k_panel()
        if panel is not None and panel.preview is not None and panel.preview.enabled:
            for comp in panel.graph.components:
                if comp.preview:
                    boxes += [s.BoundBox for s in comp.shapes() if not s.isNull()]
        doc = App.ActiveDocument
        for o in (doc.Objects if doc else []):
            vo = getattr(o, "ViewObject", None)
            if o.TypeId.startswith("Part::") and vo is not None and vo.Visibility and not o.Shape.isNull():
                boxes.append(o.Shape.BoundBox)
        if not boxes:
            return None
        bb = App.BoundBox(boxes[0])
        for b in boxes[1:]:
            bb.add(b)
        return bb

    # ------------------------------------------------------------- tutorial O
    # Bastian Wibranek, "Rhino 3D and Grasshopper - Basics Tutorial" (YouTube cN6XuHxrfxU).
    def o_new(self):
        self.tutorial = "O: Grasshopper basics, sphere and cylinder (Katydid)"
        self.key("Ctrl+N")
        b, where = self.click_ribbon("Algorithmic Modeling", tab="Application")
        QtWidgets.QApplication.processEvents()
        dock = self.k_dock()
        ok = Gui.activeWorkbench().name() == "KatydidWorkbench" and dock is not None and dock.isVisible()
        self.k_panel().scene.clear_all()
        self.step("Open Grasshopper from Rhino's toolbar; the canvas floats beside the viewports",
                  f"ribbon '{where} > Algorithmic Modeling'", SAME if ok and dock.isFloating() else FAIL,
                  f"Katydid's canvas opens as a floating window over the graphics window "
                  f"(floating {dock.isFloating() if dock else None}); the document is {App.ActiveDocument.Label}")
        self.wait = 800

    def o_names(self):
        panel = self.k_panel()
        tabs = [panel.ribbon.tabText(i) for i in range(panel.ribbon.count())]
        self.step("Display > Draw Full Names, so components show 'Sphere', 'Radius' ...",
                  "-", DIFFERS,
                  "Katydid draws each component's short name on it (Sph, Cyl ...) and shows the full name, "
                  f"every input's name and its type in the tooltip; there is no names/icons switch. Tabs {tabs}")

    def o_sphere(self):
        c = self.k_add("Sphere", 0, 0)
        self._o = {"sphere": c}
        self.k_solve()
        out = self.k_out(c)
        vol = out[0].Volume if out else 0
        want = 4 / 3 * math.pi * 5.0 ** 3
        inputs = [f"{p.nickname} ({p.name})" for p in c.inputs]
        self.step("Double-click the canvas, type Sphere, Enter: a preview sphere at the origin",
                  "double-click + 'Sphere' + Enter", SAME if abs(vol - want) < 1e-6 * want else FAIL,
                  f"sphere volume {vol:.1f} mm^3 = R 5 (Katydid's default; Grasshopper's is 1); inputs {inputs}. "
                  "Grasshopper's Sphere also has a Base plane (B) input; Katydid's sits at the origin")
        self.k_fit_3d()
        self.k_shot("tutorial-O-01-sphere.png")

    def o_point(self):
        """Grasshopper references a Rhino point (Set one Point) and moves the sphere with the Gumball.
        Katydid has no parameter that references document geometry yet: Move with X/Y/Z stands in."""
        s = self._o["sphere"]
        mv = self.k_add("Move", 220, 0)
        x = self.k_add("Number Slider", -320, 80)
        ok = self.k_wire(s, 0, mv, 0)
        ok = self.k_slider(x, "X", -50, 50, 20) and ok
        ok = self.k_wire(x, 0, mv, 1) and ok
        s.preview = False
        self.k_scene().set_preview(s, False)
        self.k_solve()
        out = self.k_out(mv)
        cx = out[0].CenterOfMass.x if out else None
        self._o.update(move=mv, x=x)
        self.step("Reference a Rhino point (Point > Set one Point) into the sphere's Base; drag it with the Gumball",
                  "stand-in: 'Move' after the sphere, a slider 'X' into its X; the sphere's own preview off",
                  MISSING if ok and cx is not None and abs(cx - 20) < 1e-6 else FAIL,
                  f"sphere centre x = {cx}. Katydid has no Point parameter that follows a FreeCAD point yet "
                  "(asked for); dragging the slider moves the sphere live, as the Gumball does in Rhino")
        self.k_shot("tutorial-O-02-move.png")

    def o_radius(self):
        s = self._o["sphere"]
        r = self.k_add("Number Slider", -320, -20)
        ok = self.k_slider(r, "Radius", 0, 10, 5)
        ok = self.k_wire(r, 0, s, 0) and ok
        self.k_solve()
        ok2 = self.k_slider(r, "Radius", 0, 10, 7.5)
        self.k_solve()
        out = self.k_out(self._o["move"])
        vol = out[0].Volume if out else 0
        want = 4 / 3 * math.pi * 7.5 ** 3
        self._o["r"] = r
        self.step("Number Slider into the sphere's Radius (R); double-click the slider's name for its range: 0 to 10",
                  "double-click + 'Number Slider'; double-click the slider: Name, Minimum 0, Maximum 10, Value; "
                  "MB1 drag from the slider to R",
                  SAME if ok and ok2 and abs(vol - want) < 1e-6 * want else FAIL,
                  f"radius 7.5 -> volume {vol:.1f} mm^3 (expected {want:.1f})")
        self.k_shot("tutorial-O-03-radius.png")

    def o_two(self):
        """Set Multiple Points gives two spheres; a second radius slider is Shift-wired into R."""
        s, mv = self._o["sphere"], self._o["move"]
        x2 = self.k_add("Number Slider", -320, 180)
        r2 = self.k_add("Number Slider", -320, -120)
        ok = self.k_slider(x2, "X 2", -50, 50, -20) and self.k_slider(r2, "Radius 2", 0, 10, 3)
        ok = self.k_wire(x2, 0, mv, 1, add=True) and ok
        ok = self.k_wire(r2, 0, s, 0, add=True) and ok
        self.k_solve()
        out = self.k_out(mv)
        got = sorted((round(o.CenterOfMass.x, 3), round((3 * o.Volume / (4 * math.pi)) ** (1 / 3), 3)) for o in out)
        want = [(-20.0, 3.0), (20.0, 7.5)]
        self.step("Two points (Set Multiple Points) give two spheres; copy the slider and Shift-wire both into R",
                  "stand-in: a second X slider Shift-wired into Move's X; a second radius slider Shift-wired into R",
                  DIFFERS if ok and got == want else FAIL,
                  f"spheres (centre x, radius): {got}. Shift + MB1 drag adds a wire, as in Grasshopper; "
                  "lists pair up item by item")
        self.k_shot("tutorial-O-04-two-spheres.png")

    def o_bake(self):
        doc = App.ActiveDocument
        before = {o.Name for o in doc.Objects}
        panel = self.k_panel()
        self.k_scene().clearSelection()
        b, where = self.click_ribbon("Bake")
        QtWidgets.QApplication.processEvents()
        new = [o for o in doc.Objects if o.Name not in before and o.TypeId == "Part::Feature"]
        self.info["O baked"] = [(o.Label, o.Shape.BoundBox.getRect() if hasattr(o.Shape.BoundBox, "getRect")
                                 else str(o.Shape.BoundBox), o.ViewObject.Visibility) for o in new]
        vols = sorted(round(o.Shape.Volume, 1) for o in new)
        want = sorted(round(4 / 3 * math.pi * r ** 3, 1) for r in (3.0, 7.5))
        self.step("Right-click the sphere's output > Bake...: real Rhino objects",
                  f"ribbon '{where} > Bake' (Katydid's own Bake on the canvas does the same)",
                  SAME if vols == want else FAIL,
                  f"baked {[o.Label for o in new]}, volumes {vols} mm^3; they are ordinary Part features in the "
                  f"Part Navigator and stay when the canvas closes. {panel.status.text()}")
        self._k_recent = []                   # the whole (small) graph
        self.k_shot("tutorial-O-05-bake.png")

    def o_cylinder(self):
        scene = self.k_scene()
        scene.clear_all()
        cyl = self.k_add("Cylinder", 0, 0)
        r = self.k_add("Number Slider", -320, -30)
        h = self.k_add("Number Slider", -320, 40)
        ok = self.k_slider(r, "Radius", 0, 10, 5) and self.k_slider(h, "Length", 0, 20, 8)
        ok = self.k_wire(r, 0, cyl, 0) and self.k_wire(h, 0, cyl, 1) and ok
        self.k_solve()
        out = self.k_out(cyl)
        vol = out[0].Volume if out else 0
        want = math.pi * 25 * 8
        self.step("Exercise: Cylinder with sliders 5 for the radius and 8 for the length",
                  "double-click + 'Cylinder'; two sliders typed 5 and 8; wired to R and L",
                  SAME if ok and abs(vol - want) < 1e-6 * want else FAIL,
                  f"volume {vol:.1f} mm^3 (expected {want:.1f}). Grasshopper makes a slider when you type '5' "
                  "into the search box; Katydid's search finds components only (asked for)")
        self.k_shot("tutorial-O-06-cylinder.png")

    def o_warning(self):
        cyl = next(c for c in self.k_scene().graph.components if type(c).__name__ == "Cylinder")
        mv = self.k_add("Move", 260, 0)
        self.k_solve()
        state, msgs = mv.state, list(mv.messages)
        self.step("An orange component: an input is missing; its balloon says why",
                  "a 'Move' with nothing in G", SAME if state == "warning" and msgs else FAIL,
                  f"state {state}: {msgs}; Katydid colours it orange and shows the message in the tooltip "
                  "(hover the component)")
        self.k_wire(cyl, 0, mv, 0)
        self.k_solve()
        self.info["O warning cleared"] = mv.state

    def o_save(self):
        doc = App.ActiveDocument
        path = os.path.join(self.out_dir(), "Katydid_Basics.FCStd")
        self.k_panel().flush()
        doc.saveAs(path)
        has = any(o.Name == "Katydid" or "Katydid" in o.TypeId or getattr(o, "Label", "") == "Katydid"
                  for o in doc.Objects)
        self.step("Save the Rhino model (.3dm) and the Grasshopper definition (.gh), and open both together",
                  "one save (Save As, named by the replay): the canvas is saved inside the part", DIFFERS if has and os.path.isfile(path) else FAIL,
                  f"{os.path.basename(path)} holds the parts and the canvas (a Katydid object in the Part "
                  "Navigator); there is no separate definition file to keep next to it")
        self.k_shot("tutorial-O-07-saved.png")

    # ------------------------------------------------------------- shared steps
    def k_start(self, title):
        """A new part and an empty canvas in the Algorithmic Modeling application."""
        self.tutorial = title
        self._k_view_dir = None
        self._k_recent = []
        self.key("Ctrl+N")
        if Gui.activeWorkbench().name() != "KatydidWorkbench":
            self.click_ribbon("Algorithmic Modeling", tab="Application")
        else:
            self.click_ribbon("Canvas")
        QtWidgets.QApplication.processEvents()
        panel = self.k_panel()
        panel.bind(App.ActiveDocument)
        panel.scene.clear_all()
        return panel is not None and self.k_dock().isVisible()

    def k_bake(self, comps, shot, what):
        doc = App.ActiveDocument
        before = {o.Name for o in doc.Objects}
        scene = self.k_scene()
        scene.clearSelection()
        for c in comps:
            scene.items_by_comp[c].setSelected(True)
        b, where = self.click_ribbon("Bake")
        QtWidgets.QApplication.processEvents()
        new = [o for o in doc.Objects if o.Name not in before and o.TypeId == "Part::Feature"]
        scene.clearSelection()
        self._k_recent = list(comps)          # the picture shows the components that were baked
        self.k_shot(shot)
        return new, where

    @staticmethod
    def k_dist(shape, point):
        import Part
        return shape.distToShape(Part.Vertex(App.Vector(*point)))[0]

    # ------------------------------------------------------------- tutorial P
    # "Grasshopper Tutorial For beginners" (YouTube q0rWnXPHeFQ, channel Rhino Grasshopper): a ribbed
    # canopy from one profile curve, its mirror, two arches, a four-sided surface and contour ribs.
    P_CURVE = [(0, 0), (16, 22), (12, 44), (30, 62), (58, 70)]      # the profile, in the XZ (Front) plane

    def p_new(self):
        ok = self.k_start("P: Waffle canopy (Katydid)")
        # isometric looks along the ribs edge-on; from the open side, slightly from above, they read as slats
        self._k_view_dir = (-1.0, 0.25, -0.3)
        self.step("Rhino's Front view; open Grasshopper", "Ctrl+N + Application > Algorithmic Modeling",
                  SAME if ok else FAIL, "an empty canvas on the new part")

    def p_curve(self):
        c = {}
        for i, (x, z) in enumerate(self.P_CURVE):
            c[f"p{i}"] = self.k_add("Construct Point", -900, -260 + 70 * i)
        c["curve"] = self.k_add("Interpolate", -620, -120)
        ok = True
        for i, (x, z) in enumerate(self.P_CURVE):
            pt = c[f"p{i}"]
            ok = self.k_set(pt.inputs[0], f"{x}") and self.k_set(pt.inputs[2], f"{z}") and ok
            ok = self.k_wire(pt, 0, c["curve"], 0, add=i > 0) and ok
        self.k_solve()
        out = self.k_out(c["curve"])
        self._p = c
        ends = (out[0].Vertexes[0].Point, out[0].Vertexes[-1].Point) if out else None
        self.step("Draw half of the profile in Rhino's Front view; Curve > Set one Curve",
                  "stand-in: five Construct Points (X and Z typed with Set value...) Shift-wired into Interpolate",
                  MISSING if ok and out else FAIL,
                  f"profile from {ends[0] if ends else '-'} to {ends[1] if ends else '-'}, length "
                  f"{out[0].Length:.1f} mm. Katydid has no Curve parameter that follows a FreeCAD sketch yet "
                  "(asked for): the points are typed instead of drawn" if out else "no curve")
        self.k_shot("tutorial-P-01-profile.png")

    def p_points(self):
        c = self._p
        c.update(self.k_build({"bottom": ("Construct Point", -620, 120), "top": ("Construct Point", -620, 300),
                               "bx": ("Number Slider", -900, 120), "by": ("Number Slider", -900, 180),
                               "tx": ("Number Slider", -900, 260), "ty": ("Number Slider", -900, 320),
                               "tz": ("Number Slider", -900, 380)}))
        ok = self.k_sliders(c, {"bx": ("Bottom X", -20, 40, 14), "by": ("Half span", 10, 80, 45),
                                "tx": ("Top X", 0, 80, 44), "ty": ("Top Y", 0, 80, 20), "tz": ("Top Z", 40, 120, 84)})
        ok = self.k_wires(c, [("bx", 0, "bottom", 0), ("by", 0, "bottom", 1),
                              ("tx", 0, "top", 0), ("ty", 0, "top", 1), ("tz", 0, "top", 2)]) and ok
        self.k_solve()
        b, t = self.k_out(c["bottom"]), self.k_out(c["top"])
        self.step("Two Rhino points, Bottom and Top, referenced into Point parameters (moved with the Gumball)",
                  "stand-in: two Construct Points driven by sliders",
                  MISSING if ok and b and t else FAIL,
                  f"bottom {b[0].Point if b else '-'}, top {t[0].Point if t else '-'}; sliders move them, as the "
                  "Gumball does in Rhino")
        self.k_shot("tutorial-P-02-points.png")

    def p_mirror(self):
        c = self._p
        c["mirror"] = self.k_add("Mirror", -360, -120)
        ok = self.k_wires(c, [("curve", 0, "mirror", 0), ("bottom", 0, "mirror", 1)])
        ok = self.k_set(c["mirror"].inputs[2], "0, 1, 0") and ok
        self.k_solve()
        out = self.k_out(c["mirror"])
        y = out[0].BoundBox.YMin if out else None
        self.step("XZ Plane at the Bottom point; Mirror the curve in it",
                  "Mirror: G = the profile, P = the Bottom point, N typed 0, 1, 0 (Katydid's Mirror takes the "
                  "plane as a point and a normal)", DIFFERS if ok and y is not None and abs(y - 90) < 1e-6 else FAIL,
                  f"mirrored profile at y = {y}; the span is twice the Bottom point's Y")
        self.k_shot("tutorial-P-03-mirror.png")

    def p_ends(self):
        c = self._p
        c.update(self.k_build({"s0": ("Evaluate Curve", -120, -300), "e0": ("Evaluate Curve", -120, -200),
                               "s1": ("Evaluate Curve", -120, -60), "e1": ("Evaluate Curve", -120, 40)}))
        ok = self.k_wires(c, [("curve", 0, "s0", 0), ("curve", 0, "e0", 0),
                              ("mirror", 0, "s1", 0), ("mirror", 0, "e1", 0)])
        for k, t in (("s0", "0"), ("e0", "1"), ("s1", "0"), ("e1", "1")):
            ok = self.k_set(c[k].inputs[1], t) and ok
        self.k_solve()
        pts = {k: self.k_out(c[k])[0].Point for k in ("s0", "e0", "s1", "e1") if self.k_out(c[k])}
        self.step("End Points of both curves", "stand-in: Evaluate Curve at t = 0 and t = 1 on each",
                  MISSING if ok and len(pts) == 4 else FAIL,
                  f"{ {k: (round(v.x, 2), round(v.y, 2), round(v.z, 2)) for k, v in pts.items()} }. Katydid has "
                  "no End Points component yet (asked for); Evaluate Curve's t runs from 0 to 1 along the curve")

    def p_arches(self):
        c = self._p
        c.update(self.k_build({"bottom_arch": ("Interpolate", 160, -260), "dtop": ("Deconstruct", -360, 300),
                               "dbot": ("Deconstruct", -360, 120), "top_on": ("Construct Point", -120, 260),
                               "top_arch": ("Interpolate", 160, 120)}))
        ok = self.k_wires(c, [("s0", 0, "bottom_arch", 0), ("bottom", 0, "bottom_arch", 0, True),
                              ("s1", 0, "bottom_arch", 0, True),
                              ("top", 0, "dtop", 0), ("bottom", 0, "dbot", 0),
                              ("dtop", 0, "top_on", 0), ("dbot", 1, "top_on", 1), ("dtop", 2, "top_on", 2),
                              ("e0", 0, "top_arch", 0), ("top_on", 0, "top_arch", 0, True),
                              ("e1", 0, "top_arch", 0, True)])
        self.k_solve()
        ba, ta = self.k_out(c["bottom_arch"]), self.k_out(c["top_arch"])
        bp, tp = self.k_out(c["bottom"]), self.k_out(c["top_on"])
        through = (self.k_dist(ba[0], tuple(bp[0].Point)) if ba and bp else None,
                   self.k_dist(ta[0], tuple(tp[0].Point)) if ta and tp else None)
        self.step("Bottom arch: Merge (start, Bottom point, mirrored start) into Interpolate; top arch the same "
                  "through the Top point Projected onto the mirror plane",
                  "Merge: the three points Shift-wired into Interpolate's V in order; Project stand-in: Deconstruct "
                  "the Top point, its Y replaced by the Bottom point's",
                  DIFFERS if ok and through[0] is not None and max(through) < 1e-6 else FAIL,
                  f"arches pass through the Bottom point and the projected Top point at {through} mm. Shift-wiring "
                  "several sources into one input merges them in order (Grasshopper does the same); Katydid has no "
                  "Merge or Project component yet")
        self.k_shot("tutorial-P-04-arches.png")

    def p_surface(self):
        """Edge Surface (four boundary curves) is not in Katydid yet: a loft through the profile, a middle
        section from the Bottom point to the projected Top point, and the mirrored profile stands in."""
        c = self._p
        c.update(self.k_build({"mid_t": ("Evaluate Curve", 160, 360), "dmid": ("Deconstruct", 400, 360),
                               "mid_pt": ("Construct Point", 620, 360), "middle": ("Interpolate", 840, 260),
                               "surface": ("Loft", 1060, -40)}))
        ok = self.k_wires(c, [("curve", 0, "mid_t", 0), ("mid_t", 0, "dmid", 0),
                              ("dmid", 0, "mid_pt", 0), ("dbot", 1, "mid_pt", 1), ("dmid", 2, "mid_pt", 2),
                              ("bottom", 0, "middle", 0), ("mid_pt", 0, "middle", 0, True),
                              ("top_on", 0, "middle", 0, True),
                              ("curve", 0, "surface", 0), ("middle", 0, "surface", 0, True),
                              ("mirror", 0, "surface", 0, True)])
        ok = self.k_set(c["mid_t"].inputs[1], "0.5") and ok
        ok = self.k_preview_off(c["curve"], c["mirror"], c["bottom_arch"], c["top_arch"], c["middle"]) and ok
        self.k_solve()
        s = self.k_out(c["surface"])
        bp, tp = self.k_out(c["bottom"]), self.k_out(c["top_on"])
        gap = (self.k_dist(s[0], tuple(bp[0].Point)), self.k_dist(s[0], tuple(tp[0].Point))) if s else None
        self.step("Edge Surface from the four boundary curves (a loft would ignore the arches)",
                  "stand-in: Loft through the profile, a middle section (Bottom point, the profile's midpoint "
                  "on the mirror plane, the projected Top point) and the mirrored profile",
                  MISSING if ok and s and max(gap) < 1e-3 else FAIL,
                  f"surface area {s[0].Area:.0f} mm^2; it passes through the Bottom point and the projected Top "
                  f"point ({gap} mm), so it follows the arches at their middle. Katydid has no Edge Surface yet "
                  "(asked for)" if s else "no surface")
        self.k_shot("tutorial-P-05-surface.png")

    def p_contour(self):
        c = self._p
        c.update(self.k_build({"span": ("Distance", 1060, 200), "count": ("Number Slider", 840, 460),
                               "step": ("Expression", 1300, 260), "planes": ("Addition", 1300, 420),
                               "offsets": ("Series", 1540, 300), "contour": ("Contour", 1780, 0)}))
        ok = self.k_slider(c["count"], "Count", 2, 30, 12, 0)
        ok = self.k_wires(c, [("s0", 0, "span", 0), ("s1", 0, "span", 1), ("span", 0, "step", 1),
                              ("count", 0, "step", 2), ("count", 0, "planes", 0), ("step", 0, "offsets", 1),
                              ("planes", 0, "offsets", 2), ("surface", 0, "contour", 0),
                              ("offsets", 0, "contour", 2)]) and ok
        # the edge fix (x - 0.001 in the video): planes 1 mm inside both edges; Katydid's Contour cuts a fine
        # mesh, and a plane 0.01 mm from the edge split into fragments (measured: 15 curves for 13 planes)
        ok = self.k_set(c["step"].inputs[0], "(x - 2)/y") and ok
        ok = self.k_set(c["planes"].inputs[1], "1") and ok
        ok = self.k_set(c["offsets"].inputs[0], "1") and ok
        ok = self.k_set(c["contour"].inputs[1], "0, 1, 0") and ok
        ok = self.k_preview_off(c["surface"]) and ok
        self.k_solve()
        curves = self.k_out(c["contour"])
        self._p_step = self.k_out(c["step"])[0] if self.k_out(c["step"]) else None
        try:
            self.k_out(c["surface"])[0].exportBrep(os.path.join(self.out_dir(), "P_surface.brep"))
        except Exception as e:
            self.info["P surface export"] = str(e)
        self.step("Contour the surface along Unit Y; distance = span / count (Distance, Division); edge fix x - 0.001",
                  "Contour with N typed 0, 1, 0 and D = a Series of offsets: 1 mm, then (span - 2) / count apart, "
                  "count + 1 of them, so the first and last planes sit 1 mm inside the edges",
                  DIFFERS if ok and len(curves) == 13 else FAIL,
                  f"{len(curves)} contour curves for count 12, {self._p_step} mm apart; per plane "
                  f"{[len(b) for _, b in c['contour'].outputs[0].data.branches()]}. Katydid's Contour takes one "
                  "plane offset per item, so a Series lists them; Division is an Expression here")
        self.k_shot("tutorial-P-06-contours.png")

    def p_ribs(self):
        c = self._p
        c.update(self.k_build({"depth": ("Number Slider", 1780, 360), "offset": ("Offset Curve", 2020, 120),
                               "ruled": ("Ruled Surface", 2260, 0)}))
        ok = self.k_slider(c["depth"], "Rib depth", 0.5, 10, 4)
        ok = self.k_wires(c, [("contour", 0, "offset", 0), ("depth", 0, "offset", 1),
                              ("contour", 0, "ruled", 0), ("offset", 0, "ruled", 1)]) and ok
        ok = self.k_modifier(c["ruled"].inputs[0], "Flatten") and self.k_modifier(c["ruled"].inputs[1], "Flatten") and ok
        ok = self.k_preview_off(c["contour"], c["offset"]) and ok
        self.k_solve()
        faces = self.k_out(c["ruled"])
        self.step("Offset Curve by the rib depth; Ruled Surface between each contour and its offset (both Flattened)",
                  "Offset Curve with a 'Rib depth' slider; Ruled Surface: A = the contours, B = their offsets, "
                  "both inputs Flattened (right-click > Flatten)",
                  SAME if ok and len(faces) == 13 else FAIL,
                  f"{len(faces)} flat rib strips, {sum(f.Area for f in faces):.0f} mm^2 in all")
        self.k_shot("tutorial-P-07-strips.png")

    def p_extrude(self):
        c = self._p
        c.update(self.k_build({"ratio": ("Number Slider", 2020, 460), "thick": ("Multiplication", 2260, 380),
                               "dir": ("Vector XYZ", 2500, 380), "ribs": ("Extrude", 2740, 100)}))
        ok = self.k_slider(c["ratio"], "Thickness ratio", 0.1, 1, 0.3, 2)
        ok = self.k_wires(c, [("step", 0, "thick", 0), ("ratio", 0, "thick", 1), ("thick", 0, "dir", 1),
                              ("ruled", 0, "ribs", 0), ("dir", 0, "ribs", 1)]) and ok
        ok = self.k_preview_off(c["ruled"]) and ok
        self.k_solve()
        ribs = self.k_out(c["ribs"])
        want = (self._p_step or 0) * 0.3
        thick = sorted({round(r.BoundBox.YLength, 4) for r in ribs})
        solids = sum(1 for r in ribs if r.Solids)
        self.step("Extrude the strips along Y by spacing x a thickness ratio (Multiplication, Unit Y)",
                  "Multiplication (spacing x 'Thickness ratio' 0.3) into Vector XYZ's Y, into Extrude's D",
                  SAME if ok and solids == 13 and thick and abs(thick[0] - want) < 1e-3 else FAIL,
                  f"{solids} solid ribs, {sum(r.Volume for r in ribs):.0f} mm^3; thickness {thick} mm "
                  f"(spacing {self._p_step} x 0.3 = {want:.4f})")
        self.k_shot("tutorial-P-08-ribs.png")

    def p_bake(self):
        c = self._p
        self.step("Custom Preview with a Colour Swatch", "-", MISSING,
                  "Katydid previews everything in one colour (red, green when selected); per-component colours "
                  "are not there yet (asked for)")
        new, where = self.k_bake([c["ribs"]], "tutorial-P-09-baked.png", "ribs")
        self.step("Bake the ribs; Internalise the referenced curve", f"select Extrude + ribbon '{where} > Bake'",
                  SAME if len(new) == 13 else FAIL,
                  f"{len(new)} rib solids in the Part Navigator, {sum(o.Shape.Volume for o in new):.0f} mm^3. "
                  "Nothing to internalise: the profile's points are typed on the canvas, not referenced")

    # ------------------------------------------------------------- tutorial Q
    # "Rhino Grasshopper Tutorial (Beginner)" (YouTube 5WAzp1-SHh4, channel Rhino Grasshopper): a faceted
    # planter from two polygons, the top one turned by 360/2N, triangle facets, a closed solid, a shell.
    def q_new(self):
        ok = self.k_start("Q: Faceted planter (Katydid)")
        self.step("Open Grasshopper", "Ctrl+N + Application > Algorithmic Modeling", SAME if ok else FAIL,
                  "an empty canvas on the new part")

    def q_polygon(self):
        c = self.k_build({"poly": ("Regular Polygon", -500, 0), "r": ("Number Slider", -800, -40),
                          "n": ("Number Slider", -800, 40)})
        ok = self.k_sliders(c, {"r": ("Radius", 10, 50, 30), "n": ("Segments", 3, 8, 5, 0)})
        ok = self.k_wires(c, [("r", 0, "poly", 0), ("n", 0, "poly", 1)]) and ok
        self.k_solve()
        p = self.k_out(c["poly"])
        self._q = c
        corner = max(v.Point.Length for v in p[0].Vertexes) if p else 0
        self.step("Polygon on the XY plane; sliders for Radius (10-50) and Segments (3-8)",
                  "Regular Polygon with 'Radius' 30 and 'Segments' 5", SAME if ok and p and len(p[0].Edges) == 5
                  and abs(corner - 30) < 1e-6 else FAIL, f"{len(p[0].Edges) if p else 0} edges, corners {corner:.3f} mm "
                  "from the centre")
        self.k_shot("tutorial-Q-01-polygon.png")

    def q_lift(self):
        c = self._q
        c.update(self.k_build({"move": ("Move", -200, 0), "h": ("Number Slider", -500, 140),
                               "angle": ("Expression", -200, 220), "rot": ("Rotate", 60, 60)}))
        ok = self.k_slider(c["h"], "Height", 12, 300, 60)
        ok = self.k_wires(c, [("poly", 0, "move", 0), ("h", 0, "move", 3), ("n", 0, "angle", 1),
                              ("move", 0, "rot", 0), ("angle", 0, "rot", 1)]) and ok
        ok = self.k_set(c["angle"].inputs[0], "360/x/2") and ok
        self.k_solve()
        top = self.k_out(c["rot"])
        first = top[0].Vertexes[0].Point if top else None
        ang = math.degrees(math.atan2(first.y, first.x)) if first else None
        self.step("Move it up by Unit Z x height; Rotate 3D by 360 / N / 2 degrees (two Divisions)",
                  "Move with 'Height' in Z; Rotate with A = Expression 360/x/2 (x = Segments); Katydid's Rotate "
                  "takes degrees", DIFFERS if ok and first and abs(first.z - 60) < 1e-6 and abs(ang - 36) < 1e-6
                  else FAIL, f"top polygon at z = {first.z if first else '-'}, first corner at {ang} degrees "
                  "(360 / 5 / 2 = 36): each top corner sits over the middle of a base edge")
        self.k_shot("tutorial-Q-02-top.png")

    def q_explode(self):
        c = self._q
        c.update(self.k_build({"bv": ("Divide Curve", 300, -200), "bv2": ("Divide Curve", 300, -100),
                               "tv": ("Divide Curve", 300, 100), "tv2": ("Divide Curve", 300, 200),
                               "bs": ("Shift List", 540, -100), "ts": ("Shift List", 540, 200)}))
        ok = self.k_wires(c, [("poly", 0, "bv", 0), ("n", 0, "bv", 1), ("poly", 0, "bv2", 0), ("n", 0, "bv2", 1),
                              ("rot", 0, "tv", 0), ("n", 0, "tv", 1), ("rot", 0, "tv2", 0), ("n", 0, "tv2", 1),
                              ("bv2", 0, "bs", 0), ("tv2", 0, "ts", 0)])
        # Shift List adds a level to the path ({0;0} in, {0;0;0} out); with its input Flattened its corners
        # land on the same paths as Divide Curve's, so the grafted branches pair up
        for k in ("bs", "ts"):
            ok = self.k_modifier(c[k].inputs[0], "Flatten") and ok
        for k in ("bv", "tv", "bs", "ts"):
            ok = self.k_modifier(c[k].outputs[0], "Graft") and ok
        ok = self.k_preview_off(c["poly"], c["move"], c["rot"], c["bv"], c["bv2"], c["tv"], c["tv2"]) and ok
        self.k_solve()
        counts = {k: len(self.k_out(c[k])) for k in ("bv", "tv", "bs", "ts")}
        self.step("Explode both polygons; Shortest List drops the repeated closing vertex; Shift List by 1",
                  "stand-in for Explode: Divide Curve into Segments (corners, without the repeated closing one, so "
                  "no Shortest List is needed); Shift List with its input Flattened; the lists for the facets "
                  "Grafted, one corner per branch",
                  MISSING if ok and set(counts.values()) == {5} else FAIL,
                  f"corners per list {counts}. Katydid has no Explode or Shortest List yet (asked for)")

    def q_facets(self):
        c = self._q
        c.update(self.k_build({"low": ("Polyline", 780, -160), "up": ("Polyline", 780, 160),
                               "low_s": ("Planar Surface", 1020, -160), "up_s": ("Planar Surface", 1020, 160)}))
        ok = self.k_wires(c, [("bv", 0, "low", 0), ("bs", 0, "low", 0, True), ("tv", 0, "low", 0, True),
                              ("tv", 0, "up", 0), ("ts", 0, "up", 0, True), ("bs", 0, "up", 0, True),
                              ("low", 0, "low_s", 0), ("up", 0, "up_s", 0)])
        ok = self.k_set(c["low"].inputs[1], "True") and self.k_set(c["up"].inputs[1], "True") and ok
        ok = self.k_preview_off(c["low"], c["up"]) and ok
        self.k_solve()
        faces = self.k_out(c["low_s"]) + self.k_out(c["up_s"])
        tri = all(len(f.Edges) == 3 for f in faces)
        try:
            low = c["low"]
            tree = low.collect(low.inputs[0])
            self.info["Q low polyline input"] = [
                (str(path), [tuple(round(v, 2) for v in (getattr(p, "Point", p))) for p in items])
                for path, items in tree.branches()]
            self.info["Q sources paths"] = {k: [str(path) for path, _ in c[k].outputs[0].data.branches()]
                                            for k in ("bv", "bs", "tv")}
        except Exception as e:
            self.info["Q low polyline input"] = str(e)
        self.step("Extrude Point: each base edge to a top corner, then each top edge to the shifted base corner",
                  "stand-in for Extrude Point: a closed Polyline through each branch's three corners (base, next "
                  "base, top / top, next top, next base), then Planar Surface",
                  MISSING if ok and len(faces) == 10 and tri else FAIL,
                  f"{len(faces)} triangular facets, {sum(f.Area for f in faces):.0f} mm^2; Shift List keeps them "
                  "from twisting. Katydid has no Extrude Point yet (asked for)")
        self.k_shot("tutorial-Q-03-facets.png")

    def q_solid(self):
        c = self._q
        c.update(self.k_build({"join": ("Solid Union", 1260, 0), "solid": ("Cap Holes", 1500, 0)}))
        ok = self.k_wires(c, [("low_s", 0, "join", 0), ("up_s", 0, "join", 0, True), ("join", 0, "solid", 0)])
        ok = self.k_modifier(c["join"].inputs[0], "Flatten") and ok
        ok = self.k_preview_off(c["low_s"], c["up_s"], c["join"]) and ok
        self.k_solve()
        s = self.k_out(c["solid"])
        want = self.q_reference_volume(30, 5, 60)
        got = s[0].Volume if s else 0
        self.step("Boundary Surfaces for the top and bottom caps; everything Flattened into Brep Join: a closed solid",
                  "Solid Union with its input Flattened joins the ten facets into one shell; Cap Holes closes the "
                  "top and bottom", DIFFERS if ok and s and s[0].isValid() and len(s[0].Faces) == 12
                  and abs(got - want) < 1e-6 * want else FAIL,
                  f"valid solid, {len(s[0].Faces) if s else 0} faces, {got:.1f} mm^3 (the same faces made "
                  f"directly with FreeCAD's Part API: {want:.1f}). Cap Holes makes both caps, so no separate "
                  "Boundary Surfaces are needed")
        self.k_shot("tutorial-Q-04-solid.png")

    @staticmethod
    def q_reference_volume(r, n, h):
        import Part
        a = 360 / n / 2
        b = [App.Vector(r * math.cos(math.radians(360 * i / n)), r * math.sin(math.radians(360 * i / n)), 0)
             for i in range(n)]
        t = [App.Vector(r * math.cos(math.radians(360 * i / n + a)), r * math.sin(math.radians(360 * i / n + a)), h)
             for i in range(n)]
        faces = [Part.Face(Part.makePolygon(b + [b[0]])), Part.Face(Part.makePolygon(t + [t[0]]))]
        for i in range(n):
            j = (i + 1) % n
            faces.append(Part.Face(Part.makePolygon([b[i], b[j], t[i], b[i]])))
            faces.append(Part.Face(Part.makePolygon([t[i], t[j], b[j], t[i]])))
        shell = Part.Shell(faces)
        shell.sewShape()
        return abs(Part.Solid(shell).Volume)

    def q_shell(self):
        """Option A of the video: bake, then the CAD's own Shell. On a plain solid that is FreeCAD's Part
        Thickness, Surface > Thicken on the NX ribbon (Shell on the Home tab is PartDesign's, for a Body)."""
        c = self._q
        new, where = self.k_bake([c["solid"]], "tutorial-Q-05-baked.png", "planter")
        obj = new[0] if new else None
        self.step("Bake the solid", f"select Cap Holes + ribbon '{where} > Bake'", SAME if obj else FAIL,
                  f"{obj.Label if obj else '-'}, {obj.Shape.Volume if obj else 0:.1f} mm^3")
        if obj is None:
            return
        top = max(range(len(obj.Shape.Faces)), key=lambda i: obj.Shape.Faces[i].CenterOfMass.z)
        self.shell.switch_application("modeling")
        QtWidgets.QApplication.processEvents()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, f"Face{top + 1}")
        sel = [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]
        b, where = self.click_ribbon("Thicken")
        QtWidgets.QApplication.processEvents()
        th = next((o for o in reversed(App.ActiveDocument.Objects) if o.TypeId == "Part::Thickness"), None)
        self.info["Q thicken"] = {"selection at click": sel, "button": where,
                                  "faces link": str(getattr(th, "Faces", None)), "value": str(getattr(th, "Value", None)),
                                  "dialog": str(Gui.Control.activeDialog())}
        self._q_shell = (obj, where)
        self.wait = 1500

    def q_shell_dialog(self):
        from .tutorial import qtest
        obj, where = self._q_shell
        doc = App.ActiveDocument
        th = next((o for o in reversed(doc.Objects) if o.TypeId == "Part::Thickness"), None)
        spin = None
        dlg = Gui.Control.activeDialog()
        panel = self.tasks_dock() if hasattr(self, "tasks_dock") else None
        if panel is not None:
            spin = next((w for w in panel.findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()), None)
        if spin is not None:
            spin.selectAll()
            qtest().keyClicks(spin, "-3 mm")
            qtest().keyClick(spin, Qt.Key_Tab)
            QtWidgets.QApplication.processEvents()
        # FreeCAD's thickness on this faceted solid needs its Intersection option: without it the result is
        # the unchanged solid (measured headless: 138495.8 mm^3 back; with it 35097.5 mm^3, valid, top open)
        inter = next((b for b in (panel.findChildren(QtWidgets.QCheckBox) if panel is not None else [])
                      if b.isVisible() and "intersection" in b.text().lower()), None)
        if inter is not None and not inter.isChecked():
            qtest().mouseClick(inter, Qt.LeftButton)
            QtWidgets.QApplication.processEvents()
        self.info["Q thicken options"] = {"intersection box": inter is not None and inter.isChecked(),
                                          "boxes": [b.text() for b in (panel.findChildren(QtWidgets.QCheckBox)
                                                                       if panel is not None else [])]}
        if dlg:
            self.mb2_click()
            QtWidgets.QApplication.processEvents()
        doc.recompute()
        ok = th is not None and th.Shape.isValid() and not th.Shape.isNull()
        bb0, bb1 = obj.Shape.BoundBox, th.Shape.BoundBox if ok else None
        inward = ok and abs(bb0.XLength - bb1.XLength) < 1e-3 and abs(bb0.ZLength - bb1.ZLength) < 1e-3
        v = th.Shape.Volume if ok else 0
        self.step("Shell: Rhino's Shell command, the top face picked, thickness 5 (or Pufferfish's Shell Polysurface)",
                  f"the top face selected + ribbon '{where} > Thicken' (FreeCAD's Part Thickness), "
                  "'-3 mm' typed, Intersection ticked, MB2 = OK", DIFFERS if inward and 0 < v < obj.Shape.Volume else FAIL,
                  f"hollow planter {v:.1f} mm^3 of {obj.Shape.Volume:.1f}, outside unchanged {inward}, "
                  f"{len(th.Shape.Faces) if ok else 0} faces; value {th.Value if th else '-'}. Option B "
                  "(Pufferfish's parametric Shell) has no Katydid component yet")
        self.k_fit_3d()
        self.k_shot("tutorial-Q-06-shell.png")

    # ------------------------------------------------------------- tutorial R
    # "Rhino Grasshopper Tutorial (Beginner)" (YouTube Y66bSN4QFUE, channel Rhino Grasshopper): plugins,
    # a swept tube, panels, Weaverbird openings driven by an attractor. The plugin parts have no Katydid
    # counterpart; the tube, the panel grid and the attractor-driven openings are rebuilt.
    def r_new(self):
        ok = self.k_start("R: Beginner masterclass, tube and attractor openings (Katydid)")
        self.step("Install Bifocals, LunchBox and Weaverbird (Components Folder, Unblock)", "-", MISSING,
                  "Katydid has no plugins: everything below uses its own components")
        self.step("Display > Draw Icons, Full Names, Fancy Wires", "-", SAME if ok else FAIL,
                  "Katydid always draws its wires 'fancy': solid for one item, double for a list, dashed for a "
                  "tree of several branches")

    def r_tube(self):
        c = self.k_build({"rail": ("Circle", -500, -100), "rr": ("Number Slider", -800, -140),
                          "t": ("Number Slider", -800, 0), "frame": ("Evaluate Curve", -240, -20),
                          "tr": ("Number Slider", -800, 100), "section": ("Circle CNR", 20, 20),
                          "tube": ("Pipe", 20, -180), "panel": ("Panel", 280, -180)})
        ok = self.k_sliders(c, {"rr": ("Rail radius", 10, 80, 40), "t": ("Frame t", 0, 1, 0.25, 2),
                                "tr": ("Tube radius", 1, 20, 9)})
        ok = self.k_wires(c, [("rr", 0, "rail", 0), ("rail", 0, "frame", 0), ("t", 0, "frame", 1),
                              ("frame", 0, "section", 0), ("frame", 1, "section", 1), ("tr", 0, "section", 2),
                              ("rail", 0, "tube", 0), ("tr", 0, "tube", 1), ("tube", 0, "panel", 0)]) and ok
        self.k_solve()
        tube = self.k_out(c["tube"])
        want = 2 * math.pi ** 2 * 40 * 9 ** 2
        self._r = c
        self.step("Circle rail; Perp Frame at t (Reparameterize: 0 to 1); a section Circle on that frame; Sweep 1",
                  "Circle (rail), Evaluate Curve at 'Frame t' (its point and tangent are the frame: Katydid's t "
                  "always runs 0 to 1), Circle CNR (centre, normal, radius) for the section; Pipe for the sweep; "
                  "a Panel shows the result", DIFFERS if ok and tube and abs(tube[0].Volume - want) < 1e-3 * want
                  else FAIL, f"tube {tube[0].Volume if tube else 0:.0f} mm^3 (a torus, 2 pi^2 R r^2 = {want:.0f}). "
                  "No Perp Frame or Sweep 1 component yet: a circle section swept along a rail is Katydid's Pipe")
        self.k_shot("tutorial-R-01-tube.png")

    def r_grid(self):
        c = self._r
        c.update(self.k_build({"u": ("Number Slider", -800, 260), "v": ("Number Slider", -800, 330),
                               "du": ("Expression", -500, 260), "ts": ("Series", -240, 260),
                               "frames": ("Evaluate Curve", 20, 220), "rings": ("Circle CNR", 280, 220),
                               "grid": ("Divide Curve", 540, 260)}))
        ok = self.k_sliders(c, {"u": ("U panels", 4, 40, 12, 0), "v": ("V panels", 3, 20, 6, 0)})
        ok = self.k_wires(c, [("u", 0, "du", 1), ("du", 0, "ts", 1), ("u", 0, "ts", 2), ("rail", 0, "frames", 0),
                              ("ts", 0, "frames", 1), ("frames", 0, "rings", 0), ("frames", 1, "rings", 1),
                              ("tr", 0, "rings", 2), ("rings", 0, "grid", 0), ("v", 0, "grid", 1)]) and ok
        ok = self.k_set(c["du"].inputs[0], "1/x") and self.k_set(c["ts"].inputs[0], "0") and ok
        ok = self.k_preview_off(c["section"], c["frame"], c["frames"]) and ok
        self.k_solve()
        pts = self.k_out(c["grid"])
        on = max((self.k_dist(self.k_out(c["tube"])[0], tuple(p.Point)) for p in pts), default=1)
        self.step("Divide Domain2 into U x V; IsoTrim the surface into panels (or LunchBox Quad Panels)",
                  "stand-in: U section circles along the rail (Series of t, Evaluate Curve, Circle CNR), each "
                  "divided into V points: the corners of U x V panels",
                  MISSING if ok and len(pts) == 12 * 6 and on < 1e-3 else FAIL,
                  f"{len(pts)} panel corners, all on the tube (within {on:.4f} mm). Katydid has no Divide Domain2, "
                  "IsoTrim or panelling components yet")
        self.k_shot("tutorial-R-02-grid.png")

    def r_weaverbird(self):
        self.step("Mesh Surface; Weaverbird Picture Frame, Weld, Catmull-Clark (level 1-3), Thicken", "-", MISSING,
                  "no mesh components or Weaverbird counterpart in Katydid: the next step frames each opening "
                  "with a ring instead of insetting mesh faces")

    def r_attractor(self):
        c = self._r
        c.update(self.k_build({"ax": ("Number Slider", 540, 460), "ay": ("Number Slider", 540, 530),
                               "az": ("Number Slider", 540, 600), "attr": ("Construct Point", 800, 500),
                               "dist": ("Distance", 1040, 360), "bounds": ("Bounds", 1280, 440),
                               "rmin": ("Number Slider", 1040, 620), "rmax": ("Number Slider", 1040, 690),
                               "size": ("Remap Numbers", 1520, 380)}))
        ok = self.k_sliders(c, {"ax": ("Attractor X", -60, 60, 45), "ay": ("Attractor Y", -60, 60, 0),
                                "az": ("Attractor Z", -20, 20, 8), "rmin": ("Smallest", 0.2, 3, 0.6, 2),
                                "rmax": ("Largest", 0.5, 5, 2.6, 2)})
        ok = self.k_wires(c, [("ax", 0, "attr", 0), ("ay", 0, "attr", 1), ("az", 0, "attr", 2),
                              ("grid", 0, "dist", 0), ("attr", 0, "dist", 1), ("dist", 0, "bounds", 0),
                              ("dist", 0, "size", 0), ("bounds", 0, "size", 1), ("bounds", 1, "size", 2),
                              ("rmax", 0, "size", 3), ("rmin", 0, "size", 4)]) and ok   # nearest -> largest
        ok = self.k_modifier(c["bounds"].inputs[0], "Flatten") and ok
        self.k_solve()
        sizes = self.k_out(c["size"])
        dists = self.k_out(c["dist"])
        near = sizes[dists.index(min(dists))] if sizes and len(dists) == len(sizes) else None
        ok = ok and near is not None and abs(near - 2.6) < 1e-6
        self.step("Attractor: Evaluate Surface at an MD Slider's uv; Closest Point distances; Bounds; Construct Domain; "
                  "Remap Numbers into the opening sizes",
                  "Construct Point with X/Y/Z sliders (no MD Slider yet); Distance from every panel corner; Bounds "
                  "(input Flattened); Remap Numbers into 'Smallest' .. 'Largest' (two sliders for the target domain)",
                  DIFFERS if ok and sizes and abs(min(sizes) - 0.6) < 1e-6 and abs(max(sizes) - 2.6) < 1e-6
                  else FAIL, f"{len(sizes)} opening radii from {min(sizes) if sizes else '-'} to "
                  f"{max(sizes) if sizes else '-'} mm; the corner nearest the attractor gets {near} ('Largest' into "
                  "T0, 'Smallest' into T1). Katydid has no MD Slider or Construct Domain yet")

    def r_openings(self):
        """Weaverbird's Picture Frame insets every mesh face into a window frame. Katydid has no mesh tools,
        so each panel corner gets a frame of its own: a ring on the tube, sized by the attractor. (Cutting
        holes instead failed: in the GUI, a second Solid Difference on a Pipe-minus-Pipe wall came back
        invalid, while the same shapes read back from BREP cut cleanly; reported to Katydid.)"""
        c = self._r
        c.update(self.k_build({"deep_r": ("Expression", 280, 400), "deep_rings": ("Circle CNR", 540, 420),
                               "deep": ("Divide Curve", 800, 420), "normal": ("Vector 2Pt", 1520, 160),
                               "opening": ("Circle CNR", 1760, 240), "fw": ("Number Slider", 1520, 520),
                               "frame": ("Pipe", 2000, 240)}))
        ok = self.k_slider(c["fw"], "Frame width", 0.1, 1.5, 0.45, 2)
        ok = self.k_wires(c, [("tr", 0, "deep_r", 1), ("frames", 0, "deep_rings", 0), ("frames", 1, "deep_rings", 1),
                              ("deep_r", 0, "deep_rings", 2), ("deep_rings", 0, "deep", 0), ("v", 0, "deep", 1),
                              ("grid", 0, "normal", 0), ("deep", 0, "normal", 1),
                              ("grid", 0, "opening", 0), ("normal", 0, "opening", 1), ("size", 0, "opening", 2),
                              ("opening", 0, "frame", 0), ("fw", 0, "frame", 1)]) and ok
        ok = self.k_set(c["deep_r"].inputs[0], "x - 3") and ok
        ok = self.k_preview_off(c["rings"], c["grid"], c["opening"], c["section"], c["rail"], c["deep_rings"],
                                c["deep"]) and ok
        self.k_solve()
        frames = self.k_out(c["frame"])
        radii = sorted(round(o.Curve.Radius, 3) for o in (e for s in self.k_out(c["opening"]) for e in s.Edges))
        valid = sum(1 for f in frames if f.isValid())
        tube = self.k_out(c["tube"])
        on = max((self.k_dist(tube[0], tuple(e.Curve.Center)) for s in self.k_out(c["opening"])
                  for e in s.Edges), default=1) if tube else 1
        self.step("Graft the remapped sizes into Weaverbird's Picture Frame distance: the openings grow near the "
                  "attractor; Weld, Catmull-Clark and Thicken round and thicken the frames",
                  "a second ring of corners 3 mm further in (Expression x - 3, Circle CNR, Divide Curve); Vector 2Pt "
                  "from each corner to its inner twin as the opening's axis; Circle CNR with the remapped radii; "
                  "Pipe with a 'Frame width' slider makes each opening's frame",
                  DIFFERS if ok and len(frames) == 72 and valid == 72 and radii and abs(radii[0] - 0.6) < 1e-6
                  and abs(radii[-1] - 2.6) < 1e-6 and on < 1e-4 else FAIL,
                  f"{len(frames)} frames ({valid} valid solids) on the tube (centres within {on:.1e} mm), openings {radii[0] if radii else '-'} to "
                  f"{radii[-1] if radii else '-'} mm in radius, the largest nearest the attractor; drag the attractor "
                  "sliders and they follow. Katydid has no mesh components: the frames are rings, not inset mesh faces")
        self.k_shot("tutorial-R-03-frames.png")

    def r_bake(self):
        c = self._r
        self.step("Deconstruct Brep, List Item and Aligned Dimension for live dimensions; Custom Preview colours",
                  "-", MISSING, "no drawing dimensions or preview colours on Katydid's canvas yet")
        new, where = self.k_bake([c["tube"], c["frame"]], "tutorial-R-04-baked.png", "tube")
        good = sum(1 for o in new if o.Shape.isValid())
        self.step("Right-click > Bake to a Rhino layer", f"select the tube's Pipe and the frames' Pipe + ribbon "
                  f"'{where} > Bake'", SAME if len(new) == 73 and good == 73 else FAIL,
                  f"{len(new)} objects baked (the tube and {len(new) - 1} frames), {good} valid; FreeCAD has no "
                  "layers here: they go into the Part Navigator")

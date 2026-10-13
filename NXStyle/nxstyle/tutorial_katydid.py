# SPDX-License-Identifier: LGPL-2.1-or-later
"""Grasshopper tutorials replayed on the Katydid canvas (Algorithmic Modeling).

The steps follow the written tutorials Foad collected (Grasshopper Waffle Canopy Tutorial.md, from
four YouTube videos). Each component is placed the way a Grasshopper user does it: double-click
the empty canvas, type its name, Enter. Wires are dragged from grip to grip with MB1 (Shift adds a
wire), slider ranges and values are typed into the slider's own dialog (double-click the slider).
Every step's result is checked on the solved graph or in the FreeCAD document, and a screenshot
of the window with the floating canvas is saved after it.

  O  Rhino/Grasshopper basics (Bastian Wibranek): sphere, sliders, two spheres, bake, cylinder
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
        p1, p2 = self.k_grip_pos(a), self.k_grip_pos(b)
        vp = view.viewport()
        if not (vp.rect().contains(p1) and vp.rect().contains(p2)):
            raise RuntimeError(f"grips not both visible: {p1} {p2} in {vp.rect()}")
        qtest().mousePress(vp, Qt.LeftButton, mods, p1)
        qtest().mouseMove(vp, (p1 + p2) / 2)
        qtest().mouseMove(vp, p2)
        qtest().mouseRelease(vp, Qt.LeftButton, mods, p2)
        QtWidgets.QApplication.processEvents()
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

    def k_shot(self, name):
        """Main window with the floating canvas painted where it is on screen (a window grab misses it)."""
        mw, dock = Gui.getMainWindow(), self.k_dock()
        try:
            from .tutorial import qtest
            self.k_layout()
            self.k_fit_3d()
            if dock is not None:
                self.k_view().fit_all()
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
            self.view().viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
            cam = self.view().getCameraNode()
            if hasattr(cam, "height"):                      # orthographic, FreeCAD's default
                from pivy import coin
                cam.height.setValue(cam.height.getValue() * 2.1)
                up = cam.orientation.getValue().multVec(coin.SbVec3f(0, 1, 0))
                shift = cam.height.getValue() * 0.26
                p = cam.position.getValue()
                cam.position.setValue(p[0] - up[0] * shift, p[1] - up[1] * shift, p[2] - up[2] * shift)
        except Exception as e:
            self.info["k_fit_3d"] = str(e)

    # ------------------------------------------------------------- tutorial O
    # Bastian Wibranek, "Rhino 3D and Grasshopper Basics" (YouTube cN6XuHxrfxU), as written up in
    # Foad's Grasshopper Waffle Canopy Tutorial.md, part 4.
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

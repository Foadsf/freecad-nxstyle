# SPDX-License-Identifier: LGPL-2.1-or-later
"""Laser Cut tutorial, on the bundled LCInterlocking add-on (github.com/execuc/LCInterlocking; the fork
github.com/Foadsf/LCInterlocking).

  AD  a tray from 3 mm sheet (our design): five flat panels, Tabs and Slots on the eight places where they
      meet, the joined parts checked solid by solid, then Export Flat Parts and an SVG for the cutter

NX has no laser-cut application, so there is no book: the steps are the add-on's own workflow (its
docs/interlocking.md and export.md), done from NX-Style's Laser Cut ribbon.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtWidgets, Qt

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


class LaserCutTutorials:
    """Mixin for tutorial.Replay."""

    AD_T = 3.0                       # sheet thickness, mm
    AD_L, AD_W, AD_H = 120.0, 80.0, 40.0
    # name: (size x, y, z), position; the walls stand on the base, the short ones between the long ones
    AD_PANELS = {
        "Base": ((AD_L, AD_W, AD_T), (0, 0, 0)),
        "Front": ((AD_L, AD_T, AD_H), (0, 0, AD_T)),
        "Back": ((AD_L, AD_T, AD_H), (0, AD_W - AD_T, AD_T)),
        "Left": ((AD_T, AD_W - 2 * AD_T, AD_H), (0, AD_T, AD_T)),
        "Right": ((AD_T, AD_W - 2 * AD_T, AD_H), (AD_L - AD_T, AD_T, AD_T)),
    }

    def AD_STEPS(self):
        return [self.p_modeling, self.ad_new, self.ad_app, self.ad_check_app, self.ad_panels, self.ad_join,
                self.ad_parts, self.ad_faces, self.ad_ok, self.ad_result, self.ad_export, self.ad_flat,
                self.ad_svg]

    # ------------------------------------------------------------- helpers
    def ad_doc(self):
        return App.listDocuments().get(getattr(self, "_ad_doc", ""))

    def ad_panel_button(self, text):
        """A push button of the add-on's task panel, by its caption."""
        dock = self.tasks_dock()
        return next((b for b in (dock.findChildren(QtWidgets.QPushButton) if dock is not None else [])
                     if b.text().replace("&", "") == text and b.isVisible()), None)

    def ad_click(self, b):
        from .tutorial import qtest
        qtest().mouseClick(b, Qt.LeftButton)
        QtWidgets.QApplication.processEvents()

    def ad_faces_to_join(self):
        """(panel, face) where a panel meets another: the walls' bottoms on the base, and the short walls'
        ends against the long walls."""
        doc, t = self.ad_doc(), self.AD_T
        out = []
        for name in ("Front", "Back", "Left", "Right"):
            o = doc.getObject(self._ad_panels.get(name, ""))
            if o is None:
                continue
            for i, f in enumerate(o.Shape.Faces):
                n, c = f.normalAt(0, 0), f.CenterOfMass
                bottom = n.z < -0.9 and abs(c.z - t) < 1e-6
                end = name in ("Left", "Right") and abs(n.y) > 0.9 and (abs(c.y - t) < 1e-6 or
                                                                         abs(c.y - (self.AD_W - t)) < 1e-6)
                if bottom or end:
                    out.append((o, f"Face{i + 1}"))
        return out

    # ------------------------------------------------------------- steps
    def ad_new(self):
        self.tutorial = "AD: A laser-cut tray with tabs and slots (LCInterlocking)"
        self._docs_before = set(App.listDocuments())
        self.key("Ctrl+N")
        self.wait = 1200

    def ad_app(self):
        new = sorted(set(App.listDocuments()) - self._docs_before)
        self._ad_doc = new[0] if new else (App.ActiveDocument.Name if App.ActiveDocument else "")
        self.step("File > New (Ctrl+N)", "Ctrl+N", SAME if new else FAIL, f"new document {new}")
        b, where = self.click_ribbon("Laser Cut", tab="Application")
        self.info["AD application button"] = where
        self.wait = 3000

    def ad_check_app(self):
        app = (getattr(self.shell, "current_app", None) or {}).get("id")
        r = self.shell.ribbon
        cmds = ("make_box_command", "multiple_tabs_command", "crosspiece", "livinghinge", "export_command")
        missing = [c for c in cmds if c not in r.locations]
        ok = app == "laser_cut" and r.tab_names()[:1] == ["Home"] and not missing and \
            Gui.activeWorkbench().name() == "LCInterlockingWorkbench"
        self.step("Application > Laser Cut", "ribbon 'Application > Laser Cut'", DIFFERS if ok else FAIL,
                  f"application {app}; tabs {r.tab_names()}; commands not found {missing or 'none'}. NX has no "
                  "laser-cut application: NX-Style adds one on the LCInterlocking add-on (bundled), with Panel Box, "
                  "Tabs and Slots, Cross Halving, Living Hinge and Export Flat Parts")
        self.shot("AD_ribbon.png")
        self.wait = 300

    def ad_panels(self):
        """Five Blocks from the ribbon, sized and placed as typed into their properties."""
        doc = self.ad_doc()
        made = []
        for name, (size, at) in self.AD_PANELS.items():
            n0 = len(doc.Objects)
            b, where = self.click_ribbon("Block")
            QtWidgets.QApplication.processEvents()
            new = [o for o in doc.Objects[n0:] if o.TypeId == "Part::Box"]
            if not new:
                continue
            o = new[0]
            o.Label = name
            o.Length, o.Width, o.Height = size
            o.Placement.Base = App.Vector(*at)
            made.append(o)
        doc.recompute()
        self._ad_panels = {o.Label: o.Name for o in made}
        ok = len(made) == 5 and all(abs(min(o.Shape.BoundBox.XLength, o.Shape.BoundBox.YLength,
                                            o.Shape.BoundBox.ZLength) - self.AD_T) < 1e-9 for o in made)
        self.step("Five 3 mm panels: a 120 x 80 base, two 120 x 40 long walls, two short walls between them",
                  "ribbon 'Home > Panel > Block' five times; sizes and positions typed into the properties",
                  DIFFERS if ok else FAIL,
                  f"{len(made)} Part solids {sorted(self._ad_panels)}. FreeCAD's Block makes a 10 mm cube to edit, "
                  "NX's asks for the sizes first. Part solids: LCInterlocking ignores a moved PartDesign Body's placement")
        Gui.SendMsgToActiveView("ViewFit")
        self.wait = 300

    def ad_join(self):
        Gui.Selection.clearSelection()
        b, where = self.click_ribbon("Tabs and Slots")
        self.info["AD Tabs and Slots"] = where
        self.wait = 1500

    def ad_parts(self):
        doc = self.ad_doc()
        panel_open = Gui.Control.activeDialog() and self.ad_panel_button("Add parts") is not None
        self._ad_join = next((o.Name for o in doc.Objects if o.Name.startswith("MultiJoin")), "")
        Gui.Selection.clearSelection()
        for name in self._ad_panels.values():
            Gui.Selection.addSelection(doc.getObject(name))
        b = self.ad_panel_button("Add parts")
        if b is not None:
            self.ad_click(b)
        join = doc.getObject(self._ad_join) if self._ad_join else None
        parts = list(join.parts.lst) if join is not None else []
        thick = sorted({round(p.thickness, 3) for p in parts})
        ok = panel_open and len(parts) == 5 and thick == [self.AD_T]
        self.step("Tabs and Slots: select the five panels, Add parts",
                  "ribbon 'Home > Joint > Tabs and Slots', the panels picked, the panel's 'Add parts' button",
                  DIFFERS if ok else FAIL,
                  f"{len(parts)} parts, thickness found {thick} mm. The add-on's own task panel (its names: "
                  "Add parts, Add faces); it reads each panel's thickness from its two largest faces")
        self.wait = 300

    def ad_faces(self):
        doc = self.ad_doc()
        faces = self.ad_faces_to_join()
        Gui.Selection.clearSelection()
        for o, f in faces:
            Gui.Selection.addSelection(doc.Name, o.Name, f)
        dock = self.tasks_dock()
        combo = next((c for c in dock.findChildren(QtWidgets.QComboBox) if c.findText("Tab") >= 0), None) \
            if dock is not None else None
        if combo is not None:
            combo.setCurrentIndex(combo.findText("Tab"))
        b = self.ad_panel_button("Add faces")
        if b is not None:
            self.ad_click(b)
        join = doc.getObject(self._ad_join) if self._ad_join else None
        tabs = list(join.faces.lst) if join is not None else []
        ok = len(faces) == 8 and len(tabs) == 8
        self.step("The eight faces where panels meet: Add faces, type Tab",
                  "the four walls' bottom faces and the short walls' four ends picked, 'Tab', 'Add faces'",
                  DIFFERS if ok else FAIL,
                  f"{len(tabs)} tab joints; one 10 mm tab per face "
                  "(the panel's default). The face picked is the tab's side; the panel it touches gets the slot")
        self.wait = 300

    def ad_ok(self):
        self._ad_ok = self.p_ok()
        self.wait = 2500

    def ad_result(self):
        doc = self.ad_doc()
        join = doc.getObject(self._ad_join) if self._ad_join else None
        parts = list(join.generatedParts) if join is not None else []
        t = self.AD_T
        before = sum(doc.getObject(n).Shape.Volume for n in self._ad_panels.values())
        after = sum(o.Shape.Volume for o in parts)
        solid = all(o.Shape.isValid() and len(o.Shape.Solids) == 1 for o in parts)
        # each tab is the slot widened by the laser kerf (thickness/15 by default): a press fit, so the
        # joined parts overlap by the kerf alone
        overlap = sum(a.Shape.common(b.Shape).Volume for i, a in enumerate(parts) for b in parts[i + 1:])
        slot = 10 * t * t
        ok = (not Gui.Control.activeDialog() and len(parts) == 5 and solid and
              0 <= after - before < 0.1 * 8 * slot and overlap < 0.1 * 8 * slot)
        self.step("OK: the panels with their tabs and slots", f"{self._ad_ok} = OK",
                  SAME if ok else FAIL,
                  f"{len(parts)} parts, each one solid: {solid}; volume {before:.1f} -> {after:.1f} mm^3 (tabs add "
                  f"what the slots remove, plus the kerf allowance); parts overlap by {overlap:.2f} mm^3 in all, the "
                  "kerf allowance of the tabs. The originals are kept, hidden, in a group")
        v = Gui.getDocument(doc.Name).ActiveView
        v.viewIsometric()
        v.fitAll()
        QtWidgets.QApplication.processEvents()
        self.shot("AD_tray.png")
        self.wait = 300

    def ad_export(self):
        doc = self.ad_doc()
        join = doc.getObject(self._ad_join) if self._ad_join else None
        Gui.Selection.clearSelection()
        for o in (join.generatedParts if join is not None else []):
            Gui.Selection.addSelection(o)
        self._docs_before = set(App.listDocuments())
        b, where = self.click_ribbon("Export Flat Parts")
        self.info["AD export"] = where
        self.wait = 2500

    def ad_flat(self):
        new = sorted(set(App.listDocuments()) - self._docs_before)
        doc = App.getDocument(new[0]) if new else None
        solids = [o for o in doc.Objects if o.TypeId == "Part::Feature"] if doc else []
        views = [o for o in doc.Objects if o.TypeId == "Part::Part2DObjectPython"] if doc else []
        flat = all(abs(o.Shape.BoundBox.ZLength - self.AD_T) < 1e-6 for o in solids)
        boxes = [o.Shape.BoundBox for o in solids]
        apart = all(not a.intersect(b) or a.intersected(b).XLength * a.intersected(b).YLength < 1e-6
                    for i, a in enumerate(boxes) for b in boxes[i + 1:])
        self._ad_flat = doc.Name if doc else ""
        ok = len(solids) == 5 and len(views) == 5 and flat and apart
        self.step("Export Flat Parts: the parts laid flat, side by side, with their outlines",
                  "the joined parts selected, ribbon 'Home > Output > Export Flat Parts'", DIFFERS if ok else FAIL,
                  f"new document {new}: {len(solids)} parts, each {self.AD_T:g} mm thick and lying flat: {flat}; "
                  f"none overlapping: {apart}; {len(views)} 2D outlines (Draft Shape2DView). NX would flatten "
                  "each body and export its face; the add-on does all of them at once")
        if doc is not None:
            v = Gui.getDocument(doc.Name).ActiveView
            v.viewTop()
            v.fitAll()
            QtWidgets.QApplication.processEvents()
            self.shot("AD_flat.png")
        self.wait = 300

    def ad_svg(self):
        doc = App.listDocuments().get(getattr(self, "_ad_flat", ""))
        views = [o for o in doc.Objects if o.TypeId == "Part::Part2DObjectPython"] if doc else []
        path = os.path.join(_out(), "Tray_flat.svg")
        detail = ""
        try:
            import importSVG
            importSVG.export(views, path)
            text = open(path, encoding="utf-8").read()
            paths = text.count("<path")
            ok = bool(views) and paths >= len(views)
            detail = f"Tray_flat.svg: {paths} paths for {len(views)} outlines, {len(text)} bytes"
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        self.step("Export the outlines for the laser cutter (File > Export)",
                  "the outlines exported as SVG (FreeCAD's importSVG, what File > Export > SVG runs)",
                  DIFFERS if ok else FAIL, detail + ". NX writes DXF from File > Export; FreeCAD writes DXF the "
                  "same way, SVG needs no extra library")
        self.wait = 300

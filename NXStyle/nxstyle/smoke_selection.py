# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of selection (called from smoke.py): scope and look-alike occurrences, QuickPick,
select-through, the gate layers, collectors in both orders, curve chains, and the Part Navigator.

Each scenario builds its own document and closes it; one that raises is recorded as a failed check and
the others still run."""

import traceback

import FreeCAD as App
import FreeCADGui as Gui

from . import collector_ui, navigator_status, quickpick
from . import selection_filter as sf
from .qt import Qt, QtCore, QtWidgets


def qwait(ms):
    from .tutorial import qtest
    qtest().qWait(ms)


def selected():
    """(top object, sub-name) of the selection, without FreeCAD's mapped element names."""
    return sorted((s.ObjectName, sf.core.plain(sub)) for s in Gui.Selection.getSelectionEx("", 0)
                  for sub in (s.SubElementNames or [""]))


def leaf_selected():
    """(object, element) of the selection: Body + 'Round.Edge7' is ('Round', 'Edge7')."""
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in (s.SubElementNames or [""]):
            r = sf.Resolved(s.DocumentName, s.ObjectName, sub)
            out.append((r.leaf.Name, r.element))
    return sorted(out)


def settle(view, ms=300):
    view.redraw()
    qwait(ms)


def qt_point(f, coin_xy):
    """Coin pixel coordinates (from getPointOnViewport) -> widget position for a mouse event."""
    w = f.widget
    dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
    return QtCore.QPoint(int(coin_xy[0] / dpr), int(w.height() - coin_xy[1] / dpr))


def click(smoke, f, p):
    smoke.send(f, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton)
    QtWidgets.QApplication.processEvents()
    smoke.send(f, QtCore.QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton)
    smoke.send(f, QtCore.QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
    QtWidgets.QApplication.processEvents()


def cancel_task_dialog():
    """Press Cancel in the open task dialog (FreeCAD's Fillet removes its new feature then)."""
    mw = Gui.getMainWindow()
    for dock in mw.findChildren(QtWidgets.QDockWidget):
        for box in dock.findChildren(QtWidgets.QDialogButtonBox):
            b = box.button(QtWidgets.QDialogButtonBox.Cancel)
            if b is not None and b.isVisible() and b.isEnabled():
                b.click()
                QtWidgets.QApplication.processEvents()
                return True
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    return False


class Scenario:
    def __init__(self, smoke, name):
        self.smoke, self.name = smoke, name
        self.before = App.ActiveDocument
        self.doc = None

    def __enter__(self):
        self.doc = App.newDocument(self.name)
        return self

    def __exit__(self, kind, value, tb):
        sh = self.smoke.shell
        if kind is not None:
            self.smoke.check(f"selection scenario {self.name} ran", False, "".join(
                traceback.format_exception_only(kind, value)).strip())
            self.smoke.info[f"traceback {self.name}"] = "".join(traceback.format_exception(kind, value, tb))
        try:
            if Gui.Control.activeDialog():
                cancel_task_dialog()
            sh.type_filter.setCurrentIndex(0)
            sh.scope_filter.select("assembly")
            Gui.Selection.clearSelection()
            App.closeDocument(self.doc.Name)
            if self.before is not None and self.before.Name in App.listDocuments():
                App.setActiveDocument(self.before.Name)
                Gui.getDocument(self.before.Name)
        except Exception:
            self.smoke.info[f"cleanup {self.name}"] = traceback.format_exc()
        return True


# ------------------------------------------------------------ scenarios
def nested_occurrences(smoke):
    """Two links to one part, one above the other: the work part is the lower one. The upper sibling
    looks the same and is nearer the eye; it must not be the one picked."""
    sh = smoke.shell
    with Scenario(smoke, "SmokeOccurrences") as sc:
        doc = sc.doc
        unit = doc.addObject("App::Part", "Unit")
        box = doc.addObject("Part::Box", "Box")
        box.Length = box.Width = 20
        box.Height = 10
        unit.addObject(box)
        asm = doc.addObject("App::Part", "Asm")
        la = doc.addObject("App::Link", "UnitA")
        la.LinkedObject = unit
        lb = doc.addObject("App::Link", "UnitB")
        lb.LinkedObject = unit
        lb.Placement.Base = App.Vector(0, 0, 30)
        asm.addObject(la)
        asm.addObject(lb)
        unit.Visibility = False
        doc.recompute()
        av = Gui.getDocument(doc.Name).ActiveView
        av.viewTop()
        av.fitAll()
        settle(av, 500)
        av.setActiveObject("part", asm, "UnitA.")
        sh.scope_filter.select("work_part_and_components")
        work = sf.work_part()
        xy = av.getPointOnViewport(App.Vector(10, 10, 40))
        rows = sf.rows_at(av, xy)
        brief = [(r["sub"], r["ok"]) for r in rows]
        top_refused = bool(rows) and rows[0]["sub"].startswith("UnitB.") and not rows[0]["ok"] \
            and "outside the work part Asm › UnitA" in rows[0]["reason"]
        a_rows = [r for r in rows if r["sub"].startswith("UnitA.")]
        smoke.check("work part can be one occurrence of a part (Asm › UnitA), not the part itself",
                    work == ("Asm", "UnitA") and "Asm › UnitA" in sf.work_part_text(), (work, sf.work_part_text()))
        smoke.check("QuickPick rows: the look-alike sibling nearer the eye is listed and refused with the reason; "
                    "the work part's occurrence behind it is allowed",
                    top_refused and a_rows and all(r["ok"] for r in a_rows), brief[:6])

        # QuickPick list: picks exactly the work part's occurrence
        menu = quickpick.open_at(av, xy, sh.mw.mapToGlobal(QtCore.QPoint(300, 300)))
        qwait(50)
        chosen = None
        if menu is not None:
            d = menu.default()
            refused_greyed = not menu.row_actions[0].isEnabled() and "outside the work part" in \
                menu.row_actions[0].toolTip()
            chosen = menu.choose(d) if d is not None else None
            menu.hide()
        got = selected()
        smoke.check("QuickPick: the sibling's row is greyed with its reason; choosing selects the work part's "
                    "occurrence, never the sibling",
                    menu is not None and refused_greyed and chosen and got == [("Asm", "UnitA.Box.Face6")],
                    f"rows {len(menu.rows) if menu else 0}, selection {got}")

        # the gate refuses the sibling directly too, and the cue line says why
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Asm", "UnitB.Box.Face6")
        refused = not selected()
        sh._tick()
        cue = sh.cue.text()
        smoke.check("a pick on the sibling occurrence is refused, and the cue line says why",
                    refused and "Cannot select" in cue and "UnitB" in cue and "work part" in cue, cue)

        # MB1 on the graphics window: select-through, then the control without a scope
        f = sh.navigation.filter_for_active_view()
        p = qt_point(f, xy)
        Gui.Selection.clearSelection()
        click(smoke, f, p)
        through = selected()
        how = f.last_pick
        sh.scope_filter.select("assembly")
        Gui.Selection.clearSelection()
        click(smoke, f, p)
        plain = selected()
        smoke.check("MB1 click selects through the refused sibling to the work part's occurrence; with Entire "
                    "Assembly the same click takes the nearer sibling (control)",
                    through == [("Asm", "UnitA.Box.Face6")] and how and how[0] == "through"
                    and plain == [("Asm", "UnitB.Box.Face6")] and f.last_pick[0] == "click",
                    f"scoped {through} ({how}); entire assembly {plain} ({f.last_pick})")

        # hold MB1 still: QuickPick opens; the release does not select anything by itself
        sh.scope_filter.select("work_part_and_components")
        Gui.Selection.clearSelection()
        smoke.send(f, QtCore.QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton)
        qwait(int(f.cfg.get("quickpick_hold_ms", 500)) + 300)
        held = quickpick.last()
        shown = held is not None and held.isVisible() and held is not menu
        smoke.send(f, QtCore.QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
        after_release = selected()
        if held is not None:
            held.hide()
        smoke.check("holding MB1 still over the overlap opens QuickPick (release selects nothing)",
                    shown and f.last_pick[0] == "quickpick" and not after_release,
                    f"{f.last_pick}, visible {shown}, selection after release {after_release}")

        # Within Work Part Only: the work part is the assembly, the units are components
        av.setActiveObject("part", asm)
        sh.scope_filter.select("work_part_only")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Asm", "UnitA.Box.Face6")
        smoke.check("Within Work Part Only refuses a component's geometry, with the reason",
                    not selected() and "component" in sf.manager().recent_rejection(),
                    sf.manager().recent_rejection())

        # the navigator shows the work part and the occurrence that is selected
        av.setActiveObject("part", asm, "UnitA.")
        sh.scope_filter.select("work_part_and_components")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Asm", "UnitA.Box.Face6")
        strip = sh.navigator_status
        st = strip.refresh(force=True) if strip is not None else {}
        text = strip.text() if strip is not None else ""
        smoke.check("Part Navigator names the work part and the selected occurrence",
                    strip is not None and "Work part: Asm › UnitA" in text and "Face6 of Asm › UnitA › Box" in text
                    and "UnitB" not in st.get("selected", "x"), text)
        smoke.shot("10_selection_navigator.png")


def gate_layers(smoke):
    """Command-then-select with Edge Blend's collector; the Type Filter changed during the command does
    not replace the command's gate and is in force after it; preselect-then-command; FreeCAD's own
    dialog gates are left alone."""
    sh = smoke.shell
    m = sf.manager()
    with Scenario(smoke, "SmokeGates") as sc:
        doc = sc.doc
        body = doc.addObject("PartDesign::Body", "Body")
        pbox = doc.addObject("PartDesign::AdditiveBox", "PBox")
        body.addObject(pbox)
        pbox.Length, pbox.Width, pbox.Height = 40, 30, 10
        doc.recompute()
        vert = next(i for i, e in enumerate(pbox.Shape.Edges, 1)
                    if all(abs(v.Point.x) < 1e-6 and abs(v.Point.y) < 1e-6 for v in e.Vertexes))
        rnd = doc.addObject("PartDesign::Fillet", "Round")
        body.addObject(rnd)
        rnd.Base = (pbox, [f"Edge{vert}"])
        rnd.Radius = 5
        other = doc.addObject("PartDesign::Body", "Body001")
        obox = doc.addObject("PartDesign::AdditiveBox", "OtherBox")
        other.addObject(obox)
        obox.Placement.Base = App.Vector(60, 0, 0)
        loose = doc.addObject("Part::Box", "Loose")
        loose.Placement.Base = App.Vector(0, 60, 0)
        doc.recompute()
        av = Gui.getDocument(doc.Name).ActiveView
        av.setActiveObject("pdbody", body)
        av.viewIsometric()
        av.fitAll()
        settle(av)
        shape = rnd.Shape
        arc = next(f"Edge{i}" for i, e in enumerate(shape.Edges, 1) if e.Curve.TypeId == "Part::GeomCircle"
                   and abs(e.BoundBox.ZMin - 10) < 1e-6 and abs(e.BoundBox.ZMax - 10) < 1e-6)
        top = next(f"Face{i}" for i, f in enumerate(shape.Faces, 1)
                   if f.Surface.TypeId == "Part::GeomPlane" and abs(f.CenterOfMass.z - 10) < 1e-6)
        ends = [v.Point for v in shape.getElement(arc).Vertexes]
        # a top line that meets the rounded corner (it continues the arc smoothly)
        line = next(f"Edge{i}" for i, e in enumerate(shape.Edges, 1) if e.Curve.TypeId == "Part::GeomLine"
                    and abs(e.BoundBox.ZMin - 10) < 1e-6 and abs(e.BoundBox.ZMax - 10) < 1e-6
                    and any((v.Point - q).Length < 1e-6 for v in e.Vertexes for q in ends))
        tf = sh.type_filter
        tf.setCurrentIndex(tf.findData("edge"))

        # --- command, then select
        Gui.Selection.clearSelection()
        Gui.runCommand("NXStyle_EdgeBlend")
        qwait(200)
        panel = collector_ui.last_panel()
        w = panel.widget
        empty = (collector_ui.last_route(), w.status.text(), w.mark.text(), panel.accept(), w.message.text())
        smoke.check("Edge Blend with nothing selected opens its collector: 'Select Edge (0)', marked as "
                    "needed, and OK is refused with the reason",
                    empty[0] == "collector" and empty[1] == "Select Edge (0)" and empty[2] == "✱"
                    and empty[3] is False and "at least 1 edge" in empty[4] and Gui.Control.activeDialog(), empty)
        when = tf.setCurrentIndex(tf.findData("face")) or m.history[-1]
        Gui.Selection.addSelection(doc.Name, "Round", top)
        face_refused = ("Round", top) not in leaf_selected()
        Gui.Selection.addSelection(doc.Name, "Round", arc)
        chain = sorted(s for o, s in leaf_selected() if o == "Round")
        smoke.check("a Type Filter change during the command does not replace the command's gate: a face is "
                    "still refused, an edge still taken",
                    m.global_kind == "face" and when.startswith("task:") and face_refused and arc in chain,
                    f"global {m.global_kind}, installed {when}, selection {chain}")
        smoke.check("Tangent Curves: one pick on the rounded corner collects the smooth chain (line, arc, line), "
                    "and the collector counts it",
                    len(chain) == 3 and line in chain and panel.collector.count == 3 and w.status.text() ==
                    "Select Edge (3)" and w.mark.text() == "✔", f"{chain}, {w.status.text()}")
        Gui.Selection.addSelection(doc.Name, "OtherBox", "Edge1")
        Gui.Selection.addSelection(doc.Name, "Loose", "Edge1")
        reasons = [r for _, r in panel.collector.rejected]
        smoke.check("the collector says why it refused picks: a face, an edge of another body, an edge "
                    "outside any body",
                    any("is a face" in r for r in reasons) and any("works on one body" in r for r in reasons)
                    and any("not in one" in r for r in reasons) and "not in one" in w.message.text()
                    and panel.collector.count == 3, reasons)
        panel.reject()
        qwait(100)
        restored = (m.history[-1], not Gui.Control.activeDialog(), leaf_selected())
        Gui.Selection.addSelection(doc.Name, "Round", top)
        Gui.Selection.addSelection(doc.Name, "Round", line)
        after = leaf_selected()
        smoke.check("after Cancel the previous gate is back with the Type Filter chosen meanwhile (Face): a face "
                    "is taken, an edge refused; the selection is as before",
                    restored[0] == "global" and restored[1] and restored[2] == [] and after == [("Round", top)],
                    f"{restored}, then {after}")

        # --- select, then command: one usable edge and a face
        tf.setCurrentIndex(0)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Round", line)
        Gui.Selection.addSelection(doc.Name, "Round", top)
        n0 = len(doc.Objects)
        Gui.runCommand("NXStyle_EdgeBlend")
        qwait(200)
        panel = collector_ui.last_panel()
        pre = (collector_ui.last_route(), panel.collector.count, [r for _, r in panel.collector.rejected],
               leaf_selected())
        ok = panel.accept()
        qwait(800)
        fillets = [o for o in doc.Objects if o.TypeId == "PartDesign::Fillet" and o.Name != "Round"]
        handed = fillets[0].Base[1] if fillets and fillets[0].Base else None
        smoke.check("preselected edge + face, then Edge Blend: the edge is collected, the face refused with the "
                    "reason and deselected; OK hands the edge to FreeCAD's Fillet",
                    pre[0] == "collector" and pre[1] == 1 and any("is a face" in r for r in pre[2])
                    and pre[3] == [("Round", line)] and ok and len(doc.Objects) == n0 + 1 and handed == [line],
                    f"{pre}; fillet base {handed}")
        cancel_task_dialog()
        qwait(300)

        # --- select, then command: all usable: straight to FreeCAD's Fillet (the tutorials' route)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Round", line)
        Gui.runCommand("NXStyle_EdgeBlend")
        qwait(800)
        direct = (collector_ui.last_route(), bool(Gui.Control.activeDialog()),
                  [o.Name for o in doc.Objects if o.TypeId == "PartDesign::Fillet" and o.Name != "Round"])
        cancel_task_dialog()
        qwait(300)
        smoke.check("preselected usable edges, then Edge Blend: FreeCAD's Fillet opens at once with them",
                    direct[0] == "direct" and direct[1] and len(direct[2]) == 1, direct)

        # --- one of FreeCAD's own dialogs with a gate of its own (FreeCAD's reference selection works so)
        class TheirGate:
            def allow(self, d, o, s):
                return s.split(".")[-1].startswith("Vertex")

        class TheirPanel:
            def __init__(self):
                self.form = QtWidgets.QLabel("a FreeCAD dialog picking vertices")

            def accept(self):
                Gui.Selection.removeSelectionGate()
                Gui.Control.closeDialog()
                return True

            reject = accept

        tf.setCurrentIndex(tf.findData("face"))
        theirs = TheirPanel()
        Gui.Control.showDialog(theirs)
        Gui.Selection.addSelectionGate(TheirGate())
        sh._tick()
        tf.setCurrentIndex(tf.findData("edge"))
        during = m.history[-1]
        Gui.Selection.clearSelection()
        for s in ("Vertex1", line, top):
            Gui.Selection.addSelection(doc.Name, "Round", s)
        in_dialog = leaf_selected()
        theirs.reject()
        sh._tick()
        Gui.Selection.clearSelection()
        for s in ("Vertex1", line, top):
            Gui.Selection.addSelection(doc.Name, "Round", s)
        afterwards = leaf_selected()
        smoke.check("a Type Filter change while FreeCAD's dialog has its own gate waits: the dialog's gate stays "
                    "in force, and NX-Style's (now Edge) comes back when it closes",
                    during == "deferred" and in_dialog == [("Round", "Vertex1")] and m.history[-1] == "global"
                    and afterwards == [("Round", line)], f"{during}; in the dialog {in_dialog}; after {afterwards}")


def chains_on_a_sketch(smoke):
    """The chain rules on real geometry: a rectangle sketch is one connected wire with square corners."""
    with Scenario(smoke, "SmokeChains") as sc:
        import Part
        import Sketcher
        doc = sc.doc
        sk = doc.addObject("Sketcher::SketchObject", "Sketch")
        pts = [App.Vector(0, 0, 0), App.Vector(30, 0, 0), App.Vector(30, 20, 0), App.Vector(0, 20, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        doc.recompute()
        pick = sf.Resolved(doc.Name, "Sketch", "Edge1")
        got = {r: sorted(collector_ui.chain_subs(pick, r)) for r in ("single", "tangent", "connected")}
        smoke.check("chain rules on a rectangle sketch: Connected Curves takes the 4 sides, Tangent Curves stops "
                    "at the square corners",
                    got["single"] == ["Edge1"] and got["tangent"] == ["Edge1"] and len(got["connected"]) == 4, got)


def navigator(smoke):
    """Suppressed and failed features and the active body are plain in the Part Navigator."""
    sh = smoke.shell
    with Scenario(smoke, "SmokeNavigator") as sc:
        doc = sc.doc
        body = doc.addObject("PartDesign::Body", "Body")
        b1 = doc.addObject("PartDesign::AdditiveBox", "PBox")
        body.addObject(b1)
        b2 = doc.addObject("PartDesign::AdditiveCylinder", "PCyl")
        body.addObject(b2)
        b2.Suppressed = True
        base = doc.addObject("Part::Box", "Block")
        bad = doc.addObject("Part::Fillet", "BadFillet")
        bad.Base = base
        bad.Edges = [(99, 1.0, 1.0)]          # no such edge: the feature fails
        doc.recompute()
        Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", body)
        qwait(200)
        strip = sh.navigator_status
        if strip is None:
            smoke.check("Part Navigator status strip", False, "not attached")
            return
        strip.refresh(force=True)
        text = strip.text()
        qwait(100)
        strip.refresh(force=True)
        pcyl, badl, pbox = strip.item_looks("PCyl"), strip.item_looks("BadFillet"), strip.item_looks("PBox")
        smoke.check("Part Navigator shows the active body, the suppressed feature and the failed one, in the "
                    "strip and on their tree items",
                    "Active body: Body" in text and "Suppressed: 1 PCyl" in text and "Errors: 1 BadFillet" in text
                    and pcyl and all(x["strike"] for x in pcyl) and badl
                    and all(x["color"].lower() == navigator_status.RED.lower() and x["tip"].startswith("Error")
                            for x in badl)
                    and pbox and not any(x["strike"] for x in pbox),
                    {"strip": text, "PCyl": pcyl, "BadFillet": badl, "PBox": pbox})
        b2.Suppressed = False
        doc.recompute()
        strip.refresh(force=True)
        smoke.check("unsuppressing clears the mark", not any(x["strike"] for x in strip.item_looks("PCyl"))
                    and "Suppressed" not in strip.text(), strip.text())
        b2.Suppressed = True                  # the picture shows both marks
        doc.recompute()
        strip.refresh(force=True)
        qwait(150)
        smoke.shot("11_navigator_status.png")


def run(smoke):
    for scenario in (nested_occurrences, gate_layers, chains_on_a_sketch, navigator):
        try:
            scenario(smoke)
        except Exception:
            smoke.check(f"selection: {scenario.__name__}", False, traceback.format_exc().splitlines()[-1])
            smoke.info[f"traceback {scenario.__name__}"] = traceback.format_exc()

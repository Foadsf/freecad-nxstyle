# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of the user's own setup in NX-Style, called from smoke.py:

- Tools › Macros: FreeCAD's macro commands, and a macro command the user made (Tools › Customize › Macros, here
  through FreeCAD's own Gui.Command.createCustomCommand) as a button with its menu text; the button runs the macro;
  once the command is removed again the button is gone (negative control)."""

import os
import traceback

import FreeCAD as App
import FreeCADGui as Gui

MARK = "User parameter:BaseApp/NXStyleSmoke"
MACRO_FILE = "nxstyle_smoke_macro.FCMacro"


def tab_buttons(smoke, tab):
    """{command: button} of the ribbon page of one tab."""
    from .ribbon import CommandButton
    r = smoke.shell.ribbon
    names = r.tab_names()
    if tab not in names:
        return {}
    page = r.stack.widget(names.index(tab))
    return {b.command: b for b in page.findChildren(CommandButton)}


def rebuild(smoke):
    smoke.shell.build_ribbon(smoke.shell.current_app)


def corner_image(view, why):
    """The top-right corner of the graphics window as drawn (FreeCAD's view cube sits there by default), or None
    when this Qt cannot read the window's framebuffer back; ``why`` collects the reason."""
    try:
        vp = view.graphicsView().viewport()
        why["viewport"] = vp.metaObject().className()
        img = vp.grabFramebuffer() if hasattr(vp, "grabFramebuffer") else vp.grab().toImage()
        if img.isNull():
            why["image"] = "null"
            return None
        s = min(170, img.width(), img.height())
        return img.copy(img.width() - s, 0, s, s)
    except Exception as e:
        why["error"] = f"{type(e).__name__}: {e}"
        return None


def changed_share(a, b):
    """Share of sampled pixels that differ between two images of the same size."""
    hits = total = 0
    for y in range(0, a.height(), 3):
        for x in range(0, a.width(), 3):
            total += 1
            hits += a.pixel(x, y) != b.pixel(x, y)
    return hits / total if total else 0.0


def run_view_cube(smoke):
    """View › Visualization › View Cube: a new profile has no cube (seeded off); the button switches FreeCAD's own
    cube on in the open view, ticks, and is kept in FreeCAD's preference; clicked again it is off. Controls: the
    corner image changes only with the cube, and a change made in Preferences (the parameter) moves the tick."""
    from .qt import QtWidgets
    from .tutorial import qtest
    doc = None
    try:
        from . import prefs
        view = smoke.view() if Gui.ActiveDocument is not None else None
        if view is None or not hasattr(view, "getViewer"):
            doc = App.newDocument("SmokeViewCube")
            import Part  # noqa: F401
            doc.addObject("Part::Box", "Box")
            doc.recompute()
            Gui.SendMsgToActiveView("ViewFit")
            qtest().qWait(300)
            view = smoke.view()
        viewer = view.getViewer()
        smoke.info["viewer has isEnabledNaviCube"] = hasattr(viewer, "isEnabledNaviCube")
        p = App.ParamGet(prefs.VIEW)
        start = p.GetBool("ShowNaviCube", True)
        b = tab_buttons(smoke, "View").get("NXStyle_ViewCube")
        smoke.check("View › Visualization › View Cube button, off in a new profile",
                    b is not None and b.nx_label == "View Cube" and b.isCheckable() and not b.isChecked()
                    and not start and smoke.shell.ribbon.locations.get("NXStyle_ViewCube") == "View › Visualization",
                    {"button": b is not None, "checked": b.isChecked() if b else None, "ShowNaviCube": start,
                     "where": smoke.shell.ribbon.locations.get("NXStyle_ViewCube")})
        if b is None:
            return
        smoke.shell.ribbon.select("View")
        QtWidgets.QApplication.processEvents()
        why = {}
        off_img = corner_image(view, why)
        b.click()
        qtest().qWait(400)
        on = (p.GetBool("ShowNaviCube", False), viewer.isEnabledNaviCube(), b.isChecked())
        on_img = corner_image(view, why)
        smoke.shot("view_cube_on.png")
        b.click()
        qtest().qWait(400)
        off = (p.GetBool("ShowNaviCube", True), viewer.isEnabledNaviCube(), b.isChecked())
        off_again = corner_image(view, why)
        smoke.info["view cube corner image"] = why
        smoke.check("View Cube on: FreeCAD's preference, the open view and the tick; off again on a second click",
                    on == (True, True, True) and off == (False, False, False),
                    {"on (parameter, view, tick)": on, "off": off})
        if off_img is None or on_img is None or off_again is None:
            smoke.skip("the view cube is drawn in the graphics window's corner", f"framebuffer not readable: {why}")
        else:
            with_cube, without = changed_share(off_img, on_img), changed_share(off_img, off_again)
            smoke.check("the view cube is drawn in the graphics window's corner (and gone again: control)",
                        with_cube > 0.05 and without < 0.01,
                        f"pixels changed with the cube {with_cube:.1%}, after switching it off {without:.1%}")
        # a change in Preferences (the same parameter) reaches the button's tick
        act = (Gui.Command.get("NXStyle_ViewCube").getAction() or [None])[0]
        p.SetBool("ShowNaviCube", True)
        qtest().qWait(300)
        ticked = (b.isChecked(), act.isChecked() if act else None)
        p.SetBool("ShowNaviCube", False)
        qtest().qWait(300)
        unticked = (b.isChecked(), act.isChecked() if act else None)
        smoke.check("a change made in Preferences moves the View Cube tick",
                    ticked == (True, True) and unticked == (False, False),
                    {"after on (button, action)": ticked, "after off": unticked})
        smoke.shell.ribbon.select("Home")
    except Exception:
        smoke.check("view cube scenario ran", False, traceback.format_exc().splitlines()[-1])
    finally:
        if doc is not None:
            App.closeDocument(doc.Name)


def run_macros(smoke):
    try:
        known = set(Gui.listCommands())
        smoke.info["macro commands in this FreeCAD"] = sorted(n for n in known if "Macro" in n)
        tools = tab_buttons(smoke, "Tools")
        fixed = ["Std_DlgMacroExecute", "Std_DlgMacroRecord", "Std_DlgMacroExecuteDirect"]
        fixed += ["Std_MacroStopRecord"] if "Std_MacroStopRecord" in known else []
        smoke.check("Tools › Macros: Macros…, Record, Run Current (and Stop where FreeCAD has Std_MacroStopRecord)",
                    all(c in tools for c in fixed),
                    {c: c in tools for c in fixed})
        if not hasattr(Gui.Command, "createCustomCommand"):
            smoke.skip("a macro command of the user's own as a Tools › Macros button",
                       "this FreeCAD has no Gui.Command.createCustomCommand")
            return
        path = os.path.join(App.getUserMacroDir(True), MACRO_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("import FreeCAD\n"
                    f"p = FreeCAD.ParamGet({MARK!r})\n"
                    "p.SetInt('Runs', p.GetInt('Runs', 0) + 1)\n")
        App.ParamGet(MARK).SetInt("Runs", 0)
        name = Gui.Command.createCustomCommand(MACRO_FILE, "Smoke Macro", "Runs the smoke test's macro")
        smoke.info["user macro command"] = name
        before = "Std_Macro_" in "".join(tab_buttons(smoke, "Tools"))
        rebuild(smoke)
        smoke.shell.ribbon.select("Tools")
        b = tab_buttons(smoke, "Tools").get(name)
        smoke.check("a macro command of the user's own is a Tools › Macros button with its menu text",
                    b is not None and b.nx_label == "Smoke Macro" and smoke.shell.ribbon.locations.get(name)
                    == "Tools › Macros" and not before,
                    {"command": name, "label": b.nx_label if b else None,
                     "where": smoke.shell.ribbon.locations.get(name), "a macro button before": before})
        smoke.shot("user_macro_button.png", smoke.shell.ribbon)
        if b is not None:
            b.click()
        smoke.check("the macro button runs the macro", App.ParamGet(MARK).GetInt("Runs", 0) == 1,
                    f"runs: {App.ParamGet(MARK).GetInt('Runs', 0)}")
        # negative control: the button follows the command, not the group
        if hasattr(Gui.Command, "removeCustomCommand"):
            Gui.Command.removeCustomCommand(name)
            rebuild(smoke)
            gone = name not in tab_buttons(smoke, "Tools")
            smoke.check("with the macro command removed its button is gone (negative control)", gone,
                        sorted(c for c in tab_buttons(smoke, "Tools") if c.startswith("Std_Macro_")))
        smoke.shell.ribbon.select("Home")
    except Exception:
        smoke.check("macros scenario ran", False, traceback.format_exc().splitlines()[-1])

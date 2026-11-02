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

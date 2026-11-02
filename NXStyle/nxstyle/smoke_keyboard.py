# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native keyboard acceptance. User actions below use Qt key events only."""
import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtWidgets
from .smoke import decode


def qtest():
    try:
        from PySide6.QtTest import QTest
    except ImportError:
        from PySide2.QtTest import QTest
    return QTest


def run(smoke):
    from . import keyboard_selection, shortcuts, command_help
    shell, app = smoke.shell, QtWidgets.QApplication.instance()
    access, mw = shell.keyboard, shell.mw
    mw.activateWindow()
    if hasattr(app, "setActiveWindow"):
        app.setActiveWindow(mw)

    def key(sequence, target=None):
        k, mods = decode(sequence)
        qtest().keyClick(target or app.focusWidget() or mw, k, mods)
        qtest().qWait(120)

    access.focus_view()
    tested, bad = smoke.press_keys("global")
    smoke.check("access shortcuts dispatch without ambiguity", tested == 10 and not bad, (tested, bad))
    key("F10")
    smoke.check("F10 focuses ribbon tabs", app.focusWidget() is shell.ribbon.tabs)
    key("Down")
    focus = app.focusWidget()
    smoke.check("Down enters enabled ribbon control", isinstance(focus, QtWidgets.QToolButton), str(focus))
    key("Tab")
    smoke.check("Tab advances ribbon focus", app.focusWidget() is not focus)
    key("Esc")
    for seq, area in (("Alt+4", shell.resource_bar), ("Alt+5", shell.border_bar)):
        key(seq)
        smoke.check(seq + " focuses toolbar", area.isAncestorOf(app.focusWidget()), str(app.focusWidget()))
    key("Alt+1")
    dock = mw.findChild(QtWidgets.QDockWidget, "Model")
    smoke.check("Alt+1 focuses navigator", dock is not None and dock.isAncestorOf(app.focusWidget()), str(app.focusWidget()))
    key("Alt+3")
    graphics = Gui.ActiveDocument.ActiveView.graphicsView()
    smoke.check("Alt+3 focuses graphics", app.focusWidget() in (graphics, graphics.viewport()), str(app.focusWidget()))
    before = smoke.camera()
    key("Right")
    smoke.check("keyboard rotates native camera", before[0] != smoke.camera()[0])
    before = smoke.camera()
    key("Shift+Right")
    smoke.check("keyboard pans native camera", before[1] != smoke.camera()[1])
    before = smoke.camera()
    key("-")
    smoke.check("keyboard zooms native camera", before[2] != smoke.camera()[2])
    key("Ctrl+Space")
    smoke.check("Ctrl+Space focuses Finder", app.focusWidget() is shell.finder)
    qtest().keyClicks(shell.finder, "xras")
    before = smoke.camera()
    key("Left")
    smoke.check("typed letters and arrows stay in Finder", shell.finder.text() == "xras" and before == smoke.camera())
    key("Esc")
    key("Ctrl+Shift+Space")
    dialog = keyboard_selection._dialog
    smoke.check("keyboard opens named geometry selector", dialog is not None and dialog.isVisible())
    if dialog is not None:
        if hasattr(app, "setActiveWindow"):
            app.setActiveWindow(dialog)  # hidden test desktop has no foreground window
        # Navigate its mnemonic buddies and lists; do not invoke selection methods.
        key("Alt+F", dialog)
        qtest().keyClicks(app.focusWidget(), "Box")
        key("Alt+O", dialog)
        key("Home")
        key("Alt+T", dialog)
        smoke.check("selector type mnemonic focuses combo", app.focusWidget() is dialog.kind)
        key("Home")
        key("Down")
        key("Alt+G", dialog)
        key("Home")
        key("Return")
        selected = [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]
        smoke.check("keyboard selects native Box.Face1", any(n == "Box" and "Face1" in subs for n, subs in selected), (selected, dialog.status.text()))
        smoke.shot("keyboard-selection.png", dialog)
        key("Esc", dialog)
    if hasattr(app, "setActiveWindow"):
        app.setActiveWindow(mw)
    key("Alt+3", mw)
    key("End")
    key("Ctrl+F")
    Gui.Selection.clearSelection()
    key("F12")
    smoke.check("F12 enables visible keyboard pointer", access.pointer_view is not None and access.mark.isVisible())
    if access.pointer_view is not None:
        key("Return")
        selected = [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]
        smoke.check("keyboard pointer clicks native visible solid", any(n == "Box" for n, _ in selected), selected)
        start = QtCore.QPoint(access.point)
        key("Shift+Right")
        smoke.check("pointer fine movement is one pixel", access.point.x() == start.x() + 1)
        key("Ctrl+Return")
        smoke.check("keyboard starts native pointer drag", access.dragging)
        key("Right")
        key("Ctrl+Return")
        smoke.check("keyboard releases native pointer drag", not access.dragging)
        smoke.shot("keyboard-pointer.png")
        key("Esc")
        smoke.check("Escape removes pointer", access.pointer_view is None)
    keys = command_help.shortcut_text("Std_ViewFitAll")
    smoke.check("live tooltip includes NX fit shortcut", "Ctrl+F" in keys, keys)
    manager = shortcuts.instance()
    action = manager.targets[shortcuts.norm("Ctrl+F")]
    old = action.shortcuts()
    action.setShortcuts([])
    hidden = command_help.shortcut_text("Std_ViewFitAll")
    smoke.check("negative control detects removed tooltip shortcut", "Ctrl+F" not in hidden, hidden)
    action.setShortcuts(old)
    key("Ctrl+Alt+K")
    smoke.check("keyboard help opens", hasattr(access, "help_dialog") and access.help_dialog.isVisible())
    if hasattr(access, "help_dialog"):
        key("Esc", access.help_dialog)
    if hasattr(app, "setActiveWindow"):
        app.setActiveWindow(mw)
    access.focus_view()
    # Create a parametric solid through Finder, then Tab through the real task panel.
    from . import primitive_ui
    Gui.Selection.clearSelection()
    key("Ctrl+Space")
    qtest().keyClicks(shell.finder, "NXStyle_Block")
    key("Return", shell.finder)
    qtest().qWait(500)
    panel = primitive_ui.current()
    smoke.check("Finder Enter starts native Block task", panel is not None)
    if panel is not None:
        task_action = shortcuts.instance().targets[shortcuts.norm("Alt+2")]
        task_hits = []
        def task_hit():
            task_hits.append(True)
        task_action.triggered.connect(task_hit)
        key("Alt+2", mw)
        task_action.triggered.disconnect(task_hit)
        tasks = mw.findChild(QtWidgets.QDockWidget, "Tasks")
        smoke.info["task focus diagnostics"] = {
            "triggered": task_hits, "enabled": task_action.isEnabled(),
            "active_window": str(app.activeWindow()), "dock": str(tasks),
            "children": [] if tasks is None else [(w.objectName(), type(w).__name__, w.isVisible(), str(w.focusPolicy()))
                                                    for w in tasks.findChildren(QtWidgets.QWidget)][:60]}
        smoke.check("Alt+2 focuses active task", tasks is not None and tasks.isAncestorOf(app.focusWidget()), str(app.focusWidget()))

        def tab_to(widget):
            for _ in range(180):
                focused = app.focusWidget()
                if focused is widget or (focused is not None and widget.isAncestorOf(focused)):
                    return True
                qtest().keyClick(focused or mw, *decode("Tab"))
                qtest().qWait(15)
            return False

        reached = True
        for field, value in zip(panel.dims.values(), (17, 13, 11)):
            reached = tab_to(field) and reached
            if not reached:
                break
            key("Ctrl+A")
            qtest().keyClicks(app.focusWidget(), str(value))
            key("Tab")
        qtest().qWait(400)
        ok = primitive_ui._dialog_button(QtWidgets.QDialogButtonBox.Ok)
        reached = ok is not None and tab_to(ok) and reached
        feature_name = panel.feature_name
        if reached:
            key("Space")
        qtest().qWait(500)
        feature = App.ActiveDocument.getObject(feature_name) if feature_name else None
        smoke.check("keyboard-only typed Block commits 17 x 13 x 11", reached and primitive_ui.current() is None
                    and feature is not None and abs(feature.Shape.Volume - 2431) < 1e-6,
                    (reached, feature_name, feature.Shape.Volume if feature else None))
        if primitive_ui.current() is not None:
            primitive_ui.current().reject()  # failure cleanup only
        elif feature is not None:
            key("Alt+3", mw)
            key("Ctrl+Z")
            smoke.check("keyboard Undo removes created feature", App.ActiveDocument.getObject(feature_name) is None)
            key("Ctrl+Y")
            smoke.check("keyboard Redo restores created feature", App.ActiveDocument.getObject(feature_name) is not None)


def sketch(smoke):
    from . import sketch_ui
    access = smoke.shell.keyboard
    app = QtWidgets.QApplication.instance()
    model = sketch_ui.edited_sketch()
    if model is None:
        smoke.check("keyboard rectangle has an active sketch", False)
        return
    access.focus_view()
    before = model.GeometryCount

    def key(sequence, count=1):
        for _ in range(count):
            qtest().keyClick(app.focusWidget(), *decode(sequence))
            qtest().qWait(25)

    key("R")
    qtest().qWait(250)
    key("F12")
    key("Left", 8)
    key("Up", 6)
    key("Return")
    key("Right", 18)
    key("Down", 12)
    key("Return")
    qtest().qWait(250)
    smoke.check("keyboard pointer creates native four-edge rectangle", model.GeometryCount == before + 4,
                (before, model.GeometryCount))
    smoke.shot("keyboard-sketch.png")
    key("Esc")  # stop keyboard pointer
    key("Esc")  # stop native rectangle command
    smoke.check("keyboard rectangle exits without held pointer", access.pointer_view is None and not access.dragging)

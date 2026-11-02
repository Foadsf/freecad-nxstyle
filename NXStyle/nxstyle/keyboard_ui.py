# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keyboard access to shell areas and the existing graphics interaction tools.

The pointer translates keys to normal viewport events. Geometry creation, picking,
selection gates and undo remain in FreeCAD and the existing NXStyle tools.
"""
import html

from . import config, theme
from .qt import QtCore, QtGui, QtWidgets, Qt, mouse_event

_instance = None
ARROWS = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}


class PointerMark(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(33, 33)
        self.setAccessibleName("Keyboard pointer")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        for color, width in (("panel", 4), ("accent", 2)):
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.color(color)), width))
            painter.drawEllipse(10, 10, 12, 12)
            painter.drawLine(16, 0, 16, 9)
            painter.drawLine(16, 23, 16, 32)
            painter.drawLine(0, 16, 9, 16)
            painter.drawLine(23, 16, 32, 16)
        painter.end()


class KeyboardAccess(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.mw)
        self.shell = shell
        self.previous = None
        self.pointer_view = None
        self.mark = None
        self.point = QtCore.QPoint()
        self.dragging = False
        self.replaying = False
        self.swallowed = set()      # keys whose press the pointer took: their release is the pointer's too
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.prepare_controls()

    @staticmethod
    def tab_stop(widget):
        """Tab reaches a button that toolbars made NoFocus; a click still leaves the focus where it was."""
        if not widget.focusPolicy() & Qt.TabFocus:
            widget.setFocusPolicy(Qt.TabFocus)

    def prepare_controls(self):
        for area in (self.shell.ribbon, self.shell.border_bar, self.shell.resource_bar):
            for button in area.findChildren(QtWidgets.QToolButton):
                self.tab_stop(button)
                if not button.accessibleName():
                    button.setAccessibleName(button.text().replace("&", "").replace("\n", " ") or button.toolTip())
        self.tab_stop(self.shell.ribbon.tabs)
        self.shell.ribbon.tabs.setAccessibleName("Ribbon tabs")
        self.shell.ribbon.collapse_button.setAccessibleName("Collapse or expand ribbon")

    def remember_focus(self):
        focus = QtWidgets.QApplication.focusWidget()
        if focus is not None and focus is not self.shell.finder:
            self.previous = focus

    def restore_focus(self):
        self.shell.ribbon.hide_popup()
        try:
            if self.previous is not None and self.previous.isVisible() and self.previous.isEnabled():
                self.previous.setFocus(Qt.ShortcutFocusReason)
                return
        except RuntimeError:
            pass
        self.focus_view()

    def focus_finder(self):
        self.remember_focus()
        self.shell.finder.setFocus(Qt.ShortcutFocusReason)
        self.shell.finder.selectAll()

    def focus_ribbon(self):
        self.remember_focus()
        self.prepare_controls()
        self.shell.ribbon.tabs.setFocus(Qt.ShortcutFocusReason)

    def focus_bar(self, bar):
        self.prepare_controls()
        first = next((b for b in bar.findChildren(QtWidgets.QToolButton) if b.isVisible() and b.isEnabled()), None)
        if first is not None:
            first.setFocus(Qt.ShortcutFocusReason)

    def focus_dock(self, name):
        dock = self.shell.mw.findChild(QtWidgets.QDockWidget, name)
        if dock is None:
            return
        dock.show()
        dock.raise_()
        dock.window().activateWindow()

        def enter():
            widgets = dock.findChildren(QtWidgets.QTreeWidget) if name == "Model" else []
            widgets += self.dock_controls(dock)
            for widget in widgets:
                if widget.isVisible() and widget.isEnabled() and widget.focusPolicy() & Qt.TabFocus:
                    widget.setFocus(Qt.ShortcutFocusReason)
                    return
        QtCore.QTimer.singleShot(0, enter)

    @staticmethod
    def dock_controls(dock):
        """The dock's controls in the order they were made. (Not QWidget.nextInFocusChain: walking the chain from
        Python left every PySide wrapper under FreeCAD's main window 'already deleted', measured 2026-11-02.)"""
        types = (QtWidgets.QAbstractButton, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox,
                 QtWidgets.QLineEdit, QtWidgets.QAbstractItemView, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)
        controls = []
        for widget in dock.findChildren(QtWidgets.QWidget):
            if not isinstance(widget, types) or not widget.isVisible() or not widget.isEnabled():
                continue
            if not widget.focusPolicy() & Qt.TabFocus:
                continue
            if isinstance(widget, QtWidgets.QLineEdit) and isinstance(
                    widget.parentWidget(), (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
                continue  # one tab stop for a compound quantity/combo field
            controls.append(widget)
        return controls

    def nav(self):
        return self.shell.navigation.filter_for_active_view()

    def in_pointer_view(self, widget):
        """Is widget the pointer's view or inside it? Sketcher's on-view fields are: EditableDatumLabel parents
        them to the viewer's parent, and FreeCAD gives one the focus on every mouse move of a sketch tool
        (DrawSketchController::afterEnforceControlParameters), so the pointer's own moves put the focus there."""
        nav = self.pointer_view
        if nav is None or not isinstance(widget, QtWidgets.QWidget):
            return False
        host = nav.view.graphicsView().parentWidget()
        return widget is host or (host is not None and host.isAncestorOf(widget))

    def focus_view(self):
        nav = self.nav()
        if nav is not None:
            nav.view.graphicsView().setFocus(Qt.ShortcutFocusReason)

    def toggle_pointer(self):
        if self.pointer_view is not None:
            self.stop_pointer()
            return
        nav = self.nav()
        if nav is None:
            return
        self.pointer_view = nav
        self.point = nav.widget.rect().center()
        self.mark = PointerMark(nav.widget)
        self.focus_view()
        self.move_pointer(0, 0)
        self.shell.mw.statusBar().showMessage(
            "Keyboard pointer: arrows move; Shift fine; Ctrl fast; Enter click; Ctrl+Enter drag; "
            "Space middle click; Menu/Shift+F10 right click; F12/Esc stop")

    def _send(self, kind, button=Qt.NoButton, buttons=Qt.NoButton):
        nav = self.pointer_view
        if nav is None:
            return
        self.replaying = True
        try:
            QtWidgets.QApplication.sendEvent(nav.widget, mouse_event(kind, self.point, button, buttons, Qt.NoModifier))
        finally:
            self.replaying = False

    def move_pointer(self, dx, dy):
        rect = self.pointer_view.widget.rect()
        self.point.setX(max(0, min(rect.width() - 1, self.point.x() + dx)))
        self.point.setY(max(0, min(rect.height() - 1, self.point.y() + dy)))
        self.mark.move(self.point - QtCore.QPoint(16, 16))
        self.mark.show()
        self.mark.raise_()
        self._send(QtCore.QEvent.MouseMove, buttons=Qt.LeftButton if self.dragging else Qt.NoButton)

    def click_pointer(self, button):
        if self.dragging:
            self._send(QtCore.QEvent.MouseButtonRelease, Qt.LeftButton)
            self.dragging = False
            return
        self._send(QtCore.QEvent.MouseButtonPress, button, button)
        self._send(QtCore.QEvent.MouseButtonRelease, button)

    def stop_pointer(self):
        try:
            if self.dragging:
                self._send(QtCore.QEvent.MouseButtonRelease, Qt.LeftButton)
            if self.mark is not None:
                self.mark.hide()
                self.mark.deleteLater()
        except RuntimeError:  # view closed during an interaction
            pass
        self.dragging = False
        self.pointer_view = None
        self.mark = None
        self.shell.mw.statusBar().clearMessage()

    def ribbon_controls(self):
        r = self.shell.ribbon
        buttons = [r.file_button] + r.qat.findChildren(QtWidgets.QToolButton) + [r.tabs, self.shell.finder, r.collapse_button]
        page = r.stack.currentWidget()
        if page is not None:
            buttons += page.findChildren(QtWidgets.QToolButton)
        return [b for b in buttons if b.isVisible() and b.isEnabled()]

    def eventFilter(self, obj, ev):
        if self.replaying:
            return False
        try:
            return self._event(obj, ev)
        except RuntimeError:  # Qt may deliver a final event while a view or dock is being deleted
            self.stop_pointer()
            return False

    def _event(self, obj, ev):
        kind = ev.type()
        if kind == QtCore.QEvent.ToolTip and isinstance(obj, QtWidgets.QToolButton) and obj.objectName() != "NXRibbonButton":
            from . import command_help
            for area, command in ((self.shell.resource_bar, "NXStyle_FocusResourceBar"),
                                  (self.shell.border_bar, "NXStyle_FocusSelectionBar"),
                                  (self.shell.ribbon, "NXStyle_FocusRibbon")):
                if area.isAncestorOf(obj):
                    base = getattr(obj, "_nx_keyboard_tip", None)
                    if base is None:
                        base = obj.toolTip() or obj.text().replace("&", "") or obj.accessibleName()
                        obj._nx_keyboard_tip = base
                    keys = command_help.shortcut_text(command)
                    obj.setToolTip(base + ("\nKeyboard: " + keys + ", Tab / Shift+Tab, Space" if keys else ""))
                    break
        if kind == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QToolButton):
            if self.shell.mw.isAncestorOf(obj):
                self.tab_stop(obj)
        if self.pointer_view is not None and kind == QtCore.QEvent.Hide and obj is self.pointer_view.widget:
            self.stop_pointer()
        if self.pointer_view is not None and kind == QtCore.QEvent.ApplicationDeactivate:
            self.stop_pointer()
        if self.pointer_view is not None and self.dragging and kind == QtCore.QEvent.FocusOut:
            # Qt names the new focus widget before FocusOut: an on-view field taking it keeps the drag
            if self.in_pointer_view(obj) and not self.in_pointer_view(QtWidgets.QApplication.focusWidget()):
                self.click_pointer(Qt.LeftButton)
        if kind == QtCore.QEvent.KeyRelease and ev.key() in self.swallowed:
            # The release of a key the pointer took: Sketcher's DrawSketchKeyboardManager also reads releases,
            # and a Return release keeps it typing into the on-view field for 2 s, so Escape did not reach the tool
            if not ev.isAutoRepeat():
                self.swallowed.discard(ev.key())
            return True
        if kind not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
            return False
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        if kind == QtCore.QEvent.ShortcutOverride:
            from . import shortcuts
            manager = shortcuts.instance()
            if manager is not None:
                sequence = shortcuts.norm(shortcuts.event_key(ev))
                for entry in manager.entries:
                    if entry.context == "global" and entry.resolved:
                        action = manager.targets.get(shortcuts.norm(entry.keys))
                        if action is not None and sequence in [shortcuts.norm(s.toString()) for s in action.shortcuts()]:
                            shortcuts.enable_if_active(entry.resolved, action)
                            # Text inputs can otherwise consume Alt+digits before
                            # Qt dispatches workspace-focus actions. Keep native
                            # QAction dispatch, including user-reassigned keys.
                            ev.ignore()
                            return True
        key, mods = ev.key(), ev.modifiers()
        tasks = self.shell.mw.findChild(QtWidgets.QDockWidget, "Tasks")
        if tasks is not None and isinstance(obj, QtWidgets.QWidget) and tasks.isAncestorOf(obj):
            if key in (Qt.Key_Tab, Qt.Key_Backtab):
                editor = obj
                while editor is not None and editor is not tasks:
                    if isinstance(editor, (QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit, QtWidgets.QTableView)):
                        if not mods & Qt.ControlModifier:
                            return False  # text indentation and table-cell navigation stay native
                        break
                    editor = editor.parentWidget()
                if kind == QtCore.QEvent.ShortcutOverride:
                    ev.accept()
                    return True
                controls = self.dock_controls(tasks)
                current = next((i for i, w in enumerate(controls) if w is obj or w.isAncestorOf(obj)), -1)
                if controls:
                    step = -1 if key == Qt.Key_Backtab or mods & Qt.ShiftModifier else 1
                    target = controls[(current + step) % len(controls)]
                    target.setFocus(Qt.TabFocusReason)
                    parent = target.parentWidget()
                    while parent is not None and parent is not tasks:
                        if isinstance(parent, QtWidgets.QScrollArea):
                            parent.ensureWidgetVisible(target)
                        parent = parent.parentWidget()
                return True
        r = self.shell.ribbon
        ribbon_area = (isinstance(obj, QtWidgets.QWidget) and
                       (r.isAncestorOf(obj) or obj is r.tabs or
                        (r._popup is not None and r._popup.isAncestorOf(obj))))
        toolbar_button = isinstance(obj, QtWidgets.QToolButton) and (
            self.shell.resource_bar.isAncestorOf(obj) or self.shell.border_bar.isAncestorOf(obj))
        if toolbar_button and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down):
            if kind == QtCore.QEvent.ShortcutOverride:
                ev.accept()
                return True
            if obj.menu() is not None:
                obj.menu().popup(obj.mapToGlobal(QtCore.QPoint(0, obj.height())))
            elif key != Qt.Key_Down:
                obj.click()
            return True
        if ribbon_area:
            handled = (key in (Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape) or
                       (obj is r.tabs and key in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter)) or
                       (isinstance(obj, QtWidgets.QToolButton) and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down)))
            if handled and kind == QtCore.QEvent.ShortcutOverride:
                ev.accept()
                return True
            if handled:
                if key == Qt.Key_Escape:
                    self.shell.finder.completer.popup().hide()
                    self.shell.finder.clear()
                    self.restore_focus()
                elif obj is r.tabs and (key in (Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter) or
                                       (key == Qt.Key_Tab and not mods & Qt.ShiftModifier)):
                    if r.is_collapsed():
                        r.show_popup()
                    self.prepare_controls()
                    page = r.stack.currentWidget()
                    buttons = [] if page is None else [b for b in page.findChildren(QtWidgets.QToolButton)
                                                       if b.isVisible() and b.isEnabled()]
                    if buttons:
                        buttons[0].setFocus(Qt.TabFocusReason)
                elif key in (Qt.Key_Tab, Qt.Key_Backtab):
                    controls = self.ribbon_controls()
                    step = -1 if key == Qt.Key_Backtab or mods & Qt.ShiftModifier else 1
                    index = controls.index(obj) if obj in controls else -1
                    if controls:
                        controls[(index + step) % len(controls)].setFocus(Qt.TabFocusReason)
                elif isinstance(obj, QtWidgets.QToolButton):
                    if obj.menu() is not None and (key == Qt.Key_Down or obj.popupMode() == QtWidgets.QToolButton.InstantPopup):
                        obj.menu().popup(obj.mapToGlobal(QtCore.QPoint(0, obj.height())))
                        first = next((a for a in obj.menu().actions() if a.isEnabled() and not a.isSeparator()), None)
                        if first is not None:
                            obj.menu().setActiveAction(first)
                    elif key != Qt.Key_Down:
                        obj.click()
                ev.accept()
                return True
        nav = self.nav()
        if nav is None:
            return False
        if self.pointer_view is not None:
            if not self.in_pointer_view(obj):
                return False  # typed fields, trees, menus and task dialogs retain their own keys
            if self.pointer_view is not nav:
                self.stop_pointer()
                return False
            context_key = key == Qt.Key_Menu or (key == Qt.Key_F10 and mods == Qt.ShiftModifier)
            handled = key in ARROWS or context_key or key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Escape)
            if not handled:
                return False
            if kind == QtCore.QEvent.ShortcutOverride:
                ev.accept()
                return True
            self.swallowed.add(key)
            if ev.isAutoRepeat() and key not in ARROWS:
                return True
            if key in ARROWS:
                dx, dy = ARROWS[key]
                step = 1 if mods & Qt.ShiftModifier else 30 if mods & Qt.ControlModifier else 10
                self.move_pointer(dx * step, dy * step)
            elif key == Qt.Key_Escape:
                self.stop_pointer()
            elif key in (Qt.Key_Return, Qt.Key_Enter) and mods & Qt.ControlModifier:
                if self.dragging:
                    self.click_pointer(Qt.LeftButton)
                else:
                    self._send(QtCore.QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton)
                    self.dragging = True
            else:
                button = Qt.MiddleButton if key == Qt.Key_Space else Qt.RightButton if context_key else Qt.LeftButton
                self.click_pointer(button)
            return True
        # Alt+arrows rotate. FreeCAD's own view keys stay: the arrows pan (with any modifier but these),
        # PageUp/PageDown zoom, Shift+Left/Right turn the view 90 degrees, Ctrl+arrows toggle the dock overlays
        if obj not in (nav.widget, nav.view.graphicsView()) or mods != Qt.AltModifier or key not in ARROWS:
            return False
        if kind == QtCore.QEvent.ShortcutOverride:
            ev.accept()
            return True
        dx, dy = ARROWS[key]
        nav.rotate(dx * 10, dy * 10)
        return True

    def help(self):
        from . import shortcuts
        dialog = QtWidgets.QDialog(self.shell.mw)
        dialog.setObjectName("NXKeyboardHelp")
        dialog.setWindowTitle("Keyboard Access")
        dialog.resize(660, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        browser = QtWidgets.QTextBrowser(dialog)
        browser.setAccessibleName("Keyboard access instructions and current shortcuts")
        rows = []
        manager = shortcuts.instance()
        for entry in shortcuts.TABLE:
            keys = manager.shortcuts_for(entry.resolved) if manager and entry.resolved else []
            if keys:
                rows.append(f"<tr><td>{html.escape(entry.nx)}</td><td>{html.escape(', '.join(keys))}</td></tr>")
        from . import command_help

        def keys(command):      # as assigned now: none with "nx_shortcuts" off, or another the user chose
            return html.escape(command_help.shortcut_text(command) or "(no key: Tools › Keyboard Access)")
        browser.setHtml(f"<h2>Work without a mouse</h2><p>{keys('NXStyle_FocusRibbon')} enters the ribbon. Left/Right "
                        "choose tabs; Down enters a page; "
                        "Tab/Shift+Tab move between controls. Enter activates; Down opens a button's menu. "
                        "Escape returns to the previous area.</p><p>In the graphics view, Alt+arrows rotate; FreeCAD's "
                        "arrows pan and PageUp/PageDown zoom. These keys leave text fields and lists alone.</p>"
                        f"<p>{keys('NXStyle_KeyboardPointer')} toggles the keyboard pointer: "
                        "arrows move, Shift moves one pixel, Ctrl moves faster, Enter clicks, Ctrl+Enter starts/ends a "
                        "left drag, Space middle-clicks, Menu or Shift+F10 right-clicks. Escape stops the pointer; another Escape "
                        "can cancel the active command. Use typed dimensions whenever exact coordinates matter: in a sketch "
                        "tool, digits go to the focused on-view field and Enter clicks with that value.</p>"
                        f"<p>{keys('NXStyle_SelectGeometry')} selects named objects or subelements. Tab and Shift+Tab "
                        "traverse task fields in the form's order and stay in the panel; "
                        f"Space activates the focused button. {keys('NXStyle_CommandFinder')} finds commands, including "
                        "those without a direct key.</p>"
                        "<h3>Current assigned shortcuts</h3><table cellspacing='8'>" + "".join(rows) + "</table>")
        layout.addWidget(browser)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=dialog)
        box.rejected.connect(dialog.reject)
        layout.addWidget(box)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()
        browser.setFocus()
        self.help_dialog = dialog


class AccessCommand:
    def __init__(self, title, callback, needs_view=False):
        self.title, self.callback, self.needs_view = title, callback, needs_view

    def GetResources(self):
        return {"MenuText": self.title, "ToolTip": self.title + " (keyboard access)",
                "CmdType": "ForEdit",
                "Pixmap": config.resource("icons", "information.svg")}

    def IsActive(self):
        return _instance is not None and (not self.needs_view or _instance.nav() is not None)

    def Activated(self):
        if _instance is not None:
            self.callback(_instance)


def select_geometry(_access):
    from . import keyboard_selection
    keyboard_selection.show()


COMMANDS = {
    "NXStyle_CommandFinder": AccessCommand("Command Finder", lambda a: a.focus_finder()),
    "NXStyle_FocusRibbon": AccessCommand("Focus Ribbon", lambda a: a.focus_ribbon()),
    "NXStyle_FocusNavigator": AccessCommand("Focus Part Navigator", lambda a: a.focus_dock("Model")),
    "NXStyle_FocusTasks": AccessCommand("Focus Task Panel", lambda a: a.focus_dock("Tasks")),
    "NXStyle_FocusView": AccessCommand("Focus Graphics View", lambda a: a.focus_view(), True),
    "NXStyle_FocusResourceBar": AccessCommand("Focus Resource Bar", lambda a: a.focus_bar(a.shell.resource_bar)),
    "NXStyle_FocusSelectionBar": AccessCommand("Focus Selection Bar", lambda a: a.focus_bar(a.shell.border_bar)),
    "NXStyle_SelectGeometry": AccessCommand("Select Geometry by Name", select_geometry, True),
    "NXStyle_KeyboardHelp": AccessCommand("Keyboard Access Help", lambda a: a.help()),
    "NXStyle_KeyboardPointer": AccessCommand("Keyboard Pointer", lambda a: a.toggle_pointer(), True),
}


def install(shell):
    global _instance
    if _instance is not None:
        QtWidgets.QApplication.instance().removeEventFilter(_instance)
        _instance.stop_pointer()
    _instance = KeyboardAccess(shell)
    return _instance

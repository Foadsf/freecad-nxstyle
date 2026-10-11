# SPDX-License-Identifier: LGPL-2.1-or-later
"""An NX-style ribbon built from JSON specs and FreeCAD's own command actions."""

import FreeCADGui as Gui

from . import config
from .qt import QtCore, QtGui, QtWidgets, Qt

LARGE = 32
SMALL = 16
ROWS = 3


_sub_cache = {"count": -1, "index": {}}


def sub_actions():
    """objectName -> QAction for entries inside FreeCAD group commands.

    Some FreeCAD 'commands' (e.g. the draw styles) only exist as actions in a
    group command such as Std_DrawStyle; this lets specs name them directly.
    """
    names = Gui.listCommands()
    if _sub_cache["count"] != len(names):
        index = {}
        for n in names:
            try:
                acts = list(Gui.Command.get(n).getAction() or [])
            except Exception:
                continue
            for a in acts[1:]:
                key = a.objectName()
                if key and key not in index:
                    index[key] = a
        _sub_cache.update(count=len(names), index=index)
    return _sub_cache["index"]


def known_commands():
    return set(Gui.listCommands()) | set(sub_actions())


def trigger(name):
    """Run a command or a group sub-action by name."""
    acts = command_actions(name)
    if acts:
        acts[0].trigger()
    else:
        Gui.runCommand(name)


def is_enabled(name):
    acts = command_actions(name)
    return bool(acts) and acts[0].isEnabled()


def resolve(spec, known=None):
    """A command name or list of candidates -> first existing command name."""
    known = known if known is not None else known_commands()
    for name in ([spec] if isinstance(spec, str) else spec):
        if name in known:
            return name
    return None


def command_actions(name):
    try:
        cmd = Gui.Command.get(name)
    except Exception:
        cmd = None
    if cmd is not None:
        try:
            return list(cmd.getAction() or [])
        except Exception:
            return []
    sub = sub_actions().get(name)
    return [sub] if sub is not None else []


def command_icon(name):
    acts = command_actions(name)
    return acts[0].icon() if acts else QtGui.QIcon()


def clean_text(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").replace("...", "").strip()


class CommandButton(QtWidgets.QToolButton):
    """A ribbon button that mirrors a FreeCAD command's QAction.

    The button keeps its own NX label but follows the action's icon, enabled
    and checked state, and reuses the action's drop-down menu for FreeCAD
    group commands (e.g. the primitive or draw-style groups).
    """

    def __init__(self, name, label, size, parent=None, on_run=None):
        super().__init__(parent)
        self.command = name
        self.nx_label = label
        self.on_run = on_run
        acts = command_actions(name)
        self.action = acts[0] if acts else None
        self.setObjectName("NXRibbonButton")
        self.setAutoRaise(True)
        big = size == "large"
        self.setIconSize(QtCore.QSize(LARGE, LARGE) if big else QtCore.QSize(SMALL, SMALL))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if big else Qt.ToolButtonTextBesideIcon)
        self.setProperty("nxsize", size)
        if big:
            self.setMinimumWidth(52)
            self.setMaximumWidth(112)
        self.setText(self._wrap(label) if big else label)
        menu = self.action.menu() if self.action else None
        if menu is None and len(acts) > 1:
            menu = QtWidgets.QMenu(self)
            for a in acts[1:]:
                menu.addAction(a)
        if menu is not None:
            self.setMenu(menu)
            self.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
            if big:  # the drop-down arrow needs room next to the label
                self.setMaximumWidth(140)
        if big:
            fm = self.fontMetrics()
            widest = max(fm.horizontalAdvance(line) for line in self.text().split("\n"))
            self.setMinimumWidth(max(52, widest + (26 if menu is not None else 12)))
        self.clicked.connect(self._run)
        if self.action is not None:
            self.action.changed.connect(self._sync)
        self._sync()

    @staticmethod
    def _wrap(text):
        words = text.split()
        if len(words) < 2 or len(text) <= 9:
            return text
        mid = len(text) // 2
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - mid))
        return " ".join(words[:best]) + "\n" + " ".join(words[best:])

    def _sync(self):
        a = self.action
        if a is None:
            self.setEnabled(False)
            return
        try:
            self.setIcon(a.icon())
            self.setEnabled(a.isEnabled())
            self.setCheckable(a.isCheckable())
            if a.isCheckable():
                self.setChecked(a.isChecked())
            tip = clean_text(a.toolTip() or a.text())
            shortcut = a.shortcut().toString()
            freecad_name = clean_text(a.text())
            parts = [f"<b>{self.nx_label}</b>"]
            if freecad_name and freecad_name != self.nx_label:
                parts.append(f"FreeCAD: {freecad_name}")
            if shortcut:
                parts.append(f"Shortcut: {shortcut}")
            if tip and tip != freecad_name:
                parts.append(tip)
            self.setToolTip("<br>".join(parts))
        except RuntimeError:  # action deleted by FreeCAD (workbench reload)
            self.action = None

    def _run(self):
        if self.action is None:
            return
        if self.on_run:
            self.on_run(self.command)
        self.action.trigger()


class ActionButton(QtWidgets.QToolButton):
    """Ribbon button for a raw toolbar QAction (auto-generated ribbons)."""

    def __init__(self, action, size, parent=None):
        super().__init__(parent)
        self.setObjectName("NXRibbonButton")
        self.setAutoRaise(True)
        big = size == "large"
        self.setIconSize(QtCore.QSize(LARGE, LARGE) if big else QtCore.QSize(SMALL, SMALL))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if big else Qt.ToolButtonTextBesideIcon)
        self.setDefaultAction(action)
        if action.menu() is not None:
            self.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        if big:
            self.setMinimumWidth(52)
            self.setMaximumWidth(112)


class DropdownButton(QtWidgets.QToolButton):
    def __init__(self, label, entries, size, parent=None, on_run=None):
        super().__init__(parent)
        self.setObjectName("NXRibbonButton")
        self.setAutoRaise(True)
        big = size == "large"
        self.setIconSize(QtCore.QSize(LARGE, LARGE) if big else QtCore.QSize(SMALL, SMALL))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if big else Qt.ToolButtonTextBesideIcon)
        self.setText(label)
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self)
        for name, text in entries:
            act = command_actions(name)
            if not act:
                continue
            item = menu.addAction(act[0].icon(), text)
            item.setShortcut(act[0].shortcut())
            item.triggered.connect(lambda _=False, n=name: (on_run and on_run(n), trigger(n)))
        self.setMenu(menu)
        if entries:
            self.setIcon(command_icon(entries[0][0]))
        if big:
            self.setMinimumWidth(52)


class RibbonGroup(QtWidgets.QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("NXRibbonGroup")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 1)
        outer.setSpacing(0)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setSpacing(1)
        self.grid.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.grid, 1)
        label = QtWidgets.QLabel(title)
        label.setObjectName("NXRibbonGroupLabel")
        label.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        outer.addWidget(label)
        self._col = 0
        self._row = 0
        self.count = 0

    def add(self, widget, size):
        if size == "large":
            if self._row:
                self._col += 1
                self._row = 0
            self.grid.addWidget(widget, 0, self._col, ROWS, 1, Qt.AlignTop | Qt.AlignHCenter)
            self._col += 1
        else:
            self.grid.addWidget(widget, self._row, self._col, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
            self._row += 1
            if self._row == ROWS:
                self._row = 0
                self._col += 1
        self.count += 1


class RibbonPage(QtWidgets.QScrollArea):
    """A ribbon page that scrolls sideways with the wheel and shows edge
    arrows when the groups do not fit, instead of a scrollbar over the labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXRibbonPage")
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.arrows = []
        for arrow, step in ((Qt.LeftArrow, -1), (Qt.RightArrow, 1)):
            b = QtWidgets.QToolButton(self)
            b.setObjectName("NXRibbonScroll")
            b.setArrowType(arrow)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, s=step: self.scroll_by(s * 160))
            b.hide()
            self.arrows.append(b)
        self.horizontalScrollBar().rangeChanged.connect(lambda *_: self._update_arrows())
        self.horizontalScrollBar().valueChanged.connect(lambda *_: self._update_arrows())

    def scroll_by(self, dx):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() + dx)

    def wheelEvent(self, ev):
        delta = ev.angleDelta()
        self.scroll_by(-(delta.y() or delta.x()) // 2)
        ev.accept()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_arrows()

    def _update_arrows(self):
        bar = self.horizontalScrollBar()
        h = self.viewport().height()
        left, right = self.arrows
        left.setGeometry(0, 0, 16, h)
        right.setGeometry(self.width() - 16, 0, 16, h)
        left.setVisible(bar.value() > bar.minimum())
        right.setVisible(bar.value() < bar.maximum())
        left.raise_()
        right.raise_()


class Ribbon(QtWidgets.QWidget):
    """Tab row (File button, quick access toolbar, tabs, command finder) + pages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXRibbon")
        self.missing = []          # (tab, group, spec) entries that did not resolve
        self.locations = {}        # command -> "Tab > Group" (for the Command Finder)
        self.labels = {}           # command -> NX label
        self.on_run = None         # callback(command) for Repeat Command tracking
        self._collapsed = False
        self._contextual = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QtWidgets.QWidget(self)
        self.header.setObjectName("NXRibbonHeader")
        head = QtWidgets.QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 4, 0)
        head.setSpacing(2)

        self.file_button = QtWidgets.QToolButton(self.header)
        self.file_button.setObjectName("NXFileButton")
        self.file_button.setText("File")
        self.file_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        head.addWidget(self.file_button)

        self.qat = QtWidgets.QToolBar(self.header)
        self.qat.setObjectName("NXQuickAccess")
        self.qat.setIconSize(QtCore.QSize(SMALL, SMALL))
        head.addWidget(self.qat)

        self.tabs = QtWidgets.QTabBar(self.header)
        self.tabs.setObjectName("NXRibbonTabs")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBarDoubleClicked.connect(lambda _i: self.set_collapsed(not self._collapsed))
        self.tabs.tabBarClicked.connect(self._tab_clicked)
        head.addWidget(self.tabs)
        head.addStretch(1)

        self.corner = QtWidgets.QHBoxLayout()
        self.corner.setSpacing(4)
        head.addLayout(self.corner)

        self.collapse_button = QtWidgets.QToolButton(self.header)
        self.collapse_button.setObjectName("NXCollapseButton")
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.setArrowType(Qt.UpArrow)
        self.collapse_button.setToolTip("Collapse Ribbon (double-click a tab)")
        self.collapse_button.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        head.addWidget(self.collapse_button)

        root.addWidget(self.header)
        self.stack = QtWidgets.QStackedWidget(self)
        self.stack.setObjectName("NXRibbonStack")
        root.addWidget(self.stack)
        qss = config.resource("ribbon.qss")
        with open(qss, encoding="utf-8") as f:
            self.setStyleSheet(f.read())

    # ---------------------------------------------------------------- tabs
    def clear(self):
        while self.tabs.count():
            self.tabs.removeTab(0)
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.missing = []
        self.locations = {}
        self.labels = {}
        self._contextual = []

    def tab_names(self):
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def _tab_changed(self, index):
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    def _tab_clicked(self, index):
        if self._collapsed and index == self.tabs.currentIndex():
            self.set_collapsed(False)

    def set_collapsed(self, collapsed):
        self._collapsed = collapsed
        self.stack.setVisible(not collapsed)
        self.collapse_button.setArrowType(Qt.DownArrow if collapsed else Qt.UpArrow)

    def select(self, name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)
                return True
        return False

    def _page(self):
        area = RibbonPage(self.stack)
        inner = QtWidgets.QWidget()
        inner.setObjectName("NXRibbonPageInner")
        lay = QtWidgets.QHBoxLayout(inner)
        lay.setContentsMargins(2, 2, 2, 0)
        lay.setSpacing(0)
        area.setWidget(inner)
        return area, lay

    def add_tab(self, name, groups, index=None, contextual=False, known=None):
        """groups: list of (title, items) from a JSON spec, or (title, [QWidget...])."""
        known = known if known is not None else known_commands()
        area, lay = self._page()
        for gname, items in groups:
            group = RibbonGroup(gname)
            for item in items:
                widget, size = self._make(item, name, gname, known)
                if widget is not None:
                    group.add(widget, size)
            if group.count:
                lay.addWidget(group)
                sep = QtWidgets.QFrame()
                sep.setObjectName("NXRibbonSeparator")
                sep.setFrameShape(QtWidgets.QFrame.VLine)
                lay.addWidget(sep)
            else:
                group.deleteLater()
        lay.addStretch(1)
        area.setMinimumHeight(area.widget().sizeHint().height() + 2)
        if index is None:
            index = self.tabs.count()
        self.stack.insertWidget(index, area)
        self.tabs.insertTab(index, name)
        if contextual:
            self.tabs.setTabTextColor(index, QtGui.QColor("#007A87"))
            self._contextual.append(name)
        return index

    def remove_tab(self, name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                w = self.stack.widget(i)
                self.tabs.removeTab(i)
                self.stack.removeWidget(w)
                w.deleteLater()
                if name in self._contextual:
                    self._contextual.remove(name)
                return True
        return False

    def has_tab(self, name):
        return name in self.tab_names()

    def _register(self, cmd, label, tab, group):
        self.locations.setdefault(cmd, f"{tab} › {group}")
        self.labels.setdefault(cmd, label)

    def _label(self, item, cmd):
        if config.get().get("labels") == "freecad":
            acts = command_actions(cmd)
            if acts:
                return clean_text(acts[0].text())
        return item.get("label") or cmd

    def _make(self, item, tab, group, known):
        if isinstance(item, QtWidgets.QWidget):
            return item, item.property("nxsize") or "small"
        if isinstance(item, QAction_types()):
            return ActionButton(item, "small"), "small"
        size = item.get("size", "small")
        if "dropdown" in item:
            entries = []
            for sub in item["items"]:
                cmd = resolve(sub["cmd"], known)
                if cmd:
                    label = self._label(sub, cmd)
                    entries.append((cmd, label))
                    self._register(cmd, label, tab, group)
                elif not sub.get("optional"):
                    self.missing.append((tab, group, sub["cmd"]))
            if not entries:
                return None, size
            return DropdownButton(item["dropdown"], entries, size, on_run=self._ran), size
        cmd = resolve(item["cmd"], known)
        if not cmd:
            if not item.get("optional"):   # optional = only in newer FreeCAD versions
                self.missing.append((tab, group, item["cmd"]))
            return None, size
        label = self._label(item, cmd)
        self._register(cmd, label, tab, group)
        return CommandButton(cmd, label, size, on_run=self._ran), size

    def _ran(self, cmd):
        if self.on_run:
            self.on_run(cmd)


def QAction_types():
    from .qt import QAction
    return (QAction,)


def spec_groups(tab_spec):
    return [(g["name"], g.get("items", [])) for g in tab_spec.get("groups", [])]


def expand_tabs(spec):
    """Resolve {"include": "common:View"} entries against common.json."""
    common = {t["name"]: t for t in config.load_json("ribbons", "common.json")["tabs"]}
    tabs = []
    for t in spec.get("tabs", []):
        if "include" in t:
            src, _, name = t["include"].partition(":")
            if src == "common" and name in common:
                tabs.append(common[name])
        else:
            tabs.append(t)
    return tabs

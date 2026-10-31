# SPDX-License-Identifier: LGPL-2.1-or-later
"""An NX-style ribbon built from JSON specs and FreeCAD's own command actions."""

import FreeCADGui as Gui

from . import config, icon_theme, ribbon_layout, theme
from .qt import QAction, QtCore, QtGui, QtWidgets, Qt, exec_menu

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
            for a in acts:                 # a group lists only its entries; a plain command, its own action
                key = a.objectName()
                if key and key != n and key not in index:
                    index[key] = a
        _sub_cache.update(count=len(names), index=index)
    return _sub_cache["index"]


def known_commands():
    return set(Gui.listCommands()) | set(sub_actions())


def trigger(name):
    """Run a command or a group sub-action by name."""
    act = command_action(name)
    if act is not None:
        act.trigger()
    else:
        Gui.runCommand(name)


def is_enabled(name):
    act = command_action(name)
    return act is not None and act.isEnabled()


def resolve(spec, known=None):
    """A command name or list of candidates -> first existing command name."""
    known = known if known is not None else known_commands()
    for name in ([spec] if isinstance(spec, str) else spec):
        if name in known:
            return name
    return None


# Actions an add-on owns for its commands (e.g. Strata's, from strata.boot.actions()): FreeCAD makes a
# Python command's own QAction only once the command sits in a toolbar or menu, so these stand in.
HOST_ACTIONS = {}


def _themed_actions(actions, name):
    for action in actions:
        icon_theme.bind(action, action.objectName() or name)
    return actions


def command_actions(name):
    """FreeCAD's Command.getAction(): a plain command's own QAction, or a group command's entries (not the
    group's own action, see command_action); empty until FreeCAD has made the action (see provide_actions)."""
    if name in HOST_ACTIONS:
        return _themed_actions([HOST_ACTIONS[name]], name)
    try:
        cmd = Gui.Command.get(name)
    except Exception:
        cmd = None
    if cmd is not None:
        try:
            return _themed_actions(list(cmd.getAction() or []), name)
        except Exception:
            return []
    sub = sub_actions().get(name)
    return _themed_actions([sub], name) if sub is not None else []


def command_action(name):
    """The QAction a FreeCAD toolbar button shows for the command, or None.

    For a group command (Sketcher_CompLine, Sketcher_CompConstrainRadDia, ...) that is the group's own action:
    FreeCAD enables it with the command and, triggered, runs the remembered or default entry. getAction() lists
    only the entries, and the first entry is a different command with its own enabled state."""
    acts = command_actions(name)
    if not acts:
        return None
    first = acts[0]
    if name in HOST_ACTIONS or first.objectName() == name:
        return first
    group = first.actionGroup()                  # the group's QActionGroup, a child of its Gui::ActionGroup
    owner = group.parent() if group is not None else None
    # children(), not findChild(): on the Gui::ActionGroup (unknown to PySide, wrapped as a QObject) PySide6's
    # findChild hands back a wrapper whose C++ object counts as deleted (measured in FreeCAD 1.1.4)
    for child in owner.children() if owner is not None else []:
        if isinstance(child, QAction) and child.objectName() == name:
            return icon_theme.bind(child, name, entries=acts, owner=owner)
    return first


def set_group_default(name, entry):
    """Make the group command name's own action run entry (NX's default, e.g. Studio Spline's Through Points)
    until the user picks another entry from its drop-down, which FreeCAD then remembers. FreeCAD keeps the
    index on the group (Gui::ActionGroup's 'defaultAction', ActionGroup::onActivated) and shows its icon.
    Returns False when name is no group or has no such entry."""
    acts = command_actions(name)
    names = [a.objectName() for a in acts]
    own = command_action(name)
    group = acts[0].actionGroup() if acts else None
    if entry not in names or own is None or own is acts[0] or group is None or group.parent() is None:
        return False
    i = names.index(entry)
    group.parent().setProperty("defaultAction", i)
    own.setIcon(acts[i].icon())
    own.setToolTip(acts[i].toolTip())
    return True


# FreeCAD makes a command's QAction (Command::initAction) only when a toolbar or menu takes the command, and the
# workbenches do not place every command a ribbon names (Sketcher_CompLine and Sketcher_CompConstrainRadDia only
# with non-default Sketcher preferences). A custom toolbar of the workbench, hidden by the shell like every native
# toolbar, places them: FreeCAD's own mechanism (Tools > Customize), so FreeCAD makes the actions at activation.
# The shell then activates the workbench again (Shell.reactivate_workbench), as it does for its own commands.
RIBBON_TOOLBAR = "Custom_NXRibbon"


def provide_actions(names, reactivate):
    """Make FreeCAD create the QActions of these registered commands: list them in the active workbench's custom
    toolbar, then reactivate() the workbench so FreeCAD builds it. Returns the commands still without an action."""
    todo = [n for n in dict.fromkeys(names) if n not in HOST_ACTIONS and not command_actions(n)
            and Gui.Command.get(n) is not None]
    if not todo:
        return []
    import FreeCAD as App
    wb = Gui.activeWorkbench().name()
    p = App.ParamGet(f"User parameter:BaseApp/Workbench/{wb}/Toolbar/{RIBBON_TOOLBAR}")
    p.SetString("Name", "NX Ribbon Commands")
    p.SetBool("Active", True)
    for n in todo:
        p.SetString(n, n.split("_", 1)[0])     # the module FreeCAD loads if the command is not registered yet
    reactivate()
    return [n for n in todo if not command_actions(n)]


def command_icon(name):
    act = command_action(name)
    return act.icon() if act is not None else QtGui.QIcon()


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
        self.action = command_action(name)
        acts = command_actions(name)
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
        if menu is None and name not in HOST_ACTIONS and acts and acts[0].objectName() != name:
            menu = QtWidgets.QMenu(self)       # a group: every entry, as FreeCAD's toolbar drop-down lists them
            menu.addActions(acts)
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
        self.setAccessibleName(label)
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.entries = []
        menu = QtWidgets.QMenu(self)
        for name, text in entries:
            act = command_action(name)
            if act is None:
                continue
            self.entries.append((name, text))
            item = menu.addAction(act.icon(), text)
            item.setData(name)
            item.setShortcut(act.shortcut())
            item.triggered.connect(lambda _=False, n=name: (on_run and on_run(n), trigger(n)))
        self.setMenu(menu)
        if entries:
            self.setIcon(command_icon(entries[0][0]))
        if big:
            self.setMinimumWidth(52)


class RibbonGroup(QtWidgets.QFrame):
    """A titled group of buttons that can give up space in stages (``ribbon_layout``): full, compact
    (small buttons icon-only), collapsed (one button whose menu lists the commands) or overflow
    (hidden here, listed in the page's More menu)."""

    def __init__(self, title, parent=None, rank=0, step=None):
        super().__init__(parent)
        self.setObjectName("NXRibbonGroup")
        self.title = title
        self.rank = rank
        self.step = step                 # guided workflow step this group stands for (FEM), or None
        self.preference = ribbon_layout.AUTO
        self.stage = ribbon_layout.FULL
        self.separator = None
        self.items = []                  # (widget, size) in the order added
        self._widths = None
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 2)
        outer.setSpacing(0)
        self.body = QtWidgets.QWidget(self)
        self.body.setObjectName("NXRibbonGroupBody")
        self.grid = QtWidgets.QGridLayout(self.body)
        self.grid.setSpacing(2)
        self.grid.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.body, 1)
        self.collapsed_button = QtWidgets.QToolButton(self)
        self.collapsed_button.setObjectName("NXRibbonGroupButton")
        self.collapsed_button.setAutoRaise(True)
        self.collapsed_button.setIconSize(QtCore.QSize(LARGE, LARGE))
        self.collapsed_button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.collapsed_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.collapsed_button.setText(CommandButton._wrap(title))
        self.collapsed_button.setAccessibleName(f"{title} group")
        self.collapsed_button.setToolTip(f"<b>{title}</b><br>The group's commands; it is collapsed to make room")
        menu = QtWidgets.QMenu(self.collapsed_button)
        menu.aboutToShow.connect(lambda m=menu: (m.clear(), self.populate(m)))
        self.collapsed_button.setMenu(menu)
        self.collapsed_button.hide()
        outer.addWidget(self.collapsed_button, 1, Qt.AlignTop | Qt.AlignHCenter)
        self.label = QtWidgets.QLabel(title)
        self.label.setObjectName("NXRibbonGroupLabel")
        self.label.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        outer.addWidget(self.label)
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
        self.items.append((widget, size))
        if isinstance(widget, CommandButton):
            widget.setAccessibleName(widget.nx_label)
        if self.collapsed_button.icon().isNull() and isinstance(widget, QtWidgets.QToolButton):
            self.collapsed_button.setIcon(widget.icon())
        self.count += 1

    # ------------------------------------------------------------ commands
    def entries(self):
        """(command, label) of every command the group offers, in order (a drop-down's entries too)."""
        out = []
        for w, _size in self.items:
            if isinstance(w, CommandButton):
                out.append((w.command, w.nx_label))
            elif isinstance(w, DropdownButton):
                out += list(w.entries)
            elif isinstance(w, QtWidgets.QToolButton) and w.defaultAction() is not None:
                a = w.defaultAction()
                out.append((a.objectName() or clean_text(a.text()), clean_text(a.text())))
        return out

    def populate(self, menu):
        """Fill a menu with the group's commands; each entry clicks the real button (or runs the same
        action), so it behaves exactly like the button: same command, Repeat Command, state."""
        for w, _size in self.items:
            if isinstance(w, CommandButton):
                sub_menu = w.menu()
                if sub_menu is not None:
                    sub = menu.addMenu(w.icon(), w.nx_label)
                    sub.menuAction().setData(w.command)
                    target = sub.addAction(w.icon(), w.nx_label)
                    sub.addSeparator()
                    sub.addActions(sub_menu.actions())
                else:
                    target = menu.addAction(w.icon(), w.nx_label)
                target.setData(w.command)
                target.setEnabled(w.isEnabled())
                if w.isCheckable():
                    target.setCheckable(True)
                    target.setChecked(w.isChecked())
                target.triggered.connect(lambda _=False, b=w: b.click())
            elif isinstance(w, DropdownButton):
                sub = menu.addMenu(w.icon(), w.text())
                sub.addActions(w.menu().actions())
            elif isinstance(w, QtWidgets.QToolButton) and w.defaultAction() is not None:
                menu.addAction(w.defaultAction())

    def menu_commands(self, menu):
        """Commands a populated menu reaches, through its submenus too (for the layout checks)."""
        found = []
        for a in menu.actions():
            cmd = a.data() if isinstance(a.data(), str) else ""
            if a.menu() is not None:
                found += self.menu_commands(a.menu())
            if cmd:
                found.append(cmd)
            elif a.objectName():
                found.append(a.objectName())
        return found

    # ---------------------------------------------------------------- stages
    def set_stage(self, stage):
        self.stage = stage
        collapsed = stage == ribbon_layout.COLLAPSED
        compact = stage in (ribbon_layout.COMPACT, ribbon_layout.COLLAPSED)
        for w, size in self.items:
            if size != "large" and isinstance(w, QtWidgets.QToolButton):
                w.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon)
        self.body.setVisible(not collapsed)
        self.body.updateGeometry()
        self.collapsed_button.setVisible(collapsed)
        self.label.setVisible(not collapsed)
        shown = stage != ribbon_layout.OVERFLOW
        self.setVisible(shown)
        if self.separator is not None:
            self.separator.setVisible(shown)

    def can_collapse(self):
        """Only groups made of buttons can be listed in a menu."""
        return all(isinstance(w, QtWidgets.QToolButton) for w, _ in self.items)

    def widths(self):
        """Width (with the separator) in each stage, measured from the widgets' size hints."""
        if self._widths is None:
            current = self.stage
            self.ensurePolished()
            m = self.layout().contentsMargins()
            pad = m.left() + m.right() + (self.separator.sizeHint().width() if self.separator is not None else 0)
            out = {}
            # the grid itself, not the group's layout: that layout caches the body's size hint until a posted
            # layout request, so it would still report the full width just after the buttons went icon-only
            for stage in (ribbon_layout.FULL, ribbon_layout.COMPACT):
                self.set_stage(stage)
                self.grid.invalidate()
                out[stage] = max(self.grid.sizeHint().width(), self.label.sizeHint().width()) + pad
            out[ribbon_layout.COLLAPSED] = self.collapsed_button.sizeHint().width() + pad
            if not self.can_collapse():           # never collapse what a menu cannot hold
                out[ribbon_layout.COLLAPSED] = out[ribbon_layout.COMPACT]
            out[ribbon_layout.OVERFLOW] = 0
            self.set_stage(current)
            self._widths = out
        return self._widths

    def invalidate_widths(self):
        self._widths = None

    def changeEvent(self, ev):
        # FreeCAD re-applies its stylesheet after start-up, and Touch Mode or a font change resizes the
        # buttons: widths measured before are stale
        super().changeEvent(ev)
        if ev.type() in (QtCore.QEvent.StyleChange, QtCore.QEvent.FontChange) and self._widths is not None:
            self._widths = None
            page = self.parentWidget()
            while page is not None and not isinstance(page, RibbonPage):
                page = page.parentWidget()
            if page is not None:
                page.schedule_refit()

    def set_status(self, done, is_next):
        """Guided workflow (FEM): mark the step done or next; True if the label changed."""
        text = self.title + (" ✓" if done else "")
        state = "done" if done else "next" if is_next else ""
        changed = self.label.text() != text or self.property("nxstep") != state
        if changed:
            self.label.setText(text)
            self.collapsed_button.setText(CommandButton._wrap(text))
            self.setProperty("nxstep", state)
            self.label.setProperty("nxstep", state)
            for w in (self, self.label):
                w.style().unpolish(w)
                w.style().polish(w)
            self.invalidate_widths()
        return changed


class RibbonPage(QtWidgets.QScrollArea):
    """A ribbon page that fits its width by compacting, collapsing and finally moving groups into its
    More menu (``ribbon_layout.plan``). Scrolling sideways with the wheel and the edge arrows remain as
    the last resort, for a window narrower than the More button itself."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXRibbonPage")
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.groups = []
        self.layout_enabled = True       # False: the old behaviour (everything full, scroll) for checks
        self.last_plan = []
        self._fitting = False
        self._fit_width = -1
        self.overflow = QtWidgets.QToolButton()
        self.overflow.setObjectName("NXRibbonOverflow")
        self.overflow.setAutoRaise(True)
        self.overflow.setText("More")
        self.overflow.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.overflow.setArrowType(Qt.DownArrow)
        self.overflow.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.overflow.setAccessibleName("More commands")
        self.overflow.setToolTip("<b>More</b><br>Groups that do not fit at this window width")
        menu = QtWidgets.QMenu(self.overflow)
        menu.aboutToShow.connect(lambda m=menu: (m.clear(), self.populate_overflow(m)))
        self.overflow.setMenu(menu)
        self.overflow.hide()
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
        self.fit()
        self._update_arrows()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.fit()

    # ----------------------------------------------------------- responsive
    def add_group(self, group):
        lay = self.widget().layout()
        lay.addWidget(group)
        sep = QtWidgets.QFrame()
        sep.setObjectName("NXRibbonSeparator")
        sep.setFrameShape(QtWidgets.QFrame.VLine)
        lay.addWidget(sep)
        group.separator = sep
        self.groups.append(group)

    def finish(self):
        lay = self.widget().layout()
        lay.addStretch(1)
        lay.addWidget(self.overflow, 0, Qt.AlignTop)

    def available_width(self):
        return self.viewport().width()

    def fit(self, force=False):
        """Choose each group's stage for the current width (ribbon_layout.plan) and apply it."""
        if self._fitting or not self.groups:
            return
        if not self.isVisible():         # a hidden page's width is stale: fit when it is shown
            self._fit_width = -1
            return
        width = self.available_width()
        if width == self._fit_width and not force:
            return
        self._fitting = True
        try:
            if not self.layout_enabled:
                stages = [ribbon_layout.FULL] * len(self.groups)
            else:
                fits = [ribbon_layout.GroupFit(g.widths(), g.rank, i, g.preference) for i, g in enumerate(self.groups)]
                m = self.widget().layout().contentsMargins()
                stages = ribbon_layout.plan(fits, width, base=m.left() + m.right(),
                                            overflow_width=self.overflow.sizeHint().width())
            for g, s in zip(self.groups, stages):
                g.set_stage(s)
            self.overflow.setVisible(ribbon_layout.OVERFLOW in stages)
            self.last_plan = stages
            self._fit_width = width
        finally:
            self._fitting = False

    def refit(self):
        self._refit_pending = False
        for g in self.groups:
            g.invalidate_widths()
        self.fit(force=True)

    def schedule_refit(self):
        """One refit after the current burst of events (a stylesheet change reaches every group)."""
        if not getattr(self, "_refit_pending", False):
            self._refit_pending = True
            QtCore.QTimer.singleShot(0, self.refit)

    def overflowed(self):
        return [g for g in self.groups if g.stage == ribbon_layout.OVERFLOW]

    def populate_overflow(self, menu):
        for g in self.overflowed():
            sub = menu.addMenu(g.collapsed_button.icon(), g.title)
            sub.menuAction().setData("")
            g.populate(sub)

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


class RibbonPopup(QtWidgets.QFrame):
    """The drop-down that shows a minimised ribbon's page; it hands the pages back when it closes."""

    def __init__(self, ribbon):
        super().__init__(ribbon, Qt.Popup)
        self.setObjectName("NXRibbonPopup")
        self.ribbon = ribbon
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.ribbon._popup_closed()


class Ribbon(QtWidgets.QWidget):
    """Tab row (File button, quick access toolbar, tabs, command finder) + pages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NXRibbon")
        self.missing = []          # (tab, group, spec) entries that did not resolve
        self.locations = {}        # command -> "Tab > Group" (for the Command Finder)
        self.labels = {}           # command -> NX label
        self.on_run = None         # callback(command) for Repeat Command tracking
        self.app_id = ""           # the application whose ribbon this is (keys the user's layout)
        self.store = None          # ribbon_layout.LayoutStore: the user's layout choices
        self.essential = set()     # commands whose groups give up space last
        self._collapsed = False
        self._auto_minimized = False
        self._popup = None
        self._contextual = []
        self._probe_menu = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QtWidgets.QWidget(self)
        self.header.setObjectName("NXRibbonHeader")
        head = QtWidgets.QHBoxLayout(self.header)
        head.setContentsMargins(6, 1, 6, 1)
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
        self.tabs.setUsesScrollButtons(True)     # a narrow window scrolls the tabs, never clips them
        self.tabs.setElideMode(Qt.ElideNone)
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
        self.setStyleSheet(theme.stylesheet("ribbon.qss"))

    # ---------------------------------------------------------------- tabs
    def clear(self):
        self.hide_popup()
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
        if self._collapsed and index >= 0:
            # a minimised ribbon shows the tab's page as a drop-down over the graphics window (as NX does)
            QtCore.QTimer.singleShot(0, lambda i=index: self.show_popup(i))

    def set_collapsed(self, collapsed, save=True):
        """Minimise the ribbon to its tab row (the user's choice, saved) or restore it."""
        self._auto_minimized = False
        self._apply_collapsed(collapsed)
        if save and self.store is not None and self.store.minimized != collapsed:
            self.store.set_minimized(collapsed)

    def _apply_collapsed(self, collapsed):
        self.hide_popup()
        self._collapsed = collapsed
        self.stack.setVisible(not collapsed)
        self.collapse_button.setArrowType(Qt.DownArrow if collapsed else Qt.UpArrow)
        self.collapse_button.setToolTip("Expand Ribbon" if collapsed else "Collapse Ribbon (double-click a tab)")

    def set_auto_minimized(self, on):
        """A window too short for the ribbon minimises it, without changing the user's saved choice; it
        comes back when the window is tall enough again (unless the user minimised it meanwhile)."""
        if on and not self._collapsed:
            self._apply_collapsed(True)
            self._auto_minimized = True
        elif not on and self._auto_minimized:
            self._auto_minimized = False
            self._apply_collapsed(False)

    def is_collapsed(self):
        return self._collapsed

    def is_auto_minimized(self):
        return self._auto_minimized

    # ------------------------------------------------- minimised: drop-down
    def show_popup(self, index=None):
        """Show the current (or given) tab's page below the tab row, over the graphics window, until a command
        runs or the user clicks elsewhere."""
        if not self._collapsed or self.stack.count() == 0:
            return None
        if index is not None and 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
        if self._popup is None:
            self._popup = RibbonPopup(self)
        p = self._popup
        if self.stack.parentWidget() is not p:
            self.layout().removeWidget(self.stack)
            p.layout().addWidget(self.stack)
        self.stack.show()
        height = max(self.stack.currentWidget().minimumHeight(), self.stack.sizeHint().height()) + 2
        p.setGeometry(QtCore.QRect(self.header.mapToGlobal(QtCore.QPoint(0, self.header.height())),
                                   QtCore.QSize(self.width(), height)))
        p.show()
        return p

    def hide_popup(self):
        if self._popup is not None and self._popup.isVisible():
            self._popup.hide()

    def _popup_closed(self):
        """The drop-down closed: the pages go back under the tab row (hidden while minimised)."""
        if self.stack.parentWidget() is self._popup:
            self._popup.layout().removeWidget(self.stack)
            self.stack.setParent(self)
            self.layout().addWidget(self.stack)
        self.stack.setVisible(not self._collapsed)

    FINDER_WIDTH = (110, 230)        # the Command Finder narrows before tabs have to scroll

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_header()

    def _fit_header(self):
        finder = next((w for w in self.header.findChildren(QtWidgets.QLineEdit)
                       if w.objectName() == "NXCommandFinder"), None)
        if finder is None:
            return
        lo, hi = self.FINDER_WIDTH
        fixed = (self.file_button.sizeHint().width() + self.qat.sizeHint().width()
                 + self.tabs.sizeHint().width() + self.collapse_button.sizeHint().width() + 24)
        finder.setFixedWidth(max(lo, min(hi, self.width() - fixed)))

    # ------------------------------------------------------- user layout
    def pages(self):
        return [self.stack.widget(i) for i in range(self.stack.count())]

    def groups(self, tab=None):
        """(tab name, group) for every group, or for one tab's groups."""
        out = []
        for i, page in enumerate(self.pages()):
            name = self.tabs.tabText(i)
            if tab is None or name == tab:
                out += [(name, g) for g in getattr(page, "groups", [])]
        return out

    def set_group_preference(self, tab, group, value):
        """Automatic / Keep Expanded / Always Collapsed for one group, saved with the profile."""
        group.preference = value
        if self.store is not None:
            self.store.set_preference(self.app_id, tab, group.title, value)
        page = group.parentWidget()
        while page is not None and not isinstance(page, RibbonPage):
            page = page.parentWidget()
        if page is not None:
            page.refit()

    def reset_layout(self):
        if self.store is not None:
            self.store.reset()
        for tab, g in self.groups():
            g.preference = ribbon_layout.AUTO
        for page in self.pages():
            page.refit()
        self.set_collapsed(False)

    def _group_menu(self, tab, group, pos):
        menu = QtWidgets.QMenu(group)
        menu.setAccessibleName(f"{group.title} group layout")
        group_class = getattr(QtGui, "QActionGroup", None) or QtWidgets.QActionGroup
        choices = group_class(menu)
        for value, text in ((ribbon_layout.AUTO, "Automatic"), (ribbon_layout.EXPANDED, "Keep Expanded"),
                            (ribbon_layout.COLLAPSED, "Always Collapsed")):
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(group.preference == value)
            a.setActionGroup(choices)
            a.triggered.connect(lambda _=False, v=value: self.set_group_preference(tab, group, v))
        menu.addSeparator()
        menu.addAction("Reset Ribbon Layout").triggered.connect(lambda _=False: self.reset_layout())
        exec_menu(menu, group.mapToGlobal(pos))

    def set_steps(self, states):
        """Guided workflow: states = {step: "done" | "next" | ""}; relabels the groups standing for them."""
        changed = set()
        for _tab, g in self.groups():
            if g.step in states:
                st = states[g.step]
                if g.set_status(st == "done", st == "next"):
                    changed.add(g)
        for page in self.pages():
            if any(g in changed for g in getattr(page, "groups", [])):
                page.refit()
        return bool(changed)

    def reach(self, button):
        """How a user reaches a ribbon button now: ("direct", button), ("group", collapsed group button) or
        ("overflow", More button); (None, None) if it is not on a page."""
        group = button.parentWidget()
        while group is not None and not isinstance(group, RibbonGroup):
            group = group.parentWidget()
        if group is None:
            return None, None
        if group.stage == ribbon_layout.COLLAPSED:
            return "group", group.collapsed_button
        if group.stage == ribbon_layout.OVERFLOW:
            page = group.parentWidget()
            while page is not None and not isinstance(page, RibbonPage):
                page = page.parentWidget()
            return "overflow", page.overflow if page is not None else None
        return "direct", button

    def menu_action(self, button):
        """The menu entry that runs this button's command when its group is collapsed or overflowed."""
        group = button.parentWidget()
        while group is not None and not isinstance(group, RibbonGroup):
            group = group.parentWidget()
        if group is None or not isinstance(button, CommandButton):
            return None
        if self._probe_menu is not None:
            self._probe_menu.deleteLater()
        menu = self._probe_menu = QtWidgets.QMenu(self)
        group.populate(menu)
        stack = list(menu.actions())
        while stack:
            a = stack.pop(0)
            if a.menu() is not None:
                stack += a.menu().actions()
            elif a.data() == button.command:
                return a
        return None

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
        lay.setContentsMargins(6, 5, 6, 4)
        lay.setSpacing(0)
        area.setWidget(inner)
        return area, lay

    def add_tab(self, name, groups, index=None, contextual=False, known=None):
        """groups: list of (title, items) or (title, items, meta) from a JSON spec (meta: rank, step),
        or (title, [QWidget...])."""
        known = known if known is not None else known_commands()
        area, _lay = self._page()
        for entry in groups:
            gname, items = entry[0], entry[1]
            meta = entry[2] if len(entry) > 2 else {}
            group = RibbonGroup(gname, rank=meta.get("rank", 0), step=meta.get("step"))
            for item in items:
                widget, size = self._make(item, name, gname, known)
                if widget is not None:
                    group.add(widget, size)
            if group.count:
                if "rank" not in meta and any(c in self.essential for c, _ in group.entries()):
                    group.rank = ribbon_layout.ESSENTIAL_RANK
                if self.store is not None:
                    group.preference = self.store.preference(self.app_id, name, gname)
                group.setContextMenuPolicy(Qt.CustomContextMenu)
                group.customContextMenuRequested.connect(lambda p, t=name, g=group: self._group_menu(t, g, p))
                area.add_group(group)
            else:
                group.deleteLater()
        area.finish()
        area.setMinimumHeight(area.widget().sizeHint().height() + 2)
        if index is None:
            index = self.tabs.count()
        self.stack.insertWidget(index, area)
        self.tabs.insertTab(index, name)
        if contextual:
            self.tabs.setTabTextColor(index, QtGui.QColor(theme.color("contextual")))
            self._contextual.append(name)
        self._fit_header()
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
                self._fit_header()
                return True
        return False

    def has_tab(self, name):
        return name in self.tab_names()

    def _register(self, cmd, label, tab, group):
        self.locations.setdefault(cmd, f"{tab} › {group}")
        self.labels.setdefault(cmd, label)

    def _label(self, item, cmd):
        if config.get().get("labels") == "freecad":
            act = command_action(cmd)
            if act is not None:
                return clean_text(act.text())
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
        if item.get("default") and item["default"] != cmd:
            set_group_default(cmd, item["default"])
        return CommandButton(cmd, label, size, on_run=self._ran), size

    def _ran(self, cmd):
        self.hide_popup()                # a command run from the drop-down closes it, as in NX
        if self.on_run:
            self.on_run(cmd)


def QAction_types():
    from .qt import QAction
    return (QAction,)


def spec_commands(groups, known):
    """The commands the buttons of these groups ((title, items[, meta]) as add_tab takes them) would run."""
    out = []
    for entry in groups:
        for item in entry[1]:
            if isinstance(item, dict):
                for spec in [s["cmd"] for s in item.get("items", [])] if "dropdown" in item else [item["cmd"]]:
                    cmd = resolve(spec, known)
                    if cmd:
                        out.append(cmd)
    return out


def spec_groups(tab_spec):
    """(name, items, meta) per group of a JSON tab; meta holds the optional rank and workflow step."""
    return [(g["name"], g.get("items", []), {k: g[k] for k in ("rank", "step") if k in g})
            for g in tab_spec.get("groups", [])]


def expand_tabs(spec):
    """Resolve {"include": "common:View"} entries against common.json, and {"include": "modeling:PMI"}
    against another application's ribbon file (one level: that file's own includes are not followed)."""
    files = {}
    tabs = []
    for t in spec.get("tabs", []):
        if "include" in t:
            src, _, name = t["include"].partition(":")
            if src not in files:
                try:
                    files[src] = {x["name"]: x for x in config.load_json("ribbons", f"{src}.json")["tabs"]
                                  if "name" in x}
                except (OSError, ValueError, KeyError):
                    files[src] = {}
            if name in files[src]:
                tabs.append(files[src][name])
        else:
            tabs.append(t)
    return tabs

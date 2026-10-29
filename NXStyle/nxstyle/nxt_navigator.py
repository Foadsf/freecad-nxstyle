# SPDX-License-Identifier: LGPL-2.1-or-later
"""With FreeCAD-Nxt on (launch_nx.py --nxt), Nxt's model panel is the Part Navigator.

- Nxt's dock is titled Part Navigator (resources/nxt/nx_names.ts) and takes the Part Navigator's place: in front
  in the left tab strip, on the Resource Bar's button, with the status strip above its tree. FreeCAD's own tree
  stays behind it as the FreeCAD Tree tab.
- Under Nxt's tree are NX's Dependencies and Details panels, for the one selected object, folded away until
  opened as in NX. Dependencies lists what Nxt's dependency arrows draw (the parents an object is built from,
  the children that use it), and Nxt draws its arrows while the panel is open. Details lists the values Nxt's
  detail strip shows (its inspector.properties), editable in place, each edit one undo step.

Nxt stays unforked: this reads Nxt's tree snapshot and calls its bridge, as its own QML does.
"""

import FreeCAD as App
import FreeCADGui as Gui

from .nxt_core import KINDS, dependencies
from .qt import QtCore, QtGui, QtWidgets, Qt

PARAM = "User parameter:BaseApp/Preferences/Mod/NXStyle/Navigator"
NXT_DOCK = "NxtModelPanel"          # freecad.nxt.tree.panel.OBJECT_NAME
TITLE = "Part Navigator"
FREECAD_TREE = "FreeCAD Tree"
def _icon(doc, name):
    try:
        return doc.getObject(name).ViewObject.Icon
    except Exception:
        return QtGui.QIcon()


class Section(QtWidgets.QWidget):
    """One of NX's Part Navigator panels below the tree: a header that folds it open or away."""

    toggled = QtCore.Signal(bool)

    def __init__(self, title, body, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName(f"NXNav{key}")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QtWidgets.QToolButton(self)
        self.header.setObjectName(f"NXNav{key}Header")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.header.toggled.connect(self.set_open)
        lay.addWidget(self.header)
        self.body = body
        lay.addWidget(body, 1)
        self.set_open(App.ParamGet(PARAM).GetBool(key, False))

    def is_open(self):
        return self.header.isChecked()

    def set_open(self, on):
        if self.header.isChecked() != on:
            self.header.setChecked(on)        # comes back here through toggled
            return
        self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)
        self.setMaximumHeight(16777215 if on else self.header.sizeHint().height())
        App.ParamGet(PARAM).SetBool(self.key, on)
        self.toggled.emit(on)


class Navigator(QtWidgets.QWidget):
    """What Nxt's dock holds once it is the Part Navigator: the status strip, Nxt's tree, Dependencies, Details."""

    def __init__(self, dock, tree, status, bridge, nxt_modules, parent=None):
        super().__init__(parent)
        self.setObjectName("NXNxtNavigator")
        self.dock, self.tree, self.bridge, self.m = dock, tree, bridge, nxt_modules
        self.subject = None
        self._filling = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.status = status
        if status is not None:
            lay.addWidget(self._status_holder(status))
        self.split = QtWidgets.QSplitter(Qt.Vertical, self)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(tree)
        tree.show()
        self.deps = QtWidgets.QTreeWidget()
        self.deps.setObjectName("NXNavDependenciesTree")
        self.deps.setHeaderLabels(["Feature", "Relation"])
        self.deps.setRootIsDecorated(True)
        self.deps.itemDoubleClicked.connect(self._go_to)
        self.deps.setToolTip("Parents: what the selected object is built from. Children: what uses it.\n"
                             "Double-click one to select it.")
        self.details = QtWidgets.QTreeWidget()
        self.details.setObjectName("NXNavDetailsTree")
        self.details.setHeaderLabels(["Parameter", "Value", "Expression"])
        self.details.setRootIsDecorated(False)
        self.details.itemChanged.connect(self._edited)
        self.details.itemDoubleClicked.connect(self._details_clicked)
        self.dep_section = Section("Dependencies", self.deps, "Dependencies")
        self.det_section = Section("Details", self.details, "Details")
        for sec in (self.dep_section, self.det_section):
            self.split.addWidget(sec)
            sec.toggled.connect(lambda on, s=sec: self._make_room(s) if on else None)
            sec.toggled.connect(lambda _on: self.schedule())
        self.dep_section.toggled.connect(self._arrows)
        for sec in (self.dep_section, self.det_section):
            if sec.is_open():                   # opened last time: room once the dock has its size
                QtCore.QTimer.singleShot(0, lambda s=sec: self._make_room(s))
        lay.addWidget(self.split, 1)
        self.split.setStretchFactor(0, 1)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.refresh)
        for sig in (bridge.problemCountChanged, bridge.documentChanged, bridge.linkArrowsChanged,
                    bridge.pickOriginsChanged):
            sig.connect(self.schedule)
        self._observer = _SelectionObserver(self.schedule)
        Gui.Selection.addObserver(self._observer)
        self.destroyed.connect(lambda *_: _remove_observer(self._observer))
        self._arrows(self.dep_section.is_open())

    STATUS_LINES = 3        # work part, active body, selected; suppressed and failed features scroll into view

    def _status_holder(self, status):
        """The status strip in a box of fixed height. The strip grows and shrinks as the selection changes;
        measured on FreeCAD 1.1.4, making and picking 25 boxes took 100 s with the strip laid out right above Nxt's
        tree, 4.3 s in this box (4.6 s without the strip). A plain resize of Nxt's panel measured 0.1 s, so the
        cost is in what the strip's size changes set off, not yet pinned down."""
        holder = QtWidgets.QScrollArea(self)
        holder.setObjectName("NXNavStatusHolder")
        holder.setWidgetResizable(True)
        holder.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder.setWidget(status)
        m = status.layout().contentsMargins()
        line = status.fontMetrics().lineSpacing() + status.layout().spacing()
        holder.setFixedHeight(self.STATUS_LINES * line + m.top() + m.bottom())
        return holder

    OPEN_HEIGHT = 180       # what an opened panel takes from the tree, when the tree can spare it

    def _make_room(self, section):
        sizes = self.split.sizes()
        i = self.split.indexOf(section)
        if i < 1 or sum(sizes) <= 0 or sizes[i] >= self.OPEN_HEIGHT:
            return
        take = min(self.OPEN_HEIGHT - sizes[i], max(0, sizes[0] - 120))
        sizes[0] -= take
        sizes[i] += take
        self.split.setSizes(sizes)

    # ------------------------------------------------------------ keeping up
    def schedule(self, *_):
        self._timer.start()

    def _arrows(self, on):
        """Nxt draws its dependency arrows while the Dependencies panel is open (its DependencyArrows setting)."""
        settings, prefs = self.m["settings"], self.m["prefs"]
        if bool(settings.get("DependencyArrows")) != on:
            settings.put("DependencyArrows", on)
            prefs.apply({"DependencyArrows"})

    def current(self):
        """The object the panels describe: what Nxt's arrows start from (the one selected object, or the
        feature behind a pick in the graphics window)."""
        try:
            name = self.bridge._arrow_subject()
        except Exception:
            name = None
        doc = App.ActiveDocument
        return (doc, name) if doc is not None and name and doc.getObject(name) is not None else (doc, None)

    def refresh(self):
        doc, name = self.current()
        self.subject = name
        if self.dep_section.is_open():
            self._fill_dependencies(doc, name)
        if self.det_section.is_open():
            self._fill_details(doc, name)

    # ---------------------------------------------------------- Dependencies
    def _fill_dependencies(self, doc, name):
        self.deps.clear()
        if name is None:
            self.deps.addTopLevelItem(QtWidgets.QTreeWidgetItem(["Select one object"]))
            return
        try:
            parents, children = dependencies(self.bridge._snapshot, name, self.m["links"].kind_of)
        except Exception as e:
            self.deps.addTopLevelItem(QtWidgets.QTreeWidgetItem([f"Not available: {e}"]))
            return
        root = QtWidgets.QTreeWidgetItem([doc.getObject(name).Label, ""])
        root.setIcon(0, _icon(doc, name))
        root.setData(0, Qt.UserRole, name)
        self.deps.addTopLevelItem(root)
        for title, rows in (("Parents", parents), ("Children", children)):
            group = QtWidgets.QTreeWidgetItem(root, [f"{title} ({len(rows)})", ""])
            for other, label, kind in rows:
                it = QtWidgets.QTreeWidgetItem(group, [label, KINDS.get(kind, kind)])
                it.setIcon(0, _icon(doc, other))
                it.setData(0, Qt.UserRole, other)
            group.setExpanded(True)
        root.setExpanded(True)
        self.deps.resizeColumnToContents(0)

    def rows(self, tree):
        """[(text of each column, depth)] of a panel's rows (for tests)."""
        out = []
        it = QtWidgets.QTreeWidgetItemIterator(tree)
        while it.value():
            v, depth, p = it.value(), 0, it.value().parent()
            while p is not None:
                depth, p = depth + 1, p.parent()
            out.append(([v.text(i) for i in range(tree.columnCount())], depth))
            it += 1
        return out

    def _go_to(self, item, _col=0):
        name = item.data(0, Qt.UserRole)
        if name:
            self.bridge.select(name, False)
            self.bridge.revealObject(name)

    # --------------------------------------------------------------- Details
    def _fill_details(self, doc, name):
        self._filling = True
        try:
            self.details.clear()
            obj = doc.getObject(name) if name else None
            if obj is None:
                self.details.addTopLevelItem(QtWidgets.QTreeWidgetItem(["Select one object"]))
                return
            props = self.m["properties"]
            for e in props.describe(obj):
                it = QtWidgets.QTreeWidgetItem([e["name"], e["text"], e["expression"]])
                it.setData(0, Qt.UserRole, e["name"])
                it.setData(1, Qt.UserRole, e["kind"])
                if e["kind"] == "bool":
                    it.setText(1, "")
                    it.setCheckState(1, Qt.Checked if e["checked"] else Qt.Unchecked)
                if not e["readOnly"]:
                    flags = it.flags() | (Qt.ItemIsUserCheckable if e["kind"] == "bool" else Qt.ItemIsEditable)
                    it.setFlags(flags)
                if e["kind"] == "enum" and e["options"]:
                    it.setToolTip(1, "One of: " + ", ".join(e["options"]))
                self.details.addTopLevelItem(it)
            if not self.details.topLevelItemCount():
                self.details.addTopLevelItem(QtWidgets.QTreeWidgetItem([f"No key values for {obj.TypeId}"]))
            more = QtWidgets.QTreeWidgetItem([f"All properties ({props.visible_count(obj)})…"])
            more.setData(0, Qt.UserRole, "")
            more.setToolTip(0, "Double-click: Nxt's Property Inspector")
            f = more.font(0)
            f.setItalic(True)
            more.setFont(0, f)
            self.details.addTopLevelItem(more)
            self.details.resizeColumnToContents(0)
        finally:
            self._filling = False

    def _details_clicked(self, item, _col):
        if item.data(0, Qt.UserRole) == "" and self.subject:
            self.bridge.openPropertyInspector(self.subject, -1.0, -1.0)

    def _edited(self, item, col):
        """A typed value (or "=expression") or a ticked box: one undo step, as in Nxt's detail strip."""
        if self._filling or col != 1 or not self.subject:
            return
        prop, kind = item.data(0, Qt.UserRole), item.data(1, Qt.UserRole)
        doc = App.ActiveDocument
        obj = doc.getObject(self.subject) if doc is not None and prop else None
        if obj is None:
            return
        value = item.checkState(1) == Qt.Checked if kind == "bool" else item.text(1)
        self.m["properties"].apply(obj, prop, value)
        self.schedule()


class _SelectionObserver:
    def __init__(self, cb):
        self.cb = cb

    def addSelection(self, *_):
        self.cb()

    def removeSelection(self, *_):
        self.cb()

    def setSelection(self, *_):
        self.cb()

    def clearSelection(self, *_):
        self.cb()


def _remove_observer(obs):
    try:
        Gui.Selection.removeObserver(obs)
    except Exception:
        pass


def nxt_modules():
    from freecad.nxt.core import settings
    from freecad.nxt.inspector import properties
    from freecad.nxt.tree import links
    from freecad.nxt.ui import prefs
    return {"settings": settings, "properties": properties, "links": links, "prefs": prefs}


def adopt(shell):
    """Make Nxt's panel the Part Navigator, once it is up. Returns the Navigator, or None while Nxt's panel is
    not there yet (the shell's tick tries again)."""
    from freecad.nxt.tree import panel as nxt_panel
    mw = shell.mw
    dock = nxt_panel.instance()
    bridge = nxt_panel.bridge()
    if dock is None or bridge is None or dock.widget() is None:
        return None
    existing = dock.findChild(QtWidgets.QWidget, "NXNxtNavigator")
    if existing is not None:
        return existing
    dock.setWindowTitle(TITLE)                    # Nxt's own title ("Model (Nxt)") is renamed too (nx_names.ts)
    model = mw.findChild(QtWidgets.QDockWidget, "Model")
    if model is not None:
        model.setWindowTitle(FREECAD_TREE)
        if not dock.isFloating() and dock not in mw.tabifiedDockWidgets(model):
            mw.tabifyDockWidget(model, dock)
        if not dock.isFloating():
            # the Part Navigator is the first tab, as in NX: the others go back in behind it, in their order
            for other in mw.tabifiedDockWidgets(dock):
                mw.tabifyDockWidget(dock, other)
    tree = dock.widget()
    status = getattr(shell, "navigator_status", None)
    nav = Navigator(dock, tree, status, bridge, nxt_modules())
    dock.setWidget(nav)
    # the Resource Bar's Part Navigator button opens this dock
    old = shell.resource_actions.get(TITLE)
    act = dock.toggleViewAction()
    act.setIcon(old.icon() if old is not None else QtGui.QIcon())
    act.setText(TITLE)
    act.setToolTip(TITLE)
    if old is not None:
        shell.resource_bar.insertAction(old, act)
        shell.resource_bar.removeAction(old)
    shell.resource_actions[TITLE] = act
    if model is not None:
        model.toggleViewAction().setText(FREECAD_TREE)
    dock.show()
    dock.raise_()
    nav.schedule()
    return nav

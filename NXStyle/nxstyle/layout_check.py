# SPDX-License-Identifier: LGPL-2.1-or-later
"""Measures the NX window's layout from widget geometry (the self-test's window-size matrix).

For a window size it checks, from the widgets' rectangles and not from a screenshot:

- clipping: every ribbon control that is shown lies wholly inside the ribbon page (and the header
  controls inside the header row); no page needs sideways scrolling;
- reachability: every command of every ribbon tab is either a button that is fully shown, or an
  entry in the menu of a collapsed group or of the page's More button that is fully shown;
- the essential commands of the application are reachable;
- the window's bars lie inside the window and the graphics area keeps some height.

Window sizes are logical pixels (``ribbon_layout.matrix_cells``): Qt lays a window out in logical
pixels and scales fonts and icons with the screen, so a scale is reproduced by the logical size.
"""

from . import ribbon_layout
from .qt import QtCore, QtWidgets
from .ribbon import CommandButton, DropdownButton, RibbonPage, clean_text


MEASURE_TOLERANCE = 3        # px per shown group between the planned and the laid-out width


def settle(rounds=4):
    app = QtWidgets.QApplication.instance()
    for _ in range(rounds):
        app.sendPostedEvents()
        app.processEvents()


def rect_in(widget, ancestor):
    """The widget's rectangle in the ancestor's coordinates."""
    return QtCore.QRect(widget.mapTo(ancestor, QtCore.QPoint(0, 0)), widget.size())


def fully_inside(widget, ancestor, area=None):
    area = area if area is not None else ancestor.rect()
    return area.contains(rect_in(widget, ancestor))


def widget_commands(w):
    if isinstance(w, CommandButton):
        return [w.command]
    if isinstance(w, DropdownButton):
        return [c for c, _ in w.entries]
    if isinstance(w, QtWidgets.QToolButton) and w.defaultAction() is not None:
        a = w.defaultAction()
        return [a.objectName() or clean_text(a.text())]
    return []


def measure_page(page, name):
    """Clipping and reachability on one ribbon page (it must be the current one, laid out)."""
    vp = page.viewport()
    area = vp.rect()
    inner = page.widget()
    clipped, unreachable = [], []
    reach = {}                                  # command -> "direct" | "group" | "overflow"
    for b in inner.findChildren(QtWidgets.QToolButton):
        if b.isVisibleTo(page) and not fully_inside(b, vp, area):
            clipped.append(f"{name}: {b.accessibleName() or b.text() or b.objectName()} {rect_in(b, vp).getRect()}")
    for lab in inner.findChildren(QtWidgets.QLabel, "NXRibbonGroupLabel"):
        if lab.isVisibleTo(page) and not fully_inside(lab, vp, area):
            clipped.append(f"{name}: group label {lab.text()} {rect_in(lab, vp).getRect()}")
    overflow_ok = page.overflow.isVisibleTo(page) and fully_inside(page.overflow, vp, area)
    for g in page.groups:
        expected = [c for c, _ in g.entries()]
        got = {}
        if g.stage in (ribbon_layout.FULL, ribbon_layout.COMPACT):
            for w, _size in g.items:
                if w.isVisibleTo(page) and fully_inside(w, vp, area):
                    for c in widget_commands(w):
                        got[c] = "direct"
        elif g.stage == ribbon_layout.COLLAPSED:
            b = g.collapsed_button
            if b.isVisibleTo(page) and fully_inside(b, vp, area):
                menu = QtWidgets.QMenu()
                g.populate(menu)
                got = {c: "group" for c in g.menu_commands(menu)}
                menu.deleteLater()
        elif g.stage == ribbon_layout.OVERFLOW and overflow_ok:
            menu = QtWidgets.QMenu()
            page.populate_overflow(menu)
            sub = next((a.menu() for a in menu.actions() if a.menu() is not None and a.text() == g.title), None)
            if sub is not None:
                got = {c: "overflow" for c in g.menu_commands(sub)}
            menu.deleteLater()
        for c in expected:
            if c in got:
                reach.setdefault(c, got[c])
            else:
                unreachable.append(f"{name} › {g.title}: {c}")
    scroll = page.horizontalScrollBar().maximum()
    shown = [g for g in page.groups if g.isVisibleTo(page)]
    used = sum(rect_in(g, inner).width() + (g.separator.width() if g.separator is not None else 0) for g in shown)
    planned = sum(g.widths()[g.stage] for g in shown)
    # the plan must rest on the widths the groups really take: a width measured too large reduces groups
    # that had room (it happened: a stale size hint made compacting look useless), too small clips them
    mismeasured = [] if abs(planned - used) <= MEASURE_TOLERANCE * max(1, len(shown)) else \
        [f"{name}: the plan counted {planned}px for the shown groups, they take {used}px"]
    return {"clipped": clipped, "unreachable": unreachable, "reach": reach, "scroll": scroll,
            "mismeasured": mismeasured,
            "stages": dict(zip([g.title for g in page.groups], page.last_plan)),
            "available": page.available_width(), "used": used,
            "planned": {g.title: g.widths() for g in page.groups}}


def measure_header(ribbon):
    """The tab row: File, Quick Access, tabs, Command Finder, collapse button inside the row; tabs
    either all shown or scrollable; Quick Access buttons shown or in its extension menu."""
    h = ribbon.header
    bad = []
    finder = next((w for w in h.findChildren(QtWidgets.QLineEdit) if w.objectName() == "NXCommandFinder"), None)
    for name, w in (("File", ribbon.file_button), ("Quick Access", ribbon.qat), ("tabs", ribbon.tabs),
                    ("Command Finder", finder), ("Collapse", ribbon.collapse_button)):
        if w is None:
            continue
        if not w.isVisibleTo(h) or w.width() <= 0:
            bad.append(f"{name} not shown")
        elif not fully_inside(w, h):
            bad.append(f"{name} clipped {rect_in(w, h).getRect()} in {h.rect().getRect()}")
    tabs = ribbon.tabs
    scrollers = [b for b in tabs.findChildren(QtWidgets.QToolButton) if b.isVisibleTo(tabs)]
    hidden_tabs = [tabs.tabText(i) for i in range(tabs.count()) if not tabs.rect().contains(tabs.tabRect(i))]
    if hidden_tabs and not scrollers:
        bad.append(f"tabs cut off without scroll buttons: {hidden_tabs}")
    qat = ribbon.qat
    ext = [b for b in qat.findChildren(QtWidgets.QToolButton) if b.objectName() == "qt_toolbar_ext_button"]
    ext_shown = any(b.isVisibleTo(qat) for b in ext)
    for a in qat.actions():
        w = qat.widgetForAction(a)
        if w is not None and not (w.isVisibleTo(qat) and fully_inside(w, qat)) and not ext_shown:
            bad.append(f"Quick Access {w.toolTip()[:30]} cut off without its extension button")
    return bad, {"tabs_scroll": bool(scrollers), "qat_extension": ext_shown, "hidden_tabs": len(hidden_tabs)}


def measure_window(shell):
    mw = shell.mw
    bad = []
    for name, w in (("ribbon", shell.ribbon_bar), ("top border bar", shell.border_bar),
                    ("resource bar", shell.resource_bar), ("status bar", mw.statusBar())):
        if w is not None and w.isVisible() and not fully_inside(w, mw):
            bad.append(f"{name} outside the window {rect_in(w, mw).getRect()} in {mw.rect().getRect()}")
    mdi = mw.findChild(QtWidgets.QMdiArea)
    graphics = mdi.height() if mdi is not None and mdi.isVisible() else 0
    return bad, graphics


def minimum_heights(shell):
    """What holds the window's minimum height up: each bar's and visible dock's minimum, the central area's."""
    mw = shell.mw
    out = {"window": mw.minimumSizeHint().height()}
    for name, w in (("ribbon", shell.ribbon_bar), ("ribbon page", shell.ribbon.stack),
                    ("top border bar", shell.border_bar), ("status bar", mw.statusBar()),
                    ("central", mw.centralWidget())):
        if w is not None and w.isVisible():
            out[name] = w.minimumSizeHint().height()
    for d in mw.findChildren(QtWidgets.QDockWidget):
        if d.isVisible() and not d.isFloating():
            out[f"dock {d.objectName()}"] = d.minimumSizeHint().height()
    return out


def run_cell(shell, cell, min_graphics=80):
    """Resize the main window to the cell's logical size and measure every tab of the current ribbon."""
    mw, r = shell.mw, shell.ribbon
    w, h = cell["window"]
    mw.showNormal()
    # twice: a short window minimises the ribbon, which lowers the window's minimum height; the window
    # manager then gives a maximised window the work area again
    for _ in range(2):
        mw.resize(w, h)
        settle()
    size = (mw.width(), mw.height())
    out = {"cell": cell["name"], "window": [w, h], "actual": list(size), "problems": [], "tabs": {}}
    screen = mw.screen().availableGeometry() if hasattr(mw, "screen") else None
    frame_h = mw.frameGeometry().height() - mw.height()
    # a screen smaller than the cell caps the height (this host's, not the cell's): a shorter window is
    # only harder for the vertical checks and the ribbon fits the width, so it is measured as is and noted
    capped = screen is not None and size[1] < h and size[1] >= screen.height() - frame_h - 2
    if capped:
        out["note"] = f"height capped at {size[1]} by this screen ({screen.width()}x{screen.height()})"
    if size[0] != w or (size[1] != h and not capped):
        out["problems"].append(f"window is {size[0]}x{size[1]}, not {w}x{h}: its minimum is "
                               f"{mw.minimumSizeHint().width()}x{mw.minimumSizeHint().height()}")
    out["minimum"] = minimum_heights(shell)
    bad, header = measure_header(r)
    out["problems"] += bad
    out["header"] = header
    bad, graphics = measure_window(shell)
    out["problems"] += bad
    out["graphics_height"] = graphics
    if graphics < min_graphics:
        out["problems"].append(f"graphics area only {graphics}px high")
    current = r.tabs.currentIndex()
    reach = {}
    minimized = r.is_collapsed()
    out["ribbon"] = ("minimised automatically" if r.is_auto_minimized() else "minimised") if minimized else "expanded"
    win = QtCore.QRect(mw.mapToGlobal(QtCore.QPoint(0, 0)), mw.size())
    for i in range(r.tabs.count()):
        page = r.stack.widget(i)
        if not isinstance(page, RibbonPage):
            continue
        r.tabs.setCurrentIndex(i)
        if minimized:                    # what a click on the tab shows: the page as a drop-down
            popup = r.show_popup(i)
            settle(2)
            box = QtCore.QRect(popup.mapToGlobal(QtCore.QPoint(0, 0)), popup.size()) if popup else None
            if box is None or not popup.isVisible():
                out["problems"].append(f"{r.tabs.tabText(i)}: the minimised ribbon's tab shows no page")
            elif not win.contains(box):
                out["problems"].append(f"{r.tabs.tabText(i)}: drop-down {box.getRect()} leaves the window "
                                       f"{win.getRect()}")
        else:
            settle(2)
        m = measure_page(page, r.tabs.tabText(i))
        if minimized:
            r.hide_popup()
            settle(1)
        out["problems"] += m["clipped"] + m["unreachable"] + m["mismeasured"]
        if m["scroll"] > 0:
            out["problems"].append(f"{r.tabs.tabText(i)}: page scrolls by {m['scroll']}px")
        out["tabs"][r.tabs.tabText(i)] = {k: v for k, v in m["stages"].items() if v != ribbon_layout.FULL}
        out.setdefault("fill", {})[r.tabs.tabText(i)] = f"{m['used']}/{m['available']}"
        if i == 0:
            out["first_tab_widths"] = m["planned"]
        for c, how in m["reach"].items():
            if reach.get(c) != "direct":
                reach[c] = how
    r.tabs.setCurrentIndex(current)
    settle(2)
    missing = sorted(c for c in r.essential if c not in reach)
    if missing:
        out["problems"].append(f"essential commands unreachable: {missing}")
    out["essential"] = {c: reach.get(c) for c in sorted(r.essential)}
    out["reach"] = {k: sum(1 for v in reach.values() if v == k) for k in ("direct", "group", "overflow")}
    out["ok"] = not out["problems"]
    return out


def run_matrix(shell, cells=None):
    cells = cells or ribbon_layout.matrix_cells()
    return [run_cell(shell, c) for c in cells]

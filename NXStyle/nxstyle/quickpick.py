# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX QuickPick: hold MB1 still over overlapping geometry and pick from the list of everything under the
cursor, nearest first. Each row names the element and the occurrence it belongs to, so two links to the
same part are told apart; a row the selection filter or the command refuses is greyed with the reason."""

import FreeCAD as App
import FreeCADGui as Gui

from . import selection_filter as sf
from .qt import QtCore, QtWidgets

_last = None


def last():
    """The QuickPick list shown last (for tests), or None."""
    return _last


class QuickPick(QtWidgets.QMenu):
    def __init__(self, rows, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("NXQuickPick")
        self.setToolTipsVisible(True)
        self.rows = rows
        self.chosen = None
        title = self.addAction(f"QuickPick: {len(rows)} under the cursor")
        title.setEnabled(False)
        self.addSeparator()
        self.row_actions = []
        for i, r in enumerate(rows):
            text = r["label"] if r["ok"] else f"{r['label']}   (refused)"
            act = self.addAction(text)
            act.setData(i)
            act.setEnabled(bool(r["ok"]))
            act.setToolTip(r["reason"] or "Select this one")
            act.triggered.connect(lambda _=False, k=i: self.choose(k))
            self.row_actions.append(act)
        self.hovered.connect(self._preselect)
        self.aboutToHide.connect(Gui.Selection.clearPreselection)

    def default(self):
        """Index of the row a click picks: the nearest allowed one."""
        return next((i for i, r in enumerate(self.rows) if r["ok"]), None)

    def _preselect(self, act):
        i = act.data()
        if i is None or not isinstance(i, int) or not self.rows[i]["ok"]:
            return
        r = self.rows[i]
        try:
            Gui.Selection.setPreselection(App.getDocument(r["doc"]).getObject(r["top"]), r["sub"])
        except Exception:
            pass

    def choose(self, i):
        r = self.rows[i]
        if not r["ok"]:
            return False
        self.chosen = r
        self.hide()
        return sf.select_row(r)


def open_at(view, xy, global_pos=None):
    """Show QuickPick for the Coin pixel xy of view; None when there is nothing to choose between."""
    global _last
    rows = sf.rows_at(view, xy)
    if len(rows) < 2:
        return None
    menu = QuickPick(rows)
    _last = menu
    if global_pos is None:
        global_pos = Gui.getMainWindow().mapToGlobal(QtCore.QPoint(200, 200))
    menu.popup(global_pos)
    return menu

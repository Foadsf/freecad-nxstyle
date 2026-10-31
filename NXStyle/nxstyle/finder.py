# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX-style Command Finder: search native commands, see their location, run them."""

import FreeCADGui as Gui

from .qt import QtCore, QtGui, QtWidgets, Qt
from . import icon_theme, theme
from .ribbon import clean_text, command_action

ROLE_CMD = Qt.UserRole + 1
ROLE_TITLE = Qt.UserRole + 2
ROLE_DETAIL = Qt.UserRole + 3
ROLE_SHORTCUT = Qt.UserRole + 4


class ResultDelegate(QtWidgets.QStyledItemDelegate):
    """Readable title, location/native alias and a separate shortcut badge."""

    def sizeHint(self, option, index):
        return QtCore.QSize(440, max(58, option.fontMetrics.height() * 2 + 18))

    def paint(self, painter, option, index):
        painter.save()
        row = option.rect.adjusted(4, 2, -4, -2)
        enabled = bool(index.flags() & Qt.ItemIsEnabled)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hovered = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(theme.color("tint2" if selected else "tint" if hovered else "panel")))
        painter.drawRoundedRect(row, 5, 5)
        if selected:
            painter.setBrush(QtGui.QColor(theme.color("accent")))
            painter.drawRoundedRect(QtCore.QRect(row.left(), row.top() + 8, 3, row.height() - 16), 1, 1)
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QtGui.QIcon):
            mode = QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled
            icon.paint(painter, QtCore.QRect(row.left() + 12, row.center().y() - 10, 20, 20), Qt.AlignCenter, mode)

        font = QtGui.QFont(option.font)
        detail_font = QtGui.QFont(font)
        if detail_font.pointSizeF() > 0:
            detail_font.setPointSizeF(max(8, detail_font.pointSizeF() - 1))
        metrics = QtGui.QFontMetrics(detail_font)
        right = row.right() - 12
        shortcut = index.data(ROLE_SHORTCUT) or ""
        if shortcut:
            badge_width = min(metrics.horizontalAdvance(shortcut) + 16, max(50, row.width() // 3))
            badge = QtCore.QRect(right - badge_width, row.center().y() - 11, badge_width, 22)
            painter.setBrush(QtGui.QColor(theme.color("panel" if selected else "panel-alt")))
            painter.setPen(QtGui.QColor(theme.color("line")))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QtGui.QColor(theme.color("muted" if enabled else "disabled")))
            painter.setFont(detail_font)
            painter.drawText(badge.adjusted(6, 0, -6, 0), Qt.AlignCenter,
                             metrics.elidedText(shortcut, Qt.ElideRight, badge.width() - 12))
            right = badge.left() - 12
        left = row.left() + 44
        width = max(0, right - left)
        title_rect = QtCore.QRect(left, row.top() + 7, width, (row.height() - 14) // 2)
        detail_rect = QtCore.QRect(left, title_rect.bottom() + 1, width, title_rect.height())
        font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.color("text" if enabled else "disabled")))
        painter.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft,
                         QtGui.QFontMetrics(font).elidedText(index.data(ROLE_TITLE) or "", Qt.ElideRight, width))
        painter.setFont(detail_font)
        painter.setPen(QtGui.QColor(theme.color("muted" if enabled else "disabled")))
        painter.drawText(detail_rect, Qt.AlignVCenter | Qt.AlignLeft,
                         metrics.elidedText(index.data(ROLE_DETAIL) or "", Qt.ElideRight, width))
        if option.state & QtWidgets.QStyle.State_HasFocus:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QtGui.QColor(theme.color("accent")))
            painter.drawRoundedRect(row.adjusted(1, 1, -1, -1), 5, 5)
        painter.restore()


class CommandFinder(QtWidgets.QLineEdit):
    def __init__(self, ribbon, parent=None, on_run=None):
        super().__init__(parent)
        self.ribbon = ribbon
        self.on_run = on_run
        self.setObjectName("NXCommandFinder")
        self.setPlaceholderText("Find a command...")
        self.setAccessibleName("Command Finder")
        self.setToolTip("Search commands, native names, ribbon locations or shortcuts")
        self.setClearButtonEnabled(True)
        self.model = QtGui.QStandardItemModel(self)
        self.completer = QtWidgets.QCompleter(self.model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.completer.setCompletionRole(Qt.DisplayRole)
        self.completer.setMaxVisibleItems(8)
        popup = self.completer.popup()
        popup.setObjectName("NXCommandResults")
        popup.setAccessibleName("Command search results")
        popup.setIconSize(QtCore.QSize(20, 20))
        popup.setItemDelegate(ResultDelegate(popup))
        popup.setUniformItemSizes(True)
        popup.setMouseTracking(True)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        popup.setStyleSheet(theme.fill("""
            QListView#NXCommandResults {
                background: @nx-panel; color: @nx-text; border: 1px solid @nx-field;
                padding: 5px; outline: none;
            }
        """))
        self.setCompleter(self.completer)
        self.completer.activated[QtCore.QModelIndex].connect(self._activated)
        # Run before QCompleter's own event filter: one Return chooses one result.
        self.installEventFilter(self)
        popup.installEventFilter(self)
        self.returnPressed.connect(self._return)
        self.textEdited.connect(self._prepare_popup)
        self._dirty = True
        self._busy = False

    def invalidate(self):
        self._dirty = True

    def focusInEvent(self, ev):
        # Native command availability changes with document/selection state.
        if self._dirty:
            self.rebuild()
        else:
            for row in range(self.model.rowCount()):
                item = self.model.item(row)
                item.setEnabled(self._enabled(item.data(ROLE_CMD)))
        self._prepare_popup()
        super().focusInEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._prepare_popup()

    def _prepare_popup(self, *_):
        if not hasattr(self, "completer"):
            return
        popup = self.completer.popup()
        screen = QtWidgets.QApplication.screenAt(self.mapToGlobal(self.rect().bottomLeft()))
        screen = screen or QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry().width() - 24 if screen else 800
        popup.setFixedWidth(max(1, min(available, max(440, self.width()))))

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._return()
                event.accept()
                return True
            if event.key() == Qt.Key_Escape:
                self.completer.popup().hide()
                self.clear()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _enabled(self, name):
        act = command_action(name)
        if act is not None:
            return act.isEnabled()
        try:
            return bool(Gui.Command.get(name).isActive())
        except Exception:
            return False

    def rebuild(self):
        self.model.clear()
        locations = self.ribbon.locations
        labels = self.ribbon.labels
        for name in sorted(Gui.listCommands()):
            act = command_action(name)
            if act is not None:
                icon, fc_text = act.icon(), clean_text(act.text())
                shortcut, tip = act.shortcut().toString(), clean_text(act.toolTip() or "")
            elif name in labels:
                info = Gui.Command.get(name).getInfo()
                icon = icon_theme.icon(name, Gui.getIcon(info.get("pixmap") or "") or QtGui.QIcon())
                fc_text, shortcut, tip = clean_text(info.get("menuText", "")), "", clean_text(info.get("toolTip", ""))
            else:
                continue
            if not fc_text:
                continue
            nx = labels.get(name)
            where = locations.get(name, "Menu")
            title = nx or fc_text
            alias = f"  /  {fc_text}" if nx and nx != fc_text else ""
            detail = f"{where}{alias}"
            # Search metadata stays in DisplayRole for standard QCompleter filtering.
            text = f"{title}  {fc_text}  {name}  {where}  {shortcut}"
            item = QtGui.QStandardItem(icon, text)
            item.setData(name, ROLE_CMD)
            item.setData(title, ROLE_TITLE)
            item.setData(detail, ROLE_DETAIL)
            item.setData(shortcut, ROLE_SHORTCUT)
            item.setToolTip(tip or f"{title} - {detail}")
            item.setData(f"{title}, {detail}, {shortcut}", Qt.AccessibleTextRole)
            item.setEditable(False)
            item.setEnabled(self._enabled(name))
            self.model.appendRow(item)
        self._dirty = False

    def find(self, text):
        """Command names whose search entry contains text (also used by smoke checks)."""
        if self._dirty:
            self.rebuild()
        text = text.lower()
        return [self.model.item(row).data(ROLE_CMD) for row in range(self.model.rowCount())
                if text in self.model.item(row).text().lower()]

    def _run(self, name):
        if not name or self._busy or not self._enabled(name):
            return
        self._busy = True
        QtCore.QTimer.singleShot(50, lambda: setattr(self, "_busy", False))
        self.completer.popup().hide()
        self.clear()
        if self.on_run:
            self.on_run(name)
        # Recheck after queued document/selection updates, before native dispatch.
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(name) if self._enabled(name) else None)
        # QLineEdit's completer connection fills the field after mouse activation.
        # Clear after that connection too, so search metadata never remains visible.
        QtCore.QTimer.singleShot(0, self.clear)

    def _activated(self, index):
        self._run(index.data(ROLE_CMD))

    def _return(self):
        if not self.text().strip():
            return
        popup = self.completer.popup()
        selected = popup.currentIndex()
        hits = self.find(self.text())
        if popup.isVisible() and selected.isValid() and selected.data(ROLE_CMD) in hits:
            self._run(selected.data(ROLE_CMD))
            return
        for name in hits:
            if self._enabled(name):
                self._run(name)
                break

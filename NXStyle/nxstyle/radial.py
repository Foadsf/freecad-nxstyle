# SPDX-License-Identifier: LGPL-2.1-or-later
"""Radial (pie) pop-up menu, opened by holding MB3 in the graphics window."""

import math

from .qt import QtCore, QtGui, QtWidgets, Qt, pos

OUTER = 118
INNER = 26


class RadialMenu(QtWidgets.QWidget):
    """items: list of dicts {label, icon, run, enabled}; item 0 sits at 12 o'clock."""

    def __init__(self, items, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("NXRadialMenu")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.items = items
        self.hover = -1
        side = 2 * OUTER + 60
        self.resize(side, side)
        self.triggered = None   # label of the item that ran (tests use this)

    def center(self):
        return QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)

    def popup_at(self, global_point):
        self.move(global_point.x() - self.width() // 2, global_point.y() - self.height() // 2)
        self.show()
        self.raise_()
        self.grabMouse()

    def index_at(self, p):
        c = self.center()
        dx, dy = p.x() - c.x(), p.y() - c.y()
        dist = math.hypot(dx, dy)
        if dist < INNER or not self.items:
            return -1
        if dist > OUTER + 30:
            return -1
        step = 360.0 / len(self.items)
        ang = (math.degrees(math.atan2(dx, -dy)) + 360.0 + step / 2.0) % 360.0
        return int(ang // step)

    def mouseMoveEvent(self, ev):
        idx = self.index_at(pos(ev))
        if idx != self.hover:
            self.hover = idx
            self.update()

    def mouseReleaseEvent(self, ev):
        idx = self.index_at(pos(ev))
        if idx >= 0:
            self.run(idx)
        elif not self.rect().contains(pos(ev)):
            self.close()
        # releasing in the centre keeps the menu open for a click choice

    def mousePressEvent(self, ev):
        if not self.rect().contains(pos(ev)):
            self.close()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        self.releaseMouse()
        super().closeEvent(ev)

    def run(self, idx):
        item = self.items[idx]
        if not item.get("enabled", True):
            return
        self.triggered = item["label"]
        self.close()
        QtCore.QTimer.singleShot(0, item["run"])

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = self.center()
        n = max(len(self.items), 1)
        step = 360.0 / n
        ring = QtGui.QPainterPath()
        ring.addEllipse(c, OUTER, OUTER)
        hole = QtGui.QPainterPath()
        hole.addEllipse(c, INNER, INNER)
        p.fillPath(ring.subtracted(hole), QtGui.QColor(245, 246, 247, 235))
        p.setPen(QtGui.QPen(QtGui.QColor("#9AA3AB"), 1))
        p.drawEllipse(c, OUTER, OUTER)
        p.drawEllipse(c, INNER, INNER)
        rect = QtCore.QRectF(c.x() - OUTER, c.y() - OUTER, 2 * OUTER, 2 * OUTER)
        for i, item in enumerate(self.items):
            # Qt angles: 0 = 3 o'clock, counter-clockwise; ours: 0 = 12 o'clock, clockwise
            start = 90.0 - (i * step) - step / 2.0
            if i == self.hover and item.get("enabled", True):
                path = QtGui.QPainterPath()
                path.moveTo(c)
                path.arcTo(rect, start, -step)
                path.closeSubpath()
                p.fillPath(path.subtracted(hole), QtGui.QColor("#CFE4F4"))
            ang = math.radians(i * step)
            r = (OUTER + INNER) / 2.0 + 6
            cx, cy = c.x() + r * math.sin(ang), c.y() - r * math.cos(ang)
            icon = item.get("icon")
            mode = QtGui.QIcon.Normal if item.get("enabled", True) else QtGui.QIcon.Disabled
            if icon is not None and not icon.isNull():
                icon.paint(p, QtCore.QRect(int(cx - 12), int(cy - 22), 24, 24), Qt.AlignCenter, mode)
            p.setPen(QtGui.QColor("#1F2326" if item.get("enabled", True) else "#9AA0A6"))
            f = p.font()
            f.setPointSizeF(max(f.pointSizeF() - 1, 7))
            p.setFont(f)
            p.drawText(QtCore.QRectF(cx - 46, cy + 2, 92, 30), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       item["label"])
            # sector divider
            a = math.radians(i * step + step / 2.0)
            p.setPen(QtGui.QPen(QtGui.QColor("#C9CED3"), 1))
            p.drawLine(QtCore.QPointF(c.x() + INNER * math.sin(a), c.y() - INNER * math.cos(a)),
                       QtCore.QPointF(c.x() + OUTER * math.sin(a), c.y() - OUTER * math.cos(a)))
        p.end()

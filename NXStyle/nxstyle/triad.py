# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX-style view triad in the lower-left corner of a 3D view.

FreeCAD 1.0 can only show its corner coordinate system in the lower-right, so
NXStyle hides that one and paints its own transparent overlay that follows the
camera orientation.
"""

import FreeCAD as App

from .qt import QtCore, QtGui, QtWidgets, Qt

AXES = [("X", App.Vector(1, 0, 0), "#D32F2F"),
        ("Y", App.Vector(0, 1, 0), "#2E7D32"),
        ("Z", App.Vector(0, 0, 1), "#1565C0")]
SIZE = 78
MARGIN = 6


class ViewTriad(QtWidgets.QWidget):
    def __init__(self, view, host):
        super().__init__(host)
        self.setObjectName("NXViewTriad")
        self.view = view
        self.host = host
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(SIZE, SIZE)
        self._last = None
        host.installEventFilter(self)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(60)
        self.place()
        self.show()
        self.raise_()

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Resize:
            self.place()
        return False

    def place(self):
        vp = self.host.viewport() if hasattr(self.host, "viewport") else self.host
        g = vp.geometry()
        self.move(g.left() + MARGIN, g.bottom() - SIZE - MARGIN)
        self.raise_()

    def orientation(self):
        try:
            return self.view.getCameraOrientation()
        except Exception:
            return None

    def _poll(self):
        rot = self.orientation()
        q = tuple(round(v, 4) for v in rot.Q) if rot is not None else None
        if q != self._last:
            self._last = q
            self.update()

    def projected(self):
        """[(label, dx, dy, depth, colour)] in widget pixels from the centre."""
        rot = self.orientation()
        if rot is None:
            return []
        inv = rot.inverted()
        r = SIZE * 0.36
        out = []
        for label, axis, col in AXES:
            c = inv.multVec(axis)
            out.append((label, c.x * r, -c.y * r, c.z, col))
        return out

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        o = QtCore.QPointF(SIZE * 0.45, SIZE * 0.55)
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(8)
        p.setFont(f)
        for label, dx, dy, depth, col in sorted(self.projected(), key=lambda a: a[3]):
            color = QtGui.QColor(col)
            if depth < -0.2:
                color.setAlpha(120)
            p.setPen(QtGui.QPen(color, 2.2))
            tip = QtCore.QPointF(o.x() + dx, o.y() + dy)
            p.drawLine(o, tip)
            p.setBrush(color)
            p.drawEllipse(tip, 2.2, 2.2)
            p.drawText(QtCore.QPointF(tip.x() + (4 if dx >= 0 else -11), tip.y() + (4 if dy >= 0 else -2)), label)
        p.end()

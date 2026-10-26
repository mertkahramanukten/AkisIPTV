"""Vektörel ikonlar (QPainter ile çizilir → font/emoji eksikliğinde bozulmaz, her DPI'da net)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

_cache: dict[tuple, QIcon] = {}


def _poly(points, s):
    return QPolygonF([QPointF(x * s, y * s) for x, y in points])


def _draw(p: QPainter, name: str, s: float, color: QColor) -> None:
    pen = QPen(color, max(1.5, s * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    fill = QBrush(color)
    if name == "play":
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly([(0.28, 0.18), (0.28, 0.82), (0.82, 0.5)], s))
    elif name == "pause":
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0.24 * s, 0.2 * s, 0.17 * s, 0.6 * s), 2, 2)
        p.drawRoundedRect(QRectF(0.59 * s, 0.2 * s, 0.17 * s, 0.6 * s), 2, 2)
    elif name in ("back", "fwd"):
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        pts1 = [(0.5, 0.25), (0.5, 0.75), (0.12, 0.5)]
        pts2 = [(0.88, 0.25), (0.88, 0.75), (0.5, 0.5)]
        if name == "fwd":
            pts1 = [(1 - x, y) for x, y in pts1]
            pts2 = [(1 - x, y) for x, y in pts2]
        p.drawPolygon(_poly(pts1, s))
        p.drawPolygon(_poly(pts2, s))
    elif name in ("volume", "mute"):
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly([(0.12, 0.38), (0.3, 0.38), (0.52, 0.18), (0.52, 0.82), (0.3, 0.62), (0.12, 0.62)], s))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if name == "volume":
            p.drawArc(QRectF(0.42 * s, 0.32 * s, 0.26 * s, 0.36 * s), -50 * 16, 100 * 16)
            p.drawArc(QRectF(0.42 * s, 0.18 * s, 0.44 * s, 0.64 * s), -50 * 16, 100 * 16)
        else:
            p.drawLine(QPointF(0.64 * s, 0.36 * s), QPointF(0.9 * s, 0.64 * s))
            p.drawLine(QPointF(0.9 * s, 0.36 * s), QPointF(0.64 * s, 0.64 * s))
    elif name == "fullscreen":
        a, b, c = 0.18 * s, 0.38 * s, 0.82 * s
        for (x, y, dx, dy) in ((a, a, 1, 1), (c, a, -1, 1), (a, c, 1, -1), (c, c, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * (b - a), y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * (b - a)))
    elif name == "refresh":
        r = QRectF(0.2 * s, 0.2 * s, 0.6 * s, 0.6 * s)
        p.drawArc(r, 40 * 16, 290 * 16)
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        ang = math.radians(40)
        cx, cy, rad = 0.5 * s, 0.5 * s, 0.3 * s
        tip = QPointF(cx + rad * math.cos(ang), cy - rad * math.sin(ang))
        p.drawPolygon(QPolygonF([tip + QPointF(0.13 * s, 0.0), tip + QPointF(-0.02 * s, -0.16 * s),
                                 tip + QPointF(-0.1 * s, 0.06 * s)]))
    elif name == "dots":
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        for x in (0.25, 0.5, 0.75):
            p.drawEllipse(QPointF(x * s, 0.5 * s), 0.07 * s, 0.07 * s)
    elif name in ("star", "star_o"):
        pts = []
        for i in range(10):
            r = 0.4 if i % 2 == 0 else 0.17
            a = math.radians(-90 + i * 36)
            pts.append((0.5 + r * math.cos(a), 0.53 + r * math.sin(a)))
        if name == "star":
            p.setBrush(fill)
            p.setPen(Qt.NoPen)
        p.drawPolygon(_poly(pts, s))
    elif name == "gear":
        p.save()
        p.translate(0.5 * s, 0.5 * s)
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        for _ in range(8):
            p.rotate(45)
            p.drawRoundedRect(QRectF(-0.07 * s, -0.42 * s, 0.14 * s, 0.2 * s), 1.5, 1.5)
        p.drawEllipse(QPointF(0, 0), 0.27 * s, 0.27 * s)
        p.setBrush(QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawEllipse(QPointF(0, 0), 0.11 * s, 0.11 * s)
        p.restore()
    elif name == "search":
        p.drawEllipse(QRectF(0.18 * s, 0.18 * s, 0.46 * s, 0.46 * s))
        p.drawLine(QPointF(0.58 * s, 0.58 * s), QPointF(0.84 * s, 0.84 * s))
    elif name == "live":
        p.setBrush(QBrush(QColor("#FF5A5A")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.2 * s, 0.2 * s)
    elif name == "user":
        p.drawEllipse(QRectF(0.33 * s, 0.14 * s, 0.34 * s, 0.34 * s))
        path = QPainterPath()
        path.moveTo(0.16 * s, 0.88 * s)
        path.cubicTo(0.18 * s, 0.56 * s, 0.82 * s, 0.56 * s, 0.84 * s, 0.88 * s)
        p.drawPath(path)
    elif name == "pip":
        p.drawRoundedRect(QRectF(0.12 * s, 0.2 * s, 0.76 * s, 0.6 * s), 2, 2)
        p.setBrush(fill)
        p.drawRect(QRectF(0.5 * s, 0.5 * s, 0.3 * s, 0.22 * s))
    elif name == "eye":
        path = QPainterPath()
        path.moveTo(0.08 * s, 0.5 * s)
        path.quadTo(0.5 * s, 0.1 * s, 0.92 * s, 0.5 * s)
        path.quadTo(0.5 * s, 0.9 * s, 0.08 * s, 0.5 * s)
        p.drawPath(path)
        p.setBrush(fill)
        p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.12 * s, 0.12 * s)
    elif name == "health":
        path = QPainterPath()
        path.moveTo(0.1 * s, 0.55 * s)
        for x, y in ((0.32, 0.55), (0.42, 0.25), (0.55, 0.8), (0.65, 0.45), (0.9, 0.45)):
            path.lineTo(x * s, y * s)
        p.drawPath(path)


def icon(name: str, color: str = "#E6EDF5", size: int = 20) -> QIcon:
    key = (name, color, size)
    ic = _cache.get(key)
    if ic is not None:
        return ic
    ic = QIcon()
    for scale in (1, 2):
        s = size * scale
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        _draw(p, name, float(s), QColor(color))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    _cache[key] = ic
    return ic

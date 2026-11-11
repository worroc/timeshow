"""Shared Qt icon without importing the GUI, photo engine, or encryption."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#257d69"))
    painter.drawRoundedRect(2, 2, 60, 60, 15, 15)
    painter.setBrush(QColor("#d9f3de"))
    painter.drawEllipse(40, 13, 10, 10)
    painter.drawPolygon(QPolygonF([QPointF(10, 49), QPointF(28, 24), QPointF(46, 49)]))
    painter.setBrush(QColor("#a7d9ca"))
    painter.drawPolygon(QPolygonF([QPointF(29, 49), QPointF(43, 32), QPointF(56, 49)]))
    painter.end()
    return QIcon(pixmap)

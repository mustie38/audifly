"""Audifly marka ikonu — kodla çizilir (yazı tipi/emoji bağımlılığı yok).

Uygulama penceresi, sistem tepsisi ve paketleme (.ico üretimi:
packaging/make_icon.py) aynı çizimi kullanır; her boyutta keskin çıkar.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def build_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    u = size / 100.0                                   # 100×100 birimlik tasarım alanı

    # Zemin: Audifly teması (koyu lacivert → mor)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#2a2370"))
    grad.setColorAt(1.0, QColor("#8b5cf6"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(3 * u, 3 * u, 94 * u, 94 * u), 22 * u, 22 * u)

    # Çifte sekizlik nota (beyaz)
    white = QColor("white")
    p.setBrush(white)
    for cx in (36, 68):                                # nota başları
        p.save()
        p.translate(cx * u, 68 * u)
        p.rotate(-20)
        p.drawEllipse(QRectF(-9 * u, -6.5 * u, 18 * u, 13 * u))
        p.restore()
    stem_w = 4.2 * u
    for x in (43.5, 75.5):                             # saplar
        p.drawRect(QRectF(x * u, 27 * u, stem_w, 42 * u))
    beam = QPainterPath()                              # üstteki bağlantı çubuğu
    beam.moveTo(QPointF(43.5 * u, 27 * u))
    beam.lineTo(QPointF(79.7 * u, 20 * u))
    beam.lineTo(QPointF(79.7 * u, 32 * u))
    beam.lineTo(QPointF(43.5 * u, 39 * u))
    beam.closeSubpath()
    p.drawPath(beam)
    p.end()
    return pm


def build_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(build_pixmap(size))
    return icon

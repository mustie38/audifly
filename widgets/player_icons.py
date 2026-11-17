"""PlayerBar için emoji içermeyen, saf QPainter tabanlı basit vektör ikonlar.

Projede bir ikon fontu/kütüphanesi (qtawesome vb.) bulunmadığından ve yeni bir
bağımlılık eklemek istenmediğinden, ihtiyaç duyulan az sayıdaki ikon burada
24x24 birimlik bir "viewBox" üzerinde çizilip QPixmap/QIcon olarak üretilir.
Tüm ikonlar tek bir renk (accent ya da metin rengi) alır ve tema değiştiğinde
yeniden üretilmesi yeterlidir — herhangi bir resim dosyasına bağımlılık yoktur.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

_BOX = 24.0  # her ikonun tasarlandığı sanal 24x24 birim alan


def _painter(pixmap: QPixmap, size: int) -> QPainter:
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / _BOX, size / _BOX)
    return p


def _stroke(color: str, width: float = 1.8) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def icon_pixmap(kind: str, size: int, color: str) -> QPixmap:
    """`kind` ikonunu `color` renginde, `size`x`size` piksellik (2x DPR ile
    keskin görünen) bir QPixmap olarak döndürür."""
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = _painter(pm, size)
    draw = _DRAWERS.get(kind)
    if draw is not None:
        draw(p, color)
    p.end()
    return pm


def icon(kind: str, size: int, color: str) -> QIcon:
    return QIcon(icon_pixmap(kind, size, color))


# ---------------------------------------------------------------------------
# Tekil çizim fonksiyonları — hepsi 24x24 sanal alanda çalışır
# ---------------------------------------------------------------------------

def _draw_play(p: QPainter, color: str):
    path = QPainterPath()
    path.moveTo(7, 4.5)
    path.lineTo(19.5, 12)
    path.lineTo(7, 19.5)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def _draw_pause(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(6.5, 5, 4, 14), 1.5, 1.5)
    p.drawRoundedRect(QRectF(13.5, 5, 4, 14), 1.5, 1.5)


def _draw_next(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    tri = QPainterPath()
    tri.moveTo(5.5, 5)
    tri.lineTo(16, 12)
    tri.lineTo(5.5, 19)
    tri.closeSubpath()
    p.drawPath(tri)
    p.drawRoundedRect(QRectF(16.5, 5, 2.2, 14), 1, 1)


def _draw_prev(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    tri = QPainterPath()
    tri.moveTo(18.5, 5)
    tri.lineTo(8, 12)
    tri.lineTo(18.5, 19)
    tri.closeSubpath()
    p.drawPath(tri)
    p.drawRoundedRect(QRectF(5.3, 5, 2.2, 14), 1, 1)


def _draw_shuffle(p: QPainter, color: str):
    pen = _stroke(color)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(4, 18), QPointF(20, 6))
    p.drawLine(QPointF(4, 6), QPointF(20, 18))
    _arrowhead(p, color, QPointF(20, 6), -28)
    _arrowhead(p, color, QPointF(20, 18), 28)


def _arrowhead(p: QPainter, color: str, tip: QPointF, angle_deg: float):
    import math
    a = math.radians(angle_deg)
    length, spread = 4.5, 0.55
    back = QPointF(tip.x() - length * math.cos(a), tip.y() - length * math.sin(a))
    perp = QPointF(-math.sin(a), math.cos(a))
    p1 = QPointF(back.x() + perp.x() * length * spread, back.y() + perp.y() * length * spread)
    p2 = QPointF(back.x() - perp.x() * length * spread, back.y() - perp.y() * length * spread)
    path = QPainterPath()
    path.moveTo(tip)
    path.lineTo(p1)
    path.lineTo(p2)
    path.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)


def _repeat_track(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(4, 6, 16, 12), 5, 5)
    _arrowhead(p, color, QPointF(17.2, 6.2), -35)
    _arrowhead(p, color, QPointF(6.8, 17.8), 145)


def _draw_repeat(p: QPainter, color: str):
    _repeat_track(p, color)


def _draw_repeat_one(p: QPainter, color: str):
    _repeat_track(p, color)
    font = QFont()
    font.setPixelSize(8)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(QRectF(4, 6, 16, 12), Qt.AlignCenter, "1")


def _draw_queue(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    widths = (14, 14, 9)
    for i, w in enumerate(widths):
        y = 6.5 + i * 5.5
        p.drawLine(QPointF(4, y), QPointF(4 + w, y))


def _draw_lyrics(p: QPainter, color: str):
    # Basit sekizlik nota: yuvarlak baş + sap + bayrak
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(5.5, 14.5, 5.5, 4.2))
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.drawLine(QPointF(10.6, 16.5), QPointF(10.6, 5))
    path = QPainterPath()
    path.moveTo(10.6, 5)
    path.cubicTo(14, 5.5, 16.5, 7.5, 15.5, 11)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def _draw_volume(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    body = QPainterPath()
    body.moveTo(4, 9.5)
    body.lineTo(7.5, 9.5)
    body.lineTo(12, 5.5)
    body.lineTo(12, 18.5)
    body.lineTo(7.5, 14.5)
    body.lineTo(4, 14.5)
    body.closeSubpath()
    p.drawPath(body)
    pen = _stroke(color, 1.6)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(14.5, 7.5, 6, 9), -60 * 16, 120 * 16)
    p.drawArc(QRectF(16.7, 4.5, 6, 15), -55 * 16, 110 * 16)


def _draw_volume_muted(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    body = QPainterPath()
    body.moveTo(4, 9.5)
    body.lineTo(7.5, 9.5)
    body.lineTo(12, 5.5)
    body.lineTo(12, 18.5)
    body.lineTo(7.5, 14.5)
    body.lineTo(4, 14.5)
    body.closeSubpath()
    p.drawPath(body)
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.drawLine(QPointF(15.5, 9), QPointF(21, 15))
    p.drawLine(QPointF(21, 9), QPointF(15.5, 15))


def _draw_heart(p: QPainter, color: str, filled: bool):
    path = QPainterPath()
    path.moveTo(12, 19.5)
    path.cubicTo(4.5, 14.2, 2.5, 10.4, 3.8, 7.6)
    path.cubicTo(5.0, 5.0, 8.6, 4.3, 12, 7.6)
    path.cubicTo(15.4, 4.3, 19.0, 5.0, 20.2, 7.6)
    path.cubicTo(21.5, 10.4, 19.5, 14.2, 12, 19.5)
    path.closeSubpath()
    if filled:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
    else:
        p.setPen(_stroke(color, 1.6))
        p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def _draw_plus(p: QPainter, color: str):
    pen = _stroke(color, 2.0)
    p.setPen(pen)
    p.drawLine(QPointF(12, 5.5), QPointF(12, 18.5))
    p.drawLine(QPointF(5.5, 12), QPointF(18.5, 12))


def _draw_more(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    for x in (6, 12, 18):
        p.drawEllipse(QPointF(x, 12), 1.6, 1.6)


def _draw_fullscreen(p: QPainter, color: str):
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(4, 9), QPointF(4, 4))
    p.drawLine(QPointF(4, 4), QPointF(9, 4))
    p.drawLine(QPointF(15, 4), QPointF(20, 4))
    p.drawLine(QPointF(20, 4), QPointF(20, 9))
    p.drawLine(QPointF(20, 15), QPointF(20, 20))
    p.drawLine(QPointF(20, 20), QPointF(15, 20))
    p.drawLine(QPointF(9, 20), QPointF(4, 20))
    p.drawLine(QPointF(4, 20), QPointF(4, 15))


_DRAWERS = {
    "play": _draw_play,
    "pause": _draw_pause,
    "next": _draw_next,
    "prev": _draw_prev,
    "shuffle": _draw_shuffle,
    "repeat": _draw_repeat,
    "repeat_one": _draw_repeat_one,
    "queue": _draw_queue,
    "lyrics": _draw_lyrics,
    "fullscreen": _draw_fullscreen,
    "volume": _draw_volume,
    "volume_muted": _draw_volume_muted,
    "heart": lambda p, c: _draw_heart(p, c, False),
    "heart_filled": lambda p, c: _draw_heart(p, c, True),
    "more": _draw_more,
    "plus": _draw_plus,
}

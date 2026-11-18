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


def _draw_mic(p: QPainter, color: str):
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # Mikrofon kapsülü
    p.drawRoundedRect(QRectF(9, 3, 6, 10.5), 3, 3)
    # U-şekilli tutucu çerçeve
    cradle = QPainterPath()
    cradle.moveTo(5.5, 9.5)
    cradle.quadTo(5.5, 17, 12, 17)
    cradle.quadTo(18.5, 17, 18.5, 9.5)
    p.drawPath(cradle)
    # Dikey ayak ve taban
    p.drawLine(QPointF(12, 17), QPointF(12, 21))
    p.drawLine(QPointF(8, 21), QPointF(16, 21))


def _draw_radio(p: QPainter, color: str):
    # Merkez yayın noktası + iki yöne yayılan sinyal halkaları
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(12, 12), 2.2, 2.2)
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # İç yaylar
    p.drawArc(QRectF(6.5, 6.5, 11, 11), -45 * 16, 90 * 16)
    p.drawArc(QRectF(6.5, 6.5, 11, 11), 135 * 16, 90 * 16)
    # Dış yaylar
    p.drawArc(QRectF(3.0, 3.0, 18, 18), -45 * 16, 90 * 16)
    p.drawArc(QRectF(3.0, 3.0, 18, 18), 135 * 16, 90 * 16)


def _draw_spectrum(p: QPainter, color: str):
    # 4 yuvarlatılmış ses spektrum çubuğu
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    bars = ((4.5, 11, 2.6, 8), (9.0, 5, 2.6, 14), (13.5, 8.5, 2.6, 10.5), (18.0, 6.5, 2.6, 12.5))
    for x, y, w, h in bars:
        p.drawRoundedRect(QRectF(x, y, w, h), 1.3, 1.3)


def _draw_expand(p: QPainter, color: str):
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # Sağ-üst ok
    p.drawLine(QPointF(14, 4), QPointF(20, 4))
    p.drawLine(QPointF(20, 4), QPointF(20, 10))
    p.drawLine(QPointF(20, 4), QPointF(13.5, 10.5))
    # Sol-alt ok
    p.drawLine(QPointF(10, 20), QPointF(4, 20))
    p.drawLine(QPointF(4, 20), QPointF(4, 14))
    p.drawLine(QPointF(4, 20), QPointF(10.5, 13.5))


def _draw_close(p: QPainter, color: str):
    pen = _stroke(color, 1.9)
    p.setPen(pen)
    p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
    p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))


def _draw_home(p: QPainter, color: str):
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(4, 10.8)
    path.lineTo(12, 4)
    path.lineTo(20, 10.8)
    p.drawPath(path)
    body = QPainterPath()
    body.moveTo(6.2, 9.8)
    body.lineTo(6.2, 19.5)
    body.lineTo(17.8, 19.5)
    body.lineTo(17.8, 9.8)
    p.drawPath(body)
    p.drawLine(QPointF(10, 19.5), QPointF(10, 14.5))
    p.drawLine(QPointF(14, 19.5), QPointF(14, 14.5))
    p.drawLine(QPointF(10, 14.5), QPointF(14, 14.5))


def _draw_compass(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(12, 12), 8.2, 8.2)
    needle = QPainterPath()
    needle.moveTo(15.5, 8.5)
    needle.lineTo(13.2, 13.2)
    needle.lineTo(8.5, 15.5)
    needle.lineTo(10.8, 10.8)
    needle.closeSubpath()
    p.drawPath(needle)


def _draw_grid(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    for x in (4.5, 13.0):
        for y in (4.5, 13.0):
            p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.8, 1.8)


def _draw_download(p: QPainter, color: str):
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(12, 4.5), QPointF(12, 15.0))
    p.drawLine(QPointF(8.0, 11.2), QPointF(12, 15.2))
    p.drawLine(QPointF(16.0, 11.2), QPointF(12, 15.2))
    tray = QPainterPath()
    tray.moveTo(4.5, 15.5)
    tray.lineTo(4.5, 19.2)
    tray.lineTo(19.5, 19.2)
    tray.lineTo(19.5, 15.5)
    p.drawPath(tray)


def _draw_folder(p: QPainter, color: str, is_open: bool = False):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(3.5, 6.5)
    path.lineTo(9.2, 6.5)
    path.lineTo(11.2, 8.8)
    path.lineTo(20.5, 8.8)
    path.lineTo(20.5, 18.5)
    path.lineTo(3.5, 18.5)
    path.closeSubpath()
    p.drawPath(path)
    if is_open:
        p.drawLine(QPointF(3.8, 12.2), QPointF(20.2, 12.2))


def _draw_star(p: QPainter, color: str):
    import math
    pen = _stroke(color, 1.6)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    cx, cy, r_out, r_in = 12.0, 12.2, 8.2, 3.6
    for i in range(10):
        angle = math.radians(-90 + i * 36)
        r = r_out if i % 2 == 0 else r_in
        pt = QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle))
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)


def _draw_clock(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(12, 12), 8.2, 8.2)
    p.drawLine(QPointF(12, 7.2), QPointF(12, 12.2))
    p.drawLine(QPointF(12, 12.2), QPointF(15.5, 14.2))


def _draw_sparkle(p: QPainter, color: str):
    pen = _stroke(color, 1.6)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(12, 3.5)
    path.quadTo(12.6, 11.4, 20.5, 12)
    path.quadTo(12.6, 12.6, 12, 20.5)
    path.quadTo(11.4, 12.6, 3.5, 12)
    path.quadTo(11.4, 11.4, 12, 3.5)
    p.drawPath(path)


def _draw_disc(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(12, 12), 8.2, 8.2)
    p.drawEllipse(QPointF(12, 12), 2.5, 2.5)


def _draw_user(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(12, 8.2), 3.6, 3.6)
    arc = QPainterPath()
    arc.moveTo(5.2, 19.5)
    arc.cubicTo(5.8, 14.5, 18.2, 14.5, 18.8, 19.5)
    p.drawPath(arc)


def _draw_archive(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(4, 5, 16, 4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(5.5, 9, 13, 10), 1.5, 1.5)
    p.drawLine(QPointF(9.5, 13.2), QPointF(14.5, 13.2))


def _draw_sliders(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    for y, knob_x in ((6.5, 9.5), (12.0, 15.0), (17.5, 10.5)):
        p.drawLine(QPointF(4, y), QPointF(20, y))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(knob_x, y), 2.0, 2.0)


def _draw_settings(p: QPainter, color: str):
    import math
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    p.drawEllipse(QPointF(12, 12), 6.5, 6.5)
    for i in range(6):
        a = math.radians(i * 60)
        p.drawLine(
            QPointF(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)),
            QPointF(12 + 8.6 * math.cos(a), 12 + 8.6 * math.sin(a)),
        )


def _draw_mini_player(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 5.0, 17.0, 14.0), 2.2, 2.2)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(11.5, 11.2, 7.2, 5.8), 1.4, 1.4)


def _draw_diagnostics(p: QPainter, color: str):
    pen = _stroke(color, 1.8)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(3.0, 12.0)
    path.lineTo(7.5, 12.0)
    path.lineTo(9.8, 6.0)
    path.lineTo(13.8, 18.0)
    path.lineTo(16.2, 12.0)
    path.lineTo(21.0, 12.0)
    p.drawPath(path)


def _draw_chart(p: QPainter, color: str):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    for x, y, h in ((5.0, 13.0, 6.5), (10.5, 8.5, 11.0), (16.0, 5.0, 14.5)):
        p.drawRoundedRect(QRectF(x, y, 3.2, h), 1.2, 1.2)


def _draw_gift(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(4.0, 8.5, 16.0, 3.5), 1.0, 1.0)
    p.drawRoundedRect(QRectF(5.2, 12.0, 13.6, 7.5), 1.2, 1.2)
    p.drawLine(QPointF(12.0, 8.5), QPointF(12.0, 19.5))
    p.drawEllipse(QRectF(8.2, 5.0, 3.8, 3.5))
    p.drawEllipse(QRectF(12.0, 5.0, 3.8, 3.5))


def _draw_bell(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(6.0, 16.5)
    path.lineTo(18.0, 16.5)
    path.quadTo(16.5, 14.5, 16.5, 10.0)
    path.cubicTo(16.5, 6.2, 7.5, 6.2, 7.5, 10.0)
    path.quadTo(7.5, 14.5, 6.0, 16.5)
    p.drawPath(path)
    p.drawArc(QRectF(10.2, 16.5, 3.6, 3.2), 180 * 16, 180 * 16)


def _draw_sidebar_right(p: QPainter, color: str):
    pen = _stroke(color, 1.7)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 4.5, 17.0, 15.0), 2.5, 2.5)
    p.drawLine(QPointF(14.5, 4.5), QPointF(14.5, 19.5))


def _draw_search(p: QPainter, color: str):
    p.setPen(_stroke(color, 1.8))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4.0, 4.0, 10.0, 10.0))
    p.drawLine(QPointF(11.2, 11.2), QPointF(18.5, 18.5))


def _draw_bolt(p: QPainter, color: str):
    p.setPen(_stroke(color, 1.6))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(13.0, 2.5)
    path.lineTo(6.5, 12.0)
    path.lineTo(11.5, 12.0)
    path.lineTo(10.0, 21.5)
    path.lineTo(17.5, 11.0)
    path.lineTo(12.5, 11.0)
    path.closeSubpath()
    p.drawPath(path)


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
    "mic": _draw_mic,
    "radio": _draw_radio,
    "spectrum": _draw_spectrum,
    "expand": _draw_expand,
    "close": _draw_close,
    "home": _draw_home,
    "compass": _draw_compass,
    "grid": _draw_grid,
    "download": _draw_download,
    "folder": lambda p, c: _draw_folder(p, c, False),
    "folder_open": lambda p, c: _draw_folder(p, c, True),
    "star": _draw_star,
    "clock": _draw_clock,
    "sparkle": _draw_sparkle,
    "disc": _draw_disc,
    "user": _draw_user,
    "archive": _draw_archive,
    "sliders": _draw_sliders,
    "settings": _draw_settings,
    "mini_player": _draw_mini_player,
    "diagnostics": _draw_diagnostics,
    "chart": _draw_chart,
    "gift": _draw_gift,
    "bell": _draw_bell,
    "sidebar_right": _draw_sidebar_right,
    "search": _draw_search,
    "bolt": _draw_bolt,
    "volume": _draw_volume,
    "volume_muted": _draw_volume_muted,
    "heart": lambda p, c: _draw_heart(p, c, False),
    "heart_filled": lambda p, c: _draw_heart(p, c, True),
    "more": _draw_more,
    "plus": _draw_plus,
}

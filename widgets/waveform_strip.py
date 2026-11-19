"""
Canlı neon waveform (ses dalgası) şeridi — PlayerBar'da süre çubuğunun arkasında
veya altında akan neon spektrum şeridi.

Orijinal mustiefly_now_playing._build_waveform_strip / _animate_waveform'un
geliştirilmiş Neon Spektrum QWidget.paintEvent portudur.
Dinlenme konumunda zamanlayıcı tamamen durur (boşta %0 CPU kullanımı).
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from mustiefly_qt.widgets.audio_visualizer import PALETTES, _complementary_neon

TICK_MS = 55
BAR_COUNT = 90


class WaveformStrip(QWidget):
    def __init__(self, accent: str = "#FF7A3D", parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self._accent_hex = accent or "#FF7A3D"
        self._accent = QColor(self._accent_hex)
        self._c1, self._c2 = _complementary_neon(self._accent_hex)
        self._palette = "dynamic"
        self._enabled = True
        self._heights = [1.0] * BAR_COUNT
        self._phase = 0.0
        self._playing = False

        # Boştayken bile her tik'te yeniden boyamamak için: dinlenme konumunda
        # zamanlayıcı durur; set_playing(True) ile tekrar başlar.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_accent(self, color: str):
        self._accent_hex = color or "#FF7A3D"
        self._accent = QColor(self._accent_hex)
        self._apply_colors()
        self.update()

    def set_palette(self, palette: str):
        if palette in PALETTES:
            self._palette = palette
            self._apply_colors()
            self.update()

    def set_enabled_state(self, enabled: bool):
        self._enabled = bool(enabled)
        if not self._enabled:
            self._timer.stop()
        elif self._playing and self.isVisible() and not self._timer.isActive():
            self._timer.start(TICK_MS)
        self.update()

    def _apply_colors(self):
        if self._palette == "dynamic":
            self._c1, self._c2 = _complementary_neon(self._accent_hex)
        else:
            _, h1, h2 = PALETTES[self._palette]
            self._c1 = QColor(h1)
            self._c2 = QColor(h2)

    def set_playing(self, playing: bool):
        self._playing = bool(playing)
        if self._playing and self.isVisible() and self._enabled:
            if not self._timer.isActive():
                self._timer.start(TICK_MS)
        # Durunca hemen durdurmuyoruz: barlar önce düz çizgiye iner (_tick yönetir).

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._playing and self._enabled and not self._timer.isActive():
            self._timer.start(TICK_MS)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        at_rest = not self._playing and all(abs(h - 1.0) < 0.05 for h in self._heights)
        if at_rest:
            self._timer.stop()
            return
        self._phase += 0.28
        max_h = max(float(self.height() - 1), 9.0)
        for i in range(BAR_COUNT):
            if self._playing:
                norm_i = i / max(1, BAR_COUNT - 1)
                wave = (
                    math.sin(self._phase + i * 0.18) * 0.45
                    + math.cos(self._phase * 0.7 - i * 0.11) * 0.35
                )
                envelope = math.sin(norm_i * math.pi) * 0.65 + 0.35
                ratio = max(0.12, min(1.0, (0.48 + wave * 0.38 + random.uniform(-0.15, 0.22)) * envelope))
                target = 1.0 + ratio * (max_h - 1.0)
            else:
                target = 1.0
            cur = self._heights[i]
            self._heights[i] = cur + (target - cur) * 0.5  # yumuşak geçiş
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if not self._enabled:
            return
        w = float(self.width() or 1400)
        h = float(self.height())
        if h <= 0:
            return
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        bar_w = max(w / BAR_COUNT, 2.0)

        brush_key = (int(w), self._c1.rgba(), self._c2.rgba())
        if getattr(self, "_cached_brush_key", None) != brush_key:
            grad = QLinearGradient(0, 0, w, 0)
            c1 = QColor(self._c1.red(), self._c1.green(), self._c1.blue(), 195)
            c2 = QColor(self._c2.red(), self._c2.green(), self._c2.blue(), 215)
            grad.setColorAt(0.0, c1)
            grad.setColorAt(0.5, c2)
            grad.setColorAt(1.0, c1)
            self._cached_brush = QBrush(grad)
            self._cached_brush_key = brush_key
        painter.setBrush(self._cached_brush)

        draw_w = max(bar_w - 2.0, 1.2)
        for i, bh in enumerate(self._heights):
            x = i * bar_w
            bh_clamped = max(1.0, min(h, float(bh)))
            painter.drawRect(QRectF(x, h - bh_clamped, draw_w, bh_clamped))
        painter.end()

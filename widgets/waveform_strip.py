"""
Canlı waveform (ses dalgası) şeridi — pencerenin altında ince, animasyonlu çizgi.

Orijinal mustiefly_now_playing._build_waveform_strip / _animate_waveform'un
QWidget.paintEvent portudur. Kozmetiktir: sese göre gerçek analiz yapmaz,
çalarken barlar yumuşak geçişlerle zıplar, durunca düz çizgiye iner.
"""
from __future__ import annotations

import random

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

TICK_MS = 160
BAR_COUNT = 90


class WaveformStrip(QWidget):
    def __init__(self, accent: str = "#FF7A3D", parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self._accent = QColor(accent)
        self._heights = [1.0] * BAR_COUNT
        self._playing = False

        # Boştayken bile her tik'te yeniden boyamamak için: dinlenme konumunda
        # zamanlayıcı durur; set_playing(True) ile tekrar başlar.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_accent(self, color: str):
        self._accent = QColor(color)
        self.update()

    def set_playing(self, playing: bool):
        self._playing = bool(playing)
        if self._playing and self.isVisible():
            if not self._timer.isActive():
                self._timer.start(TICK_MS)
        # Durunca hemen durdurmuyoruz: barlar önce düz çizgiye iner (_tick yönetir).

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._playing and not self._timer.isActive():
            self._timer.start(TICK_MS)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        at_rest = not self._playing and all(abs(h - 1.0) < 0.05 for h in self._heights)
        if at_rest:
            self._timer.stop()
            return
        for i in range(BAR_COUNT):
            target = random.uniform(1.0, 9.0) if self._playing else 1.0
            cur = self._heights[i]
            self._heights[i] = cur + (target - cur) * 0.5  # yumuşak geçiş
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._accent)
        w = self.width() or 1400
        bar_w = max(w / BAR_COUNT, 2.0)
        h = self.height()
        for i, bh in enumerate(self._heights):
            x = i * bar_w
            painter.drawRect(int(x), int(h - bh), max(int(bar_w) - 2, 1), int(bh))
        painter.end()

"""
Dönen plak animasyonu — çalan şarkının kapağı varken plak gibi döner.

Orijinal mustiefly_sidebar_thumbnails._rotate_vinyl_tick'in QWidget.paintEvent +
QTimer portudur. Kapak yokken ya da müzik dururken sadece son kareyi gösterir
(CPU harcamaz).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

TICK_MS = 130          # ~7.7 fps — orijinaldeki performans dengesi
DEGREES_PER_TICK = 10  # aynı açısal hız, daha düşük kare hızı


class VinylCoverWidget(QWidget):
    """Kare bir QPixmap'i dairesel kırparak plak gibi sürekli döndürür.
    pixmap boşken ortadaki fallback metni (🎵 / 📻) gösterir."""

    def __init__(self, size: int = 220, fallback: str = "🎵", parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.fallback_label = QLabel(fallback)
        self.fallback_label.setAlignment(Qt.AlignCenter)
        self.fallback_label.setStyleSheet(
            f"background: #241c38; border-radius: {size // 4}px; font-size: {size // 3}px;"
        )
        layout.addWidget(self.fallback_label)

        self._base_pixmap: QPixmap | None = None   # dairesel kırpılmış kapak
        self._angle = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_playing(self, playing: bool):
        self._want_playing = bool(playing)
        if self._want_playing and self._base_pixmap is not None and self.isVisible():
            if not self._timer.isActive():
                self._timer.start(TICK_MS)
        else:
            self._timer.stop()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_want_playing", False) and self._base_pixmap is not None:
            if not self._timer.isActive():
                self._timer.start(TICK_MS)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def set_pixmap(self, pm: QPixmap | None):
        """Kapağı ayarlar (kare verilirse dairesel kırpılır). None ise fallback'e döner."""
        if pm is None or pm.isNull():
            self._base_pixmap = None
            self._timer.stop()
            self.fallback_label.setVisible(True)
            self.update()
            return
        self.fallback_label.setVisible(False)
        s = min(pm.width(), pm.height())
        self._base_pixmap = pm.copy(
            (pm.width() - s) // 2, (pm.height() - s) // 2, s, s
        )
        self._rotated_cache = None
        self._angle = 0.0
        if getattr(self, "_want_playing", False) and self.isVisible():
            if not self._timer.isActive():
                self._timer.start(TICK_MS)
        self.update()

    def set_fallback_text(self, text: str):
        self.fallback_label.setText(text)

    def set_fallback_gradient(self, top_color: str, bottom_color: str):
        """Kapak yokken düz renk yerine yumuşak bir renk geçişi gösterir
        (örn. şarkı başlığından türetilen renk + onun koyu tonu)."""
        self.fallback_label.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {top_color}, stop:1 {bottom_color});"
            f" border-radius: {self._size // 4}px; font-size: {self._size // 3}px;"
        )

    def _tick(self):
        self._angle = (self._angle + DEGREES_PER_TICK) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._base_pixmap is None:
            return  # fallback QLabel görünür durumda
        # Her karede transformed() ile yeni QPixmap üretmek yerine painter'ı döndür.
        pm = self._base_pixmap
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-self._angle)
        painter.drawPixmap(QPointF(-pm.width() / 2, -pm.height() / 2), pm)
        painter.end()

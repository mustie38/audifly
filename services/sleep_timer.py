"""Uyku zamanlayıcısı: süre dolunca müziği duraklatır; isteğe bağlı kademeli fade-out.

Gerçek süre `time.monotonic()` bitiş anına göre hesaplanır (zamanlayıcı
gecikse bile kayma olmaz). Fade, motorun geçici ses çarpanıyla yapılır —
kullanıcının kalıcı ses ayarı değişmez ve duraklatma sonrası ses eski
seviyesine döner.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

MAX_MINUTES = 12 * 60
FADE_SECONDS = 30
TICK_MS = 1000
MAX_LOADING_WAIT_S = 30    # süre dolduğunda şarkı çözülüyorsa (yükleniyor) en fazla bu kadar bekle


class SleepTimer(QObject):
    changed = Signal()        # başladı / iptal / bitti
    finished = Signal()

    def __init__(self, playback, parent=None):
        super().__init__(parent)
        self.playback = playback
        self._deadline: float | None = None
        self._fade_seconds = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._deadline is not None

    def remaining_seconds(self) -> int:
        if self._deadline is None:
            return 0
        return max(0, int(round(self._deadline - time.monotonic())))

    def start(self, minutes: float, fade: bool = True) -> bool:
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return False
        if not (0 < minutes <= MAX_MINUTES):
            return False
        total = minutes * 60
        self._cancel_fade()
        self._deadline = time.monotonic() + total
        self._fade_seconds = min(FADE_SECONDS, total / 2) if fade else 0.0
        self._timer.start()
        self.changed.emit()
        return True

    def cancel(self):
        if self._deadline is None:
            return
        self._timer.stop()
        self._deadline = None
        self._cancel_fade()
        self.changed.emit()

    def _cancel_fade(self):
        self.playback.set_volume_scale(1.0)

    def _tick(self):
        if self._deadline is None:
            self._timer.stop()
            return
        left = self._deadline - time.monotonic()
        if left <= 0:
            # Şarkı o an çözülüyorsa pause() hiçbir şey yapmazdı ve müzik sonradan çalmaya başlardı:
            # yükleme bitene (en çok MAX_LOADING_WAIT_S) kadar bekle, sonra duraklat.
            if getattr(self.playback, "is_loading", False) and left > -MAX_LOADING_WAIT_S:
                self.playback.set_volume_scale(0.0)
                return
            self._finish()
            return
        if self._fade_seconds and left < self._fade_seconds:
            self.playback.set_volume_scale(left / self._fade_seconds)

    def _finish(self):
        self._timer.stop()
        self._deadline = None
        try:
            self.playback.pause()
        finally:
            self.playback.set_volume_scale(1.0)   # sonraki ▶ normal seviyede
        self.changed.emit()
        self.finished.emit()

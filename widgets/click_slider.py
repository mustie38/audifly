"""Tıklanan yere doğrudan atlayan kaydırıcı.

QSlider varsayılanında çizgiye tıklamak sayfa adımı atlar; kullanıcı
tıkladığı noktaya gitmek ister. Bu bileşen tıklama anında değeri tıklanan
konuma ayarlar (sürükleyince normal davranış sürer).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QStyle


class ClickSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._click_seeking = False

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            self._click_seeking = True
            self.setSliderDown(True)
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), max(self.width() - 1, 1))
            self.setValue(val)
            self.sliderPressed.emit()
            self.sliderMoved.emit(val)
            event.accept()
            return
        self._click_seeking = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._click_seeking and event.button() == Qt.LeftButton:
            self._click_seeking = False
            self.setSliderDown(False)
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

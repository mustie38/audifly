"""
"Geri Al" ve durum/hata snackbar'ı (toast bildirimi).

Silme/temizleme işlemlerinden sonra alt kısımda belirir; 8 saniye içinde
"Geri Al" butonuna basılırsa son işlem geri alınır. Hata bildirimlerinde ise
"🩺 Sorun Bildir" butonu gösterilir; kullanıcı tek tıkla tanılama raporunu
kopyalayıp paylaşabilir.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class UndoSnackbar(QWidget):
    undoClicked = Signal()
    reportClicked = Signal()

    HIDE_AFTER_MS = 8000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Snackbar")
        self.setVisible(False)
        self._mode = "undo"

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        row.addWidget(self.message_label, stretch=1)

        self.undo_btn = QPushButton("↩ Geri Al")
        self.undo_btn.setObjectName("Primary")
        self.undo_btn.clicked.connect(self._on_action)
        row.addWidget(self.undo_btn)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(self, message: str, undoable: bool = True,
                     duration_ms: int | None = None, reportable: bool = False):
        """undoable=True: 'Geri Al' butonlu, uzun ömürlü (silme işlemleri).
        reportable=True: '🩺 Sorun Bildir' butonlu (hata mesajları).
        İkisi de False: salt bilgilendirme (başarı mesajları), kısa ömürlü."""
        self.message_label.setText(message)
        if undoable:
            self._mode = "undo"
            self.undo_btn.setText("↩ Geri Al")
            self.undo_btn.setVisible(True)
        elif reportable:
            self._mode = "report"
            self.undo_btn.setText("🩺 Sorun Bildir")
            self.undo_btn.setVisible(True)
        else:
            self._mode = "info"
            self.undo_btn.setVisible(False)
        self._reposition()
        self.show()
        self.raise_()
        self._hide_timer.start(duration_ms or self.HIDE_AFTER_MS)

    def _reposition(self):
        """Pencerenin alt-ortasına hizalar (player bar'ın üstünde)."""
        p = self.parentWidget()
        if p is None:
            return
        w = min(560, max(280, p.width() - 40))
        h = self.sizeHint().height()
        self.setGeometry((p.width() - w) // 2, p.height() - h - 110, w, h)

    def _on_action(self):
        self._hide_timer.stop()
        self.hide()
        if self._mode == "report":
            self.reportClicked.emit()
        else:
            self.undoClicked.emit()

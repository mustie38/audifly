"""Wrapped sayfası: dönem seçimi, özet kartı ve PNG olarak dışa aktarma."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.services import wrapped as wr
from mustiefly_qt.views.stats_view import format_listen_time

CARD_W, CARD_H = 540, 780
# Paylaşılan görsel tema bağımsız olsun diye kart renkleri sabittir.
CARD_STYLE = """
#WrappedCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1d1b4b, stop:1 #6d28d9);
              border-radius: 24px; }
#WrappedCard QLabel { color: white; background: transparent; }
#WrappedCard QLabel#dim { color: rgba(255,255,255,170); }
"""


def _label(text: str, size: int = 14, bold: bool = False, dim: bool = False) -> QLabel:
    lbl = QLabel(text)
    f = QFont()
    f.setPixelSize(size)
    f.setBold(bold)
    lbl.setFont(f)
    lbl.setWordWrap(True)
    if dim:
        lbl.setObjectName("dim")
    return lbl


def period_label(period) -> str:
    return "Son 12 ay" if period == wr.LAST_12_MONTHS else str(period)


class WrappedCard(QFrame):
    """Dışa aktarılan görsel — sabit boyutlu."""

    def __init__(self, data: wr.Wrapped, parent=None):
        super().__init__(parent)
        self.setObjectName("WrappedCard")
        self.setStyleSheet(CARD_STYLE)
        self.setFixedSize(CARD_W, CARD_H)
        v = QVBoxLayout(self)
        v.setContentsMargins(32, 30, 32, 26)
        v.setSpacing(6)
        v.addWidget(_label(f"{APP_DISPLAY_NAME} Wrapped · {data.label}", 15, True, dim=True))
        v.addSpacing(8)
        v.addWidget(_label("Bu dönemde toplam", 14, dim=True))
        v.addWidget(_label(format_listen_time(data.total_seconds), 46, True))
        v.addWidget(_label(f"müzik dinledin · {data.plays} dinleme · {data.active_days} aktif gün", 13, dim=True))
        v.addSpacing(12)
        v.addWidget(_label("EN ÇOK DİNLEDİĞİN SANATÇILAR", 11, True, dim=True))
        for i, a in enumerate(data.top_artists, 1):
            v.addWidget(_label(f"{i}. {a['artist']}", 20 if i == 1 else 15, i == 1))
        v.addSpacing(10)
        v.addWidget(_label("EN ÇOK DİNLEDİĞİN ŞARKILAR", 11, True, dim=True))
        for i, s in enumerate(data.top_songs, 1):
            v.addWidget(_label(f"{i}. {s['title']} — {s['artist']}  ({s['plays']}×)", 13))
        v.addStretch(1)
        facts = [f"📅 En yoğun ay: {data.busiest_month}",
                 f"🕘 {data.busiest_weekday} günleri, {data.daypart.lower()}",
                 f"🔥 En uzun seri: {data.longest_streak} gün",
                 f"🌱 {data.new_artists} sanatçıyı ilk kez dinledin"]
        for f in facts:
            v.addWidget(_label(f, 13))


class WrappedView(QWidget):
    def __init__(self, playback, parent=None):
        super().__init__(parent)
        self.playback = playback
        self.card: WrappedCard | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 10)
        title = _label("🎁 Wrapped", 22, True)
        root.addWidget(title)
        row = QHBoxLayout()
        self.period_combo = QComboBox()
        self.period_combo.currentIndexChanged.connect(self._render)
        row.addWidget(self.period_combo)
        self.export_btn = QPushButton("🖼 PNG olarak kaydet")
        self.export_btn.clicked.connect(self._export_dialog)
        row.addWidget(self.export_btn)
        row.addStretch(1)
        root.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().setAutoFillBackground(False)
        self.host = QWidget()
        self.host.setAttribute(Qt.WA_StyledBackground, True)
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, stretch=1)

    def refresh(self):
        history = getattr(self.playback, "history", None)
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        for p in wr.available_periods(history):
            self.period_combo.addItem(period_label(p), p)
        self.period_combo.blockSignals(False)
        self._render()

    def _clear(self):
        while self.host_layout.count():
            w = self.host_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.card = None

    def _render(self, *_):
        self._clear()
        data = wr.build_wrapped(getattr(self.playback, "history", None), self.period_combo.currentData()
                                if self.period_combo.count() else wr.LAST_12_MONTHS)
        self.export_btn.setEnabled(data is not None)
        if data is None:
            note = _label(f"Bu dönem için henüz yeterli veri yok.\n"
                          f"Wrapped için en az {wr.MIN_EVENTS} dinleme ve {wr.MIN_DAYS} farklı gün gerekir "
                          f"(30 saniyeden uzun dinlemeler sayılır).", 14, dim=False)
            note.setObjectName("Muted")
            note.setAlignment(Qt.AlignCenter)
            self.host_layout.addWidget(note)
            return
        self.card = WrappedCard(data)
        self.host_layout.addWidget(self.card)

    def export_png(self, path: str) -> bool:
        if self.card is None:
            return False
        return self.card.grab().save(path, "PNG")

    def _export_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Wrapped görselini kaydet", "wrapped.png", "PNG (*.png)")
        if path and not self.export_png(path):
            QMessageBox.warning(self, "Wrapped", "Görsel kaydedilemedi.")

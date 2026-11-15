"""
Yinelenen şarkı bulucu — aynı YouTube videosunun birden fazla kopyasını bulur
ve tek tıkla temizler (geri alınabilir).

Orijinal find_duplicate_songs / open_duplicate_finder / _clean_duplicates'in
Qt portudur; silme mantığı PlaylistStore.clean_duplicates'tadır.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.services.playlist_store import PlaylistStore


class DuplicateFinderDialog(QDialog):
    def __init__(self, store: PlaylistStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.duplicates = store.find_duplicate_groups()

        self.setWindowTitle("🧹 Yinelenen Şarkılar")
        self.resize(560, 480)

        root = QVBoxLayout(self)
        title = QLabel("Yinelenen Şarkılar")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        if not self.duplicates:
            info = QLabel("🎉 Kütüphanende hiç yinelenen şarkı yok.")
            info.setObjectName("Muted")
            root.addWidget(info)
            return

        total_extra = sum(len(g) - 1 for g in self.duplicates)
        info = QLabel(f"{len(self.duplicates)} şarkının birden fazla kopyası var "
                      f"(temizlenirse {total_extra} kopya silinir).")
        info.setObjectName("Muted")
        root.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 12, 0)

        for group in self.duplicates:
            card = QWidget()
            card.setObjectName("Card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 8, 12, 8)
            song_title = group[0][2].get('title', 'Bilinmeyen Şarkı')
            t_label = QLabel(song_title[:60])
            t_label.setStyleSheet("font-weight: bold;")
            card_layout.addWidget(t_label)
            locations = ", ".join(f"{pl} (#{idx + 1})" for pl, idx, _ in group)
            loc_label = QLabel(locations)
            loc_label.setObjectName("Muted")
            loc_label.setWordWrap(True)
            card_layout.addWidget(loc_label)
            content_layout.addWidget(card)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        clean_btn = QPushButton(f"🧹 Kopyaları Temizle ({total_extra} şarkı)")
        clean_btn.setObjectName("Primary")
        clean_btn.clicked.connect(self._clean)
        btn_row.addWidget(clean_btn)
        root.addLayout(btn_row)

    def _clean(self):
        removed = self.store.clean_duplicates(self.duplicates)
        if removed:
            QMessageBox.information(
                self, "Temizlendi",
                f"🧹 {removed} yinelenen şarkı temizlendi.\n\n"
                f"Not: Yanlışlıkla sildiysen durum çubuğundaki \"↩ Geri Al\" ile "
                f"geri getirebilirsin (8 saniye içinde).")
        self.accept()

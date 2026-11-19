"""
🖼️ Paylaşılabilir Şarkı Sözü Kartı Diyaloğu:
Söz satırlarını seç/düzenle, kart temasını değiştir, tek tıkla panoya PNG
kopyala veya dosyaya kaydet.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.lyric_card import CARD_THEMES, render_lyric_card
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.helpers.win_theme import apply_dark_titlebar


class LyricCardDialog(QDialog):
    """Şarkı sözlerinden paylaşılabilir PNG kart üreten pencere."""

    def __init__(self, song: dict | None, thumbnails=None,
                 initial_lines: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.song = song or {}
        self.thumbnails = thumbnails
        self._theme_key = "dynamic"
        self._current_pixmap = None

        raw_t = self.song.get("title", "Bilinmeyen Şarkı")
        raw_u = self.song.get("uploader", "Audifly")
        self._title, self._artist = parse_track_and_artist(raw_t, raw_u, self.song)
        self._cover_pm = (
            self.thumbnails.pixmap_for(self.song, 256, rounded=False)
            if (self.thumbnails is not None and self.song) else None
        )

        self.setWindowTitle("🖼️ Şarkı Sözü Kartı Oluştur")
        self.resize(840, 620)
        apply_dark_titlebar(self, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(18)

        # SOL: Metin seçimi + Tema + Aksiyonlar
        left = QVBoxLayout()
        left.setSpacing(10)

        hdr = QLabel("🖼️ Şarkı Sözü Kartı")
        hf = QFont()
        hf.setPixelSize(19)
        hf.setBold(True)
        hdr.setFont(hf)
        left.addWidget(hdr)

        sub = QLabel(f"{self._title}  •  {self._artist}")
        sub.setObjectName("Muted")
        left.addWidget(sub)

        if initial_lines:
            pick_lbl = QLabel("Hızlı Satır Seç (tıkla, karta ekle):")
            pick_lbl.setObjectName("Muted")
            left.addWidget(pick_lbl)
            self.lines_list = QListWidget()
            self.lines_list.setMaximumHeight(160)
            for ln in initial_lines:
                clean = ln.strip()
                if clean:
                    self.lines_list.addItem(QListWidgetItem(clean))
            self.lines_list.itemClicked.connect(self._append_clicked_line)
            left.addWidget(self.lines_list)

        edit_lbl = QLabel("Kartta Görünecek Sözler (2–6 satır önerilir):")
        edit_lbl.setObjectName("Muted")
        left.addWidget(edit_lbl)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Favori şarkı sözü satırlarını buraya yaz veya yukarıdan seç…")
        if initial_lines:
            sample = [ln.strip() for ln in initial_lines if ln.strip()][:4]
            self.text_edit.setPlainText("\n".join(sample))
        self.text_edit.textChanged.connect(self._render_preview)
        left.addWidget(self.text_edit, stretch=1)

        # Tema seçici
        theme_lbl = QLabel("Kart Teması:")
        theme_lbl.setObjectName("Muted")
        left.addWidget(theme_lbl)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(6)
        self._theme_btns: dict[str, QPushButton] = {}
        for key, (label, _, _) in CARD_THEMES.items():
            btn = QPushButton(label)
            btn.setObjectName("Chip")
            btn.setCheckable(True)
            btn.setChecked(key == self._theme_key)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self._select_theme(k))
            theme_row.addWidget(btn)
            self._theme_btns[key] = btn
        left.addLayout(theme_row)

        # Alt butonlar
        act_row = QHBoxLayout()
        act_row.setSpacing(8)
        self.copy_btn = QPushButton("📋 Panoya Kopyala (PNG)")
        self.copy_btn.setObjectName("Primary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        act_row.addWidget(self.copy_btn, stretch=1)

        self.save_btn = QPushButton("💾 PNG Kaydet…")
        self.save_btn.setObjectName("Secondary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._save_png)
        act_row.addWidget(self.save_btn)
        left.addLayout(act_row)

        left_host = QWidget()
        left_host.setLayout(left)
        root.addWidget(left_host, stretch=1)

        # SAĞ: Canlı Kart Önizlemesi
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignCenter)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(360, 450)
        self.preview_label.setStyleSheet(
            "background: rgba(255,255,255,0.04); border-radius: 18px;"
        )
        right.addWidget(self.preview_label)
        root.addLayout(right)

        self._render_preview()

    def _append_clicked_line(self, item: QListWidgetItem):
        cur = self.text_edit.toPlainText().strip()
        line = item.text().strip()
        if not line:
            return
        self.text_edit.setPlainText(f"{cur}\n{line}" if cur else line)

    def _select_theme(self, key: str):
        self._theme_key = key
        for k, btn in self._theme_btns.items():
            btn.blockSignals(True)
            btn.setChecked(k == key)
            btn.blockSignals(False)
        self._render_preview()

    def _render_preview(self):
        pm = render_lyric_card(
            self._title,
            self._artist,
            self.text_edit.toPlainText(),
            cover_pixmap=self._cover_pm,
            theme_key=self._theme_key,
        )
        self._current_pixmap = pm
        scaled = pm.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def _copy_to_clipboard(self):
        if self._current_pixmap is not None:
            QApplication.clipboard().setPixmap(self._current_pixmap)
            self.copy_btn.setText("✓ Panoya Kopyalandı!")

    def _save_png(self):
        if self._current_pixmap is None:
            return
        safe_name = "".join(c for c in self._title if c.isalnum() or c in " -_").strip() or "audifly_kart"
        path, _ = QFileDialog.getSaveFileName(
            self, "Şarkı Sözü Kartını Kaydet", f"{safe_name}.png", "PNG Görseli (*.png)"
        )
        if path:
            self._current_pixmap.save(path, "PNG")
            self.save_btn.setText("✓ Kaydedildi")

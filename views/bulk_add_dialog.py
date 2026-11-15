"""
Toplu Şarkı Ekle diyaloğu — satır satır girilen şarkı adlarını YouTube'da
otomatik arayıp aktif listeye ekler.

Orijinal open_bulk_add_dialog'ın Qt portudur; ağır iş BulkSearchWorker'dadır.
"""
from __future__ import annotations

import threading

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout,
)

from mustiefly_qt.services.bulk_search import BulkSearchWorker
from mustiefly_qt.services.playlist_store import PlaylistStore


class BulkAddDialog(QDialog):
    def __init__(self, store: PlaylistStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Toplu Şarkı Ekle")
        self.resize(580, 560)
        self._worker: BulkSearchWorker | None = None
        self._running = False

        root = QVBoxLayout(self)
        title = QLabel("Toplu Şarkı Ekle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        info = QLabel(
            f"Her satıra bir şarkı adı yaz (\"Sanatçı - Şarkı Adı\" önerilir).\n"
            f"Her satır için YouTube'daki en iyi eşleşme otomatik olarak\n"
            f"\"{store.active_playlist}\" listesine eklenecek.")
        info.setObjectName("Muted")
        root.addWidget(info)

        self.text_box = QTextEdit()
        self.text_box.setPlaceholderText(
            "Sezen Aksu - Kaçın Kurası\nMFÖ - Ele Güne Karşı\nBarış Manço - Dönence")
        root.addWidget(self.text_box, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Muted")
        self.progress_label.setWordWrap(True)
        root.addWidget(self.progress_label)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Aramaya Başla")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Vazgeç")
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

    # --- Akış ---
    def _start(self):
        if self._running:
            return
        raw = self.text_box.toPlainText()
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            self.progress_label.setText("Lütfen en az bir şarkı adı gir.")
            return

        target_playlist = self.store.active_playlist
        existing_urls = {s.get('webpage_url') for s in self.store.playlists.get(target_playlist, [])}

        self._running = True
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Ekleniyor…")
        self.cancel_btn.setText("Durdur")

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(lines))
        self.progress_bar.setValue(0)

        self._worker = BulkSearchWorker(lines, existing_urls)
        self._worker.progress.connect(self._on_progress)
        self._worker.itemFound.connect(lambda item: self._append_item(target_playlist, item))
        self._worker.finished.connect(lambda added, failed, cancelled:
                                      self._on_finished(target_playlist, added, failed, cancelled))

        threading.Thread(target=self._worker.run, daemon=True).start()

    def _on_progress(self, done: int, total: int, query: str):
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"🔍 ({done}/{total}) aranıyor: {query[:50]}")

    def _append_item(self, playlist_name: str, item: dict):
        """GUI thread'inde listeye ekler (thread güvenliği)."""
        self.store.playlists.setdefault(playlist_name, []).append(item)

    def _on_finished(self, target_playlist: str, added: int, failed: list, cancelled: bool):
        self._running = False
        self.store.save()
        self.store.playlistsChanged.emit()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Aramaya Başla")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Kapat")

        total = self.progress_bar.maximum()
        if cancelled:
            msg = f"⏹ Durduruldu. {added}/{total} şarkı eklendi."
        elif failed:
            msg = f"✅ {added}/{total} şarkı eklendi. {len(failed)} tanesi bulunamadı."
        else:
            msg = f"✅ {added}/{total} şarkının tamamı eklendi!"

        if failed:
            shown = failed[:8]
            extra = f"\n… ve {len(failed) - 8} tane daha" if len(failed) > 8 else ""
            msg += "\n\nBulunamayanlar:\n• " + "\n• ".join(shown) + extra

        self.progress_label.setText(msg)
        self.store.statusMessage.emit(
            f"Toplu ekleme tamamlandı: {added}/{total} şarkı eklendi.", "success")

    def _cancel_or_close(self):
        if self._running:
            if self._worker is not None:
                self._worker.cancel()
            self.cancel_btn.setText("Durduruluyor…")
            self.cancel_btn.setEnabled(False)
        else:
            self.accept()

    def reject(self):
        self._cancel_or_close()

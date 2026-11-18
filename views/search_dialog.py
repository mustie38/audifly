from __future__ import annotations

from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import SEARCH_RESULT_THUMB_SIZE, cover_color_for, format_time
from mustiefly_qt.helpers.win_theme import apply_dark_titlebar
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService


class _ResultRow(QWidget):
    def __init__(self, result: dict, on_add, thumbnails: ThumbnailService | None = None):
        super().__init__()
        self.result = result
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Yuvarlak kapak (ThumbnailService hazır değilse renkli placeholder)
        self.thumb_label = None
        if thumbnails is not None:
            self.thumb_label = QLabel("🎵")
            self.thumb_label.setFixedSize(SEARCH_RESULT_THUMB_SIZE, SEARCH_RESULT_THUMB_SIZE)
            self.thumb_label.setAlignment(Qt.AlignCenter)
            self.thumb_label.setStyleSheet(
                f"background: {cover_color_for(result.get('title', '?'))};"
                f"border-radius: 5px; font-size: 14px;")
            layout.addWidget(self.thumb_label)
            self._apply_thumb(thumbnails)

        title = escape(str(result.get("title") or "?"))
        uploader = escape(str(result.get("uploader") or ""))
        info = QLabel(f"<b>{title[:60]}</b><br><span style='color:#9a92b0;'>"
                      f"{uploader} • {format_time((result.get('duration') or 0) * 1000)}</span>")
        layout.addWidget(info, stretch=1)

        add_btn = QPushButton("Ekle")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(lambda: on_add(result))
        layout.addWidget(add_btn)

    def _apply_thumb(self, thumbnails: ThumbnailService):
        pm = thumbnails.pixmap_for(self.result, SEARCH_RESULT_THUMB_SIZE)
        if pm is not None and not pm.isNull():
            self.thumb_label.setPixmap(pm)
            self.thumb_label.setText("")


class SearchDialog(QDialog):
    def __init__(self, store: PlaylistStore, playback: PlaybackEngine, parent=None,
                 initial_query: str = "", thumbnails: ThumbnailService | None = None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails
        self.setWindowTitle("YouTube'da Ara")
        apply_dark_titlebar(self)
        self.resize(560, 460)

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Şarkı adı ya da YouTube linki…")
        self.query_edit.returnPressed.connect(self._start_search)
        search_row.addWidget(self.query_edit, stretch=1)
        self.search_btn = QPushButton("🔍 Ara")
        self.search_btn.setObjectName("Primary")
        self.search_btn.clicked.connect(self._start_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        layout.addWidget(self.results_list, stretch=1)

        self.playback.searchResults.connect(self._on_results)
        self.playback.searchFailed.connect(self._on_failed)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

        if initial_query:
            self.query_edit.setText(initial_query)
            self._start_search()

    def done(self, result: int):
        for sig, slot in ((self.playback.searchResults, self._on_results),
                          (self.playback.searchFailed, self._on_failed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        if self.thumbnails is not None:
            try:
                self.thumbnails.thumbnailReady.disconnect(self._on_thumbnail_ready)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    def _start_search(self):
        query = self.query_edit.text().strip()
        if not query:
            return
        self.search_btn.setEnabled(False)
        self.status_label.setText(f"🔍 '{query}' aranıyor…")
        self.results_list.clear()
        self.playback.search(query)

    def _on_results(self, results: list):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"{len(results)} sonuç bulundu.")
        self.results_list.clear()
        for result in results:
            item = QListWidgetItem()
            row = _ResultRow(result, self._add_result, self.thumbnails)
            item.setSizeHint(row.sizeHint())
            self.results_list.addItem(item)
            self.results_list.setItemWidget(item, row)

    def _on_thumbnail_ready(self, key: str):
        """Bir kapak indikçe yalnızca eşleşen sonuç satırları güncellenir."""
        if not self.results_list.count():
            return
        for i in range(self.results_list.count()):
            row = self.results_list.itemWidget(self.results_list.item(i))
            if isinstance(row, _ResultRow) and row.result.get("webpage_url") == key:
                row._apply_thumb(self.thumbnails)

    def _on_failed(self, message: str):
        self.search_btn.setEnabled(True)
        self.status_label.setText(f"❌ Arama başarısız: {message}")

    def _add_result(self, result: dict):
        target = self.store.active_playlist
        if self.store.add_song(target, result):
            self.store.statusMessage.emit(
                f"✅ '{result.get('title', '?')}' → '{target}' listesine eklendi.", "success")
        else:
            self.store.statusMessage.emit("Bu şarkı zaten listede var.", "warning")

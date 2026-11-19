"""
Genel kütüphane arama: TÜM playlistlerde başlık/sanatçı araması.

Satıra çift tık / ▶ → şarkı çalar; 📂 butonu → şarkının listesini açar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import format_time
from mustiefly_qt.helpers.win_theme import apply_dark_titlebar
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService

DEBOUNCE_MS = 250


class LibrarySearchDialog(QDialog):
    openPlaylistRequested = Signal(str, int)  # playlist_adı, şarkı_index

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails
        self.setWindowTitle("🔎 Kütüphanede Ara")
        apply_dark_titlebar(self)
        self.resize(620, 520)

        layout = QVBoxLayout(self)

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Tüm listelerde şarkı/sanatçı ara…")
        self.query_edit.textChanged.connect(self._schedule_search)
        layout.addWidget(self.query_edit)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(
            lambda item: self._open_song(item))
        layout.addWidget(self.results_list, stretch=1)

        hint = QLabel("Çift tık: çal  •  📂: şarkının listesini göster")
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._run_search)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

        self.query_edit.setFocus()

    def done(self, result: int):
        if self.thumbnails is not None:
            try:
                self.thumbnails.thumbnailReady.disconnect(self._on_thumbnail_ready)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    # --- Arama ---
    def _schedule_search(self):
        self._debounce.start()

    def _run_search(self):
        query = self.query_edit.text().strip().lower()
        self.results_list.clear()
        if not query:
            self.status_label.setText("Yazmaya başla — tüm listelerde aranır.")
            return
        matches: list[tuple[str, int, dict]] = []
        for pl_name, songs in self.store.playlists.items():
            for idx, s in enumerate(songs):
                if (query in s.get("title", "").lower()
                        or query in s.get("uploader", "").lower()):
                    matches.append((pl_name, idx, s))
        matches.sort(key=lambda t: t[2].get("title", "").lower())

        max_rows = 120
        shown = matches[:max_rows]
        if len(matches) > max_rows:
            self.status_label.setText(f"{len(matches)} sonuç bulundu (ilk {max_rows} gösteriliyor).")
        else:
            self.status_label.setText(f"{len(matches)} sonuç bulundu.")
        self._thumb_rows: dict[str, list[_SearchRow]] = {}
        for pl_name, idx, song in shown:
            item = QListWidgetItem()
            row = _SearchRow(self.store, self.playback, self.thumbnails,
                             pl_name, idx, song)
            row.playRequested.connect(
                lambda i=idx, pl=pl_name: self.playback.play_song_at_index(pl, i))
            row.openListRequested.connect(
                lambda pl=pl_name, i=idx: (self.openPlaylistRequested.emit(pl, i), self.accept()))
            item.setSizeHint(row.sizeHint())
            self.results_list.addItem(item)
            self.results_list.setItemWidget(item, row)
            key = song.get("webpage_url")
            if key:
                self._thumb_rows.setdefault(key, []).append(row)
            self._request_thumbnail(row, song)

    def _on_thumbnail_ready(self, key: str):
        rows = getattr(self, "_thumb_rows", {}).get(key)
        if not rows:
            return
        for row in rows:
            try:
                self._request_thumbnail(row, row.song)
            except RuntimeError:
                pass

    def _request_thumbnail(self, row, song):
        if self.thumbnails is None:
            return
        pm = self.thumbnails.pixmap_for(song, 36)
        if pm is not None:
            row.set_thumbnail(pm)

    def _open_song(self, item: QListWidgetItem):
        row = self.results_list.itemWidget(item)
        if row is not None:
            row.playRequested.emit(row.index)


class _SearchRow(QWidget):
    """Arama sonucu satırı: SongRow + playlist etiketi + 'listede göster' butonu."""
    playRequested = Signal(int)
    openListRequested = Signal()

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None,
                 playlist_name: str, index: int, song: dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.playlist_name = playlist_name
        self.song = song
        self.setObjectName("SongRow")
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        from mustiefly_qt.helpers.constants import cover_color_for
        self.thumb_label = QLabel("🎵")
        self.thumb_label.setFixedSize(36, 36)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background: {cover_color_for(song.get('title', '?'))};"
            "border-radius: 5px; font-size: 15px;")
        layout.addWidget(self.thumb_label)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        title = song.get("title", "?")
        title_label = QLabel(title[:55] + ("…" if len(title) > 55 else ""))
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        text_layout.addWidget(title_label)
        sub_label = QLabel(f"{song.get('uploader', '')} • {playlist_name} • "
                           f"{format_time((song.get('duration') or 0) * 1000)}")
        sub_label.setObjectName("Muted")
        text_layout.addWidget(sub_label)
        layout.addWidget(text_box, stretch=1)

        like_btn = QPushButton("♥" if song.get("liked") else "♡")
        like_btn.setFixedWidth(28)
        like_btn.setStyleSheet(
            f"color: {'#FF7A3D' if song.get('liked') else 'palette(midlight)'};")
        like_btn.clicked.connect(
            lambda: self._toggle_like(store, like_btn))
        layout.addWidget(like_btn)

        open_btn = QPushButton("📂")
        open_btn.setFixedWidth(28)
        open_btn.setToolTip("Şarkının listesini göster")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(self.openListRequested.emit)
        layout.addWidget(open_btn)

    def set_thumbnail(self, pm):
        if pm is not None and not pm.isNull():
            self.thumb_label.setPixmap(pm)
            self.thumb_label.setText("")

    def _toggle_like(self, store: PlaylistStore, btn: QPushButton):
        songs = store.playlists.get(self.playlist_name, [])
        if 0 <= self.index < len(songs):
            store.toggle_like(self.playlist_name, self.index)
            btn.setText("♥" if songs[self.index].get("liked") else "♡")

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.playRequested.emit(self.index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

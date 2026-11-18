"""
İstatistikler sayfası: toplam şarkı/çalma/dinleme süresi/beğeni kartları,
en çok dinlenenler Top 10 ve liste dağılımı.

Veriler gerçek kütüphaneden (play_count / last_played / duration) hesaplanır.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidgetItem, QScrollArea, QVBoxLayout, QWidget,
)

from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.views.home_view import QListWidgetHost, StatCard
from mustiefly_qt.widgets.song_row import SongRow


PERIODS = (("Tüm zamanlar", None), ("Son 7 gün", 7), ("Son 30 gün", 30), ("Son 365 gün", 365))


def format_listen_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600} sa {seconds % 3600 // 60} dk"
    return f"{seconds // 60} dk"


class StatsView(QWidget):
    startRadioRequested = Signal(dict)
    artistRequested = Signal(str)

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 10)

        title = QLabel("📊 İstatistikler")
        title_font = QFont()
        title_font.setPixelSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)
        self.period_combo = QComboBox()
        for label, days in PERIODS:
            self.period_combo.addItem(label, days)
        root.addWidget(self.period_combo, alignment=Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("HomeContent")
        # Düz QWidget QSS arkaplanını ancak WA_StyledBackground ile boyar
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 12, 0)
        self.content_layout.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll)

        # --- Kartlar ---
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.card_songs = StatCard("🎵", "0", "Toplam Şarkı")
        self.card_plays = StatCard("▶", "0", "Toplam Çalma")
        self.card_time = StatCard("⏱", "0 sa", "Toplam Dinleme")
        self.card_liked = StatCard("❤️", "0", "Beğenilenler")
        for card in (self.card_songs, self.card_plays, self.card_time, self.card_liked):
            cards_row.addWidget(card)
        cards_row.addStretch(1)
        self.content_layout.addLayout(cards_row)

        # --- Geçmişe dayalı (seçili döneme göre) ---
        self.artists_header = QLabel("🎤 En Çok Dinlenen Sanatçılar")
        self.recent_header = QLabel("🕘 Son Dinlenenler")
        for h in (self.artists_header, self.recent_header):
            hf = QFont()
            hf.setPixelSize(16)
            hf.setBold(True)
            h.setFont(hf)
        self.artists_box = QVBoxLayout()
        self.artists_box.setSpacing(4)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(4)
        self.content_layout.addWidget(self.artists_header)
        self.content_layout.addLayout(self.artists_box)
        self.content_layout.addWidget(self.recent_header)
        self.content_layout.addLayout(self.recent_box)

        # --- En çok dinlenenler ---
        top_header = QLabel("🔥 En Çok Dinlenenler (Top 10)")
        header_font = QFont()
        header_font.setPixelSize(16)
        header_font.setBold(True)
        top_header.setFont(header_font)
        self.content_layout.addWidget(top_header)

        self.top_list = QListWidgetHost()
        self.content_layout.addWidget(self.top_list, stretch=1)

        # --- Liste dağılımı ---
        dist_header = QLabel("📀 Liste Dağılımı")
        dist_header.setFont(header_font)
        self.content_layout.addWidget(dist_header)
        self.dist_box = QVBoxLayout()
        self.dist_box.setSpacing(4)
        self.content_layout.addLayout(self.dist_box)
        self.content_layout.addStretch(1)

        self.store.playlistsChanged.connect(self._on_store_changed)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)
        self.refresh()
        self.period_combo.currentIndexChanged.connect(self.refresh)

    def _on_thumbnail_ready(self, key: str):
        if self.thumbnails is None:
            return
        for i in range(self.top_list.count()):
            row = self.top_list.itemWidget(self.top_list.item(i))
            if isinstance(row, SongRow) and row.song.get("webpage_url") == key:
                pm = self.thumbnails.pixmap_for(row.song, 36)
                if pm is not None:
                    row.set_thumbnail(pm)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self.refresh()

    def _on_store_changed(self):
        # Görünür değilken (ör. indirme/ekleme sırasında) satır widget'larını
        # baştan kurmak boşa takılma yaratıyordu; gösterilince yenilenir.
        if self.isVisible():
            self.refresh()
        else:
            self._dirty = True

    def refresh(self):
        self._dirty = False
        all_refs: list[tuple[str, int, dict]] = []
        for name, songs in self.store.playlists.items():
            for idx, s in enumerate(songs):
                all_refs.append((name, idx, s))

        total_songs = len(all_refs)
        total_plays = sum((s.get("play_count") or 0) for _, _, s in all_refs)
        history = getattr(self.playback, "history", None)
        days = self.period_combo.currentData()
        if history is not None and history.events():
            period_events = history.since(days)
            total_seconds = sum(e["listened"] for e in period_events)   # gerçek dinleme
            total_plays = len(period_events)
        else:   # geçmiş henüz yok: eski tahmin (süre × çalma sayısı)
            total_seconds = sum((s.get("duration") or 0) * (s.get("play_count") or 0)
                                for _, _, s in all_refs)
        self._fill_history_sections(history, days)
        total_liked = sum(1 for _, _, s in all_refs if s.get("liked"))

        self.card_songs.set_data(str(total_songs))
        self.card_plays.set_data(str(total_plays))
        self.card_time.set_data(format_listen_time(total_seconds))
        self.card_liked.set_data(str(total_liked))

        # En çok dinlenenler (çalınmış olanlar, azalan)
        played = [t for t in all_refs if (t[2].get("play_count") or 0) > 0]
        played.sort(key=lambda t: (t[2].get("play_count") or 0), reverse=True)

        self._fill_distribution()   # erken return'den ÖNCE (eskiden hiç çalınmamışsa boş kalıyordu)

        self.top_list.clear()
        if not played:
            empty = QLabel("Henüz hiç şarkı çalmadın. Çaldıkça istatistikler burada birikir.")
            empty.setObjectName("Muted")
            self._add_row(empty)
            return

        for pl_name, idx, song in played[:10]:
            row = SongRow(idx, song, row_number=None, show_uploader=False)
            count_tag = QLabel(f"{song.get('play_count', 0)}×")
            count_tag.setObjectName("Accent")
            count_tag.setFixedWidth(40)
            count_tag.setAlignment(Qt.AlignCenter)
            row.layout().addWidget(count_tag)
            row.playRequested.connect(
                lambda i, pl=pl_name: self.playback.play_song_at_index(pl, i))
            row.likeToggled.connect(lambda i, pl=pl_name: self.store.toggle_like(pl, i))
            row.addToQueueRequested.connect(
                lambda i, pl=pl_name, s=song: self.store.add_to_queue(pl, i, s))
            row.playNextRequested.connect(
                lambda i, pl=pl_name, s=song: self.store.add_to_queue_next(pl, i, s))
            row.startRadioRequested.connect(self.startRadioRequested.emit)
            row.artistRequested.connect(self.artistRequested.emit)
            # ⋮ menüsündeki sil/indir/taşı öğeleri de çalışsın
            row.removeRequested.connect(
                lambda i, pl=pl_name: self.store.remove_song(pl, i))
            row.downloadRequested.connect(
                lambda i, pl=pl_name: self.playback.download_song_for_offline(pl, i))
            row.moveRequested.connect(
                lambda i, pl=pl_name: self._move_song_dialog(pl, i))
            self._add_row(row)
            if self.thumbnails is not None:
                pm = self.thumbnails.pixmap_for(song, 36)
                if pm is not None:
                    row.set_thumbnail(pm)

    def _fill_distribution(self):
        self._clear_box(self.dist_box)
        for name, songs in self.store.playlists.items():
            lbl = QLabel(f"• {name} — {len(songs)} şarkı")
            lbl.setObjectName("Muted")
            self.dist_box.addWidget(lbl)

    def _clear_box(self, box: QVBoxLayout):
        while box.count():
            w = box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    def _fill_history_sections(self, history, days):
        from datetime import datetime
        for box in (self.artists_box, self.recent_box):
            self._clear_box(box)
        artists = history.top_artists(8, days) if history is not None else []
        recent = history.recent(15) if history is not None else []
        if not artists:
            note = QLabel("Henüz dinleme geçmişi yok. 30 saniyeden uzun dinlediğin şarkılar burada görünür.")
            note.setObjectName("Muted")
            self.artists_box.addWidget(note)
        for row in artists:
            art_name = row.get("artist", "")
            lbl = QLabel(f"• {art_name} — {row['plays']} dinleme, "
                         f"{format_listen_time(row['seconds'])}")
            if art_name and art_name not in ("Bilinmeyen Sanatçı", "?"):
                lbl.setCursor(Qt.PointingHandCursor)
                lbl.setToolTip(f"👤 {art_name} profiline git")
                lbl.mousePressEvent = lambda e, a=art_name: (
                    self.artistRequested.emit(a) if e.button() == Qt.LeftButton else None
                )
            self.artists_box.addWidget(lbl)
        for e in recent:
            try:
                when = datetime.fromisoformat(e["ts"]).strftime("%d.%m %H:%M")
            except (KeyError, TypeError, ValueError):
                continue
            lbl = QLabel(f"{when}  ·  {e.get('title', '?')} — {e.get('artist', '')}  "
                         f"({format_listen_time(e['listened'])})")
            lbl.setObjectName("Muted")
            self.recent_box.addWidget(lbl)

    def _add_row(self, widget: QWidget):
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.top_list.addItem(item)
        self.top_list.setItemWidget(item, widget)

    def _move_song_dialog(self, playlist_name: str, index: int):
        """Kütüphane görünümündekiyle aynı taşıma akışı (İstatistik satırları için)."""
        from PySide6.QtWidgets import QInputDialog
        targets = [n for n in self.store.playlists if n != playlist_name]
        if not targets:
            self.store.statusMessage.emit(
                "Taşınacak başka bir liste yok. Önce yeni bir liste oluştur.", "warning")
            return
        target, ok = QInputDialog.getItem(
            self, "Başka Listeye Taşı", "Hedef liste seç:", targets, 0, False)
        if not ok:
            return
        success, err = self.store.move_song_to_playlist(playlist_name, index, target)
        if success:
            self.store.statusMessage.emit(
                f"📂 Şarkı '{target}' listesine taşındı.", "success")
        else:
            self.store.statusMessage.emit(f"⚠️ Şarkı taşınmadı: {err}", "warning")

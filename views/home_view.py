"""
Ana Sayfa panosu: hoş geldin başlığı + Karışık Çal, istatistik kartları,
Hızlı Erişim playlist grid'i ve Son Çalınanlar listesi.

Orijinal _render_home_view / _render_stats_view'in Qt portudur — tüm veriler
gerçek kütüphane verisinden (play_count/last_played) hesaplanır.
"""
from __future__ import annotations

from datetime import datetime
from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.thumbnails import crop_to_square, pil_to_qimage
from mustiefly_qt.widgets.player_icons import icon as vicon, icon_pixmap
from mustiefly_qt.widgets.song_row import SongRow
from mustiefly_qt.helpers.logging_setup import get_logger



log = get_logger(__name__)
class StatCard(QFrame):
    def __init__(self, icon_kind: str, value: str, label: str, accent: str = "#a980f9", parent=None):
        super().__init__(parent)
        self.setObjectName("HomeStatCard")
        self.setMinimumWidth(140)
        self.setFixedHeight(96)
        self.setStyleSheet(f"""
            #HomeStatCard {{
                background: rgba(255, 255, 255, 0.032);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-left: 3px solid {accent};
                border-radius: 14px;
            }}
            #HomeStatCard:hover {{
                background: rgba(255, 255, 255, 0.055);
                border-color: rgba(255, 255, 255, 0.14);
                border-left: 3px solid {accent};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 14, 12)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        icon_label = QLabel()
        icon_label.setFixedSize(20, 20)
        pm = icon_pixmap(icon_kind, 16, accent)
        if pm is not None and not pm.isNull():
            icon_label.setPixmap(pm)
        else:
            icon_label.setText(icon_kind)
        top_row.addWidget(icon_label)

        text_label = QLabel(label)
        text_label.setObjectName("Muted")
        text_label.setStyleSheet("font-size: 11px; font-weight: 600;")
        top_row.addWidget(text_label, stretch=1)
        layout.addLayout(top_row)

        self.value_label = QLabel(value)
        value_font = QFont()
        value_font.setPixelSize(22)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(self.value_label)

    def set_data(self, value: str):
        self.value_label.setText(value)


class QuickAccessCard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, emoji: str = "🎵",
                 accent_bg: str | None = None, pixmap=None, parent=None):
        super().__init__(parent)
        self.setObjectName("QuickAccessCard")
        self.setFixedWidth(166)
        self.setStyleSheet("""
            #QuickAccessCard {
                background: rgba(255, 255, 255, 0.032);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 16px;
            }
            #QuickAccessCard:hover {
                background: rgba(255, 255, 255, 0.065);
                border: 1px solid rgba(169, 128, 249, 0.42);
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(6)

        cover = QLabel()
        cover.setFixedSize(150, 146)
        cover.setAlignment(Qt.AlignCenter)
        cover_font = QFont()
        cover_font.setPixelSize(46)
        cover.setFont(cover_font)
        if pixmap is not None and not pixmap.isNull():
            cover.setPixmap(pixmap)
            cover.setScaledContents(True)
            cover.setStyleSheet("border-radius: 12px;")
        else:
            bg = accent_bg or cover_color_for(title)
            cover.setText(emoji)
            cover.setStyleSheet(f"background: {bg}; border-radius: 12px; color: white;")
        cover.setCursor(Qt.PointingHandCursor)
        cover.mousePressEvent = lambda event: self.clicked.emit()

        self._hover_play = QPushButton(cover)
        self._hover_play.setFixedSize(38, 38)
        self._hover_play.move(150 - 46, 146 - 46)
        self._hover_play.setIcon(vicon("play", 16, "#ffffff"))
        self._hover_play.setIconSize(QSize(16, 16))
        self._hover_play.setCursor(Qt.PointingHandCursor)
        self._hover_play.setStyleSheet(
            "QPushButton { background: #a980f9; border: none; border-radius: 19px; }"
            "QPushButton:hover { background: #b995ff; }"
        )
        sh = QGraphicsDropShadowEffect(self._hover_play)
        sh.setBlurRadius(14)
        sh.setOffset(0, 3)
        sh.setColor(QColor(0, 0, 0, 150))
        self._hover_play.setGraphicsEffect(sh)
        self._hover_play.clicked.connect(self.clicked.emit)
        self._hover_play.hide()

        layout.addWidget(cover)

        title_label = QLabel(title[:20] + ("…" if len(title) > 20 else ""))
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #FFFFFF; font-size: 13px;")
        title_label.setFixedWidth(150)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        sub_label = QLabel(subtitle)
        sub_label.setObjectName("Muted")
        sub_label.setStyleSheet("font-size: 11px; color: #8F9CAE;")
        sub_label.setFixedWidth(150)
        layout.addWidget(sub_label)

    def enterEvent(self, event):  # noqa: N802
        self._hover_play.show()
        self._hover_play.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover_play.hide()
        super().leaveEvent(event)


class _HorizontalScrollArea(QScrollArea):
    """Fare tekerleğini yatay kaydırmaya çeviren alan — Hızlı Erişim kartları
    ekrana sığmadığında sağa sola kaydırılabilir."""

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)


class HomeView(QWidget):
    openPlaylistRequested = Signal(str)
    openLikedRequested = Signal()
    playShuffledRequested = Signal()
    startRadioRequested = Signal(dict)
    artistRequested = Signal(str)

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails=None, username: str = "", parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails
        self.username = username or "kullanıcı"

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("HomeContent")
        # Düz QWidget QSS arkaplanını ancak WA_StyledBackground ile boyar;
        # aksi halde viewport varsayılan (açık) palet rengiyle görünür.
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 12, 0)
        self.content_layout.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll)

        # --- Karşılama Hero Banner ---
        hero_card = QFrame()
        hero_card.setObjectName("HomeHeroCard")
        hero_card.setStyleSheet("""
            #HomeHeroCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(169, 128, 249, 0.18),
                    stop:0.5 rgba(20, 24, 38, 0.94),
                    stop:1 rgba(13, 16, 26, 0.98));
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
        """)
        header_row = QHBoxLayout(hero_card)
        header_row.setContentsMargins(22, 18, 22, 18)
        header_row.setSpacing(16)

        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        hour = datetime.now().hour
        if 5 <= hour < 12:
            greet = "Günaydın"
        elif 12 <= hour < 18:
            greet = "İyi günler"
        elif 18 <= hour < 23:
            greet = "İyi akşamlar"
        else:
            greet = "Gece modu"
        welcome = QLabel(f"{greet}, {self.username}")
        welcome_font = QFont()
        welcome_font.setPixelSize(23)
        welcome_font.setBold(True)
        welcome.setFont(welcome_font)
        welcome.setStyleSheet("color: #FFFFFF;")
        title_box.addWidget(welcome)
        subtitle = QLabel("Müziğin ritmiyle günü güzelleştir — kaldığın yerden devam et.")
        subtitle.setObjectName("Muted")
        subtitle.setStyleSheet("font-size: 12px; color: #8F9CAE;")
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box, stretch=1)

        liked_btn = QPushButton(" Favoriler")
        liked_btn.setObjectName("Chip")
        liked_btn.setIcon(vicon("heart_filled", 14, "#FF6B8A"))
        liked_btn.setIconSize(QSize(14, 14))
        liked_btn.setFixedHeight(36)
        liked_btn.setCursor(Qt.PointingHandCursor)
        liked_btn.clicked.connect(self.openLikedRequested.emit)
        header_row.addWidget(liked_btn, alignment=Qt.AlignVCenter)

        shuffle_btn = QPushButton(" Karışık Çal")
        shuffle_btn.setObjectName("Primary")
        shuffle_btn.setIcon(vicon("shuffle", 14, "#ffffff"))
        shuffle_btn.setIconSize(QSize(14, 14))
        shuffle_btn.setFixedHeight(36)
        shuffle_btn.setCursor(Qt.PointingHandCursor)
        shuffle_btn.clicked.connect(self.playShuffledRequested.emit)
        header_row.addWidget(shuffle_btn, alignment=Qt.AlignVCenter)
        self.content_layout.addWidget(hero_card)

        # --- İstatistik kartları (tam genişliğe dengeli dağılır) ---
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.card_songs = StatCard("disc", "0", "Toplam Şarkı", "#00D2FF")
        self.card_playlists = StatCard("folder", "0", "Çalma Listesi", "#a980f9")
        self.card_time = StatCard("clock", "0 sa", "Dinleme Süresi", "#FBBF24")
        self.card_liked = StatCard("heart_filled", "0", "Favori Şarkılar", "#FF6B8A")
        for card in (self.card_songs, self.card_playlists, self.card_time, self.card_liked):
            cards_row.addWidget(card, stretch=1)
        self.content_layout.addLayout(cards_row)

        # --- Hızlı Erişim ---
        quick_header = QLabel("Hızlı Erişim")
        header_font = QFont()
        header_font.setPixelSize(16)
        header_font.setBold(True)
        quick_header.setFont(header_font)
        self.content_layout.addWidget(quick_header)

        self.quick_grid_host = QWidget()
        self.quick_grid_host.setAutoFillBackground(False)
        # QScrollArea.setWidget() içeriye konan widget'a da varsayılan (beyaz)
        # bir arkaplan/palet rolü verebiliyor; sadece viewport'u şeffaf yapmak
        # yetmiyor, asıl içerik widget'ını da açıkça şeffaf yapmamız gerekiyor.
        self.quick_grid_host.setStyleSheet("background: transparent;")
        self.quick_grid = QHBoxLayout(self.quick_grid_host)
        self.quick_grid.setContentsMargins(0, 0, 0, 0)
        self.quick_grid.setSpacing(12)
        # Yatay kaydırılabilir alan: 4'ten fazla kart sıkışmadan yan yana durur
        self.quick_scroll = _HorizontalScrollArea()
        self.quick_scroll.setWidgetResizable(True)
        self.quick_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.quick_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.quick_scroll.setFixedHeight(236)
        self.quick_scroll.setFrameShape(QScrollArea.NoFrame)
        # Yukarıdaki ana scroll area'da olduğu gibi: bu ayar yapılmazsa
        # viewport, kart kapaklarının altındaki başlık/alt yazı şeridinde
        # varsayılan (açık/beyaz) palet rengiyle görünür.
        self.quick_scroll.viewport().setAutoFillBackground(False)
        self.quick_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.quick_scroll.setWidget(self.quick_grid_host)
        self.content_layout.addWidget(self.quick_scroll)

        # --- Son Çalınanlar ---
        recent_header = QLabel("Son Çalınanlar")
        recent_header.setFont(header_font)
        self.content_layout.addWidget(recent_header)

        self.recent_list = QListWidgetHost()
        self.content_layout.addWidget(self.recent_list, stretch=1)

        self._dirty = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)
        self._refresh_timer.timeout.connect(self.refresh)
        self.store.playlistsChanged.connect(self._on_store_changed)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)
        self.refresh()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def _on_store_changed(self):
        if self.isVisible():
            self._refresh_timer.start()
        else:
            self._dirty = True

    def _on_thumbnail_ready(self, key: str):
        if self.thumbnails is None:
            return
        for i in range(self.recent_list.count()):
            row = self.recent_list.itemWidget(self.recent_list.item(i))
            if isinstance(row, SongRow) and row.song.get("webpage_url") == key:
                pm = self.thumbnails.pixmap_for(row.song, 36)
                if pm is not None:
                    row.set_thumbnail(pm)

    # --- Veri + render ---
    def refresh(self):
        self._dirty = False
        self._refresh_timer.stop()
        all_songs = [s for songs in self.store.playlists.values() for s in songs]
        total_seconds = sum((s.get('duration') or 0) for s in all_songs)
        total_liked = sum(1 for s in all_songs if s.get('liked'))
        hours = total_seconds // 3600

        self.card_songs.set_data(str(len(all_songs)))
        self.card_playlists.set_data(str(len(self.store.playlists)))
        self.card_time.set_data(f"{hours} sa")
        self.card_liked.set_data(str(total_liked))

        # Hızlı Erişim grid'ini yeniden kur
        while self.quick_grid.count():
            item = self.quick_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        liked_card = QuickAccessCard(
            "Beğenilen Şarkılar", f"{total_liked} şarkı", "🤍", "#1DB954")
        liked_card.clicked.connect(self.openLikedRequested.emit)
        self.quick_grid.addWidget(liked_card)

        from mustiefly_qt.helpers.covers import playlist_cover_pixmap
        for name in list(self.store.playlists.keys())[:4]:
            songs = self.store.playlists.get(name, [])
            pm = playlist_cover_pixmap(self.store, self.thumbnails, name, songs, size=300)
            card = QuickAccessCard(name[:18] + ("…" if len(name) > 18 else ""),
                                   f"{len(songs)} şarkı", "🎵", pixmap=pm)
            card.clicked.connect(lambda _=False, n=name: self.openPlaylistRequested.emit(n))
            self.quick_grid.addWidget(card)
        self.quick_grid.addStretch(1)

        # Son Çalınanlar (last_played'e göre en yeni 5)
        refs = []
        for pl_name, songs in self.store.playlists.items():
            for idx, song in enumerate(songs):
                if song.get('last_played'):
                    refs.append((pl_name, idx, song))
        refs.sort(key=lambda t: t[2].get('last_played') or '', reverse=True)
        refs = refs[:5]

        self.recent_list.clear()
        if not refs:
            empty = QLabel("Henüz hiç şarkı çalmadın. Bir şarkı çaldıkça burada birikmeye başlayacak.")
            empty.setObjectName("Muted")
            self.recent_list.addItemHost(empty)
            return

        for pl_name, idx, song in refs:
            row = SongRow(idx, song, show_uploader=False)
            tag = QLabel(pl_name)
            tag.setObjectName("Muted")
            tag.setFixedWidth(140)
            row.layout().addWidget(tag)
            row.playRequested.connect(
                lambda i, pl=pl_name: self.playback.play_song_at_index(pl, i))
            row.likeToggled.connect(lambda i, pl=pl_name: self.store.toggle_like(pl, i))
            row.addToQueueRequested.connect(
                lambda i, pl=pl_name, s=song: self.store.add_to_queue(pl, i, s))
            row.playNextRequested.connect(
                lambda i, pl=pl_name, s=song: self.store.add_to_queue_next(pl, i, s))
            row.startRadioRequested.connect(self.startRadioRequested.emit)
            row.artistRequested.connect(self.artistRequested.emit)
            # ⋮ menüsündeki öğeler de çalışsın (sessiz no-op olmasın):
            row.removeRequested.connect(
                lambda i, pl=pl_name: self.store.remove_song(pl, i))
            row.downloadRequested.connect(
                lambda i, pl=pl_name: self.playback.download_song_for_offline(pl, i))
            row.moveRequested.connect(
                lambda i, pl=pl_name: self._move_song_dialog(pl, i))
            self.recent_list.addItemHost(row)
            self._request_thumbnail(row, song)

    def _move_song_dialog(self, playlist_name: str, index: int):
        """Kütüphane görünümündekiyle aynı taşıma akışı (Ana Sayfa satırları için)."""
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

    def _request_thumbnail(self, row: SongRow, song: dict):
        if self.thumbnails is None:
            return
        pm = self.thumbnails.pixmap_for(song, 36)
        if pm is not None:
            row.set_thumbnail(pm)

    def _collage_pixmap(self, songs):
        """Son 4 şarkının kapağından basit bir kolaj QPixmap'i üretir.
        Thumbnail'ler henüz inmemişse None döner (renkli placeholder'a düşer)."""
        if self.thumbnails is None or not songs:
            return None
        recent = songs[-4:]
        pil_imgs = []
        for s in recent:
            img = self.thumbnails.pil_for(s)
            if img is None:
                return None  # eksik varsa kolaj önbelleklenmez/üretilmez
            pil_imgs.append(img)
        try:
            collage = Image.new('RGB', (300, 300), '#282828')
            positions = [(0, 0), (150, 0), (0, 150), (150, 150)]
            for i, img in enumerate(pil_imgs[:4]):
                resized = crop_to_square(img).resize((150, 150), Image.Resampling.LANCZOS)
                collage.paste(resized, positions[i])
            return QPixmap.fromImage(pil_to_qimage(collage))
        except Exception as e:
            log.error("%s %s", "Kolaj oluşturulamadı:", e)
            return None


class QListWidgetHost(QListWidget):
    """Ana Sayfa'daki 'Son Çalınanlar' gibi serbest satır listeleri için küçük
    bir yardımcı: widget'ları doğrudan da ekleyebilmeyi sağlar."""

    def addItemHost(self, widget: QWidget):
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, widget)

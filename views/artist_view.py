"""Sanatçı & Albüm Detay Sayfası — Artist & Album Detail View.

- Sanatçı Profili: Büyük yuvarlak avatar, doğrulanmış rozet, abone/dinleyici sayısı.
- Hızlı Eylemler: "▶ Tümünü Çal", "🔀 Karışık", "📻 Sanatçı Radyosu".
- Kütüphanemdeki Şarkıları: Kullanıcının kendi kütüphanesindeki bu sanatçıya ait parçalar.
- Popüler Şarkılar: YouTube Music'ten çekilen en popüler parçalar (doğrudan çal / kütüphaneye ekle).
- Albümler ve Tekliler: Kapaklı albüm kartları (tıklanınca albüm detay moduna geçer).
- Benzer Sanatçılar: Tıklanabilir benzer sanatçı profilleri.
- Albüm Detay Modu: Albüm kapağı, parça listesi, albümü baştan çalma ve playlist olarak ekleme.
"""
from __future__ import annotations

import threading
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for, format_time
from mustiefly_qt.helpers.logging_setup import get_logger
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.player_icons import icon as vicon

log = get_logger(__name__)


class _HorizontalScrollArea(QScrollArea):
    """Fare tekerleğini yatay kaydırmaya dönüştüren alan."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().setAutoFillBackground(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)


class ArtistDetailView(QWidget):
    """Sanatçı ve Albüm detay görünümü."""

    backRequested = Signal()
    playSongRequested = Signal(dict)
    startRadioRequested = Signal(dict)
    artistDataReady = Signal(int, str, object)
    albumDataReady = Signal(int, object, str)

    def __init__(
        self,
        store: PlaylistStore,
        playback: PlaybackEngine,
        thumbnails: ThumbnailService | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails

        self.setObjectName("ArtistDetailView")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#ArtistDetailView {
                background-color: #0c0a18;
            }
        """)
        self.setFocusPolicy(Qt.StrongFocus)
        self._current_mode = "artist"  # "artist" | "album"
        self._current_artist = ""
        self._current_browse_id = ""
        self._nav_stack: list[tuple[str, str, str]] = []  # (mode, id_or_name, extra)

        self._artist_data: dict | None = None
        self._album_data: dict | None = None
        self._artist_cache: dict[str, dict] = {}
        self._album_cache: dict[str, dict] = {}
        self._token = 0
        self._song_cover_labels: list[tuple] = []

        self.artistDataReady.connect(self._apply_artist_data)
        self.albumDataReady.connect(self._apply_album_data)

        self._build_ui()
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Ana dikey kaydırma alanı
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.16);
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.32);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("ArtistContent")
        self.content_widget.setAttribute(Qt.WA_StyledBackground, True)
        self.content_widget.setStyleSheet("""
            QWidget#ArtistContent {
                background-color: #0c0a18;
            }
        """)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(28, 20, 28, 40)
        self.content_layout.setSpacing(24)

        # 1) Üst Hero Başlık Bölümü
        self._build_hero_section()

        # 2) Dinamik İçerik Konteyneri
        self.sections_widget = QWidget()
        self.sections_layout = QVBoxLayout(self.sections_widget)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(28)
        self.content_layout.addWidget(self.sections_widget)

        self.content_layout.addStretch(1)
        self.scroll.setWidget(self.content_widget)
        root.addWidget(self.scroll)

    def _build_hero_section(self):
        hero_box = QWidget()
        hero_layout = QVBoxLayout(hero_box)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(14)

        # Geri Dön butonu
        top_bar = QHBoxLayout()
        self.back_btn = QPushButton("← Geri")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setFixedHeight(34)
        self.back_btn.setToolTip("Önceki sayfaya dön (Esc)")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 17px;
                padding: 4px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #a980f9;
                color: #ffffff;
                border-color: #a980f9;
            }
            QPushButton:pressed {
                background: #8b5cf6;
            }
        """)
        self.back_btn.clicked.connect(self._on_back_clicked)
        top_bar.addWidget(self.back_btn)
        top_bar.addStretch(1)
        hero_layout.addLayout(top_bar)

        # Hero Kartı (Kapak + Başlık + Eylemler)
        self.hero_card = QFrame()
        self.hero_card.setObjectName("ArtistHeroCard")
        self.hero_card.setStyleSheet("""
            QFrame#ArtistHeroCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(169, 128, 249, 0.22),
                    stop:0.65 rgba(22, 18, 36, 0.90),
                    stop:1 rgba(14, 12, 24, 0.98));
                border-radius: 20px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        card_layout = QVBoxLayout(self.hero_card)
        card_layout.setContentsMargins(24, 24, 24, 24)

        header_row = QHBoxLayout()
        header_row.setSpacing(24)

        # Avatar / Kapak Görseli
        self.hero_avatar = QLabel()
        self.hero_avatar.setFixedSize(130, 130)
        self.hero_avatar.setAlignment(Qt.AlignCenter)
        self.hero_avatar.setStyleSheet("border-radius: 65px; background: rgba(255, 255, 255, 0.08);")
        shadow = QGraphicsDropShadowEffect(self.hero_avatar)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.hero_avatar.setGraphicsEffect(shadow)
        header_row.addWidget(self.hero_avatar)

        # Başlık ve Bilgiler
        info_col = QVBoxLayout()
        info_col.setSpacing(8)
        info_col.addStretch(1)

        self.hero_tag = QLabel("SANATÇI")
        self.hero_tag.setStyleSheet(
            "color: #a980f9; font-size: 11px; font-weight: bold; letter-spacing: 1.5px;"
        )
        info_col.addWidget(self.hero_tag)

        self.hero_title = QLabel("Sanatçı Adı")
        self.hero_title.setStyleSheet("color: #ffffff; font-size: 34px; font-weight: 800;")
        self.hero_title.setWordWrap(True)
        info_col.addWidget(self.hero_title)

        self.hero_sub = QLabel("Doğrulanmış Sanatçı")
        self.hero_sub.setStyleSheet("color: rgba(255, 255, 255, 0.70); font-size: 13px;")
        info_col.addWidget(self.hero_sub)

        # Eylem Butonları Satırı
        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self.play_all_btn = QPushButton(" Tümünü Çal")
        self.play_all_btn.setIcon(vicon("play", 15, "#ffffff"))
        self.play_all_btn.setIconSize(QSize(15, 15))
        self.play_all_btn.setObjectName("Primary")
        self.play_all_btn.setCursor(Qt.PointingHandCursor)
        self.play_all_btn.setFixedHeight(38)
        self.play_all_btn.setStyleSheet("""
            QPushButton {
                background: #a980f9;
                color: #ffffff;
                border-radius: 19px;
                padding: 6px 22px;
                font-size: 13px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background: #b996fb;
            }
        """)
        self.play_all_btn.clicked.connect(self._on_play_all)
        actions_row.addWidget(self.play_all_btn)

        self.shuffle_btn = QPushButton(" Karışık Çal")
        self.shuffle_btn.setIcon(vicon("shuffle", 15, "#ffffff"))
        self.shuffle_btn.setIconSize(QSize(15, 15))
        self.shuffle_btn.setCursor(Qt.PointingHandCursor)
        self.shuffle_btn.setFixedHeight(38)
        self.shuffle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 19px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.20);
            }
        """)
        self.shuffle_btn.clicked.connect(self._on_shuffle_all)
        actions_row.addWidget(self.shuffle_btn)

        self.radio_btn = QPushButton(" Sanatçı Radyosu")
        self.radio_btn.setIcon(vicon("radio", 15, "#ffffff"))
        self.radio_btn.setIconSize(QSize(15, 15))
        self.radio_btn.setCursor(Qt.PointingHandCursor)
        self.radio_btn.setFixedHeight(38)
        self.radio_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 19px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.20);
            }
        """)
        self.radio_btn.clicked.connect(self._on_start_radio)
        actions_row.addWidget(self.radio_btn)

        self.add_album_btn = QPushButton(" Çalma Listesi Yap")
        self.add_album_btn.setIcon(vicon("plus", 14, "#ffffff"))
        self.add_album_btn.setIconSize(QSize(14, 14))
        self.add_album_btn.setCursor(Qt.PointingHandCursor)
        self.add_album_btn.setFixedHeight(38)
        self.add_album_btn.setVisible(False)
        self.add_album_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.10);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 19px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.20);
            }
        """)
        self.add_album_btn.clicked.connect(self._on_save_album_as_playlist)
        actions_row.addWidget(self.add_album_btn)

        actions_row.addStretch(1)
        info_col.addLayout(actions_row)
        info_col.addStretch(1)

        header_row.addLayout(info_col, stretch=1)
        card_layout.addLayout(header_row)
        hero_layout.addWidget(self.hero_card)

        self.content_layout.addWidget(hero_box)

    # =========================================================================
    # SANATÇI YÜKLEME
    # =========================================================================
    def show_artist(self, artist_name: str, browse_id: str = "", push_history: bool = True):
        clean_name = artist_name.strip()
        if not clean_name:
            return

        if push_history and (self._current_artist or self._current_browse_id):
            if self._current_mode == "album":
                self._nav_stack.append((
                    "album", self._current_browse_id,
                    getattr(self, "_current_album_title", ""), self._current_artist,
                ))
            else:
                self._nav_stack.append(("artist", self._current_browse_id, self._current_artist, ""))

        self._current_mode = "artist"
        self._current_artist = clean_name
        self._current_browse_id = browse_id
        self._artist_data = None
        self._album_data = None
        self._avatar_url = None
        self._token += 1
        token = self._token

        # Hero'yu Sanatçı moduna hazırla
        self.hero_tag.setText("SANATÇI")
        self.hero_title.setText(clean_name)
        self.hero_avatar.setStyleSheet("border-radius: 62px; background: rgba(255, 255, 255, 0.08);")
        self.add_album_btn.setVisible(False)
        self.radio_btn.setVisible(True)

        # Placeholder avatar
        col = cover_color_for(clean_name)
        if hasattr(self, "hero_card"):
            self.hero_card.setStyleSheet(f"""
                QFrame#ArtistHeroCard {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {col}44,
                        stop:0.65 rgba(20, 16, 34, 0.90),
                        stop:1 rgba(12, 10, 24, 0.98));
                    border-radius: 20px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                }}
            """)
        self.hero_avatar.setPixmap(QPixmap())
        initial = clean_name[0].upper() if clean_name else "👤"
        self.hero_avatar.setText(initial)
        self.hero_avatar.setStyleSheet(
            f"border-radius: 65px; background: {col}; color: #ffffff; font-size: 44px; font-weight: bold;"
        )

        # Kütüphanedeki parçaları topla
        library_songs = self._find_library_songs(clean_name)
        self.hero_sub.setText(f"Doğrulanmış Sanatçı • Kütüphanende {len(library_songs)} şarkı")

        # Önceki bölümleri temizle
        self._clear_sections()

        # 1) Kütüphanemdeki Parçalar Bölümü
        if library_songs:
            self._render_library_section(library_songs)

        cache_key = f"{browse_id}|{clean_name.casefold()}"
        cached = self._artist_cache.get(cache_key)
        if cached is not None:
            self._apply_artist_data(token, clean_name, cached)
            return

        # Durum göstergesi: Yükleniyor
        self.loading_label = QLabel("⏳ Sanatçı bilgileri ve popüler parçalar yükleniyor…")
        self.loading_label.setStyleSheet("color: rgba(255, 255, 255, 0.65); font-size: 13px; padding: 10px 0;")
        self.sections_layout.addWidget(self.loading_label)

        # 2) Arka plan iş parçacığı: YouTube Music verilerini çek
        def worker():
            data = self._fetch_artist_remote(clean_name, browse_id)
            if token == self._token:
                try:
                    self.artistDataReady.emit(token, clean_name, data)
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True, name="ArtistWorker").start()

    @classmethod
    def _get_ytm(cls):
        ytm = getattr(cls, "_shared_ytm", None)
        if ytm is None:
            import ytmusicapi
            ytm = ytmusicapi.YTMusic()
            cls._shared_ytm = ytm
        return ytm

    def _fetch_artist_remote(self, clean_name: str, browse_id: str) -> dict | None:
        data = None
        try:
            ytm = self._get_ytm()
            b_id = browse_id
            if not b_id:
                res = ytm.search(clean_name, filter="artists")
                if res:
                    b_id = res[0].get("browseId") or ""
            if b_id:
                data = ytm.get_artist(b_id)
            if not data or not data.get("songs", {}).get("results"):
                search_songs = ytm.search(clean_name, filter="songs")
                if search_songs:
                    if not data:
                        data = {"name": clean_name}
                    data.setdefault("songs", {})["results"] = search_songs[:15]
            else:
                existing = data.get("songs", {}).get("results", [])
                if len(existing) < 10:
                    try:
                        extra_songs = ytm.search(clean_name, filter="songs")
                        seen_ids = {s.get("videoId") for s in existing if s.get("videoId")}
                        for s in extra_songs:
                            vid = s.get("videoId")
                            if vid and vid not in seen_ids:
                                existing.append(s)
                                seen_ids.add(vid)
                            if len(existing) >= 15:
                                break
                    except Exception:
                        pass
        except Exception as e:
            log.warning("Sanatçı verisi alınamadı (%s): %s", clean_name, e)
        return data

    def _find_library_songs(self, artist_name: str) -> list[dict]:
        """Tüm çalma listelerini tarayıp bu sanatçıya ait parçaları bulur."""
        norm_target = artist_name.strip().casefold()
        matches = []
        seen_urls = set()
        for playlist, songs in self.store.playlists.items():
            for song in songs:
                url = song.get("webpage_url")
                if url in seen_urls:
                    continue
                _, p_artist = parse_track_and_artist(song.get("title", ""), song.get("uploader", ""), song)
                if norm_target in p_artist.casefold() or p_artist.casefold() in norm_target:
                    seen_urls.add(url)
                    matches.append(song)
        return matches

    def _apply_artist_data(self, token: int, artist_name: str, data: dict | None):
        if token != self._token or self._current_mode != "artist":
            return
        if hasattr(self, "loading_label") and self.loading_label:
            self.loading_label.deleteLater()
            self.loading_label = None

        if not data:
            no_info = QLabel("Çevrimiçi ek sanatçı verisi bulunamadı.")
            no_info.setStyleSheet("color: rgba(255, 255, 255, 0.50); font-size: 13px; padding: 10px 0;")
            self.sections_layout.addWidget(no_info)
            return
        self._artist_data = data
        cache_key = f"{self._current_browse_id}|{artist_name.casefold()}"
        self._artist_cache[cache_key] = data
        while len(self._artist_cache) > 30:
            self._artist_cache.pop(next(iter(self._artist_cache)))

        # Sanatçı kapak fotoğrafı
        thumbs = data.get("thumbnails", [])
        if thumbs and self.thumbnails is not None:
            photo_url = thumbs[-1].get("url")
            if photo_url:
                self._avatar_url = photo_url
                fake_song = {"thumbnail": photo_url, "webpage_url": photo_url}
                pm = self.thumbnails.pixmap_for(fake_song, 130, radius=65, rounded=True)
                if pm is not None and not pm.isNull():
                    self.hero_avatar.setPixmap(pm)
                    self.hero_avatar.setText("")
                    self.hero_avatar.setStyleSheet("border-radius: 65px; background: transparent;")

        # Abone bilgisi
        subs = data.get("subscribers")
        lib_count = len(self._find_library_songs(artist_name))
        sub_text = f"Doğrulanmış Sanatçı • Kütüphanende {lib_count} şarkı"
        if subs:
            sub_text += f" • {subs} Abone"
        self.hero_sub.setText(sub_text)

        # Popüler Şarkılar Bölümü
        top_songs = data.get("songs", {}).get("results", [])
        if top_songs:
            self._render_popular_songs_section(top_songs, artist_name)

        # Albümler ve Tekliler Bölümü
        albums = data.get("albums", {}).get("results", [])
        singles = data.get("singles", {}).get("results", [])
        all_releases = albums + singles
        if all_releases:
            self._render_releases_carousel(all_releases)

        # Benzer Sanatçılar Bölümü
        related = data.get("related", {}).get("results", [])
        if related:
            self._render_related_artists_carousel(related)

    # =========================================================================
    # BÖLÜMLERİN OLUŞTURULMASI
    # =========================================================================
    def _clear_sections(self):
        self._song_cover_labels.clear()
        while self.sections_layout.count():
            item = self.sections_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_library_section(self, songs: list[dict]):
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(10)

        header = QLabel(f"Kütüphanemdeki Şarkıları ({len(songs)})")
        header.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        box_layout.addWidget(header)

        for song in songs[:8]:  # İlk 8 parçayı listele
            row = self._create_song_item_row(song)
            box_layout.addWidget(row)

        self.sections_layout.addWidget(box)

    def _render_popular_songs_section(self, top_songs: list[dict], artist_name: str):
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(10)

        header = QLabel("Popüler Şarkılar")
        header.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        box_layout.addWidget(header)

        for idx, item in enumerate(top_songs[:10], start=1):
            vid = item.get("videoId")
            if not vid:
                continue
            song_dict = {
                "title": item.get("title", ""),
                "uploader": artist_name,
                "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                "duration": item.get("duration_seconds") or 0,
                "thumbnail": item.get("thumbnails", [{}])[-1].get("url") if item.get("thumbnails") else None,
            }
            row = self._create_song_item_row(song_dict, rank=idx, can_add=True)
            box_layout.addWidget(row)

        self.sections_layout.addWidget(box)

    def _create_song_item_row(self, song: dict, rank: int | None = None, can_add: bool = False) -> QWidget:
        row = QFrame()
        row.setObjectName("SongItemRow")
        row.setStyleSheet("""
            QFrame#SongItemRow {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 10px;
            }
            QFrame#SongItemRow:hover {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.15);
            }
        """)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # Sıra numarası (opsiyonel)
        if rank is not None:
            rank_lbl = QLabel(str(rank))
            rank_lbl.setObjectName("Muted")
            rank_lbl.setFixedWidth(20)
            rank_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(rank_lbl)

        # Kapak resmi
        cover_lbl = QLabel()
        cover_lbl.setFixedSize(40, 40)
        cover_lbl.setAlignment(Qt.AlignCenter)
        thumb_url = song.get("thumbnail")
        if self.thumbnails is not None and thumb_url:
            self._song_cover_labels.append((cover_lbl, song, 40, 6))
            pm = self.thumbnails.pixmap_for(song, 40, radius=6, rounded=True)
            if pm is not None and not pm.isNull():
                cover_lbl.setPixmap(pm)
            else:
                cover_lbl.setText("🎵")
                cover_lbl.setStyleSheet(f"background: {cover_color_for(song.get('title', ''))}; border-radius: 6px;")
        else:
            cover_lbl.setText("🎵")
            cover_lbl.setStyleSheet(f"background: {cover_color_for(song.get('title', ''))}; border-radius: 6px;")
        layout.addWidget(cover_lbl)

        # Başlık & Sanatçı
        t_clean, a_clean = parse_track_and_artist(song.get("title", ""), song.get("uploader", ""), song)
        t_layout = QVBoxLayout()
        t_layout.setContentsMargins(0, 0, 0, 0)
        t_layout.setSpacing(2)

        title_lbl = QLabel(t_clean)
        title_lbl.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 13px;")
        t_layout.addWidget(title_lbl)

        sub_lbl = QLabel(a_clean)
        sub_lbl.setObjectName("Muted")
        sub_lbl.setStyleSheet("font-size: 11px;")
        t_layout.addWidget(sub_lbl)
        layout.addLayout(t_layout, stretch=1)

        # Süre
        dur = song.get("duration")
        if dur:
            dur_lbl = QLabel(format_time(dur * 1000 if dur < 10000 else dur))
            dur_lbl.setObjectName("Muted")
            dur_lbl.setStyleSheet("font-size: 11px;")
            layout.addWidget(dur_lbl)

        # Oynat butonu
        play_btn = QPushButton()
        play_btn.setIcon(vicon("play", 13, "#ffffff"))
        play_btn.setIconSize(QSize(13, 13))
        play_btn.setFixedSize(28, 28)
        play_btn.setCursor(Qt.PointingHandCursor)
        play_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.12);
                color: #ffffff;
                border-radius: 14px;
                border: none;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #a980f9;
            }
        """)
        play_btn.clicked.connect(lambda: self._on_play_single_song(song))
        layout.addWidget(play_btn)

        # Kütüphaneye Ekle butonu (popüler şarkılar için)
        if can_add:
            add_btn = QPushButton("+ Ekle")
            add_btn.setCursor(Qt.PointingHandCursor)
            add_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: rgba(255, 255, 255, 0.6);
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    color: #ffffff;
                    border-color: #a980f9;
                }
            """)
            add_btn.clicked.connect(lambda: self._on_add_song_to_library(song))
            layout.addWidget(add_btn)

        return row

    def _render_releases_carousel(self, releases: list[dict]):
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(12)

        header = QLabel(f"Albümler ve Tekliler ({len(releases)})")
        header.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        box_layout.addWidget(header)

        # Yatay kaydırılabilir kart konteyneri
        hscroll = _HorizontalScrollArea()
        hscroll.setWidgetResizable(True)
        hscroll.setFixedHeight(210)
        hscroll.setFrameShape(QFrame.NoFrame)
        hscroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hscroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        cards_widget = QWidget()
        cards_widget.setAttribute(Qt.WA_StyledBackground, True)
        cards_widget.setStyleSheet("background: transparent;")
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(16)

        for rel in releases[:15]:
            card = self._create_album_card(rel)
            cards_layout.addWidget(card)

        cards_layout.addStretch(1)
        hscroll.setWidget(cards_widget)
        box_layout.addWidget(hscroll)

        self.sections_layout.addWidget(box)

    def _create_album_card(self, album: dict) -> QWidget:
        card = QFrame()
        card.setFixedSize(140, 195)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 10px;
            }
            QFrame:hover {
                background: rgba(255, 255, 255, 0.10);
                border-color: rgba(255, 255, 255, 0.20);
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Kapak
        cover = QLabel()
        cover.setFixedSize(120, 120)
        cover.setAlignment(Qt.AlignCenter)
        thumbs = album.get("thumbnails", [])
        if thumbs and self.thumbnails is not None:
            thumb_url = thumbs[-1].get("url")
            fake = {"thumbnail": thumb_url, "webpage_url": thumb_url}
            self._song_cover_labels.append((cover, fake, 120, 10))
            pm = self.thumbnails.pixmap_for(fake, 120, radius=10, rounded=True)
            if pm is not None and not pm.isNull():
                cover.setPixmap(pm)
            else:
                cover.setText("💿")
                cover.setStyleSheet("background: rgba(255,255,255,0.08); border-radius: 8px; font-size: 24px;")
        else:
            cover.setText("💿")
            cover.setStyleSheet("background: rgba(255,255,255,0.08); border-radius: 8px; font-size: 24px;")
        layout.addWidget(cover)

        # Başlık
        title = QLabel(album.get("title", "Albüm"))
        title.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 12px;")
        fm = QFontMetrics(title.font())
        title.setText(fm.elidedText(title.text(), Qt.ElideRight, 120))
        layout.addWidget(title)

        # Yıl / Tip
        sub = QLabel(str(album.get("year") or album.get("type") or "Albüm"))
        sub.setObjectName("Muted")
        sub.setStyleSheet("font-size: 11px;")
        layout.addWidget(sub)

        # Tıklanma olayı
        b_id = album.get("browseId")
        if b_id:
            alb_title = album.get("title", "")

            def _on_album_click(e, _bid=b_id, _t=alb_title, _card=card):
                if e.button() == Qt.LeftButton:
                    self.show_album(_bid, _t, self._current_artist)
                    e.accept()
                else:
                    QFrame.mousePressEvent(_card, e)

            card.mousePressEvent = _on_album_click

        return card

    def _render_related_artists_carousel(self, related: list[dict]):
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(12)

        header = QLabel("Benzer Sanatçılar")
        header.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        box_layout.addWidget(header)

        hscroll = _HorizontalScrollArea()
        hscroll.setWidgetResizable(True)
        hscroll.setFixedHeight(160)
        hscroll.setFrameShape(QFrame.NoFrame)
        hscroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hscroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        cards_widget = QWidget()
        cards_widget.setAttribute(Qt.WA_StyledBackground, True)
        cards_widget.setStyleSheet("background: transparent;")
        cards_layout = QHBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(16)

        for rel in related[:12]:
            card = self._create_related_artist_card(rel)
            cards_layout.addWidget(card)

        cards_layout.addStretch(1)
        hscroll.setWidget(cards_widget)
        box_layout.addWidget(hscroll)

        self.sections_layout.addWidget(box)

    def _create_related_artist_card(self, artist_dict: dict) -> QWidget:
        card = QFrame()
        card.setFixedSize(110, 140)
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet("""
            QFrame {
                background: transparent;
                border: none;
            }
            QFrame:hover QLabel#ArtistAvatar {
                border: 2px solid #a980f9;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        # Dairesel Avatar
        avatar = QLabel()
        avatar.setObjectName("ArtistAvatar")
        avatar.setFixedSize(84, 84)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("border-radius: 42px; background: rgba(255, 255, 255, 0.08);")

        name = artist_dict.get("title") or artist_dict.get("name") or "Sanatçı"
        thumbs = artist_dict.get("thumbnails", [])
        if thumbs and self.thumbnails is not None:
            thumb_url = thumbs[-1].get("url")
            fake = {"thumbnail": thumb_url, "webpage_url": thumb_url}
            self._song_cover_labels.append((avatar, fake, 84, 42))
            pm = self.thumbnails.pixmap_for(fake, 84, radius=42, rounded=True)
            if pm is not None and not pm.isNull():
                avatar.setPixmap(pm)
            else:
                col = cover_color_for(name)
                avatar.setText(name[0].upper() if name else "👤")
                avatar.setStyleSheet(f"border-radius: 42px; background: {col}; color: #ffffff; font-weight: bold;")
        else:
            col = cover_color_for(name)
            avatar.setText(name[0].upper() if name else "👤")
            avatar.setStyleSheet(f"border-radius: 42px; background: {col}; color: #ffffff; font-weight: bold;")
        layout.addWidget(avatar, alignment=Qt.AlignCenter)

        # İsim
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color: #ffffff; font-weight: 600; font-size: 11px;")
        name_lbl.setAlignment(Qt.AlignCenter)
        fm = QFontMetrics(name_lbl.font())
        name_lbl.setText(fm.elidedText(name, Qt.ElideRight, 96))
        layout.addWidget(name_lbl, alignment=Qt.AlignCenter)

        # Tıklanma olayı
        b_id = artist_dict.get("browseId") or ""

        def _on_related_click(e, _name=name, _bid=b_id, _card=card):
            if e.button() == Qt.LeftButton:
                self.show_artist(_name, _bid)
                e.accept()
            else:
                QFrame.mousePressEvent(_card, e)

        card.mousePressEvent = _on_related_click

        return card

    # =========================================================================
    # ALBÜM MODU
    # =========================================================================
    def show_album(self, browse_id: str, title: str = "", artist_name: str = "", push_history: bool = True):
        if not browse_id:
            return

        if push_history and (self._current_artist or self._current_browse_id):
            if self._current_mode == "album":
                self._nav_stack.append((
                    "album", self._current_browse_id,
                    getattr(self, "_current_album_title", ""), self._current_artist,
                ))
            else:
                self._nav_stack.append(("artist", self._current_browse_id, self._current_artist, ""))

        self._current_mode = "album"
        self._current_browse_id = browse_id
        self._current_album_title = title or "Albüm"
        if artist_name:
            self._current_artist = artist_name
        self._artist_data = None
        self._album_data = None
        self._avatar_url = None
        self._token += 1
        token = self._token

        # Hero'yu Albüm moduna hazırla
        self.hero_tag.setText("ALBÜM")
        self.hero_title.setText(title or "Albüm")
        self.hero_sub.setText(f"{artist_name} • Yükleniyor…")
        self.hero_avatar.setStyleSheet("border-radius: 16px; background: rgba(255, 255, 255, 0.08);")
        self.add_album_btn.setVisible(True)
        self.radio_btn.setVisible(False)

        col = cover_color_for(title or "Albüm")
        if hasattr(self, "hero_card"):
            self.hero_card.setStyleSheet(f"""
                QFrame#ArtistHeroCard {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {col}44,
                        stop:0.65 rgba(20, 16, 34, 0.90),
                        stop:1 rgba(12, 10, 24, 0.98));
                    border-radius: 20px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                }}
            """)
        self.hero_avatar.setPixmap(QPixmap())
        self.hero_avatar.setText("💿")
        self.hero_avatar.setStyleSheet(
            f"border-radius: 16px; background: {col}; color: #ffffff; font-size: 38px;"
        )

        self._clear_sections()
        cached = self._album_cache.get(browse_id)
        if cached is not None:
            self._apply_album_data(token, cached, artist_name)
            return

        self.loading_label = QLabel("⏳ Albüm parçaları yükleniyor…")
        self.loading_label.setStyleSheet("color: rgba(255, 255, 255, 0.65); font-size: 13px; padding: 10px 0;")
        self.sections_layout.addWidget(self.loading_label)

        def worker():
            data = self._fetch_album_remote(browse_id)
            if token == self._token:
                try:
                    self.albumDataReady.emit(token, data, artist_name)
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True, name="AlbumWorker").start()

    def _fetch_album_remote(self, browse_id: str) -> dict | None:
        try:
            return self._get_ytm().get_album(browse_id)
        except Exception as e:
            log.warning("Albüm verisi alınamadı (%s): %s", browse_id, e)
            return None

    def _apply_album_data(self, token: int, data: dict | None, artist_name: str):
        if token != self._token or self._current_mode != "album":
            return
        if hasattr(self, "loading_label") and self.loading_label:
            self.loading_label.deleteLater()
            self.loading_label = None

        if not data:
            no_info = QLabel("Albüm içeriği yüklenemedi.")
            no_info.setStyleSheet("color: rgba(255, 255, 255, 0.50); font-size: 13px; padding: 10px 0;")
            self.sections_layout.addWidget(no_info)
            return
        self._album_data = data
        if self._current_browse_id:
            self._album_cache[self._current_browse_id] = data
            while len(self._album_cache) > 30:
                self._album_cache.pop(next(iter(self._album_cache)))

        album_title = data.get("title", self.hero_title.text())
        self.hero_title.setText(album_title)

        year = data.get("year") or ""
        tracks = data.get("tracks", [])
        sub_info = f"{artist_name} • {len(tracks)} Şarkı"
        if year:
            sub_info = f"{artist_name} • {year} • {len(tracks)} Şarkı"
        self.hero_sub.setText(sub_info)

        # Kapak görseli
        thumbs = data.get("thumbnails", [])
        if thumbs and self.thumbnails is not None:
            photo_url = thumbs[-1].get("url")
            if photo_url:
                self._avatar_url = photo_url
                fake_song = {"thumbnail": photo_url, "webpage_url": photo_url}
                pm = self.thumbnails.pixmap_for(fake_song, 124, radius=16, rounded=True)
                if pm is not None and not pm.isNull():
                    self.hero_avatar.setPixmap(pm)
                    self.hero_avatar.setText("")
                    self.hero_avatar.setStyleSheet("border-radius: 16px; background: transparent;")

        # Parça listesi
        tracklist_box = QWidget()
        box_layout = QVBoxLayout(tracklist_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(8)

        header = QLabel(f"Parçalar ({len(tracks)})")
        header.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        box_layout.addWidget(header)

        for idx, t in enumerate(tracks, start=1):
            vid = t.get("videoId")
            if not vid:
                continue
            song_dict = {
                "title": t.get("title", ""),
                "uploader": artist_name,
                "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                "duration": t.get("duration_seconds") or 0,
                "thumbnail": thumbs[-1].get("url") if thumbs else None,
            }
            row = self._create_song_item_row(song_dict, rank=idx, can_add=True)
            box_layout.addWidget(row)

        self.sections_layout.addWidget(tracklist_box)

    # =========================================================================
    # EYLEMLER
    # =========================================================================
    def _on_back_clicked(self):
        if self._nav_stack:
            prev_mode, prev_bid, prev_title_or_artist, prev_artist = self._nav_stack.pop()
            if prev_mode == "artist":
                self.show_artist(prev_title_or_artist, prev_bid, push_history=False)
            elif prev_mode == "album":
                self.show_album(prev_bid, prev_title_or_artist, prev_artist, push_history=False)
        else:
            self.backRequested.emit()

    def _on_play_single_song(self, song: dict):
        self.playSongRequested.emit(song)

    def _on_add_song_to_library(self, song: dict):
        active_pl = self.store.active_playlist or "Varsayılan"
        if self.store.add_song(active_pl, song):
            self.store.statusMessage.emit(f"✓ \"{song.get('title')}\" listeye eklendi.", "success")
        else:
            self.store.statusMessage.emit(f"Bu şarkı zaten listede mevcut.", "info")

    def _on_play_all(self):
        """Mevcut sayfadaki tüm şarkıları kuyruğa alır ve başlatır."""
        all_songs = []
        if self._current_mode == "artist":
            # Kütüphanedeki şarkılar varsa onları, yoksa popüler parçaları çal
            lib_songs = self._find_library_songs(self._current_artist)
            if lib_songs:
                all_songs = lib_songs
            elif self._artist_data:
                for item in self._artist_data.get("songs", {}).get("results", []):
                    vid = item.get("videoId")
                    if vid:
                        thumbs = item.get("thumbnails") or []
                        all_songs.append({
                            "title": item.get("title", ""),
                            "uploader": self._current_artist,
                            "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                            "duration": item.get("duration_seconds") or 0,
                            "thumbnail": thumbs[-1].get("url") if thumbs else None,
                        })
        elif self._current_mode == "album" and self._album_data:
            artist_n = self._current_artist
            album_thumbs = self._album_data.get("thumbnails") or []
            album_thumb = album_thumbs[-1].get("url") if album_thumbs else None
            for t in self._album_data.get("tracks", []):
                vid = t.get("videoId")
                if vid:
                    t_thumbs = t.get("thumbnails") or []
                    all_songs.append({
                        "title": t.get("title", ""),
                        "uploader": artist_n,
                        "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                        "duration": t.get("duration_seconds") or 0,
                        "thumbnail": t_thumbs[-1].get("url") if t_thumbs else album_thumb,
                    })

        if not all_songs:
            self.store.statusMessage.emit("Çalınacak şarkı bulunamadı.", "info")
            return

        # Geçici Sanatçı/Albüm çalma listesi oluştur ve çal
        pl_name = f"Sanatçı: {self._current_artist}" if self._current_mode == "artist" else f"Albüm: {self.hero_title.text()}"
        self.store.playlists[pl_name] = all_songs
        self.store.playlistsChanged.emit()
        self.playback.play_song_at_index(pl_name, 0)
        self.store.statusMessage.emit(f"▶ {pl_name} başlatıldı ({len(all_songs)} şarkı).", "success")

    def _on_shuffle_all(self):
        if hasattr(self.playback, "enable_shuffle"):
            self.playback.enable_shuffle()
        elif not self.playback.shuffle_mode:
            if hasattr(self.playback, "toggle_shuffle"):
                self.playback.toggle_shuffle()
            else:
                self.playback.shuffle_mode = True
        self._on_play_all()

    def _on_start_radio(self):
        """Sanatçı radyosu başlat."""
        fake_seed = {
            "title": self._current_artist,
            "uploader": self._current_artist,
            "artist": self._current_artist,
        }
        self.startRadioRequested.emit(fake_seed)

    def _on_save_album_as_playlist(self):
        """Albümdeki parçaları kütüphanede kalıcı bir playlist olarak kaydeder."""
        if not self._album_data:
            return
        album_title = self.hero_title.text()
        tracks = self._album_data.get("tracks", [])
        album_thumbs = self._album_data.get("thumbnails") or []
        album_thumb = album_thumbs[-1].get("url") if album_thumbs else None
        song_list = []
        for t in tracks:
            vid = t.get("videoId")
            if vid:
                t_thumbs = t.get("thumbnails") or []
                song_list.append({
                    "title": t.get("title", ""),
                    "uploader": self._current_artist,
                    "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                    "duration": t.get("duration_seconds") or 0,
                    "thumbnail": t_thumbs[-1].get("url") if t_thumbs else album_thumb,
                })
        if song_list:
            target_name = f"Albüm: {album_title}"
            self.store.playlists[target_name] = song_list
            if hasattr(self.store, "save"):
                self.store.save()
            self.store.playlistsChanged.emit()
            self.store.statusMessage.emit(f"✓ \"{target_name}\" kütüphaneye eklendi ({len(song_list)} şarkı).", "success")

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Escape, Qt.Key_Back):
            self._on_back_clicked()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.BackButton:
            self._on_back_clicked()
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_thumbnail_ready(self, key: str):
        # 1) Avatar güncellemesi
        if getattr(self, "_avatar_url", None) == key and self.thumbnails is not None:
            fake_song = {"thumbnail": key, "webpage_url": key}
            is_artist = (self._current_mode == "artist")
            rad_px = 65 if is_artist else 16
            sz_px = 130 if is_artist else 124
            pm = self.thumbnails.pixmap_for(fake_song, sz_px, radius=rad_px, rounded=True)
            if pm and not pm.isNull():
                self.hero_avatar.setPixmap(pm)
                self.hero_avatar.setText("")
                self.hero_avatar.setStyleSheet(f"border-radius: {rad_px}px; background: transparent;")

        # 2) Parça, Albüm ve Benzer Sanatçı kapakları güncellemesi
        for entry in getattr(self, "_song_cover_labels", []):
            try:
                lbl, item_song, sz, rad = entry
                if item_song.get("webpage_url") == key and self.thumbnails is not None:
                    pm = self.thumbnails.pixmap_for(item_song, sz, radius=rad, rounded=True)
                    if pm and not pm.isNull():
                        lbl.setPixmap(pm)
                        lbl.setText("")
                        lbl.setStyleSheet(f"border-radius: {rad}px; background: transparent;")
            except Exception:
                pass

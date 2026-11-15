"""
Keşfet ekranı — "Music Discovery Hub".

Düz bir şarkı listesi yerine: büyük bir "Bugünün Keşfi" hero alanı ve altında
her biri kendi içinde yatay kaydırılabilen, YouTube/YouTube Music verisinden
üretilen kategori bölümleri (Türkiye'de Yükselenler, Türkçe Rap, Global,
Sanatçı Keşfi, mood bölümleri, ...).

Veri katmanı (helpers.discovery.DiscoveryService) tamamen ayrıdır ve Qt'ye
bağımlı değildir; burada yalnızca UI + arka plan thread orkestrasyonu var.
Desen: 1) cache varsa hemen göster, 2) arka planda refresh başlat,
3) her bölüm hazır oldukça o bölümün kartlarını güncelle — hiçbir zaman
GUI thread'ini kilitlemeden, hiçbir zaman ekranı boş bırakmadan.
"""
from __future__ import annotations

import threading
import webbrowser
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedLayout,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for, format_time
from mustiefly_qt.helpers.discovery import CATEGORY_DEFS, DiscoveryService
from mustiefly_qt.helpers.logging_setup import get_logger
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.thumbnails import ThumbnailService


log = get_logger(__name__)


class _HorizontalScroll(QScrollArea):
    """Fare tekerleğini yatay kaydırmaya çeviren alan (bkz. HomeView)."""

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)


class _Skeleton(QWidget):
    """Veri gelene kadar gösterilen soluk placeholder kart."""

    def __init__(self, size: int = 150, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet("background: rgba(255,255,255,18); border-radius: 14px;")


class TrackCard(QWidget):
    """Bir şarkı için yatay vitrindeki kart: thumbnail + hover'da play/+ ."""

    playRequested = Signal(dict)
    addRequested = Signal(dict)

    CARD_W = 148
    THUMB_H = 148

    def __init__(self, track: dict, thumbnails: ThumbnailService | None,
                 rank: int | None = None, parent=None):
        super().__init__(parent)
        self.track = track
        self.thumbnails = thumbnails
        self.setObjectName("DiscoveryCard")
        self.setFixedWidth(self.CARD_W)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 6)
        outer.setSpacing(6)

        self._thumb_frame = QWidget()
        self._thumb_frame.setFixedSize(self.CARD_W - 8, self.THUMB_H)
        stack = QStackedLayout(self._thumb_frame)
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)

        self.thumb = QLabel("🎵")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedSize(self.CARD_W - 8, self.THUMB_H)
        self.thumb.setStyleSheet(
            f"background: {cover_color_for(track.get('title', '?'))};"
            "border-radius: 14px; font-size: 32px;")
        stack.addWidget(self.thumb)

        self._overlay = QWidget()
        self._overlay.setAttribute(Qt.WA_StyledBackground, True)
        self._overlay.setStyleSheet("background: transparent; border-radius: 14px;")
        ov_layout = QVBoxLayout(self._overlay)
        ov_layout.setContentsMargins(6, 6, 6, 6)
        top_row = QHBoxLayout()
        top_row.addStretch(1)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.setToolTip("Kütüphaneye ekle")
        self.add_btn.setStyleSheet(
            "QPushButton { background: rgba(10,10,16,190); color: white;"
            " border-radius: 12px; font-weight: bold; border: none; }"
            "QPushButton:hover { background: rgba(10,10,16,230); }")
        self.add_btn.clicked.connect(lambda: self.addRequested.emit(self.track))
        top_row.addWidget(self.add_btn)
        ov_layout.addLayout(top_row)
        ov_layout.addStretch(1)
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.clicked.connect(lambda: self.playRequested.emit(self.track))
        bottom_row.addWidget(self.play_btn, alignment=Qt.AlignCenter)
        bottom_row.addStretch(1)
        ov_layout.addLayout(bottom_row)
        ov_layout.addStretch(1)
        stack.addWidget(self._overlay)
        self._set_overlay_visible(False)

        if rank is not None:
            self.rank_label = QLabel(str(rank), self._thumb_frame)
            self.rank_label.setStyleSheet(
                "background: rgba(10,10,16,190); color: white; font-weight: bold;"
                " border-radius: 10px; padding: 2px 8px;")
            self.rank_label.move(6, 6)
            self.rank_label.show()
            self.rank_label.raise_()

        outer.addWidget(self._thumb_frame)

        title = track.get("title", "?")
        t_label = QLabel(title[:28] + ("…" if len(title) > 28 else ""))
        t_label.setWordWrap(True)
        t_label.setStyleSheet("font-weight: 600;")
        outer.addWidget(t_label)

        meta = track.get("uploader") or "Bilinmeyen Sanatçı"
        if track.get("duration"):
            meta += f" • {format_time(track['duration'] * 1000)}"
        m_label = QLabel(meta[:32] + ("…" if len(meta) > 32 else ""))
        m_label.setObjectName("Muted")
        outer.addWidget(m_label)

        if thumbnails is not None:
            pm = thumbnails.pixmap_for(track, self.THUMB_H, radius=14)
            if pm is not None:
                self.set_pixmap(pm)

    def _set_overlay_visible(self, visible: bool):
        self._overlay.setStyleSheet(
            "background: rgba(0,0,0,110); border-radius: 14px;" if visible
            else "background: transparent; border-radius: 14px;")
        self.add_btn.setVisible(visible)
        self.play_btn.setVisible(visible)

    def enterEvent(self, event):  # noqa: N802
        self._set_overlay_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._set_overlay_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.playRequested.emit(self.track)
        super().mousePressEvent(event)

    def set_pixmap(self, pm):
        if pm is not None and not pm.isNull():
            self.thumb.setPixmap(pm)
            self.thumb.setText("")


class ArtistCard(QWidget):
    """Sanatçı Keşfi bölümündeki dairesel kart."""

    clicked = Signal()

    SIZE = 118

    def __init__(self, artist: dict, thumbnails: ThumbnailService | None, parent=None):
        super().__init__(parent)
        self.artist = artist
        self.setFixedWidth(self.SIZE + 10)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignHCenter)

        self.photo = QLabel("🧑‍🎤")
        self.photo.setFixedSize(self.SIZE, self.SIZE)
        self.photo.setAlignment(Qt.AlignCenter)
        self.photo.setStyleSheet(
            f"background: {cover_color_for(artist.get('name', '?'))};"
            f"border-radius: {self.SIZE // 2}px; font-size: 30px;")
        layout.addWidget(self.photo)

        name = artist.get("name", "?")
        name_label = QLabel(name[:18] + ("…" if len(name) > 18 else ""))
        name_label.setAlignment(Qt.AlignHCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(name_label)

        sub_label = QLabel(artist.get("subtitle", ""))
        sub_label.setObjectName("Muted")
        sub_label.setAlignment(Qt.AlignHCenter)
        layout.addWidget(sub_label)

        if thumbnails is not None and artist.get("thumbnail"):
            fake_song = {"webpage_url": artist["thumbnail"], "thumbnail": artist["thumbnail"]}
            pm = thumbnails.pixmap_for(fake_song, self.SIZE, radius=self.SIZE // 2)
            if pm is not None:
                self.photo.setPixmap(pm)
                self.photo.setText("")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class HeroCard(QWidget):
    """Ekranın en üstündeki 'BUGÜNÜN KEŞFİ' öne çıkan alanı."""

    playRequested = Signal(dict)

    def __init__(self, thumbnails: ThumbnailService | None, parent=None):
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.track: dict | None = None
        self.setObjectName("HeroCard")
        self.setMinimumHeight(220)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(22)

        self.art = QLabel("🎧")
        self.art.setFixedSize(180, 180)
        self.art.setAlignment(Qt.AlignCenter)
        self.art.setStyleSheet(
            "background: rgba(255,255,255,22); border-radius: 16px; font-size: 50px;")
        layout.addWidget(self.art)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)
        tag = QLabel("BUGÜNÜN KEŞFİ")
        tag.setObjectName("Muted")
        tag.setStyleSheet("font-weight: 700; letter-spacing: 1px;")
        text_col.addWidget(tag)

        self.title_label = QLabel("Yükleniyor…")
        self.title_label.setStyleSheet("font-size: 23px; font-weight: bold;")
        self.title_label.setWordWrap(True)
        text_col.addWidget(self.title_label)

        self.artist_label = QLabel("")
        self.artist_label.setObjectName("Muted")
        text_col.addWidget(self.artist_label)

        self.desc_label = QLabel("Keşfet verileri hazırlanıyor…")
        self.desc_label.setObjectName("Muted")
        self.desc_label.setWordWrap(True)
        text_col.addWidget(self.desc_label)
        text_col.addStretch(1)

        self.play_btn = QPushButton("▶ Şimdi Dinle")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setFixedWidth(170)
        self.play_btn.clicked.connect(self._on_play)
        text_col.addWidget(self.play_btn)

        layout.addLayout(text_col, stretch=1)

    def set_track(self, track: dict | None):
        self.track = track
        if not track:
            self.title_label.setText("Şu anda öne çıkan bir içerik yok")
            self.artist_label.setText("")
            self.desc_label.setText("İnternet bağlantını kontrol et ya da \"Yenile\"ye bas.")
            return
        self.title_label.setText(track.get("title", "?"))
        self.artist_label.setText(track.get("uploader") or "Bilinmeyen Sanatçı")
        self.desc_label.setText("Keşfet bölümlerinden rastgele seçildi.")
        self.art.setText("🎧")
        if self.thumbnails is not None:
            pm = self.thumbnails.pixmap_for(track, 180, radius=16)
            if pm is not None:
                self.art.setPixmap(pm)
                self.art.setText("")

    def _on_play(self):
        if self.track:
            self.playRequested.emit(self.track)


class DiscoverySection(QWidget):
    """Bir kategori: başlık + alt açıklama + yatay kaydırılabilen kart şeridi.
    Veri gelene kadar skeleton gösterir; veri yoksa (kategori boşsa) gizlenir."""

    playRequested = Signal(dict)
    addRequested = Signal(dict)
    artistClicked = Signal(dict)

    def __init__(self, cat_def: dict, thumbnails: ThumbnailService | None, parent=None):
        super().__init__(parent)
        self.cat_def = cat_def
        self.thumbnails = thumbnails
        self.items: list[dict] = []
        self._is_artist = cat_def.get("kind") == "artist"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QVBoxLayout()
        header.setSpacing(0)
        self.title_label = QLabel(self._resolve_title())
        self.title_label.setStyleSheet("font-size: 17px; font-weight: bold;")
        header.addWidget(self.title_label)
        self.subtitle_label = QLabel(cat_def.get("subtitle", ""))
        self.subtitle_label.setObjectName("Muted")
        header.addWidget(self.subtitle_label)
        self.source_label = QLabel("")
        self.source_label.setObjectName("Muted")
        self.source_label.setStyleSheet("font-size: 11px;")
        self.source_label.setVisible(False)
        header.addWidget(self.source_label)
        layout.addLayout(header)

        self.row_host = QWidget()
        self.row_host.setStyleSheet("background: transparent;")
        self.row_layout = QHBoxLayout(self.row_host)
        self.row_layout.setContentsMargins(2, 2, 2, 2)
        self.row_layout.setSpacing(12)

        self.scroll = _HorizontalScroll()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        card_h = ArtistCard.SIZE if self._is_artist else TrackCard.THUMB_H
        self.scroll.setFixedHeight(card_h + 68)
        self.scroll.setWidget(self.row_host)
        layout.addWidget(self.scroll)

        self._show_skeleton()

    @staticmethod
    def source_text(section: dict) -> str:
        """\"Kaynak: … · Güncelleme: …\" satırı (kaynak bilinmiyorsa dürüstçe belirtilir)."""
        source = (section.get("source") or {}).get("label") or "bilinmiyor (eski önbellek)"
        text = f"Kaynak: {source}"
        ts = section.get("updated_at")
        if ts:
            text += " · Güncelleme: " + datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
        return text

    def _resolve_title(self) -> str:
        title = self.cat_def.get("title")
        if callable(title):
            return title(datetime.now())
        return title

    def _clear_row(self):
        while self.row_layout.count():
            item = self.row_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_skeleton(self, count: int = 5):
        self._clear_row()
        size = ArtistCard.SIZE if self._is_artist else TrackCard.CARD_W
        for _ in range(count):
            self.row_layout.addWidget(_Skeleton(size))
        self.row_layout.addStretch(1)

    def set_data(self, section: dict | None):
        """Bölüm verisini uygular. Veri yoksa bölüm tamamen gizlenir
        (spec: "veri yoksa -> bölümü gizle")."""
        if not section or not section.get("items"):
            self.hide()
            return
        self.show()
        self.items = section["items"]
        self.title_label.setText(section.get("title") or self._resolve_title())
        self.subtitle_label.setText(section.get("subtitle") or self.cat_def.get("subtitle", ""))
        self._clear_row()

        # Sıra rozeti yalnızca GERÇEK sıralı liste verisinde; eski önbellekte
        # (kaynak bilgisi yok) güvenli tarafta kalıp gizlenir.
        rank_enabled = bool(section.get("ranked", False))
        self.source_label.setText(self.source_text(section))
        self.source_label.setVisible(True)
        if self._is_artist:
            for artist in self.items:
                card = ArtistCard(artist, self.thumbnails)
                card.clicked.connect(lambda a=artist: self.artistClicked.emit(a))
                self.row_layout.addWidget(card)
        else:
            for i, track in enumerate(self.items):
                card = TrackCard(track, self.thumbnails, rank=(i + 1) if rank_enabled else None)
                card.playRequested.connect(self.playRequested.emit)
                card.addRequested.connect(self.addRequested.emit)
                self.row_layout.addWidget(card)
        self.row_layout.addStretch(1)


class ExploreView(QWidget):
    """Keşfet ekranının kökü: hero + bölüm listesi + arka plan yenileme."""

    # Arka plan thread'inden GUI thread'ine sonuç taşıyıcılar
    sectionUpdated = Signal(dict)
    heroUpdated = Signal(dict)
    refreshFinished = Signal(bool, str)

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None = None, paths=None,
                 settings: dict | None = None, save_settings_fn=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails
        cache_dir = getattr(paths, "cache_dir", None) if paths is not None else None
        # settings/save_settings_fn verilirse (Ayarlar > Entegrasyonlar'da
        # kayıtlı Spotify bilgileri), kullanıcı zaten bağlıysa chart
        # kategorileri gerçek Spotify verisiyle zenginleşir; verilmezse
        # DiscoveryService yalnızca YouTube tabanlı kaynakları kullanır.
        self.discovery = DiscoveryService(cache_dir, settings, save_settings_fn)
        self._sections: dict[str, DiscoverySection] = {}
        self._refreshing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("🧭 Keşfet")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        title_box.addWidget(title)
        self.status_label = QLabel("Hazırlanıyor…")
        self.status_label.setObjectName("Muted")
        title_box.addWidget(self.status_label)
        header.addLayout(title_box, stretch=1)

        self.refresh_btn = QPushButton("🔄 Yenile")
        self.refresh_btn.setObjectName("Primary")
        self.refresh_btn.clicked.connect(lambda: self.start_refresh(force=True))
        header.addWidget(self.refresh_btn, alignment=Qt.AlignTop)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("DiscoveryContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(2, 2, 14, 20)
        self.content_layout.setSpacing(22)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        self.hero = HeroCard(self.thumbnails)
        self.hero.playRequested.connect(self._add_and_play)
        self.content_layout.addWidget(self.hero)

        # Tüm bölüm widget'ları baştan (skeleton halinde) kurulur — böylece
        # sıra CATEGORY_DEFS ile birebir eşleşir ve veri geldikçe yerinde
        # güncellenir; ekran asla tamamen boş kalmaz.
        for cat in CATEGORY_DEFS:
            section = DiscoverySection(cat, self.thumbnails)
            section.playRequested.connect(self._add_and_play)
            section.addRequested.connect(self._add_to_library)
            section.artistClicked.connect(self._on_artist_clicked)
            self.content_layout.addWidget(section)
            self._sections[cat["id"]] = section
        self.content_layout.addStretch(1)

        self.sectionUpdated.connect(self._on_section_updated)
        self.heroUpdated.connect(self.hero.set_track)
        self.refreshFinished.connect(self._on_refresh_finished)

        self._load_cache_then_refresh()

    # --- Yaşam döngüsü ---
    def _load_cache_then_refresh(self):
        cached = self.discovery.get_cached_data()
        if cached:
            for section in cached.get("sections", []):
                widget = self._sections.get(section.get("id"))
                if widget is not None:
                    widget.set_data(section)
            if cached.get("hero"):
                self.hero.set_track(cached["hero"])
            self.status_label.setText(self._status_text(cached.get("last_updated", 0)))
        else:
            self.status_label.setText("İlk kez yükleniyor…")
        self.start_refresh(force=False)

    def start_refresh(self, force: bool = False):
        if self._refreshing:
            return
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("🧭 Keşfet güncelleniyor…")
        threading.Thread(target=self._refresh_worker, args=(force,), daemon=True).start()

    def _refresh_worker(self, force: bool):
        try:
            cache = self.discovery.refresh_if_needed(
                force=force, on_section=lambda s: self.sectionUpdated.emit(s))
            if cache.get("hero"):
                self.heroUpdated.emit(cache["hero"])
            self.refreshFinished.emit(True, self._status_text(cache.get("last_updated", 0)))
        except Exception as e:
            log.error("%s %s", "Keşfet güncellemesi başarısız:", e)
            self.refreshFinished.emit(
                False,
                "Keşfet verileri şu anda güncellenemiyor. Son güncellenen içerikler gösteriliyor.")

    def _on_section_updated(self, section: dict):
        widget = self._sections.get(section.get("id"))
        if widget is not None:
            widget.set_data(section)

    def _on_refresh_finished(self, success: bool, message: str):
        self._refreshing = False
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(message)
        if not success:
            has_any = any(w.isVisible() for w in self._sections.values())
            if not has_any and self.hero.track is None:
                self.status_label.setText(
                    "Keşfet verileri şu anda güncellenemiyor. İnternet bağlantını kontrol et.")

    @staticmethod
    def _status_text(ts: float) -> str:
        if not ts:
            return "Henüz güncellenmedi."
        return "Son güncelleme: " + datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")

    # --- Etkileşimler (mevcut PlaylistStore / PlaybackEngine kullanılır) ---
    def _add_to_library(self, track: dict):
        target = self.store.active_playlist
        added = self.store.add_song(target, dict(track))
        if added:
            self.store.statusMessage.emit(
                f"✅ '{track['title']}' → \"{target}\" listesine eklendi.", "success")
        else:
            self.store.statusMessage.emit("Bu şarkı zaten listede var.", "warning")

    def _add_and_play(self, track: dict):
        """Keşfet'ten bir şarkıyı aktif playliste ekleyip (zaten ekliyse tekrar
        eklemeden) hemen mevcut PlaybackEngine üzerinden çalar."""
        target = self.store.active_playlist
        # Ham dict eklemek _clean_song/added_date normalleştirmesini atlıyordu;
        # add_song zaten yinelenenleri atlar ve gerekli alanları temizler.
        self.store.add_song(target, dict(track))
        webpage_url = track.get('webpage_url')
        index = next((i for i, s in enumerate(self.store.playlists.get(target, []))
                      if s.get('webpage_url') == webpage_url), -1)
        if index < 0:
            return
        self.playback.play_song_at_index(target, index)

    def _on_artist_clicked(self, artist: dict):
        url = artist.get("channel_url")
        if url:
            webbrowser.open(url)

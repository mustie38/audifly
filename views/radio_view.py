"""
Radyo görünümü — gerçek internet radyo istasyonları (Radio Browser API).

Orijinal _render_radio_view + radio_* metodlarının Qt portudur. Arama/filtre
arka planda yapılır; istasyon çalmayı PlaybackEngine.play_radio_station üstlenir
(aynı VLC player paylaşılır).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for
from mustiefly_qt.helpers.radio import RADIO_GENRE_CHIPS, fetch_radio_stations
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.widgets.player_icons import icon as vicon, icon_pixmap


class _StationRow(QWidget):
    playRequested = Signal(dict)
    favoriteToggled = Signal(dict)

    def __init__(self, station: dict, is_current: bool, is_fav: bool, parent=None):
        super().__init__(parent)
        self.station = station
        self.setObjectName("SongRow")
        self.setProperty("current", "true" if is_current else "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"background: {cover_color_for(station.get('name', '?'))};"
            "border-radius: 10px;")
        pm = icon_pixmap("radio", 18, "#ffffff")
        if pm is not None:
            icon.setPixmap(pm)
        layout.addWidget(icon)

        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        name = station.get('name', '?')
        t_label = QLabel(name[:55] + ("..." if len(name) > 55 else ""))
        t_label.setStyleSheet("font-weight: 600;")
        text_layout.addWidget(t_label)

        meta_parts = []
        if station.get('tags'):
            meta_parts.append(station['tags'].split(',')[0].strip().title())
        if station.get('country'):
            meta_parts.append(station['country'])
        if station.get('bitrate'):
            meta_parts.append(f"{station['bitrate']}kbps")
        m_label = QLabel(" • ".join(meta_parts) or "İnternet radyosu")
        m_label.setObjectName("Muted")
        text_layout.addWidget(m_label)
        layout.addWidget(text, stretch=1)

        fav_btn = QPushButton()
        fav_btn.setFixedSize(30, 30)
        fav_btn.setIcon(vicon("star", 15, "#FBBF24" if is_fav else "#9EA3B8"))
        fav_btn.setIconSize(QSize(15, 15))
        fav_btn.setCursor(Qt.PointingHandCursor)
        fav_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 15px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 0.08); }"
        )
        fav_btn.clicked.connect(lambda: self.favoriteToggled.emit(self.station))
        layout.addWidget(fav_btn)

        play_btn = QPushButton()
        play_btn.setObjectName("Primary")
        play_btn.setFixedSize(32, 32)
        play_btn.setIcon(vicon("play", 14, "#ffffff"))
        play_btn.setIconSize(QSize(14, 14))
        play_btn.setCursor(Qt.PointingHandCursor)
        play_btn.clicked.connect(lambda: self.playRequested.emit(self.station))
        layout.addWidget(play_btn)


class RadioView(QWidget):
    stationsFetched = Signal(list)

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 settings: dict, save_settings_fn, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.settings = settings
        self.save_settings_fn = save_settings_fn

        self.radio_query = ""
        self.radio_country_filter = "TR"
        self.radio_tag_filter = ""
        self.radio_show_favorites_only = False
        self._stations: list[dict] = []
        self._favorites: dict[str, dict] = {
            s.get("stationuuid"): s for s in settings.get("radio_favorites", [])
            if s.get("stationuuid")
        }

        # Radyo modunda ileri/geri tuşlarının listede gezinebilmesi için
        self.playback._radio_station_provider = lambda: self._stations

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        r_icon = QLabel()
        r_pm = icon_pixmap("radio", 22, "#00D2FF")
        if r_pm is not None:
            r_icon.setPixmap(r_pm)
        title_row.addWidget(r_icon)
        title = QLabel("Canlı Radyo")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        self.now_label = QLabel("Gerçek, canlı yayın yapan internet radyo kanalları")
        self.now_label.setObjectName("Muted")
        layout.addWidget(self.now_label)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İstasyon adı ara (ör. Kral FM)…")
        self.search_edit.returnPressed.connect(
            lambda: self.search_async(query=self.search_edit.text()))
        search_row.addWidget(self.search_edit, stretch=1)
        search_btn = QPushButton(" Ara")
        search_btn.setObjectName("Primary")
        search_btn.setIcon(vicon("search", 14, "#ffffff"))
        search_btn.setIconSize(QSize(14, 14))
        search_btn.clicked.connect(lambda: self.search_async(query=self.search_edit.text()))
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        self.chip_buttons: list[QPushButton] = []
        chips = [
            ("🇹🇷 Türkiye", lambda: self._set_country("TR")),
            ("🌍 Tüm Dünya", lambda: self._set_country("")),
            ("⭐ Favorilerim", self._toggle_favorites_view),
        ]
        for label, cmd in chips:
            btn = QPushButton(label)
            btn.setObjectName("Chip")
            btn.clicked.connect(cmd)
            filter_row.addWidget(btn)
            self.chip_buttons.append(btn)
        self._country_chips = (self.chip_buttons[0], self.chip_buttons[1])
        self._fav_chip = self.chip_buttons[2]
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        genre_row = QHBoxLayout()
        self._genre_chips: dict[str, QPushButton] = {}
        for genre in RADIO_GENRE_CHIPS:
            btn = QPushButton(genre.title())
            btn.setObjectName("Chip")
            btn.clicked.connect(lambda _=False, g=genre: self._set_tag(g))
            genre_row.addWidget(btn)
            self._genre_chips[genre] = btn
        genre_row.addStretch(1)
        layout.addLayout(genre_row)

        self.status_label = QLabel(
            "Henüz istasyon listelenmedi — ara ya da 🇹🇷/🌍 filtrelerinden birine bas.")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)

        self.stationsFetched.connect(self._on_fetched)
        self.playback.radioStarted.connect(self._on_radio_started)
        self.playback.radioStopped.connect(self._on_radio_stopped)

    # --- Filtreler ---
    def _set_country(self, country: str):
        self.radio_country_filter = country
        self.radio_tag_filter = ""
        self.radio_show_favorites_only = False
        self.search_async(country=country, tag="")

    def _set_tag(self, tag: str):
        self.radio_tag_filter = "" if self.radio_tag_filter == tag else tag
        self.radio_show_favorites_only = False
        self.search_async(tag=self.radio_tag_filter)

    def _toggle_favorites_view(self):
        self.radio_show_favorites_only = not self.radio_show_favorites_only
        self._render()

    def _chip_active_style(self, active: bool):
        return f"color: {'#FF7A3D' if active else 'palette(midlight)'}; font-weight: {'bold' if active else 'normal'};"

    def _refresh_chip_styles(self):
        self._country_chips[0].setStyleSheet(self._chip_active_style(
            self.radio_country_filter == "TR" and not self.radio_show_favorites_only))
        self._country_chips[1].setStyleSheet(self._chip_active_style(
            self.radio_country_filter == "" and not self.radio_show_favorites_only))
        self._fav_chip.setStyleSheet(self._chip_active_style(self.radio_show_favorites_only))
        for g, btn in self._genre_chips.items():
            btn.setStyleSheet(self._chip_active_style(
                self.radio_tag_filter == g and not self.radio_show_favorites_only))

    # --- Arama ---
    def search_async(self, query=None, country=None, tag=None):
        if query is not None:
            self.radio_query = query.strip()
        if country is not None:
            self.radio_country_filter = country
        if tag is not None:
            self.radio_tag_filter = tag
        self.radio_show_favorites_only = False
        self.status_label.setText("📡 İstasyonlar getiriliyor…")
        # Parametreler şimdi yakalanır; yavaş gelen ESKİ arama yeni aramanın
        # sonucunun üzerine yazmasın diye sıra numarası tutulur.
        self._search_seq = getattr(self, "_search_seq", 0) + 1
        seq = self._search_seq
        q, c, t = self.radio_query, self.radio_country_filter, self.radio_tag_filter

        def worker():
            try:
                stations = fetch_radio_stations(query=q, country=c, tag=t)
            except Exception as e:
                log.warning("Radyo istasyonları alınamadı: %s", e)
                stations = []
            if seq == self._search_seq:
                try:
                    self.stationsFetched.emit(stations)
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_fetched(self, stations: list):
        self._stations = stations or []
        if not self._stations:
            self.status_label.setText(
                "📡 İstasyon bulunamadı (internet bağlantını veya farklı bir arama terimini kontrol et).")
        else:
            self.status_label.setText(f"📡 {len(self._stations)} istasyon listelendi.")
        self._render()

    # --- Render ---
    def _render(self):
        self._refresh_chip_styles()
        self.list_widget.clear()

        current_uuid = self.playback.radio_playing.get("stationuuid") \
            if self.playback.radio_playing else None

        if self.radio_show_favorites_only:
            stations = list(self._favorites.values())
            if not stations:
                hint = QLabel("Henüz favori istasyonun yok. Bir istasyonun ☆ ikonuna tıkla.")
                hint.setObjectName("Muted")
                hint.setAlignment(Qt.AlignCenter)
                item = QListWidgetItem()
                item.setSizeHint(hint.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, hint)
                return
        else:
            stations = self._stations

        for station in stations:
            is_fav = station.get("stationuuid") in self._favorites
            row = _StationRow(station, station.get("stationuuid") == current_uuid, is_fav)
            row.playRequested.connect(self._play_station)
            row.favoriteToggled.connect(self._toggle_favorite)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

    def _play_station(self, station: dict):
        self.playback.play_radio_station(station)

    def _toggle_favorite(self, station: dict):
        uuid = station.get('stationuuid')
        if not uuid:
            return
        if uuid in self._favorites:
            del self._favorites[uuid]
        else:
            self._favorites[uuid] = station
        self.settings["radio_favorites"] = list(self._favorites.values())
        self.save_settings_fn()
        self._render()

    # --- Çalan istasyon bilgisi ---
    def _on_radio_started(self, station: dict):
        name = station.get("name", "?")
        self.now_label.setText(f"🔴 Şu an çalıyor: {name}")
        self._render()

    def _on_radio_stopped(self):
        self.now_label.setText("Gerçek, canlı yayın yapan internet radyo kanalları")
        self._render()

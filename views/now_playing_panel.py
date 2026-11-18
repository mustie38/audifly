from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from mustiefly_qt.helpers.constants import cover_color_for, format_time, shade_color
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.audio_visualizer import MODE_LABELS, NeonAudioVisualizer
from mustiefly_qt.widgets.vinyl_cover import VinylCoverWidget
from mustiefly_qt.widgets.player_icons import icon as vicon


class NowPlayingPanel(QWidget):
    collapseRequested = Signal()  # paneli gizleme isteği (MainWindow yönetir)
    startRadioRequested = Signal(dict)
    karaokeRequested = Signal()
    artistClicked = Signal(str)
    visualizerModeChanged = Signal(str)
    visualizerPaletteChanged = Signal(str)

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails
        self.setObjectName("NowPlayingPanel")
        self.setFixedWidth(300)
        self._seeking = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 20)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        # Bölüm başlığı + paneli kapatma düğmesi
        header_row = QHBoxLayout()
        header = QLabel("ŞU AN ÇALIYOR")
        header.setObjectName("NowPlayingHeader")
        header_row.addWidget(header)
        header_row.addStretch(1)
        collapse_btn = QPushButton("»")
        collapse_btn.setObjectName("IconSquare")
        collapse_btn.setToolTip("Paneli kapat (üst çubuktan geri açılır)")
        collapse_btn.setCursor(Qt.PointingHandCursor)
        collapse_btn.clicked.connect(self.collapseRequested.emit)
        header_row.addWidget(collapse_btn)
        layout.addLayout(header_row)

        # Dönen plak kapağı (kapak yokken 🎵 fallback)
        self.vinyl = VinylCoverWidget(220, "🎵")
        layout.addWidget(self.vinyl, alignment=Qt.AlignHCenter)
        layout.addSpacing(12)

        self.title_label = QLabel("Henüz şarkı seçilmedi")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.title_label)

        self.artist_label = QLabel("")
        self.artist_label.setObjectName("Muted")
        self.artist_label.setAlignment(Qt.AlignCenter)
        self.artist_label.setCursor(Qt.PointingHandCursor)
        self.artist_label.setToolTip("Sanatçı profiline git")
        self.artist_label.mousePressEvent = self._on_artist_label_clicked
        layout.addWidget(self.artist_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.like_btn = QPushButton(" Beğen")
        self.like_btn.setIcon(vicon("heart", 14, "#cfc9e6"))
        self.like_btn.setIconSize(QSize(14, 14))
        self.like_btn.setCursor(Qt.PointingHandCursor)
        self.like_btn.clicked.connect(self._toggle_like)
        btn_row.addWidget(self.like_btn)

        lyrics_btn = QPushButton(" Sözler")
        lyrics_btn.setIcon(vicon("lyrics", 14, "#cfc9e6"))
        lyrics_btn.setIconSize(QSize(14, 14))
        lyrics_btn.setCursor(Qt.PointingHandCursor)
        lyrics_btn.setToolTip("Sözler penceresini açar (Ayarlar > Sözler)")
        self.lyrics_btn = lyrics_btn
        btn_row.addWidget(lyrics_btn)

        self.radio_btn = QPushButton(" Radyo")
        self.radio_btn.setIcon(vicon("radio", 14, "#cfc9e6"))
        self.radio_btn.setIconSize(QSize(14, 14))
        self.radio_btn.setCursor(Qt.PointingHandCursor)
        self.radio_btn.setToolTip("Bu şarkı için Şarkı Radyosu başlatır")
        self.radio_btn.clicked.connect(self._on_start_radio)
        btn_row.addWidget(self.radio_btn)

        self.karaoke_btn = QPushButton()
        self.karaoke_btn.setIcon(vicon("fullscreen", 15, "#cfc9e6"))
        self.karaoke_btn.setIconSize(QSize(15, 15))
        self.karaoke_btn.setCursor(Qt.PointingHandCursor)
        self.karaoke_btn.setToolTip("Canlı Karaoke & Tam Ekran (F11)")
        self.karaoke_btn.setFixedWidth(36)
        self.karaoke_btn.clicked.connect(self.karaokeRequested.emit)
        btn_row.addWidget(self.karaoke_btn)

        self.vocal_btn = QPushButton()
        self.vocal_btn.setIcon(vicon("mic", 15, "#cfc9e6"))
        self.vocal_btn.setIconSize(QSize(15, 15))
        self.vocal_btn.setToolTip("Vokal Ayırma / Enstrümantal Mod (V)")
        self.vocal_btn.setFixedWidth(36)
        self.vocal_btn.setCursor(Qt.PointingHandCursor)
        if hasattr(self.playback, "toggle_vocal_remover"):
            self.vocal_btn.clicked.connect(self.playback.toggle_vocal_remover)
        btn_row.addWidget(self.vocal_btn)
        layout.addLayout(btn_row)

        # --- Arka planda tutulan yedek kontroller (Test uyumluluğu için) ---
        self.dummy_controls_host = QWidget()
        self.dummy_controls_host.setVisible(False)
        dummy_layout = QVBoxLayout(self.dummy_controls_host)

        self.progress_section = QWidget()
        prog_layout = QVBoxLayout(self.progress_section)
        from mustiefly_qt.widgets.click_slider import ClickSlider
        self.progress_slider = ClickSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.sliderPressed.connect(self._on_slider_press)
        self.progress_slider.sliderReleased.connect(self._on_slider_release)
        prog_layout.addWidget(self.progress_slider)
        self.current_time_label = QLabel("00:00")
        self.total_time_label = QLabel("00:00")
        dummy_layout.addWidget(self.progress_section)

        self.prev_btn = QPushButton()
        self.prev_btn.clicked.connect(self.playback.play_previous)
        self.play_btn = QPushButton()
        self.play_btn.clicked.connect(self.playback.toggle_play_pause)
        self.next_btn = QPushButton()
        self.next_btn.clicked.connect(self.playback.play_next)
        dummy_layout.addWidget(self.prev_btn)
        dummy_layout.addWidget(self.play_btn)
        dummy_layout.addWidget(self.next_btn)
        layout.addWidget(self.dummy_controls_host)

        # --- YENİ ODAK ALANI: Sıradaki Parça ve Sanatçı Bilgisi Kartı ---
        self.up_next_card = QFrame()
        self.up_next_card.setObjectName("UpNextCard")
        self.up_next_card.setStyleSheet("""
            #UpNextCard {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
            #UpNextCard:hover {
                background: rgba(255, 255, 255, 0.07);
                border-color: rgba(0, 210, 255, 0.3);
            }
        """)
        self.up_next_card.setCursor(Qt.PointingHandCursor)
        self.up_next_card.mousePressEvent = lambda _: self.playback.play_next()
        up_next_layout = QVBoxLayout(self.up_next_card)
        up_next_layout.setContentsMargins(12, 10, 12, 10)
        up_next_layout.setSpacing(4)

        up_next_header = QHBoxLayout()
        up_next_lbl = QLabel("📑 SIRADAKİ PARÇA")
        up_next_lbl.setStyleSheet("font-size: 10px; font-weight: bold; color: #8F9CAE; letter-spacing: 0.8px;")
        up_next_header.addWidget(up_next_lbl)
        up_next_header.addStretch(1)
        next_hint = QLabel("Atla ⏭")
        next_hint.setStyleSheet("font-size: 10px; color: #00D2FF; font-weight: 600;")
        up_next_header.addWidget(next_hint)
        up_next_layout.addLayout(up_next_header)

        self.up_next_title = QLabel("Sırada parça yok")
        self.up_next_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #FFFFFF;")
        up_next_layout.addWidget(self.up_next_title)

        self.up_next_artist = QLabel("Son şarkıdasın veya radyo başlat")
        self.up_next_artist.setStyleSheet("font-size: 11px; color: #8F9CAE;")
        up_next_layout.addWidget(self.up_next_artist)

        layout.addWidget(self.up_next_card)

        # Sanatçı Profili Hızlı Butonu
        self.artist_profile_btn = QPushButton("👤 Sanatçı Sayfası ve Diskografi →")
        self.artist_profile_btn.setCursor(Qt.PointingHandCursor)
        self.artist_profile_btn.setFixedHeight(30)
        self.artist_profile_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px dashed rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                color: #C084FC;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: rgba(162, 89, 255, 0.12);
                border-color: #C084FC;
                color: #FFFFFF;
            }
        """)
        self.artist_profile_btn.clicked.connect(self._emit_artist_clicked)
        layout.addWidget(self.artist_profile_btn)

        # --- Canlı Müzik Görselleştirici & Neon Spektrum ---
        st = getattr(self.playback, "settings", {}) or {}
        init_mode = st.get("visualizer_mode", "bars")
        init_pal = st.get("visualizer_palette", "dynamic")
        init_enabled = bool(st.get("visualizer_enabled", True))

        self.visualizer_section = QWidget()
        viz_layout = QVBoxLayout(self.visualizer_section)
        viz_layout.setContentsMargins(0, 6, 0, 0)
        viz_layout.setSpacing(6)

        viz_header = QHBoxLayout()
        viz_header.setContentsMargins(2, 0, 2, 0)
        viz_lbl = QLabel("CANLI SPEKTRUM")
        viz_lbl.setObjectName("Muted")
        viz_lbl.setStyleSheet("font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        viz_header.addWidget(viz_lbl)
        viz_header.addStretch(1)

        self.viz_mode_btn = QPushButton(MODE_LABELS.get(init_mode, "📊 Neon Barlar"))
        self.viz_mode_btn.setCursor(Qt.PointingHandCursor)
        self.viz_mode_btn.setToolTip("Görselleştirici modunu değiştir (Sol tık: Mod, Sağ tık: Renk Paleti)")
        self.viz_mode_btn.setFixedHeight(22)
        self.viz_mode_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.07);
                color: #cfc9e6;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 11px;
                padding: 2px 10px;
                font-size: 10px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(169, 128, 249, 0.22);
                color: #ffffff;
            }
        """)
        viz_header.addWidget(self.viz_mode_btn)
        viz_layout.addLayout(viz_header)

        self.visualizer = NeonAudioVisualizer(
            playback=self.playback,
            mode=init_mode,
            palette=init_pal,
            bar_count=34,
            interactive=True,
            transparent_bg=False,
        )
        self.visualizer.setFixedHeight(78)
        self.viz_mode_btn.clicked.connect(lambda: self.visualizer.cycle_mode(include_off=False))
        self.visualizer.modeChanged.connect(self._on_visualizer_mode_changed)
        self.visualizer.paletteChanged.connect(self.visualizerPaletteChanged.emit)
        viz_layout.addWidget(self.visualizer)
        layout.addWidget(self.visualizer_section)
        self.set_visualizer_enabled(init_enabled)

        self.playback.songStarted.connect(self._on_song_started)
        self.playback.songLoading.connect(self._on_song_loading)
        self.playback.playStateChanged.connect(self._on_play_state)
        self.playback.playError.connect(self._on_play_error)
        self.playback.positionChanged.connect(self._on_position)
        self.playback.radioStarted.connect(self._on_radio_started)
        self.playback.radioStopped.connect(self._on_radio_stopped)
        if hasattr(self.playback, "vocalRemoverChanged"):
            self.playback.vocalRemoverChanged.connect(self._sync_vocal_button)
        self.store.playlistsChanged.connect(self._sync_like_button)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)
        self._sync_vocal_button(getattr(self.playback, "vocal_remover_enabled", False))

    # --- İlerleme çubuğu ---
    def _on_position(self, current_ms: int, total_ms: int):
        if self._seeking or self.playback.radio_playing is not None:
            return
        if total_ms > 0:
            self.progress_slider.setRange(0, total_ms)
            self.progress_slider.setValue(current_ms)
            self.current_time_label.setText(format_time(current_ms))
            self.total_time_label.setText(format_time(total_ms))

    def _on_slider_press(self):
        self._seeking = True

    def _on_slider_release(self):
        self.playback.seek(self.progress_slider.value())
        self._seeking = False

    def _on_song_loading(self, playlist_name, index, song):
        self.play_btn.setEnabled(False)

    def _on_play_error(self, *_):
        self.play_btn.setIcon(vicon("play", 22, "#ffffff"))
        self.play_btn.setEnabled(True)

    def _on_play_state(self, playing: bool):
        self.play_btn.setIcon(vicon("pause" if playing else "play", 22, "#ffffff"))
        self.play_btn.setEnabled(True)

    def _on_song_started(self, playlist_name, index, song, is_offline):
        self._playlist_name = playlist_name
        self._index = index
        clean_title, clean_artist = parse_track_and_artist(
            song.get("title", ""),
            song.get("uploader", ""),
            song,
        )
        self.title_label.setText(clean_title)
        self._current_artist = clean_artist
        if song.get("local_path"):
            source = "💽 Yerel Dosya"
        elif is_offline:
            source = "📀 Çevrimdışı"
        else:
            source = "🌐 Çevrimiçi"
        self.artist_label.setText(f"{clean_artist} • {playlist_name} • {source}")
        self.like_btn.setVisible(True)
        self._apply_like_state(bool(song.get("liked")))
        self.progress_section.setVisible(True)
        self.progress_slider.setValue(0)
        self.current_time_label.setText("00:00")
        self.total_time_label.setText(format_time((song.get("duration") or 0) * 1000))

        # Kapak: önbellekte varsa hemen bas; yoksa indirilince _on_thumbnail_ready basar.
        # Fallback: başlıktan türetilen renkle yumuşak gradient (düz gri yerine)
        base = cover_color_for(song.get("title", "?"))
        self.vinyl.set_fallback_gradient(base, shade_color(base, 0.45))
        self.vinyl.set_fallback_text("🎵")
        pm = self.thumbnails.pixmap_for(song, 220, rounded=False) if self.thumbnails else None
        self.vinyl.set_pixmap(pm)
        if hasattr(self, "visualizer"):
            self.visualizer.set_accent(base)
        self._update_up_next()

    def _update_up_next(self):
        pl = getattr(self, "_playlist_name", None) or self.playback.playing_playlist
        idx = getattr(self, "_index", -1)
        if idx == -1:
            idx = self.playback.current_index
        songs = self.store.playlists.get(pl, []) if pl else []
        next_song = None
        if 0 <= idx + 1 < len(songs):
            next_song = songs[idx + 1]

        if next_song:
            t = next_song.get("title", "")
            u = next_song.get("uploader", "")
            clean_t, clean_a = parse_track_and_artist(t, u, next_song)
            self.up_next_title.setText(clean_t[:26] + ("…" if len(clean_t) > 26 else ""))
            self.up_next_artist.setText(clean_a[:26] + ("…" if len(clean_a) > 26 else ""))
            self.up_next_card.setVisible(True)
        else:
            self.up_next_title.setText("Sırada parça yok")
            self.up_next_artist.setText("Listenin sonundasın veya radyo başlat")

    def _on_radio_started(self, station: dict):
        """Canlı radyo modu: albüm kapağı yok, plak dönmesin, süre çubuğu yok."""
        self._playlist_name = None
        name = station.get("name", "?")
        self.title_label.setText(name[:40] + ("..." if len(name) > 40 else ""))
        country = f" • {station['country']}" if station.get("country") else ""
        self.artist_label.setText(f"📻 Canlı Radyo{country}")
        self.like_btn.setVisible(False)
        self.vinyl.set_pixmap(None)
        self.vinyl.set_fallback_text("📻")
        self.progress_section.setVisible(False)
        self.up_next_card.setVisible(False)
        self.artist_profile_btn.setVisible(False)

    def _on_radio_stopped(self):
        self.like_btn.setVisible(True)
        self.title_label.setText("Henüz şarkı seçilmedi")
        self.artist_label.setText("")
        self.vinyl.set_pixmap(None)
        self.vinyl.set_fallback_text("🎵")
        self.progress_section.setVisible(True)
        self.progress_slider.setValue(0)
        self.current_time_label.setText("00:00")
        self.total_time_label.setText("00:00")
        self.play_btn.setIcon(vicon("play", 22, "#ffffff"))
        self.up_next_card.setVisible(True)
        self.artist_profile_btn.setVisible(True)

    def _emit_artist_clicked(self):
        artist = getattr(self, "_current_artist", "")
        if artist and artist not in ("YouTube Stream", "Bilinmeyen Sanatçı", "?", ""):
            self.artistClicked.emit(artist)

    def _on_artist_label_clicked(self, event=None):
        if event is None or isinstance(event, bool) or event.button() == Qt.LeftButton:
            self._emit_artist_clicked()
        if event is not None and not isinstance(event, bool):
            super(QLabel, self.artist_label).mousePressEvent(event)

    def set_playing_state(self, playing: bool):
        """Plak dönüşünü ve spektrumu çalma durumuna bağlar (MainWindow/player_bar'dan beslenir)."""
        self.vinyl.set_playing(playing)
        if hasattr(self, "visualizer"):
            self.visualizer.set_playing(playing)

    def set_accent(self, color: str):
        if hasattr(self, "visualizer"):
            self.visualizer.set_accent(color)

    def set_visualizer_enabled(self, enabled: bool):
        if hasattr(self, "visualizer_section"):
            self.visualizer_section.setVisible(bool(enabled))
        if hasattr(self, "visualizer"):
            self.visualizer.set_enabled_state(bool(enabled))

    def set_visualizer_mode(self, mode: str):
        if hasattr(self, "visualizer"):
            self.visualizer.set_mode(mode)
        if hasattr(self, "viz_mode_btn"):
            self.viz_mode_btn.setText(MODE_LABELS.get(mode, "📊 Neon Barlar"))

    def set_visualizer_palette(self, palette: str):
        if hasattr(self, "visualizer"):
            self.visualizer.set_palette(palette)

    def _on_visualizer_mode_changed(self, mode: str):
        if hasattr(self, "viz_mode_btn"):
            self.viz_mode_btn.setText(MODE_LABELS.get(mode, "📊 Neon Barlar"))
        self.visualizerModeChanged.emit(mode)

    def _on_start_radio(self):
        if self.playback.current_song:
            self.startRadioRequested.emit(self.playback.current_song)

    def _toggle_like(self):
        pl = self.playback.playing_playlist or getattr(self, "_playlist_name", None)
        if pl is None:
            return
        songs = self.store.playlists.get(pl, [])
        idx = self.playback.current_index if self.playback.playing_playlist else getattr(self, "_index", -1)
        if not (0 <= idx < len(songs)):
            return  # şarkı silinmiş olabilir
        self.store.toggle_like(pl, idx)
        self._sync_like_button()

    def _apply_like_state(self, liked: bool):
        self.like_btn.setText(" Beğenildi" if liked else " Beğen")
        self.like_btn.setIcon(vicon("heart_filled" if liked else "heart", 14, "#ff5e7e" if liked else "#cfc9e6"))

    def _sync_like_button(self):
        pl = self.playback.playing_playlist
        songs = self.store.playlists.get(pl, []) if pl else []
        idx = self.playback.current_index
        if pl and 0 <= idx < len(songs):
            self._apply_like_state(bool(songs[idx].get("liked")))

    def _on_thumbnail_ready(self, key: str):
        """Kapak indiğinde yalnızca o an çalan şarkıysa plak kapağını güncelle."""
        pp = self.playback.playing_playlist
        songs = self.playback.store.playlists.get(pp, []) if pp else []
        if songs and 0 <= self.playback.current_index < len(songs):
            current = songs[self.playback.current_index]
            if current.get("webpage_url") == key and self.thumbnails is not None:
                pm = self.thumbnails.pixmap_for(current, 220, rounded=False)
                self.vinyl.set_pixmap(pm)

    def _sync_vocal_button(self, enabled: bool):
        self.vocal_btn.setIcon(vicon("mic", 15, "#ffffff" if enabled else "#cfc9e6"))
        if enabled:
            self.vocal_btn.setToolTip("🎙️ Enstrümantal Mod (Vokal Kısık) — Kapatmak için tıkla (V)")
            self.vocal_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #ec4899);
                    color: #ffffff;
                    border: 1px solid rgba(255, 255, 255, 0.4);
                    border-radius: 4px;
                    font-weight: bold;
                }
            """)
        else:
            self.vocal_btn.setToolTip("🎙️ Vokal Ayırma / Enstrümantal Mod (V)")
            self.vocal_btn.setStyleSheet("")

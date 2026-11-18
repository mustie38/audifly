# mustiefly_qt/views/mini_player.py
"""Elit, Modern Vektör İkonlu Mini Oynatıcı (Always-on-Top Mini Player)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME, cover_color_for, format_time
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.click_slider import ClickSlider
from mustiefly_qt.widgets.player_icons import icon as vicon


class MiniPlayer(QWidget):
    closed = Signal()  # mini kapatılınca ana pencerenin geri gelmesi için

    def __init__(
        self,
        playback: PlaybackEngine,
        parent=None,
        thumbnails: ThumbnailService | None = None,
    ):
        super().__init__(parent)
        self.playback = playback
        self.thumbnails = thumbnails
        self._seeking = False
        self._accent = "#a980f9"

        self.setWindowTitle(f"{APP_DISPLAY_NAME} Mini")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setFixedSize(376, 158)
        self.setObjectName("MiniPlayerWindow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#MiniPlayerWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #151226, stop:1 #0b0915);
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # --- ÜST SATIR: Kapak + Başlık/Sanatçı + Beğen & Genişlet ---
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.cover_label = QLabel("♪")
        self.cover_label.setFixedSize(52, 52)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet(
            "background: rgba(169, 128, 249, 0.18); color: #ffffff; "
            "border-radius: 12px; font-size: 20px; font-weight: bold;"
        )
        cov_shadow = QGraphicsDropShadowEffect(self.cover_label)
        cov_shadow.setBlurRadius(16)
        cov_shadow.setOffset(0, 4)
        cov_shadow.setColor(QColor(0, 0, 0, 150))
        self.cover_label.setGraphicsEffect(cov_shadow)
        top_row.addWidget(self.cover_label)

        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 2, 0, 2)
        info_col.setSpacing(2)

        self.title_label = QLabel("Şarkı çalınmıyor")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #ffffff; background: transparent;")
        info_col.addWidget(self.title_label)

        self.artist_label = QLabel("Hazır")
        self.artist_label.setObjectName("Muted")
        self.artist_label.setStyleSheet("color: #b7b2cf; font-size: 11px; background: transparent;")
        info_col.addWidget(self.artist_label)
        info_col.addStretch(1)
        top_row.addLayout(info_col, stretch=1)

        # Sağ üst eylem butonları (Beğen + Normal Pencereye Dön)
        top_actions = QHBoxLayout()
        top_actions.setSpacing(6)

        self.like_btn = QPushButton()
        self.like_btn.setFixedSize(30, 30)
        self.like_btn.setCursor(Qt.PointingHandCursor)
        self.like_btn.setToolTip("Beğen")
        self.like_btn.setIcon(vicon("heart", 15, "#cfc9e6"))
        self.like_btn.setIconSize(QSize(15, 15))
        self.like_btn.setStyleSheet(self._circle_btn_qss(30))
        self.like_btn.clicked.connect(self._toggle_like)
        top_actions.addWidget(self.like_btn, alignment=Qt.AlignTop)

        self.expand_btn = QPushButton()
        self.expand_btn.setFixedSize(30, 30)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setToolTip("Tam pencereye dön")
        self.expand_btn.setIcon(vicon("expand", 15, "#cfc9e6"))
        self.expand_btn.setIconSize(QSize(15, 15))
        self.expand_btn.setStyleSheet(self._circle_btn_qss(30))
        self.expand_btn.clicked.connect(self.close)
        top_actions.addWidget(self.expand_btn, alignment=Qt.AlignTop)

        top_row.addLayout(top_actions)
        root.addLayout(top_row)

        # --- ORTA SATIR: Süre Çubuğu (Progress Bar) ---
        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)

        self.curr_time_label = QLabel("00:00")
        self.curr_time_label.setStyleSheet("color: rgba(255,255,255,0.48); font-size: 10px;")
        self.curr_time_label.setFixedWidth(30)
        prog_row.addWidget(self.curr_time_label)

        self.progress_slider = ClickSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setFixedHeight(14)
        self.progress_slider.setStyleSheet(self._slider_qss(self._accent))
        self.progress_slider.sliderPressed.connect(self._on_slider_press)
        self.progress_slider.sliderReleased.connect(self._on_slider_release)
        prog_row.addWidget(self.progress_slider, stretch=1)

        self.total_time_label = QLabel("00:00")
        self.total_time_label.setStyleSheet("color: rgba(255,255,255,0.48); font-size: 10px;")
        self.total_time_label.setFixedWidth(30)
        self.total_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prog_row.addWidget(self.total_time_label)

        root.addLayout(prog_row)

        # --- ALT SATIR: Elit Vektör Oynatma Kontrolleri ---
        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addStretch(1)

        self.shuffle_btn = QPushButton()
        self.shuffle_btn.setFixedSize(30, 30)
        self.shuffle_btn.setCursor(Qt.PointingHandCursor)
        self.shuffle_btn.setToolTip("Karışık Çal")
        self.shuffle_btn.setIcon(vicon("shuffle", 14, "#cfc9e6"))
        self.shuffle_btn.setIconSize(QSize(14, 14))
        self.shuffle_btn.setStyleSheet(self._circle_btn_qss(30))
        if hasattr(self.playback, "toggle_shuffle"):
            self.shuffle_btn.clicked.connect(self.playback.toggle_shuffle)
        controls.addWidget(self.shuffle_btn)

        self.prev_btn = QPushButton()
        self.prev_btn.setFixedSize(34, 34)
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.setToolTip("Önceki Şarkı")
        self.prev_btn.setIcon(vicon("prev", 16, "#ffffff"))
        self.prev_btn.setIconSize(QSize(16, 16))
        self.prev_btn.setStyleSheet(self._circle_btn_qss(34))
        self.prev_btn.clicked.connect(self.playback.play_previous)
        controls.addWidget(self.prev_btn)

        self.play_btn = QPushButton()
        self.play_btn.setFixedSize(42, 42)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip("Oynat / Duraklat")
        self.play_btn.setIcon(vicon("play", 18, "#ffffff"))
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setStyleSheet(self._play_btn_qss(self._accent))
        self.play_btn.clicked.connect(self.playback.toggle_play_pause)
        controls.addWidget(self.play_btn)

        self.next_btn = QPushButton()
        self.next_btn.setFixedSize(34, 34)
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setToolTip("Sonraki Şarkı")
        self.next_btn.setIcon(vicon("next", 16, "#ffffff"))
        self.next_btn.setIconSize(QSize(16, 16))
        self.next_btn.setStyleSheet(self._circle_btn_qss(34))
        self.next_btn.clicked.connect(self.playback.play_next)
        controls.addWidget(self.next_btn)

        self.vocal_btn = QPushButton()
        self.vocal_btn.setFixedSize(30, 30)
        self.vocal_btn.setCursor(Qt.PointingHandCursor)
        self.vocal_btn.setToolTip("Vokal Ayırma / Enstrümantal Mod (V)")
        self.vocal_btn.setIcon(vicon("mic", 14, "#cfc9e6"))
        self.vocal_btn.setIconSize(QSize(14, 14))
        self.vocal_btn.setStyleSheet(self._circle_btn_qss(30))
        if hasattr(self.playback, "toggle_vocal_remover"):
            self.vocal_btn.clicked.connect(self.playback.toggle_vocal_remover)
        controls.addWidget(self.vocal_btn)

        controls.addStretch(1)
        root.addLayout(controls)

        # Sinyal bağlantıları
        self.playback.songStarted.connect(self._on_song_started)
        self.playback.playStateChanged.connect(self._on_play_state)
        self.playback.radioStarted.connect(self._on_radio_started)
        self.playback.radioStopped.connect(self._on_radio_stopped)
        if hasattr(self.playback, "positionChanged"):
            self.playback.positionChanged.connect(self._on_position)
        if hasattr(self.playback, "shuffleChanged"):
            self.playback.shuffleChanged.connect(self._sync_shuffle)
        if hasattr(self.playback, "vocalRemoverChanged"):
            self.playback.vocalRemoverChanged.connect(self._sync_vocal)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    @staticmethod
    def _circle_btn_qss(size: int, active_bg: str = "rgba(255, 255, 255, 0.07)") -> str:
        r = size // 2
        return f"""
            QPushButton {{
                background: {active_bg};
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: {r}px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.18);
                border-color: rgba(255, 255, 255, 0.28);
            }}
            QPushButton:pressed {{
                background: rgba(255, 255, 255, 0.25);
            }}
        """

    @staticmethod
    def _play_btn_qss(accent: str) -> str:
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {accent}, stop:1 #7c3aed);
                border: 1px solid rgba(255, 255, 255, 0.28);
                border-radius: 21px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #b996fb, stop:1 #8b5cf6);
                border-color: rgba(255, 255, 255, 0.5);
            }}
        """

    @staticmethod
    def _slider_qss(accent: str) -> str:
        return f"""
            QSlider::groove:horizontal {{
                height: 4px;
                background: rgba(255, 255, 255, 0.14);
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {accent};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 10px;
                height: 10px;
                margin: -3px 0;
                background: #ffffff;
                border-radius: 5px;
            }}
        """

    def _on_song_started(self, playlist_name, index, song, is_offline):
        clean_title, clean_artist = parse_track_and_artist(
            song.get("title", "Bilinmeyen Şarkı"),
            song.get("uploader", ""),
            song,
        )
        fm_t = QFontMetrics(self.title_label.font())
        fm_a = QFontMetrics(self.artist_label.font())
        self.title_label.setText(fm_t.elidedText(clean_title, Qt.ElideRight, 200))
        self.artist_label.setText(fm_a.elidedText(clean_artist, Qt.ElideRight, 200))
        self._on_play_state(True)
        self._sync_like(song)
        self._update_cover(song, clean_title)
        dur_ms = int((song.get("duration") or 0) * 1000)
        self.total_time_label.setText(format_time(dur_ms))

    def _update_cover(self, song: dict, clean_title: str):
        pm = self.thumbnails.pixmap_for(song, 52, radius=12, rounded=True) if self.thumbnails else None
        if pm is not None and not pm.isNull():
            self.cover_label.setText("")
            self.cover_label.setPixmap(pm)
            self.cover_label.setStyleSheet("border-radius: 12px; background: transparent;")
        else:
            col = cover_color_for(clean_title)
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("♪")
            self.cover_label.setStyleSheet(
                f"background: {col}; color: #ffffff; border-radius: 12px; font-size: 20px; font-weight: bold;"
            )

    def _on_thumbnail_ready(self, key: str):
        song = getattr(self.playback, "current_song", None)
        if isinstance(song, dict) and song.get("webpage_url") == key:
            clean_t, _ = parse_track_and_artist(song.get("title", ""), song.get("uploader", ""), song)
            self._update_cover(song, clean_t)

    def _on_radio_started(self, station: dict):
        name = station.get("name", "Radyo")
        fm_t = QFontMetrics(self.title_label.font())
        self.title_label.setText(fm_t.elidedText(name, Qt.ElideRight, 200))
        self.artist_label.setText("Canlı Radyo Yayını")
        self.cover_label.setPixmap(QPixmap())
        self.cover_label.setText("")
        self.cover_label.setPixmap(vicon("radio", 24, "#ffffff").pixmap(24, 24))
        self._on_play_state(True)

    def _on_radio_stopped(self):
        self.title_label.setText("Şarkı çalınmıyor")
        self.artist_label.setText("Hazır")
        self.cover_label.setPixmap(QPixmap())
        self.cover_label.setText("♪")
        self._on_play_state(False)

    def _on_play_state(self, playing: bool):
        self.play_btn.setIcon(vicon("pause" if playing else "play", 18, "#ffffff"))

    def _on_position(self, current_ms: int, total_ms: int):
        if self._seeking or getattr(self.playback, "radio_playing", None) is not None:
            return
        if total_ms > 0:
            self.progress_slider.setRange(0, total_ms)
            self.progress_slider.setValue(current_ms)
            self.curr_time_label.setText(format_time(current_ms))
            self.total_time_label.setText(format_time(total_ms))

    def _on_slider_press(self):
        self._seeking = True

    def _on_slider_release(self):
        if hasattr(self.playback, "seek"):
            self.playback.seek(self.progress_slider.value())
        self._seeking = False

    def _toggle_like(self):
        pl = getattr(self.playback, "playing_playlist", None)
        idx = getattr(self.playback, "current_index", -1)
        store = getattr(self.playback, "store", None)
        if pl and idx >= 0 and store is not None:
            store.toggle_like(pl, idx)
            self._sync_like(getattr(self.playback, "current_song", None))

    def _sync_like(self, song: dict | None):
        liked = bool(song and song.get("liked"))
        self.like_btn.setIcon(
            vicon("heart_filled" if liked else "heart", 15, "#ff5e7e" if liked else "#cfc9e6")
        )

    def _sync_shuffle(self, enabled: bool):
        self.shuffle_btn.setIcon(vicon("shuffle", 14, self._accent if enabled else "#cfc9e6"))

    def _sync_vocal(self, enabled: bool):
        self.vocal_btn.setIcon(vicon("mic", 14, "#ec4899" if enabled else "#cfc9e6"))

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        station = getattr(self.playback, "radio_playing", None)
        song = getattr(self.playback, "current_song", None)
        playing = bool(getattr(self.playback, "is_playing", False))
        if isinstance(station, dict):
            self._on_radio_started(station)
            self._on_play_state(playing)
        elif isinstance(song, dict):
            self._on_song_started("", 0, song, False)
            self._on_play_state(playing)
        self._sync_shuffle(bool(getattr(self.playback, "shuffle_mode", False)))
        self._sync_vocal(bool(getattr(self.playback, "vocal_remover_enabled", False)))

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)

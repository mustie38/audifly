# mustiefly_qt/views/mini_player.py
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine


class MiniPlayer(QWidget):
    closed = Signal()  # mini kapatılınca ana pencerenin geri gelmesi için

    def __init__(self, playback: PlaybackEngine, parent=None):
        super().__init__(parent)
        self.playback = playback
        self.setWindowTitle(f"{APP_DISPLAY_NAME} Mini")
        # Her zaman üstte kalmasını (always-on-top) sağlayan Qt bayrağı
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setFixedSize(320, 130)
        self.setObjectName("Card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)

        top_row = QHBoxLayout()
        self.title_label = QLabel("Şarkı çalınmıyor")
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        top_row.addWidget(self.title_label, stretch=1)

        expand_btn = QPushButton("⤢")
        expand_btn.setToolTip("Normal pencereye dön")
        expand_btn.setFixedWidth(28)
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.clicked.connect(self.close)
        top_row.addWidget(expand_btn)
        layout.addLayout(top_row)

        self.artist_label = QLabel("")
        self.artist_label.setObjectName("Muted")
        self.artist_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.artist_label)

        controls = QHBoxLayout()
        self.prev_btn = QPushButton("⏮")
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(self.playback.play_previous)
        controls.addWidget(self.prev_btn)

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self.playback.toggle_play_pause)
        controls.addWidget(self.play_btn)

        self.next_btn = QPushButton("⏭")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(self.playback.play_next)
        controls.addWidget(self.next_btn)

        layout.addLayout(controls)

        # Sinyal bağlantıları
        self.playback.songStarted.connect(self._on_song_started)
        self.playback.playStateChanged.connect(self._on_play_state)
        self.playback.radioStarted.connect(self._on_radio_started)
        self.playback.radioStopped.connect(self._on_radio_stopped)

    def _on_song_started(self, playlist_name, index, song, is_offline):
        clean_title, clean_artist = parse_track_and_artist(
            song.get("title", "Bilinmeyen Şarkı"),
            song.get("uploader", ""),
            song,
        )
        self.title_label.setText(clean_title[:35] + "…" if len(clean_title) > 35 else clean_title)
        self.artist_label.setText(clean_artist)
        self.play_btn.setText("⏸")

    def _on_radio_started(self, station: dict):
        name = station.get("name", "Radyo")
        self.title_label.setText(name[:35] + "…" if len(name) > 35 else name)
        self.artist_label.setText("📻 Canlı Radyo")
        self.play_btn.setText("⏸")

    def _on_radio_stopped(self):
        self.title_label.setText("Şarkı çalınmıyor")
        self.artist_label.setText("")
        self.play_btn.setText("▶")

    def _on_play_state(self, playing: bool):
        self.play_btn.setText("⏸" if playing else "▶")

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)

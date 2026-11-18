"""
Masaüstü Şeffaf Widget Modu (Rainmeter Tarzı) — DesktopWidget.

Pencere çerçevesi ve görev çubuğu simgesi olmadan masaüstünde süzülen,
yarı saydam cam efektli (glassmorphism) müzik widget'ı:
  - Kapak görseli + Şarkı adı + Sanatçı + Canlı İnce Neon Spektrum
  - Boştayken ultra sade Rainmeter görünümü; üzerine gelince (hover) kontrol butonları
  - Sürükleyerek konumlandırma + konumu ayarlara kaydetme
  - Sağ tık menüsü: Her Zaman Üstte, Konumu Kilitle, Stil (Cam/Ultra Şeffaf/Neon), Kapat
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMenu,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.audio_visualizer import NeonAudioVisualizer
from mustiefly_qt.widgets.player_icons import icon as vicon


STYLE_GLASS = "glass"
STYLE_MINIMAL = "minimal"
STYLE_NEON = "neon"

COVER_SIZE = 64
COVER_RADIUS = 12


class DesktopWidget(QWidget):
    """Rainmeter tarzı yarı saydam masaüstü müzik widget'ı."""

    closed = Signal()

    def __init__(
        self,
        playback: PlaybackEngine,
        thumbnails: ThumbnailService | None = None,
        settings: dict | None = None,
        save_settings_fn=None,
        parent=None,
    ):
        super().__init__(parent)
        self.playback = playback
        self.thumbnails = thumbnails
        self.settings = settings if settings is not None else {}
        self._save_settings = save_settings_fn

        self._drag_offset: QPoint | None = None
        self._current_key: str | None = None
        self._accent = "#a980f9"
        self._locked = bool(self.settings.get("desktop_widget_locked", False))
        self._always_on_top = bool(self.settings.get("desktop_widget_on_top", False))
        self._style_mode = self.settings.get("desktop_widget_style", STYLE_GLASS)

        self._apply_window_flags(initial=True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(376, 108)
        self.setWindowTitle("Audifly Masaüstü Widget")

        self._build_ui()
        self._apply_style()
        self._wire_signals()
        self._restore_position()
        self._sync_initial_state()

    def _apply_window_flags(self, initial: bool = False):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self._always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible() if not initial else False
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self.card = QFrame()
        self.card.setObjectName("DesktopWidgetCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)

        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(12)

        # 1. Kapak
        self.cover_label = QLabel("♪")
        self.cover_label.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet(
            f"background: {cover_color_for('?')}; border-radius: {COVER_RADIUS}px; "
            "font-size: 24px; color: rgba(255,255,255,0.8);"
        )
        card_layout.addWidget(self.cover_label, alignment=Qt.AlignVCenter)

        # 2. Orta: Başlık, Sanatçı, İlerleme ve Canlı İnce Spektrum
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(2)

        self.title_label = QLabel("Müzik Çalmıyor")
        tf = QFont()
        tf.setBold(True)
        tf.setPointSize(10)
        self.title_label.setFont(tf)
        self.title_label.setStyleSheet("color: #FFFFFF; background: transparent;")
        mid.addWidget(self.title_label)

        self.artist_label = QLabel("Audifly Masaüstü Widget")
        self.artist_label.setStyleSheet("color: #b7b2cf; font-size: 11px; background: transparent;")
        mid.addWidget(self.artist_label)

        # İnce neon spektrum
        self.visualizer = NeonAudioVisualizer(
            playback=self.playback,
            mode=self.settings.get("visualizer_mode", "bars"),
            palette=self.settings.get("visualizer_palette", "dynamic"),
            bar_count=26,
            interactive=False,
            transparent_bg=True,
        )
        self.visualizer.setFixedHeight(20)
        mid.addWidget(self.visualizer)

        # İnce 3px ilerleme çubuğu
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        mid.addWidget(self.progress)

        card_layout.addLayout(mid, stretch=1)

        # 3. Sağ: Hover ile beliren sade kontrol düğmeleri
        self.controls_box = QWidget()
        self.controls_box.setStyleSheet("background: transparent;")
        ctrl_col = QVBoxLayout(self.controls_box)
        ctrl_col.setContentsMargins(0, 0, 0, 0)
        ctrl_col.setSpacing(4)

        top_ctrl = QHBoxLayout()
        top_ctrl.setSpacing(4)
        top_ctrl.addStretch(1)
        self.close_btn = self._icon_btn("close", 11, "Widget'ı kapat (Sağ tık: Ayarlar)", 22)
        self.close_btn.clicked.connect(self.close)
        top_ctrl.addWidget(self.close_btn)
        ctrl_col.addLayout(top_ctrl)

        ctrl_col.addStretch(1)

        trans_row = QHBoxLayout()
        trans_row.setSpacing(4)
        self.prev_btn = self._icon_btn("prev", 13, "Önceki şarkı", 26)
        self.prev_btn.clicked.connect(self.playback.play_previous)
        trans_row.addWidget(self.prev_btn)

        self.play_btn = self._icon_btn("play", 14, "Oynat / Duraklat", 30, primary=True)
        self.play_btn.clicked.connect(self.playback.toggle_play_pause)
        trans_row.addWidget(self.play_btn)

        self.next_btn = self._icon_btn("next", 13, "Sonraki şarkı", 26)
        self.next_btn.clicked.connect(self.playback.play_next)
        trans_row.addWidget(self.next_btn)
        ctrl_col.addLayout(trans_row)

        self.controls_box.setVisible(False)
        card_layout.addWidget(self.controls_box, alignment=Qt.AlignVCenter)

        root.addWidget(self.card)

    def _icon_btn(self, kind: str, ic_size: int, tip: str, size: int, primary: bool = False) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(size, size)
        btn.setIcon(vicon(kind, ic_size, "#ffffff"))
        btn.setIconSize(QSize(ic_size, ic_size))
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        if primary:
            btn.setStyleSheet(
                f"QPushButton {{ background: {self._accent}; border: none; border-radius: {size // 2}px; }}"
                f"QPushButton:hover {{ background: #b995ff; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(255,255,255,0.08); border: none; border-radius: {size // 2}px; }}"
                "QPushButton:hover { background: rgba(255,255,255,0.18); }"
            )
        return btn

    def _apply_style(self):
        if self._style_mode == STYLE_MINIMAL:
            card_css = (
                "#DesktopWidgetCard { background: rgba(12, 14, 22, 0.35); "
                "border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 18px; }"
            )
        elif self._style_mode == STYLE_NEON:
            card_css = (
                f"#DesktopWidgetCard {{ background: rgba(14, 16, 26, 0.82); "
                f"border: 1px solid {self._accent}; border-radius: 18px; }}"
            )
        else:
            card_css = (
                "#DesktopWidgetCard { background: rgba(16, 18, 30, 0.72); "
                "border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 18px; }"
            )
        self.card.setStyleSheet(card_css)
        self.progress.setStyleSheet(
            "QProgressBar { background: rgba(255, 255, 255, 0.10); border: none; border-radius: 1px; }"
            f"QProgressBar::chunk {{ background: {self._accent}; border-radius: 1px; }}"
        )

    def _wire_signals(self):
        self.playback.songStarted.connect(self._on_song_started)
        self.playback.playStateChanged.connect(self._on_play_state)
        self.playback.positionChanged.connect(self._on_position)
        self.playback.radioStarted.connect(self._on_radio_started)
        self.playback.radioStopped.connect(self._on_radio_stopped)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    def _sync_initial_state(self):
        song = getattr(self.playback, "current_song", None)
        if song:
            self._on_song_started(self.playback.playing_playlist, self.playback.current_index, song, False)
        self._on_play_state(bool(getattr(self.playback, "is_playing", False)))

    # --- Olaylar ---
    def _on_song_started(self, playlist_name, index, song, is_offline):
        self._current_key = song.get("webpage_url")
        clean_t, clean_a = parse_track_and_artist(
            song.get("title", ""), song.get("uploader", ""), song
        )
        self.title_label.setText(clean_t[:26] + ("…" if len(clean_t) > 26 else ""))
        self.artist_label.setText(clean_a[:28] + ("…" if len(clean_a) > 28 else ""))
        self._accent = cover_color_for(clean_t)
        self._apply_style()
        if hasattr(self, "visualizer"):
            self.visualizer.set_accent(self._accent)
        self._update_cover(song, clean_t)

    def _update_cover(self, song: dict, title: str):
        pm = self.thumbnails.pixmap_for(song, COVER_SIZE) if self.thumbnails else None
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(COVER_SIZE, COVER_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, (scaled.width() - COVER_SIZE) // 2)
            y = max(0, (scaled.height() - COVER_SIZE) // 2)
            cropped = scaled.copy(x, y, COVER_SIZE, COVER_SIZE)
            rounded = QPixmap(COVER_SIZE, COVER_SIZE)
            rounded.fill(Qt.transparent)
            p = QPainter(rounded)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, COVER_SIZE, COVER_SIZE), COVER_RADIUS, COVER_RADIUS)
            p.setClipPath(path)
            p.drawPixmap(0, 0, cropped)
            p.end()
            self.cover_label.setStyleSheet("background: transparent;")
            self.cover_label.setPixmap(rounded)
            self.cover_label.setText("")
        else:
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("♪")
            self.cover_label.setStyleSheet(
                f"background: {cover_color_for(title)}; border-radius: {COVER_RADIUS}px; "
                "font-size: 24px; color: white;"
            )

    def _on_thumbnail_ready(self, key: str):
        if key == self._current_key and self.playback.current_song:
            self._update_cover(self.playback.current_song, self.title_label.text())

    def _on_play_state(self, playing: bool):
        self.play_btn.setIcon(vicon("pause" if playing else "play", 14, "#ffffff"))
        if hasattr(self, "visualizer"):
            self.visualizer.set_playing(playing and self.isVisible())

    def _on_position(self, current_ms: int, total_ms: int):
        if total_ms > 0:
            self.progress.setRange(0, total_ms)
            self.progress.setValue(current_ms)

    def _on_radio_started(self, station: dict):
        name = station.get("name", "Canlı Radyo")
        self.title_label.setText(name[:26] + ("…" if len(name) > 26 else ""))
        self.artist_label.setText("📻 Canlı Radyo")
        self.progress.setValue(0)

    def _on_radio_stopped(self):
        self.title_label.setText("Müzik Çalmıyor")
        self.artist_label.setText("Audifly Masaüstü Widget")
        self.progress.setValue(0)

    # --- Hover ve Sürükleme ---
    def enterEvent(self, event):  # noqa: N802
        self.controls_box.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.controls_box.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and not self._locked:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton) and not self._locked:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        top_act = menu.addAction("📌 Her Zaman Üstte")
        top_act.setCheckable(True)
        top_act.setChecked(self._always_on_top)

        lock_act = menu.addAction("🔒 Konumu Kilitle")
        lock_act.setCheckable(True)
        lock_act.setChecked(self._locked)

        style_menu = menu.addMenu("🎨 Görünüm Stili")
        s_glass = style_menu.addAction("Cam Koyu (Varsayılan)")
        s_minimal = style_menu.addAction("Ultra Şeffaf (Rainmeter)")
        s_neon = style_menu.addAction("Neon Çerçeve")
        for act, key in ((s_glass, STYLE_GLASS), (s_minimal, STYLE_MINIMAL), (s_neon, STYLE_NEON)):
            act.setCheckable(True)
            act.setChecked(self._style_mode == key)

        menu.addSeparator()
        close_act = menu.addAction("✕ Widget'ı Kapat")

        chosen = menu.exec(event.globalPos())
        if chosen == top_act:
            self._always_on_top = not self._always_on_top
            self.settings["desktop_widget_on_top"] = self._always_on_top
            self._apply_window_flags()
            self._persist()
        elif chosen == lock_act:
            self._locked = not self._locked
            self.settings["desktop_widget_locked"] = self._locked
            self._persist()
        elif chosen == s_glass:
            self._set_style_mode(STYLE_GLASS)
        elif chosen == s_minimal:
            self._set_style_mode(STYLE_MINIMAL)
        elif chosen == s_neon:
            self._set_style_mode(STYLE_NEON)
        elif chosen == close_act:
            self.close()

    def _set_style_mode(self, mode: str):
        self._style_mode = mode
        self.settings["desktop_widget_style"] = mode
        self._apply_style()
        self._persist()

    def _restore_position(self):
        pos = self.settings.get("desktop_widget_pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))

    def _save_position(self):
        self.settings["desktop_widget_pos"] = [self.x(), self.y()]
        self._persist()

    def _persist(self):
        if callable(self._save_settings):
            try:
                self._save_settings()
            except Exception:
                pass

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if hasattr(self, "visualizer"):
            self.visualizer.set_playing(bool(getattr(self.playback, "is_playing", False)))

    def hideEvent(self, event):  # noqa: N802
        if hasattr(self, "visualizer"):
            self.visualizer.set_playing(False)
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        if hasattr(self, "visualizer"):
            self.visualizer.set_playing(False)
        self.closed.emit()
        super().closeEvent(event)

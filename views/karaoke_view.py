"""Apple Music / Canlı Karaoke Tarzı Tam Ekran Görünümü.

- F11 veya arayüzdeki Karaoke düğmesi ile açılır (showFullScreen).
- Arka planda albüm kapağının renklerinden üretilen akışkan, bulanık ambient ışık gradyanı.
- Sol tarafta büyük albüm kapağı, parça bilgileri ve zarif çalma denetimleri.
- Sağ tarafta canlı senkronize sözler (söylenen satır dev boyutta ve parlayarak ortalanır).
- Söz satırına tıklandığında şarkı o saniyeye sarılır.
- Fare hareketsiz kaldığında üst kontroller otomatik gizlenir; Esc veya F11 ile çıkılır.
"""
from __future__ import annotations

import colorsys
import os
import threading

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for, format_time, shade_color
from mustiefly_qt.helpers.dynamic_theme import dominant_accent_color
from mustiefly_qt.helpers import lyrics as ly
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.click_slider import ClickSlider
from mustiefly_qt.widgets.player_icons import icon as vicon

PAGE_STATUS, PAGE_PLAIN, PAGE_SYNCED = 0, 1, 2


class _AmbientBackground(QWidget):
    """Kapağın renklerinden türetilen akışkan, yumuşak radyal ışık gradyanı."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._c1 = QColor("#5a2d82")
        self._c2 = QColor("#1e3c72")
        self._base = QColor(10, 8, 16)

    def set_colors(self, hex1: str | None, hex2: str | None = None):
        if hex1:
            try:
                self._c1 = QColor(hex1)
                if hex2:
                    self._c2 = QColor(hex2)
                else:
                    # c1'den biraz farklı tonda ikinci renk üret
                    r, g, b = self._c1.red(), self._c1.green(), self._c1.blue()
                    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                    h2 = (h + 0.12) % 1.0
                    r2, g2, b2 = colorsys.hsv_to_rgb(h2, max(0.5, s), max(0.4, v * 0.8))
                    self._c2 = QColor(int(r2 * 255), int(g2 * 255), int(b2 * 255))
            except Exception:
                pass
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 1) Çok koyu arka plan
        painter.fillRect(0, 0, w, h, self._base)

        # 2) Sol-üst ışık küresi (birinci renk)
        g1 = QRadialGradient(w * 0.28, h * 0.38, max(w, h) * 0.65)
        c1_intense = QColor(self._c1.red(), self._c1.green(), self._c1.blue(), 140)
        c1_fade = QColor(self._c1.red(), self._c1.green(), self._c1.blue(), 30)
        g1.setColorAt(0.0, c1_intense)
        g1.setColorAt(0.45, c1_fade)
        g1.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, g1)

        # 3) Sağ-alt ışık küresi (ikinci renk)
        g2 = QRadialGradient(w * 0.72, h * 0.65, max(w, h) * 0.70)
        c2_intense = QColor(self._c2.red(), self._c2.green(), self._c2.blue(), 120)
        c2_fade = QColor(self._c2.red(), self._c2.green(), self._c2.blue(), 25)
        g2.setColorAt(0.0, c2_intense)
        g2.setColorAt(0.50, c2_fade)
        g2.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, g2)

        # 4) Metin okunurluğu için koyu tül katmanı
        dark_overlay = QLinearGradient(0, 0, 0, h)
        dark_overlay.setColorAt(0.0, QColor(8, 6, 14, 150))
        dark_overlay.setColorAt(0.5, QColor(6, 5, 10, 110))
        dark_overlay.setColorAt(1.0, QColor(8, 6, 14, 210))
        painter.fillRect(0, 0, w, h, dark_overlay)


class KaraokeView(QWidget):
    """Tam ekran Apple Music tarzı canlı Karaoke ve Sözler görünümü."""

    closed = Signal()
    lyricsReady = Signal(dict, int, object)

    def __init__(self, playback: PlaybackEngine, thumbnails: ThumbnailService | None = None, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.playback = playback
        self.thumbnails = thumbnails
        self.setObjectName("KaraokeView")
        self.setMouseTracking(True)

        self._token = 0
        self._lines: list[tuple[int, str]] = []
        self._active_index = -1
        self._seeking = False
        self._lyrics_dir = os.path.join(self.playback.store.paths.dir, "lyrics")

        self._build_ui()
        self._wire_signals()

        # Otomatik gizlenen kontroller (HUD) zamanlayıcısı
        self._hud_timer = QTimer(self)
        self._hud_timer.setInterval(3200)
        self._hud_timer.setSingleShot(True)
        self._hud_timer.timeout.connect(self._fade_out_hud)

    def _build_ui(self):
        # Arka plan katmanı
        self.ambient = _AmbientBackground(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(24)

        # --- ÜST ÇUBUK (HUD) ---
        self.top_bar = QWidget()
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)

        app_title = QLabel("AUDIFLY KARAOKE")
        app_title.setStyleSheet(
            "color: rgba(255, 255, 255, 0.45); font-weight: bold; font-size: 13px; letter-spacing: 2px;"
        )
        top_layout.addWidget(app_title)
        top_layout.addStretch(1)

        self.exit_btn = QPushButton("✕ Çıkış (Esc)")
        self.exit_btn.setCursor(Qt.PointingHandCursor)
        self.exit_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.12);
                color: #ffffff;
                border-radius: 16px;
                padding: 6px 16px;
                font-weight: 600;
                font-size: 12px;
                border: 1px solid rgba(255, 255, 255, 0.15);
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.22);
            }
        """)
        self.exit_btn.clicked.connect(self.close)
        top_layout.addWidget(self.exit_btn)
        root.addWidget(self.top_bar)

        # --- ORTA ANA BÖLÜM (2 SÜTUN) ---
        main_layout = QHBoxLayout()
        main_layout.setSpacing(64)

        # 1) SOL SÜTUN: Kapak + Şarkı Bilgisi + Oynatma Denetimleri
        left_box = QWidget()
        left_box.setFixedWidth(420)
        left_col = QVBoxLayout(left_box)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(18)
        left_col.addStretch(1)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(360, 360)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("border-radius: 20px; background: rgba(255,255,255,0.06);")
        shadow = QGraphicsDropShadowEffect(self.cover_label)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.cover_label.setGraphicsEffect(shadow)
        left_col.addWidget(self.cover_label, alignment=Qt.AlignCenter)

        # Başlık & Sanatçı
        self.title_label = QLabel("Şarkı Adı")
        self.title_label.setStyleSheet("color: #ffffff; font-size: 26px; font-weight: bold;")
        self.title_label.setWordWrap(True)
        left_col.addWidget(self.title_label)

        self.artist_label = QLabel("Sanatçı")
        self.artist_label.setStyleSheet("color: rgba(255, 255, 255, 0.65); font-size: 17px; font-weight: 500;")
        self.artist_label.setWordWrap(True)
        left_col.addWidget(self.artist_label)

        # Süre çubuğu
        slider_box = QWidget()
        slider_layout = QVBoxLayout(slider_box)
        slider_layout.setContentsMargins(0, 4, 0, 0)
        slider_layout.setSpacing(4)
        self.time_slider = ClickSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 1000)
        self.time_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 5px;
                background: rgba(255, 255, 255, 0.18);
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #ffffff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 12px;
                margin: -4px 0;
                background: #ffffff;
                border-radius: 6px;
            }
        """)
        self.time_slider.sliderPressed.connect(self._on_slider_pressed)
        self.time_slider.sliderReleased.connect(self._on_slider_released)
        slider_layout.addWidget(self.time_slider)

        times_row = QHBoxLayout()
        self.curr_time_label = QLabel("00:00")
        self.curr_time_label.setStyleSheet("color: rgba(255, 255, 255, 0.5); font-size: 11px;")
        self.total_time_label = QLabel("00:00")
        self.total_time_label.setStyleSheet("color: rgba(255, 255, 255, 0.5); font-size: 11px;")
        times_row.addWidget(self.curr_time_label)
        times_row.addStretch(1)
        times_row.addWidget(self.total_time_label)
        slider_layout.addLayout(times_row)
        left_col.addWidget(slider_box)

        # Oynatma Düğmeleri (Transport)
        controls_row = QHBoxLayout()
        controls_row.setSpacing(16)
        controls_row.setAlignment(Qt.AlignCenter)

        self.shuffle_btn = QPushButton("🔀")
        self.shuffle_btn.setFixedSize(38, 38)
        self.shuffle_btn.setCursor(Qt.PointingHandCursor)
        self.shuffle_btn.setStyleSheet(self._btn_style(small=True))
        self.shuffle_btn.clicked.connect(self.playback.toggle_shuffle)
        controls_row.addWidget(self.shuffle_btn)

        self.prev_btn = QPushButton("⏮")
        self.prev_btn.setFixedSize(44, 44)
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.setStyleSheet(self._btn_style())
        self.prev_btn.clicked.connect(self.playback.play_previous)
        controls_row.addWidget(self.prev_btn)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(62, 62)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                color: #100e18;
                border-radius: 31px;
                font-size: 22px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #e6e6e6;
                transform: scale(1.05);
            }
        """)
        self.play_btn.clicked.connect(self.playback.toggle_play_pause)
        controls_row.addWidget(self.play_btn)

        self.next_btn = QPushButton("⏭")
        self.next_btn.setFixedSize(44, 44)
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setStyleSheet(self._btn_style())
        self.next_btn.clicked.connect(self.playback.play_next)
        controls_row.addWidget(self.next_btn)

        self.like_btn = QPushButton("♡")
        self.like_btn.setFixedSize(38, 38)
        self.like_btn.setCursor(Qt.PointingHandCursor)
        self.like_btn.setStyleSheet(self._btn_style(small=True))
        self.like_btn.clicked.connect(self._toggle_like)
        controls_row.addWidget(self.like_btn)

        left_col.addLayout(controls_row)
        left_col.addStretch(1)
        main_layout.addWidget(left_box)

        # 2) SAĞ SÜTUN: Canlı Senkronize Sözler (Lyrics Stream)
        right_box = QWidget()
        right_col = QVBoxLayout(right_box)
        right_col.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()

        # Sayfa 0: Durum / Yükleniyor / Söz Yok
        status_card = QWidget()
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setAlignment(Qt.AlignCenter)
        sc_layout.setSpacing(12)
        self.status_icon = QLabel("🎤")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet("font-size: 64px;")
        self.status_text = QLabel("Sözler aranıyor…")
        self.status_text.setAlignment(Qt.AlignCenter)
        self.status_text.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 20px; font-weight: 500;")
        sc_layout.addWidget(self.status_icon)
        sc_layout.addWidget(self.status_text)
        self.stack.addWidget(status_card)

        # Sayfa 1: Düz Sözler
        plain_scroll = QScrollArea()
        plain_scroll.setWidgetResizable(True)
        plain_scroll.setStyleSheet("background: transparent; border: none;")
        plain_content = QWidget()
        plain_layout = QVBoxLayout(plain_content)
        plain_layout.setContentsMargins(20, 20, 20, 20)
        self.plain_label = QLabel()
        self.plain_label.setStyleSheet("color: rgba(255, 255, 255, 0.85); font-size: 22px; line-height: 1.8;")
        self.plain_label.setWordWrap(True)
        plain_layout.addWidget(self.plain_label)
        plain_layout.addStretch(1)
        plain_scroll.setWidget(plain_content)
        self.stack.addWidget(plain_scroll)

        # Sayfa 2: Senkronize Sözler (LRC)
        self.synced_list = QListWidget()
        self.synced_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.synced_list.setFocusPolicy(Qt.NoFocus)
        self.synced_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.synced_list.setWordWrap(True)
        self.synced_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.synced_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.synced_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                padding-top: 140px;
                padding-bottom: 240px;
            }
            QListWidget::item {
                padding: 12px 16px;
                border-radius: 12px;
            }
            QListWidget::item:hover {
                background: rgba(255, 255, 255, 0.05);
            }
        """)
        self.synced_list.itemClicked.connect(self._on_line_clicked)
        self.stack.addWidget(self.synced_list)

        right_col.addWidget(self.stack)
        main_layout.addWidget(right_box, stretch=1)

        root.addLayout(main_layout, stretch=1)

    def _btn_style(self, small: bool = False) -> str:
        size = 38 if small else 44
        font_size = "16px" if small else "19px"
        radius = size // 2
        return f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.12);
                color: #ffffff;
                border-radius: {radius}px;
                font-size: {font_size};
                border: none;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.24);
            }}
        """

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.ambient.setGeometry(0, 0, self.width(), self.height())

    def _wire_signals(self):
        self.playback.songStarted.connect(self._on_song_started)
        self.playback.playStateChanged.connect(self._on_play_state)
        self.playback.positionChanged.connect(self._on_position)
        self.lyricsReady.connect(self._apply_lyrics_result)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    def mouseMoveEvent(self, event):  # noqa: N802
        super().mouseMoveEvent(event)
        self.top_bar.setVisible(True)
        self._hud_timer.start()

    def _fade_out_hud(self):
        self.top_bar.setVisible(False)

    def keyPressEvent(self, event):  # noqa: N802
        k = event.key()
        if k in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
            event.accept()
            return
        if k == Qt.Key_Space:
            self.playback.toggle_play_pause()
            event.accept()
            return
        if k in (Qt.Key_Right, Qt.Key_L):
            self.playback.seek(self.playback.player.get_time() + 5000)
            event.accept()
            return
        if k in (Qt.Key_Left, Qt.Key_J):
            self.playback.seek(max(0, self.playback.player.get_time() - 5000))
            event.accept()
            return
        if k == Qt.Key_N:
            self.playback.play_next()
            event.accept()
            return
        if k == Qt.Key_P:
            self.playback.play_previous()
            event.accept()
            return
        if k == Qt.Key_Up:
            cur = int(self.playback.settings.get("_volume", 80))
            self.playback.change_volume(min(100, cur + 5))
            event.accept()
            return
        if k == Qt.Key_Down:
            cur = int(self.playback.settings.get("_volume", 80))
            self.playback.change_volume(max(0, cur - 5))
            event.accept()
            return
        super().keyPressEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._sync_all()
        self._hud_timer.start()

    def closeEvent(self, event):  # noqa: N802
        self._hud_timer.stop()
        self.closed.emit()
        super().closeEvent(event)

    # --- Güncelleme & Şarkı Değişimi ---
    def _sync_all(self, song: dict | None = None):
        if song is None:
            song = self.playback.current_song
        if not song:
            self.title_label.setText("Şarkı Çalınmıyor")
            self.artist_label.setText("")
            self._show_status("🎵", "Şu an bir şarkı çalmıyor")
            return

        clean_t, clean_a = parse_track_and_artist(song.get("title", ""), song.get("uploader", ""), song)
        self.title_label.setText(clean_t)
        self.artist_label.setText(clean_a)
        self.like_btn.setText("♥" if song.get("liked") else "♡")
        self.like_btn.setStyleSheet(
            f"color: {'#ff5e7e' if song.get('liked') else '#ffffff'}; " + self._btn_style(small=True)
        )
        self.play_btn.setText("⏸" if self.playback.is_playing else "▶")
        self.shuffle_btn.setStyleSheet(
            f"color: {'#a980f9' if self.playback.shuffle_mode else '#ffffff'}; " + self._btn_style(small=True)
        )

        # Kapak resmi ve renkler
        pm = self.thumbnails.pixmap_for(song, 360, rounded=False) if self.thumbnails else None
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(360, 360, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, (scaled.width() - 360) // 2)
            y = max(0, (scaled.height() - 360) // 2)
            cropped = scaled.copy(x, y, 360, 360)
            self.cover_label.setPixmap(cropped)
            self.cover_label.setStyleSheet("border-radius: 20px; background: transparent;")
        else:
            base_col = cover_color_for(clean_t)
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setStyleSheet(f"background: {base_col}; border-radius: 20px;")

        # Arka plan ambient renklerini belirle
        accent = cover_color_for(clean_t)
        if self.thumbnails is not None:
            try:
                img = self.thumbnails.pil_for(song)
                if img is not None:
                    extracted = dominant_accent_color(img)
                    if extracted:
                        accent = extracted
            except Exception:
                pass
        self.ambient.set_colors(accent)

        # Şarkı sözlerini çek
        self._load_lyrics(song)

    def _on_song_started(self, playlist_name, index, song, is_offline):
        self._sync_all(song)

    def _on_thumbnail_ready(self, key: str):
        song = self.playback.current_song
        if song and song.get("webpage_url") == key and self.isVisible():
            if self.thumbnails is not None:
                pm = self.thumbnails.pixmap_for(song, 360, rounded=False)
                if pm is not None and not pm.isNull():
                    scaled = pm.scaled(360, 360, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    x = max(0, (scaled.width() - 360) // 2)
                    y = max(0, (scaled.height() - 360) // 2)
                    self.cover_label.setPixmap(scaled.copy(x, y, 360, 360))
                    self.cover_label.setStyleSheet("border-radius: 20px; background: transparent;")
                img = self.thumbnails.pil_for(song)
                if img is not None:
                    extracted = dominant_accent_color(img)
                    if extracted:
                        self.ambient.set_colors(extracted)

    def _on_play_state(self, playing: bool):
        self.play_btn.setText("⏸" if playing else "▶")

    def _toggle_like(self):
        pl = self.playback.playing_playlist
        idx = self.playback.current_index
        if pl and idx >= 0:
            self.playback.store.toggle_like(pl, idx)
            song = self.playback.current_song
            if song:
                self.like_btn.setText("♥" if song.get("liked") else "♡")
                self.like_btn.setStyleSheet(
                    f"color: {'#ff5e7e' if song.get('liked') else '#ffffff'}; " + self._btn_style(small=True)
                )

    # --- Söz Yönetimi ---
    def _show_status(self, icon: str, text: str):
        self.status_icon.setText(icon)
        self.status_text.setText(text)
        self.stack.setCurrentIndex(PAGE_STATUS)

    def _load_lyrics(self, song: dict):
        self._token += 1
        self._lines = []
        self._active_index = -1
        self._show_status("⏳", "Sözler aranıyor…")

        token = self._token
        lyrics_dir = self._lyrics_dir

        def worker():
            try:
                vid = ly.extract_video_id(song.get("webpage_url") or song.get("id") or "")
                res = ly.fetch_lyrics_result(
                    song.get("title", ""), song.get("uploader", ""),
                    song.get("duration") or 0, lyrics_dir,
                    video_id=vid,
                )
            except Exception:
                res = ly.LyricsResult(ly.ERROR)
            self.lyricsReady.emit(song, token, res)

        threading.Thread(target=worker, daemon=True, name="KaraokeLyricsWorker").start()

    def _apply_lyrics_result(self, song: dict, token: int, result: ly.LyricsResult):
        if token != self._token:
            return
        cur = self.playback.current_song
        if cur and song.get("title") != cur.get("title") and song.get("webpage_url") != cur.get("webpage_url"):
            return

        if result.status == ly.ERROR:
            self._show_status("📡", "Sözler alınamadı")
        elif result.instrumental:
            self._show_status("🎼", "Bu şarkı enstrümantal")
        elif result.status == ly.NOT_FOUND or not result.has_text:
            self._show_status("🔍", "Bu şarkı için söz bulunamadı")
        elif result.synced:
            self._lines = result.synced
            self._active_index = -1
            self.synced_list.clear()
            for _, text in self._lines:
                item = QListWidgetItem(text or "♪")
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                font = QFont()
                font.setPixelSize(21)
                font.setBold(False)
                item.setFont(font)
                item.setForeground(QBrush(QColor(255, 255, 255, 110)))
                self.synced_list.addItem(item)
            self.stack.setCurrentIndex(PAGE_SYNCED)
            self._on_position(max(0, self.playback.player.get_time()), 0)
        else:
            self.plain_label.setText(result.plain or "")
            self.stack.setCurrentIndex(PAGE_PLAIN)

    # --- Konum & Canlı Karaoke Kaydırma ---
    def _on_position(self, current_ms: int, total_ms: int):
        if not self._seeking:
            if total_ms > 0:
                self.time_slider.setRange(0, total_ms)
                self.time_slider.setValue(current_ms)
                self.curr_time_label.setText(format_time(current_ms))
                self.total_time_label.setText(format_time(total_ms))

        if not self._lines or self.stack.currentIndex() != PAGE_SYNCED:
            return

        idx = ly.current_line_index(self._lines, current_ms)
        if idx == self._active_index:
            return

        # Önceki satırı eski haline getir
        if 0 <= self._active_index < self.synced_list.count():
            old_item = self.synced_list.item(self._active_index)
            f = old_item.font()
            f.setPixelSize(21)
            f.setBold(False)
            old_item.setFont(f)
            old_item.setForeground(QBrush(QColor(255, 255, 255, 110)))

        self._active_index = idx

        # Yeni aktif satırı parlat ve büyüt
        if 0 <= idx < self.synced_list.count():
            item = self.synced_list.item(idx)
            f = item.font()
            f.setPixelSize(28)
            f.setBold(True)
            item.setFont(f)
            item.setForeground(QBrush(QColor(255, 255, 255, 255)))
            self.synced_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _on_line_clicked(self, item: QListWidgetItem):
        row = self.synced_list.row(item)
        if 0 <= row < len(self._lines):
            target_ms = self._lines[row][0]
            self.playback.seek(target_ms)

    def _on_slider_pressed(self):
        self._seeking = True

    def _on_slider_released(self):
        self.playback.seek(self.time_slider.value())
        self._seeking = False

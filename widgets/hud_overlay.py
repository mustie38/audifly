"""Ekran Üstü Mini Bildirim / HUD (Gaming Overlay).

Oyun oynarken veya başka bir tam ekran uygulamadayken (kodlama, tarayıcı vb.)
şarkı değiştiğinde ekranın köşesinde zarif, yarı saydam, odak çalmayan
(non-activating / non-stealing) bir HUD kartı gösterir.
"""
from __future__ import annotations

import sys
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.thumbnails import ThumbnailService


class HudOverlay(QWidget):
    """Ekranın üstünde beliren, oyun veya diğer uygulamalardan odak çalmayan HUD."""

    clicked = Signal()

    WIDTH = 370
    HEIGHT = 80

    def __init__(
        self,
        playback: PlaybackEngine,
        thumbnails: ThumbnailService | None = None,
        settings: dict | None = None,
        parent: QWidget | None = None,
    ):
        # Qt.ToolTip + Qt.WindowStaysOnTopHint + Qt.WindowDoesNotAcceptFocus
        # sayesinde Windows pencere yöneticisi oyundan veya uygulamadan odağı ASLA çalmaz.
        flags = (
            Qt.ToolTip
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.playback = playback
        self.thumbnails = thumbnails
        self.settings = settings or {}
        self.main_window = parent

        self.setObjectName("HudOverlay")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        self._current_song: dict | None = None
        self._is_dismissed = False

        self._build_ui()
        self._setup_animation()
        self._wire_signals()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        # Cam efektli ana kart container'ı
        self.card = QFrame(self)
        self.card.setObjectName("HudCard")
        self.card.setStyleSheet("""
            QFrame#HudCard {
                background: rgba(18, 16, 26, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 16px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(10, 8, 12, 8)
        card_layout.setSpacing(12)

        # 1) Sol: Albüm kapağı
        self.cover_label = QLabel(self.card)
        self.cover_label.setFixedSize(50, 50)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("border-radius: 10px; background: rgba(255, 255, 255, 0.08);")
        card_layout.addWidget(self.cover_label)

        # 2) Orta: Başlık, Sanatçı ve Rozet
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 2, 0, 2)
        text_layout.setSpacing(2)

        # Mini üst rozet
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(6)

        self.badge_dot = QLabel("●", self.card)
        self.badge_dot.setStyleSheet("color: #a980f9; font-size: 8px;")
        self.badge_label = QLabel("AUDIFLY HUD", self.card)
        self.badge_label.setStyleSheet(
            "color: #a980f9; font-size: 9px; font-weight: bold; letter-spacing: 1px;"
        )
        badge_row.addWidget(self.badge_dot)
        badge_row.addWidget(self.badge_label)
        badge_row.addStretch(1)
        text_layout.addLayout(badge_row)

        # Şarkı adı
        self.title_label = QLabel("Şarkı Adı", self.card)
        self.title_label.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        self.title_label.setFixedHeight(18)
        text_layout.addWidget(self.title_label)

        # Sanatçı adı
        self.artist_label = QLabel("Sanatçı", self.card)
        self.artist_label.setStyleSheet("color: rgba(255, 255, 255, 0.65); font-size: 11px;")
        self.artist_label.setFixedHeight(16)
        text_layout.addWidget(self.artist_label)

        card_layout.addLayout(text_layout, stretch=1)

        # 3) Sağ: Kapatma butonu
        self.close_btn = QPushButton("✕", self.card)
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Gizle")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(255, 255, 255, 0.35);
                border: none;
                border-radius: 11px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }
        """)
        self.close_btn.clicked.connect(self.dismiss)
        card_layout.addWidget(self.close_btn, alignment=Qt.AlignTop)

        root.addWidget(self.card)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

    def _on_anim_finished(self):
        if self._is_dismissed:
            self.hide()

    def _wire_signals(self):
        self.playback.songStarted.connect(self._on_song_started)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    def _apply_windows_flags(self):
        """Windows üzerinde oyun oynarken odağın kaymasını %100 engelleyen Win32 bayrakları."""
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOPMOST = 0x00000008
                cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
            except Exception:
                pass

    def _is_app_active(self) -> bool:
        """Ana pencere aktif ve ön planda mı?"""
        if self.main_window is None:
            return False
        return self.main_window.isActiveWindow() and self.main_window.isVisible() and not self.main_window.isMinimized()

    def _on_song_started(self, playlist_name, index, song, is_offline):
        self.show_song(song)

    def show_song(self, song: dict | None):
        if not song or not isinstance(song, dict):
            return
        if not self.settings.get("hud_overlay_enabled", True):
            return

        # Sadece uygulama arka plandayken göster ayarı açıksa ve uygulama aktifse atla
        if self.settings.get("hud_overlay_only_background", True) and self._is_app_active():
            return

        self._current_song = song
        self._is_dismissed = False

        # Başlık ve Sanatçı
        raw_t = song.get("title", "Bilinmeyen Şarkı")
        raw_u = song.get("uploader", "")
        clean_t, clean_a = parse_track_and_artist(raw_t, raw_u, song)

        # Elide metinler (uzun başlıkları kırp)
        fm_title = QFontMetrics(self.title_label.font())
        fm_artist = QFontMetrics(self.artist_label.font())
        self.title_label.setText(fm_title.elidedText(clean_t, Qt.ElideRight, 220))
        self.artist_label.setText(fm_artist.elidedText(clean_a, Qt.ElideRight, 220))

        # Kapak görseli
        self._update_cover(song, clean_t)

        # Konumlandırma ve animasyon
        self._reposition()
        self._apply_windows_flags()

        self._anim.stop()
        self.setWindowOpacity(0.0)
        self.show()

        self._anim.setStartValue(0.0)
        self._anim.setEndValue(0.96)
        self._anim.start()

        duration_sec = int(self.settings.get("hud_overlay_duration", 4))
        self._hide_timer.start(max(2, duration_sec) * 1000)

    def _update_cover(self, song: dict, clean_t: str):
        pm = self.thumbnails.pixmap_for(song, 50, rounded=True) if self.thumbnails else None
        if pm is not None and not pm.isNull():
            self.cover_label.setText("")
            self.cover_label.setPixmap(pm)
            self.cover_label.setStyleSheet("border-radius: 10px; background: transparent;")
        else:
            col = cover_color_for(clean_t)
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("🎵")
            self.cover_label.setStyleSheet(
                f"border-radius: 10px; background: {col}; color: #ffffff; font-size: 18px;"
            )

    def _on_thumbnail_ready(self, key: str):
        if self.isVisible() and self._current_song and self._current_song.get("webpage_url") == key:
            raw_t = self._current_song.get("title", "")
            raw_u = self._current_song.get("uploader", "")
            clean_t, _ = parse_track_and_artist(raw_t, raw_u, self._current_song)
            self._update_cover(self._current_song, clean_t)

    def _reposition(self):
        """Kullanıcının aktif olduğu ekrana göre köşeye yerleştirir."""
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()

        pos_setting = self.settings.get("hud_overlay_position", "top-right")
        margin = 24

        if pos_setting == "bottom-right":
            x = geo.x() + geo.width() - self.WIDTH - margin
            y = geo.y() + geo.height() - self.HEIGHT - margin
        elif pos_setting == "top-left":
            x = geo.x() + margin
            y = geo.y() + margin
        elif pos_setting == "top-center":
            x = geo.x() + (geo.width() - self.WIDTH) // 2
            y = geo.y() + margin
        else:  # top-right
            x = geo.x() + geo.width() - self.WIDTH - margin
            y = geo.y() + margin

        self.move(x, y)

    def dismiss(self):
        """HUD'u yumuşakça soldurarak kapatır."""
        if self._is_dismissed or not self.isVisible():
            return
        self._is_dismissed = True
        self._hide_timer.stop()
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def enterEvent(self, event):  # noqa: N802
        """Fare üzerine geldiğinde zamanlayıcıyı durdur."""
        super().enterEvent(event)
        self._hide_timer.stop()

    def leaveEvent(self, event):  # noqa: N802
        """Fare ayrıldığında 1.5 sn sonra kapat."""
        super().leaveEvent(event)
        if not self._is_dismissed:
            self._hide_timer.start(1500)

    def mousePressEvent(self, event):  # noqa: N802
        """HUD'a tıklandığında ana pencereyi öne getir."""
        if event.button() == Qt.LeftButton:
            if self.main_window is not None:
                if self.main_window.isMinimized():
                    self.main_window.showNormal()
                else:
                    self.main_window.show()
                self.main_window.raise_()
                self.main_window.activateWindow()
            self.clicked.emit()
            self.dismiss()
            event.accept()
            return
        super().mousePressEvent(event)

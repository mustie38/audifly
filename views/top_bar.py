"""
Üst çubuk: küresel arama alanı, "+ Ekle" menüsü, güncelleme bildirimi zili ve
kullanıcı avatarı. Mockup'taki üst navigasyon çubuğunun Qt karşılığı.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
)

from mustiefly_qt.widgets.player_icons import icon as vicon


class TopBar(QFrame):
    searchSubmitted = Signal(str)          # Enter ile arama
    addSongRequested = Signal()
    bulkAddRequested = Signal()
    importYouTubeRequested = Signal()
    importSpotifyRequested = Signal()
    importM3URequested = Signal()
    localFilesRequested = Signal()         # bilgisayardan mp3/flac/... ekle
    notificationsClicked = Signal()
    panelToggleClicked = Signal()          # "Şu An Çalıyor" panelini geri açar

    def __init__(self, username: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(64)

        row = QHBoxLayout(self)
        row.setContentsMargins(24, 12, 24, 12)
        row.setSpacing(12)

        # --- Küresel arama / Komut Paleti ---
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("TopSearch")
        self.search_edit.setPlaceholderText("⚡  Ara veya komut çalıştır… (Ctrl + K)")
        self.search_edit.setToolTip("Spotlight & Hızlı Komut Paleti (Ctrl + K)")
        self.search_edit.setFixedWidth(360)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._emit_search)
        row.addWidget(self.search_edit)

        row.addStretch(1)

        # --- + Ekle menüsü ---
        self.add_btn = QPushButton(" Ekle")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setIcon(vicon("plus", 14, "#ffffff"))
        self.add_btn.setIconSize(QSize(14, 14))
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._show_add_menu)
        add_shadow = QGraphicsDropShadowEffect(self.add_btn)
        add_shadow.setBlurRadius(18)
        add_shadow.setOffset(0, 3)
        add_shadow.setColor(QColor(0, 0, 0, 90))
        self.add_btn.setGraphicsEffect(add_shadow)
        row.addWidget(self.add_btn)

        # --- Bildirim zili (yt-dlp güncellemesi vb.) ---
        self.bell_btn = QPushButton()
        self.bell_btn.setObjectName("IconSquare")
        self.bell_btn.setIcon(vicon("bell", 16, "#cfc9e6"))
        self.bell_btn.setIconSize(QSize(16, 16))
        self.bell_btn.setToolTip("Bildirimler")
        self.bell_btn.setCursor(Qt.PointingHandCursor)
        self.bell_btn.clicked.connect(self.notificationsClicked.emit)
        self.bell_btn.setVisible(False)
        row.addWidget(self.bell_btn)

        # --- Panel geri açma (panel kapatıldığında görünür) ---
        self.panel_btn = QPushButton()
        self.panel_btn.setObjectName("IconSquare")
        self.panel_btn.setIcon(vicon("sidebar_right", 16, "#cfc9e6"))
        self.panel_btn.setIconSize(QSize(16, 16))
        self.panel_btn.setToolTip('"Şu An Çalıyor" panelini göster')
        self.panel_btn.setCursor(Qt.PointingHandCursor)
        self.panel_btn.clicked.connect(self.panelToggleClicked.emit)
        self.panel_btn.setVisible(False)
        row.addWidget(self.panel_btn)

        # --- Avatar ---
        self.avatar = QLabel((username[:1] or "M").upper())
        self.avatar.setObjectName("Avatar")
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setFixedSize(34, 34)
        self.avatar.setToolTip(username)
        avatar_font = QFont()
        avatar_font.setBold(True)
        self.avatar.setFont(avatar_font)
        avatar_shadow = QGraphicsDropShadowEffect(self.avatar)
        avatar_shadow.setBlurRadius(16)
        avatar_shadow.setOffset(0, 3)
        avatar_shadow.setColor(QColor(0, 0, 0, 100))
        self.avatar.setGraphicsEffect(avatar_shadow)
        row.addWidget(self.avatar)

    def _emit_search(self):
        query = self.search_edit.text().strip()
        if query:
            self.searchSubmitted.emit(query)

    def _show_add_menu(self):
        menu = QMenu(self)
        song_action = menu.addAction("🎵  Şarkı Ara / Ekle")
        bulk_action = menu.addAction("📥  Toplu Şarkı Ekle…")
        local_action = menu.addAction("💽  Bilgisayardan Ses Dosyası Ekle…")
        menu.addSeparator()
        yt_action = menu.addAction("▶  YouTube Playlist İçe Aktar…")
        spotify_action = menu.addAction("🎧  Spotify Playlist İçe Aktar…")
        m3u_action = menu.addAction("📂  M3U İçe Aktar…")
        chosen = menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))
        if chosen == song_action:
            self.addSongRequested.emit()
        elif chosen == bulk_action:
            self.bulkAddRequested.emit()
        elif chosen == local_action:
            self.localFilesRequested.emit()
        elif chosen == yt_action:
            self.importYouTubeRequested.emit()
        elif chosen == spotify_action:
            self.importSpotifyRequested.emit()
        elif chosen == m3u_action:
            self.importM3URequested.emit()

    def set_notification(self, message: str | None):
        """Güncelleme bildirimi varsa zili gösterir; tooltip'te detay taşır."""
        self.bell_btn.setVisible(bool(message))
        if message:
            self.bell_btn.setToolTip(message)

    def set_panel_toggle_visible(self, visible: bool):
        """Panel kapalıyken geri açma butonu görünür olur."""
        self.panel_btn.setVisible(visible)

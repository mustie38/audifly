"""
Kütüphane görünümü: tüm çalma listelerinin kapak kartlarından grid.
Karta tıklayınca o liste açılır (mockup'taki 'Tüm Çalma Listeleri' ekranı).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for
from mustiefly_qt.helpers.covers import playlist_cover_pixmap
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.player_icons import icon as vicon

COLUMNS = 4
COVER_SIZE = 150


class PlaylistCard(QWidget):
    clicked = Signal(str)

    def __init__(self, name: str, song_count: int, pixmap: QPixmap | None, parent=None):
        super().__init__(parent)
        self.name = name
        self.setObjectName("PlaylistCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(180, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        cover = QLabel()
        cover.setFixedSize(COVER_SIZE, COVER_SIZE - 30)
        cover.setAlignment(Qt.AlignCenter)
        cover_font = QFont()
        cover_font.setPixelSize(40)
        cover.setFont(cover_font)
        if pixmap is not None and not pixmap.isNull():
            cover.setPixmap(pixmap)
            cover.setScaledContents(True)
            cover.setStyleSheet("border-radius: 10px;")
        else:
            cover.setText("🎵")
            cover.setStyleSheet(
                f"background: {cover_color_for(name)}; border-radius: 10px; color: white;")
        self._hover_play = QPushButton(cover)
        self._hover_play.setFixedSize(36, 36)
        self._hover_play.move(COVER_SIZE - 44, (COVER_SIZE - 30) - 44)
        self._hover_play.setIcon(vicon("play", 15, "#ffffff"))
        self._hover_play.setIconSize(QSize(15, 15))
        self._hover_play.setCursor(Qt.PointingHandCursor)
        self._hover_play.setStyleSheet(
            "QPushButton { background: #a980f9; border: none; border-radius: 18px; }"
            "QPushButton:hover { background: #b995ff; }"
        )
        sh = QGraphicsDropShadowEffect(self._hover_play)
        sh.setBlurRadius(14)
        sh.setOffset(0, 3)
        sh.setColor(QColor(0, 0, 0, 150))
        self._hover_play.setGraphicsEffect(sh)
        self._hover_play.clicked.connect(lambda: self.clicked.emit(self.name))
        self._hover_play.hide()

        layout.addWidget(cover)

        name_label = QLabel(name[:20] + ("…" if len(name) > 20 else ""))
        title_font = QFont()
        title_font.setBold(True)
        name_label.setFont(title_font)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        count_label = QLabel(f"{song_count} şarkı")
        count_label.setObjectName("Muted")
        layout.addWidget(count_label)
        layout.addStretch(1)

    def enterEvent(self, event):  # noqa: N802
        self._hover_play.show()
        self._hover_play.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover_play.hide()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)


class LibraryGridView(QWidget):
    openPlaylistRequested = Signal(str)

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 10)

        header = QHBoxLayout()
        title = QLabel("Tüm Çalma Listeleri")
        title_font = QFont()
        title_font.setPixelSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch(1)
        new_btn = QPushButton("+ Yeni Liste")
        new_btn.setObjectName("Primary")
        new_btn.clicked.connect(self._new_playlist)
        header.addWidget(new_btn)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("HomeContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.grid_layout = QGridLayout(content)
        self.grid_layout.setContentsMargins(0, 10, 12, 12)
        self.grid_layout.setSpacing(16)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        self._dirty = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)
        self._refresh_timer.timeout.connect(self.refresh)
        self.store.playlistsChanged.connect(self._on_store_changed)
        self.refresh()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def _on_store_changed(self):
        if self.isVisible():
            self._refresh_timer.start()
        else:
            self._dirty = True

    def _new_playlist(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "Yeni Çalma Listesi", "Liste adı:")
        if not ok or not name.strip():
            return
        success, err = self.store.create_playlist(name)
        if not success:
            QMessageBox.warning(self, "Hata", err)
        else:
            self.openPlaylistRequested.emit(name.strip())

    def refresh(self):
        self._dirty = False
        self._refresh_timer.stop()
        # Grid'i temizle
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        for i, (name, songs) in enumerate(self.store.playlists.items()):
            pm = playlist_cover_pixmap(self.store, self.thumbnails, name, songs,
                                       size=COVER_SIZE * 2)
            card = PlaylistCard(name, len(songs), pm)
            card.clicked.connect(self.openPlaylistRequested.emit)
            self.grid_layout.addWidget(card, i // COLUMNS, i % COLUMNS)

        rows = (len(self.store.playlists) + COLUMNS - 1) // COLUMNS
        for r in range(rows):
            self.grid_layout.setRowStretch(r, 0)
        self.grid_layout.setRowStretch(rows, 1)
        self.grid_layout.setColumnStretch(COLUMNS, 1)

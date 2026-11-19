from __future__ import annotations

import json
import random

from PySide6.QtCore import Qt, QTimer, QPoint, QSize, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QStackedLayout, QWidget,
)

from mustiefly_qt.helpers.constants import format_time, offline_path_for
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.widgets.player_icons import icon as vicon

SONG_MIME = "application/x-mustiefly-song"


class _PlayingIndicator(QWidget):
    """Çalan satırda numaranın yerine geçen 3 çubuklu mini ekolayzer animasyonu.
    Zamanlayıcı yalnızca görünürken ve çalarken çalışır (boşta CPU harcamaz)."""

    def __init__(self, accent: str = "#FF7A3D", parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 16)
        self._accent = QColor(accent)
        self._heights = [0.45, 0.9, 0.6]
        self._timer = QTimer(self)
        self._timer.setInterval(140)
        self._timer.timeout.connect(self._tick)

    def set_running(self, running: bool):
        self._want_running = bool(running)
        if self._want_running and self.isVisible():
            if not self._timer.isActive():
                self._timer.start(140)
        else:
            self._timer.stop()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_want_running", False) and not self._timer.isActive():
            self._timer.start(140)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._heights = [
            min(1.0, max(0.25, h + random.uniform(-0.35, 0.35)))
            for h in self._heights
        ]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._accent)
        col_w = self.width() / 3.0
        for i, h in enumerate(self._heights):
            bh = self.height() * h
            x = i * col_w + 1.5
            painter.drawRect(int(x), int(self.height() - bh),
                             max(int(col_w) - 3, 2), int(bh))
        painter.end()


class SongRow(QWidget):
    """Tek bir şarkı satırı. `index` burada listedeki (playlist içi) index'tir,
    view katmanı bunu play_song_at_index()'e geçer."""

    playRequested = Signal(int)
    likeToggled = Signal(int)
    removeRequested = Signal(int)
    downloadRequested = Signal(int)
    addToQueueRequested = Signal(int)
    playNextRequested = Signal(int)
    startRadioRequested = Signal(dict)
    moveRequested = Signal(int)
    addToRoomQueueRequested = Signal(int)
    artistRequested = Signal(str)
    room_queue_enabled = False   # Birlikte Dinle odasındayken menüde gösterilir (app_window ayarlar)

    def __init__(self, index: int, song: dict, row_number: int | None = None,
                 show_uploader: bool = True, parent=None):
        super().__init__(parent)
        self.index = index
        self.song = song
        self.playlist_name: str | None = None  # LibraryView render'da doldurur
        self._drag_start_pos: QPoint | None = None
        self.setObjectName("SongRow")
        self.setProperty("current", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(52)
        self._is_current = False
        self._is_playing = False
        self._hovered = False
        self._num_stack = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)

        if row_number is not None:
            # Numara / ▶ (hover) / ekolayzer (çalan) aynı alanda dönüşümlü
            self.num_label = QLabel(str(row_number))
            self.num_label.setFixedWidth(28)
            self.num_label.setObjectName("Muted")
            self.num_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.play_btn_overlay = QPushButton("▶")
            self.play_btn_overlay.setObjectName("RowPlay")
            self.play_btn_overlay.setFixedSize(28, 28)
            self.play_btn_overlay.setCursor(Qt.PointingHandCursor)
            self.play_btn_overlay.setToolTip("Çal")
            self.play_btn_overlay.clicked.connect(
                lambda: self.playRequested.emit(self.index))

            self.eq_indicator = _PlayingIndicator()

            holder = QWidget()
            holder.setFixedWidth(28)
            stack = QStackedLayout(holder)
            stack.setContentsMargins(0, 0, 0, 0)
            stack.addWidget(self.num_label)
            stack.addWidget(self.play_btn_overlay)
            stack.addWidget(self.eq_indicator)
            self._num_stack = stack
            layout.addWidget(holder)

        # Kapak / thumbnail placeholder'ı — ThumbnailService hazır olunca set_thumbnail
        # ile doldurulur; o zamana kadar başlığa göre sabit renkli 🎵 rozeti görünür.
        from mustiefly_qt.helpers.constants import cover_color_for
        self.thumb_label = QLabel("🎵")
        self.thumb_label.setFixedSize(36, 36)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background: {cover_color_for(song.get('title', '?'))};"
            "border-radius: 5px; font-size: 15px;"
        )
        layout.addWidget(self.thumb_label)

        parsed_title, parsed_artist = parse_track_and_artist(
            song.get("title", "Bilinmeyen Şarkı"),
            song.get("uploader", "Bilinmeyen Sanatçı"),
            song,
        )
        text_box = QWidget()
        text_layout = QHBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        title_label = QLabel(parsed_title if len(parsed_title) <= 60 else parsed_title[:57] + "...")
        title_label.setObjectName("RowTitle")
        text_layout.addWidget(title_label)
        self.offline_badge = QLabel("✓")
        self.offline_badge.setObjectName("OfflineBadge")
        self.offline_badge.setToolTip("Çevrimdışı kullanılabilir")
        self.offline_badge.setAccessibleName("Çevrimdışı kullanılabilir")
        self.offline_badge.setVisible(offline_path_for(song) is not None)
        text_layout.addWidget(self.offline_badge)
        layout.addWidget(text_box, stretch=1)

        if show_uploader:
            uploader_label = QLabel(parsed_artist)
            uploader_label.setObjectName("Muted")
            uploader_label.setFixedWidth(180)
            if parsed_artist and parsed_artist not in ("Bilinmeyen Sanatçı", "?"):
                uploader_label.setCursor(Qt.PointingHandCursor)
                uploader_label.setToolTip(f"👤 {parsed_artist} profiline git")
                uploader_label.mousePressEvent = lambda e, a=parsed_artist: (
                    self.artistRequested.emit(a) if e.button() == Qt.LeftButton else None
                )
            layout.addWidget(uploader_label)

        liked = bool(song.get("liked"))
        self.like_btn = QPushButton()
        self.like_btn.setObjectName("RowActionBtn")
        self.like_btn.setFixedSize(28, 28)
        self.like_btn.setIcon(vicon("heart_filled" if liked else "heart", 14, "#FF6B8A" if liked else "#9EA3B8"))
        self.like_btn.setIconSize(QSize(14, 14))
        self.like_btn.setToolTip("Beğen" if not liked else "Beğeniyi kaldır")
        self.like_btn.setCursor(Qt.PointingHandCursor)
        self.like_btn.clicked.connect(lambda: self.likeToggled.emit(self.index))
        layout.addWidget(self.like_btn)

        duration_label = QLabel(format_time((song.get("duration") or 0) * 1000))
        duration_label.setObjectName("Muted")
        duration_label.setFixedWidth(46)
        duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(duration_label)

        more_btn = QPushButton()
        more_btn.setObjectName("RowActionBtn")
        more_btn.setFixedSize(28, 28)
        more_btn.setIcon(vicon("more", 15, "#9EA3B8"))
        more_btn.setIconSize(QSize(15, 15))
        more_btn.setToolTip("Şarkı seçenekleri")
        more_btn.setCursor(Qt.PointingHandCursor)
        more_btn.clicked.connect(self._open_menu)
        layout.addWidget(more_btn)

    # --- Numara / ▶ / ekolayzer alanı ---
    def _update_number_area(self):
        if self._num_stack is None:
            return
        if self._is_current:
            self._num_stack.setCurrentWidget(self.eq_indicator)
            self.eq_indicator.set_running(self._is_playing)
        elif self._hovered:
            self._num_stack.setCurrentWidget(self.play_btn_overlay)
            self.eq_indicator.set_running(False)
        else:
            self._num_stack.setCurrentWidget(self.num_label)
            self.eq_indicator.set_running(False)

    def set_current(self, is_current: bool, playing: bool | None = None):
        if is_current != self._is_current:   # gereksiz unpolish/polish maliyetini önle
            self.setProperty("current", "true" if is_current else "false")
            self.style().unpolish(self)
            self.style().polish(self)
        self._is_current = is_current
        if playing is not None:
            self._is_playing = playing
        self._update_number_area()

    def set_playing_state(self, playing: bool):
        """Satır çalıyorsa ekolayzer animasyonu, duraklatıldıysa sabit kalır."""
        self._is_playing = playing
        self._update_number_area()

    def enterEvent(self, event):  # noqa: N802
        self._hovered = True
        self._update_number_area()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hovered = False
        self._update_number_area()
        super().leaveEvent(event)

    def set_thumbnail(self, pm: QPixmap):
        """İndirilmiş kapak görselini satıra uygular."""
        if pm is not None and not pm.isNull():
            self.thumb_label.setPixmap(pm)
            self.thumb_label.setText("")

    def mouseDoubleClickEvent(self, event):
        self.playRequested.emit(self.index)
        super().mouseDoubleClickEvent(event)

    # --- Sürükle → sidebar listeye bırak ---
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        # Sol tuş + 10px eşik: tıklamaları sürüklemeden ayırır
        if (self._drag_start_pos is not None and self.playlist_name
                and (event.buttons() & Qt.LeftButton)
                and (event.pos() - self._drag_start_pos).manhattanLength() >= 10):
            from PySide6.QtCore import QMimeData
            payload = json.dumps({
                "playlist": self.playlist_name,
                "index": self.index,
            })
            mime = QMimeData()
            mime.setData(SONG_MIME, payload.encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            pm = self.thumb_label.pixmap()
            drag.setPixmap(pm if (pm is not None and not pm.isNull())
                           else self.thumb_label.grab())
            self._drag_start_pos = None
            drag.exec(Qt.CopyAction)
            return
        super().mouseMoveEvent(event)

    def _open_menu(self):
        menu = QMenu(self)
        play_action = menu.addAction("▶ Çal")
        radio_action = menu.addAction("📻 Şarkı Radyosu")

        parsed_title, parsed_artist = parse_track_and_artist(
            self.song.get("title", ""),
            self.song.get("uploader", ""),
            self.song,
        )
        artist_action = None
        if parsed_artist and parsed_artist not in ("Bilinmeyen Sanatçı", "?"):
            artist_action = menu.addAction(f"👤 {parsed_artist} Sayfası")

        play_next_action = menu.addAction("⏭ Sırada Çal")
        queue_action = menu.addAction("➕ Kuyruğa Ekle")
        room_action = None
        if SongRow.room_queue_enabled and not self.song.get("local_path"):
            room_action = menu.addAction("👥 Oda Kuyruğuna Ekle")
        move_action = menu.addAction("📂 Başka Listeye Taşı…")
        download_action = None
        if not self.song.get("local_path"):
            download_action = menu.addAction("💾 Çevrimdışı indir")
        like_action = menu.addAction(
            "💔 Beğenmekten vazgeç" if self.song.get("liked") else "♥ Beğen")
        copy_action = None
        if not self.song.get("local_path"):
            copy_action = menu.addAction("🔗 YouTube Linkini Kopyala")
        remove_action = menu.addAction("🗑 Listeden kaldır")
        chosen = menu.exec(self.mapToGlobal(self.rect().bottomRight()))
        if chosen == play_action:
            self.playRequested.emit(self.index)
        elif artist_action is not None and chosen == artist_action:
            self.artistRequested.emit(parsed_artist)
        elif chosen == radio_action:
            self.startRadioRequested.emit(self.song)
        elif chosen == play_next_action:
            self.playNextRequested.emit(self.index)
        elif chosen == queue_action:
            self.addToQueueRequested.emit(self.index)
        elif room_action is not None and chosen == room_action:
            self.addToRoomQueueRequested.emit(self.index)
        elif chosen == move_action:
            self.moveRequested.emit(self.index)
        elif download_action is not None and chosen == download_action:
            self.downloadRequested.emit(self.index)
        elif chosen == like_action:
            self.likeToggled.emit(self.index)
        elif copy_action is not None and chosen == copy_action:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self.song.get("webpage_url", ""))
        elif chosen == remove_action:
            self.removeRequested.emit(self.index)

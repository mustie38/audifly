"""Sözler penceresi — LRCLIB'ten o an çalan şarkının sözlerini getirir.

Senkron söz varsa çalma konumuna göre satır vurgulanır ve otomatik kaydırılır
(satıra tıklamak o ana sarar); yoksa düz metin gösterilir. Yükleniyor / söz yok /
enstrümantal / bağlantı hatası durumlarının her biri ayrı bir ekrandır.
Şarkı değiştiğinde sözler kendiliğinden yenilenir.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from mustiefly_qt.helpers import lyrics as ly
from mustiefly_qt.helpers.win_theme import apply_dark_titlebar, is_dark_theme
from mustiefly_qt.services.playback import PlaybackEngine

PAGE_STATUS, PAGE_PLAIN, PAGE_SYNCED = 0, 1, 2


class LyricsWindow(QWidget):
    lyricsReady = Signal(dict, int, object)   # (song, istek_no, LyricsResult)

    def __init__(self, playback: PlaybackEngine, parent=None):
        # Qt.Window olmadan bu widget ana pencereye gömülü bir alt widget gibi
        # (0,0)'a yapışık, çerçevesiz görünürdü.
        super().__init__(parent, Qt.Window)
        self.setObjectName("LyricsWindow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.playback = playback
        self.setWindowTitle("🎤 Sözler")
        self.resize(420, 560)
        apply_dark_titlebar(self, dark=is_dark_theme(getattr(playback, "settings", {}).get("theme")))
        if parent is not None:
            p = parent.geometry()
            self.move(p.x() + (p.width() - self.width()) // 2,
                      p.y() + (p.height() - self.height()) // 2)

        root = QVBoxLayout(self)
        header_row = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.title_label.setWordWrap(True)
        header_row.addWidget(self.title_label, stretch=1)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("RoundSmall")
        close_btn.setToolTip("Kapat")
        close_btn.setFixedWidth(32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        header_row.addWidget(close_btn)
        root.addLayout(header_row)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Yenile")
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        btn_row.addWidget(self.refresh_btn)

        self.card_btn = QPushButton("🖼️ Söz Kartı")
        self.card_btn.setToolTip("Seçtiğin sözlerden paylaşılabilir PNG kart oluştur")
        self.card_btn.setCursor(Qt.PointingHandCursor)
        self.card_btn.clicked.connect(self._open_lyric_card)
        btn_row.addWidget(self.card_btn)

        self.mode_label = QLabel("")
        self.mode_label.setObjectName("Muted")
        btn_row.addWidget(self.mode_label)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.stack = QStackedWidget()
        # 0: durum ekranı (yükleniyor / yok / hata)
        status = QWidget()
        sv = QVBoxLayout(status)
        sv.setAlignment(Qt.AlignCenter)
        self.status_icon = QLabel("")
        self.status_icon.setAlignment(Qt.AlignCenter)
        icon_font = QFont()
        icon_font.setPixelSize(44)
        self.status_icon.setFont(icon_font)
        self.status_title = QLabel("")
        self.status_title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPixelSize(16)
        title_font.setBold(True)
        self.status_title.setFont(title_font)
        self.status_desc = QLabel("")
        self.status_desc.setObjectName("Muted")
        self.status_desc.setAlignment(Qt.AlignCenter)
        self.status_desc.setWordWrap(True)
        self.retry_btn = QPushButton("Tekrar Dene")
        self.retry_btn.setObjectName("Primary")
        self.retry_btn.clicked.connect(lambda: self.refresh(force=True))
        for w in (self.status_icon, self.status_title, self.status_desc):
            sv.addWidget(w)
        sv.addWidget(self.retry_btn, alignment=Qt.AlignCenter)
        self.stack.addWidget(status)
        # 1: düz metin
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        cl = QVBoxLayout(content)
        self.plain_label = QLabel("")
        self.plain_label.setWordWrap(True)
        self.plain_label.setAlignment(Qt.AlignTop)
        self.plain_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(self.plain_label)
        cl.addStretch(1)
        scroll.setWidget(content)
        self.stack.addWidget(scroll)
        # 2: senkron
        self.synced_list = QListWidget()
        self.synced_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.synced_list.setFocusPolicy(Qt.NoFocus)
        self.synced_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.synced_list.setWordWrap(True)
        self.synced_list.setStyleSheet("QListWidget { border: none; background: transparent; }"
                                       "QListWidget::item { padding: 6px 4px; }")
        self.synced_list.itemClicked.connect(self._on_line_clicked)
        self.stack.addWidget(self.synced_list)
        root.addWidget(self.stack, stretch=1)

        self._token = 0                       # bayat sonuç filtresi (istek numarası)
        self._lines: list[tuple[int, str]] = []
        self._active = -1
        self._last_song: dict | None = None
        self._lyrics_dir = os.path.join(self.playback.store.paths.dir, "lyrics")

        self.playback.songStarted.connect(self._on_song_started)
        self.playback.positionChanged.connect(self._on_position)
        self.lyricsReady.connect(self._apply_result)

    def _on_song_started(self, *_):
        self.refresh()

    def closeEvent(self, event):
        # Kapalı pencere şarkı değişince ağ isteği atmaya devam etmesin
        self._token += 1
        for signal, slot in ((self.playback.songStarted, self._on_song_started),
                             (self.playback.positionChanged, self._on_position)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)

    # --- Durum ekranları ---
    def _show_status(self, icon: str, title: str, desc: str = "", retry: bool = False):
        self.status_icon.setText(icon)
        self.status_title.setText(title)
        self.status_desc.setText(desc)
        self.retry_btn.setVisible(retry)
        self.mode_label.setText("")
        self.stack.setCurrentIndex(PAGE_STATUS)

    def _current_song(self) -> dict | None:
        cur = getattr(self.playback, "current_song", None)
        if isinstance(cur, dict):
            return cur
        pp = self.playback.playing_playlist
        songs = self.playback.store.playlists.get(pp, []) if pp else []
        idx = self.playback.current_index
        return songs[idx] if songs and 0 <= idx < len(songs) else None

    # --- Getirme ---
    def refresh(self, force: bool = False):
        song = self._current_song()
        self._token += 1
        self._lines, self._active = [], -1
        if song is None:
            self.title_label.setText("")
            self._show_status("🎵", "Şu an bir şarkı çalmıyor", "Bir şarkı başlatınca sözleri burada görünür.")
            return
        self._last_song = song
        self.title_label.setText(f"{song.get('title', '')}\n{song.get('uploader', '')}")
        self._show_status("⏳", "Sözler aranıyor…")
        threading.Thread(target=self._fetch_worker, args=(song, self._token, force), daemon=True).start()

    def _fetch_worker(self, song: dict, token: int, force: bool):
        try:
            vid = ly.extract_video_id(song.get("webpage_url") or song.get("id") or "")
            result = ly.fetch_lyrics_result(
                song.get("title", ""), song.get("uploader", ""),
                song.get("duration") or 0,
                self._lyrics_dir,
                video_id=vid,
                force=force,
            )
        except Exception:                                 # söz hatası çalmayı/arayüzü bozmasın
            result = ly.LyricsResult(ly.ERROR)
        try:
            self.lyricsReady.emit(song, token, result)     # queued → GUI thread
        except RuntimeError:
            pass

    def _open_lyric_card(self):
        from mustiefly_qt.views.lyric_card_dialog import LyricCardDialog
        song = self._current_song()
        if not song:
            return
        lines: list[str] = []
        if self._lines:
            lines = [txt for _, txt in self._lines if txt.strip()]
        else:
            plain = self.plain_label.text().strip()
            if plain:
                lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
        thumbs = getattr(self.parent(), "thumbnails", None) if self.parent() is not None else None
        dlg = LyricCardDialog(song, thumbnails=thumbs, initial_lines=lines, parent=self)
        dlg.exec()
        dlg.deleteLater()

    def _apply_result(self, song: dict, token: int, result):
        if token != self._token or song is not self._current_song():
            return                                         # kullanıcı başka şarkıya geçti
        if result.status == ly.ERROR:
            self._show_status("📡", "Sözler alınamadı", "İnternet bağlantını kontrol edip tekrar dene.", retry=True)
        elif result.instrumental:
            self._show_status("🎼", "Bu şarkı enstrümantal", "Söz içermiyor.")
        elif result.status == ly.NOT_FOUND or not result.has_text:
            self._show_status("🔍", "Bu şarkı için söz bulunamadı",
                              "LRCLIB'te eşleşen bir kayıt yok. Başlık/sanatçı farklı yazılmış olabilir.")
        elif result.synced:
            self._show_synced(result)
        else:
            self.plain_label.setText(result.plain or "")
            self.mode_label.setText("düz metin")
            self.stack.setCurrentIndex(PAGE_PLAIN)

    def _show_synced(self, result):
        self._lines = result.synced
        self._active = -1
        self.synced_list.clear()
        for _, text in self._lines:
            item = QListWidgetItem(text or "♪")
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.synced_list.addItem(item)
        self.mode_label.setText("senkron")
        self.stack.setCurrentIndex(PAGE_SYNCED)
        src = (self.playback.player_b
               if getattr(self.playback, "_xfade_is_ramping", lambda: False)() is True
               else self.playback.player)
        self._on_position(max(0, src.get_time()), 0)

    # --- Senkronizasyon ---
    def _on_position(self, current_ms: int, _total: int):
        if not self._lines or self.stack.currentIndex() != PAGE_SYNCED:
            return
        idx = ly.current_line_index(self._lines, current_ms)
        if idx == self._active:
            return                                         # gereksiz yeniden çizim yok
        self._style_item(self._active, False)
        self._active = idx
        self._style_item(idx, True)
        if idx >= 0:
            self.synced_list.scrollToItem(self.synced_list.item(idx), QAbstractItemView.PositionAtCenter)

    def _style_item(self, idx: int, active: bool):
        if not 0 <= idx < self.synced_list.count():
            return
        item = self.synced_list.item(idx)
        font = item.font()
        font.setBold(active)
        font.setPixelSize(18 if active else 14)
        item.setFont(font)
        item.setForeground(QBrush(self.palette().highlight().color() if active
                                  else self.palette().text().color()))

    def _on_line_clicked(self, item: QListWidgetItem):
        row = self.synced_list.row(item)
        if 0 <= row < len(self._lines):
            self.playback.seek(self._lines[row][0])

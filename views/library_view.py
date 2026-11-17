from __future__ import annotations

from mustiefly_qt.helpers.constants import offline_path_for, APP_DISPLAY_NAME

import random

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for, format_time, shade_color
from mustiefly_qt.helpers.covers import format_playlist_duration, playlist_cover_pixmap
from mustiefly_qt.services import smart_lists
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.song_row import SongRow


class _QueueList(QListWidget):
    """Sürükle-bırak ile sıralanabilen kuyruk listesi.
    Qt'nin InternalMove'u setItemWidget'lı öğelerde widget'ı taşımaz; bu yüzden
    dropEvent'i yakalayıp model sırasını (PlaylistStore.manual_queue) yeniden
    düzenleyip yeniden render ettiriyoruz."""
    reordered = Signal(int, int)  # from_index, to_index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def set_interactive(self, interactive: bool):
        """Sadece kuyruk görünümünde sürükle-bırak aktiftir; playlist/akıllı
        listelerde drag aktif kalırsa yanlışlıkla kuyruk yeniden sıralanırdı."""
        self.setDragEnabled(interactive)
        self.setAcceptDrops(interactive)
        self.setDropIndicatorShown(interactive)
        self.setDragDropMode(
            QAbstractItemView.DragDrop if interactive else QAbstractItemView.NoDragDrop)

    def dropEvent(self, event):
        source_row = self.currentRow()
        target_item = self.itemAt(event.pos())
        if target_item is None:
            target_row = self.count() - 1
        else:
            target_row = self.row(target_item)
            # Öğenin üst/alt yarısına göre ekleme noktası
            rect = self.visualItemRect(target_item)
            if event.pos().y() > rect.center().y():
                target_row += 1
        if target_row > source_row:
            target_row -= 1
        super().dropEvent(event)
        if 0 <= source_row < self.count() and 0 <= target_row < self.count() and source_row != target_row:
            self.reordered.emit(source_row, target_row)


class QueueRow(QWidget):
    """Kuyruktaki tek satır: ☰ tutamacı + başlık + süre + ✕ kaldır."""
    playRequested = Signal(int)   # q_idx
    removeRequested = Signal(int)

    def __init__(self, q_idx: int, playlist_name: str, song: dict, is_missing: bool, parent=None):
        super().__init__(parent)
        self.q_idx = q_idx
        self.setProperty("missing", is_missing)
        self.setObjectName("SongRow")
        self.setProperty("current", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        handle = QLabel("☰")
        handle.setObjectName("Muted")
        handle.setToolTip("Sürükleyerek sırayı değiştir")
        layout.addWidget(handle)

        thumb = QLabel("❌" if is_missing else "🎵")
        if not is_missing:
            thumb.setFixedSize(32, 32)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet(
                f"background: {cover_color_for(song.get('title', '?'))};"
                "border-radius: 5px; font-size: 14px;")
        layout.addWidget(thumb)

        text = QWidget()
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        title = song.get("title", "?")
        title_label = QLabel(title[:55] + ("..." if len(title) > 55 else ""))
        title_label.setStyleSheet("font-weight: 600;")
        if is_missing:
            title_label.setStyleSheet("font-weight: 600; color: gray;")
        text_layout.addWidget(title_label)
        subtitle = "Artık kütüphanede yok" if is_missing else \
            f"{song.get('uploader', '')} • {playlist_name}"
        sub_label = QLabel(subtitle)
        sub_label.setObjectName("Muted")
        text_layout.addWidget(sub_label)
        layout.addWidget(text, stretch=1)

        dur_label = QLabel(format_time((song.get("duration") or 0) * 1000))
        dur_label.setObjectName("Muted")
        layout.addWidget(dur_label)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedWidth(24)
        remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.q_idx))
        layout.addWidget(remove_btn)

    def mouseDoubleClickEvent(self, event):
        if not self.property("missing"):
            self.playRequested.emit(self.q_idx)
        super().mouseDoubleClickEvent(event)


class LibraryView(QWidget):
    addSongRequested = Signal()          # arama diyaloğunu açması için MainWindow'a haber verir
    roomQueueRequested = Signal(dict)    # Birlikte Dinle ortak sırasına ekle
    startRadioRequested = Signal(dict)   # Şarkı Radyosu isteği
    artistRequested = Signal(str)        # Sanatçı detay sayfasına git isteği

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine,
                 thumbnails: ThumbnailService | None = None, paths=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.smart_rules_provider = lambda: []   # MainWindow ayarlardan bağlar
        self.thumbnails = thumbnails
        self.paths = paths
        self._mode = "playlist"  # "playlist" | "liked" | "queue" | akıllı modlar
        self._current_songs_index: list[tuple[str, int, dict]] = []  # her satır için (playlist, index, song)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = QLabel("Çalma Listesi")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Bu listede ara…")
        self.filter_edit.setFixedWidth(220)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._render)
        self.filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        header.addWidget(self.filter_edit)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Sırala: Varsayılan", "default")
        self.sort_combo.addItem("Sırala: İsim (A-Z)", "name")
        self.sort_combo.addItem("Sırala: Sanatçı (A-Z)", "uploader")
        self.sort_combo.addItem("Sırala: Süre (uzun→kısa)", "duration")
        self.sort_combo.addItem("Sırala: Eklenme Tarihi (yeni→eski)", "date")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header.addWidget(self.sort_combo)

        self.add_btn = QPushButton("＋ Şarkı Ekle")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self.addSongRequested.emit)
        header.addWidget(self.add_btn)

        self.clear_queue_btn = QPushButton("🗑 Kuyruğu Temizle")
        self.clear_queue_btn.clicked.connect(self.store.clear_queue)
        self.clear_queue_btn.setVisible(False)
        header.addWidget(self.clear_queue_btn)

        self.batch_delete_btn = QPushButton("🗑 Seçilenleri Sil")
        self.batch_delete_btn.setObjectName("Primary")
        self.batch_delete_btn.clicked.connect(self._delete_selected)
        self.batch_delete_btn.setVisible(False)
        header.addWidget(self.batch_delete_btn)

        # ==========================================
        # KARIŞIK ÇAL — modern cam efektli (Secondary) stil
        # ==========================================
        self.shuffle_play_btn = QPushButton("🔀 Karışık Çal")
        self.shuffle_play_btn.setObjectName("Secondary")
        self.shuffle_play_btn.setCursor(Qt.PointingHandCursor)
        self.shuffle_play_btn.clicked.connect(self._play_shuffled)
        header.addWidget(self.shuffle_play_btn)

        layout.addLayout(header)

        # --- Playlist başlık kartı (mockup: büyük kapak + ad + eylemler) ---
        self.playlist_header = self._build_playlist_header()
        layout.addWidget(self.playlist_header)
        self.playlist_header.setVisible(False)

        # --- Sütun başlıkları (# SIRALA | BAŞLIK | SANATÇI | ⏱) ---
        self.columns_row = self._build_columns_row()
        layout.addWidget(self.columns_row)
        self.columns_row.setVisible(False)

        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        layout.addWidget(self.count_label)

        self.list_widget = _QueueList()
        self.list_widget.reordered.connect(self._reorder_queue)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget, stretch=1)

        # Sanal liste: yalnız görünür satırlar için SongRow widget'ı kurulur.
        self._live_rows: set[int] = set()        # widget'ı kurulu satır indexleri
        self._populating = False
        self._keep_scroll_on_render = False
        # Yapı değişimleri (beğeni, indirme bitişi, toplu ekleme…) art arda gelebilir;
        # her biri için listeyi baştan kurmak yerine tek bir yeniden çizime indirilir.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(40)
        self._render_timer.timeout.connect(self._run_scheduled_render)
        self.list_widget.verticalScrollBar().valueChanged.connect(
            lambda _v: self._populate_visible())
        self.store.playlistsChanged.connect(self._schedule_render)
        self.store.activePlaylistChanged.connect(lambda _: self._maybe_refresh_on_active_change())
        self.store.queueChanged.connect(self._on_queue_changed)
        self._playing = False  # MainWindow playStateChanged ile besler
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    # --- Playlist başlık kartı ---
    def _build_playlist_header(self) -> QWidget:
        from PySide6.QtWidgets import QFrame

        card = QFrame()
        card.setObjectName("PlaylistCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(18)

        # Sol: kapak + değiştir butonu
        cover_box = QVBoxLayout()
        cover_box.setSpacing(6)
        self.ph_cover = QLabel("🎵")
        self.ph_cover.setFixedSize(110, 110)
        self.ph_cover.setAlignment(Qt.AlignCenter)
        self.ph_cover.setStyleSheet("background: #444; border-radius: 10px; font-size: 36px;")
        cover_box.addWidget(self.ph_cover)
        self.ph_cover_btn = QPushButton("🖼 Kapağı Değiştir")
        self.ph_cover_btn.setObjectName("Chip")
        self.ph_cover_btn.setCursor(Qt.PointingHandCursor)
        self.ph_cover_btn.clicked.connect(self._change_cover)
        cover_box.addWidget(self.ph_cover_btn, alignment=Qt.AlignHCenter)
        row.addLayout(cover_box)

        # Orta: ad + meta
        info_box = QVBoxLayout()
        info_box.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.ph_title = QLabel("")
        ph_font = QFont()
        ph_font.setPixelSize(24)
        ph_font.setBold(True)
        self.ph_title.setFont(ph_font)
        title_row.addWidget(self.ph_title)
        self.ph_rename_btn = QPushButton("✏")
        self.ph_rename_btn.setFixedWidth(30)
        self.ph_rename_btn.setToolTip("Listeyi yeniden adlandır")
        self.ph_rename_btn.setCursor(Qt.PointingHandCursor)
        self.ph_rename_btn.clicked.connect(self._rename_active_playlist)
        title_row.addWidget(self.ph_rename_btn)
        title_row.addStretch(1)
        info_box.addLayout(title_row)

        self.ph_meta = QLabel("")
        self.ph_meta.setObjectName("Muted")
        info_box.addWidget(self.ph_meta)

        self.ph_creator = QLabel(f"♪ {APP_DISPLAY_NAME} tarafından oluşturuldu")
        self.ph_creator.setObjectName("Muted")
        info_box.addWidget(self.ph_creator)
        info_box.addStretch(1)
        row.addLayout(info_box, stretch=1)

        # Sağ: eylem butonları
        actions = QVBoxLayout()
        actions.setSpacing(8)
        play_row = QHBoxLayout()
        play_row.setSpacing(8)
        self.ph_play_btn = QPushButton("▶  Oynat")
        self.ph_play_btn.setObjectName("Primary")
        self.ph_play_btn.setCursor(Qt.PointingHandCursor)
        self.ph_play_btn.clicked.connect(self._play_active_from_start)
        play_row.addWidget(self.ph_play_btn)
        actions.addLayout(play_row)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        self.ph_cover_icon = QPushButton("🖼")
        self.ph_cover_icon.setObjectName("RoundSmall")
        self.ph_cover_icon.setToolTip("Kapağı değiştir")
        self.ph_cover_icon.setCursor(Qt.PointingHandCursor)
        self.ph_cover_icon.clicked.connect(self._change_cover)
        btn_row2.addWidget(self.ph_cover_icon)

        self.ph_delete_btn = QPushButton("🗑")
        self.ph_delete_btn.setObjectName("RoundSmall")
        self.ph_delete_btn.setToolTip("Listeyi boşalt / sil")
        self.ph_delete_btn.setCursor(Qt.PointingHandCursor)
        self.ph_delete_btn.clicked.connect(self._show_delete_menu)
        btn_row2.addWidget(self.ph_delete_btn)

        self.ph_download_btn = QPushButton("⬇")
        self.ph_download_btn.setObjectName("RoundSmall")
        self.ph_download_btn.setToolTip("Tümünü çevrimdışı indir")
        self.ph_download_btn.setCursor(Qt.PointingHandCursor)
        self.ph_download_btn.clicked.connect(self._download_all)
        btn_row2.addWidget(self.ph_download_btn)
        btn_row2.addStretch(1)
        actions.addLayout(btn_row2)
        row.addLayout(actions)

        return card

    # --- Sütun başlıkları ---
    def _build_columns_row(self) -> QWidget:
        row = QWidget()
        cols = QHBoxLayout(row)
        cols.setContentsMargins(12, 0, 12, 0)
        cols.setSpacing(12)

        self.sort_pill = QPushButton("# SIRALA")
        self.sort_pill.setObjectName("SortPill")
        self.sort_pill.setCursor(Qt.PointingHandCursor)
        self.sort_pill.setToolTip("Sıralama modunu değiştirir")
        self.sort_pill.clicked.connect(self._cycle_sort)
        cols.addWidget(self.sort_pill)

        # Tıklanabilir sütun başlıkları: tıklanınca o sütuna göre sıralar,
        # aktif sütun vurgu rengiyle gösterilir
        self.col_title_btn = QPushButton("BAŞLIK")
        self.col_title_btn.setObjectName("ColHeader")
        self.col_title_btn.setCursor(Qt.PointingHandCursor)
        self.col_title_btn.setToolTip("Başlığa göre sırala (A-Z)")
        self.col_title_btn.clicked.connect(
            lambda: self.sort_combo.setCurrentIndex(self.sort_combo.findData("name")))
        cols.addWidget(self.col_title_btn)
        cols.addStretch(1)

        self.col_artist_btn = QPushButton("SANATÇI")
        self.col_artist_btn.setObjectName("ColHeader")
        self.col_artist_btn.setCursor(Qt.PointingHandCursor)
        self.col_artist_btn.setToolTip("Sanatçıya göre sırala (A-Z)")
        self.col_artist_btn.clicked.connect(
            lambda: self.sort_combo.setCurrentIndex(self.sort_combo.findData("uploader")))
        self.col_artist_btn.setFixedWidth(170)
        cols.addWidget(self.col_artist_btn)

        dur_h = QLabel("⏱")
        dur_h.setObjectName("SectionHeader")
        dur_h.setFixedWidth(96)
        dur_h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cols.addWidget(dur_h)
        return row

    SORT_LABELS = {"default": "# SIRALA", "name": "# İSİM", "uploader": "# SANATÇI",
                   "duration": "# SÜRE", "date": "# TARİH"}

    def _cycle_sort(self):
        idx = (self.sort_combo.currentIndex() + 1) % self.sort_combo.count()
        self.sort_combo.setCurrentIndex(idx)

    def _on_sort_changed(self, _idx: int):
        self.sort_pill.setText(self.SORT_LABELS.get(self.sort_combo.currentData(), "# SIRALA"))
        self._update_col_header_active()
        self._render()

    def _update_col_header_active(self):
        """Hangi sütunda sıralanıyorsa o başlık vurgu renginde gösterilir."""
        mode = self.sort_combo.currentData()
        for btn, key in ((self.col_title_btn, "name"), (self.col_artist_btn, "uploader")):
            btn.setProperty("active", "true" if mode == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # --- Playlist başlık eylemleri ---
    def _play_active_from_start(self):
        name = self.store.active_playlist
        if not self.store.playlists.get(name):
            self.store.statusMessage.emit("Bu liste boş, önce şarkı ekle.", "warning")
            return
        self.playback.play_song_at_index(name, 0)

    def _rename_active_playlist(self):
        old = self.store.active_playlist
        new, ok = QInputDialog.getText(self, "Yeniden Adlandır", "Yeni ad:", QLineEdit.Normal, old)
        if not ok or not new.strip() or new.strip() == old:
            return
        success, err = self.store.rename_playlist(old, new.strip())
        if not success and err:
            QMessageBox.warning(self, "Hata", err)

    def _change_cover(self):
        if self.paths is None:
            return
        from mustiefly_qt.helpers.covers import pick_and_save_cover
        pick_and_save_cover(self.store, self.store.active_playlist,
                            self.paths.covers_dir, self)

    def _show_delete_menu(self):
        from PySide6.QtWidgets import QMenu
        name = self.store.active_playlist
        menu = QMenu(self)
        clear_action = menu.addAction("🧹  Listeyi Boşalt (geri alınabilir)")
        delete_action = menu.addAction("🗑  Listeyi Sil")
        chosen = menu.exec(self.ph_delete_btn.mapToGlobal(
            self.ph_delete_btn.rect().bottomLeft()))
        if chosen == clear_action:
            self.store.clear_playlist(name)
            self.store.statusMessage.emit(f"'{name}' listesi boşaltıldı.", "info")
        elif chosen == delete_action:
            confirm = QMessageBox.question(
                self, "Listeyi Sil", f"\"{name}\" listesi silinsin mi?")
            if confirm == QMessageBox.Yes:
                success, err = self.store.delete_playlist(name)
                if not success and err:
                    QMessageBox.warning(self, "Hata", err)

    def _download_all(self):
        name = self.store.active_playlist
        songs = self.store.playlists.get(name, [])
        # Yerel dosyalar (local://) zaten diskte — indirme kuyruğuna alınmaz
        pending = [i for i, s in enumerate(songs)
                   if offline_path_for(s) is None and not s.get("local_path")]
        if not pending:
            if any(s.get("local_path") for s in songs):
                self.store.statusMessage.emit(
                    "Yerel dosyalar zaten çevrimdışı; indirilecek YouTube şarkısı yok.", "info")
            else:
                self.store.statusMessage.emit("Tüm şarkılar zaten çevrimdışı.", "info")
            return
        # Buton geri bildirimi: indirme arka planda sürerken kilitli kalır
        btn = self.ph_download_btn
        btn.setEnabled(False)
        btn.setText("⏬")
        btn.setToolTip(f"{len(pending)} şarkı indiriliyor…")
        QTimer.singleShot(2500, lambda: (
            btn.setEnabled(True), btn.setText("⬇"),
            btn.setToolTip("Tümünü çevrimdışı indir")))
        for i in pending:
            self.playback.download_song_for_offline(name, i)
        self.store.statusMessage.emit(
            f"⬇ {len(pending)} şarkı çevrimdışı indirme kuyruğuna alındı.", "info")

    def _refresh_playlist_header(self):
        name = self.store.active_playlist
        songs = self.store.playlists.get(name, [])
        self.ph_title.setText(name)
        dur = format_playlist_duration(songs)
        meta = f"{len(songs)} şarkı"
        if dur:
            meta += f"  •  {dur}"
        self.ph_meta.setText(meta)
        # Hero gradient: liste adından türetilen renkle başlık kartının arka planı
        base = cover_color_for(name)
        self.playlist_header.setStyleSheet(
            "#PlaylistCard {"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {shade_color(base, 0.65)}, stop:0.55 {shade_color(base, 0.32)},"
            f" stop:1 {shade_color(base, 0.12)});"
            " border-radius: 20px; }")
        pm = playlist_cover_pixmap(self.store, self.thumbnails, name, songs, size=220)
        if pm is not None and not pm.isNull():
            self.ph_cover.setPixmap(pm)
            self.ph_cover.setText("")
            self.ph_cover.setStyleSheet("border-radius: 16px;")
        else:
            self.ph_cover.setPixmap(QPixmap())
            self.ph_cover.setText("🎵")
            self.ph_cover.setStyleSheet(
                f"background: {base}; border-radius: 16px; font-size: 36px;")

    def set_playing_state(self, playing: bool):
        """MainWindow playStateChanged bağlar; çalan satırın ekolayzer
        animasyonunu senkron tutar."""
        self._playing = playing
        self.refresh_current_row_highlight()

    # --- Görünüm değiştirme ---
    def show_playlist(self, name: str):
        self._mode = "playlist"
        self.store.switch_playlist(name)
        self._apply_mode_ui(title=name, show_add=True, show_shuffle=True, show_clear=False)
        self.filter_edit.clear()
        self._render()

    def show_liked(self):
        self._mode = "liked"
        self._apply_mode_ui(title="💚 Beğenilenler", show_add=False, show_shuffle=True, show_clear=False)
        self.filter_edit.clear()
        self._render()

    def show_queue(self):
        self._mode = "queue"
        self._apply_mode_ui(title="📃 Sıradaki", show_add=False, show_shuffle=False, show_clear=True)
        self._render()

    def show_smart(self, mode: str):
        """Akıllı (otomatik) listeler: yerleşikler (smart_lists.BUILTIN_TITLES)
        ve kullanıcı kuralları ("rule:<ad>")."""
        self._mode = mode
        title = smart_lists.BUILTIN_TITLES.get(mode) or (
            "🧩 " + mode[5:] if mode.startswith("rule:") else
            "✨ " + self._mix_title(mode[4:]) if mode.startswith("mix:") else "Akıllı Liste")
        self._apply_mode_ui(title=title, show_add=False, show_shuffle=True, show_clear=False)
        self.filter_edit.clear()
        self._render()

    def _apply_mode_ui(self, title: str, show_add: bool, show_shuffle: bool, show_clear: bool):
        self.title_label.setText(title)
        self.add_btn.setVisible(show_add)
        self.shuffle_play_btn.setVisible(show_shuffle)
        self.clear_queue_btn.setVisible(show_clear)
        self.filter_edit.setVisible(self._mode != "queue")
        is_playlist = self._mode == "playlist"
        # Playlist modunda başlık kartı + sütun başlıkları devreye girer
        self.title_label.setVisible(not is_playlist)
        self.playlist_header.setVisible(is_playlist)
        self.columns_row.setVisible(self._mode in ("playlist", "liked"))
        self.count_label.setVisible(not is_playlist)
        # Sıralama combo'su sadece playlist/beğenilenlerde anlamlıdır; akıllı
        # listelerin kendi doğal sırası vardır (çalma sayısı, tarih vb.)
        self.sort_combo.setVisible(self._mode in ("playlist", "liked"))
        self._update_col_header_active()
        is_queue = self._mode == "queue"
        self.list_widget.set_interactive(is_queue)
        self.list_widget.setSelectionMode(
            QAbstractItemView.SingleSelection if is_queue else QAbstractItemView.ExtendedSelection)
        self.batch_delete_btn.setVisible(False)

    def _maybe_refresh_on_active_change(self):
        if self._mode == "playlist":
            self.title_label.setText(self.store.active_playlist)
            self._render()

    def _on_queue_changed(self):
        if self._mode == "queue":
            self._render()

    # --- Kaynak seçimi ---
    def _source_songs(self) -> list[tuple[str, int, dict]]:
        if self._mode == "liked":
            return self.store.liked_songs
        if self._is_smart_mode():
            return self._smart_songs()
        name = self.store.active_playlist
        return [(name, i, s) for i, s in enumerate(self.store.playlists.get(name, []))]

    def _is_smart_mode(self) -> bool:
        return (self._mode in smart_lists.BUILTIN_TITLES
                or self._mode.startswith(("rule:", "mix:")))

    def _find_mix(self, mix_id: str):
        from mustiefly_qt.views.mixes_view import build_for
        return next((m for m in build_for(self.store, self.playback) if m.id == mix_id), None)

    def _mix_title(self, mix_id: str) -> str:
        mix = self._find_mix(mix_id)
        return mix.title if mix else "Mix"

    def _smart_songs(self) -> list[tuple[str, int, dict]]:
        """Tüm playlistler genelinde akıllı listeler (elle bakım gerektirmez)."""
        all_refs = [(name, idx, s) for name, songs in self.store.playlists.items()
                    for idx, s in enumerate(songs)]
        history = getattr(self.playback, "history", None)
        if self._mode.startswith("mix:"):
            mix = self._find_mix(self._mode[4:])
            return list(mix.refs) if mix else []
        if self._mode.startswith("rule:"):
            wanted = self._mode[5:].casefold()
            for rule in smart_lists.sanitize_rules(self.smart_rules_provider()):
                if rule["name"].casefold() == wanted:
                    return smart_lists.apply_rule(rule, all_refs, history)
            return []
        return smart_lists.build_builtin(self._mode, all_refs, history)

    # --- Render ---
    ROW_HEIGHT = 52        # SongRow.setFixedHeight(52) ile aynı olmalı
    _ROW_BUFFER = 12       # görünür alanın üstünde/altında önceden kurulan satır sayısı
    _ROW_KEEP = 150        # görünür alandan bu kadar uzaktaki satırların widget'ı serbest bırakılır

    def _schedule_render(self):
        """Store sinyalleri için: kısa süre içindeki tüm tetiklemeleri tek çizime indirir
        ve kaydırma konumunu korur (beğenince liste başa atlamaz)."""
        self._keep_scroll_on_render = True
        self._render_timer.start()

    def _run_scheduled_render(self):
        keep = self._keep_scroll_on_render
        self._keep_scroll_on_render = False
        bar = self.list_widget.verticalScrollBar()
        pos = bar.value() if keep else 0
        self._render()
        if keep and pos:
            self.list_widget.doItemsLayout()
            bar.setValue(pos)
            self._populate_visible()

    def _render(self):
        self._render_timer.stop()
        self._filter_timer.stop()
        self._keep_scroll_on_render = False
        self.list_widget.setUpdatesEnabled(False)
        try:
            self._render_inner()
        finally:
            self.list_widget.setUpdatesEnabled(True)

    def _render_inner(self):
        self.list_widget.clear()
        self._live_rows.clear()
        if self._mode == "playlist":
            self._refresh_playlist_header()
        if self._mode == "queue":
            self._current_songs_index = []
            self._render_queue()
            return

        songs = self._source_songs()
        query = self.filter_edit.text().strip().lower() if not self.filter_edit.isHidden() else ""
        if query:
            songs = [t for t in songs if query in t[2].get("title", "").lower()
                     or query in t[2].get("uploader", "").lower()]

        sort_mode = self.sort_combo.currentData() if not self.sort_combo.isHidden() else "default"
        if sort_mode == "name":
            songs = sorted(songs, key=lambda t: t[2].get("title", "").lower())
        elif sort_mode == "uploader":
            songs = sorted(songs, key=lambda t: t[2].get("uploader", "").lower())
        elif sort_mode == "duration":
            songs = sorted(songs, key=lambda t: t[2].get("duration") or 0, reverse=True)
        elif sort_mode == "date":
            songs = sorted(songs, key=lambda t: t[2].get("added_date") or "", reverse=True)

        self._current_songs_index = songs
        self.count_label.setText(f"{len(songs)} şarkı")

        # Ucuz yer tutucu öğeler: asıl SongRow widget'ları _populate_visible() ile
        # yalnız ekranda görünen aralık için kurulur.
        row_size = QSize(0, self.ROW_HEIGHT)
        for _ in songs:
            item = QListWidgetItem()
            item.setSizeHint(row_size)
            self.list_widget.addItem(item)

        if songs:
            self._populate_visible()
        else:
            empty = self._build_empty_state()
            item = QListWidgetItem()
            item.setSizeHint(empty.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, empty)

    def _make_row(self, i: int) -> SongRow:
        playlist_name, idx, song = self._current_songs_index[i]
        row = SongRow(idx, song, row_number=i + 1)
        row.playlist_name = playlist_name  # sürükle-bırak kaynağı
        row.set_current(
            playlist_name == self.playback.playing_playlist and idx == self.playback.current_index,
            self._playing,
        )
        row.playRequested.connect(lambda i, pl=playlist_name: self.playback.play_song_at_index(pl, i))
        row.likeToggled.connect(lambda i, pl=playlist_name: self.store.toggle_like(pl, i))
        row.removeRequested.connect(lambda i, pl=playlist_name: self.store.remove_song(pl, i))
        row.downloadRequested.connect(
            lambda i, pl=playlist_name: self.playback.download_song_for_offline(pl, i))
        row.addToQueueRequested.connect(
            lambda i, pl=playlist_name, s=song: self.store.add_to_queue(pl, i, s))
        row.playNextRequested.connect(
            lambda i, pl=playlist_name, s=song: self.store.add_to_queue_next(pl, i, s))
        row.startRadioRequested.connect(self.startRadioRequested.emit)
        row.moveRequested.connect(
            lambda i, pl=playlist_name: self._move_song_dialog(pl, i))
        row.addToRoomQueueRequested.connect(
            lambda _i, s=song: self.roomQueueRequested.emit(s))
        row.artistRequested.connect(self.artistRequested.emit)
        return row

    def _populate_visible(self):
        """Görünür aralık (+ tampon) için SongRow kurar, uzaktakileri serbest bırakır."""
        if self._populating or self._mode == "queue":
            return
        n = len(self._current_songs_index)
        lw = self.list_widget
        if n == 0 or lw.count() != n:
            return
        self._populating = True
        try:
            top = lw.indexAt(QPoint(4, 2))
            first = top.row() if top.isValid() else 0
            height = lw.viewport().height()
            visible = height // self.ROW_HEIGHT + 1 if height > 50 else 25
            lo = max(0, first - self._ROW_BUFFER)
            hi = min(n - 1, first + visible + self._ROW_BUFFER)
            for i in range(lo, hi + 1):
                if i in self._live_rows:
                    continue
                row = self._make_row(i)
                lw.setItemWidget(lw.item(i), row)
                self._live_rows.add(i)
                self._request_thumbnail(row, self._current_songs_index[i][2])
            far = [i for i in self._live_rows
                   if i < lo - self._ROW_KEEP or i > hi + self._ROW_KEEP]
            for i in far:
                lw.removeItemWidget(lw.item(i))
                self._live_rows.discard(i)
        finally:
            self._populating = False

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, self._populate_visible)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._populate_visible)

    def _build_empty_state(self) -> QWidget:
        """Liste/beğenilenler/akıllı liste boşken yol gösteren ekran."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)

        if self._mode == "playlist":
            icon = "🎵"
            title = "Bu liste boş"
            desc = "İlk şarkını ekleyerek başla."
            btn_text, cb = "＋ İlk Şarkını Ekle", lambda: self.addSongRequested.emit()
        elif self._mode == "liked":
            icon = "💚"
            title = "Henüz beğenilen şarkı yok"
            desc = "Şarkı satırlarının yanındaki ♡ kalbe tıklaman yeterli."
            btn_text, cb = None, None
        elif self._mode == "forgotten":
            icon = "💤"
            title = "Unutulmuş şarkı yok"
            desc = f"{smart_lists.FORGOTTEN_DAYS} günden uzun süredir dinlemediğin şarkılar burada görünür."
            btn_text, cb = None, None
        elif self._mode == "fav_artists":
            icon = "🎤"
            title = "Favori sanatçıların henüz belli değil"
            desc = "Son 90 günde dinlediğin sanatçılar biriktikçe bu liste oluşur."
            btn_text, cb = None, None
        elif self._mode.startswith("mix:"):
            icon = "✨"
            title = "Bu Mix için yeterli veri yok"
            desc = "Biraz daha dinledikçe Mix'ler oluşur."
            btn_text, cb = None, None
        elif self._mode.startswith("rule:"):
            icon = "🧩"
            title = "Bu kurala uyan şarkı yok"
            desc = "Kuralı Kural Listeleri'nden düzenleyebilirsin."
            btn_text, cb = None, None
        else:
            icon = "🕒"
            title = "Burada henüz bir şey yok"
            desc = "Şarkı çaldıkça bu liste kendiliğinden oluşur."
            btn_text, cb = None, None

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_font = QFont()
        icon_font.setPixelSize(44)
        icon_label.setFont(icon_font)
        v.addWidget(icon_label)

        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPixelSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        v.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setObjectName("Muted")
        desc_label.setAlignment(Qt.AlignCenter)
        v.addWidget(desc_label)

        if btn_text:
            btn = QPushButton(btn_text)
            btn.setObjectName("Primary")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(cb)
            v.addWidget(btn, alignment=Qt.AlignHCenter)
        return w

    def _move_song_dialog(self, playlist_name: str, index: int):
        targets = [n for n in self.store.playlists if n != playlist_name]
        if not targets:
            self.store.statusMessage.emit(
                "Taşınacak başka bir liste yok. Önce yeni bir liste oluştur.", "warning")
            return
        target, ok = QInputDialog.getItem(
            self, "Başka Listeye Taşı", "Hedef liste seç:", targets, 0, False)
        if not ok:
            return
        success, err = self.store.move_song_to_playlist(playlist_name, index, target)
        if success:
            self.store.statusMessage.emit(
                f"📂 Şarkı '{target}' listesine taşındı.", "success")
        else:
            self.store.statusMessage.emit(f"⚠️ Şarkı taşınmadı: {err}", "warning")

    # --- Çoklu seçim + toplu silme ---
    def _on_selection_changed(self):
        if self._mode == "queue":
            self.batch_delete_btn.setVisible(False)
            return
        n = len(self.list_widget.selectedItems())
        self.batch_delete_btn.setVisible(n > 1)
        if n > 1:
            self.batch_delete_btn.setText(f"🗑 Seçilenleri Sil ({n})")

    def _delete_selected(self):
        items = self.list_widget.selectedItems()
        refs: list[tuple[str, int]] = []
        for it in items:
            i = self.list_widget.row(it)
            if 0 <= i < len(self._current_songs_index):
                pl_name, idx, _ = self._current_songs_index[i]
                refs.append((pl_name, idx))
        if len(refs) < 2:
            return
        confirm = QMessageBox.question(
            self, "Şarkıları Sil",
            f"{len(refs)} şarkı silinsin mi?\n(Silme işlemini 'Geri Al' ile geri alabilirsin.)")
        if confirm != QMessageBox.Yes:
            return
        n = self.store.remove_songs_batch(refs)
        self.store.statusMessage.emit(f"🗑 {n} şarkı silindi.", "info")

    def _render_queue(self):
        self._current_songs_index = []
        self._queue_offset = 0
        q_len = len(self.store.manual_queue)
        self.count_label.setText(f"{q_len} şarkı kuyrukta")

        # "ŞİMDİ ÇALIYOR" bilgi şeridi
        pp = self.playback.playing_playlist
        if pp is not None and 0 <= self.playback.current_index < len(self.store.playlists.get(pp, [])):
            now_song = self.store.playlists[pp][self.playback.current_index]
            banner_item = QListWidgetItem()
            banner = QLabel(f"ŞİMDİ ÇALIYOR  •  {now_song.get('title', '')}")
            banner.setStyleSheet(
                "color: #1DB954; font-weight: bold; padding: 8px 12px;"
                "background: rgba(29, 185, 84, 30); border-radius: 8px;")
            banner_item.setSizeHint(banner.sizeHint())
            self.list_widget.addItem(banner_item)
            self.list_widget.setItemWidget(banner_item, banner)
            self._queue_offset = 1

        if not self.store.manual_queue:
            hint = QListWidgetItem()
            label = QLabel("Kuyruk boş. Bir şarkının ⋮ menüsünden \"Kuyruğa Ekle\" diyebilirsin.")
            label.setObjectName("Muted")
            label.setAlignment(Qt.AlignCenter)
            label.setContentsMargins(0, 24, 0, 0)
            hint.setSizeHint(label.sizeHint())
            self.list_widget.addItem(hint)
            self.list_widget.setItemWidget(hint, label)
            return

        for q_idx, (pl_name, orig_idx, song) in enumerate(self.store.manual_queue):
            real_pl, _ = self.store.locate_song(pl_name, orig_idx, song)
            is_missing = real_pl is None
            display_playlist = real_pl or pl_name
            item = QListWidgetItem()
            row = QueueRow(q_idx, display_playlist, song, is_missing)
            item.setSizeHint(row.sizeHint())
            row.playRequested.connect(self._play_from_queue)
            row.removeRequested.connect(self.store.remove_from_queue)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

    def _play_from_queue(self, q_idx: int):
        """Kuyruktaki bir şarkıyı çalar; öncekiler 'geçilmiş' sayılır."""
        real_pl, real_idx = self.store.play_from_queue(q_idx)
        if real_pl is None:
            self.store.statusMessage.emit(
                "⚠️ Bu şarkı artık kütüphanede yok.", "warning")
            return
        self.playback.play_song_at_index(real_pl, real_idx)

    def _reorder_queue(self, from_idx: int, to_idx: int):
        offset = getattr(self, "_queue_offset", 0)
        from_idx -= offset
        to_idx -= offset
        queue = self.store.manual_queue
        if not (0 <= from_idx < len(queue)):
            return
        to_idx = max(0, min(to_idx, len(queue) - 1))
        if from_idx == to_idx:
            self._render()
            return
        item = queue.pop(from_idx)
        queue.insert(to_idx, item)
        self._render()

    # --- Thumbnail'ler ---
    def _request_thumbnail(self, row: SongRow, song: dict):
        if self.thumbnails is None:
            return
        pm = self.thumbnails.pixmap_for(song, 36)
        if pm is not None:
            row.set_thumbnail(pm)

    def _on_thumbnail_ready(self, key: str):
        """Bir thumbnail indiğinde sadece eşleşen görünür satırları günceller —
        tüm listeyi yeniden oluşturmaz (O(n²) davranışını önler)."""
        for i in list(self._live_rows):
            item = self.list_widget.item(i)
            row = self.list_widget.itemWidget(item) if item is not None else None
            if isinstance(row, SongRow) and row.song.get("webpage_url") == key:
                pm = self.thumbnails.pixmap_for(row.song, 36) if self.thumbnails else None
                if pm is not None:
                    row.set_thumbnail(pm)

    def scroll_to_playing(self) -> bool:
        """Listedeki çalan şarkının satırına kaydırıp seçer (sıralamadan bağımsız
        olarak _current_songs_index üzerinden çözülür)."""
        pp = self.playback.playing_playlist
        ci = self.playback.current_index
        if pp is None or ci < 0:
            return False
        return self.scroll_to_song(pp, ci)

    def scroll_to_song(self, playlist_name: str, index: int) -> bool:
        """Verilen şarkının satırına kaydırır; bulunamazsa False döner."""
        for i, (pl_name, idx, _s) in enumerate(self._current_songs_index):
            if pl_name == playlist_name and idx == index:
                item = self.list_widget.item(i)
                if item is None:
                    return False
                self.list_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                self.list_widget.setCurrentRow(i)
                return True
        return False

    def refresh_current_row_highlight(self):
        pp, ci = self.playback.playing_playlist, self.playback.current_index
        for i in list(self._live_rows):
            item = self.list_widget.item(i)
            row = self.list_widget.itemWidget(item) if item is not None else None
            if isinstance(row, SongRow) and i < len(self._current_songs_index):
                is_cur = self._current_songs_index[i][0] == pp and row.index == ci
                if is_cur:
                    # çalma durumu da iletilir (eskiden iletilmediği için duraklatınca
                    # satırdaki ekolayzer animasyonu durmuyordu)
                    row.set_current(True, self._playing)
                elif row._is_current:
                    row.set_current(False, False)

    def _play_shuffled(self):
        songs = self._source_songs()
        if not songs:
            return
        playlist_name, idx, _ = random.choice(songs)
        self.playback.enable_shuffle()
        self.playback.play_song_at_index(playlist_name, idx)

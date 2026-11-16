from __future__ import annotations


from dataclasses import replace

from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGraphicsOpacityEffect, QHBoxLayout, QLineEdit,
    QMainWindow, QMenuBar, QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget,
    QTextEdit, QVBoxLayout, QWidget, QSystemTrayIcon, QMenu,
)
from PySide6.QtCore import QAbstractAnimation

from mustiefly_qt.helpers.brand_icon import build_icon
from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME, APP_VERSION
from mustiefly_qt.helpers import app_update
from mustiefly_qt.helpers.i18n import apply_language, translate_widget
from mustiefly_qt.services.app_updater import AppUpdater
from mustiefly_qt.helpers.constants import (
    AppPaths, DEFAULT_THEME_KEY, DISCORD_CLIENT_ID_DEFAULT, THEMES, shade_color,
)
from mustiefly_qt.helpers.backup import export_library_dialog, import_library_dialog
from mustiefly_qt.helpers.dynamic_theme import dominant_accent_color
from mustiefly_qt.helpers.local_files import pick_and_add_local_files
from mustiefly_qt.services.discord_rpc import DiscordRPCService
from mustiefly_qt.services.listen_together import ListenTogether
from mustiefly_qt.services.download_manager import DownloadManager
from mustiefly_qt.services.media_keys import GlobalMediaKeys
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.smtc import SMTC_AVAILABLE, SMTCService
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.theme import build_qss
from mustiefly_qt.views.bulk_add_dialog import BulkAddDialog
from mustiefly_qt.views.downloads_view import DownloadsView
from mustiefly_qt.views.duplicate_finder_dialog import DuplicateFinderDialog
from mustiefly_qt.views.equalizer_window import EqualizerWindow
from mustiefly_qt.views.explore_view import ExploreView
from mustiefly_qt.views.home_view import HomeView
from mustiefly_qt.views.import_dialogs import (
    SpotifyImportDialog, export_playlist_m3u_dialog, import_playlist_m3u,
    import_youtube_playlist,
)
from mustiefly_qt.views.library_view import LibraryView
from mustiefly_qt.views.library_search_dialog import LibrarySearchDialog
from mustiefly_qt.views.listen_together_dialog import ListenTogetherDialog
from mustiefly_qt.views.lyrics_window import LyricsWindow
from mustiefly_qt.views.mini_player import MiniPlayer
from mustiefly_qt.views.now_playing_panel import NowPlayingPanel
from mustiefly_qt.views.player_bar import PlayerBar
from mustiefly_qt.views.radio_view import RadioView
from mustiefly_qt.views.search_dialog import SearchDialog
from mustiefly_qt.views.settings_dialog import SettingsView
from mustiefly_qt.views.sidebar import SidebarWidget
from mustiefly_qt.views.mixes_view import MixesView
from mustiefly_qt.views.smart_rules_dialog import SmartRulesDialog
from mustiefly_qt.views.stats_view import StatsView
from mustiefly_qt.views.wrapped_view import WrappedView
from mustiefly_qt.widgets.snackbar import UndoSnackbar
from mustiefly_qt.widgets.song_row import SongRow
from mustiefly_qt.helpers.logging_setup import get_logger



log = get_logger(__name__)
class MainWindow(QMainWindow):
    updateNotice = Signal(str)  # arka plandaki yt-dlp güncelleme kontrolünden

    def __init__(self, username: str, paths: AppPaths, settings: dict):
        super().__init__()
        self.username = username
        self.paths = paths
        self.settings = settings

        self.setWindowTitle(f"{APP_DISPLAY_NAME} {APP_VERSION} - {username}")
        self.resize(1250, 780)
        self.setMinimumSize(980, 760)

        # --- Servisler ---
        self.store = PlaylistStore(paths)
        self.store.load()
        self.store.backup_enabled = bool(settings.get("backup_enabled", True))
        self.playback = PlaybackEngine(self.store, paths, settings)
        self.listen = ListenTogether(self.store, self.playback, parent=self)
        self._listen_dialog = None
        self._listen_unread = 0
        self.listen.notice.connect(self._on_status_message)
        self.thumbnails = ThumbnailService(
            settings.get("thumbnail_max_workers"), parent=self,
            disk_cache_dir=paths.cache_dir)
        self.app_updater = AppUpdater(self)
        self._update_manual = False
        self._update_progress = None
        self.app_updater.checkFinished.connect(self._on_app_update_checked)
        self.app_updater.downloadFinished.connect(self._on_app_update_downloaded)
        self.app_updater.downloadFailed.connect(self._on_app_update_failed)
        self.downloads = DownloadManager(self.store, paths, self)
        self.playback.download_manager = self.downloads
        self.downloads.downloadFinished.connect(self._on_download_finished)
        self.downloads.downloadFailed.connect(self._on_download_failed)

        # Discord RPC + Mini Player
        client_id = self.settings.get("discord_client_id", DISCORD_CLIENT_ID_DEFAULT)
        self.discord_rpc = DiscordRPCService(client_id, self.playback, self)
        self.mini_player = MiniPlayer(self.playback)

        # Ekolayzer + Sözler pencereleri (menüden açılır, tek örnek)
        self._eq_window: EqualizerWindow | None = None
        self._lyrics_window: LyricsWindow | None = None

        # Global medya tuşları (ayar açıkken)
        self._media_keys = GlobalMediaKeys(
            lambda: self.playback.toggle_play_pause(),
            self.playback.play_next,
            self.playback.play_previous,
        )
        if settings.get("global_media_keys"):
            self._media_keys.start()

        # Windows medya denetimleri (SMTC): ses açılır penceresi + medya tuşları
        self.smtc: SMTCService | None = None
        if settings.get("smtc_enabled", True) and SMTC_AVAILABLE:
            self._setup_smtc()

        # --- Merkezi düzen ---
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = SidebarWidget(self.store, self.thumbnails, paths)
        body.addWidget(self.sidebar)

        # Sağ kolon: üst çubuk + (görünüm yığını | şu an çalıyor paneli)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        from mustiefly_qt.views.top_bar import TopBar
        self.top_bar = TopBar(username)
        right.addWidget(self.top_bar)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # Görünüm yığını: ana sayfa / kütüphane / radyo / keşfet / istatistik / liste grid'i / indirmeler
        self.library_view = LibraryView(self.store, self.playback, self.thumbnails, paths)
        self.home_view = HomeView(self.store, self.playback, self.thumbnails, username)
        self.radio_view = RadioView(self.store, self.playback, settings, self.save_settings)
        self.explore_view = ExploreView(
            self.store, self.playback, self.thumbnails, paths,
            self.settings, self.save_settings)
        self.library_view.smart_rules_provider = lambda: self.settings.get("smart_rules", [])
        self.wrapped_view = WrappedView(self.playback)
        self.mixes_view = MixesView(self.store, self.playback)
        self.mixes_view.openRequested.connect(lambda mid: self.show_smart_list("mix:" + mid))
        self.stats_view = StatsView(self.store, self.playback, self.thumbnails)
        from mustiefly_qt.views.library_grid import LibraryGridView
        self.library_grid = LibraryGridView(self.store, self.playback, self.thumbnails)
        self.downloads_view = DownloadsView(self.downloads, self.store)
        # Ayarlar artık ayrı bir pencere değil — içerik yığınına eklenen
        # bir sayfa. Geri/İptal ve Kaydet önceki sayfaya döner.
        self.settings_view = SettingsView(self.paths, self.settings, self,
                                          store=self.store, thumbnails=self.thumbnails)
        self.settings_view.backRequested.connect(self._close_settings_view)
        self.settings_view.saved.connect(self._on_settings_saved)
        self._pre_settings_index = 0

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.home_view)      # index 0
        self.view_stack.addWidget(self.library_view)   # index 1
        self.view_stack.addWidget(self.radio_view)     # index 2
        self.view_stack.addWidget(self.explore_view)   # index 3
        self.view_stack.addWidget(self.stats_view)     # index 4
        self.view_stack.addWidget(self.library_grid)   # index 5
        self.view_stack.addWidget(self.downloads_view)  # index 6
        self.view_stack.addWidget(self.settings_view)   # index 7
        self.view_stack.addWidget(self.mixes_view)      # index 8
        self.view_stack.addWidget(self.wrapped_view)    # index 9
        content.addWidget(self.view_stack, stretch=1)

        self.now_playing_panel = NowPlayingPanel(self.store, self.playback, self.thumbnails)
        content.addWidget(self.now_playing_panel)

        right.addLayout(content, stretch=1)
        body.addLayout(right, stretch=1)

        outer.addLayout(body, stretch=1)

        _pb_theme = THEMES.get(settings.get("theme"), THEMES[DEFAULT_THEME_KEY])
        self.player_bar = PlayerBar(self.playback, self.thumbnails, accent=_pb_theme.accent)
        outer.addWidget(self.player_bar)

        # Geri Al snackbar'ı — pencerenin altına sabitlenmiş katman
        self.snackbar = UndoSnackbar(self)
        self.snackbar.hide()
        self._undo_menu_action = None  # _build_menu içinde gerçek değere bağlanır
        self._really_quit = False  # tepsiye küçültme açıkken pencere ✕'i tepsiye indirir
        self._recent_errors: list[str] = []
        self._last_error_text = ""
        self._ytdlp_auto_attempted = False

        self._build_menu()
        self._setup_room_indicator()
        self.library_view.roomQueueRequested.connect(self.listen.add_to_room_queue)

        # --- Sistem Tepsisi ---
        self._setup_system_tray()

        # --- Sinyal bağlantıları ---
        self.sidebar.navSelected.connect(self._on_nav_selected)
        self.sidebar.playlistSelected.connect(self.show_playlist_view)
        self.sidebar.settingsRequested.connect(self._open_settings_dialog)
        self.sidebar.equalizerRequested.connect(self._toggle_equalizer_window)
        self.sidebar.lyricsRequested.connect(self._toggle_lyrics_window)
        self.sidebar.miniPlayerRequested.connect(self._toggle_mini_player)
        self.sidebar.reportRequested.connect(self.open_diagnostics_dialog)
        self.settings_view.diagnosticsRequested.connect(self.open_diagnostics_dialog)
        self.mini_player.closed.connect(self._on_mini_closed)
        self.library_view.addSongRequested.connect(self._open_search_dialog)
        self.store.statusMessage.connect(self._on_status_message)
        self.playback.statusMessage.connect(self._on_status_message)
        self.playback.playError.connect(self.playback.on_play_error)
        self.playback.extractionFailed.connect(self._on_extraction_failed)
        self.playback.songStarted.connect(lambda *_: self.library_view.refresh_current_row_highlight())
        # Şarkı silinince/taşınınca çalan şarkının index'i yeniden çözümlensin
        self.store.playlistsChanged.connect(self.playback.resync_current_index)
        self.playback.playStateChanged.connect(self.now_playing_panel.set_playing_state)
        self.playback.playStateChanged.connect(self.library_view.set_playing_state)

        # Üst çubuk
        self.top_bar.searchSubmitted.connect(
            lambda q: self._open_search_dialog(initial_query=q))
        self.top_bar.addSongRequested.connect(self._open_search_dialog)
        self.top_bar.bulkAddRequested.connect(self._open_bulk_add)
        self.top_bar.importYouTubeRequested.connect(
            lambda: import_youtube_playlist(self.store, self))
        self.top_bar.importSpotifyRequested.connect(
            lambda: SpotifyImportDialog.prompt_and_run(
                self.store, self.settings, self.save_settings, self))
        self.top_bar.importM3URequested.connect(
            lambda: import_playlist_m3u(self.store, self))
        self.top_bar.localFilesRequested.connect(
            lambda: pick_and_add_local_files(self.store, self))
        self.top_bar.notificationsClicked.connect(self._open_settings_dialog)

        # Player bar kısayolları + kütüphane grid'i
        self.player_bar.queueRequested.connect(self.show_queue_view)
        self.player_bar.lyricsRequested.connect(self._toggle_lyrics_window)
        self.player_bar.jumpToPlayingRequested.connect(self._jump_to_playing)
        self.library_grid.openPlaylistRequested.connect(self.show_playlist_view)

        # "Şu An Çalıyor" panelini kapat/aç (ayarda kalıcı)
        self.now_playing_panel.collapseRequested.connect(self._hide_now_playing_panel)
        self.top_bar.panelToggleClicked.connect(self._show_now_playing_panel)
        if not settings.get("now_playing_panel_visible", True):
            self.now_playing_panel.hide()
            self.top_bar.set_panel_toggle_visible(True)

        # Ana Sayfa yönlendirmeleri
        self.home_view.openPlaylistRequested.connect(self.show_playlist_view)
        self.home_view.openLikedRequested.connect(self.show_liked_view)
        self.home_view.playShuffledRequested.connect(self._play_shuffled_from_home)

        # Dinamik tema: çalan şarkının kapağından vurgu rengi
        base_theme = THEMES.get(settings.get("theme"), THEMES[DEFAULT_THEME_KEY])
        self._current_accent = base_theme.accent
        # Tüm uygulamanın QSS'ini yeniden kurmak pahalıdır: şarkı değişimini
        # bloklamasın diye ertelenir ve art arda tetiklenmeler tek işe iner.
        self._accent_timer = QTimer(self)
        self._accent_timer.setSingleShot(True)
        self._accent_timer.setInterval(400)
        self._accent_timer.timeout.connect(self._apply_dynamic_accent)
        self.playback.songStarted.connect(lambda *_: self._accent_timer.start())
        if self.thumbnails is not None:
            # Yalnız ÇALAN şarkının kapağı indiyse rengi tazele (eskiden her
            # thumbnail için görüntü analizi + QSS yenilemesi yapılıyordu)
            self.thumbnails.thumbnailReady.connect(self._on_thumb_for_accent)

        # Arka plan güncelleme kontrolü bildirimi (thread → GUI)
        self.updateNotice.connect(self._on_status_message)
        self.updateNotice.connect(self.top_bar.set_notification)

        # Snackbar geri alma ve hata raporlama
        self.snackbar.undoClicked.connect(self._perform_undo)
        self.snackbar.reportClicked.connect(self.open_diagnostics_dialog)
        self.store.undoAvailable.connect(self._on_undo_available)

        if self.settings.get("language", "tr") != "tr":
            apply_language(self.settings["language"])
            translate_widget(self)

        self.show_home_view()
        self._select_nav_silent("home")
        self.statusBar().showMessage(f"Hoş geldin, {username}!", 4000)

        # --- Oturum geri yükleme (kaldığın liste/şarkı açılışta yüklü gelir) ---
        self._restore_last_session()

    # --- Ayar kaydı (radyo favorileri, Spotify refresh token vb. için ortak yol) ---
    def save_settings(self):
        from mustiefly_qt.auth.service import save_settings_for
        return save_settings_for(self.paths, self.settings)

    # --- Oturum geri yükleme ---
    def _restore_last_session(self):
        if not self.settings.get("restore_session", True):
            return
        session = self.settings.get("last_session")
        if not isinstance(session, dict) or not session.get("playlist"):
            return
        if not self.playback.restore_session(session):
            return
        playlist = session["playlist"]
        if playlist in self.store.playlists and playlist != self.store.active_playlist:
            self.store.switch_playlist(playlist)
        self.show_playlist_view(playlist)
        # Nav vurgusu "home"da kaldı; hepsini temizle (liste görünümü aktif)
        for btn in self.sidebar._nav_buttons.values():
            btn.setProperty("active", "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        pos_ms = int(session.get("position_ms") or 0)
        from mustiefly_qt.helpers.constants import format_time
        extra = f" Kaldığın yerden ({format_time(pos_ms)}) sürer." if pos_ms > 5000 else ""
        self.statusBar().showMessage(
            f"Son dinlediğin şarkı yüklendi — ▶ ile devam et.{extra}", 8000)

    # --- İndirme yöneticisi bildirimleri ---
    def _on_download_finished(self, song: dict, _path: str, already_cached: bool):
        if not already_cached:
            self._on_status_message(
                f"⬇ '{song.get('title', '?')}' çevrimdışı indirildi.", "success")

    def _on_download_failed(self, song: dict, error: str):
        if "İptal" in error:
            self._on_status_message(
                f"⛔ '{song.get('title', '?')}' indirmesi iptal edildi.", "info")
        else:
            self._on_status_message(
                f"❌ İndirme başarısız: {song.get('title', '?')} — İndirmeler "
                "sayfasından tekrar deneyebilirsin.", "error")

    # --- SMTC (Windows medya denetimleri) olayları ---
    def _setup_smtc(self):
        """SMTC servisini kurar ve sinyalleri bağlar. Kurulum başarısızsa None.
        Sinyaller tek sefer bağlanır; lambdalar çağrı anında self.smtc'ye
        baktığı için kapat-aç döngüsünde çift bağlantı/çalışma olmaz."""
        first_setup = not getattr(self, "_smtc_signals_bound", False)
        try:
            self.smtc = SMTCService(self)
            self.smtc.buttonPressed.connect(self._on_smtc_button)
            self.smtc.start(int(self.winId()))
            if first_setup:
                self._smtc_signals_bound = True
                self.playback.songStarted.connect(self._on_smtc_song_started)
                self.playback.radioStarted.connect(self._on_smtc_radio_started)
                self.playback.playStateChanged.connect(
                    lambda playing: self.smtc.update_status(playing)
                    if self.smtc else None)
                self.playback.positionChanged.connect(
                    lambda cur, tot: self.smtc.update_position(cur, tot)
                    if self.smtc else None)
        except Exception as e:
            log.error("%s %s", "SMTC kurulamadı:", e)
            self.smtc = None

    def _on_smtc_button(self, name: str):
        if name == "play":
            self.playback.toggle_play_pause()
        elif name == "pause":
            self.playback.pause()
        elif name == "next":
            self.playback.play_next()
        elif name == "previous":
            self.playback.play_previous()
        elif name == "stop":
            self.playback.pause()

    def _on_smtc_song_started(self, _playlist_name, _index, song, _is_offline):
        if self.smtc is None:
            return
        pil = self.thumbnails.pil_for(song) if self.thumbnails else None
        thumb_url = None if pil is not None else song.get("thumbnail")
        self.smtc.update_metadata(song.get("title", ""), song.get("uploader", ""),
                                  thumb_url=thumb_url, thumb_pil=pil)
        self.smtc.update_status(True)

    def _on_smtc_radio_started(self, station: dict):
        if self.smtc is None:
            return
        self.smtc.update_metadata(station.get("name", "Radyo"),
                                  station.get("country") or "Canlı Yayın")
        self.smtc.update_status(True)

    # --- Sistem Tepsisi ---
    def _setup_system_tray(self):
        self.tray_icon = QSystemTrayIcon(build_icon(), self)   # ikonsuz tepsi simgesi gösterilmez
        self.tray_icon.setToolTip(APP_DISPLAY_NAME)
        tray_menu = QMenu()

        play_action = tray_menu.addAction("▶ Oynat / Duraklat")
        play_action.triggered.connect(self.playback.toggle_play_pause)

        next_action = tray_menu.addAction("⏭ Sonraki Şarkı")
        next_action.triggered.connect(self.playback.play_next)

        tray_menu.addSeparator()

        show_action = tray_menu.addAction("Göster")
        show_action.triggered.connect(self.showNormal)

        quit_action = tray_menu.addAction("Çıkış")
        quit_action.triggered.connect(self._quit_app)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            if self.isHidden() or self.isMinimized():
                self.showNormal()
                self.activateWindow()
            else:
                self.hide()

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            # Ayar açıksa küçültünce tepsiye iner (pencere listeden kaybolur,
            # müzik tepsi ikonu üzerinden çalmaya devam eder).
            if (self.windowState() & Qt.WindowMinimized) and self.settings.get("minimize_to_tray"):
                self.hide()
        super().changeEvent(event)

    def _quit_app(self):
        """Tepsi menüsündeki 'Çıkış' — minimize_to_tray açıkken bile gerçekten kapatır."""
        self._really_quit = True
        self.close()

    # --- Mini oynatıcı modu: mini açıkken ana pencere gizlenir ---
    def _toggle_mini_player(self):
        if self.mini_player.isVisible():
            self.mini_player.close()  # closed sinyali ana pencereyi geri getirir
            return
        self.hide()
        self.mini_player.show()

    def _on_mini_closed(self):
        if self.isHidden():
            self.showNormal()
            self.activateWindow()

    # --- "Şu An Çalıyor" panelini kapat/aç ---
    def _hide_now_playing_panel(self):
        self.now_playing_panel.hide()
        self.settings["now_playing_panel_visible"] = False
        self.top_bar.set_panel_toggle_visible(True)
        self.save_settings()

    def _show_now_playing_panel(self):
        self.now_playing_panel.show()
        self.settings["now_playing_panel_visible"] = True
        self.top_bar.set_panel_toggle_visible(False)
        self.save_settings()

    def _jump_to_playing(self):
        """Çalan şarkının listesini açıp satırına kaydırır."""
        pp = self.playback.playing_playlist
        if pp is None:
            self._on_status_message("Henüz bir şarkı çalmıyor.", "info")
            return
        self.show_playlist_view(pp)
        if not self.library_view.scroll_to_playing():
            self._on_status_message(
                "Çalan şarkı bu listede artık görünmüyor (silinmiş olabilir).", "warning")

    # --- Klavye kısayolları (metin kutusuna yazarken tetiklenmez) ---
    def keyPressEvent(self, event):  # noqa: N802
        # Ctrl+F her koşulda üst aramaya odaklanır
        if event.key() == Qt.Key_F and event.modifiers() & Qt.ControlModifier:
            self.top_bar.search_edit.setFocus()
            self.top_bar.search_edit.selectAll()
            event.accept()
            return
        fw = self.focusWidget()
        if isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_Space:
            self.playback.toggle_play_pause()
        elif key == Qt.Key_N:
            self.playback.play_next()
        elif key == Qt.Key_P:
            self.playback.play_previous()
        elif key == Qt.Key_Right:
            self.playback.seek(self.playback.player.get_time() + 10000)
        elif key == Qt.Key_Left:
            self.playback.seek(max(0, self.playback.player.get_time() - 10000))
        elif key == Qt.Key_Up:
            self.playback.change_volume(min(100, int(self.settings.get("_volume", 80)) + 5))
        elif key == Qt.Key_Down:
            self.playback.change_volume(max(0, int(self.settings.get("_volume", 80)) - 5))
        else:
            super().keyPressEvent(event)

    # --- Menü ---
    def _build_menu(self):
        menu_bar: QMenuBar = self.menuBar()

        app_menu = menu_bar.addMenu(APP_DISPLAY_NAME)
        mini_player_action = app_menu.addAction("🎵 Mini Oynatıcıyı Aç")
        mini_player_action.triggered.connect(self.mini_player.show)
        library_search_action = app_menu.addAction("🔎 Kütüphanede Ara…")
        library_search_action.setShortcut("Ctrl+K")
        library_search_action.triggered.connect(self._open_library_search_dialog)
        settings_action = app_menu.addAction("⚙ Ayarlar")
        settings_action.triggered.connect(self._open_settings_dialog)
        app_menu.addSeparator()
        exit_action = app_menu.addAction("Çıkış")
        exit_action.triggered.connect(self._quit_app)   # tepsiye küçült açıkken de gerçekten kapatır

        tools_menu = menu_bar.addMenu("Araçlar")

        listen_action = tools_menu.addAction("👥 Birlikte Dinle…")
        listen_action.triggered.connect(self._open_listen_together)
        self.listen.stateChanged.connect(lambda st: listen_action.setText(
            "👥 Birlikte Dinle (odadasın)…" if st == "connected" else "👥 Birlikte Dinle…"))
        update_action = tools_menu.addAction("🔄 Güncellemeleri Denetle…")
        update_action.triggered.connect(lambda: self.check_for_app_update(manual=True))
        data_dir_action = tools_menu.addAction("📁 Veri Klasörünü Aç")
        data_dir_action.triggered.connect(self._open_data_dir)
        tools_menu.addSeparator()

        bulk_action = tools_menu.addAction("📥 Toplu Şarkı Ekle…")
        bulk_action.triggered.connect(self._open_bulk_add)

        spotify_action = tools_menu.addAction("🎧 Spotify Playlist İçe Aktar…")
        spotify_action.triggered.connect(
            lambda: SpotifyImportDialog.prompt_and_run(
                self.store, self.settings, self.save_settings, self))

        youtube_action = tools_menu.addAction("▶ YouTube Playlist İçe Aktar…")
        youtube_action.triggered.connect(
            lambda: import_youtube_playlist(self.store, self))

        m3u_import_action = tools_menu.addAction("📂 M3U İçe Aktar…")
        m3u_import_action.triggered.connect(
            lambda: import_playlist_m3u(self.store, self))

        m3u_export_action = tools_menu.addAction("📤 Aktif Listeyi M3U Olarak Dışa Aktar…")
        m3u_export_action.triggered.connect(
            lambda: export_playlist_m3u_dialog(self.store, self.store.active_playlist, self))

        local_files_action = tools_menu.addAction("💽 Bilgisayardan Ses Dosyası Ekle…")
        local_files_action.triggered.connect(
            lambda: pick_and_add_local_files(self.store, self))

        tools_menu.addSeparator()

        backup_action = tools_menu.addAction("💾 Tüm Kütüphaneyi Yedekle…")
        backup_action.triggered.connect(
            lambda: export_library_dialog(self.store, self, self.settings))

        restore_backup_action = tools_menu.addAction("📂 Yedekten Geri Yükle…")
        restore_backup_action.triggered.connect(self._restore_from_backup)

        duplicates_action = tools_menu.addAction("🧹 Yinelenen Şarkı Bulucu…")
        duplicates_action.triggered.connect(self._open_duplicate_finder)

        undo_action = tools_menu.addAction("↩ Geri Al")
        undo_action.triggered.connect(self._perform_undo)
        self._undo_menu_action = undo_action

        eq_menu_item = menu_bar.addMenu("Ses")
        equalizer_action = eq_menu_item.addAction("🎚 Ekolayzer…")
        equalizer_action.triggered.connect(self._toggle_equalizer_window)

        lyrics_action = eq_menu_item.addAction("🎤 Sözler Paneli…")
        lyrics_action.triggered.connect(self._toggle_lyrics_window)

        help_menu = menu_bar.addMenu("Yardım")
        report_action = help_menu.addAction("🩺 Sorun Bildir / Tanılama Raporu…")
        report_action.triggered.connect(self.open_diagnostics_dialog)
        logs_action = help_menu.addAction("📁 Kayıt Klasörünü Aç")
        logs_action.triggered.connect(self._open_logs_dir)
        help_menu.addSeparator()
        help_update_action = help_menu.addAction("🔄 Güncellemeleri Denetle…")
        help_update_action.triggered.connect(lambda: self.check_for_app_update(manual=True))

    # --- Navigasyon / görünüm yönetimi ---
    def _select_nav_silent(self, key: str):
        """Sidebar buton görselini kod tarafından senkronlar (sinyal tetiklemeden)."""
        for k, btn in self.sidebar._nav_buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _switch_view(self, index: int):
        widget = self.view_stack.widget(index)
        self.view_stack.setCurrentIndex(index)
        if widget is None:
            return
        # Yumuşak geçiş: 150ms fade. Efekt bitince kaldırılır (kalıcı
        # QGraphicsOpacityEffect render performansını düşürür).
        # Yüzlerce satır widget'ı içeren şarkı listesinde efekt her karede tüm
        # listeyi yeniden çizdirip takılma yaptığı için orada uygulanmaz.
        if widget is getattr(self, "library_view", None):
            return
        old = getattr(self, "_fade_widget", None)
        if old is not None and old is not widget:
            try:
                old.setGraphicsEffect(None)
            except RuntimeError:
                pass  # widget bu arada yok edildi
        self._fade_widget = widget
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(150)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim  # GC'ye yenilmesin

    def show_home_view(self):
        self._refresh_home_recent()
        self._switch_view(0)

    def show_playlist_view(self, name: str):
        self.library_view.show_playlist(name)
        self._switch_view(1)

    def show_liked_view(self):
        self.library_view.show_liked()
        self._switch_view(1)

    def show_queue_view(self):
        self.library_view.show_queue()
        self._switch_view(1)

    def show_radio_view(self):
        self._switch_view(2)

    def show_explore_view(self):
        self._switch_view(3)

    def show_stats_view(self):
        self.stats_view.refresh()
        self._switch_view(4)

    def show_library_grid(self):
        self.library_grid.refresh()
        self._switch_view(5)

    def show_downloads_view(self):
        self.downloads_view.refresh()
        self._switch_view(6)

    def show_wrapped_view(self):
        self.wrapped_view.refresh()
        self._switch_view(9)

    def show_mixes_view(self):
        self.mixes_view.refresh()
        self._switch_view(8)

    def show_smart_rules_dialog(self):
        dlg = SmartRulesDialog(self.settings, self.save_settings, self)
        dlg.openRequested.connect(lambda name: self.show_smart_list("rule:" + name))
        dlg.exec()

    def show_smart_list(self, mode: str):
        self.library_view.show_smart(mode)
        self._switch_view(1)

    def _refresh_home_recent(self):
        try:
            self.home_view.refresh()
        except Exception:
            pass  # ana sayfa yenilemesi kritik değil

    def _play_shuffled_from_home(self):
        import random
        candidates = [(name, songs) for name, songs in self.store.playlists.items() if songs]
        if not candidates:
            self._on_status_message("Karışık çalmak için önce bir şarkı eklemelisin.", "warning")
            return
        self.playback.enable_shuffle()
        name, songs = random.choice(candidates)
        index = random.randrange(len(songs))
        self.store.switch_playlist(name)
        self.playback.play_song_at_index(name, index)

    def _on_nav_selected(self, key: str):
        routes = {
            "home": self.show_home_view,
            "liked": self.show_liked_view,
            "queue": self.show_queue_view,
            "downloads": self.show_downloads_view,
            "radio": self.show_radio_view,
            "explore": self.show_explore_view,
            "library": self.show_library_grid,
            "most_played": lambda: self.show_smart_list("most_played"),
            "recent": lambda: self.show_smart_list("recent"),
            "new_added": lambda: self.show_smart_list("new_added"),
            "mixes": self.show_mixes_view,
            "wrapped": self.show_wrapped_view,
            "fav_artists": lambda: self.show_smart_list("fav_artists"),
            "forgotten": lambda: self.show_smart_list("forgotten"),
            "smart_rules": self.show_smart_rules_dialog,
            "stats": self.show_stats_view,
        }
        handler = routes.get(key)
        if handler:
            handler()

    # --- Dinamik tema (kapak → vurgu rengi) ---
    def _on_thumb_for_accent(self, key: str):
        pl_name = self.playback.playing_playlist
        songs = self.store.playlists.get(pl_name) if pl_name else None
        idx = self.playback.current_index
        if songs and 0 <= idx < len(songs) and songs[idx].get("webpage_url") == key:
            self._accent_timer.start()

    def _apply_dynamic_accent(self):
        if not self.settings.get("dynamic_theme", True):
            return
        pl_name = self.playback.playing_playlist
        songs = self.store.playlists.get(pl_name) if pl_name else None
        idx = self.playback.current_index
        if not songs or not (0 <= idx < len(songs)) or self.thumbnails is None:
            return
        img = self.thumbnails.pil_for(songs[idx])
        if img is None:  # thumbnail henüz inmedi; thumbnailReady tekrar tetikler
            return
        color = dominant_accent_color(img)
        if not color or color == self._current_accent:
            return
        self._set_accent(color)

    def _set_accent(self, color: str):
        self._current_accent = color
        base = THEMES.get(self.settings.get("theme"), THEMES[DEFAULT_THEME_KEY])
        t = replace(base, accent=color, accent_dark=shade_color(color, 0.18))
        QApplication.instance().setStyleSheet(build_qss(t))
        if hasattr(self, "player_bar"):
            self.player_bar.waveform_strip.set_accent(color)
            self.player_bar.set_accent(color)  # YENİ: time_slider / volume_slider

    def _reset_accent(self):
        """Dinamik tema kapatıldığında / tema değiştiğinde temel renge döner."""
        base = THEMES.get(self.settings.get("theme"), THEMES[DEFAULT_THEME_KEY])
        self._set_accent(base.accent)

    # --- Diyaloglar ---
    def _open_search_dialog(self, initial_query: str = ""):
        dialog = SearchDialog(self.store, self.playback, self,
                              initial_query=initial_query, thumbnails=self.thumbnails)
        dialog.exec()
        dialog.deleteLater()  # parent'lı diyalog kapanınca da yaşar; sinyal bağlantıları birikmesin

    def _open_data_dir(self):
        """Hesap, ayar ve kütüphane dosyalarının bulunduğu klasörü gösterir."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.paths.dir))

    def _open_logs_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.paths.logs_dir))

    def open_diagnostics_dialog(self):
        """Sorun Bildir / Tanılama Raporu penceresini açar."""
        from mustiefly_qt.views.diagnostics_dialog import DiagnosticsDialog
        dlg = DiagnosticsDialog(
            self.paths.logs_dir,
            error_text=self._last_error_text,
            recent_errors=self._recent_errors,
            parent=self,
        )
        dlg.exec()
        dlg.deleteLater()

    def _on_extraction_failed(self, error_text: str):
        """YouTube çıkarımı hata verdiğinde (yt-dlp eski olabilir) bir kez arka planda
        güncelleme dener; böylece yeni kurulum beklemeden sorun kendi kendine çözülür."""
        self._last_error_text = error_text
        if self._ytdlp_auto_attempted or not self.settings.get("auto_ytdlp_update", True):
            return
        self._ytdlp_auto_attempted = True
        import threading

        def worker():
            try:
                from mustiefly_qt.helpers.updates import installed_version, run_update, update_available
                has_new, inst, latest = update_available()
                if not has_new:
                    return
                ok, _ = run_update()
                if ok:
                    self.updateNotice.emit(
                        f"⬆ yt-dlp otomatik güncellendi ({inst} → {installed_version() or latest}). "
                        "Etkinleşmesi için uygulamayı yeniden başlat.")
            except Exception as e:
                log.warning("Otomatik yt-dlp güncellemesi başarısız: %s", e)

        threading.Thread(target=worker, daemon=True).start()

    def _setup_room_indicator(self):
        """Durum çubuğunda tıklanabilir oda göstergesi (yalnız odadayken görünür)."""
        self._room_btn = QPushButton("")
        self._room_btn.setFlat(True)
        self._room_btn.setCursor(Qt.PointingHandCursor)
        self._room_btn.clicked.connect(self._open_listen_together)
        self._room_btn.hide()
        self.statusBar().addPermanentWidget(self._room_btn)
        for sig in (self.listen.stateChanged, self.listen.membersChanged):
            sig.connect(lambda *_: self._update_room_indicator())
        self.listen.chatReceived.connect(self._on_room_chat)
        self.listen.emojiReceived.connect(self._on_room_emoji)
        self.listen.stateChanged.connect(self._on_room_state)

    def _on_room_state(self, state: str):
        SongRow.room_queue_enabled = state == "connected"
        if state != "connected":
            self._listen_unread = 0
        self._update_room_indicator()

    def _update_room_indicator(self):
        if self.listen.state != "connected":
            self._room_btn.hide()
            return
        n = len(self.listen.members)
        unread = f"  💬{self._listen_unread}" if self._listen_unread else ""
        self._room_btn.setText(f"👥 {self.listen.room} · {n} kişi{unread}")
        self._room_btn.show()

    def _on_room_chat(self, name: str, text: str, mine: bool):
        if mine:
            return
        dialog = self._listen_dialog
        if dialog is None or not dialog.isVisible():
            self._listen_unread += 1
            self._update_room_indicator()
            self.statusBar().showMessage(f"💬 {name}: {text}", 8000)

    def _on_room_emoji(self, name: str, emoji: str):
        if name != self.listen.name:
            self.statusBar().showMessage(f"{emoji}  {name}", 4000)

    def _open_listen_together(self):
        self._listen_unread = 0
        self._update_room_indicator()
        if self._listen_dialog is None:
            self._listen_dialog = ListenTogetherDialog(
                self.listen, self.settings, self.save_settings, parent=self)
        self._listen_dialog.show()
        self._listen_dialog.raise_()
        self._listen_dialog.activateWindow()

    def _open_library_search_dialog(self):
        """Genel kütüphane arama: TÜM playlistlerde aynı anda arar."""
        dialog = LibrarySearchDialog(self.store, self.playback,
                                     self.thumbnails, parent=self)
        dialog.openPlaylistRequested.connect(self._open_song_from_library_search)
        dialog.exec()
        dialog.deleteLater()

    def _open_song_from_library_search(self, playlist_name: str, index: int):
        self.show_playlist_view(playlist_name)
        self.library_view.scroll_to_song(playlist_name, index)

    def _restore_from_backup(self):
        import_library_dialog(
            self.store, self, settings=self.settings,
            on_settings_restored=self._on_backup_settings_restored)

    def _on_backup_settings_restored(self):
        """Yedekteki ayarlar bu oturuma alındı: temayı canlı uygula, kalanlar
        için yeniden başlatma öner."""
        self.save_settings()
        self._reset_accent()
        if self.settings.get("dynamic_theme", True):
            self._apply_dynamic_accent()
        QMessageBox.information(
            self, "Ayarlar Geri Yüklendi",
            "Yedekteki ayarlar uygulandı. Bazı ayarların (medya tuşları vb.) "
            "tam etkinleşmesi için uygulamayı yeniden başlatabilirsin.")

    def _open_settings_dialog(self):
        """Ayarlar sayfasını ana pencerenin içeriğinde açar (ayrı pencere YOK).
        Geri dönüşte hangi sayfada olunacağını hatırlamak için mevcut
        sayfayı kaydeder, ardından ayarları güncel verilerle tazeleyip
        view_stack'i ayarlar sayfasına çevirir."""
        self._pre_settings_index = self.view_stack.currentIndex()
        self._settings_was_media_keys = bool(self.settings.get("global_media_keys"))
        self._settings_was_smtc = self.smtc is not None
        self.settings_view.refresh_dynamic()
        self.view_stack.setCurrentWidget(self.settings_view)

    def _close_settings_view(self):
        """'Geri' ya da 'İptal' — hiçbir yan etki uygulamadan önceki sayfaya döner."""
        self.view_stack.setCurrentIndex(self._pre_settings_index)

    def _on_settings_saved(self):
        """'Kaydet' — eski modal diyalogda exec() sonrası yapılan aynı
        canlı-uygulama mantığı, artık kaydetme sinyaline bağlı."""
        was_media_keys = self._settings_was_media_keys
        was_smtc = self._settings_was_smtc
        now_media_keys = bool(self.settings.get("global_media_keys"))
        if was_media_keys and not now_media_keys:
            self._media_keys.stop()
        elif not was_media_keys and now_media_keys:
            self._media_keys.start()
        # SMTC aç/kapat canlı uygulanır
        now_smtc = (bool(self.settings.get("smtc_enabled", True))
                    and SMTC_AVAILABLE)
        if was_smtc and not now_smtc and self.smtc is not None:
            self.smtc.stop()
            self.smtc = None
        elif not was_smtc and now_smtc:
            self._setup_smtc()
            if self.smtc is not None:
                pp = self.playback.playing_playlist
                if pp is not None:
                    idx = self.playback.current_index
                    songs = self.store.playlists.get(pp, [])
                    if 0 <= idx < len(songs):
                        self._on_smtc_song_started(pp, idx, songs[idx], False)
        self.store.backup_enabled = bool(self.settings.get("backup_enabled", True))
        # Tema + vurgu rengi artık canlı uygulanır (yeniden başlatma gerekmez)
        self._reset_accent()
        if self.settings.get("dynamic_theme", True):
            self._apply_dynamic_accent()
        self._close_settings_view()

    def _open_bulk_add(self):
        dialog = BulkAddDialog(self.store, self)
        dialog.exec()
        dialog.deleteLater()

    def _open_duplicate_finder(self):
        dialog = DuplicateFinderDialog(self.store, self)
        dialog.exec()
        dialog.deleteLater()

    # --- Ekolayzer & Sözler pencereleri ---
    def _toggle_equalizer_window(self):
        if self._eq_window is not None and self._eq_window.isVisible():
            self._eq_window.close()
            self._eq_window = None
            return
        self._eq_window = EqualizerWindow(
            self.playback, self.settings, self.save_settings, self)
        self._eq_window.show()

    def _toggle_lyrics_window(self):
        if self._lyrics_window is not None and self._lyrics_window.isVisible():
            self._lyrics_window.close()
            self._lyrics_window = None
            return
        self._lyrics_window = LyricsWindow(self.playback, self)
        self._lyrics_window.show()
        self._lyrics_window.refresh()

    # --- Uygulama güncellemesi (GitHub Releases) ---
    def check_for_app_update(self, manual: bool = True):
        self._update_manual = manual
        if manual:
            self._on_status_message("Güncellemeler denetleniyor…", "info")
        if not self.app_updater.check() and manual:
            self._on_status_message("Güncelleme denetimi zaten sürüyor.", "info")

    def _on_app_update_checked(self, status: str, info, message: str):
        manual = self._update_manual
        self._update_manual = False
        if status == "error":
            if manual:
                QMessageBox.warning(self, "Güncelleme", message or "Güncelleme denetlenemedi.")
            return
        if status == app_update.UP_TO_DATE:
            if manual:
                QMessageBox.information(
                    self, "Güncelleme", f"{APP_DISPLAY_NAME} güncel (sürüm {APP_VERSION}).")
            return
        if status == app_update.NO_RELEASE:
            if manual:
                QMessageBox.information(self, "Güncelleme", "Henüz yayınlanmış bir sürüm bulunamadı.")
            return
        if info is None:
            return
        if not manual and self.settings.get("skipped_update_version") == info.version:
            return
        self._show_update_dialog(info)

    def _show_update_dialog(self, info):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Yeni sürüm var")
        notes = f"\n\nDeğişiklikler:\n{info.notes}" if info.notes else ""
        box.setText(f"{APP_DISPLAY_NAME} {info.version} yayınlandı (şu an {APP_VERSION}).{notes}")
        install = app_update.can_install_here() and info.can_auto_install
        update_btn = box.addButton("Şimdi güncelle" if install else "İndirme sayfasını aç",
                                   QMessageBox.AcceptRole)
        box.addButton("Sonra", QMessageBox.RejectRole)
        skip_btn = box.addButton("Bu sürümü atla", QMessageBox.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skip_btn:
            self.settings["skipped_update_version"] = info.version
            self.save_settings()
        elif clicked is update_btn:
            if install:
                self._start_update_download(info)
            else:
                QDesktopServices.openUrl(QUrl(info.page_url))

    def _start_update_download(self, info):
        from PySide6.QtWidgets import QProgressDialog
        dialog = QProgressDialog(f"{APP_DISPLAY_NAME} {info.version} indiriliyor…", "İptal", 0, 100, self)
        dialog.setWindowTitle("Güncelleme")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.canceled.connect(self.app_updater.cancel)
        self.app_updater.progress.connect(dialog.setValue)
        self._update_progress = dialog
        if not self.app_updater.download(info):
            self._close_update_progress()
            return
        dialog.show()

    def _close_update_progress(self):
        dialog, self._update_progress = self._update_progress, None
        if dialog is not None:
            try:
                self.app_updater.progress.disconnect(dialog.setValue)
            except (RuntimeError, TypeError):
                pass
            dialog.close()
            dialog.deleteLater()

    def _on_app_update_failed(self, message: str):
        self._close_update_progress()
        if "iptal" in message.lower():
            self._on_status_message("Güncelleme indirmesi iptal edildi.", "info")
            return
        QMessageBox.warning(
            self, "Güncelleme",
            f"{message}\n\nİstersen yeni sürümü elle indirebilirsin:\n{app_update.RELEASES_PAGE}")

    def _on_app_update_downloaded(self, path: str):
        self._close_update_progress()
        answer = QMessageBox.question(
            self, "Güncellemeyi kur",
            f"İndirme tamamlandı ve doğrulandı.\n\n{APP_DISPLAY_NAME} şimdi kapanıp kurulum başlayacak "
            "(verilerin korunur). Devam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            self._on_status_message(f"Kurulum dosyası hazır: {path}", "info")
            return
        if not app_update.launch_installer(path):
            QMessageBox.warning(self, "Güncelleme",
                                f"Kurulum başlatılamadı. Dosyayı elle çalıştırabilirsin:\n{path}")
            return
        self._quit_app()

    # --- Geri al (snackbar) akışı ---
    def _on_undo_available(self, available: bool):
        """Yeni bir geri alınabilir işlem oluştuğunda snackbar gösterilir;
        geri alındığında (False) gizlenir."""
        if self._undo_menu_action is not None:
            self._undo_menu_action.setEnabled(bool(available))
        if available:
            self.snackbar.show_message("↩ Son işlemi geri alabilirsin.", undoable=True)
        else:
            self.snackbar.hide()

    def _perform_undo(self):
        message = self.store.perform_undo()
        if message:
            self._on_status_message(message, "success")

    # --- Durum mesajları ---
    def _on_status_message(self, message: str, level: str = "info"):
        first_line = (message or "").splitlines()[0] if message else ""
        self.statusBar().showMessage(first_line, 6000)
        if level == "error" and message:
            self._last_error_text = message
            self._recent_errors.append(message)
            del self._recent_errors[:-20]
            if not self.store.can_undo():
                self.snackbar.show_message(
                    f"⚠️ {first_line}", undoable=False, reportable=True, duration_ms=9000)
        elif level == "success" and message:
            # Geri alınabilir bir işlem snackbar'da bekliyorsa üzerine yazma;
            # değilse başarı mesajını 3 sn'lik tost olarak göster
            if not self.store.can_undo():
                self.show_success_message(message)

    def show_success_message(self, text: str):
        """'Geri Al'sız kısa süreli başarı bildirimi (içe aktarma, indirme vb.)."""
        self.snackbar.show_message(f"✅ {text}", undoable=False, duration_ms=3000)

    def resizeEvent(self, event):  # noqa: N802
        """Snackbar'ı pencere altına hizalar."""
        super().resizeEvent(event)
        if hasattr(self, "snackbar") and self.snackbar.isVisible():
            w = min(520, self.width() - 40)
            self.snackbar.setGeometry(
                (self.width() - w) // 2, self.height() - self.snackbar.sizeHint().height() - 110,
                w, self.snackbar.sizeHint().height())

    def closeEvent(self, event):
        # "Tepsiye küçült" açıksa ✕ uygulamayı kapatmaz, tepsiye indirir
        if (self.settings.get("minimize_to_tray") and not self._really_quit
                and QSystemTrayIcon.isSystemTrayAvailable()):
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                APP_DISPLAY_NAME, "Uygulama tepsiye küçüldü; müzik çalmaya devam ediyor.",
                QSystemTrayIcon.Information, 2000)
            return
        self.listen.shutdown()
        self.discord_rpc.close()
        self.mini_player.close()
        if self._eq_window is not None:
            self._eq_window.close()
        if self._lyrics_window is not None:
            self._lyrics_window.close()
        self._media_keys.stop()
        # Son dinleme durumu: açılışta kaldığın yerden devam etmek için
        try:
            self.settings["last_session"] = (
                self.playback.save_session_state()
                if self.settings.get("restore_session", True) else None)
            self.save_settings()
        except Exception as e:
            log.error("%s %s", "Oturum kaydedilemedi:", e)
        if self.smtc is not None:
            self.smtc.stop()
        self.downloads.shutdown()
        self.thumbnails.shutdown()
        self.store.flush_now()
        try:
            self.playback.shutdown()
        except Exception as e:
            log.error("%s %s", "VLC kaynakları serbest bırakılamadı:", e)
        super().closeEvent(event)

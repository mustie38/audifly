"""
Spotify playlist içe aktarma ve M3U içe/dışa aktarma diyalogları.

Orijinal import_spotify_playlist / _open_spotify_import_dialog ve
import_playlist_m3u / export_playlist_m3u'nun Qt portudur.
"""
from __future__ import annotations

import threading
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)

import yt_dlp

from mustiefly_qt.helpers.constants import yt_dlp_base_opts
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.helpers.spotify_import import (
    SpotifyApiError, SpotifyAuthError, extract_spotify_playlist_id,
    export_playlist_m3u, fetch_spotify_playlist, parse_m3u_file,
)
from mustiefly_qt.services.bulk_search import BulkSearchWorker
from mustiefly_qt.services.playlist_store import PlaylistStore, _clean_song
from mustiefly_qt.helpers.logging_setup import get_logger



log = get_logger(__name__)
class SpotifyImportDialog(QDialog):
    """Bir Spotify playlist linkini YouTube üzerinden eşleştirip yeni bir listeye aktarır."""

    tracksFetched = Signal(str, list)                 # playlist_adı, arama_sorguları
    fetchError = Signal(str)
    searchFinished = Signal(str, int, list, bool)     # playlist_adı, eklenen, başarısızlar, iptal

    def __init__(self, store: PlaylistStore, settings: dict, save_settings_fn, parent=None):
        super().__init__(parent)
        self.store = store
        self.settings = settings
        self.save_settings_fn = save_settings_fn
        self._target_name = ""
        self._running = True  # fetch aşamasından itibaren iptal edilebilir
        self._worker: BulkSearchWorker | None = None

        self.setWindowTitle("🎧 Spotify Playlist İçe Aktar")
        self.resize(520, 240)

        root = QVBoxLayout(self)
        title = QLabel("🎧 Spotify Playlist İçe Aktarılıyor")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        self.progress_label = QLabel("Spotify'dan playlist bilgisi alınıyor…")
        self.progress_label.setObjectName("Muted")
        self.progress_label.setWordWrap(True)
        root.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.close_btn = QPushButton("Durdur")
        self.close_btn.clicked.connect(self._cancel_or_close)
        btn_row.addWidget(self.close_btn)
        root.addLayout(btn_row)

        self.tracksFetched.connect(self._on_tracks_fetched)
        self.fetchError.connect(self._on_fetch_error)
        self.searchFinished.connect(self._on_search_finished)

    @staticmethod
    def prompt_and_run(store: PlaylistStore, settings: dict, save_settings_fn, parent=None):
        """Giriş doğrulama + link sorma dahil tam akış. Client ID girilmemişse bile
        herkese açık (public) tüm Spotify listeleri doğrudan embed üzerinden çekilir."""
        client_id = settings.get("spotify_client_id", "").strip()
        client_secret = settings.get("spotify_client_secret", "").strip()

        url, ok = QInputDialog.getText(
            parent, "Spotify Playlist İçe Aktar",
            "Spotify playlist linkini yapıştır (senin, başka bir kullanıcının ya da Spotify'ın listesi):\n"
            "(örn. https://open.spotify.com/playlist/...)",
            QLineEdit.Normal)
        if not ok or not url.strip():
            return

        playlist_id = extract_spotify_playlist_id(url)
        if not playlist_id:
            QMessageBox.warning(parent, "Hata", "Geçerli bir Spotify playlist linki/ID'si değil.")
            return

        dialog = SpotifyImportDialog(store, settings, save_settings_fn, parent)
        dialog.show()
        dialog._start_fetch(playlist_id, client_id, client_secret)

    # --- Adım 1: Spotify'dan şarkı listesini çek ---
    def _start_fetch(self, playlist_id: str, client_id: str, client_secret: str):
        if client_id and not self.settings.get("spotify_refresh_token"):
            self.progress_label.setText(
                "🌐 Spotify hesabınla giriş yapman gerekiyor — tarayıcıda bir sekme "
                "açılacak, giriş yapıp 'Anlaştık'a bas. Bu sadece ilk seferde gerekiyor.")

        def fetch_worker():
            try:
                playlist_name, queries = fetch_spotify_playlist(
                    playlist_id, client_id, client_secret,
                    self.settings, self.save_settings_fn)
            except SpotifyAuthError as e:
                if e.status_code == 401:
                    msg = (f"Spotify girişi tamamlanamadı: \"{e.detail}\"\n\n"
                           "Tarayıcıda açılan sekmede Spotify hesabınla giriş yapıp izin vermen "
                           "gerekiyor. Tekrar dene; tarayıcı açılmıyorsa varsayılan tarayıcı "
                           "ayarını kontrol et.")
                else:
                    msg = (f"Spotify kimlik doğrulaması başarısız (kod {e.status_code}):\n\"{e.detail}\"")
                try:
                    self.fetchError.emit(msg)
                except RuntimeError:
                    pass
                return
            except SpotifyApiError as e:
                if e.status_code == 404:
                    msg = ("Playlist bulunamadı. Linkin doğru ve playlistin herkese açık "
                           "(public) olduğundan emin ol.")
                elif e.status_code == 403:
                    msg = (f"Spotify erişimi reddetti (403): \"{e.detail}\"\n\n"
                           "Giriş başarılı ama bu playlist'e erişim engellendi. Spotify'ın kendi "
                           "kürasyonlu/algoritmik listeleri API ile çekilemiyor — kendi "
                           "oluşturduğun bir playlist ile dene.")
                else:
                    msg = f"Spotify API hatası (kod {e.status_code}): \"{e.detail}\""
                try:
                    self.fetchError.emit(msg)
                except RuntimeError:
                    pass
                return
            except Exception as e:
                try:
                    self.fetchError.emit(f"Spotify'a bağlanılamadı: {e}")
                except RuntimeError:
                    pass
                return

            try:
                self.tracksFetched.emit(playlist_name, queries)
            except RuntimeError:
                pass

        threading.Thread(target=fetch_worker, daemon=True).start()

    # --- Adım 2: her şarkı için YouTube eşleşmesi ara ---
    def _on_tracks_fetched(self, playlist_name: str, queries: list):
        if not self._running:
            return
        if not queries:
            self._on_fetch_error("Bu playlist'te şarkı bulunamadı ya da playlist gizli/erişilemez.")
            return

        self._target_name = playlist_name
        if playlist_name not in self.store.playlists:
            self.store.playlists[playlist_name] = []

        existing_urls = {s.get('webpage_url')
                         for s in self.store.playlists.get(playlist_name, [])}
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(queries))
        self.progress_bar.setValue(0)

        self._worker = BulkSearchWorker(queries, existing_urls)
        self._worker.progress.connect(self._on_search_progress)
        self._worker.itemFound.connect(self._append_item)
        self._worker.finished.connect(lambda added, failed, cancelled:
                                      self.searchFinished.emit(playlist_name, added, failed, cancelled))

        self._running = True
        threading.Thread(target=self._worker.run, daemon=True).start()

    def _on_search_progress(self, done: int, total: int, query: str):
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"🔍 ({done}/{total}) aranıyor: {query[:50]}")

    def _append_item(self, item: dict):
        """GUI thread'inde hedef listeye ekler (thread güvenliği)."""
        self.store.playlists.setdefault(self._target_name, []).append(_clean_song(item))

    def _on_fetch_error(self, message: str):
        self._running = False
        self.progress_label.setText(f"❌ {message}")
        self.close_btn.setText("Kapat")
        self.close_btn.setEnabled(True)

    def _on_search_finished(self, playlist_name: str, added: int, failed: list, cancelled: bool):
        self._running = False
        total = self.progress_bar.maximum()
        self.store.save()
        self.store.playlistsChanged.emit()

        if cancelled:
            msg = f"⏹ Durduruldu. {added}/{total} şarkı '{playlist_name}' listesine eklendi."
        elif failed:
            msg = f"✅ '{playlist_name}' — {added}/{total} şarkı eklendi. {len(failed)} tanesi bulunamadı."
        else:
            msg = f"✅ '{playlist_name}' — {added}/{total} şarkının tamamı eklendi!"
        self.progress_label.setText(msg)
        self.close_btn.setText("Kapat")
        self.close_btn.setEnabled(True)

        self.store.statusMessage.emit(
            f"Spotify içe aktarma tamamlandı: '{playlist_name}' ({added} şarkı).", "success")

    def _cancel_or_close(self):
        if self._running:
            self._running = False
            if self._worker is not None:
                self._worker.cancel()
                self.close_btn.setText("Durduruluyor…")
                self.close_btn.setEnabled(False)
                return
        self.accept()

    def reject(self):
        self._cancel_or_close()


class _M3UImportBridge(QObject):
    """Worker thread'inde çözülen şarkıları GUI thread'ine taşır.
    Liste mutasyonu her zaman ana thread'de olmalı (race condition önlemi)."""
    resolved = Signal(list)  # list[dict]


class _YouTubeImportBridge(QObject):
    """Worker thread'inde çözülen YouTube playlist'ini GUI thread'ine taşır."""
    resolved = Signal(str, list)  # playlist_adı, şarkı_listesi
    failed = Signal(str)


def extract_youtube_playlist(url: str) -> tuple[str, list[dict]]:
    """YouTube playlist linkini flat modda çözer: (playlist_adı, şarkı_sözlükleri).

    extract_flat='in_playlist' video başına ekstra istek yapmaz; sadece metadata
    (başlık/süre/kanal) saniyeler içinde döner. Gerçek ses linki zaten çalma
    anında resolve_stream_url tarafından çözülür.
    """
    ydl_opts = yt_dlp_base_opts(quiet=True, extract_flat="in_playlist", skip_download=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise Exception("Playlist bilgisi alınamadı (link doğru mu?).")
    if not info.get("entries"):
        raise Exception(
            "Bu link bir playlist gibi görünmüyor.\nÖrnek format: "
            "https://www.youtube.com/playlist?list=PL...")
    name = (info.get("title") or "YouTube Playlist").strip()
    songs = []
    for e in info["entries"]:
        if not e:
            continue
        vid = e.get("id")
        web = e.get("webpage_url") or e.get("url") or (
            f"https://www.youtube.com/watch?v={vid}" if vid else "")
        if not web or "://" not in web:
            continue
        thumbs = e.get("thumbnails") or []
        clean_title, clean_artist = parse_track_and_artist(
            e.get("title") or "Bilinmeyen Şarkı",
            e.get("uploader") or e.get("channel") or "",
            e,
        )
        songs.append({
            "title": clean_title,
            "webpage_url": web,
            "duration": int(e.get("duration") or 0),
            "uploader": clean_artist,
            "thumbnail": (thumbs[-1] or {}).get("url") if thumbs else e.get("thumbnail"),
            "liked": False,
            "added_date": datetime.now().isoformat(),
        })
    return name, songs


def import_youtube_playlist(store: PlaylistStore, parent=None):
    """YouTube playlist linkini sorar, arka planda çözer ve kütüphaneye aktarır.
    Aynı isimli liste varsa şarkılar onun sonuna eklenir (mükerrerler atlanır)."""
    url, ok = QInputDialog.getText(
        parent, "YouTube Playlist İçe Aktar",
        "YouTube playlist linkini yapıştır:\n"
        "(örn. https://www.youtube.com/playlist?list=...)",
        QLineEdit.Normal)
    if not ok or not url.strip():
        return
    url = url.strip()

    bridge = _YouTubeImportBridge(parent=parent or store)

    def apply(name: str, songs: list):
        bridge.deleteLater()
        if not songs:
            store.statusMessage.emit(
                "Playlist'te içe aktarılabilir şarkı bulunamadı.", "warning")
            return
        target = name or "YouTube Playlist"
        store.playlists.setdefault(target, [])
        existing_urls = {s.get("webpage_url") for s in store.playlists[target]}
        added = 0
        for item in songs:
            if item["webpage_url"] in existing_urls:
                continue
            existing_urls.add(item["webpage_url"])
            store.playlists[target].append(_clean_song(item))   # add_song ile aynı normalizasyon
            added += 1
        store.save()
        store.playlistsChanged.emit()
        skipped = len(songs) - added
        msg = f"✅ '{target}' — {added} şarkı eklendi"
        if skipped:
            msg += f" ({skipped} tanesi zaten listedeydi)"
        store.statusMessage.emit(msg + ".", "success")

    def on_error(message: str):
        bridge.deleteLater()
        QMessageBox.warning(parent, "Hata", f"YouTube playlist alınamadı:\n{message}")

    bridge.resolved.connect(apply)
    bridge.failed.connect(on_error)

    def worker():
        try:
            name, songs = extract_youtube_playlist(url)
        except Exception as e:
            try:
                bridge.failed.emit(str(e))
            except RuntimeError:
                pass
            return
        try:
            bridge.resolved.emit(name, songs)
        except RuntimeError:
            pass

    threading.Thread(target=worker, daemon=True).start()
    store.statusMessage.emit("📥 YouTube playlist alınıyor…", "info")


def import_playlist_m3u(store: PlaylistStore, parent=None):
    """M3U dosyası seçtirip içindeki YouTube linklerini çözerek aktif listeye ekler.
    Ağır iş arka plandadır; sonuçlar sinyalle GUI thread'ine taşınır."""
    path, _ = QFileDialog.getOpenFileName(
        parent, "M3U Playlist Seç", "", "M3U Playlist (*.m3u *.m3u8);;Tüm dosyalar (*.*)")
    if not path:
        return
    entries, err = parse_m3u_file(path)
    if err:
        QMessageBox.warning(parent, "Hata", f"M3U dosyası okunamadı:\n{err}")
        return
    youtube_entries = [(url, t, d) for url, t, d in entries
                       if "youtube.com" in url or "youtu.be" in url]
    skipped = len(entries) - len(youtube_entries)
    if not youtube_entries:
        QMessageBox.information(parent, "Bilgi",
                                "Dosyada içe aktarılabilir YouTube linki bulunamadı "
                                "(şimdilik sadece YouTube linkleri destekleniyor).")
        return

    target_playlist = store.active_playlist
    bridge = _M3UImportBridge(parent=parent or store)

    def apply(items: list):
        bridge.deleteLater()
        added = 0
        for item in items:
            added += store.add_song(target_playlist, item)
        store.flush_now()
        store.statusMessage.emit(
            f"📥 M3U'dan {added} şarkı '{target_playlist}' listesine eklendi."
            + (f" ({skipped} YouTube olmayan link atlandı.)" if skipped else ""), "success")

    bridge.resolved.connect(apply)

    def worker():
        items: list[dict] = []
        ydl_opts = yt_dlp_base_opts(format='bestaudio/best', quiet=True, noplaylist=True)
        for url, title_hint, dur_hint in youtube_entries:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                clean_title, clean_artist = parse_track_and_artist(
                    info.get('title', title_hint or 'Bilinmeyen Şarkı'),
                    info.get('uploader') or info.get('channel') or 'Bilinmeyen Sanatçı',
                    info,
                )
                items.append({
                    'title': clean_title,
                    'webpage_url': info.get('webpage_url', url),
                    'duration': info.get('duration', dur_hint) or 0,
                    'uploader': clean_artist,
                    'thumbnail': info.get('thumbnail'),
                    'liked': False,
                    'added_date': datetime.now().isoformat(),
                })
            except Exception as e:
                log.error("%s %s", f"M3U öğesi çözülemedi ('{url}'):", e)
        try:
            bridge.resolved.emit(items)  # queued connection → GUI thread
        except RuntimeError:
            pass

    threading.Thread(target=worker, daemon=True).start()
    store.statusMessage.emit("📥 M3U dosyası işleniyor…", "info")


def export_playlist_m3u_dialog(store: PlaylistStore, playlist_name: str, parent=None):
    songs = store.playlists.get(playlist_name, [])
    if not songs:
        store.statusMessage.emit("Bu liste boş, dışa aktarılacak bir şey yok.", "warning")
        return
    # Yerel dosyalar (local://) M3U'da anlam taşımaz — diğer oynatıcılar
    # bu URI'yi açamaz; sadece link taşınabilir kayıtlar dışa aktarılır.
    exportable = [s for s in songs if not s.get("local_path")]
    skipped_local = len(songs) - len(exportable)
    if not exportable:
        store.statusMessage.emit(
            "Listede yalnızca yerel dosyalar var; M3U'ya aktarılacak link yok.", "warning")
        return
    path, _ = QFileDialog.getSaveFileName(
        parent, "M3U olarak kaydet", f"{playlist_name}.m3u8",
        "M3U Playlist (*.m3u8 *.m3u);;Tüm dosyalar (*.*)")
    if not path:
        return
    err = export_playlist_m3u(exportable, path)
    if err:
        log.error("%s %s", "M3U dışa aktarma hatası:", err)
        store.statusMessage.emit("M3U dışa aktarılamadı.", "error")
    else:
        extra = f" ({skipped_local} yerel dosya atlandı)" if skipped_local else ""
        store.statusMessage.emit(
            f"✅ '{playlist_name}' M3U olarak dışa aktarıldı.{extra}", "success")

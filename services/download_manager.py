"""
Çevrimdışı indirme yöneticisi.

Şu ana kadar indirmeler sessizce arka planda kayboluyordu; bu servis her
indirmeyi görünür kılar: sıra, yüzde, iptal ve başarısız-tekrar deneme.

Tek bir çalışan (worker) thread sırayı tüketir — aynı anda tek indirme,
bant genişliğini boğmasın. İptal, yt-dlp progress hook'una bayrak kontrolü
gömülerek yapılır (hook exception fırlatınca indirme durur).
"""
from __future__ import annotations

import hashlib
import os
import queue
import threading

import yt_dlp
from PySide6.QtCore import QObject, QTimer, Signal

from mustiefly_qt.helpers.constants import AppPaths, yt_dlp_base_opts
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
# İndirme durumları
QUEUED, DOWNLOADING, DONE, FAILED, CANCELLED = (
    "queued", "downloading", "done", "failed", "cancelled")

PROGRESS_EMIT_INTERVAL = 0.25  # saniye — sinyal fırtınasını önler


class _Cancelled(Exception):
    """progress hook içinden fırlatılır; yt-dlp indirmeyi iptal eder."""


# Modern yt-dlp'nin native iptal istisnası varsa onu kullan (part dosyası vb.
# temizliğini kendisi yapar); yoksa kendi istisnamıza düşer.
try:
    _DL_CANCELLED = yt_dlp.utils.DownloadCancelled
    _CANCEL_EXCS = (_DL_CANCELLED, _Cancelled)
except AttributeError:
    _DL_CANCELLED = _Cancelled
    _CANCEL_EXCS = (_Cancelled,)


class DownloadManager(QObject):
    itemChanged = Signal(str)      # key — tek satır güncellemesi
    queueChanged = Signal()        # satır eklendi/kaldırıldı — tam yeniden çizim
    downloadFinished = Signal(dict, str, bool)   # song, path, already_cached
    downloadFailed = Signal(dict, str)
    # Worker thread'den GUI'ye: cached_path yazımı + debounce kaydı orada yapılır
    # (QTimer yalnızca GUI thread'inde başlatılabilir).
    _finishRequested = Signal(object, str)

    def __init__(self, store: PlaylistStore, paths: AppPaths, parent=None):
        super().__init__(parent)
        self.store = store
        self.paths = paths
        self.items: dict[str, dict] = {}     # key → item sözlüğü
        self._order: list[str] = []          # görüntüleme sırası
        self._work = queue.Queue()
        self._stopping = threading.Event()
        # Toplu indirmede her biten şarkı için tüm arayüzü yeniden çizmemek için
        # playlistsChanged yayını kısa süre içinde tek sinyale indirilir.
        self._changed_timer = QTimer(self)
        self._changed_timer.setSingleShot(True)
        self._changed_timer.setInterval(300)
        self._changed_timer.timeout.connect(self._emit_library_changed)
        self._worker = None
        self._lock = threading.Lock()
        self._worker_started = False
        self._finishRequested.connect(self._finish_on_gui)

    # --- Genel API (GUI thread'inden çağrılır) ---
    def enqueue(self, playlist_name: str, index: int) -> bool:
        """Şarkıyı indirme kuyruğuna alır. Zaten kuyruktaysa/iniyorsa False."""
        songs = self.store.playlists.get(playlist_name)
        if not songs or not (0 <= index < len(songs)):
            return False
        song = songs[index]
        url = song.get("webpage_url")
        if not url or url.startswith("local://"):
            return False  # yerel dosyalar indirilemez — zaten diskte
        if self._stopping.is_set():
            return False
        with self._lock:
            existing = self.items.get(url)
            if existing is not None and existing["state"] in (QUEUED, DOWNLOADING):
                return False
            item = {
                "key": url, "playlist": playlist_name, "index": index,
                "song": song, "state": QUEUED, "progress": 0.0,
                "error": "", "path": None, "cancel": threading.Event(),
            }
            self.items[url] = item
            if url not in self._order:
                self._order.append(url)
        self._ensure_worker()
        self._work.put(item)
        self.queueChanged.emit()
        return True

    def cancel(self, key: str):
        with self._lock:
            item = self.items.get(key)
            if item is None or item["state"] not in (QUEUED, DOWNLOADING):
                return
            item["cancel"].set()
            item["state"] = CANCELLED
        self.itemChanged.emit(key)

    def retry(self, key: str):
        with self._lock:
            previous = self.items.get(key)
            if previous is None or previous["state"] not in (FAILED, CANCELLED) or self._stopping.is_set():
                return
            previous["cancel"].set()
            item = {**previous, "state": QUEUED, "progress": 0.0,
                    "error": "", "path": None, "preexisting": False,
                    "cancel": threading.Event()}
            self.items[key] = item
        self._ensure_worker()
        self._work.put(item)
        self.itemChanged.emit(key)

    def remove(self, key: str):
        self.cancel(key)
        with self._lock:
            self.items.pop(key, None)
            if key in self._order:
                self._order.remove(key)
        self.queueChanged.emit()

    def _emit_library_changed(self):
        if not self._stopping.is_set():
            self.store.playlistsChanged.emit()

    def shutdown(self, timeout=2.0):
        """Cancel work on close. Bounded wait; network hooks observe cancellation."""
        self._stopping.set()
        self._changed_timer.stop()
        with self._lock:
            for item in self.items.values():
                item["cancel"].set()
                if item["state"] in (QUEUED, DOWNLOADING):
                    item["state"] = CANCELLED
        self._work.put(None)
        if self._worker is not None:
            self._worker.join(timeout)
        return self._worker is None or not self._worker.is_alive()

    def clear_finished(self):
        with self._lock:
            for key in [k for k, it in self.items.items()
                        if it["state"] in (DONE, FAILED, CANCELLED)]:
                del self.items[key]
                self._order.remove(key)
        self.queueChanged.emit()

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for it in self.items.values()
                       if it["state"] in (QUEUED, DOWNLOADING))

    def ordered_items(self) -> list[dict]:
        with self._lock:
            return [dict(self.items[k]) for k in self._order if k in self.items]

    # --- Worker ---
    def _ensure_worker(self):
        if self._worker_started:
            return
        self._worker_started = True
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="mustiefly-downloads")
        self._worker.start()

    def _run(self):
        while True:
            item = self._work.get()
            try:
                if item is None:
                    return
                with self._lock:
                    if (self._stopping.is_set() or self.items.get(item["key"]) is not item
                            or item["state"] != QUEUED or item["cancel"].is_set()):
                        continue
                    item["state"] = DOWNLOADING
                self._process(item)
            finally:
                self._work.task_done()

    def _process(self, item: dict):
        song = item["song"]
        key = item["key"]
        cancel = item["cancel"]
        item["progress"] = 0.0
        self.itemChanged.emit(key)
        try:
            safe_title = "".join(
                c for c in song.get("title", "") if c.isalnum() or c in (" ", "-", "_")).rstrip()
            filename = f"{hashlib.md5(key.encode()).hexdigest()}_{safe_title[:50]}.mp3"
            filepath = os.path.join(self.paths.cache_dir, filename)

            os.makedirs(self.paths.cache_dir, exist_ok=True)
            if cancel.is_set():
                raise _Cancelled()
            if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                item["preexisting"] = True  # zaten diskteydi — "yeni indirildi" sayılmasın
                self._finishRequested.emit(item, filepath)
                return

            last_t = {"v": 0.0}

            def hook(d):
                if cancel.is_set():
                    # yt-dlp bunu temiz bir iptal olarak işler (part dosyalarını
                    # da toplar); eski sürümlerde _Cancelled fallback devreye girer
                    raise _DL_CANCELLED()
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    done = d.get("downloaded_bytes") or 0
                    frac = (done / total) if total else 0.0
                    import time as _time
                    now = _time.monotonic()
                    if now - last_t["v"] >= PROGRESS_EMIT_INTERVAL or frac >= 1.0:
                        last_t["v"] = now
                        item["progress"] = min(frac, 1.0)
                        self.itemChanged.emit(key)

            ydl_opts = yt_dlp_base_opts(
                format="bestaudio/best",
                outtmpl=os.path.splitext(filepath)[0] + ".%(ext)s",
                noplaylist=True,
                socket_timeout=15,
                quiet=True,
                postprocessors=[{"key": "FFmpegExtractAudio",
                                 "preferredcodec": "mp3", "preferredquality": "192"}],
                progress_hooks=[hook],
            )
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([key])

            if cancel.is_set():
                raise _Cancelled()
            if not os.path.isfile(filepath) or os.path.getsize(filepath) == 0:
                raise RuntimeError("İndirme ses dosyası üretmedi; FFmpeg kurulumunu kontrol et.")
            self._finishRequested.emit(item, filepath)
        except (*_CANCEL_EXCS,):
            item["state"] = CANCELLED
            # Öğe bu arada listeden kaldırıldıysa (remove) satırı/bildirimi yok say
            if self.items.get(key) is item and not self._stopping.is_set():
                self.itemChanged.emit(key)
                self.downloadFailed.emit(song, "İptal edildi.")
        except Exception as e:
            log.error("%s %s", "İndirme hatası:", e)
            item["state"] = CANCELLED if cancel.is_set() else FAILED
            item["error"] = "İptal edildi." if cancel.is_set() else str(e)[:200]
            if self.items.get(key) is item and not self._stopping.is_set():
                self.itemChanged.emit(key)
                self.downloadFailed.emit(song, str(e))

    def _finish_on_gui(self, item: dict, path: str):
        """(GUI thread) İndirme bitti: durumu işaretle, cached_path'i kalıcıya yaz."""
        key = item["key"]
        if (self._stopping.is_set() or self.items.get(key) is not item
                or item["cancel"].is_set()):
            return
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            item.update(state=FAILED, error="İndirilen dosya bulunamadı.")
            self.itemChanged.emit(key)
            return
        already_cached = bool(item.pop("preexisting", False))
        item["state"] = DONE
        item["progress"] = 1.0
        item["path"] = path
        for songs in self.store.playlists.values():
            for song in songs:
                if song.get("webpage_url") == key and not song.get("local_path"):
                    song["cached_path"] = path
        self.store.save()
        self._changed_timer.start()   # yeniden başlatılır: seli tek yayına indirir
        self.itemChanged.emit(key)
        self.downloadFinished.emit(item["song"], path, already_cached)

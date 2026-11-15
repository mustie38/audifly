"""
Ortak toplu arama çalıştırıcısı — Toplu Ekle ve Spotify içe aktarma aynı
mekanizmayı paylaşır (orijinal _bulk_add_worker mantığı).

Arka plan thread'inde satırları YouTube'da paralel arar (ThreadPoolExecutor);
sonuçları sinyallerle GUI thread'ine iletir. Liste mutasyonu her zaman GUI
thread'inde yapılır (race condition önlemi).
"""
from __future__ import annotations

import concurrent.futures
import threading
from datetime import datetime

import yt_dlp
from PySide6.QtCore import QObject, Signal

from mustiefly_qt.helpers.constants import BULK_SEARCH_WORKERS, yt_dlp_base_opts
from mustiefly_qt.helpers.logging_setup import get_logger



log = get_logger(__name__)
class BulkSearchWorker(QObject):
    progress = Signal(int, int, str)        # tamamlanan, toplam, sorgu
    itemFound = Signal(dict)                # bulunan şarkı sözlüğü
    finished = Signal(int, list, bool)      # eklenen, başarısız_sorgular, iptal_edildi

    def __init__(self, lines: list[str], existing_urls: set[str], parent=None):
        super().__init__(parent)
        self.lines = lines
        self.existing_urls = set(existing_urls)
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        total = len(self.lines)
        added = 0
        failed: list[str] = []
        completed = 0

        ydl_opts = yt_dlp_base_opts(
            format='bestaudio/best',
            quiet=True,
            default_search='ytsearch1:',
            noplaylist=True,
            socket_timeout=15,
        )

        def search_one(query):
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
            if isinstance(info, dict) and info.get('entries'):
                entries = [e for e in info['entries'] if e]
                info = entries[0] if entries else None
            webpage_url = (info or {}).get('webpage_url', '')
            if not webpage_url:
                raise Exception("Sonuç bulunamadı")
            return info, webpage_url

        with concurrent.futures.ThreadPoolExecutor(max_workers=BULK_SEARCH_WORKERS) as pool:
            future_to_query = {}
            for query in self.lines:
                if self._cancel.is_set():
                    break
                future_to_query[pool.submit(search_one, query)] = query

            for future in concurrent.futures.as_completed(future_to_query):
                query = future_to_query[future]
                completed += 1
                self.progress.emit(completed, total, query)

                if self._cancel.is_set():
                    # Başlamamış aramaları iptal et: aksi halde "with" bloğu kalan TÜM sorguların
                    # bitmesini bekler ve iptal düğmesi dakikalarca etkisiz görünürdü.
                    for pending in future_to_query:
                        pending.cancel()
                    continue  # sonucu tüket ama ekleme

                try:
                    info, webpage_url = future.result()
                    if webpage_url in self.existing_urls:
                        continue  # zaten listede var, sessizce atla
                    self.existing_urls.add(webpage_url)

                    item = {
                        'title': info.get('title') or 'Bilinmeyen Şarkı',
                        'webpage_url': webpage_url,
                        'duration': info.get('duration') or 0,
                        'uploader': info.get('uploader') or info.get('channel') or 'Bilinmeyen Sanatçı',
                        'thumbnail': info.get('thumbnail'),
                        'liked': False,
                        'added_date': datetime.now().isoformat(),
                    }
                    self.itemFound.emit(item)
                    added += 1
                except Exception as e:
                    log.error("%s %s", f"Toplu ekleme hatası ('{query}'):", e)
                    failed.append(query)

        self.finished.emit(added, failed, self._cancel.is_set())

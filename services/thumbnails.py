"""
Şarkı satırları ve kapaklar için thumbnail indirme servisi.

Orijinal mustiefly_sidebar_thumbnails.py'deki mantığın Qt portudur:
- PIL görüntüleri key (webpage_url) bazında önbellekler,
- QPixmap üretimi yalnızca GUI thread'inde yapılır (thumbnailReady sinyali ile),
- indirme sınırlı boyutlu bir havuzda yürür (yüzlerce paralel istek açılmaz),
- kalıcı olarak başarısız linkler işaretlenir (tekrar tekrar denenmez).
"""
from __future__ import annotations

import collections
import concurrent.futures
import hashlib
import io
import os
import threading
import time

import requests
from PIL import Image
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from mustiefly_qt.helpers.constants import THUMBNAIL_MAX_WORKERS
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
MAX_PIL_CACHE_SIZE = 300  # uzun oturumlarda RAM'in sınırsız büyümesini önler
RAM_CACHE_MAX_SIDE = 640   # arayüzde en büyük kullanım ~300 px; tam boy görsel yalnız diskte kalır


def crop_to_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def disk_cache_path(cache_dir: str | None, key: str) -> str | None:
    """Thumbnail disk önbelleği yolu (cache_dir verilmezse None)."""
    if not cache_dir:
        return None
    return os.path.join(cache_dir, "thumbnails",
                        hashlib.md5(key.encode("utf-8")).hexdigest() + ".jpg")


class ThumbnailService(QObject):
    """Şarkı URL'lerinden küçük kapak görselleri indirip QPixmap olarak sunar."""
    thumbnailReady = Signal(str)  # webpage_url — aboneler pixmap'i çeker

    def __init__(self, max_workers: int | None = None, parent=None,
                 disk_cache_dir: str | None = None):
        super().__init__(parent)
        workers = max_workers or THUMBNAIL_MAX_WORKERS
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        self._closed = False
        self.disk_cache_dir = disk_cache_dir
        # LRU: en son erişilen öne taşınır; limit aşılınca en bayatı atılır
        self._pil_cache: collections.OrderedDict[str, Image.Image] = collections.OrderedDict()
        self._fetching: set[str] = set()
        self._failed: set[str] = set()
        self._failed_at: dict[str, float] = {}   # geçici ağ hatası kalıcı olmasın
        self._lock = threading.Lock()
        # Ölçeklenmiş QPixmap önbelleği (yalnız GUI thread'i). Eskiden her
        # pixmap_for çağrısı tam boy görseli yeniden ölçekleyip yuvarlıyordu;
        # liste çizimi ve her thumbnailReady bunu yüzlerce kez tekrarlıyordu.
        self._pm_cache: collections.OrderedDict[tuple, QPixmap] = collections.OrderedDict()

    # --- Önbellek (LRU) ---
    def _cache_get(self, key: str) -> Image.Image | None:
        with self._lock:
            img = self._pil_cache.get(key)
            if img is not None:
                self._pil_cache.move_to_end(key)
            return img

    def _cache_put(self, key: str, img: Image.Image):
        # 1280x720 bir kapak RGB olarak ~2.7 MB tutar; 300 adet yüzlerce MB eder.
        # RAM'de küçültülmüş kopya saklanır (çağıranın img nesnesi değişmez, disk
        # önbelleğine hâlâ tam boy yazılır).
        if max(img.size) > RAM_CACHE_MAX_SIDE:
            img = img.copy()
            img.thumbnail((RAM_CACHE_MAX_SIDE, RAM_CACHE_MAX_SIDE), Image.Resampling.BILINEAR)
        with self._lock:
            self._pil_cache[key] = img
            self._pil_cache.move_to_end(key)
            while len(self._pil_cache) > MAX_PIL_CACHE_SIZE:
                self._pil_cache.popitem(last=False)  # en eski (en az kullanılan)

    # --- Sorgulama (GUI thread'inden çağrılır) ---
    def has_pil(self, song: dict) -> bool:
        return song.get("webpage_url") in self._pil_cache

    def pil_for(self, song: dict) -> Image.Image | None:
        return self._cache_get(song.get("webpage_url"))

    def _is_failed(self, key) -> bool:
        if key not in self._failed:
            return False
        # Ağ anlık koptuğunda kapak oturum boyunca "başarısız" kalıyordu;
        # 90 sn sonra yeniden denemeye izin ver.
        if time.monotonic() - self._failed_at.get(key, 0.0) > 90:
            self._failed.discard(key)
            self._failed_at.pop(key, None)
            return False
        return True

    def is_failed(self, song: dict) -> bool:
        return self._is_failed(song.get("webpage_url"))

    def pixmap_for(self, song: dict, size: int, radius: int | None = None, rounded: bool = True):
        """Hazır bir QPixmap döner; yoksa indirmeyi tetikleyip None verir.
        İndirme bittiğinde thumbnailReady(key) yayınlanır, çağıran yeniden sorar."""
        key = song.get("webpage_url")
        url = song.get("thumbnail")
        if not key or not url or self._is_failed(key):
            return None

        pil_img = self._cache_get(key)
        if pil_img is not None:
            ck = (key, size, radius, rounded)
            cached = self._pm_cache.get(ck)
            if cached is not None:
                self._pm_cache.move_to_end(ck)
                return cached
            # Küçük boyutlarda BILINEAR yeterince kaliteli (kutu filtreli küçültme)
            # ve LANCZOS'tan belirgin hızlı.
            resample = (Image.Resampling.LANCZOS if size >= 120
                        else Image.Resampling.BILINEAR)
            square = crop_to_square(pil_img).resize((size, size), resample)
            pm = QPixmap.fromImage(pil_to_qimage(square))
            if rounded:
                r = radius if radius is not None else max(4, size // 5)
                pm = _rounded_pixmap(pm, r)
            self._pm_cache[ck] = pm
            while len(self._pm_cache) > 600:
                self._pm_cache.popitem(last=False)
            return pm

        with self._lock:
            if key not in self._fetching:
                self._fetching.add(key)
                self._submit(key, url)
        return None

    def request(self, song: dict):
        """Sadece indirmeyi tetikler (sonuç thumbnailReady ile gelir)."""
        key = song.get("webpage_url")
        url = song.get("thumbnail")
        if not key or not url or self._is_failed(key):
            return
        if key in self._pil_cache:
            return
        with self._lock:
            if key in self._fetching:
                return
            self._fetching.add(key)
            self._submit(key, url)

    def _submit(self, key: str, url: str):
        if self._closed:
            self._fetching.discard(key)
            return
        try:
            self._executor.submit(self._download, key, url)
        except RuntimeError:        # kapanış sırasında havuz kapanmış olabilir
            self._fetching.discard(key)

    def shutdown(self):
        """Kapanışta bekleyen indirmeleri iptal eder: işlem süreci takılı thread yüzünden
        açık kalmasın (güncelleme kurulumu çalışan Audifly.exe'yi bulmasın)."""
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --- Arka plan ---
    def _download(self, key: str, url: str):
        try:
            # 1) RAM LRU boşsa disk önbelleğine bak (yeniden başlatışta hızlı)
            path = disk_cache_path(self.disk_cache_dir, key)
            if path and os.path.exists(path):
                try:
                    img = Image.open(path).convert("RGB")
                    self._cache_put(key, img)
                    return
                except Exception:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            self._cache_put(key, img)

            # 2) Disk kalıcılığı — sonraki oturumlarda tekrar indirilmesin.
            # TAM BOYUT kaydediyoruz: küçültüp saklasaydık "Şu An Çalıyor"
            # panelindeki büyük kapaklar bulanık görünürdü.
            if path is not None:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    img.save(path, "JPEG", quality=88)
                except Exception as e:
                    log.error("%s %s", "Thumbnail diske yazılamadı:", e)
        except Exception as e:
            self._failed.add(key)
            self._failed_at[key] = time.monotonic()
            log.error("%s %s", "Thumbnail indirilemedi:", e)
        finally:
            with self._lock:
                self._fetching.discard(key)
            self.thumbnailReady.emit(key)

    def clear_disk_cache(self) -> tuple[int, int]:
        """Disk thumbnail önbelleğini siler. Dönüş: (dosya_sayısı, bayt)."""
        count = total = 0
        if not self.disk_cache_dir:
            return 0, 0
        tdir = os.path.join(self.disk_cache_dir, "thumbnails")
        if not os.path.isdir(tdir):
            return 0, 0
        for name in os.listdir(tdir):
            p = os.path.join(tdir, name)
            try:
                total += os.path.getsize(p)
                os.remove(p)
                count += 1
            except OSError:
                pass
        with self._lock:
            self._pil_cache.clear()
        self._pm_cache.clear()
        return count, total


def pil_to_qimage(pil_img: Image.Image):
    """PIL RGB görüntüsünü QImage'e çevirir (kopyasız, veri PIL tarafından yaşatılır)."""
    from PySide6.QtGui import QImage
    data = pil_img.tobytes("raw", "RGB")
    return QImage(data, pil_img.width, pil_img.height, pil_img.width * 3, QImage.Format.Format_RGB888).copy()


def _rounded_pixmap(pm: QPixmap, radius: int) -> QPixmap:
    from PySide6.QtGui import QPainter, QPainterPath
    from PySide6.QtCore import Qt
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pm.width(), pm.height(), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out

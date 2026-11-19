"""Playlist kapak pixmap'i üretimi — sidebar ve kütüphane grid'i ortak kullanır.

Öncelik: özel kapak > son 4 şarkının kolajı > None (arayan renkli placeholder
gösterir).
"""
from __future__ import annotations

import collections
import os

from PIL import Image
from PySide6.QtGui import QPixmap

from mustiefly_qt.helpers.constants import cover_color_for
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService, crop_to_square, pil_to_qimage
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
_COVER_CACHE_MAX = 128
_COVER_PM_CACHE: collections.OrderedDict[tuple, QPixmap] = collections.OrderedDict()


def _cache_get(key: tuple) -> QPixmap | None:
    pm = _COVER_PM_CACHE.get(key)
    if pm is not None and not pm.isNull():
        _COVER_PM_CACHE.move_to_end(key)
        return pm
    return None


def _cache_put(key: tuple, pm: QPixmap) -> QPixmap:
    _COVER_PM_CACHE[key] = pm
    _COVER_PM_CACHE.move_to_end(key)
    while len(_COVER_PM_CACHE) > _COVER_CACHE_MAX:
        _COVER_PM_CACHE.popitem(last=False)
    return pm


def playlist_cover_pixmap(store: PlaylistStore, thumbnails: ThumbnailService | None,
                          name: str, songs: list[dict], size: int = 300) -> QPixmap | None:
    """Özel kapak ya da kolajdan kare QPixmap üretir; yoksa None döner.
    Aynı kapak/kolaj tekrar sorulduğunda disk/LANCZOS yerine RAM LRU önbelleğinden döner."""
    resample = Image.Resampling.LANCZOS if size > 160 else Image.Resampling.BILINEAR
    # 1) Özel kapak
    path = store.playlist_covers.get(name)
    if path and os.path.exists(path):
        try:
            mtime = os.path.getmtime(path)
            ck = ("custom", path, mtime, size)
            hit = _cache_get(ck)
            if hit is not None:
                return hit
            pil_img = Image.open(path).convert("RGB")
            square = crop_to_square(pil_img).resize((size, size), resample)
            return _cache_put(ck, QPixmap.fromImage(pil_to_qimage(square)))
        except Exception as e:
            log.error("%s %s", "Playlist kapağı yüklenemedi:", e)

    # 2) Son 4 şarkının kolajı
    if thumbnails is not None and songs:
        recent = songs[-4:]
        sig = tuple(s.get("webpage_url") for s in recent)
        ck = ("collage", size, sig)
        hit = _cache_get(ck)
        if hit is not None:
            return hit
        imgs = []
        missing = False
        for s in recent:
            img = thumbnails.pil_for(s)
            if img is None:
                thumbnails.request(s)   # disk önbelleğinden / ağdan yüklenmesini tetikle
                missing = True
            else:
                imgs.append(img)
        if missing:
            return None  # eksik varsa kolaj üretilmez (bayat kolaj olmasın)
        try:
            cell = size // 2
            collage = Image.new("RGB", (size, size), "#282828")
            positions = [(0, 0), (cell, 0), (0, cell), (cell, cell)]
            for i, img in enumerate(imgs[:4]):
                resized = crop_to_square(img).resize((cell, cell), resample)
                collage.paste(resized, positions[i])
            return _cache_put(ck, QPixmap.fromImage(pil_to_qimage(collage)))
        except Exception as e:
            log.error("%s %s", "Kolaj oluşturulamadı:", e)

    return None


def cover_fallback_color(name: str) -> str:
    return cover_color_for(name)


def pick_and_save_cover(store: PlaylistStore, name: str, covers_dir: str, parent=None) -> bool:
    """Kullanıcıdan görsel seçtirir, kare kırpar, covers_dir'e kaydeder ve
    store'a işler. Başarı/başarısızlık mesajlarını kendisi gösterir."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    path, _ = QFileDialog.getOpenFileName(
        parent, f"'{name}' için kapak resmi seç", "",
        "Görsel dosyaları (*.png *.jpg *.jpeg *.webp *.bmp);;Tüm dosyalar (*.*)")
    if not path:
        return False
    try:
        pil_img = Image.open(path).convert("RGB")
    except Exception as e:
        QMessageBox.critical(parent, "Görsel Açılamadı",
                             f"Seçilen dosya bir görsel olarak açılamadı:\n\n{e}")
        return False

    os.makedirs(covers_dir, exist_ok=True)
    import hashlib
    dest_path = os.path.join(covers_dir, f"{hashlib.md5(name.encode('utf-8')).hexdigest()}.jpg")
    try:
        square = crop_to_square(pil_img).resize((300, 300), Image.Resampling.LANCZOS)
        square.save(dest_path, "JPEG", quality=90)
    except Exception as e:
        QMessageBox.critical(parent, "Kaydedilemedi",
                             f"Kapak resmi kaydedilirken hata oluştu:\n\n{e}")
        return False

    store.playlist_covers[name] = dest_path
    store.save()
    store.playlistsChanged.emit()
    store.statusMessage.emit(f"'{name}' listesinin kapağı güncellendi.", "success")
    return True


def format_playlist_duration(songs: list[dict]) -> str:
    """'3 dakika 12 saniye' / '1 saat 4 dakika' biçiminde toplam süre."""
    total = int(sum((s.get("duration") or 0) for s in songs))
    if total <= 0:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours} saat")
    if minutes:
        parts.append(f"{minutes} dakika")
    if seconds and not hours:
        parts.append(f"{seconds} saniye")
    return " ".join(parts) if parts else "0 saniye"

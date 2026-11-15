"""
Tüm kütüphane yedekleme / geri yükleme.

Tek JSON dosyası: tüm playlistler + kapak görselleri (base64 gömülü) + aktif
liste + taşınabilir uygulama ayarları (v2). Tema/ekolayzer taşınır;
Spotify secret/token ve son oturum bilgisi güvenlik için taşınmaz.
(v1 yedekleri ayarsızdır; geri yükleme sırasında sorunsuz kabul edilir.)
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QMessageBox

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.services.playlist_store import PlaylistStore, _clean_song, _normalize_library
from mustiefly_qt.helpers.persistence import atomic_write_json
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
BACKUP_FORMAT = "audifly-backup"
ACCEPTED_BACKUP_FORMATS = (BACKUP_FORMAT, "mustiefly-backup")   # eski yedekler içe aktarılabilir
BACKUP_VERSION = 2

# Yedekte taşınmayacak anahtarlar (makineye/oturuma özgü geçici durumlar)
NON_PORTABLE_SETTING_KEYS = {
    "_volume", "_rate", "now_playing_panel_visible", "last_session",
    "spotify_client_secret", "spotify_refresh_token", "spotify_access_token",
    "skipped_update_version",
}
MAX_BACKUP_BYTES = 64 * 1024 * 1024
MAX_COVER_BYTES = 8 * 1024 * 1024


def export_library(store: PlaylistStore, path: str, settings: dict | None = None) -> str | None:
    """Kütüphaneyi yazar. Hata olursa mesaj döner, başarılıysa None."""
    covers_b64 = {}
    for name, cover_path in store.playlist_covers.items():
        try:
            if cover_path and os.path.isfile(cover_path):
                if os.path.getsize(cover_path) > MAX_COVER_BYTES:
                    return f"Kapak çok büyük: {name} (en fazla 8 MiB)."
                with open(cover_path, "rb") as f:
                    covers_b64[name] = base64.b64encode(f.read()).decode("ascii")
        except Exception as e:
            log.error("%s %s", f"Kapak gömülemedi ('{name}'):", e)

    data = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": datetime.now().isoformat(),
        "active_playlist": store.active_playlist,
        # Ham sözlükler değil, temizlenmiş kopya: aksi halde süreli YouTube
        # stream_url / resolved_at gibi geçici alanlar yedeğe sızıyordu.
        "playlists": {n: [_clean_song(x) for x in songs] for n, songs in store.playlists.items()},
        "covers": covers_b64,
    }
    if settings is not None:
        data["settings"] = {
            k: v for k, v in settings.items()
            if k not in NON_PORTABLE_SETTING_KEYS
        }
    try:
        # Never silently overwrite an existing backup with a partial file.
        if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_BACKUP_BYTES:
            return "Yedek en fazla 64 MiB olabilir."
        atomic_write_json(path, data)
    except Exception as e:
        return str(e)
    return None


def import_library(store: PlaylistStore, path: str, settings: dict | None = None) -> tuple[int, str]:
    """Yedeği yükler ve MEVCUT kütüphanenin üzerine yazar (UI onay sorar).
    settings verilirse yedekteki ayarlar da bu sözlüğe işlenir (kalıcı kayıt
    ve canlı uygulama çağıranın sorumluluğundadır).
    Dönüş: (içe aktarılan şarkı sayısı, hata_mesajı — boşsa başarılı)."""
    try:
        if os.path.getsize(path) > MAX_BACKUP_BYTES:
            raise ValueError("Yedek en fazla 64 MiB olabilir.")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("format") not in ACCEPTED_BACKUP_FORMATS:
            raise ValueError(f"Bu dosya geçerli bir {APP_DISPLAY_NAME} yedeği değil.")
        version = data.get("version", 1)
        if type(version) is not int or version not in (1, BACKUP_VERSION):
            raise ValueError("Desteklenmeyen yedek sürümü.")
        playlists, active, _ = _normalize_library(data)
        raw_covers = data.get("covers", {})
        if not isinstance(raw_covers, dict):
            raise ValueError("Geçersiz kapak verisi.")
        decoded = {}
        for name, b64 in raw_covers.items():
            if name not in playlists:
                continue
            if not isinstance(b64, str) or len(b64) > ((MAX_COVER_BYTES + 2) // 3) * 4:
                raise ValueError("Geçersiz veya çok büyük kapak.")
            cover = base64.b64decode(b64, validate=True)
            if len(cover) > MAX_COVER_BYTES:
                raise ValueError("Kapak en fazla 8 MiB olabilir.")
            decoded[name] = cover
        portable_settings = data.get("settings", {})
        if not isinstance(portable_settings, dict):
            raise ValueError("Geçersiz ayar verisi.")
    except Exception as e:
        return 0, f"Yedek dosyası yüklenemedi: {e}"

    # Stage into unique files; failure cannot corrupt existing covers/library.
    restored_covers = {}
    try:
        os.makedirs(store.paths.covers_dir, exist_ok=True)
        for name, cover in decoded.items():
            dest = os.path.join(store.paths.covers_dir, f"restore-{uuid.uuid4().hex}.jpg")
            restored_covers[name] = dest
            with open(dest, "xb") as f:
                f.write(cover)
        if store.flush_now() is False:
            raise OSError("Mevcut kütüphane kaydedilemedi; geri yükleme durduruldu.")
        snapshot = {"playlists": playlists, "active_playlist": active,
                    "playlist_covers": restored_covers}
        store._backup_playlist_file()
        atomic_write_json(store.paths.playlist_file, snapshot)
    except Exception as e:
        for dest in restored_covers.values():
            try:
                os.remove(dest)
            except OSError:
                pass
        return 0, f"Yedek geri yüklenemedi: {e}"

    # Discard references to the old library, including delayed deletions/undo.
    for timer in store._pending_file_deletions.values():
        timer.stop()
        timer.deleteLater()
    store._pending_file_deletions.clear()
    store._undo_stack.clear()
    store.manual_queue.clear()
    store.playlists = playlists
    store.playlist_covers = restored_covers
    store.active_playlist = active
    store._pending_snapshot = None
    store._save_dirty = False
    store._failed_snapshot = None
    if settings is not None:
        from mustiefly_qt.auth.service import _SETTING_RULES, validate_settings
        from mustiefly_qt.helpers.constants import DEFAULT_SETTINGS
        # Yalnızca bilinen, taşınabilir anahtarlar (izin listesi) alınır.
        settings.update({k: v for k, v in portable_settings.items()
                         if k in DEFAULT_SETTINGS and k not in NON_PORTABLE_SETTING_KEYS})
        checked = validate_settings(dict(settings))
        # Sayısal/bool alanlar + tema, ekolayzer bantları ve akıllı kurallar doğrulanmış halleriyle
        # alınır; aksi halde bozuk bir yedek oturum içinde (yeniden başlatmaya kadar) bozuk değer bırakırdı.
        validated_keys = set(_SETTING_RULES) | {"theme", "equalizer_bands", "smart_rules"}
        for key in portable_settings:
            if key in validated_keys and key in checked:
                settings[key] = checked[key]
    store.undoAvailable.emit(False)
    store.queueChanged.emit()
    store.playlistsChanged.emit()
    store.activePlaylistChanged.emit(active)
    return sum(len(songs) for songs in playlists.values()), ""


# --- Diyalog akışları ---
def export_library_dialog(store: PlaylistStore, parent=None, settings: dict | None = None):
    default_name = f"audifly-yedek-{datetime.now():%Y%m%d}.json"
    path, _ = QFileDialog.getSaveFileName(
        parent, "Kütüphaneyi yedekle", default_name, "JSON Yedek (*.json)")
    if not path:
        return
    err = export_library(store, path, settings)
    if err:
        QMessageBox.warning(parent, "Hata", f"Yedek alınamadı:\n{err}")
        store.statusMessage.emit("❌ Yedek alınamadı.", "error")
    else:
        total = sum(len(songs) for songs in store.playlists.values())
        extra = " + ayarlar" if settings is not None else ""
        store.statusMessage.emit(
            f"💾 Yedek alındı: {total} şarkı{extra} → {os.path.basename(path)}", "success")


def import_library_dialog(store: PlaylistStore, parent=None, settings: dict | None = None,
                          on_settings_restored=None):
    """on_settings_restored: yedekte ayar varsa geri yükleme sonrası çağrılır
    (MainWindow temayı yeniden uygular, 'yeniden başlat' uyarısı verir)."""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Yedekten geri yükle", "", "JSON Yedek (*.json);;Tüm dosyalar (*.*)")
    if not path:
        return
    confirm = QMessageBox.question(
        parent, "Geri Yükle",
        "Yedek yüklendiğinde MEVCUT tüm playlistlerin yerine geçer.\n"
        "Devam etmek istiyor musun?",
        QMessageBox.Yes | QMessageBox.No)
    if confirm != QMessageBox.Yes:
        return
    total, err = import_library(store, path, settings)
    if err:
        QMessageBox.warning(parent, "Hata", f"Geri yükleme başarısız:\n{err}")
    else:
        store.statusMessage.emit(
            f"📂 Yedek geri yüklendi: {total} şarkı.", "success")
        if settings is not None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    has_settings = isinstance(json.load(f).get("settings"), dict)
            except Exception:
                has_settings = False
            if has_settings and on_settings_restored is not None:
                on_settings_restored()

"""
Çalma listesi verisinin yüklenmesi/kaydedilmesi/CRUD işlemleri + manuel kuyruk
("Sıradaki") + geri al (undo) altyapısı.

UI'dan bağımsız bir servistir (QObject) — sinyaller yayınlar, hiçbir widget'a
doğrudan referansı yoktur.

Dosya formatı orijinal (tkinter) sürümle birebir aynıdır; manual kuyruk ve undo
stack bilinçli olarak diske yazılmaz (orijinaldeki gibi oturumluk durumdur).
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime

from mustiefly_qt.helpers.persistence import atomic_write_json

from PySide6.QtCore import QObject, QTimer, Signal

from mustiefly_qt.helpers.constants import AppPaths, BACKUP_MIN_INTERVAL, DEFAULT_PLAYLIST_NAME
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
SAVE_DEBOUNCE_MS = 400
UNDO_STACK_LIMIT = 10
PENDING_DELETE_DELAY_MS = 8000  # "geri al" penceresi kadar dosyaları diskte tut


def _clean_song(s: dict) -> dict:
    def text(key, default=""):
        value = s.get(key)
        return value if isinstance(value, str) and value else default

    def number(key):
        try:
            value = float(s.get(key) or 0)
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    out = {
        "title": text("title", "Bilinmeyen Şarkı"),
        "webpage_url": text("webpage_url"),
        "duration": number("duration"),
        "uploader": text("uploader", "Bilinmeyen Sanatçı"),
        "thumbnail": text("thumbnail") or None,
        "liked": s.get("liked") is True,
        "cached_path": text("cached_path") or None,
        "added_date": text("added_date"),
        "play_count": number("play_count"),
        "last_played": text("last_played") or None,
    }
    if text("local_path"):
        out["local_path"] = text("local_path")
    return out


def _normalize_library(data):
    """Validate the container before replacing any live library state."""
    if isinstance(data, list):
        data = {"playlists": {DEFAULT_PLAYLIST_NAME: data}}
    if not isinstance(data, dict) or not isinstance(data.get("playlists"), dict):
        raise ValueError("Geçersiz kütüphane yapısı.")
    playlists = {}
    for name, songs in data["playlists"].items():
        if not isinstance(name, str) or not name.strip() or not isinstance(songs, list):
            continue
        playlists[name] = [_clean_song(s) for s in songs if isinstance(s, dict)
                           and (isinstance(s.get("webpage_url"), str) and s["webpage_url"]
                                or isinstance(s.get("local_path"), str) and s["local_path"])]
    if not playlists:
        raise ValueError("Geçerli çalma listesi bulunamadı.")
    active = data.get("active_playlist")
    active = active if isinstance(active, str) and active in playlists else next(iter(playlists))
    raw_covers = data.get("playlist_covers", {})
    covers = {name: path for name, path in raw_covers.items()
              if name in playlists and isinstance(path, str) and os.path.isfile(path)} if isinstance(raw_covers, dict) else {}
    return playlists, active, covers


class PlaylistStore(QObject):
    statusMessage = Signal(str, str)       # (mesaj, seviye: "info"|"success"|"warning"|"error")
    playlistsChanged = Signal()            # yapı değişti (oluşturma/silme/yeniden adlandırma/şarkı ekleme-çıkarma)
    activePlaylistChanged = Signal(str)
    queueChanged = Signal()                # manuel kuyruk değişti
    undoAvailable = Signal(bool)           # geri alınacak işlem var mı

    def __init__(self, paths: AppPaths, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.playlists: dict[str, list[dict]] = {DEFAULT_PLAYLIST_NAME: []}
        self.playlist_covers: dict[str, str] = {}
        self.active_playlist: str = DEFAULT_PLAYLIST_NAME

        # Manuel kuyruk: [(playlist_adı, index, şarkı_ref), ...]
        self.manual_queue: list[tuple[str, int, dict]] = []

        # Geri al (undo) altyapısı
        self._undo_stack: list[tuple] = []
        self._pending_file_deletions: dict[str, QTimer] = {}

        self._pending_snapshot = None
        self._save_dirty = False   # snapshot gecikmeli (debounce sonunda) üretilir
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_pending_save)
        self._write_in_progress = False
        self._writer_thread = None
        self._failed_snapshot = None
        self._last_backup_time = 0.0
        self.backup_enabled = True  # MainWindow settings'ten bağlanır

    # --- Yükleme ---
    def load(self):
        if not os.path.exists(self.paths.playlist_file):
            return
        try:
            with open(self.paths.playlist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            normalized = _normalize_library(data)
        except (ValueError, OSError, UnicodeDecodeError) as e:
            log.warning("Ana playlist okunamadı (%s), yedekler deneniyor...", e)
            data = self._try_recover_from_backup()
            self._quarantine_library_file()   # bozuk dosya sonraki kayıtla ezilmesin
            if data is None:
                self.statusMessage.emit(
                    "Kütüphane okunamadı; bozuk dosya '.corrupt' olarak saklandı, "
                    "geçerli bir yedek bulunamadı.", "warning")
                return
            normalized = _normalize_library(data)
            self.statusMessage.emit("Kütüphane yedekten kurtarıldı.", "success")
        self.playlists, self.active_playlist, self.playlist_covers = normalized
        total = sum(len(songs) for songs in self.playlists.values())
        self.statusMessage.emit(f"{len(self.playlists)} çalma listesi yüklendi ({total} şarkı).", "info")

    def _quarantine_library_file(self):
        try:
            os.replace(self.paths.playlist_file,
                       f"{self.paths.playlist_file}.corrupt-{int(time.time())}")
        except OSError as e:
            log.error("Bozuk kütüphane dosyası ayrılamadı: %s", e)

    def _try_recover_from_backup(self):
        backup_dir = os.path.join(os.path.dirname(self.paths.playlist_file), "backups")
        for bak_name in ("playlists.bak1.json", "playlists.bak2.json", "playlists.bak3.json"):
            bak_path = os.path.join(backup_dir, bak_name)
            if not os.path.exists(bak_path):
                continue
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _normalize_library(data)
                return data
            except Exception as e:
                log.error("%s %s", f"'{bak_name}' de bozuk, bir sonraki yedek deneniyor:", e)
        return None

    # --- Kaydetme (debounce'lu) ---
    def save(self):
        """Kaydı 400ms sonraya planlar; art arda çağrılar tek yazmaya iner."""
        # Tüm kütüphaneyi her save()'de kopyalamak (her şarkı başlangıcında!)
        # GUI thread'ini yoruyordu; yalnız "kirli" işaretle, debounce sonunda üret.
        self._save_dirty = True
        self._save_timer.start(SAVE_DEBOUNCE_MS)

    def flush_now(self):
        """Uygulama kapanırken bekleyen kaydı senkron olarak diske yazar."""
        self._save_timer.stop()
        # A background write must finish BEFORE the final snapshot is written.
        # Otherwise an older worker can overwrite the close-time library.
        if self._writer_thread is not None:
            self._writer_thread.join()
        if self._save_dirty:
            self._pending_snapshot = self._build_snapshot()
            self._save_dirty = False
        snapshot = self._pending_snapshot or self._failed_snapshot
        if snapshot is None:
            return True
        self._pending_snapshot = None
        return self._write_playlist_file(snapshot)

    def _build_snapshot(self) -> dict:
        return {
            "playlists": {
                name: [_clean_song(s) for s in songs]
                for name, songs in self.playlists.items()
            },
            "active_playlist": self.active_playlist,
            "playlist_covers": dict(self.playlist_covers),
        }

    def _flush_pending_save(self):
        if self._write_in_progress:
            self._save_timer.start(150)
            return
        if self._save_dirty:
            self._pending_snapshot = self._build_snapshot()
            self._save_dirty = False
        snapshot = self._pending_snapshot
        if snapshot is None:
            return
        self._pending_snapshot = None
        self._write_in_progress = True
        self._writer_thread = threading.Thread(
            target=self._write_playlist_file, args=(snapshot,), daemon=True,
            name="mustiefly-save")
        self._writer_thread.start()

    def _backup_playlist_file(self):
        if not self.backup_enabled:
            return
        if not os.path.exists(self.paths.playlist_file):
            return
        now = time.time()
        if (now - self._last_backup_time) < BACKUP_MIN_INTERVAL:
            return
        try:
            with open(self.paths.playlist_file, "r", encoding="utf-8") as f:
                _normalize_library(json.load(f))
        except Exception:
            return  # mevcut dosya geçersiz: sağlam yedekleri ezme
        self._last_backup_time = now
        backup_dir = os.path.join(os.path.dirname(self.paths.playlist_file), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        try:
            for i in (2, 1):
                src = os.path.join(backup_dir, f"playlists.bak{i}.json")
                dst = os.path.join(backup_dir, f"playlists.bak{i + 1}.json")
                if os.path.exists(src):
                    shutil.copy2(src, dst)
            shutil.copy2(self.paths.playlist_file, os.path.join(backup_dir, "playlists.bak1.json"))
        except Exception as e:
            log.error("%s %s", "Yedekleme başarısız:", e)

    def _write_playlist_file(self, data: dict):
        try:
            self._backup_playlist_file()
            atomic_write_json(self.paths.playlist_file, data)
            self._failed_snapshot = None
            return True
        except Exception as e:
            self._failed_snapshot = data
            log.error("%s %s", "Çalma listeleri kaydedilemedi:", e)
            self.statusMessage.emit("Kütüphane kaydedilemedi. Disk alanını ve izinleri kontrol et.", "error")
            return False
        finally:
            self._write_in_progress = False

    # --- CRUD ---
    def create_playlist(self, name: str) -> tuple[bool, str]:
        name = name.strip()
        if not name:
            return False, "Liste adı boş olamaz."
        if name in self.playlists:
            return False, "Bu isimde bir liste zaten var."
        self.playlists[name] = []
        self.active_playlist = name
        self.save()
        self.playlistsChanged.emit()
        self.activePlaylistChanged.emit(name)
        return True, ""

    def rename_playlist(self, old_name: str, new_name: str) -> tuple[bool, str]:
        new_name = new_name.strip()
        if old_name not in self.playlists or not new_name or new_name == old_name:
            return False, ""
        if new_name in self.playlists:
            return False, "Bu isimde bir liste zaten var."
        self.playlists[new_name] = self.playlists.pop(old_name)
        if old_name in self.playlist_covers:
            self.playlist_covers[new_name] = self.playlist_covers.pop(old_name)
        if self.active_playlist == old_name:
            self.active_playlist = new_name
        self.manual_queue = [(new_name if pl == old_name else pl, idx, song)
                             for pl, idx, song in self.manual_queue]
        self.save()
        self.playlistsChanged.emit()
        self.activePlaylistChanged.emit(self.active_playlist)
        self.queueChanged.emit()
        return True, ""

    def delete_playlist(self, name: str) -> tuple[bool, str]:
        if name not in self.playlists:
            return False, "Liste bulunamadı."
        if len(self.playlists) <= 1:
            return False, "Son çalma listesi silinemez."
        songs = self.playlists.pop(name)
        cover_path = self.playlist_covers.pop(name, None)

        # Silinen listedeki şarkılar kuyruktaysa temizle
        self.manual_queue = [q for q in self.manual_queue if q[0] != name]

        if self.active_playlist == name:
            self.active_playlist = next(iter(self.playlists))
        self.save()
        self.playlistsChanged.emit()
        self.activePlaylistChanged.emit(self.active_playlist)
        self.queueChanged.emit()

        self._push_undo(("delete_playlist", name, songs, cover_path))
        self._schedule_cover_deletion(cover_path)
        return True, ""

    def switch_playlist(self, name: str):
        if name in self.playlists and name != self.active_playlist:
            self.active_playlist = name
            self.save()
            self.activePlaylistChanged.emit(name)

    def add_song(self, playlist_name: str, song: dict) -> bool:
        """False dönerse şarkı zaten o listede vardır (eklenmedi)."""
        songs = self.playlists.setdefault(playlist_name, [])
        existing = {s.get("webpage_url") for s in songs}
        if song.get("webpage_url") in existing:
            return False
        songs.append(_clean_song({**song, "added_date": song.get("added_date") or datetime.now().isoformat()}))
        self.save()
        self.playlistsChanged.emit()
        return True

    def move_song(self, playlist_name: str, index: int, target_playlist: str) -> bool:
        """Şarkıyı bir playlistten diğerine taşır. False dönerse taşınmadı
        (hedefte aynı şarkı zaten var / index geçersiz)."""
        songs = self.playlists.get(playlist_name)
        if not songs or not (0 <= index < len(songs)):
            return False
        if target_playlist == playlist_name or target_playlist not in self.playlists:
            return False
        song = songs[index]
        target = self.playlists[target_playlist]
        if any(s.get("webpage_url") == song.get("webpage_url") for s in target):
            return False
        songs.pop(index)
        target.append(song)
        # Kuyruk referansları index'e değil objeye/URL'e dayalı çözülür
        # (locate_song) — bu yüzden burada ek düzeltme gerekmez.
        self.save()
        self.playlistsChanged.emit()
        return True

    def remove_songs_batch(self, refs: list[tuple[str, int]]) -> int:
        """Çoklu seçimle silme. refs: (playlist_adı, index) listesi.
        Tek composite undo kaydı tutar; kaç şarkı silindiğini döner."""
        # Indexler silme sırasında kayacağı için her playlist için büyükten küçüğe
        by_playlist: dict[str, list[int]] = {}
        for pl, idx in refs:
            if pl in self.playlists:
                by_playlist.setdefault(pl, []).append(idx)
        removed: list[tuple[str, int, dict]] = []
        for pl, idxs in by_playlist.items():
            songs = self.playlists[pl]
            for idx in sorted(set(idxs), reverse=True):
                if 0 <= idx < len(songs):
                    removed.append((pl, idx, songs.pop(idx)))
        if not removed:
            return 0
        self._push_undo(("bulk_delete", removed))
        removed_refs = {id(s) for _, _, s in removed}
        self.manual_queue = [q for q in self.manual_queue if id(q[2]) not in removed_refs]
        self.save()
        self.playlistsChanged.emit()
        self.queueChanged.emit()
        for _, _, s in removed:
            self._schedule_file_deletion(s.get("cached_path"))
        return len(removed)

    def remove_song(self, playlist_name: str, index: int):
        songs = self.playlists.get(playlist_name)
        if not songs or not (0 <= index < len(songs)):
            return
        song = songs.pop(index)
        self.manual_queue = [
            q for q in self.manual_queue
            if not (q[0] == playlist_name and q[2].get("webpage_url") == song.get("webpage_url"))
        ]
        self.save()
        self.playlistsChanged.emit()
        self.queueChanged.emit()

        self._push_undo(("delete_song", playlist_name, index, song))
        self._schedule_file_deletion(song.get("cached_path"))

    def toggle_like(self, playlist_name: str, index: int):
        songs = self.playlists.get(playlist_name)
        if not songs or not (0 <= index < len(songs)):
            return
        songs[index]["liked"] = not songs[index].get("liked", False)
        self.save()
        self.playlistsChanged.emit()

    def move_song_to_playlist(self, from_playlist: str, from_index: int, to_playlist: str) -> tuple[bool, str]:
        songs = self.playlists.get(from_playlist)
        if not songs or not (0 <= from_index < len(songs)) or to_playlist not in self.playlists:
            return False, "Geçersiz taşıma."
        song = songs[from_index]
        target = self.playlists[to_playlist]
        if any(s.get("webpage_url") == song.get("webpage_url") for s in target):
            return False, f"Şarkı zaten \"{to_playlist}\" listesinde."
        target.append(song)
        songs.pop(from_index)
        self.save()
        self.playlistsChanged.emit()
        return True, ""

    def clear_playlist(self, name: str):
        """Listedeki tüm şarkıları kaldırır (geri alınabilir)."""
        songs = self.playlists.get(name)
        if not songs:
            return
        removed = list(songs)
        self.playlists[name] = []
        self.manual_queue = [q for q in self.manual_queue if q[0] != name]
        self.save()
        self.playlistsChanged.emit()
        self.queueChanged.emit()

        self._push_undo(("clear_playlist", name, removed))
        for s in removed:
            self._schedule_file_deletion(s.get("cached_path"))

    @property
    def liked_songs(self) -> list[tuple[str, int, dict]]:
        result = []
        for name, songs in self.playlists.items():
            for idx, s in enumerate(songs):
                if s.get("liked"):
                    result.append((name, idx, s))
        return result

    # --- Manuel kuyruk ("Sıradaki") ---
    def add_to_queue(self, playlist_name: str, index: int, song: dict):
        self.manual_queue.append((playlist_name, index, song))
        self.queueChanged.emit()
        self.statusMessage.emit(f"➕ '{song.get('title', '?')}' kuyruğa eklendi.", "success")

    def add_to_queue_next(self, playlist_name: str, index: int, song: dict):
        """'Sırada Çal': şarkıyı kuyruğun EN ÖNÜNE ekler — mevcut şarkı bitince
        hemen o çalar (Spotify'ın 'Play Next' davranışı)."""
        self.manual_queue.insert(0, (playlist_name, index, song))
        self.queueChanged.emit()
        self.statusMessage.emit(f"⏭ '{song.get('title', '?')}' sırada çalacak.", "success")

    def remove_from_queue(self, q_idx: int):
        if not (0 <= q_idx < len(self.manual_queue)):
            return
        removed_item = self.manual_queue.pop(q_idx)
        self.queueChanged.emit()
        self._push_undo(("remove_from_queue", q_idx, removed_item))

    def set_queue(self, items: list[tuple[str, int, dict]]):
        """Kuyruğu verilen liste ile değiştirir (Mix çalarken kullanılır)."""
        self.manual_queue = list(items)
        self.queueChanged.emit()

    def clear_queue(self):
        if self.manual_queue:
            old_queue = list(self.manual_queue)
            self.manual_queue = []
            self.queueChanged.emit()
            self._push_undo(("clear_queue", old_queue))
            self.statusMessage.emit("Kuyruk temizlendi.", "info")

    def pop_next_from_queue(self) -> tuple[str, int, dict] | None:
        """Otomatik geçişte sıradaki kuyruk öğesini verir (Spotify mantığı)."""
        if not self.manual_queue:
            return None
        item = self.manual_queue.pop(0)
        self.queueChanged.emit()
        return item

    def play_from_queue(self, q_idx: int) -> tuple[str | None, int]:
        """Kuyruktaki bir şarkıyı çalar. Ondan öncekiler 'geçilmiş' sayılıp
        kuyruktan düşer. Dönüş: (gerçek_playlist_adi_ya_None, gerçek_index)."""
        if not (0 <= q_idx < len(self.manual_queue)):
            return None, -1
        pl_name, orig_idx, song = self.manual_queue[q_idx]
        del self.manual_queue[:q_idx + 1]
        self.queueChanged.emit()
        real_pl, real_idx = self.locate_song(pl_name, orig_idx, song)
        return real_pl, real_idx

    def locate_song(self, hint_playlist: str, hint_idx: int, song: dict) -> tuple[str | None, int]:
        """Bir şarkının GÜNCEL playlist adı + index'ini bulur.

        Sıra: (1) ipucu konumdaki obje kimliği (hızlı/yol), (2) ipucu listede
        webpage_url, (3) tüm kütüphanede webpage_url, (4) tüm kütüphanede obje
        kimliği. URL önce gelir çünkü kuyruktaki referans, şarkı silinip
        yeniden eklendiğinde (_clean_song yeni dict üretir) bayatlayabilir;
        URL ise kalıcı kimliktir. Bulunamazsa (None, -1) döner."""
        hint_songs = self.playlists.get(hint_playlist)
        if (hint_songs is not None and 0 <= hint_idx < len(hint_songs)
                and hint_songs[hint_idx] is song):
            return hint_playlist, hint_idx

        url = song.get('webpage_url')
        if url:
            hint_match = self._find_by_url(hint_playlist, url)
            if hint_match is not None:
                return hint_match
            for pl_name in self.playlists:
                if pl_name == hint_playlist:
                    continue
                match = self._find_by_url(pl_name, url)
                if match is not None:
                    return match

        for pl_name, songs in self.playlists.items():
            for i, s in enumerate(songs):
                if s is song:
                    return pl_name, i

        return None, -1

    def _find_by_url(self, playlist_name: str, url: str) -> tuple[str, int] | None:
        songs = self.playlists.get(playlist_name)
        if not songs:
            return None
        for i, s in enumerate(songs):
            if s.get('webpage_url') == url:
                return playlist_name, i
        return None

    # --- Tekrarlanan şarkı bulucu ---
    def find_duplicate_groups(self) -> list[list[tuple[str, int, dict]]]:
        """Aynı YouTube videosunun birden fazla kopyasını gruplar (webpage_url'e göre)."""
        by_url: dict[str, list[tuple[str, int, dict]]] = {}
        for pl_name, songs in self.playlists.items():
            for idx, song in enumerate(songs):
                key = song.get('webpage_url')
                if not key:
                    continue
                by_url.setdefault(key, []).append((pl_name, idx, song))
        return [group for group in by_url.values() if len(group) > 1]

    def clean_duplicates(self, groups: list[list[tuple[str, int, dict]]]) -> int:
        """Her grupta İLK kopyayı tutar, gerisini siler. Silinen adet döner."""
        to_remove = []
        for group in groups:
            for pl, idx, song in group[1:]:
                to_remove.append((pl, idx, song))
        # Aynı playlistten çoklu silmede index kaymasın: yüksekten düşüğe
        to_remove.sort(key=lambda t: -t[1])
        before_queue_len = len(self.manual_queue)

        removed = []
        for pl, idx, song in to_remove:
            songs = self.playlists.get(pl)
            if not songs or idx >= len(songs) or songs[idx] is not song:
                continue
            removed.append((pl, idx, song))
            songs.pop(idx)
            self._schedule_file_deletion(song.get("cached_path"))

        if removed:
            self._push_undo(("bulk_delete", removed))
            removed_refs = {id(s) for _, _, s in removed}
            self.manual_queue = [q for q in self.manual_queue if id(q[2]) not in removed_refs]
            if len(self.manual_queue) != before_queue_len:
                self.queueChanged.emit()
        self.save()
        self.playlistsChanged.emit()
        return len(removed)

    # --- Geri al (undo) ---
    def _push_undo(self, action: tuple):
        self._undo_stack.append(action)
        if len(self._undo_stack) > UNDO_STACK_LIMIT:
            self._undo_stack.pop(0)
        self.undoAvailable.emit(True)

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def perform_undo(self) -> str:
        """Son işlemi geri alır; kullanıcıya gösterilecek mesajı döndürür."""
        if not self._undo_stack:
            return ""
        action = self._undo_stack.pop()
        kind = action[0]
        message = "↩ Geri alındı."

        if kind == "delete_song":
            _, pl, idx, song = action
            songs = self.playlists.setdefault(pl, [])
            idx = min(idx, len(songs))
            songs.insert(idx, song)
            self._cancel_pending_deletion(song.get("cached_path"))
            message = f"↩ '{song.get('title', '?')}' geri getirildi."

        elif kind == "bulk_delete":
            _, removed = action
            for pl, idx, song in reversed(removed):
                songs = self.playlists.setdefault(pl, [])
                idx = min(idx, len(songs))
                songs.insert(idx, song)
                self._cancel_pending_deletion(song.get("cached_path"))
            message = f"↩ {len(removed)} şarkı geri getirildi."

        elif kind == "clear_queue":
            _, old_queue = action
            self.manual_queue = list(old_queue)
            self.queueChanged.emit()
            message = f"↩ Kuyruktaki {len(old_queue)} şarkı geri getirildi."

        elif kind == "remove_from_queue":
            _, q_idx, removed_item = action
            insert_at = min(q_idx, len(self.manual_queue))
            self.manual_queue.insert(insert_at, removed_item)
            self.queueChanged.emit()
            title = removed_item[2].get("title", "?") if len(removed_item) == 3 else "?"
            message = f"↩ '{title}' kuyruğa geri eklendi."

        elif kind == "clear_playlist":
            _, name, songs = action
            self.playlists[name] = songs + self.playlists.get(name, [])
            for s in songs:
                self._cancel_pending_deletion(s.get("cached_path"))
            message = f"↩ '{name}' listesindeki {len(songs)} şarkı geri getirildi."

        elif kind == "delete_playlist":
            _, name, songs, cover_path = action
            restore_name = name
            if restore_name in self.playlists:
                suffix = 2
                candidate = f"{name} (Geri Alındı)"
                while candidate in self.playlists:
                    candidate = f"{name} (Geri Alındı {suffix})"
                    suffix += 1
                restore_name = candidate
                message = f"↩ '{name}' geri getirildi — '{restore_name}' olarak eklendi."
            else:
                message = f"↩ '{name}' listesi geri getirildi."

            self.playlists[restore_name] = songs
            if cover_path and os.path.exists(cover_path):
                self.playlist_covers[restore_name] = cover_path
                self._cancel_cover_deletion(cover_path)
            for s in songs:
                self._cancel_pending_deletion(s.get("cached_path"))

        # View katmanı undoAvailable sinyalini dinleyip snackbar'ı gizler
        self.save()
        self.playlistsChanged.emit()
        self.undoAvailable.emit(self.can_undo())
        return message

    # --- Gecikmeli dosya silme ("geri al" penceresi) ---
    def _schedule_file_deletion(self, path: str | None):
        """İndirilmiş dosyayı HEMEN silmek yerine 8 sn bekletir; kullanıcı bu süre
        içinde geri alırsa dosya hâlâ diskte olur."""
        if not self._can_delete_owned_file(path):
            return
        if path in self._pending_file_deletions:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda p=path: self._execute_file_deletion(p))
        self._pending_file_deletions[path] = timer
        timer.start(PENDING_DELETE_DELAY_MS)

    def _execute_file_deletion(self, path: str):
        timer = self._pending_file_deletions.pop(path, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if self._can_delete_owned_file(path):
            try:
                os.remove(path)
            except Exception as e:
                log.error("%s %s", "Dosya silinemedi:", e)

    def _can_delete_owned_file(self, path):
        if not isinstance(path, str) or not os.path.isfile(path):
            return False
        real = os.path.realpath(path)
        roots = [os.path.realpath(self.paths.cache_dir), os.path.realpath(self.paths.covers_dir)]
        try:
            if not any(os.path.commonpath([root, real]) == root and real != root for root in roots):
                return False
        except ValueError:
            return False
        references = list(self.playlist_covers.values())
        for songs in self.playlists.values():
            for song in songs:
                references.extend((song.get("cached_path"), song.get("local_path")))
        return not any(isinstance(ref, str) and os.path.realpath(ref) == real for ref in references)

    def _cancel_pending_deletion(self, path: str | None):
        if not path:
            return
        timer = self._pending_file_deletions.pop(path, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _schedule_cover_deletion(self, path: str | None):
        self._schedule_file_deletion(path)

    def _cancel_cover_deletion(self, path: str | None):
        self._cancel_pending_deletion(path)

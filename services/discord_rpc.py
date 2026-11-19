# mustiefly_qt/services/discord_rpc.py
from __future__ import annotations

import time
import threading
try:
    from pypresence import Presence
except ImportError:
    Presence = None
from PySide6.QtCore import QObject

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
class DiscordRPCService(QObject):
    def __init__(self, client_id: str, playback: PlaybackEngine, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.playback = playback
        
        self.rpc = None
        self.is_connected = False
        self.current_song = None
        self.is_playing = False
        self.start_time = None
        self._elapsed = 0.0          # duraklatıldığında şarkının geçen süresi (devam edince süre kaymasın)
        self._closed = False
        # rpc.update() Discord'a senkron IPC yapar; GUI thread'inde çağrılınca
        # şarkı değişiminde arayüz takılıyordu. Tek işçi thread + son-değer-kazanır.
        self._presence_lock = threading.Lock()
        self._rpc_lock = threading.Lock()
        self._presence_pending: dict | None = None
        self._presence_worker_running = False

        # Sinyalleri bağlıyoruz
        self.playback.songStarted.connect(self._on_song_started)
        self.playback.playStateChanged.connect(self._on_play_state)
        radio_started = getattr(self.playback, "radioStarted", None)
        if radio_started is not None:
            radio_started.connect(self._on_radio_started)

        # Discord bağlantısını arayüzü dondurmamak için arka planda başlatıyoruz
        if Presence is not None and self.client_id:
            threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        if self._closed or Presence is None or not self.client_id:
            return
        try:
            rpc = Presence(self.client_id)
            rpc.connect()
            with self._rpc_lock:
                if self._closed:
                    try:
                        rpc.close()
                    except Exception:
                        pass
                    return
                self.rpc = rpc
                self.is_connected = True
            log.info("Discord RPC başarıyla bağlandı.")
            if self.current_song is not None:
                self._update_presence()
        except Exception as e:
            log.error("%s %s", "Discord RPC bağlanamadı (Discord kapalı olabilir):", e)
            self.is_connected = False

    def _on_song_started(self, playlist_name, index, song, is_offline):
        self.current_song = song
        self.is_playing = True
        self._elapsed = 0.0
        self.start_time = int(time.time())
        self._update_presence()

    def _on_radio_started(self, station: dict):
        self._on_song_started("", -1, {"title": station.get("name") or "Radyo",
                                        "uploader": station.get("country") or "Canlı Yayın"}, False)

    def _on_play_state(self, playing: bool):
        if playing and not self.is_playing:
            self.start_time = int(time.time() - self._elapsed)       # kaldığı süreden devam
        elif not playing and self.is_playing and self.start_time:
            self._elapsed = max(0.0, time.time() - self.start_time)
        self.is_playing = playing
        if playing and not self.start_time:
            self.start_time = int(time.time())
        self._update_presence()

    def _update_presence(self):
        if not self.is_connected or not self.rpc or not self.current_song:
            return

        raw_title = self.current_song.get("title", "Bilinmeyen Şarkı")
        raw_uploader = self.current_song.get("uploader", "Bilinmeyen Sanatçı")
        title, artist = parse_track_and_artist(raw_title, raw_uploader, self.current_song)

        # Duruma göre metin ayarı
        state_text = f"👤 {artist[:120]}" if self.is_playing else "⏸ Duraklatıldı"   # Discord 128 karakter sınırı
        details_text = f"🎵 {title[:125]}"  # Discord API sınırlarına göre kırpıyoruz

        payload = dict(
            state=state_text,
            details=details_text,
            start=self.start_time if self.is_playing else None,
        )
        thumb = (self.current_song.get("thumbnail") or "").strip()
        if thumb.startswith(("http://", "https://")):
            payload["large_image"] = thumb
            payload["large_text"] = title[:120] if len(title) >= 2 else f"{APP_DISPLAY_NAME} Müzik Çalar"
            payload["small_image"] = "logo"
            payload["small_text"] = f"{APP_DISPLAY_NAME} Müzik Çalar"
        else:
            payload["large_image"] = "logo"
            payload["large_text"] = f"{APP_DISPLAY_NAME} Müzik Çalar"

        with self._presence_lock:
            self._presence_pending = payload
            if self._presence_worker_running:
                return
            self._presence_worker_running = True
        threading.Thread(target=self._presence_worker, daemon=True).start()

    def _presence_worker(self):
        while True:
            with self._presence_lock:
                payload, self._presence_pending = self._presence_pending, None
                if payload is None or self._closed:
                    self._presence_worker_running = False
                    return
            try:
                with self._rpc_lock:
                    if self._closed or not self.is_connected or self.rpc is None:
                        continue
                    self.rpc.update(**payload)
            except Exception as e:
                log.error("%s %s", "Discord RPC güncellenemedi:", e)

    def close(self):
        self._closed = True
        with self._rpc_lock:
            rpc, self.rpc = self.rpc, None
            was_connected = self.is_connected
            self.is_connected = False
            if was_connected and rpc is not None:
                try:
                    rpc.clear()
                    rpc.close()
                except Exception:
                    pass

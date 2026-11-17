"""Şarkı Radyosu & Sonsuz Çalma (Song Radio & Autoplay) Servisi.

- Şarkı Radyosu: Herhangi bir şarkıdan yola çıkarak YouTube Music / YouTube
  üzerinden benzer tarzda parçalardan dinamik bir radyo listesi ("📻 Şarkı Radyosu")
  oluşturur ve anında çalmaya başlar.
- Sonsuz Çalma (Autoplay): Çalma listesi sona erdiğinde müzik durmaz;
  son şarkıya benzer parçalar arka planda önceden hazırlanarak ("♾️ Sonsuz Çalma")
  kesintisiz bir şekilde devam eder.
"""
from __future__ import annotations

import copy
from datetime import datetime
import re
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from mustiefly_qt.helpers.constants import yt_dlp_base_opts
from mustiefly_qt.helpers.logging_setup import get_logger
from mustiefly_qt.helpers.lyrics import clean_track_title, parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore

try:
    from ytmusicapi import YTMusic
except ImportError:
    YTMusic = None

import yt_dlp

log = get_logger(__name__)

RADIO_PLAYLIST_NAME = "📻 Şarkı Radyosu"
AUTOPLAY_PLAYLIST_NAME = "♾️ Sonsuz Çalma"


def extract_video_id(url_or_song: str | dict | None) -> str | None:
    """YouTube URL'sinden veya şarkı sözlüğünden 11 karakterlik video ID'sini çıkarır."""
    if isinstance(url_or_song, dict):
        url = url_or_song.get("webpage_url") or url_or_song.get("url") or ""
    elif isinstance(url_or_song, str):
        url = url_or_song
    else:
        return None

    if not url:
        return None

    # ?v=... veya &v=...
    m = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # youtu.be/... veya /embed/... veya /shorts/...
    m = re.search(r"(?:youtu\.be/|/embed/|/v/|/shorts/)([a-zA-Z0-9_-]{11})", url)
    if m:
        return m.group(1)

    return None


def parse_duration_seconds(length_val: Any) -> int:
    """Metin ("3:34", "1:02:15") veya sayısal süreyi tam saniyeye dönüştürür."""
    if isinstance(length_val, (int, float)):
        return max(0, int(length_val))
    if not isinstance(length_val, str):
        return 0
    s = length_val.strip()
    if not s:
        return 0
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 1:
            return int(parts[0])
    except ValueError:
        return 0
    return 0


def fetch_radio_recommendations(song: dict, limit: int = 25) -> list[dict]:
    """Verilen şarkı için YouTube Music veya yt-dlp üzerinden benzer parça önerilerini çeker."""
    video_id = extract_video_id(song)
    raw_title = song.get("title") or ""
    raw_uploader = song.get("uploader") or ""
    clean_title, clean_artist = parse_track_and_artist(raw_title, raw_uploader, song)

    tracks: list[dict] = []
    seen_urls: set[str] = set()

    seed_url = song.get("webpage_url")
    if seed_url:
        seen_urls.add(seed_url)

    # 1) Birincil yöntem: ytmusicapi watch playlist
    if YTMusic is not None and video_id:
        try:
            ytm = YTMusic()
            watch_res = ytm.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
            raw_tracks = watch_res.get("tracks") or []
            for item in raw_tracks:
                item_vid = item.get("videoId")
                if not item_vid or item_vid == video_id:
                    continue
                item_url = f"https://www.youtube.com/watch?v={item_vid}"
                if item_url in seen_urls:
                    continue
                seen_urls.add(item_url)

                artists_list = item.get("artists") or []
                item_artist = ", ".join(
                    a["name"] for a in artists_list if isinstance(a, dict) and "name" in a
                ) or "Bilinmeyen Sanatçı"
                item_title = item.get("title") or "Bilinmeyen Şarkı"
                t_clean, a_clean = parse_track_and_artist(item_title, item_artist, item)

                thumbs = item.get("thumbnail") or []
                thumb_url = None
                if isinstance(thumbs, list) and thumbs:
                    thumb_url = thumbs[-1].get("url")
                elif isinstance(thumbs, str):
                    thumb_url = thumbs

                duration = parse_duration_seconds(item.get("length"))
                tracks.append({
                    "title": t_clean,
                    "webpage_url": item_url,
                    "duration": duration,
                    "uploader": a_clean,
                    "thumbnail": thumb_url,
                    "liked": False,
                    "added_date": datetime.now().isoformat(),
                })
                if len(tracks) >= limit:
                    break
        except Exception as e:
            log.warning("%s %s", "ytmusicapi get_watch_playlist başarısız, arama yedeğine geçiliyor:", e)

    # 2) İkincil yöntem / Yedeğe düşme: yt-dlp arama (mix / benzer şarkılar)
    if not tracks:
        query = f"{clean_artist} {clean_title} mix" if clean_artist else f"{clean_title} mix"
        try:
            ydl_opts = yt_dlp_base_opts(
                format="bestaudio/best",
                quiet=True,
                noplaylist=True,
                extract_flat="in_playlist",
            )
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit + 5}:{query}", download=False)
            entries = info.get("entries") or [] if info else []
            for e in entries:
                if not e:
                    continue
                e_vid = e.get("id")
                e_url = e.get("webpage_url") or e.get("url") or (
                    f"https://www.youtube.com/watch?v={e_vid}" if e_vid else ""
                )
                if not e_url or e_url in seen_urls or (video_id and e_vid == video_id):
                    continue
                seen_urls.add(e_url)

                t_clean, a_clean = parse_track_and_artist(
                    e.get("title") or "Bilinmeyen Şarkı",
                    e.get("uploader") or e.get("channel") or "",
                    e,
                )
                thumbs = e.get("thumbnails") or []
                thumb_url = (thumbs[-1].get("url") if thumbs else None) or e.get("thumbnail")
                tracks.append({
                    "title": t_clean,
                    "webpage_url": e_url,
                    "duration": int(e.get("duration") or 0),
                    "uploader": a_clean,
                    "thumbnail": thumb_url,
                    "liked": False,
                    "added_date": datetime.now().isoformat(),
                })
                if len(tracks) >= limit:
                    break
        except Exception as e:
            log.error("%s %s", "yt-dlp radyo arama hatası:", e)

    return tracks


class SongRadioService(QObject):
    """Şarkı Radyosu ve Sonsuz Çalma işlemlerini koordine eden servis."""

    radioStarted = Signal(str, dict)       # playlist_name, seed_song
    radioReady = Signal(str, int)          # playlist_name, track_count
    autoplayTriggered = Signal(str, dict)  # playlist_name, first_song

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback

        self._prefetched_seed_key: str | None = None
        self._prefetched_tracks: list[dict] = []
        self._prefetch_lock = threading.Lock()
        self._is_prefetching = False
        self._is_handling_autoplay = False

        # Çalan şarkı değiştikçe, eğer son şarkıysa arka planda sonsuz çalma önerilerini önceden çek
        self.playback.songStarted.connect(self._on_song_started)

        # PlaybackEngine'e autoplay kancasını bağla
        self.playback.autoplay_handler = self.handle_autoplay

    def start_radio_for_song(self, song: dict):
        """Verilen şarkı için anında '📻 Şarkı Radyosu' listesi oluşturur ve başlatır."""
        if not song:
            return

        seed = copy.deepcopy(song)
        # Önce tohum şarkıyı çalma listesinin başına koyarak anında başlat
        self.store.playlists[RADIO_PLAYLIST_NAME] = [seed]
        self.store.playlistsChanged.emit()

        clean_t, clean_a = parse_track_and_artist(seed.get("title", ""), seed.get("uploader", ""), seed)
        self.store.statusMessage.emit(f"📻 '{clean_t}' için Şarkı Radyosu başlatılıyor…", "info")
        self.playback.play_song_at_index(RADIO_PLAYLIST_NAME, 0)
        self.radioStarted.emit(RADIO_PLAYLIST_NAME, seed)

        # Arka planda benzer parçaları çekip listeye ekle
        def worker():
            recommendations = fetch_radio_recommendations(seed, limit=30)
            if not recommendations:
                self.store.statusMessage.emit("⚠️ Şarkı radyosu için benzer parça bulunamadı.", "warning")
                return

            current_list = self.store.playlists.get(RADIO_PLAYLIST_NAME, [])
            existing_urls = {s.get("webpage_url") for s in current_list if s.get("webpage_url")}
            added = 0
            for r in recommendations:
                if r.get("webpage_url") not in existing_urls:
                    current_list.append(r)
                    existing_urls.add(r.get("webpage_url"))
                    added += 1

            self.store.playlists[RADIO_PLAYLIST_NAME] = current_list
            self.store.playlistsChanged.emit()
            self.radioReady.emit(RADIO_PLAYLIST_NAME, len(current_list))
            self.store.statusMessage.emit(
                f"📻 Şarkı Radyosu hazır: {added} benzer parça eklendi.", "success"
            )

        threading.Thread(target=worker, daemon=True, name="SongRadioWorker").start()

    def _on_song_started(self, playlist_name: str, index: int, song: dict, is_offline: bool):
        """Son şarkıya gelindiyse Sonsuz Çalma (Autoplay) önerilerini önceden önbelleğe al."""
        if not self.playback.settings.get("autoplay_enabled", True):
            return
        if self.playback.repeat_mode in ("one", "all"):
            return

        # Sırada başka şarkı yoksa ve manuel kuyruk da boşsa bu son şarkıdır
        if self.playback.get_next_index() == -1 and not self.store.manual_queue:
            song_key = song.get("webpage_url") or song.get("title")
            if song_key and song_key != self._prefetched_seed_key:
                self._prefetch_autoplay(song)

    def _prefetch_autoplay(self, seed_song: dict):
        with self._prefetch_lock:
            if self._is_prefetching:
                return
            self._is_prefetching = True

        def worker():
            try:
                tracks = fetch_radio_recommendations(seed_song, limit=20)
                with self._prefetch_lock:
                    self._prefetched_seed_key = seed_song.get("webpage_url") or seed_song.get("title")
                    self._prefetched_tracks = tracks
            except Exception as e:
                log.warning("%s %s", "Autoplay ön yükleme hatası:", e)
            finally:
                with self._prefetch_lock:
                    self._is_prefetching = False

        threading.Thread(target=worker, daemon=True, name="AutoplayPrefetch").start()

    def handle_autoplay(self) -> bool:
        """Çalma listesi tükendiğinde PlaybackEngine tarafından çağrılır.
        Eğer Sonsuz Çalma açıksa yeni parçalarla kesintisiz devam eder.
        Dönüş: True ise autoplay devreye girdi; False ise normal duruş yapılır.
        """
        if not self.playback.settings.get("autoplay_enabled", True):
            return False
        if self.playback.repeat_mode in ("one", "all"):
            return False

        seed = self.playback.current_song
        if not seed:
            return False

        if self._is_handling_autoplay:
            return False
        self._is_handling_autoplay = True

        with self._prefetch_lock:
            cached_tracks = list(self._prefetched_tracks)
            self._prefetched_tracks = []
            self._prefetched_seed_key = None

        if cached_tracks:
            self._apply_autoplay_tracks(seed, cached_tracks)
            self._is_handling_autoplay = False
            return True

        # Önbellekte henüz yoksa arka planda çekip anında başlat
        self.store.statusMessage.emit("♾️ Çalma listesi tamamlandı; benzer şarkılar aranıyor…", "info")

        def worker():
            try:
                tracks = fetch_radio_recommendations(seed, limit=20)
                if tracks:
                    self._apply_autoplay_tracks(seed, tracks)
                else:
                    self.store.statusMessage.emit("♾️ Benzer şarkı bulunamadı, çalma durduruldu.", "info")
                    self.playback.player.stop()
                    self.playback.playStateChanged.emit(False)
            finally:
                self._is_handling_autoplay = False

        threading.Thread(target=worker, daemon=True, name="AutoplayOnDemand").start()
        return True

    def _apply_autoplay_tracks(self, seed: dict, tracks: list[dict]):
        """Yeni öneri parçalarını '♾️ Sonsuz Çalma' listesine ekler ve oynatmayı başlatır."""
        current_pl = self.playback.playing_playlist

        if current_pl == AUTOPLAY_PLAYLIST_NAME:
            # Zaten Sonsuz Çalma'dayız: sonuna ekle ve sonraki şarkıya geç
            existing_list = self.store.playlists.get(AUTOPLAY_PLAYLIST_NAME, [])
            existing_urls = {s.get("webpage_url") for s in existing_list if s.get("webpage_url")}
            added = 0
            start_index = len(existing_list)
            for t in tracks:
                if t.get("webpage_url") not in existing_urls:
                    existing_list.append(t)
                    existing_urls.add(t.get("webpage_url"))
                    added += 1

            self.store.playlists[AUTOPLAY_PLAYLIST_NAME] = existing_list
            self.store.playlistsChanged.emit()
            if start_index < len(existing_list):
                self.playback.play_song_at_index(AUTOPLAY_PLAYLIST_NAME, start_index, auto=True)
                self.store.statusMessage.emit("♾️ Sonsuz Çalma yeni önerilerle devam ediyor.", "info")
        else:
            # Başka bir listeden Sonsuz Çalma moduna geçiş
            self.store.playlists[AUTOPLAY_PLAYLIST_NAME] = tracks
            self.store.playlistsChanged.emit()
            self.playback.play_song_at_index(AUTOPLAY_PLAYLIST_NAME, 0, auto=True)
            self.autoplayTriggered.emit(AUTOPLAY_PLAYLIST_NAME, tracks[0])
            clean_t, clean_a = parse_track_and_artist(seed.get("title", ""), seed.get("uploader", ""), seed)
            self.store.statusMessage.emit(
                f"♾️ '{clean_t}' bitti; Sonsuz Çalma benzer şarkılarla devam ediyor.", "info"
            )

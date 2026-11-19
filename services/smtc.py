"""
Windows Sistem Medya Denetimleri (SMTC) entegrasyonu.

Klavyedeki medya tuşları + ses açılır penceresinde (ve Windows medya
kaplamalarında) şarkı adı/sanatçı/kapak gösterimi. 'keyboard' paketinden daha
güvenilirdir çünkü işletim sisteminin kendi medya oturumuna bağlanır.

İki opsiyonel paket ailesi desteklenir (hangisi kuruluysa o kullanılır):
- 'winsdk'  : klasik paket (Python 3.9–3.12 için derlenmiş tekerlekleri var)
- 'winrt-*' : yeni pywinrt v3 projeksiyonu (winrt-Windows.Media,
              winrt-Windows.Foundation, winrt-Windows.Storage.Streams,
              winrt-Windows.Media.Interop) — daha yeni Python'larda çalışır

Hiçbiri kurulu değilse her şey sessizce devre dışı kalır (SMTC_AVAILABLE
= False) — ayarlar diyaloğu da bu bayrağı okur.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading

from PySide6.QtCore import QObject, QThread, Signal
from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
_SMTC_GET_FOR_WINDOW = None
try:
    from winsdk.windows.foundation import Uri  # noqa: F401
    from winsdk.windows.media import (
        MediaPlaybackStatus,
        MediaPlaybackType,
        SystemMediaTransportControlsButton,
        SystemMediaTransportControlsTimelineProperties,
    )
    from winsdk.windows.media import SystemMediaTransportControlsInterop
    from winsdk.windows.storage.streams import RandomAccessStreamReference
    _SMTC_GET_FOR_WINDOW = SystemMediaTransportControlsInterop.get_for_window
    SMTC_AVAILABLE = True
except ImportError:
    try:
        from winrt.windows.foundation import Uri  # noqa: F401
        from winrt.windows.media import (
            MediaPlaybackStatus,
            MediaPlaybackType,
            SystemMediaTransportControlsButton,
            SystemMediaTransportControlsTimelineProperties,
        )
        from winrt.windows.media.interop import get_for_window
        from winrt.windows.storage.streams import RandomAccessStreamReference
        _SMTC_GET_FOR_WINDOW = get_for_window
        SMTC_AVAILABLE = True
    except Exception:
        SMTC_AVAILABLE = False
except Exception:
    SMTC_AVAILABLE = False

_BUTTON_MAP = {}
if SMTC_AVAILABLE:
    _BUTTON_MAP = {
        SystemMediaTransportControlsButton.PLAY: "play",
        SystemMediaTransportControlsButton.PAUSE: "pause",
        SystemMediaTransportControlsButton.NEXT: "next",
        SystemMediaTransportControlsButton.PREVIOUS: "previous",
        SystemMediaTransportControlsButton.STOP: "stop",
    }

_COVER_DIR = os.path.join(tempfile.gettempdir(), "mustiefly-smtc-covers")


class SMTCService(QObject):
    """Pencere tutamacına bağlı SMTC oturumu. ButtonPressed olayları WinRT
    thread'inden gelir; Qt Signal emit etmek güvenlidir (queued connection ile
    GUI thread'ine düşer)."""
    buttonPressed = Signal(str)  # "play" | "pause" | "next" | "previous" | "stop"
    _coverReady = Signal(int, str, str, str, str)  # gen, key, yol, başlık, sanatçı

    def __init__(self, parent=None):
        super().__init__(parent)
        self._coverReady.connect(self._apply_cover)
        self._smtc = None
        self._event_token = None
        self._last_cover_key = None
        self._cover_path = None
        self._duration_ms = 0
        self._position_ms = 0
        self._meta_gen = 0

    # --- Yaşam döngüsü ---
    def start(self, hwnd: int):
        if not SMTC_AVAILABLE or _SMTC_GET_FOR_WINDOW is None:
            return
        if self._smtc is not None:
            return  # zaten kurulu
        try:
            self._smtc = _SMTC_GET_FOR_WINDOW(hwnd)
            self._smtc.is_play_enabled = True
            self._smtc.is_pause_enabled = True
            self._smtc.is_next_enabled = True
            self._smtc.is_previous_enabled = True
            self._smtc.playback_status = MediaPlaybackStatus.STOPPED
            self._event_token = self._smtc.add_button_pressed(self._on_button_pressed)
        except Exception as e:
            log.error("%s %s", "SMTC başlatılamadı:", e)
            self._smtc = None

    def stop(self):
        if self._smtc is None:
            return
        try:
            if self._event_token is not None:
                self._smtc.remove_button_pressed(self._event_token)
            self._smtc.playback_status = MediaPlaybackStatus.STOPPED
            try:
                updater = self._smtc.display_updater
                updater.clear_all()
                updater.update()
            except Exception:
                pass
        except Exception:
            pass
        self._smtc = None
        self._event_token = None

    # --- Olay köprüsü ---
    def _on_button_pressed(self, sender, args):
        name = _BUTTON_MAP.get(args.button)
        if name:
            self.buttonPressed.emit(name)

    # --- Durum / meta güncellemeleri (GUI thread'inden çağrılır) ---
    def update_status(self, playing: bool):
        if self._smtc is None:
            return
        try:
            status = MediaPlaybackStatus.PLAYING if playing else MediaPlaybackStatus.PAUSED
            self._smtc.playback_status = status
        except Exception:
            pass

    def set_stopped(self):
        if self._smtc is None:
            return
        try:
            self._smtc.playback_status = MediaPlaybackStatus.STOPPED
        except Exception:
            pass

    def update_metadata(self, title: str, artist: str,
                        thumb_url: str | None = None, thumb_pil=None):
        """Şarkı bilgisini yazar. Kapak arka planda hazırlanıp eklenir."""
        if self._smtc is None:
            return
        self._meta_gen += 1
        gen = self._meta_gen
        self._set_text(title, artist)
        if thumb_pil is not None or thumb_url:
            pil_copy = thumb_pil.copy() if thumb_pil is not None else None
            threading.Thread(
                target=self._prepare_cover_and_update,
                args=(gen, title, artist, thumb_url, pil_copy),
                daemon=True).start()

    def _set_text(self, title: str, artist: str):
        try:
            updater = self._smtc.display_updater
            updater.type = MediaPlaybackType.MUSIC
            props = updater.music_properties
            props.title = (title or "Bilinmeyen Şarkı")[:120]
            props.artist = (artist or "")[:120]
            props.album_title = APP_DISPLAY_NAME
            updater.update()
        except Exception as e:
            log.error("%s %s", "SMTC meta yazılamadı:", e)

    def _prepare_cover_and_update(self, gen, title, artist, thumb_url, pil_img):
        """Arka plan thread'i: kapak görselini diske yazıp SMTC'ye ekler."""
        if pil_img is not None:
            try:
                key = "pil:" + hashlib.md5(
                    (thumb_url or title or "?").encode("utf-8")).hexdigest()
                os.makedirs(_COVER_DIR, exist_ok=True)
                path = os.path.join(_COVER_DIR,
                                    hashlib.md5(key.encode()).hexdigest() + ".jpg")
                img = pil_img.convert("RGB")
                w, h = img.size
                side = min(w, h)
                img = img.crop(((w - side) // 2, (h - side) // 2,
                                (w - side) // 2 + side, (h - side) // 2 + side))
                fd, tmp_path = tempfile.mkstemp(prefix=".smtc-", suffix=".jpg", dir=_COVER_DIR)
                os.close(fd)
                try:
                    img.save(tmp_path, "JPEG", quality=90)
                    os.replace(tmp_path, path)
                except Exception:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    raise
                try:
                    self._coverReady.emit(gen, key, path, title, artist)
                except RuntimeError:
                    pass
                return
            except Exception as e:
                log.error("%s %s", "SMTC kapak yazılamadı:", e)

        if not thumb_url:
            return
        key = "url:" + hashlib.md5(thumb_url.encode("utf-8")).hexdigest()
        cached = os.path.join(_COVER_DIR, hashlib.md5(key.encode()).hexdigest() + ".jpg")
        if not os.path.exists(cached):
            try:
                import requests
                resp = requests.get(thumb_url, timeout=8)
                resp.raise_for_status()
                os.makedirs(_COVER_DIR, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(prefix=".smtc-", suffix=".jpg", dir=_COVER_DIR)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(resp.content)
                    os.replace(tmp_path, cached)
                except Exception:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    raise
            except Exception as e:
                log.error("%s %s", "SMTC kapak indirilemedi:", e)
                return
        try:
            self._coverReady.emit(gen, key, cached, title, artist)
        except RuntimeError:
            pass

    def _apply_cover(self, gen: int, key: str, cover_path: str, title: str, artist: str):
        if QThread.currentThread() != self.thread():
            log.warning("SMTC kapak güncellemesi GUI thread'i dışında çağrıldı.")
            return
        if gen != self._meta_gen:
            return
        if self._smtc is None or not os.path.exists(cover_path):
            return
        self._last_cover_key = key
        self._cover_path = cover_path
        try:
            ref = RandomAccessStreamReference.create_from_uri(
                Uri(_file_uri(cover_path)))
            updater = self._smtc.display_updater
            updater.type = MediaPlaybackType.MUSIC
            updater.thumbnail = ref
            props = updater.music_properties
            props.title = (title or "Bilinmeyen Şarkı")[:120]
            props.artist = (artist or "")[:120]
            props.album_title = APP_DISPLAY_NAME
            updater.update()
        except Exception as e:
            log.error("%s %s", "SMTC kapak uygulanamadı:", e)

    def update_position(self, pos_ms: int, duration_ms: int):
        self._position_ms = pos_ms
        self._duration_ms = duration_ms
        if self._smtc is None:
            return
        try:
            from datetime import timedelta
            tl = SystemMediaTransportControlsTimelineProperties()
            tl.position = timedelta(milliseconds=max(0, pos_ms))
            tl.start_time = timedelta(0)
            tl.end_time = timedelta(milliseconds=max(0, duration_ms))
            tl.min_seek_time = timedelta(0)
            tl.max_seek_time = timedelta(milliseconds=max(0, duration_ms))
            self._smtc.update_timeline_properties(tl)
        except Exception:
            pass


def _file_uri(path: str) -> str:
    """Windows dosya yolunu file:/// URI'ye çevirir."""
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    from urllib.parse import quote
    return "file://" + quote(p)

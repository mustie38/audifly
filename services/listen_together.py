"""Birlikte Dinle: oda koduyla arkadaşlarla eşzamanlı müzik dinleme.

Ses aktarılmaz. Röle sunucusu (relay_server/server.py) yalnızca küçük JSON
mesajları iletir: hangi şarkı, çalıyor mu, kaçıncı saniye. Her kişi şarkıyı
kendi bilgisayarında (YouTube üzerinden) çalar.

Kurallar:
- Odadaki herkes şarkı seçebilir, duraklatabilir, sarabilir.
- Her gönderenin seq sayacı ayrı izlenir; aynı gönderenden eski mesajlar yoksayılır.
- Şarkı bitince sıradakini yalnızca ODA SAHİBİ (ilk giren) seçer; diğerleri bekler.
- Oda sahibi çalarken birkaç saniyede bir konumunu yayınlar; sapma büyükse
  diğerleri kendini düzeltir.
- Yerel dosyalar (local://) paylaşılamaz; yalnızca http(s) bağlantılı şarkılar.
- Sohbet, emoji tepkileri ve ortak sıra (herkes ekler; sıradaki şarkı önce buradan çalınır).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from mustiefly_qt.helpers.logging_setup import get_logger

log = get_logger(__name__)

PROTOCOL_VERSION = 2
MAX_SEQ = 2**31 - 1
PENDING_TIMEOUT_MS = 20_000
SHARED_PLAYLIST = "🎧 Birlikte Dinle"
# Sunucu adresini bir kez buraya yaz (örn. "wss://adin.onrender.com"); arkadaşların
# uygulamayı alınca sunucu adresi girmeden yalnızca oda kodu yazar.
DEFAULT_SERVER_URL = ""

# Uzaktan paylaşılmasına izin verilen güvenli müzik alan adları (yalnızca HTTPS)
ALLOWED_SHARE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
})
ALLOWED_THUMBNAIL_HOSTS = frozenset({
    "i.ytimg.com",
    "i9.ytimg.com",
    "img.youtube.com",
    "lh3.googleusercontent.com",
    "yt3.ggpht.com",
})

HEARTBEAT_MS = 8000
PING_MS = 5000
DRIFT_MS = 1500          # oda sahibinin periyodik konumuna göre tolerans
SYNC_TOL_MS = 600        # "Eşitle" ile istenen anlık düzeltmede tolerans
SEEK_TOL_MS = 1000       # açık sarma/duraklatma mesajlarında tolerans
CONNECT_TIMEOUT_MS = 12000
# Son beklemeleri 15 sn'den 8 sn'ye indir; en kötü bütçe yaklaşık 3 dk.
RECONNECT_DELAYS_S = (2, 3, 5, 8, 10, 8, 8, 8, 8)
RECONNECT_TOTAL_TIMEOUT_S = (
    sum(RECONNECT_DELAYS_S) + (len(RECONNECT_DELAYS_S) + 1) * CONNECT_TIMEOUT_MS // 1000
)
SLOW_CONNECT_NOTICE_S = 4
EMOJIS = ("❤️", "🔥", "👏", "😂", "😍", "🎉", "👍", "😭")
MAX_CHAT_CHARS = 200
CHAT_HISTORY = 100
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # karışan harfler (I, O, 0, 1) yok


# --- Saf yardımcılar (kolay test) ---
def generate_room_code(length: int = 6) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def normalize_room_code(raw: str) -> str:
    code = "".join(ch for ch in str(raw or "").upper() if ch.isalnum())
    return code if 4 <= len(code) <= 12 else ""


def is_valid_seq(value) -> bool:
    """Sequence değeri 1..MAX_SEQ aralığında gerçek bir int olmalı (bool/float/negatif reddedilir)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_SEQ


def _is_loopback_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_valid_hostname(host: str) -> bool:
    if not host or len(host) > 253 or any(ord(c) <= 32 for c in host):
        return False
    if _is_loopback_host(host):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_unspecified or ip.is_multicast)
    except ValueError:
        pass
    if "." not in host or host.startswith(".") or host.endswith(".") or ".." in host:
        return False
    labels = host.split(".")
    return all(
        1 <= len(lbl) <= 63
        and all(ch.isalnum() or ch == "-" for ch in lbl)
        and not lbl.startswith("-")
        and not lbl.endswith("-")
        for lbl in labels
    )


def normalize_server_url(raw: str) -> str:
    """Sunucu adresini doğrular ve güvenli WebSocket URL'sine ('wss://' veya yerel 'ws://') çevirir.

    Güvenlik kuralları:
    - Uzak sunucularda yalnızca 'wss://' (veya 'https://') kabul edilir.
    - 'ws://' ve 'http://' yalnızca localhost / 127.0.0.1 / ::1 için kabul edilir.
    - Kimlik bilgisi (user:pass@), sorgu/fragment veya geçersiz port içeren adresler reddedilir.
    """
    url = str(raw or "").strip()
    if not url or any(ord(c) <= 32 for c in url):
        return ""
    if "://" not in url:
        if url.startswith("/") or "@" in url:
            return ""
        url = "wss://" + url
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return ""
    scheme = (parts.scheme or "").lower()
    if scheme not in ("wss", "https", "ws", "http"):
        return ""
    if parts.username is not None or parts.password is not None or "@" in (parts.netloc or ""):
        return ""
    if parts.query or parts.fragment:
        return ""
    if port is not None and not (1 <= port <= 65535):
        return ""
    host = (parts.hostname or "").lower()
    if not _is_valid_hostname(host):
        return ""
    if scheme in ("ws", "http"):
        if not _is_loopback_host(host):
            return ""
        out_scheme = "ws"
    else:
        out_scheme = "wss"
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = (parts.path or "").rstrip("/")
    if ".." in path:
        return ""
    return f"{out_scheme}://{netloc}{path}"


def _safe_ms(value) -> int:
    return max(0, min(int(value), 5000)) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def hash_password(room: str, password: str) -> str:
    """Düz şifre sunucuya gitmez; oda koduyla tuzlanmış SHA-256 özeti gider."""
    password = (password or "").strip()
    if not password:
        return ""
    return hashlib.sha256(f"audifly:{room}:{password}".encode("utf-8")).hexdigest()


def build_invite(room: str, server_url: str) -> str:
    """Arkadaşa gönderilecek tek parça davet: KOD@sunucu (şifre varsa ayrıca söylenir)."""
    host = normalize_server_url(server_url)
    if host.startswith("wss://"):
        host = host[len("wss://"):]
    return f"{room}@{host}" if host else room


def parse_invite(text: str) -> tuple[str, str]:
    """'KOD@sunucu' ya da yalnız 'KOD' -> (kod, sunucu_url_veya_boş)."""
    text = str(text or "").strip()
    if text.count("@") > 1:
        return "", ""
    if "@" in text:
        code, server = text.rsplit("@", 1)
        norm_code = normalize_room_code(code)
        norm_srv = normalize_server_url(server) if server else ""
        if server and not norm_srv:
            return "", ""
        return norm_code, norm_srv
    return normalize_room_code(text), ""


def is_valid_share_url(url) -> bool:
    """Birlikte Dinle üzerinden paylaşılabilecek müzik bağlantısını doğrular.

    Yalnızca HTTPS şemalı, kimlik bilgisi/beklenmeyen port içermeyen, izin verilen
    YouTube / YouTube Music alan adlarına ait geçerli parça adresleri kabul edilir.
    """
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not (1 <= len(url) <= 300) or any(ord(c) <= 32 for c in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if (parts.scheme or "").lower() != "https":
        return False
    if parts.username is not None or parts.password is not None or "@" in (parts.netloc or ""):
        return False
    if port not in (None, 443):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_SHARE_HOSTS:
        return False
    path = parts.path or ""
    if not path or path == "/" or ".." in path or "\\" in path:
        return False
    if host == "youtu.be":
        vid = path.lstrip("/").split("/", 1)[0]
        return bool(vid) and all(ch.isalnum() or ch in "-_" for ch in vid)
    if path == "/watch":
        qs = parse_qs(parts.query)
        v = (qs.get("v") or [""])[0]
        return bool(v) and all(ch.isalnum() or ch in "-_" for ch in v)
    if path.startswith(("/shorts/", "/live/", "/embed/")):
        seg = path.split("/", 2)[2].split("/", 1)[0] if path.count("/") >= 2 else ""
        return bool(seg) and all(ch.isalnum() or ch in "-_" for ch in seg)
    if path == "/playlist":
        qs = parse_qs(parts.query)
        plist = (qs.get("list") or [""])[0]
        return bool(plist) and all(ch.isalnum() or ch in "-_" for ch in plist)
    return False


def is_valid_thumbnail_url(url) -> bool:
    if not isinstance(url, str) or not (1 <= len(url) <= 400) or any(ord(c) <= 32 for c in url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if (parts.scheme or "").lower() != "https":
        return False
    if parts.username is not None or parts.password is not None or "@" in (parts.netloc or ""):
        return False
    if port not in (None, 443):
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    return host in ALLOWED_THUMBNAIL_HOSTS and ".." not in (parts.path or "")


def is_shareable(song) -> bool:
    return (
        isinstance(song, dict)
        and not song.get("local_path")
        and is_valid_share_url(song.get("webpage_url", ""))
    )


def song_payload(song: dict) -> dict:
    out = {k: song.get(k) for k in ("title", "uploader", "webpage_url")
           if isinstance(song.get(k), str)}
    thumb = song.get("thumbnail")
    if isinstance(thumb, str) and is_valid_thumbnail_url(thumb):
        out["thumbnail"] = thumb
    duration = song.get("duration")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        out["duration"] = int(duration)
    return out


def _default_socket_factory():
    from PySide6.QtWebSockets import QWebSocket
    return QWebSocket()


class ListenTogether(QObject):
    stateChanged = Signal(str)            # "disconnected" | "connecting" | "connected"
    membersChanged = Signal(list, str)    # [{id, name}], oda sahibi id
    notice = Signal(str, str)             # mesaj, seviye (arayüz durum çubuğu)
    chatReceived = Signal(str, str, bool) # gönderen adı, metin, benim mesajım mı
    emojiReceived = Signal(str, str)      # gönderen adı, emoji
    queueChanged = Signal()               # ortak sıra değişti
    latencyChanged = Signal(int)          # tek yön gecikme tahmini (ms)
    connectProgress = Signal(int, bool)   # deneme sayısı, sunucu uyanıyor olabilir mi

    def __init__(self, store, playback, parent=None, socket_factory=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self._socket_factory = socket_factory or _default_socket_factory
        self._ws = None
        self._url = ""
        self.room = ""
        self.name = ""
        self.my_id = ""
        self.host_id = ""
        self.members: list[dict] = []
        self.state = "disconnected"

        self._wanted = False
        self._create_mode = False
        self._retry = 0
        self._seq = 0
        self._last_by_sender: dict[str, int] = {}
        self._suppress_until = 0.0           # uzaktan uygulanan değişiklikleri geri yayınlama
        self._pending: dict | None = None    # çözülmekte olan uzak şarkı
        self._pending_gen = 0
        self._last_sent = ("", "", 0.0)      # (tür, url, zaman)
        self._warned_local = False
        self.room_queue: list[dict] = []
        self.password = ""
        self.locked = False
        self.latency_ms = 0
        self._ping_sent: dict[int, float] = {}
        self._nam = None
        self.chat_log: list[tuple[str, str, bool]] = []

        self._hb = QTimer(self)
        self._hb.setInterval(HEARTBEAT_MS)
        self._hb.timeout.connect(self._heartbeat)
        self._reconnect = QTimer(self)
        self._reconnect.setSingleShot(True)
        self._reconnect.timeout.connect(self._open_socket)
        self._ping = QTimer(self)
        self._ping.setInterval(PING_MS)
        self._ping.timeout.connect(self._send_ping)
        self._watchdog = QTimer(self)             # bağlantı kurulamıyorsa soketi yeniden aç
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._connect_timeout)
        self._slow = QTimer(self)                 # "sunucu uyanıyor" bilgisi için
        self._slow.setSingleShot(True)
        self._slow.timeout.connect(lambda: self.connectProgress.emit(self._retry + 1, True))
        self._pending_timer = QTimer(self)        # uzak şarkı yükleme zaman aşımı (20 sn)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._on_pending_timeout)

        playback.songStarted.connect(self._on_song_started)
        playback.playStateChanged.connect(self._on_play_state)
        playback.seeked.connect(self._on_seeked)
        if hasattr(playback, "playError"):
            playback.playError.connect(self._on_play_error)
        playback.next_provider = self._next_from_room_queue
        playback.crossfade_guard = self._blocks_crossfade

    # --- Genel arayüz ---
    @property
    def joined(self) -> bool:
        return self.state == "connected"

    @property
    def is_host(self) -> bool:
        return bool(self.my_id) and self.my_id == self.host_id

    def create_room(self, server_url: str, room: str = "", name: str = "", password: str = "") -> bool:
        """Yeni bir oda oluşturur (oda kodu verilmezse otomatik üretir)."""
        code = room.strip() if room and room.strip() else generate_room_code()
        return self.join(server_url, code, name, password, create=True)

    def join(self, server_url: str, room: str, name: str, password: str = "",
             *, create: bool = False) -> bool:
        raw_room = str(room or "").strip()
        raw_srv = str(server_url or "").strip()
        if raw_room.count("@") > 1:
            self.notice.emit("Oda kodu 4-12 harf/rakam olmalı.", "warning")
            return False
        invite_code, invite_url = parse_invite(raw_room)
        if "@" in raw_room and not invite_url:
            self.notice.emit(
                "Güvensiz veya geçersiz sunucu adresi. Uzak sunucularda yalnızca https:// veya wss:// kullanılabilir.",
                "error",
            )
            return False
        norm_srv = normalize_server_url(raw_srv)
        if raw_srv and not norm_srv and not invite_url:
            if raw_srv.lower().startswith(("http://", "ws://")):
                self.notice.emit(
                    "Güvensiz sunucu bağlantısı (http/ws) yalnızca yerel geliştirmede (localhost) kullanılabilir; "
                    "uzak sunucu için https:// veya wss:// kullan.",
                    "error",
                )
            else:
                self.notice.emit("Sunucu adresi geçersiz.", "error")
            return False
        url = invite_url or norm_srv or normalize_server_url(DEFAULT_SERVER_URL)
        code = invite_code
        if not url:
            self.notice.emit("Sunucu adresi girilmedi.", "warning")
            return False
        if not code:
            self.notice.emit("Oda kodu 4-12 harf/rakam olmalı.", "warning")
            return False
        self.leave(silent=True)
        self._url, self.room = url, code
        self.password = (password or "").strip()
        self.name = (name or "").strip()[:24] or "Misafir"
        self._create_mode = bool(create)
        self._wanted, self._retry = True, 0
        self._last_by_sender.clear()
        self._seq = 0
        self._set_state("connecting")
        self._open_socket()
        return True

    def leave(self, silent: bool = False):
        was_active = self._wanted or self.state != "disconnected"
        self._wanted = False
        self._create_mode = False
        for t in (self._hb, self._reconnect, self._ping, self._watchdog, self._slow, self._pending_timer):
            t.stop()
        self._pending_gen += 1
        self._pending = None
        self._ping_sent.clear()
        self.latency_ms = 0
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
                ws.deleteLater()
            except Exception as e:   # kapanış hatası uygulamayı etkilemesin
                log.warning("Soket kapatılamadı: %s", e)
        self.members, self.host_id, self.my_id = [], "", ""
        self.playback.suppress_auto_advance = False
        self.room_queue, self.chat_log = [], []
        self._set_state("disconnected")
        self.membersChanged.emit([], "")
        self.queueChanged.emit()
        if was_active and not silent:
            self.notice.emit("Odadan ayrıldın.", "info")

    def shutdown(self):
        self.leave(silent=True)

    # --- Gecikme ölçümü / eşitleme / yetki ---
    def _send_ping(self):
        if not self.joined:
            return
        stamp = int(time.monotonic() * 1000)
        self._ping_sent[stamp] = time.monotonic()
        if len(self._ping_sent) > 8:
            self._ping_sent.pop(next(iter(self._ping_sent)))
        self._send({"t": "ping", "c": stamp})

    def _on_pong(self, stamp):
        sent = self._ping_sent.pop(stamp, None) if isinstance(stamp, int) else None
        if sent is None:
            return
        one_way = int((time.monotonic() - sent) * 500)       # RTT / 2, ms
        self.latency_ms = one_way if self.latency_ms == 0 else int(self.latency_ms * 0.7 + one_way * 0.3)
        self.latencyChanged.emit(self.latency_ms)

    def request_sync(self):
        """Oda sahibinden anlık konumunu iste ve ona göre düzel."""
        if self.joined and not self.is_host:
            self._send({"t": "sync_req"})

    def transfer_host(self, member_id: str):
        if self.joined and self.is_host and member_id != self.my_id:
            self._send({"t": "transfer", "to": member_id})

    def wake_server(self, server_url: str = ""):
        """Ücretsiz sunucu uyuyorsa HTTP isteğiyle önceden uyandır (yanıt beklenmez)."""
        url = normalize_server_url(server_url or self._url or DEFAULT_SERVER_URL)
        if not url:
            return
        http = ("https://" if url.startswith("wss://") else "http://") + url.split("://", 1)[1]
        try:
            from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
            if self._nam is None:
                self._nam = QNetworkAccessManager(self)
            reply = self._nam.get(QNetworkRequest(QUrl(http.rstrip("/") + "/health")))
            reply.finished.connect(reply.deleteLater)
        except Exception as e:
            log.warning("Sunucu uyandırma isteği gönderilemedi: %s", e)

    # --- Sohbet / emoji ---
    def send_chat(self, text: str) -> bool:
        text = " ".join(str(text or "").split())[:MAX_CHAT_CHARS]
        if not self.joined or not text:
            return False
        self._send({"t": "chat", "text": text})
        self._on_chat(self.name, text, mine=True)
        return True

    def send_emoji(self, emoji: str) -> bool:
        if not self.joined or emoji not in EMOJIS:
            return False
        self._send({"t": "emoji", "e": emoji})
        self.emojiReceived.emit(self.name, emoji)
        return True

    def _on_chat(self, name: str, text: str, mine: bool):
        if not text:
            return
        self.chat_log.append((name, text, mine))
        del self.chat_log[:-CHAT_HISTORY]
        self.chatReceived.emit(name, text, mine)

    # --- Ortak sıra ---
    def add_to_room_queue(self, song: dict) -> bool:
        if not self.joined:
            self.notice.emit("Önce bir odaya katılmalısın.", "warning")
            return False
        if not is_shareable(song):
            self.notice.emit("Yerel ses dosyaları odayla paylaşılamaz.", "warning")
            return False
        self._send({"t": "queue_add", "song": song_payload(song)})
        return True

    def remove_from_room_queue(self, url: str):
        if self.joined:
            self._send({"t": "queue_remove", "url": url})

    def _set_queue(self, items, announce: bool = True):
        if not isinstance(items, list):
            return
        clean = [dict(i) for i in items if isinstance(i, dict) and is_shareable(i)]
        if announce and len(clean) > len(self.room_queue):
            last = clean[-1]
            if last.get("by") and last["by"] != self.name:
                self.notice.emit(f"➕ {last['by']} kuyruğa ekledi: {last.get('title', '?')}", "info")
        self.room_queue = clean
        self.queueChanged.emit()

    def _ensure_song(self, song: dict):
        url = song["webpage_url"]
        loc = self._find_song(url)
        if loc is None:
            self.store.add_song(SHARED_PLAYLIST, song_payload(song))
            loc = self._find_song(url)
        return loc

    def _blocks_crossfade(self) -> bool:
        """Odadayken crossfade yalnız oda sahibinde ve ortak sıra boşken çalışabilir:
        aksi halde sıradaki şarkıyı odanın değil bu bilgisayarın listesi belirlerdi."""
        return self.joined and (not self.is_host or bool(self.room_queue))

    def _next_from_room_queue(self):
        """PlaybackEngine.play_next için: ortak sıranın başındaki şarkıyı verir."""
        while self.joined and self.room_queue:
            song = self.room_queue.pop(0)
            self._send({"t": "queue_pop", "url": song["webpage_url"]})
            self.queueChanged.emit()
            loc = self._ensure_song(song)
            if loc is not None:
                return loc
        return None

    # --- Soket ---
    def _set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)

    def _open_socket(self):
        if not self._wanted:
            return
        old, self._ws = self._ws, None
        if old is not None:
            try:
                old.deleteLater()
            except Exception:
                pass
        ws = self._socket_factory()
        ws.connected.connect(self._on_ws_connected)
        ws.disconnected.connect(self._connection_lost)
        ws.errorOccurred.connect(self._on_ws_error)
        ws.textMessageReceived.connect(self._on_text)
        self._ws = ws
        self._watchdog.start(CONNECT_TIMEOUT_MS)
        self._slow.start(SLOW_CONNECT_NOTICE_S * 1000)
        ws.open(QUrl(self._url))

    def _on_ws_connected(self):
        action = "create" if self._create_mode else "join"
        self._send({"t": action, "v": PROTOCOL_VERSION, "room": self.room, "name": self.name,
                    "pw": hash_password(self.room, self.password)})

    def _connect_timeout(self):
        """12 sn içinde 'joined' gelmediyse soketi bırakıp yeniden dene."""
        if self._wanted and not self.joined:
            ws, self._ws = self._ws, None
            if ws is not None:
                try:
                    ws.abort() if hasattr(ws, "abort") else ws.close()
                except Exception:
                    pass
            self._connection_lost()

    def _on_ws_error(self, *_args):
        err = ""
        try:
            err = self._ws.errorString()
        except Exception:
            pass
        log.warning("Birlikte Dinle bağlantı hatası: %s", err)
        self._connection_lost()

    def _connection_lost(self, *_args):
        if not self._wanted or self._reconnect.isActive():
            return
        for t in (self._hb, self._ping, self._watchdog, self._pending_timer):
            t.stop()
        self._pending_gen += 1
        self._pending = None
        self.playback.suppress_auto_advance = False
        self._set_state("connecting")
        if self._retry >= len(RECONNECT_DELAYS_S):
            self.notice.emit("Sunucuya bağlanılamadı. Adresi kontrol edip tekrar dene.", "error")
            self.leave(silent=True)
            return
        delay = RECONNECT_DELAYS_S[self._retry]
        self._retry += 1
        self.connectProgress.emit(self._retry, self._retry >= 2)
        if self._retry == 2:
            self.notice.emit("Sunucu uyanıyor olabilir (ücretsiz sunucu ~1 dk sürebilir). "
                             "Bekleniyor…", "info")
        self._reconnect.start(delay * 1000)

    def _send(self, msg: dict):
        if self._ws is not None:
            self._ws.sendTextMessage(json.dumps(msg, ensure_ascii=False))

    def _on_text(self, raw: str):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("t")
        if kind == "joined":
            self._on_joined(msg)
        elif kind == "members":
            self._set_members(msg.get("members"), msg.get("host", ""))
        elif kind == "state":
            if self.joined:
                self._receive_state(msg)
        elif kind == "pong":
            self._on_pong(msg.get("c"))
        elif kind == "sync_req" and self.joined and self.is_host:
            if self._is_playing() and self._pending is None:
                self._broadcast(True, self._player_time(), kind="hb", hb=True, sync=True)
        elif kind == "chat" and self.joined:
            self._on_chat(str(msg.get("name", "?")), str(msg.get("text", "")), mine=False)
        elif kind == "emoji" and self.joined:
            name, emoji = str(msg.get("name", "?")), str(msg.get("e", ""))
            if emoji in EMOJIS:
                self.emojiReceived.emit(name, emoji)
        elif kind == "queue" and self.joined:
            self._set_queue(msg.get("items"))
        elif kind == "error":
            err_code = str(msg.get("code", "")).strip().lower()
            error_message = str(msg.get("msg", "hata"))
            normalized_error = error_message.casefold()
            if err_code == "wrong_password" or "oda şifresi yanlış" in normalized_error:
                self.leave(silent=True)
                self.notice.emit(
                    "Oda şifresi yanlış. Şifreyi kontrol edip tekrar dene "
                    "(sunucu yeniden başlamışsa oda başka bir şifreyle kurulmuş olabilir).",
                    "error")
            elif err_code == "room_not_found" or "oda bulunamadı" in normalized_error:
                self.leave(silent=True)
                self.notice.emit(
                    "Sunucu yeniden başlamış olabilir; oda artık mevcut değil. "
                    "Yeni oda oluştur ya da kodu tekrar kontrol et.",
                    "error")
            elif err_code == "room_exists" or "zaten kullanımda" in normalized_error:
                self.leave(silent=True)
                self.notice.emit(
                    "Bu oda kodu zaten kullanımda. Yeni bir oda aç ya da mevcut odaya katıl.",
                    "error")
            elif err_code == "version_mismatch" or "uyumsuz" in normalized_error:
                self.leave(silent=True)
                self.notice.emit(
                    "Uygulama sürümü sunucuyla uyumsuz. Lütfen Audifly'ı son sürüme güncelle.",
                    "error")
            else:
                self.notice.emit(f"Birlikte Dinle: {error_message}", "error")
                self.leave(silent=True)

    def _on_joined(self, msg: dict):
        self._create_mode = False
        self._last_by_sender.clear()
        self._seq = 0
        self.my_id = str(msg.get("id", ""))
        self._retry = 0
        self._watchdog.stop()
        self._slow.stop()
        self.locked = bool(msg.get("locked"))
        self._set_state("connected")
        self._set_members(msg.get("members"), msg.get("host", ""), announce=False)
        self._hb.start()
        self._ping.start()
        self._send_ping()
        self.notice.emit(f"👥 Odaya bağlandın: {self.room}", "success")
        self._set_queue(msg.get("queue"), announce=False)
        state = msg.get("state")
        if isinstance(state, dict):
            self._receive_state(state, force=True)

    def _set_members(self, members, host, announce: bool = True):
        if not isinstance(members, list):
            return
        members = [{"id": str(m.get("id", "")), "name": str(m.get("name", "?"))}
                   for m in members if isinstance(m, dict)]
        if announce:
            before = {m["id"]: m["name"] for m in self.members}
            after = {m["id"]: m["name"] for m in members}
            for mid, name in after.items():
                if mid not in before and mid != self.my_id:
                    self.notice.emit(f"👋 {name} odaya katıldı.", "info")
            for mid, name in before.items():
                if mid not in after:
                    self.notice.emit(f"{name} odadan ayrıldı.", "info")
        self.members, self.host_id = members, str(host or "")
        # Sıradaki şarkıyı yalnız oda sahibi seçer; diğerleri onun mesajını bekler.
        self.playback.suppress_auto_advance = self.joined and not self.is_host
        self.membersChanged.emit(self.members, self.host_id)

    # --- Yerel olaylar → odaya yayın ---
    def _suppress(self, seconds: float):
        self._suppress_until = max(self._suppress_until, time.monotonic() + seconds)

    def _quiet(self) -> bool:
        return (not self.joined or self._pending is not None
                or time.monotonic() < self._suppress_until)

    def _current_song(self):
        return getattr(self.playback, "_current_song_ref", None)

    def _player_time(self) -> int:
        try:
            return max(0, int(self.playback.player.get_time()))
        except Exception:
            return 0

    def _is_playing(self) -> bool:
        try:
            return bool(self.playback.player.is_playing())
        except Exception:
            return False

    def _on_song_started(self, _pl, _idx, song, _offline):
        url = song.get("webpage_url") if isinstance(song, dict) else None
        pending = self._pending
        if pending is not None:
            if url == pending["url"]:
                self._finish_pending(pending)
                return
            started_at = pending.get("started_at", pending.get("at", 0.0))
            if time.monotonic() - started_at < PENDING_TIMEOUT_MS / 1000.0:
                return       # uzak şarkı çözülürken araya giren başlangıçları yayınlama
            self._clear_pending(pending.get("gen"))
        if self._quiet():
            return
        self._broadcast(True, 0, kind="start")

    def _on_play_error(self, playlist_name: str, index: int):
        """Uzak şarkı çözümlenemezse pending durumunun takılı kalmasını önle."""
        pending = self._pending
        if pending is None:
            return
        songs = self.store.playlists.get(playlist_name, [])
        if 0 <= index < len(songs) and songs[index].get("webpage_url") == pending.get("url"):
            self._on_pending_timeout(pending.get("gen"))
        elif playlist_name == SHARED_PLAYLIST:
            self._on_pending_timeout(pending.get("gen"))

    def _on_play_state(self, playing: bool):
        if self._quiet():
            return
        self._broadcast(bool(playing), self._player_time(), kind="play")

    def _on_seeked(self, ms: int):
        if self._quiet():
            return
        self._broadcast(self._is_playing(), int(ms), kind="seek")

    def _heartbeat(self):
        if self.joined and self.is_host and self._pending is None and self._is_playing():
            self._broadcast(True, self._player_time(), kind="hb", hb=True)

    def _broadcast(self, playing: bool, pos_ms: int, kind: str, hb: bool = False,
                   sync: bool = False):
        song = self._current_song()
        if not is_shareable(song):
            if isinstance(song, dict) and not hb and not self._warned_local:
                self._warned_local = True
                self.notice.emit("Yerel ses dosyaları odayla paylaşılamaz.", "warning")
            return
        now = time.monotonic()
        url = song["webpage_url"]
        last_kind, last_url, last_at = self._last_sent
        if kind == "play" and last_kind == "start" and last_url == url and now - last_at < 1.5:
            return    # yeni şarkının hemen ardından gelen "çalıyor" sinyali zaten yayınlandı
        if self._seq >= MAX_SEQ:
            self._seq = 0
        self._seq += 1
        if self.my_id:
            self._last_by_sender[self.my_id] = self._seq
        if not hb:
            self._last_sent = (kind, url, now)
        self._send({"t": "state", "seq": self._seq, "song": song_payload(song),
                    "playing": bool(playing), "pos_ms": int(pos_ms), "hb": hb,
                    "sync": sync, "lat": self.latency_ms})

    # --- Uzaktan gelen durumu uygula ---
    def _receive_state(self, msg: dict, force: bool = False):
        song = msg.get("song")
        if not is_shareable(song):
            return
        raw_seq = msg.get("seq")
        if not is_valid_seq(raw_seq):
            return
        seq = raw_seq
        raw_pos = msg.get("pos_ms", 0)
        raw_age = msg.get("age_ms", 0)
        if (isinstance(raw_pos, bool) or not isinstance(raw_pos, (int, float))
                or isinstance(raw_age, bool) or not isinstance(raw_age, (int, float))):
            return
        pos = max(0, min(int(raw_pos), 86_400_000))
        age = max(0, min(int(raw_age), 86_400_000))
        raw_from = msg.get("from")
        if not isinstance(raw_from, str) or not raw_from.strip():
            return
        frm = raw_from.strip()
        if not force and self.my_id and frm == self.my_id:
            return
        hb, playing = bool(msg.get("hb")), bool(msg.get("playing"))
        prev = self._last_by_sender.get(frm, 0)
        if not force and seq <= prev:
            return
        # Yalnız gönderenin kendi son sayacını güncelle; yerel _seq sayacına ASLA dokunma!
        self._last_by_sender[frm] = seq
        if playing:
            # geçen süre: sunucuda bekleme + göndericinin ve bizim tek yön gecikmemiz
            pos += age + _safe_ms(msg.get("lat")) + self.latency_ms
        if not hb:
            self._announce_song(song, frm)
        self._apply(song, playing, pos, hb, tight=bool(msg.get("sync")))

    def _announce_song(self, song: dict, frm: str):
        current = self._current_song()
        if isinstance(current, dict) and current.get("webpage_url") == song["webpage_url"]:
            return
        who = next((m["name"] for m in self.members if m["id"] == frm), "")
        if who and frm != self.my_id:
            self.notice.emit(f"🎵 {who}: {song.get('title', '?')}", "info")

    def _apply(self, song: dict, playing: bool, pos: int, hb: bool, tight: bool = False):
        url = song["webpage_url"]
        pending = self._pending
        if pending is not None and pending["url"] == url:
            # Son senkron konumunu ve zamanını (at) güncelle; yükleme başlangıç zamanını
            # (started_at) ve zaman aşımı sayacını (_pending_timer) SIFIRLAMA.
            pending.update(playing=playing, pos=pos, at=time.monotonic())
            return
        current = self._current_song()
        if isinstance(current, dict) and current.get("webpage_url") == url:
            if self._pending is not None:
                self._clear_pending()
            self._sync_same_song(playing, pos, hb, tight)
        else:
            self._play_remote(song, playing, pos)

    def _find_song(self, url: str):
        for name, songs in self.store.playlists.items():
            for idx, s in enumerate(songs):
                if s.get("webpage_url") == url:
                    return name, idx
        return None

    def _play_remote(self, song: dict, playing: bool, pos: int):
        url = song["webpage_url"]
        loc = self._ensure_song(song)
        if loc is None:
            return
        self._pending_gen += 1
        gen = self._pending_gen
        now = time.monotonic()
        self._pending = {
            "url": url,
            "playing": playing,
            "pos": pos,
            "at": now,
            "started_at": now,
            "gen": gen,
        }
        self._pending_timer.start(PENDING_TIMEOUT_MS)
        self._suppress(3.0)
        self.playback.play_song_at_index(*loc)

    def _clear_pending(self, gen: int | None = None) -> bool:
        if self._pending is None:
            return False
        if gen is not None and self._pending.get("gen") != gen:
            return False
        self._pending_timer.stop()
        self._pending = None
        return True

    def _on_pending_timeout(self, gen: int | None = None):
        """Uzak şarkı PENDING_TIMEOUT_MS içinde başlamadıysa pending kilidini güvenli temizle."""
        if self._pending is None:
            return
        if gen is not None and self._pending.get("gen") != gen:
            return
        timed_out = self._pending
        self._pending_timer.stop()
        self._pending = None
        # Mevcut çalma durumunun yanlışlıkla geri yayınlanmasını önle
        self._suppress(1.5)
        log.warning("Uzak şarkı yükleme zaman aşımına uğradı: %s", timed_out.get("url", "?"))

    def _finish_pending(self, pending: dict):
        if not self._clear_pending(pending.get("gen")):
            return
        self._suppress(4.0)
        QTimer.singleShot(1600, lambda: self._after_remote_start(pending))

    def _after_remote_start(self, pending: dict):
        if pending["gen"] != self._pending_gen:
            return
        current = self._current_song()
        if not (isinstance(current, dict) and current.get("webpage_url") == pending["url"]):
            return
        target = pending["pos"]
        if pending["playing"]:
            target += int((time.monotonic() - pending["at"]) * 1000)
        self._suppress(1.5)
        if target > 1500:
            self.playback.seek(int(target))
        if not pending["playing"]:
            self.playback.pause()
        elif not self.is_host:
            QTimer.singleShot(3000, self.request_sync)    # çözülme gecikmesini oda sahibine göre kapat

    def _sync_same_song(self, playing: bool, pos: int, hb: bool, tight: bool = False):
        pb = self.playback
        if getattr(pb, "is_loading", False):
            return
        self._suppress(1.0)
        is_playing = self._is_playing()
        if playing and not is_playing:
            pb.toggle_play_pause()
        elif not playing and is_playing:
            pb.pause()
        tolerance = SYNC_TOL_MS if tight else (DRIFT_MS if hb else SEEK_TOL_MS)
        if abs(self._player_time() - pos) > tolerance:
            pb.seek(int(pos))

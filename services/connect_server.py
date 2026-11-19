"""
Audifly Connect — Yerel ağ (Wi-Fi) üzerinden telefonla canlı web kumanda servisi.

- Harici paket gerektirmez (Python stdlib ThreadingHTTPServer).
- Oturum başına rastgele token üretir; token'sız istekler 403 döner.
- HTTP işçi thread'i hiçbir zaman doğrudan Qt/VLC nesnelerine dokunmaz:
  durum anlık görüntüsü kilitli önbellekten okunur, komutlar Qt sinyaliyle
  GUI thread'ine kuyruklanır.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, Signal

from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.helpers.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_CONNECT_PORT = 8766
MAX_BODY_BYTES = 16_384


def detect_lan_ip() -> str:
    """Bilgisayarın yerel ağ (Wi-Fi/Ethernet) IPv4 adresini paket göndermeden bulur."""
    for target in (("10.255.255.255", 1), ("8.8.8.8", 80)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(target)
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return "127.0.0.1"


def request_windows_firewall_allow(port: int) -> bool:
    """Windows Güvenlik Duvarı'nda Audifly Connect TCP portu için gelen kuralı
    (Private + Public) standart Windows UAC onay penceresiyle ekler."""
    import sys
    if sys.platform != "win32" or not isinstance(port, int) or not (1 <= port <= 65535):
        return False
    try:
        import ctypes
        rule_name = f"Audifly Connect (TCP {port})"
        params = (
            f'advfirewall firewall add rule name="{rule_name}" '
            f'dir=in action=allow protocol=TCP localport={port} profile=private,public'
        )
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", params, None, 0)
        return int(ret) > 32
    except Exception as e:
        log.warning("Windows Güvenlik Duvarı kuralı açılamadı: %s", e)
        return False


_MOBILE_HTML = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0b0d17">
<title>Audifly Connect</title>
<style>
  :root {
    --bg: #0b0d17;
    --card: rgba(22, 26, 42, 0.78);
    --border: rgba(255, 255, 255, 0.10);
    --text: #f3f5fc;
    --muted: #9aa3bd;
    --accent: #a980f9;
    --accent2: #00d2ff;
    --pink: #ff6b8a;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body {
    margin: 0; padding: 0; height: 100%; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
    overflow: hidden;
  }
  .bg-blur {
    position: fixed; inset: -30px; z-index: 0;
    background: radial-gradient(circle at 20% 20%, rgba(169,128,249,.28), transparent 55%),
                radial-gradient(circle at 80% 80%, rgba(0,210,255,.18), transparent 55%),
                #0b0d17;
    background-size: cover; background-position: center;
    filter: blur(42px) brightness(0.45);
    transition: background-image .5s ease;
  }
  .app {
    position: relative; z-index: 1; height: 100%; display: flex; flex-direction: column;
    max-width: 480px; margin: 0 auto;
    padding: env(safe-area-inset-top) 0 env(safe-area-inset-bottom) 0;
  }
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px 8px;
  }
  .brand { font-weight: 800; font-size: 16px; letter-spacing: .4px; display: flex; align-items: center; gap: 8px; }
  .pill {
    font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 999px;
    background: rgba(72, 199, 142, 0.16); color: #5ce1a6; border: 1px solid rgba(72, 199, 142, 0.3);
  }
  .pill.offline { background: rgba(255, 107, 138, 0.16); color: #ff8aa3; border-color: rgba(255, 107, 138, 0.3); }
  .content { flex: 1; overflow-y: auto; padding: 8px 18px 16px; }
  .panel { display: none; }
  .panel.active { display: block; }

  /* Now Playing */
  .cover-wrap {
    width: min(74vw, 290px); height: min(74vw, 290px); margin: 10px auto 18px;
    border-radius: 22px; overflow: hidden;
    background: linear-gradient(135deg, #2d2154, #14192c);
    border: 1px solid var(--border);
    box-shadow: 0 18px 48px rgba(0,0,0,.55);
    display: flex; align-items: center; justify-content: center;
    font-size: 64px;
  }
  .cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: none; }
  .meta-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
  .meta-txt { min-width: 0; flex: 1; }
  .title { font-size: 20px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .artist { font-size: 14px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 3px; }
  .sub-badge { font-size: 11px; color: var(--accent2); margin-top: 2px; }
  .icon-btn {
    background: rgba(255,255,255,.07); border: 1px solid var(--border); color: var(--text);
    width: 44px; height: 44px; border-radius: 22px; font-size: 19px;
    display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
    transition: transform .1s, background .15s, border-color .15s;
  }
  .icon-btn:active { transform: scale(.93); }
  .icon-btn.active { background: rgba(169,128,249,.26); border-color: var(--accent); color: #fff; }
  .icon-btn.liked { background: rgba(255,107,138,.22); border-color: var(--pink); color: var(--pink); }

  /* Sliders */
  .seek-box { margin: 8px 0 16px; }
  input[type=range] {
    -webkit-appearance: none; appearance: none; width: 100%; height: 6px;
    border-radius: 999px; background: rgba(255,255,255,.15); outline: none;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; width: 16px; height: 16px;
    border-radius: 50%; background: #fff; box-shadow: 0 0 10px rgba(169,128,249,.75);
  }
  .times { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); margin-top: 6px; font-variant-numeric: tabular-nums; }

  /* Transport */
  .transport { display: flex; align-items: center; justify-content: space-between; margin: 12px 0 18px; }
  .play-btn {
    width: 66px; height: 66px; border-radius: 33px; border: none; color: #fff; font-size: 26px;
    background: linear-gradient(135deg, var(--accent), #7b52d6);
    box-shadow: 0 10px 28px rgba(169,128,249,.45);
    display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
  }
  .play-btn:active { transform: scale(.94); }

  /* Volume & extras */
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 16px;
    padding: 12px 14px; margin-bottom: 12px;
  }
  .vol-row { display: flex; align-items: center; gap: 12px; }
  .vol-lbl { font-size: 12px; color: var(--muted); min-width: 34px; text-align: right; font-variant-numeric: tabular-nums; }
  .extras { display: flex; gap: 8px; margin-top: 10px; }
  .chip {
    flex: 1; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--border);
    background: rgba(255,255,255,.05); color: var(--text); font-size: 12px; font-weight: 600;
    cursor: pointer; text-align: center;
  }
  .chip.active { background: rgba(0,210,255,.18); border-color: var(--accent2); color: #fff; }

  /* Lists */
  .list-item {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 12px 14px; border-radius: 14px; background: var(--card);
    border: 1px solid var(--border); margin-bottom: 8px; cursor: pointer;
  }
  .list-item:active { background: rgba(169,128,249,.18); }
  .li-main { min-width: 0; flex: 1; }
  .li-title { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .li-sub { font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }
  .empty { text-align: center; color: var(--muted); padding: 36px 12px; font-size: 14px; }
  .back-btn {
    background: rgba(255,255,255,.08); border: 1px solid var(--border); color: var(--text);
    padding: 8px 14px; border-radius: 10px; font-size: 13px; font-weight: 600; margin-bottom: 12px; cursor: pointer;
  }

  /* Bottom Tabs */
  .tabs {
    display: flex; border-top: 1px solid var(--border); background: rgba(12, 14, 24, 0.92);
    backdrop-filter: blur(14px);
  }
  .tab {
    flex: 1; padding: 11px 6px; border: none; background: transparent; color: var(--muted);
    font-size: 12px; font-weight: 700; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 3px;
  }
  .tab.active { color: var(--accent); }
</style>
</head>
<body>
<div class="bg-blur" id="bgBlur"></div>
<div class="app">
  <div class="topbar">
    <div class="brand">🎵 Audifly Connect</div>
    <div class="pill" id="connPill">Bağlanıyor…</div>
  </div>

  <div class="content">
    <!-- TAB 1: NOW PLAYING -->
    <div class="panel active" id="panel-now">
      <div class="cover-wrap">
        <span id="coverFallback">🎵</span>
        <img id="coverImg" alt="Kapak">
      </div>

      <div class="meta-row">
        <div class="meta-txt">
          <div class="title" id="songTitle">Şarkı seçilmedi</div>
          <div class="artist" id="songArtist">Audifly Masaüstü</div>
          <div class="sub-badge" id="songSource"></div>
        </div>
        <button class="icon-btn" id="likeBtn" title="Beğen">♡</button>
      </div>

      <div class="seek-box">
        <input type="range" id="seekSlider" min="0" max="1000" value="0">
        <div class="times"><span id="curTime">00:00</span><span id="totTime">00:00</span></div>
      </div>

      <div class="transport">
        <button class="icon-btn" id="shuffleBtn" title="Karışık">🔀</button>
        <button class="icon-btn" id="prevBtn" title="Önceki">⏮</button>
        <button class="play-btn" id="playBtn" title="Oynat / Duraklat">▶</button>
        <button class="icon-btn" id="nextBtn" title="Sonraki">⏭</button>
        <button class="icon-btn" id="repeatBtn" title="Tekrar">🔁</button>
      </div>

      <div class="card">
        <div class="vol-row">
          <span style="font-size:18px">🔊</span>
          <input type="range" id="volSlider" min="0" max="100" value="80">
          <span class="vol-lbl" id="volLbl">80%</span>
        </div>
        <div class="extras">
          <button class="chip" id="vocalBtn">🎙️ Vokal Ayırma</button>
        </div>
      </div>
    </div>

    <!-- TAB 2: QUEUE -->
    <div class="panel" id="panel-queue">
      <div id="queueList"></div>
    </div>

    <!-- TAB 3: PLAYLISTS -->
    <div class="panel" id="panel-playlists">
      <div id="playlistView"></div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab active" data-tab="now"><span>🎧</span><span>Çalıyor</span></button>
    <button class="tab" data-tab="queue"><span>📋</span><span>Kuyruk</span></button>
    <button class="tab" data-tab="playlists"><span>📂</span><span>Listeler</span></button>
  </div>
</div>

<script>
const TOKEN = __AUDIFLY_TOKEN__;
let lastState = null;
let seeking = false;
let volDragging = false;
let lastCoverKey = "";
let activePlaylistName = null;

function fmt(ms) {
  ms = Math.max(0, Math.floor((ms || 0) / 1000));
  const m = Math.floor(ms / 60), s = ms % 60;
  return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}

async function api(path, opts = {}) {
  const headers = Object.assign({ 'X-Audifly-Token': TOKEN }, opts.headers || {});
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

async function sendCmd(action, extra = {}) {
  try {
    await api('/api/cmd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ action }, extra)),
    });
    setTimeout(pollState, 120);
  } catch (e) {
    setConn(false);
  }
}

function setConn(ok) {
  const p = document.getElementById('connPill');
  if (ok) { p.textContent = '● Bağlı'; p.classList.remove('offline'); }
  else { p.textContent = '● Yeniden bağlanıyor…'; p.classList.add('offline'); }
}

function renderState(s) {
  lastState = s;
  document.getElementById('songTitle').textContent = s.title || 'Şarkı seçilmedi';
  document.getElementById('songArtist').textContent = s.artist || 'Audifly Masaüstü';
  document.getElementById('songSource').textContent = s.radio ? '📻 Canlı Radyo' : (s.playlist ? '📂 ' + s.playlist : '');

  document.getElementById('playBtn').textContent = s.playing ? '⏸' : '▶';

  const likeBtn = document.getElementById('likeBtn');
  likeBtn.textContent = s.liked ? '♥' : '♡';
  likeBtn.classList.toggle('liked', !!s.liked);

  document.getElementById('shuffleBtn').classList.toggle('active', !!s.shuffle);
  const repBtn = document.getElementById('repeatBtn');
  repBtn.textContent = s.repeat === 'one' ? '🔂' : '🔁';
  repBtn.classList.toggle('active', s.repeat && s.repeat !== 'off');

  document.getElementById('vocalBtn').classList.toggle('active', !!s.vocal_remover);

  if (!volDragging && typeof s.volume === 'number') {
    document.getElementById('volSlider').value = s.volume;
    document.getElementById('volLbl').textContent = s.volume + '%';
  }
  if (!seeking) {
    const dur = s.duration_ms || 0;
    const pos = s.position_ms || 0;
    const sl = document.getElementById('seekSlider');
    sl.max = dur > 0 ? dur : 1000;
    sl.value = dur > 0 ? Math.min(pos, dur) : 0;
    document.getElementById('curTime').textContent = s.radio ? 'CANLI' : fmt(pos);
    document.getElementById('totTime').textContent = s.radio ? '' : fmt(dur);
  }

  // Cover art
  const cKey = s.cover_key || '';
  if (cKey !== lastCoverKey) {
    lastCoverKey = cKey;
    const img = document.getElementById('coverImg');
    const fb = document.getElementById('coverFallback');
    const bg = document.getElementById('bgBlur');
    if (cKey) {
      const url = '/api/cover?t=' + encodeURIComponent(TOKEN) + '&v=' + encodeURIComponent(cKey);
      img.onload = () => { img.style.display = 'block'; fb.style.display = 'none'; bg.style.backgroundImage = `url("${url}")`; };
      img.onerror = () => { img.style.display = 'none'; fb.style.display = 'block'; bg.style.backgroundImage = ''; };
      img.src = url;
    } else {
      img.style.display = 'none'; fb.style.display = 'block'; bg.style.backgroundImage = '';
    }
  }

  // Queue tab
  const qEl = document.getElementById('queueList');
  const q = s.queue || [];
  if (!q.length) {
    qEl.innerHTML = '<div class="empty">Kuyruk boş.<br>Listeler sekmesinden şarkı seçebilirsin.</div>';
  } else {
    qEl.innerHTML = q.map((it, idx) => `
      <div class="list-item" onclick="sendCmd('play_queue_item',{index:${idx}})">
        <div class="li-main">
          <div class="li-title">${esc(it.title)}</div>
          <div class="li-sub">${esc(it.artist || it.playlist || '')}</div>
        </div>
        <span>▶</span>
      </div>`).join('');
  }
}

function esc(str) {
  return String(str || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadPlaylists() {
  const el = document.getElementById('playlistView');
  try {
    if (!activePlaylistName) {
      const data = await api('/api/playlists');
      const pls = data.playlists || [];
      if (!pls.length) { el.innerHTML = '<div class="empty">Henüz çalma listesi yok.</div>'; return; }
      el.innerHTML = pls.map(p => `
        <div class="list-item" onclick="openPlaylist(${JSON.stringify(p.name)})">
          <div class="li-main">
            <div class="li-title">📂 ${esc(p.name)}</div>
            <div class="li-sub">${p.count} şarkı</div>
          </div>
          <span>›</span>
        </div>`).join('');
    } else {
      const data = await api('/api/playlists?name=' + encodeURIComponent(activePlaylistName));
      const songs = data.songs || [];
      let html = `<button class="back-btn" onclick="activePlaylistName=null;loadPlaylists()">← Tüm Listeler</button>`;
      if (!songs.length) html += '<div class="empty">Bu listede şarkı yok.</div>';
      else html += songs.map((s, idx) => `
        <div class="list-item" onclick="sendCmd('play_playlist_song',{playlist:${JSON.stringify(activePlaylistName)},index:${idx}})">
          <div class="li-main">
            <div class="li-title">${esc(s.title)}</div>
            <div class="li-sub">${esc(s.artist)}</div>
          </div>
          <span>▶</span>
        </div>`).join('');
      el.innerHTML = html;
    }
  } catch (e) {
    el.innerHTML = '<div class="empty">Listeler yüklenemedi.</div>';
  }
}

function openPlaylist(name) {
  activePlaylistName = name;
  loadPlaylists();
}

async function pollState() {
  try {
    const s = await api('/api/state');
    setConn(true);
    renderState(s);
  } catch (e) {
    setConn(false);
  }
}

// Wire controls
document.getElementById('playBtn').onclick = () => sendCmd('toggle');
document.getElementById('nextBtn').onclick = () => sendCmd('next');
document.getElementById('prevBtn').onclick = () => sendCmd('prev');
document.getElementById('shuffleBtn').onclick = () => sendCmd('shuffle');
document.getElementById('repeatBtn').onclick = () => sendCmd('repeat');
document.getElementById('likeBtn').onclick = () => sendCmd('like');
document.getElementById('vocalBtn').onclick = () => sendCmd('vocal_remover');

const seekSl = document.getElementById('seekSlider');
seekSl.addEventListener('pointerdown', () => seeking = true);
seekSl.addEventListener('input', () => { document.getElementById('curTime').textContent = fmt(Number(seekSl.value)); });
seekSl.addEventListener('change', () => { seeking = false; sendCmd('seek', { ms: Number(seekSl.value) }); });

const volSl = document.getElementById('volSlider');
volSl.addEventListener('pointerdown', () => volDragging = true);
volSl.addEventListener('input', () => { document.getElementById('volLbl').textContent = volSl.value + '%'; });
volSl.addEventListener('change', () => { volDragging = false; sendCmd('volume', { value: Number(volSl.value) }); });

document.querySelectorAll('.tab').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const t = btn.dataset.tab;
    document.getElementById('panel-' + t).classList.add('active');
    if (t === 'playlists') loadPlaylists();
  };
});

pollState();
setInterval(pollState, 1000);
</script>
</body>
</html>
"""


class AudiflyConnectService(QObject):
    """Yerel ağda çalışan güvenli Audifly Connect HTTP sunucusu."""

    statusChanged = Signal(bool, str)      # running, url
    _commandRequested = Signal(str, object)

    def __init__(self, store, playback, thumbnails=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails

        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._token: str = secrets.token_urlsafe(9)
        self._port: int = 0
        self._host_ip: str = "127.0.0.1"

        self._state_lock = threading.Lock()
        self._state: dict = {}
        self._playlists_cache: dict[str, list[dict]] = {}
        self._cover_bytes: bytes | None = None
        self._cover_key: str = ""

        self._commandRequested.connect(self._execute_command)
        self._wire_signals()
        self._refresh_snapshot()
        self._refresh_playlists_cache()

    # ------------------------------------------------------------------
    # Yaşam Döngüsü
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    @property
    def token(self) -> str:
        return self._token

    @property
    def url(self) -> str:
        if not self.is_running:
            return ""
        return f"http://{self._host_ip}:{self._port}/?t={self._token}"

    def start(self, port: int = DEFAULT_CONNECT_PORT) -> tuple[bool, str]:
        """Yerel HTTP sunucusunu başlatır. (ok, url_veya_hata) döner."""
        if self._httpd is not None:
            return True, self.url

        self._host_ip = detect_lan_ip()
        self._refresh_snapshot()
        self._refresh_playlists_cache()

        class _ReusableHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        handler_cls = self._make_handler_class()
        server = None
        for candidate in (port, 0):
            try:
                server = _ReusableHTTPServer(("0.0.0.0", candidate), handler_cls)
                break
            except OSError:
                continue
        if server is None:
            return False, "Yerel sunucu portu açılamadı."

        self._httpd = server
        self._port = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.25},
            daemon=True,
            name="AudiflyConnectHTTP",
        )
        self._thread.start()
        log.info("Audifly Connect başlatıldı: %s", self.url)
        self.statusChanged.emit(True, self.url)
        return True, self.url

    def stop(self):
        server, self._httpd = self._httpd, None
        thread, self._thread = self._thread, None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as e:
                log.warning("Audifly Connect kapatma uyarısı: %s", e)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._port = 0
        self.statusChanged.emit(False, "")

    def rotate_token(self) -> str:
        self._token = secrets.token_urlsafe(9)
        if self.is_running:
            self.statusChanged.emit(True, self.url)
        return self.url

    # ------------------------------------------------------------------
    # GUI Thread Durum Senkronu
    # ------------------------------------------------------------------
    def _wire_signals(self):
        pb = self.playback
        for sig_name in (
            "songStarted", "playStateChanged", "positionChanged",
            "volumeChanged", "shuffleChanged", "repeatChanged",
            "vocalRemoverChanged", "radioStarted", "radioStopped",
        ):
            sig = getattr(pb, sig_name, None)
            if sig is not None:
                sig.connect(self._on_state_signal)
        if self.store is not None:
            if hasattr(self.store, "playlistsChanged"):
                self.store.playlistsChanged.connect(self._on_library_changed)
            if hasattr(self.store, "queueChanged"):
                self.store.queueChanged.connect(self._on_state_signal)
        if self.thumbnails is not None and hasattr(self.thumbnails, "thumbnailReady"):
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    def _on_state_signal(self, *_args):
        self._refresh_snapshot()

    def _on_library_changed(self, *_args):
        self._refresh_playlists_cache()
        self._refresh_snapshot()

    def _on_thumbnail_ready(self, key: str):
        song = getattr(self.playback, "current_song", None)
        if isinstance(song, dict) and song.get("webpage_url") == key:
            self._update_cover_bytes(song)

    def _update_cover_bytes(self, song: dict | None):
        if not song or self.thumbnails is None:
            with self._state_lock:
                self._cover_bytes = None
                self._cover_key = ""
                if self._state:
                    self._state["cover_key"] = ""
            return
        try:
            pil_img = self.thumbnails.pil_for(song)
        except Exception:
            pil_img = None
        if pil_img is None:
            with self._state_lock:
                self._cover_bytes = None
                self._cover_key = ""
                if self._state:
                    self._state["cover_key"] = ""
            return
        try:
            buf = io.BytesIO()
            img = pil_img.convert("RGB")
            img.thumbnail((512, 512))
            img.save(buf, format="JPEG", quality=85)
            raw = buf.getvalue()
            ckey = hashlib.md5(raw[:1024] + str(len(raw)).encode()).hexdigest()[:12]
            with self._state_lock:
                self._cover_bytes = raw
                self._cover_key = ckey
                if self._state:
                    self._state["cover_key"] = ckey
        except Exception as e:
            log.debug("Connect kapak kodlanamadı: %s", e)

    def _refresh_playlists_cache(self):
        cache: dict[str, list[dict]] = {}
        playlists = getattr(self.store, "playlists", {}) or {}
        for pl_name, songs in playlists.items():
            items = []
            for s in songs[:300]:
                t, a = parse_track_and_artist(s.get("title", ""), s.get("uploader", ""), s)
                items.append({"title": t, "artist": a})
            cache[pl_name] = items
        with self._state_lock:
            self._playlists_cache = cache

    def _refresh_snapshot(self):
        pb = self.playback
        radio = getattr(pb, "radio_playing", None)
        song = getattr(pb, "current_song", None)

        if radio is not None:
            title = radio.get("name") or "Canlı Radyo"
            artist = radio.get("country") or "Canlı Yayın"
            liked = False
            dur_ms = 0
            pos_ms = 0
            is_radio = True
            self._update_cover_bytes(None)
        elif isinstance(song, dict):
            title, artist = parse_track_and_artist(
                song.get("title", ""), song.get("uploader", ""), song
            )
            liked = bool(song.get("liked"))
            dur_ms = max(0, int((song.get("duration") or 0) * 1000))
            pos_ms = 0
            try:
                src = pb.player_b if (callable(getattr(pb, "_xfade_is_ramping", None)) and pb._xfade_is_ramping()) else pb.player
                raw_pos = src.get_time()
                raw_len = src.get_length()
                if isinstance(raw_len, int) and raw_len > 0:
                    dur_ms = raw_len
                if isinstance(raw_pos, int) and raw_pos >= 0:
                    pos_ms = raw_pos
            except Exception:
                pass
            is_radio = False
            self._update_cover_bytes(song)
        else:
            title = "Şarkı seçilmedi"
            artist = "Audifly Masaüstü"
            liked = False
            dur_ms = 0
            pos_ms = 0
            is_radio = False
            self._update_cover_bytes(None)

        queue_out = []
        for pl_name, _idx, q_song in list(getattr(self.store, "manual_queue", []) or [])[:40]:
            qt, qa = parse_track_and_artist(q_song.get("title", ""), q_song.get("uploader", ""), q_song)
            queue_out.append({"title": qt, "artist": qa, "playlist": pl_name})

        settings = getattr(pb, "settings", {}) or {}
        vol = int(settings.get("_volume", 80))

        with self._state_lock:
            self._state = {
                "title": title,
                "artist": artist,
                "playlist": getattr(pb, "playing_playlist", None) or "",
                "radio": is_radio,
                "playing": bool(getattr(pb, "is_playing", False)),
                "position_ms": pos_ms,
                "duration_ms": dur_ms,
                "volume": max(0, min(100, vol)),
                "shuffle": bool(getattr(pb, "shuffle_mode", False)),
                "repeat": getattr(pb, "repeat_mode", "off"),
                "vocal_remover": bool(getattr(pb, "vocal_remover_enabled", False)),
                "liked": liked,
                "cover_key": self._cover_key,
                "queue": queue_out,
            }

    # ------------------------------------------------------------------
    # GUI Thread Komut Yürütücü
    # ------------------------------------------------------------------
    def _execute_command(self, action: str, payload: dict):
        pb = self.playback
        if action == "toggle":
            pb.toggle_play_pause()
        elif action == "next":
            pb.play_next()
        elif action == "prev":
            pb.play_previous()
        elif action == "seek":
            ms = payload.get("ms")
            if isinstance(ms, (int, float)):
                pb.seek(int(ms))
        elif action == "volume":
            val = payload.get("value")
            if isinstance(val, (int, float)):
                pb.change_volume(max(0, min(100, int(val))))
        elif action == "shuffle":
            pb.toggle_shuffle()
        elif action == "repeat":
            pb.cycle_repeat()
        elif action == "vocal_remover":
            if hasattr(pb, "toggle_vocal_remover"):
                pb.toggle_vocal_remover()
        elif action == "like":
            pl = getattr(pb, "playing_playlist", None)
            idx = getattr(pb, "current_index", -1)
            if pl is not None and idx >= 0:
                self.store.toggle_like(pl, idx)
        elif action == "play_playlist_song":
            pl = str(payload.get("playlist") or "")
            idx = payload.get("index")
            if pl in self.store.playlists and isinstance(idx, int) and 0 <= idx < len(self.store.playlists[pl]):
                pb.play_song_at_index(pl, idx)
        elif action == "play_queue_item":
            idx = payload.get("index")
            if isinstance(idx, int) and 0 <= idx < len(self.store.manual_queue):
                real_pl, real_idx = self.store.play_from_queue(idx)
                if real_pl is not None:
                    pb.play_song_at_index(real_pl, real_idx)
        self._refresh_snapshot()

    # ------------------------------------------------------------------
    # HTTP Handler
    # ------------------------------------------------------------------
    def _is_authorized(self, header_tok: str | None, query_tok: str | None) -> bool:
        provided = (header_tok or query_tok or "").strip()
        return bool(provided) and hmac.compare_digest(provided, self._token)

    def _make_handler_class(self):
        svc = self

        class ConnectHandler(BaseHTTPRequestHandler):
            timeout = 5

            def log_message(self, fmt, *args):  # noqa: A002
                return  # konsolu HTTP loglarıyla doldurma

            def _send_json(self, data: dict, status: int = HTTPStatus.OK):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_bytes(self, body: bytes, content_type: str, status: int = HTTPStatus.OK,
                            cache_control: str = "no-store"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", cache_control)
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _check_auth(self, parsed) -> bool:
                qs = parse_qs(parsed.query)
                q_tok = qs.get("t", [""])[0]
                h_tok = self.headers.get("X-Audifly-Token", "")
                if not svc._is_authorized(h_tok, q_tok):
                    self._send_json({"error": "unauthorized"}, HTTPStatus.FORBIDDEN)
                    return False
                return True

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path

                if path == "/" or path == "/index.html":
                    if not self._check_auth(parsed):
                        return
                    html = _MOBILE_HTML.replace("__AUDIFLY_TOKEN__", json.dumps(svc._token))
                    self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
                    return

                if path == "/api/state":
                    if not self._check_auth(parsed):
                        return
                    with svc._state_lock:
                        snap = dict(svc._state)
                    self._send_json(snap)
                    return

                if path == "/api/playlists":
                    if not self._check_auth(parsed):
                        return
                    qs = parse_qs(parsed.query)
                    wanted = qs.get("name", [""])[0]
                    with svc._state_lock:
                        if wanted:
                            songs = list(svc._playlists_cache.get(wanted, []))
                            self._send_json({"name": wanted, "songs": songs})
                        else:
                            summary = [
                                {"name": name, "count": len(songs)}
                                for name, songs in svc._playlists_cache.items()
                            ]
                            self._send_json({"playlists": summary})
                    return

                if path == "/api/cover":
                    if not self._check_auth(parsed):
                        return
                    with svc._state_lock:
                        raw = svc._cover_bytes
                    if not raw:
                        self.send_response(HTTPStatus.NOT_FOUND)
                        self.end_headers()
                        return
                    self._send_bytes(raw, "image/jpeg", cache_control="public, max-age=60")
                    return

                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/api/cmd":
                    self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                    return
                if not self._check_auth(parsed):
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > MAX_BODY_BYTES:
                    self._send_json({"error": "bad_request"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
                    return
                if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
                    self._send_json({"error": "missing_action"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    svc._commandRequested.emit(payload["action"], payload)
                except RuntimeError:
                    self._send_json({"error": "closing"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._send_json({"ok": True})

        return ConnectHandler

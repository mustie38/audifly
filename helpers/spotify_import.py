"""
Spotify playlist içe aktarma: OAuth (Authorization Code) akışı + playlist çekme.

Orijinal mustiefly_helpers.py'deki Spotify bölümünün portudur — stdlib
http.server tabanlıdır, Qt'ye bağımlılığı yoktur.

NOT (Şubat 2026 Spotify API migrasyonu): Playlist okuma uç noktaları salt Client
Credentials token'ları kabul etmiyor; gerçek kullanıcı girişi (Authorization Code)
gerekiyor. Bir kez tarayıcıdan onay verilince alınan refresh_token ayarlara
kaydedilip sonraki seferlerde sessizce yenileniyor.
"""
from __future__ import annotations

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
import base64
import hashlib
import json
import re
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_REDIRECT_PORT = 8888
SPOTIFY_REDIRECT_URI = f"http://127.0.0.1:{SPOTIFY_REDIRECT_PORT}/callback"
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"


def extract_spotify_playlist_id(url_or_uri):
    """Bir Spotify playlist URL'sinden ya da URI'sından sadece ID'yi çıkarır."""
    text = (url_or_uri or "").strip()
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?playlist/([A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"spotify:playlist:([A-Za-z0-9]+)", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{15,30}", text):
        return text
    return None


class _SpotifyCallbackHandler(BaseHTTPRequestHandler):
    """Spotify'ın tarayıcıdan yönlendirdiği kısa ömürlü yerel uç nokta."""
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        state = params.get("state", [""])[0]
        if not secrets.compare_digest(state.encode("utf-8"), self.server.expected_state.encode("utf-8")):
            self.send_error(400, "Invalid OAuth state")
            return
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]
        if not code and not error:
            self.send_error(400, "Missing authorization result")
            return
        self.server.auth_code = code
        self.server.auth_error = error

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        if self.server.auth_code:
            body = f"<h2>{APP_DISPLAY_NAME} Spotify bağlantısı başarılı ✅</h2><p>Bu sekmeyi kapatıp uygulamaya dönebilirsin.</p>"
        else:
            body = "<h2>Yetkilendirme tamamlanamadı ❌</h2><p>Bu sekmeyi kapatıp uygulamada tekrar dene.</p>"
        self.wfile.write(f"<html><body style='font-family:sans-serif;text-align:center;margin-top:80px'>{body}</body></html>".encode("utf-8"))

    def log_message(self, format, *args):
        pass


def make_pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge[S256]) — RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def spotify_authorize_interactive(client_id, timeout=120, code_challenge=None):
    """Tarayıcıda Spotify giriş/onay ekranını açar ve localhost:8888'de dinleyerek
    yetkilendirme kodunu yakalar. (auth_code, error) döner."""
    try:
        server = HTTPServer(("127.0.0.1", SPOTIFY_REDIRECT_PORT), _SpotifyCallbackHandler)
    except OSError as e:
        return None, f"Yerel port {SPOTIFY_REDIRECT_PORT} kullanılamıyor: {e}"

    server.auth_code = None
    server.auth_error = None
    server.expected_state = secrets.token_urlsafe(32)
    server.timeout = min(1.0, max(0.01, timeout))

    params = {
        "state": server.expected_state,
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SPOTIFY_SCOPES,
        "show_dialog": "true",
    }
    if code_challenge:
        params["code_challenge_method"] = "S256"
        params["code_challenge"] = code_challenge
    auth_url = f"{SPOTIFY_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    try:
        if not webbrowser.open(auth_url):
            return None, "Tarayıcı açılamadı. Varsayılan tarayıcı ayarlarını kontrol et."
        deadline = time.monotonic() + timeout
        while not server.auth_code and not server.auth_error:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            server.timeout = min(1.0, remaining)
            server.handle_request()
    finally:
        server.server_close()

    if server.auth_code:
        return server.auth_code, None
    return None, server.auth_error or "Zaman aşımı: tarayıcıda giriş/onay tamamlanmadı."


class SpotifyAuthError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Spotify auth hatası ({status_code}): {detail}")


class SpotifyApiError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Spotify API hatası ({status_code}): {detail}")


def _spotify_error_detail(resp):
    try:
        data = resp.json()
        if isinstance(data.get("error"), dict):
            return data["error"].get("message", resp.text[:200])
        return data.get("error_description") or data.get("error") or resp.text[:200]
    except Exception:
        return (resp.text or "")[:200]


def _token_request(data, client_id, client_secret):
    """Secret varsa Basic auth (eski bağlantılar), yoksa PKCE: client_id gövdede."""
    if client_secret:
        return requests.post(SPOTIFY_TOKEN_URL, data=data,
                             auth=(client_id, client_secret), timeout=10)
    return requests.post(SPOTIFY_TOKEN_URL, data={**data, "client_id": client_id}, timeout=10)


def get_spotify_user_access_token(client_id, client_secret, settings, save_settings_fn,
                                  *, allow_interactive: bool = True):
    """Kullanıcı bağlamlı access token döner. client_secret ARTIK İSTEĞE BAĞLI:
    yetkilendirme her zaman PKCE (S256) ile yapılır. Kayıtlı refresh_token varsa
    tarayıcı açmadan yenilenir."""
    refresh_token = settings.get("spotify_refresh_token", "")

    if refresh_token:
        resp = _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token},
                              client_id, client_secret)
        if resp.ok:
            data = resp.json()
            if data.get("refresh_token"):
                settings["spotify_refresh_token"] = data["refresh_token"]
                save_settings_fn()
            return data["access_token"]
        if not allow_interactive:
            raise SpotifyAuthError(resp.status_code, _spotify_error_detail(resp))

    if not allow_interactive:
        raise SpotifyAuthError(401, "Kayıtlı Spotify oturumu yok.")

    verifier, challenge = make_pkce_pair()
    code, error = spotify_authorize_interactive(client_id, code_challenge=challenge)
    if not code:
        raise SpotifyAuthError(401, error or "Kullanıcı yetkilendirmesi tamamlanmadı veya iptal edildi.")

    resp = _token_request({"grant_type": "authorization_code", "code": code,
                           "redirect_uri": SPOTIFY_REDIRECT_URI, "code_verifier": verifier},
                          client_id, client_secret)
    if not resp.ok:
        raise SpotifyAuthError(resp.status_code, _spotify_error_detail(resp))
    data = resp.json()
    if data.get("refresh_token"):
        settings["spotify_refresh_token"] = data["refresh_token"]
        save_settings_fn()
    return data["access_token"]


def search_spotify_playlist(query, client_id, client_secret, settings, save_settings_fn,
                             prefer_owner_id="spotify", *, allow_interactive: bool = True):
    """Bir playlist adını (örn. 'Top 50 - Türkiye') Spotify'da arar ve en
    uygun playlist'in ID'sini döner — kullanıcı ID'yi elle bulup yapıştırmak
    zorunda kalmasın diye. Sonuçlar arasında sahibi resmi 'Spotify' hesabı
    olan (örn. resmi Top 50/Viral 50 chart'ları) varsa o önceliklidir;
    yoksa ilk sonuca düşülür. (id, playlist_adı) döner; bulunamazsa (None, None)."""
    if allow_interactive:
        token = get_spotify_user_access_token(client_id, client_secret, settings, save_settings_fn)
    else:
        token = get_spotify_user_access_token(
            client_id, client_secret, settings, save_settings_fn, allow_interactive=False
        )
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"{SPOTIFY_API_BASE}/search", headers=headers,
        params={"q": query, "type": "playlist", "limit": 10}, timeout=10,
    )
    if not resp.ok:
        raise SpotifyApiError(resp.status_code, _spotify_error_detail(resp))
    items = ((resp.json().get("playlists") or {}).get("items")) or []
    items = [it for it in items if it]  # Spotify bazen null öğe döndürebiliyor
    if not items:
        return None, None
    for item in items:
        if (item.get("owner") or {}).get("id") == prefer_owner_id:
            return item["id"], item.get("name")
    first = items[0]
    return first["id"], first.get("name")


def fetch_spotify_playlist_embed(playlist_id: str, get=None) -> tuple[str, list[str]]:
    """Spotify'ın herkese açık gömülü sayfasından (`open.spotify.com/embed/playlist/<id>`)
    liste adını ve şarkı sorgularını ('Sanatçı - Şarkı Adı') çeker.

    Neden: Şubat 2026'dan itibaren Spotify Development Mode API'si (`/v1/playlists/{id}/items`)
    başka kullanıcıların herkese açık listelerine ve Spotify'ın kendi resmi listelerine
    403/404 döndürüyor. Gömülü sayfa ise Client ID veya giriş gerektirmeden tüm herkese
    açık listelerin `__NEXT_DATA__` JSON verisini doğrudan döndürür.
    """
    if get is None:
        get = requests.get
    resp = get(
        f"https://open.spotify.com/embed/playlist/{playlist_id}",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        timeout=12,
    )
    if not resp.ok:
        raise SpotifyApiError(resp.status_code, _spotify_error_detail(resp))
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if not match:
        raise SpotifyApiError(404, "Playlist verisi okunamadı (liste gizli veya mevcut değil).")
    try:
        data = json.loads(match.group(1))
        entity = (
            ((data.get("props") or {}).get("pageProps") or {})
            .get("state", {})
            .get("data", {})
            .get("entity")
        ) or {}
    except Exception as e:
        raise SpotifyApiError(500, f"Embed JSON ayrıştırılamadı: {e}") from e

    playlist_name = (entity.get("name") or entity.get("title") or "Spotify Playlist").strip()[:50]
    queries: list[str] = []
    for item in entity.get("trackList") or []:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").replace("\xa0", " ").strip()
        artists = (item.get("subtitle") or "").replace("\xa0", " ").strip()
        if title:
            queries.append(f"{artists} - {title}" if artists else title)
    if not queries:
        raise SpotifyApiError(404, "Bu playlist boş veya gizli.")
    return playlist_name, queries


def fetch_spotify_playlist(playlist_id, client_id, client_secret, settings, save_settings_fn,
                           *, allow_interactive: bool = True):
    """Bir Spotify playlist'inin adını ve tüm şarkılarını ('Sanatçı - Şarkı Adı'
    arama sorguları olarak) çeker.

    Önce (Client ID tanımlıysa) resmi Web API'yi dener (100+ şarkılık kendi listelerin
    ve gizli/ortak listelerin için). Eğer Client ID girilmemişse ya da liste başka bir
    kullanıcıya / Spotify'a ait olduğu için API 403/404/401 döndürürse otomatik olarak
    herkese açık embed sayfasına (`fetch_spotify_playlist_embed`) düşer.
    """
    if not (client_id or "").strip():
        return fetch_spotify_playlist_embed(playlist_id)

    try:
        if allow_interactive:
            token = get_spotify_user_access_token(client_id, client_secret, settings, save_settings_fn)
        else:
            token = get_spotify_user_access_token(
                client_id, client_secret, settings, save_settings_fn, allow_interactive=False
            )
        headers = {"Authorization": f"Bearer {token}"}

        meta_resp = requests.get(
            f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
            headers=headers, params={"fields": "name"}, timeout=10,
        )
        if not meta_resp.ok:
            raise SpotifyApiError(meta_resp.status_code, _spotify_error_detail(meta_resp))
        playlist_name = (meta_resp.json().get("name") or "Spotify Playlist").strip()[:50]

        queries = []
        url = f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/items"
        params = {"fields": "next,items(item(name,artists(name)))", "limit": 100}

        while url:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if not resp.ok:
                raise SpotifyApiError(resp.status_code, _spotify_error_detail(resp))
            data = resp.json()
            for entry in data.get("items", []):
                track = entry.get("item") or entry.get("track")  # eski API'den kalma yedek alan
                if not track:
                    continue
                name = track.get("name")
                artists = ", ".join(a["name"] for a in track.get("artists", []) if a.get("name"))
                if name:
                    queries.append(f"{artists} - {name}" if artists else name)
            url = data.get("next")
            params = None  # 'next' URL'si tüm parametreleri zaten içeriyor

        if queries:
            return playlist_name, queries
    except (SpotifyApiError, SpotifyAuthError):
        # Başka bir kullanıcının veya Spotify'ın herkese açık listesi (403/404) ya da
        # henüz giriş yapılmamış durum: embed üzerinden çekmeyi dene.
        try:
            return fetch_spotify_playlist_embed(playlist_id)
        except Exception:
            raise

    return fetch_spotify_playlist_embed(playlist_id)


# --- M3U dışa/içe aktarma ---

def export_playlist_m3u(songs, path) -> str | None:
    """Şarkı listesini M3U dosyasına yazar. Hata olursa hata mesajı döner."""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            for s in songs:
                dur = int(s.get('duration') or 0)
                raw_title = f"{s.get('uploader', '')} - {s.get('title', '')}".strip(" -")
                title = raw_title.replace("\r", " ").replace("\n", " ")
                url = str(s.get('webpage_url', '') or '').replace("\r", "").replace("\n", "")
                f.write(f"#EXTINF:{dur},{title}\n")
                f.write(f"{url}\n")
        return None
    except Exception as e:
        return str(e)


def parse_m3u_file(path) -> tuple[list, str | None]:
    """M3U dosyasını ayrıştırır; (entries, hata_mesajı) döner.
    entries: [(url, title_hint, duration_hint), ...]"""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as e:
        return [], str(e)

    entries = []
    pending_title, pending_duration = None, 0
    for line in lines:
        if line.startswith("#EXTINF"):
            try:
                meta = line.split(":", 1)[1]
                dur_str, _, title = meta.partition(",")
                pending_duration = int(float(dur_str))
                pending_title = title.strip()
            except Exception:
                pending_title, pending_duration = None, 0
        elif line.startswith("#"):
            continue
        else:
            entries.append((line, pending_title, pending_duration))
            pending_title, pending_duration = None, 0
    return entries, None

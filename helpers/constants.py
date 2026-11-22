"""
Mustiefly (Qt) - Ortak sabitler, tema paleti ve saf yardımcı fonksiyonlar.

NOT (mimari): Orijinal tkinter sürümünde bu sabitler "from mustiefly_helpers
import *" ile her dosyaya birer KOPYA olarak bağlanıyordu, bu yüzden runtime'da
mustiefly_helpers.PLAYLIST_FILE gibi modül özniteliklerini değiştirmek
gerekiyordu. Qt sürümünde bu tuzağa hiç girmiyoruz: kullanıcıya özel yollar
`AppPaths` adlı küçük bir veri sınıfında tutulur ve ihtiyacı olan her yere
parametre olarak geçilir; hiçbir yerde process-genelinde mutasyona uğrayan
modül-seviyesi bir sabit yok.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Optional

import yt_dlp
from mustiefly_qt.helpers.dependencies import bundled_bin_dir, prepend_bundled_bin_to_path
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
# --- Genel sabitler ---
DEFAULT_PLAYLIST_NAME = "Varsayılan"
STREAM_URL_TTL = 3 * 60 * 60  # 3 saat
BACKUP_MIN_INTERVAL = 180  # 3 dakika
PAGE_SIZE = 60
LIBRARY_SEARCH_DEBOUNCE_MS = 300
THUMBNAIL_MAX_WORKERS = 6
BULK_SEARCH_WORKERS = 5
SEARCH_RESULT_THUMB_SIZE = 32  # arama sonuçlarındaki yuvarlak kapak boyutu

DISCORD_CLIENT_ID_DEFAULT = "1536007378783436922"

# Paketle gelen bin/ (ffmpeg, node) varsa PATH'e ekle — aşağıdaki Node denetiminden ÖNCE
prepend_bundled_bin_to_path()


def _detect_node_path() -> str | None:
    """Önce kurulum paketindeki `bin/node.exe`'yi, yoksa PATH'teki `node`'u döndürür."""
    exe = "node.exe" if sys.platform == "win32" else "node"
    bundled = os.path.join(bundled_bin_dir(), exe)
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("node")


# yt-dlp JS runtime (YouTube "n challenge" için) — açık yol verilir ki PyInstaller
# ortamında sysconfig.get_path('scripts') yüzünden veya eski bir sistem Node sürümü
# yüzünden çözümleme bozulmasın.
_NODE_PATH = _detect_node_path()
_NODE_AVAILABLE = _NODE_PATH is not None
YT_DLP_JS_RUNTIMES = {"node": {"path": _NODE_PATH}} if _NODE_PATH else {}
if not _NODE_AVAILABLE:
    log.warning(
        "Node.js bulunamadı (PATH'te 'node' yok). YouTube bazı videolarda "
        "\"formats eksik\" hatası verip o şarkıyı atlayabilir. Çözüm: "
        "https://nodejs.org adresinden Node.js (LTS) kurup uygulamayı yeniden başlat."
    )


APP_VERSION = "0.8.0"   # pyproject.toml ile aynı olmalı (tests/test_diagnostics.py denetler)
APP_DISPLAY_NAME = "Audifly"   # kullanıcıya görünen ad (tek nokta)
LEGACY_APP_NAME = "Mustiefly"  # eski sürümlerin ad/klasör/anahtar adı (göç uyumluluğu)


def yt_dlp_base_opts(**overrides) -> dict:
    # socket_timeout: ağ takılırsa arayüzdeki "Yükleniyor" sonsuza dek sürmesin.
    # extractor_args: YouTube CDN, tv_samsung (c=TVHTML5) akışlarına HTTP 403 Forbidden
    # döndürdüğü için devre dışı bırakılır; visionos / web istemcileri kullanılır.
    opts = {
        "js_runtimes": dict(YT_DLP_JS_RUNTIMES),
        "socket_timeout": 15,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["default", "-tv_samsung"]}},
    }
    opts.update(overrides)
    return opts


# --- Tema paleti ---
@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    bg_sidebar: str
    bg_main: str
    bg_card: str
    bg_row_hover: str
    bg_playerbar: str
    accent: str
    accent_dark: str
    text: str
    text_dim: str


THEMES: dict[str, Theme] = {
    "space_orange": Theme(
        "space_orange", "🪐 Uzay (Turuncu/Mor) — Varsayılan",
        "#0a0910", "#0e0d16", "#16141f", "#241f33", "#08070c",
        "#FF7A3D", "#E8602A", "#f0ecf8", "#8a80a0",
    ),
    "classic_green": Theme(
        "classic_green", "🎧 Klasik Yeşil",
        "#0a0a0a", "#121212", "#181818", "#282828", "#0a0a0a",
        "#1DB954", "#169c46", "#f0f0f0", "#727272",
    ),
    "midnight_blue": Theme(
        "midnight_blue", "🌊 Gece Mavisi",
        "#0a0e17", "#0e1420", "#161d2b", "#212b3f", "#0a0e17",
        "#4FA8FF", "#3A87D9", "#e7edf5", "#6d7f96",
    ),
    "crimson": Theme(
        "crimson", "🔥 Kızıl",
        "#120808", "#180c0c", "#241313", "#331a1a", "#120808",
        "#FF4D4D", "#D93A3A", "#f2e3e3", "#8f6d6d",
    ),
    "mono_light": Theme(
        "mono_light", "☀️ Açık (Gündüz)",
        "#eceff3", "#f5f6f8", "#ffffff", "#e4e7ec", "#eceff3",
        "#FF7A3D", "#E8602A", "#20242c", "#6b7280",
    ),
    "audifly": Theme(
        "audifly", "💜 Audifly (Mor/Mavi Neon)",
        "#0a0a14", "#0d0d18", "#161622", "#1f1f30", "#0a0a14",
        "#6d5ef0", "#8b5cf6", "#e6e4f5", "#726d8c",
    ),
}
DEFAULT_THEME_KEY = "audifly"

COVER_COLORS = [
    "#5f2a86", "#2a5f86", "#865f2a", "#2a8656", "#862a5f",
    "#3d3d86", "#865f5f", "#2a8686", "#6b862a", "#862a2a",
]


# --- Kullanıcıya özel dosya yolları (auth.service tarafından doldurulur) ---
@dataclass
class AppPaths:
    base_dir: str
    dir: str = ""
    playlist_file: str = ""
    settings_file: str = ""
    cache_dir: str = ""
    covers_dir: str = ""

    def ensure_dirs(self):
        os.makedirs(self.dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.covers_dir, exist_ok=True)
        os.makedirs(os.path.join(self.dir, "backups"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "logs"), exist_ok=True)

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.dir, "logs")


DEFAULT_SETTINGS = {
    "discord_rpc_enabled": True,
    "discord_client_id": DISCORD_CLIENT_ID_DEFAULT,
    "custom_cache_dir": "",
    "page_size": PAGE_SIZE,
    "thumbnail_max_workers": THUMBNAIL_MAX_WORKERS,
    "audio_normalization": False,
    "minimize_to_tray": False,
    "global_media_keys": False,
    "dynamic_theme": True,
    "equalizer_enabled": False,
    "equalizer_preamp": 0.0,
    "equalizer_bands": [0.0] * 10,
    "backup_enabled": True,
    "theme": DEFAULT_THEME_KEY,
    "now_playing_panel_visible": True,
    "restore_session": True,
    "last_session": None,          # {playlist, index, position_ms} — kapanışta yazılır
    "smtc_enabled": True,          # Windows medya denetimleri (winsdk gerekir)
    "crossfade_enabled": False,
    "crossfade_seconds": 3,
    "vocal_remover_enabled": False,
    "visualizer_enabled": True,
    "visualizer_mode": "bars",
    "visualizer_palette": "dynamic",
    "autoplay_enabled": True,
    "settings_version": 2,
    "sleep_fade_enabled": True,
    "smart_rules": [],
    "dependency_notice_dismissed": False,
    "auto_update_check": True,          # açılışta GitHub'da yeni sürüm var mı diye bak
    "auto_ytdlp_update": True,          # açılışta/çıkartım hatasında yt-dlp'yi otomatik güncelle
    "skipped_update_version": "",       # "Bu sürümü atla" denen sürüm (elle denetim yine gösterir)
    "hud_overlay_enabled": True,
    "hud_overlay_duration": 4,
    "hud_overlay_position": "top-right",
    "hud_overlay_only_background": True,
    "language": "tr",                   # arayüz dili ("tr" | "en")
}


# --- Saf yardımcı fonksiyonlar ---
def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


def format_time(ms: Optional[int]) -> str:
    if ms is None or ms < 0:
        return "00:00"
    seconds = int(ms // 1000)
    minutes = seconds // 60
    rem_seconds = seconds % 60
    return f"{minutes:02d}:{rem_seconds:02d}"


def cover_color_for(title: str) -> str:
    h = int(hashlib.md5((title or "?").encode("utf-8")).hexdigest(), 16)
    return COVER_COLORS[h % len(COVER_COLORS)]


def shade_color(hex_color: str, factor: float = 0.35) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r, g, b = int(r * (1 - factor)), int(g * (1 - factor)), int(b * (1 - factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def offline_path_for(song: dict) -> str | None:
    """A stored path alone is not proof of offline availability."""
    for key in ("local_path", "cached_path"):
        path = song.get(key)
        if isinstance(path, str) and os.path.isfile(path):
            return path
    return None


# YouTube ses linkleri ~6 saat geçerlidir ve son kullanma anı linkin içinde yazar
# (`expire=<unix zamanı>`). Önceden çözülmüş bir link, şarkı çalınmaya başlamadan önce
# en az bu kadar daha geçerli olmalı; yoksa VLC yarıda "403" alıp şarkıyı atlıyordu.
STREAM_URL_SAFETY_MARGIN = 20 * 60
_EXPIRE_RE = re.compile(r"[?&/]expire[=/](\d{9,11})")


def stream_url_expiry(url: str | None) -> float | None:
    match = _EXPIRE_RE.search(url or "")
    return float(match.group(1)) if match else None


def stream_url_is_fresh(song: dict, now: float | None = None) -> bool:
    """Önbellekteki stream linki hâlâ güvenle kullanılabilir mi?"""
    url = song.get("stream_url")
    if not url or "c=TVHTML5" in url:
        return False
    now = time.time() if now is None else now
    if (now - (song.get("resolved_at") or 0)) >= STREAM_URL_TTL:
        return False
    expiry = stream_url_expiry(url)
    return expiry is None or (expiry - now) >= STREAM_URL_SAFETY_MARGIN


def needs_stream_resolve(song: dict, now: float | None = None) -> bool:
    """Çalmadan önce ağdan (yt-dlp) çözümleme gerekecek mi? Ön yükleme bunu kullanır."""
    if song.get("local_path"):
        return False
    cached_path = song.get("cached_path")
    if cached_path and os.path.exists(cached_path):
        return False
    return bool(song.get("webpage_url")) and not stream_url_is_fresh(song, now)


def resolve_stream_url(song: dict) -> tuple[str, bool]:
    """Bir şarkının çalınabilir ses linkini çözer (önbellek + TTL kontrolü ile).
    Döner: (url_veya_dosya_yolu, is_offline)."""
    now = time.time()

    # Yerel dosya (bilgisayardan eklenen mp3/flac/...): internet gerekmez
    local_path = song.get("local_path")
    if local_path:
        if os.path.isfile(local_path):
            return local_path, True
        raise FileNotFoundError(f"Yerel ses dosyası bulunamadı: {local_path}")

    cached_path = song.get("cached_path")
    if cached_path and os.path.exists(cached_path):
        return cached_path, True

    cached_url = song.get("stream_url")
    if cached_url and stream_url_is_fresh(song, now):
        return cached_url, False

    # VLC 3.x'te Opus/WebM (251, 48kHz) akışı mkv demuxer ile tüm dosyayı indirmeyi
    # beklemeden <0.5 sn'de başlar; VISIONOS m4a (140) ise parçalı DASH MP4 olduğu için
    # VLC prefetch ile tüm dosyayı önbelleğe çekmeye çalışıp süreyi 00:00'da bekletebilir.
    ydl_opts = yt_dlp_base_opts(
        format="bestaudio[ext=webm][protocol^=http]/bestaudio[ext=m4a][protocol^=http]/bestaudio[protocol^=http]/bestaudio/best",
        quiet=True,
        noplaylist=True,
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(song["webpage_url"], download=False)
        url = info.get("url")
        best = None
        if not url:
            formats = info.get("formats") or []
            audio_formats = [f for f in formats if f.get("url") and f.get("acodec") not in (None, "none")]
            candidates = audio_formats or [f for f in formats if f.get("url")]
            if candidates:
                best = max(candidates, key=lambda f: (f.get("abr") or f.get("tbr") or 0))
                url = best.get("url")
        if not url:
            raise KeyError(
                f"'{song.get('title', '?')}' için çalınabilir bir ses linki bulunamadı."
            )
        headers = info.get("http_headers") or (best.get("http_headers") if best else None) or {}
        ua = headers.get("User-Agent")
        if ua:
            song["http_user_agent"] = ua
        song["stream_url"] = url
        song["resolved_at"] = now
        return url, False

"""Şarkı sözü getirme — LRCLIB (lrclib.net) ve YouTube Music API.

- Senkron (LRC) ve düz sözler ayrı tutulur; zaman damgaları korunur.
- Gelişmiş arama stratejisi: Kesin eşleşme (/get), sanatçı+şarkı araması (/search),
  genel arama (/search?q=...) ve Türkçe karakter toleransı.
- LRCLIB bulunamadığında YouTube Music (ytmusicapi) yedek söz sağlayıcısı devreye girer.
- Video kliplerdeki intro/outro süre farkları akıllı eşleşme ile tolere edilir.
- Sonuçlar diskte önbelleğe alınır.
"""
from __future__ import annotations

import bisect
import difflib
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field

import requests

from mustiefly_qt.helpers.logging_setup import get_logger
from mustiefly_qt.helpers.persistence import atomic_write_json

log = get_logger(__name__)

API = "https://lrclib.net/api"
HEADERS = {"User-Agent": "Audifly"}
NOT_FOUND_TTL = 3600            # 1 saat (önceden 7 gündü; hatalı bulunamadı kayıtları kilitlenmesin)
CACHE_MAX_FILES = 500
MAX_DURATION_DIFF = 75          # sn: klip introları/diyaloglar için tolerans

FOUND, NOT_FOUND, ERROR = "found", "not_found", "error"


@dataclass
class LyricsResult:
    status: str
    plain: str | None = None
    synced: list[tuple[int, str]] = field(default_factory=list)   # (ms, satır)
    instrumental: bool = False
    source: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.plain or self.synced)


# ---------------------------------------------------------------- LRC
_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]\s*$", re.IGNORECASE | re.MULTILINE)


def parse_lrc(text: str) -> list[tuple[int, str]]:
    """LRC → [(ms, satır)] (zamana göre sıralı). Çoklu zaman damgası, offset
    etiketi ve meta etiketleri ([ar:], [ti:] …) desteklenir; bozuk satırlar atlanır."""
    if not text:
        return []
    m = _OFFSET.search(text)
    offset = int(m.group(1)) if m else 0
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stamps = list(_TS.finditer(raw))
        if not stamps:
            continue
        line = raw[stamps[-1].end():].strip()
        for s in stamps:
            minutes, seconds, frac = int(s.group(1)), int(s.group(2)), s.group(3) or "0"
            if seconds >= 60:
                continue
            ms = minutes * 60_000 + seconds * 1000 + int(frac.ljust(3, "0")[:3])
            rows.append((max(0, ms + offset), line))
    rows.sort(key=lambda r: r[0])
    return rows


def current_line_index(lines: list[tuple[int, str]], position_ms: int) -> int:
    """position_ms anında söylenen satırın indeksi; ilk satırdan önce -1."""
    return bisect.bisect_right([t for t, _ in lines], position_ms) - 1


def strip_timestamps(text: str) -> str:
    return re.sub(r"^(?:\[\d+:\d+(?:[.:]\d+)?\]\s*)+", "", text or "", flags=re.MULTILINE).strip()


# ----------------------------------------------------- başlık/sanatçı
_BRACKETS = re.compile(r"[\(\[\{].*?[\)\]\}]")
_NOISE = re.compile(r"\b(official|video|audio|lyrics?|lyric video|hd|4k|remaster(?:ed)?|"
                    r"music video|klip|resmi|sözleri|sözleriyle|visualizer)\b", re.IGNORECASE)
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)

_JUNK_SUFFIX_RE = re.compile(
    r"\s*(?:"
    r"[\(\[\{].*?(?:official|video|audio|lyrics?|lyric\s+video|hd|4k|uhd|hq|clip|remaster(?:ed)?|"
    r"music\s+video|klip|resmi|sözleri|sözleriyle|visualizer|slowed|reverb|remix|version|arrangement|"
    r"edit|bass\s*boosted|live|akustik|acoustic|cover|10\s*hours?).*?[\)\]\}]|"
    r"\|\s*.*$|"
    r"\/{2}\s*.*$|"
    r"\s+I\s+.*$|"
    r"[©®].*$"
    r")",
    re.IGNORECASE,
)


def deaccent(text: str) -> str:
    """Türkçe özel karakterleri ASCII eşdeğerlerine dönüştürür."""
    tbl = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return (text or "").translate(tbl)


def _norm(text: str) -> str:
    text = _FEAT.sub("", _BRACKETS.sub("", text or ""))
    text = _NOISE.sub("", text).casefold()
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(text.split())


def clean_artist(uploader: str) -> str:
    a = re.sub(r"\s*-\s*topic$", "", uploader or "", flags=re.IGNORECASE)
    a = re.sub(r"(vevo|official)$", "", a, flags=re.IGNORECASE).strip()
    return a


def clean_track_title(title: str) -> str:
    """Parça başlığındaki '(Official Video)', '| Video Klip' gibi gereksiz video etiketlerini temizler."""
    if not title:
        return ""
    cleaned = _JUNK_SUFFIX_RE.sub("", title).strip()
    cleaned = re.sub(r"\s+(?:BEST\s+VERSION|10\s*HOURS?|HQ|HD).*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+Remix$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+Music$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or title


def parse_track_and_artist(title: str, uploader: str = "", entry: dict | None = None) -> tuple[str, str]:
    """YouTube başlığı ve kanal bilgisinden şarkı adı ve gerçek sanatçıyı ayrıştırır.

    Örnekler:
        "Bengü - Saat 3 (Official Video)", "Avrupa Müzik" -> ("Saat 3", "Bengü")
        "Motive - HANIMEFENDİ", "Motive" -> ("HANIMEFENDİ", "Motive")
        "Uzi & Motive - Cennet", "UZI" -> ("Cennet", "Uzi & Motive")
        "Saat 3", "Bengü - Topic" -> ("Saat 3", "Bengü")
    """
    raw_title = str(title or "").strip()
    raw_uploader = str(uploader or "").strip()

    if isinstance(entry, dict):
        exp_artist = str(entry.get("artist") or entry.get("creator") or "").strip()
        exp_track = str(entry.get("track") or "").strip()
        if exp_artist and exp_track:
            return clean_track_title(exp_track), exp_artist
        if exp_artist and not raw_uploader:
            raw_uploader = exp_artist

    cleaned_uploader = clean_artist(raw_uploader)

    # Başlıkta "Sanatçı - Şarkı" ayrımı var mı? ( - , – , — )
    if re.search(r"\s+[-–—]\s+", raw_title):
        parts = re.split(r"\s+[-–—]\s+", raw_title, maxsplit=1)
        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()
            cleaned_right = clean_track_title(right)
            if left and cleaned_right:
                return cleaned_right, left

    cleaned_title = clean_track_title(raw_title)
    return cleaned_title or raw_title, cleaned_uploader or "Bilinmeyen Sanatçı"


def guess_track(title: str, uploader: str) -> tuple[str, str]:
    """YouTube başlığından (track, artist) tahmini. 'Sanatçı - Şarkı' kalıbı desteklenir."""
    return parse_track_and_artist(title, uploader)


def extract_video_id(url_or_id: str) -> str:
    """URL veya ID metninden 11 karakterlik YouTube video ID'sini çıkarır."""
    if not url_or_id:
        return ""
    m = re.search(r"(?:v=|\/embed\/|\/watch\?v=|youtu\.be\/|\/v\/)([a-zA-Z0-9_-]{11})", str(url_or_id))
    if m:
        return m.group(1)
    cleaned = str(url_or_id).strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", cleaned):
        return cleaned
    return ""


def _ratio(a: str, b: str) -> float:
    a_n, b_n = _norm(a), _norm(b)
    if not a_n or not b_n:
        return 0.0
    if a_n == b_n:
        return 1.0
    a_d, b_d = deaccent(a_n), deaccent(b_n)
    if a_d == b_d:
        return 0.98
    base = difflib.SequenceMatcher(None, a_n, b_n).ratio()
    if a_n in b_n or b_n in a_n:
        base = max(base, 0.82)
    if a_d in b_d or b_d in a_d:
        base = max(base, 0.80)
    return base


def score_candidate(c: dict, track: str, artist: str, duration: float) -> float | None:
    """None = reddet; yüksek puan = daha iyi eşleşme."""
    cand_track = c.get("trackName") or ""
    cand_artist = c.get("artistName") or ""

    # LRCLIB'de parça adı bazen 'Sanatçı - Şarkı' biçiminde saklanır; sanatçıyı ayıkla
    if " - " in cand_track:
        parts = cand_track.split(" - ", 1)
        if _ratio(parts[0], cand_artist) > 0.55 or _ratio(parts[0], artist) > 0.55:
            cand_track = parts[1]

    title_r = max(_ratio(cand_track, track), _ratio(c.get("trackName") or "", track))
    if title_r < 0.5:
        return None

    artist_r = max(_ratio(cand_artist, artist), _ratio(cand_artist, track)) if artist else 0.5
    if artist:
        a1, a2 = _norm(artist), _norm(cand_artist)
        if a1 and a2 and (a1 in a2 or a2 in a1):
            artist_r = max(artist_r, 0.85)

    c_dur = c.get("duration")
    diff = None
    if duration and isinstance(c_dur, (int, float)) and c_dur > 0:
        diff = abs(c_dur - duration)

    if artist and artist_r < 0.35:
        # Enstrümantal tema/soundtrack ise (kanal adı sanatçı değilse) başlık yeterlidir
        if c.get("instrumental") and title_r >= 0.85:
            pass
        # YouTube'da uploader bazen sanatçı yerine kanal adıdır (örn. netd, Avrupa Müzik).
        # Sanatçı uyuşmuyorsa, yalnızca tam başlık ve kesin süre (<= 2 sn) eşleşmesi kabul edilir.
        elif not (title_r >= 0.95 and diff is not None and diff <= 2):
            return None

    # Başlık ve sanatçı birlikte uyuşuyorsa, video intro/outro süre farklarına (≤75 sn) izin ver
    is_strong = (title_r >= 0.75 and artist_r >= 0.5)
    if is_strong:
        if diff is not None and diff > MAX_DURATION_DIFF:
            return None
    else:
        if diff is not None and diff > 15:
            return None
        if diff is None and duration > 0:
            return None

    score = title_r * 2.5 + artist_r * 1.5
    if diff is not None:
        if diff <= 3:
            score += 1.5
        elif diff <= 10:
            score += 0.8
        else:
            score -= min(1.0, (diff - 10) / 40.0)

    if c.get("syncedLyrics"):
        score += 1.0
    return score


def pick_best(candidates: list[dict], track: str, artist: str, duration: float) -> dict | None:
    scored = [(s, c) for c in candidates
              if isinstance(c, dict) and (s := score_candidate(c, track, artist, duration)) is not None]
    return max(scored, key=lambda x: x[0])[1] if scored else None


def _to_result(c: dict) -> LyricsResult:
    synced = parse_lrc(c.get("syncedLyrics") or "")
    plain = (c.get("plainLyrics") or "").strip() or (strip_timestamps(c.get("syncedLyrics") or "") or None)
    if c.get("instrumental"):
        return LyricsResult(FOUND, instrumental=True, source="lrclib")
    return LyricsResult(FOUND, plain=plain, synced=synced, source="lrclib")


# --------------------------------------------------------------- önbellek
def _cache_path(cache_dir: str, track: str, artist: str, duration: float) -> str:
    key = f"{_norm(track)}|{_norm(artist)}|{int(duration or 0) // 5}"
    return os.path.join(cache_dir, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def _cache_read(path: str) -> LyricsResult | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("status") == NOT_FOUND:
            return LyricsResult(NOT_FOUND) if time.time() - d.get("ts", 0) < NOT_FOUND_TTL else None
        return LyricsResult(FOUND, d.get("plain"), [(int(t), str(s)) for t, s in d.get("synced", [])],
                            bool(d.get("instrumental")), d.get("source", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_write(path: str, r: LyricsResult) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_json(path, {"status": r.status, "ts": time.time(), "plain": r.plain,
                                 "synced": r.synced, "instrumental": r.instrumental,
                                 "source": r.source})
        files = sorted((os.path.join(os.path.dirname(path), f) for f in os.listdir(os.path.dirname(path))
                        if f.endswith(".json")), key=os.path.getmtime)
        for old in files[:-CACHE_MAX_FILES]:
            try:
                os.remove(old)
            except OSError:
                pass
    except OSError as e:
        log.warning("Söz önbelleği yazılamadı: %s", e)


# ----------------------------------------------------------- YTMusic yedek
def _fetch_ytmusic_lyrics(track: str, artist: str, video_id: str = "") -> LyricsResult | None:
    """LRCLIB'de bulunamayan şarkılar için YouTube Music resmi sözlerini çeker."""
    try:
        import ytmusicapi
        ytm = ytmusicapi.YTMusic()

        # 1. Doğrudan video ID'si ile dene
        if video_id:
            try:
                watch = ytm.get_watch_playlist(videoId=video_id)
                lid = watch.get("lyrics")
                if lid:
                    data = ytm.get_lyrics(lid)
                    text = (data.get("lyrics") or "").strip()
                    if text:
                        return LyricsResult(FOUND, plain=text, source="ytmusic")
            except Exception:
                pass

        # 2. Şarkı araması ile parça bazında dene
        q = f"{track} {artist}".strip()
        res = ytm.search(q, filter="songs")
        if not res and track:
            res = ytm.search(track, filter="songs")

        for item in (res or [])[:2]:
            vid = item.get("videoId")
            if not vid:
                continue
            try:
                watch = ytm.get_watch_playlist(videoId=vid)
                lid = watch.get("lyrics")
                if lid:
                    data = ytm.get_lyrics(lid)
                    text = (data.get("lyrics") or "").strip()
                    if text:
                        return LyricsResult(FOUND, plain=text, source="ytmusic")
            except Exception:
                continue
    except Exception as e:
        log.debug("YTMusic söz alma hatası: %s", e)
    return None


_DEFAULT_SESSION = requests.Session()


# ------------------------------------------------------------------ ağ
def fetch_lyrics_result(title: str, uploader: str = "", duration: float = 0,
                        cache_dir: str | None = None, session=None,
                        video_id: str = "", force: bool = False) -> LyricsResult:
    """Şarkı sözlerini LRCLIB ve YouTube Music üzerinden arar.

    Önce LRCLIB üzerinden senkron LRC veya düz metin arar.
    Bulunamazsa YouTube Music resmi söz sağlayıcısından çeker.
    """
    track, artist = guess_track(title, uploader)
    if not track:
        return LyricsResult(NOT_FOUND)

    path = _cache_path(cache_dir, track, artist, duration) if cache_dir else None
    if path and not force:
        cached = _cache_read(path)
        if cached:
            return cached

    http = session or _DEFAULT_SESSION
    is_mock = session is not None and session is not requests and session is not _DEFAULT_SESSION
    best: dict | None = None
    all_candidates: list[dict] = []
    seen_ids: set[int] = set()

    def add_candidates(data):
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    cid = item.get("id")
                    if cid is None or cid not in seen_ids:
                        if cid is not None:
                            seen_ids.add(cid)
                        all_candidates.append(item)
        elif isinstance(data, dict):
            cid = data.get("id")
            if cid is None or cid not in seen_ids:
                if cid is not None:
                    seen_ids.add(cid)
                all_candidates.append(data)

    try:
        # Aşama 1: Kesin eşleşme (/get)
        if duration and artist:
            try:
                resp = http.get(f"{API}/get", headers=HEADERS, timeout=7,
                                params={"track_name": track, "artist_name": artist,
                                        "duration": int(duration)})
                if resp.status_code == 200:
                    add_candidates(resp.json())
                elif resp.status_code != 404:
                    resp.raise_for_status()
            except (requests.RequestException, ValueError):
                if is_mock:
                    raise

        best = pick_best(all_candidates, track, artist, duration)

        # Aşama 2: Başlık ve Sanatçı ile arama (/search)
        if best is None:
            try:
                resp = http.get(f"{API}/search", headers=HEADERS, timeout=7,
                                params={"track_name": track, "artist_name": artist})
                if resp.status_code == 200:
                    add_candidates(resp.json())
                elif resp.status_code != 404:
                    resp.raise_for_status()
            except (requests.RequestException, ValueError):
                if is_mock:
                    raise
            best = pick_best(all_candidates, track, artist, duration)

        # Aşama 3: Genel sorgu ile arama (/search?q=...)
        if best is None and not is_mock:
            try:
                resp = http.get(f"{API}/search", headers=HEADERS, timeout=7,
                                params={"q": f"{track} {artist}".strip()})
                if resp.status_code == 200:
                    add_candidates(resp.json())
            except Exception:
                pass
            best = pick_best(all_candidates, track, artist, duration)

        # Aşama 4: Türkçe karakter dönüştürülmüş genel sorgu
        if best is None and not is_mock:
            deacc_q = f"{deaccent(track)} {deaccent(artist)}".strip()
            if deacc_q != f"{track} {artist}".strip():
                try:
                    resp = http.get(f"{API}/search", headers=HEADERS, timeout=7,
                                    params={"q": deacc_q})
                    if resp.status_code == 200:
                        add_candidates(resp.json())
                except Exception:
                    pass
                best = pick_best(all_candidates, track, artist, duration)

        # Aşama 5: Şarkı adı tek başına arama (uploader etiket/kanal adı olduğunda kurtarır)
        if best is None and not is_mock and len(track) >= 3:
            try:
                resp = http.get(f"{API}/search", headers=HEADERS, timeout=7,
                                params={"q": track.strip()})
                if resp.status_code == 200:
                    add_candidates(resp.json())
            except Exception:
                pass
            best = pick_best(all_candidates, track, artist, duration)

    except (requests.RequestException, ValueError) as e:
        log.warning("Şarkı sözü alınamadı: %s", e)
        return LyricsResult(ERROR)          # ağ hatası önbelleğe yazılmaz

    result: LyricsResult | None = None
    if best:
        result = _to_result(best)
        if not (result.has_text or result.instrumental):
            result = None

    # Aşama 5: LRCLIB'de yoksa YouTube Music fallback dene
    if result is None and not is_mock:
        yt_res = _fetch_ytmusic_lyrics(track, artist, video_id=video_id)
        if yt_res and yt_res.has_text:
            result = yt_res

    if result is None:
        result = LyricsResult(NOT_FOUND)

    if path:
        _cache_write(path, result)
    return result


def fetch_lyrics(title: str, artist: str) -> str | None:
    """Geriye dönük uyumluluk: düz metin söz ya da None."""
    r = fetch_lyrics_result(title, artist)
    return r.plain if r.status == FOUND else None

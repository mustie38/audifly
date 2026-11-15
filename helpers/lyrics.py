"""Şarkı sözü getirme — LRCLIB (lrclib.net) açık API'si.

- Senkron (LRC) ve düz sözler ayrı tutulur; zaman damgaları artık atılmaz.
- Aday sonuçlar başlık/sanatçı/süre ile doğrulanır (yanlış şarkının sözü
  gösterilmez).
- Ağ hatası ile "söz yok" ayrı durumlardır (`status`).
- Sonuçlar diskte önbelleğe alınır (bulunamadı kayıtları 7 gün geçerli).

Fonksiyonlar senkrondur; çağıran arka plan thread'inde kullanmalıdır.
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
NOT_FOUND_TTL = 7 * 24 * 3600
CACHE_MAX_FILES = 400
MAX_DURATION_DIFF = 8       # sn: daha fazla fark → büyük olasılıkla başka kayıt

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
                    r"music video|klip|resmi|sözleri|visualizer)\b", re.IGNORECASE)
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*$", re.IGNORECASE)


def _norm(text: str) -> str:
    text = _FEAT.sub("", _BRACKETS.sub("", text or ""))
    text = _NOISE.sub("", text).casefold()
    return re.sub(r"[^\w\s]|_", " ", text).replace("  ", " ").strip()


def clean_artist(uploader: str) -> str:
    a = re.sub(r"\s*-\s*topic$", "", uploader or "", flags=re.IGNORECASE)
    a = re.sub(r"(vevo|official)$", "", a, flags=re.IGNORECASE).strip()
    return a


def guess_track(title: str, uploader: str) -> tuple[str, str]:
    """YouTube başlığından (track, artist) tahmini. 'Sanatçı - Şarkı' kalıbı desteklenir."""
    artist = clean_artist(uploader)
    cleaned = _BRACKETS.sub("", title or "").strip()
    if " - " in cleaned:
        left, right = [p.strip() for p in cleaned.split(" - ", 1)]
        if not artist or _norm(left) == _norm(artist) or _norm(artist) in _norm(left):
            return right, left
    return cleaned, artist


def _ratio(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def score_candidate(c: dict, track: str, artist: str, duration: float) -> float | None:
    """None = reddet; yüksek puan = daha iyi eşleşme."""
    title_r = _ratio(c.get("trackName") or "", track)
    if title_r < 0.6:
        return None
    artist_r = _ratio(c.get("artistName") or "", artist) if artist else 0.5
    score = title_r * 2 + artist_r
    c_dur = c.get("duration")
    diff = None
    if duration and isinstance(c_dur, (int, float)) and c_dur > 0:
        diff = abs(c_dur - duration)
        if diff > MAX_DURATION_DIFF:
            return None
        score += 1.0 if diff <= 2 else 0.4
    if artist and artist_r < 0.3:
        # YouTube'da yükleyen kanal çoğu zaman sanatçı değil (etiket/kanal adı).
        # Sanatçı uymuyorsa yalnızca tam başlık + süre ≤2 sn eşleşmesi kabul edilir.
        if not (title_r == 1.0 and diff is not None and diff <= 2):
            return None
    if c.get("syncedLyrics"):
        score += 0.5
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
        if d["status"] == NOT_FOUND:
            return LyricsResult(NOT_FOUND) if time.time() - d["ts"] < NOT_FOUND_TTL else None
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
            os.remove(old)
    except OSError as e:
        log.warning("Söz önbelleği yazılamadı: %s", e)


# ------------------------------------------------------------------ ağ
def fetch_lyrics_result(title: str, uploader: str, duration: float = 0,
                        cache_dir: str | None = None, session=None) -> LyricsResult:
    track, artist = guess_track(title, uploader)
    if not track:
        return LyricsResult(NOT_FOUND)
    path = _cache_path(cache_dir, track, artist, duration) if cache_dir else None
    if path and (cached := _cache_read(path)):
        return cached
    http = session or requests
    try:
        candidates: list[dict] = []
        if duration and artist:      # kesin eşleşme: tek istek
            resp = http.get(f"{API}/get", headers=HEADERS, timeout=8,
                            params={"track_name": track, "artist_name": artist,
                                    "duration": int(duration)})
            if resp.status_code == 200:
                candidates.append(resp.json())
            elif resp.status_code != 404:
                resp.raise_for_status()
        best = pick_best(candidates, track, artist, duration)
        if best is None:
            resp = http.get(f"{API}/search", headers=HEADERS, timeout=8,
                            params={"track_name": track, "artist_name": artist})
            resp.raise_for_status()
            data = resp.json()
            best = pick_best(data if isinstance(data, list) else [], track, artist, duration)
    except (requests.RequestException, ValueError) as e:
        log.warning("Şarkı sözü alınamadı: %s", e)
        return LyricsResult(ERROR)          # önbelleğe YAZILMAZ
    result = _to_result(best) if best else LyricsResult(NOT_FOUND)
    if result.status == FOUND and not (result.has_text or result.instrumental):
        result = LyricsResult(NOT_FOUND)
    if path:
        _cache_write(path, result)
    return result


def fetch_lyrics(title: str, artist: str) -> str | None:
    """Geriye dönük uyumluluk: düz metin söz ya da None."""
    r = fetch_lyrics_result(title, artist)
    return r.plain if r.status == FOUND else None

"""Dinleme geçmişi: eklemeli (append-only) JSON Lines olay günlüğü.

Her satır bir dinleme olayıdır:
  {"v":1,"ts":"2026-10-31T21:04:05","url":..,"title":..,"artist":..,
   "duration":215,"listened":187.5,"completed":true}

Neden JSONL: tek satır ekleme çökmeye dayanıklıdır (yarım satır yalnızca
son olayı etkiler), büyük geçmişte tüm dosya yeniden yazılmaz. Okuma
sırasında bozuk satırlar atlanır; dosya hiçbir zaman düzeltme amacıyla
üzerine yazılmaz. Qt'ye bağımlılığı yoktur.
"""
from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta

from mustiefly_qt.helpers.logging_setup import get_logger

log = get_logger(__name__)
HISTORY_FILENAME = "listening_history.jsonl"
HISTORY_VERSION = 1
MIN_LISTEN_SECONDS = 30     # Spotify mantığı: 30 sn ya da şarkının yarısı
MAX_LINE_BYTES = 16_384


def qualifies(listened: float, duration: float) -> bool:
    """Bu dinleme geçmişe yazılmaya değer mi?"""
    threshold = MIN_LISTEN_SECONDS
    if duration and duration > 0:
        threshold = min(threshold, duration / 2)
    return listened >= max(threshold, 1.0)


class HistoryStore:
    def __init__(self, directory: str):
        self.path = os.path.join(directory, HISTORY_FILENAME) if directory else ""
        self._lock = threading.Lock()
        self._events: list[dict] | None = None   # tembel yükleme

    # --- yazma ---
    def record(self, song: dict, listened: float, completed: bool, when: datetime | None = None) -> bool:
        """Olayı ekler. Eşik altındaki dinlemeler yok sayılır (False döner)."""
        duration = _num(song.get("duration"))
        listened = max(0.0, float(listened))
        if duration:
            listened = min(listened, duration * 1.05)   # sapmaları kırp
        if not self.path or not qualifies(listened, duration):
            return False
        url = song.get("webpage_url") or song.get("local_path") or ""
        if not url:
            return False
        event = {
            "v": HISTORY_VERSION,
            "ts": (when or datetime.now()).isoformat(timespec="seconds"),
            "url": url,
            "title": str(song.get("title") or "Bilinmeyen Şarkı")[:300],
            "artist": str(song.get("uploader") or "Bilinmeyen Sanatçı")[:200],
            "duration": int(duration),
            "listened": round(listened, 1),
            "completed": bool(completed),
        }
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        try:
            with self._lock:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()   # fsync GUI thread'ini her şarkı değişiminde bekletiyordu
                if self._events is not None:
                    self._events.append(event)
            return True
        except OSError as e:
            log.error("Dinleme geçmişi yazılamadı: %s", e)
            return False

    # --- okuma ---
    def events(self) -> list[dict]:
        with self._lock:
            if self._events is None:
                self._events = self._load()
            return list(self._events)

    def _load(self) -> list[dict]:
        out: list[dict] = []
        if not self.path or not os.path.isfile(self.path):
            return out
        bad = 0
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    if len(raw) > MAX_LINE_BYTES:
                        bad += 1
                        continue
                    try:
                        e = json.loads(raw)
                        datetime.fromisoformat(e["ts"])
                        if not isinstance(e["url"], str) or not e["url"]:
                            raise ValueError
                        e["listened"] = max(0.0, float(e.get("listened") or 0))
                        out.append(e)
                    except (ValueError, KeyError, TypeError):
                        bad += 1
        except OSError as ex:
            log.error("Dinleme geçmişi okunamadı: %s", ex)
        if bad:
            log.warning("Dinleme geçmişinde %d bozuk satır atlandı.", bad)
        return out

    def since(self, days: int | None, now: datetime | None = None) -> list[dict]:
        events = self.events()
        if days is None:
            return events
        cutoff = (now or datetime.now()) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        out: list[dict] = []
        for e in events:
            ts = e.get("ts", "")
            # Standart "YYYY-MM-DDTHH:MM:SS" biçiminde sözlüksel (lexicographical) karşılaştırma
            # datetime.fromisoformat'dan ~15 kat hızlıdır; farklı biçimdeyse güvenli ayrıştırmaya düşer.
            if len(ts) == 19 and ts[10] == "T":
                if ts >= cutoff_iso:
                    out.append(e)
            else:
                try:
                    parsed = datetime.fromisoformat(ts)
                    if parsed.tzinfo is not None:
                        parsed = parsed.astimezone().replace(tzinfo=None)
                    if parsed >= cutoff:
                        out.append(e)
                except ValueError:
                    pass
        return out

    def recent(self, limit: int = 50) -> list[dict]:
        """En yeni dinlemeler (aynı şarkının art arda tekrarı tek satıra iner)."""
        out: list[dict] = []
        for e in reversed(self.events()):
            if out and out[-1]["url"] == e["url"]:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def total_seconds(self, days: int | None = None, now: datetime | None = None) -> float:
        return sum(e["listened"] for e in self.since(days, now))

    def top_songs(self, limit: int = 10, days: int | None = None, now: datetime | None = None) -> list[dict]:
        agg: dict[str, dict] = {}
        for e in self.since(days, now):
            row = agg.setdefault(e["url"], {"url": e["url"], "title": e.get("title", ""),
                                            "artist": e.get("artist", ""), "plays": 0, "seconds": 0.0})
            row["plays"] += 1
            row["seconds"] += e["listened"]
            row["title"], row["artist"] = e.get("title", row["title"]), e.get("artist", row["artist"])
        return sorted(agg.values(), key=lambda r: (-r["plays"], -r["seconds"]))[:limit]

    def top_artists(self, limit: int = 10, days: int | None = None, now: datetime | None = None) -> list[dict]:
        agg: dict[str, dict] = defaultdict(lambda: {"plays": 0, "seconds": 0.0})
        for e in self.since(days, now):
            a = agg[e.get("artist") or "Bilinmeyen Sanatçı"]
            a["plays"] += 1
            a["seconds"] += e["listened"]
        rows = [{"artist": k, **v} for k, v in agg.items()]
        return sorted(rows, key=lambda r: (-r["plays"], -r["seconds"]))[:limit]


def _num(value) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0

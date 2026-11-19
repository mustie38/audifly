"""Akıllı (otomatik) çalma listeleri — saf mantık, Qt'ye bağımlılığı yok.

Girdi: (playlist_adı, index, şarkı) üçlülerinin listesi + dinleme geçmişi.
Yerleşik listeler eskisiyle aynı davranır; yenileri geçmişi kullanır.
Kullanıcı kuralları `settings["smart_rules"]` içinde saklanır ve
`sanitize_rules` ile doğrulanır (bozuk kural uygulamayı çökertmez).
"""
from __future__ import annotations

from datetime import datetime, timedelta

Ref = tuple[str, int, dict]

FORGOTTEN_DAYS = 60
FAV_ARTIST_COUNT = 5
FAV_WINDOW_DAYS = 90

BUILTIN_TITLES = {
    "most_played": "🔥 En Çok Dinlenenler",
    "recent": "🕒 Son Çalınanlar",
    "new_added": "🆕 Yeni Eklenenler",
    "forgotten": "💤 Uzun Süredir Dinlenmeyenler",
    "fav_artists": "🎤 Favori Sanatçılar",
}

RULE_LIMIT_MAX = 500
MAX_RULES = 30


def _parse(ts) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if isinstance(ts, str) and ts else None
    except ValueError:
        return None


def last_listen_map(refs: list[Ref], history=None) -> dict[str, datetime]:
    """url → son dinleme zamanı (geçmiş + eski `last_played` alanı)."""
    out: dict[str, datetime] = {}
    for _, _, s in refs:
        d = _parse(s.get("last_played"))
        k = _key(s)
        if d and k and (k not in out or d > out[k]):
            out[k] = d
    if history is not None:
        for e in history.events():
            d = _parse(e["ts"])
            if d and (e["url"] not in out or d > out[e["url"]]):
                out[e["url"]] = d
    return out


def _key(song: dict) -> str:
    return song.get("webpage_url") or song.get("local_path") or ""


def _unique_by_url(refs: list[Ref]) -> list[Ref]:
    """URL'si olan aynı şarkıyı ilk görüldüğü yerde bir kez tutar."""
    seen, unique = set(), []
    for ref in refs:
        url = ref[2].get("webpage_url")
        if url:
            if url in seen:
                continue
            seen.add(url)
        unique.append(ref)
    return unique


def build_builtin(mode: str, refs: list[Ref], history=None, now: datetime | None = None) -> list[Ref]:
    now = now or datetime.now()
    if mode == "most_played":
        out = [t for t in refs if (t[2].get("play_count") or 0) > 0]
        out.sort(key=lambda t: (t[2].get("play_count") or 0, t[2].get("last_played") or ""), reverse=True)
        return _unique_by_url(out)[:100]
    if mode == "recent":
        out = [t for t in refs if t[2].get("last_played")]
        out.sort(key=lambda t: t[2].get("last_played") or "", reverse=True)
        return _unique_by_url(out)[:100]
    if mode == "new_added":
        out = [t for t in refs if t[2].get("added_date")]
        out.sort(key=lambda t: t[2].get("added_date") or "", reverse=True)
        return _unique_by_url(out)[:50]
    if mode == "forgotten":
        return _forgotten(refs, history, now)
    if mode == "fav_artists":
        return _favorite_artists(refs, history, now)
    return []


def _forgotten(refs: list[Ref], history, now: datetime) -> list[Ref]:
    """Daha önce dinlenmiş (ya da çoktan eklenmiş) ama 60+ gündür dinlenmeyenler;
    en uzun süredir dinlenmeyen en üstte."""
    cutoff = now - timedelta(days=FORGOTTEN_DAYS)
    last = last_listen_map(refs, history)
    seen, rows = set(), []
    for t in refs:
        k = _key(t[2])
        if k in seen:
            continue
        seen.add(k)
        listened = last.get(k)
        reference = listened or _parse(t[2].get("added_date"))
        if reference is not None and reference < cutoff:
            rows.append((reference, t))
    rows.sort(key=lambda r: r[0])
    return _unique_by_url([t for _, t in rows])[:100]


def _favorite_artists(refs: list[Ref], history, now: datetime) -> list[Ref]:
    """Son 90 günde en çok dinlenen 5 sanatçının kütüphanedeki şarkıları."""
    if history is None:
        return []
    top = {r["artist"] for r in history.top_artists(FAV_ARTIST_COUNT, FAV_WINDOW_DAYS, now)}
    if not top:
        return []
    plays: dict[str, int] = {}
    for e in history.since(FAV_WINDOW_DAYS, now):
        plays[e["url"]] = plays.get(e["url"], 0) + 1
    out = [t for t in refs if (t[2].get("uploader") or "Bilinmeyen Sanatçı") in top]
    out.sort(key=lambda t: (-plays.get(_key(t[2]), 0), t[2].get("uploader") or ""))
    return _unique_by_url(out)[:100]


# --- Kullanıcı kuralları ---
_NUM_FIELDS = {          # alan → (min, max)
    "min_plays": (0, 100000), "max_plays": (0, 100000),
    "not_played_days": (1, 3650), "added_within_days": (1, 3650),
    "max_duration_min": (1, 600), "min_duration_min": (0, 600), "limit": (1, RULE_LIMIT_MAX),
}
_SORTS = {"most_played", "least_played", "newest", "oldest", "random_stable"}


def sanitize_rule(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    rule = {"name": name.strip()[:60], "liked_only": raw.get("liked_only") is True,
            "artist_contains": str(raw.get("artist_contains") or "").strip()[:100],
            "title_contains": str(raw.get("title_contains") or "").strip()[:100],
            "sort": raw.get("sort") if raw.get("sort") in _SORTS else "most_played"}
    for key, (lo, hi) in _NUM_FIELDS.items():
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            rule[key] = 0 if key != "limit" else 100
        else:
            rule[key] = int(value)
    return rule


def sanitize_rules(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    rules = [r for r in (sanitize_rule(x) for x in raw[:MAX_RULES]) if r]
    seen, unique = set(), []
    for r in rules:
        if r["name"].casefold() not in seen:
            seen.add(r["name"].casefold())
            unique.append(r)
    return unique


def apply_rule(rule: dict, refs: list[Ref], history=None, now: datetime | None = None) -> list[Ref]:
    """Kuralın TÜM koşulları sağlanmalı (0/boş = koşul yok)."""
    now = now or datetime.now()
    last = last_listen_map(refs, history)
    artist, title = rule["artist_contains"].casefold(), rule["title_contains"].casefold()
    out = []
    for t in refs:
        s = t[2]
        plays = s.get("play_count") or 0
        if rule["liked_only"] and not s.get("liked"):
            continue
        if artist and artist not in (s.get("uploader") or "").casefold():
            continue
        if title and title not in (s.get("title") or "").casefold():
            continue
        if plays < rule["min_plays"] or (rule["max_plays"] and plays > rule["max_plays"]):
            continue
        dur = (s.get("duration") or 0) / 60
        if rule["max_duration_min"] and dur > rule["max_duration_min"]:
            continue
        if rule["min_duration_min"] and dur < rule["min_duration_min"]:
            continue
        if rule["not_played_days"]:
            d = last.get(_key(s))
            if d and d >= now - timedelta(days=rule["not_played_days"]):
                continue
        if rule["added_within_days"]:
            added = _parse(s.get("added_date"))
            if not added or added < now - timedelta(days=rule["added_within_days"]):
                continue
        out.append(t)
    sort = rule["sort"]
    if sort == "most_played":
        out.sort(key=lambda t: -(t[2].get("play_count") or 0))
    elif sort == "least_played":
        out.sort(key=lambda t: t[2].get("play_count") or 0)
    elif sort in ("newest", "oldest"):
        out.sort(key=lambda t: t[2].get("added_date") or "", reverse=sort == "newest")
    else:  # random_stable: her açılışta aynı sıra (başlığa göre karma)
        out.sort(key=lambda t: hash_key(t[2]))
    return _unique_by_url(out)[:rule["limit"]]


def hash_key(song: dict) -> int:
    import hashlib
    return int(hashlib.md5(_key(song).encode()).hexdigest()[:8], 16)

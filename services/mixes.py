"""Kişiselleştirilmiş Mix'ler — tamamen yerel (harici yapay zekâ/API yok).

Girdi: kütüphane şarkıları (playlist, index, şarkı) + dinleme geçmişi.
Şarkı verisinde tür bilgisi OLMADIĞI için "tarz" türden değil, birlikte
dinleme davranışından çıkarılır: aynı oturumda (45 dk içinde) art arda
dinlenen sanatçılar aynı kümeye girer. Arayüzde bu açıkça belirtilir.

Mix'ler yalnızca kullanıcının KENDİ kütüphanesindeki şarkılardan oluşur.
"Günlük Mix" tarihe göre sabit tohumla üretilir: gün içinde aynı kalır,
ertesi gün değişir.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mustiefly_qt.helpers.lyrics import clean_artist

Ref = tuple[str, int, dict]

HALF_LIFE_DAYS = 30
SESSION_GAP = timedelta(minutes=45)
MAX_PER_ARTIST = 4
LIKED_BONUS = 2.0
UNKNOWN_ARTIST = "Bilinmeyen Sanatçı"


@dataclass
class Mix:
    id: str
    title: str
    subtitle: str
    refs: list[Ref] = field(default_factory=list)


def _key(song: dict) -> str:
    return song.get("webpage_url") or song.get("local_path") or ""


def artist_of(song: dict) -> str:
    return clean_artist(song.get("uploader") or "") or UNKNOWN_ARTIST


def _unique(refs: list[Ref]) -> list[Ref]:
    seen, out = set(), []
    for t in refs:
        k = _key(t[2])
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def song_scores(refs: list[Ref], history, now: datetime) -> dict[str, float]:
    """url → zevk puanı: zamanla sönümlenen dinlemeler (tam dinleme > yarım),
    beğeni ve eski çalma sayısı. Puanı 0 olan şarkı hiç sinyal vermemiş demektir."""
    scores: dict[str, float] = defaultdict(float)
    durations = {_key(s): s.get("duration") or 0 for _, _, s in refs}
    if history is not None:
        for e in history.events():
            try:
                age = (now - datetime.fromisoformat(e["ts"])).total_seconds() / 86400
            except ValueError:
                continue
            decay = 0.5 ** (max(age, 0) / HALF_LIFE_DAYS)
            dur = durations.get(e["url"]) or e.get("duration") or 0
            share = 1.0 if e.get("completed") else min(1.0, e["listened"] / dur) if dur else 0.5
            scores[e["url"]] += decay * share
    for _, _, s in refs:
        k = _key(s)
        scores[k] += min(s.get("play_count") or 0, 20) * 0.05    # geçmişten önceki dinlemeler
        if s.get("liked"):
            scores[k] += LIKED_BONUS
    return {k: v for k, v in scores.items() if v > 0}


def artist_affinity(refs: list[Ref], scores: dict[str, float]) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    for _, _, s in refs:
        total[artist_of(s)] += scores.get(_key(s), 0.0)
    top = max(total.values(), default=0.0)
    return {a: v / top for a, v in total.items() if v > 0 and top > 0}


def _spread(refs: list[Ref], limit: int, max_per_artist: int = MAX_PER_ARTIST) -> list[Ref]:
    """Sıralı listeden, sanatçı başına üst sınırla ve art arda aynı sanatçıyı
    mümkün olduğunca ayırarak `limit` şarkı seçer."""
    counts: Counter = Counter()
    picked: list[Ref] = []
    for t in refs:
        a = artist_of(t[2])
        if counts[a] < max_per_artist:
            counts[a] += 1
            picked.append(t)
        if len(picked) >= limit:
            break
    for i in range(1, len(picked)):                      # komşu aynı sanatçıyı ayır
        if artist_of(picked[i][2]) == artist_of(picked[i - 1][2]):
            for j in range(i + 1, len(picked)):
                if artist_of(picked[j][2]) != artist_of(picked[i - 1][2]) and (
                        i + 1 >= len(picked) or artist_of(picked[j][2]) != artist_of(picked[i + 1][2])):
                    picked[i], picked[j] = picked[j], picked[i]
                    break
    return picked


def _sana_ozel(refs, scores, affinity) -> Mix | None:
    def rank(t: Ref) -> float:
        # Kendi puanı + sevilen sanatçının henüz az dinlenmiş şarkıları da öne çıkar
        return scores.get(_key(t[2]), 0.0) + 1.5 * affinity.get(artist_of(t[2]), 0.0)
    ranked = sorted((t for t in refs if rank(t) > 0), key=rank, reverse=True)
    picked = _spread(ranked, 30)
    if len(picked) < 3:
        return None
    return Mix("sana_ozel", "Sana Özel",
               "En çok ve en son dinlediklerine, sevdiğin sanatçıların az dinlenmiş şarkılarına göre", picked)


def _gunluk_mix(refs, scores, affinity, now: datetime) -> Mix | None:
    rng = random.Random(now.strftime("%Y-%m-%d"))          # gün içinde sabit
    familiar = [t for t in refs if scores.get(_key(t[2]), 0) > 0 or affinity.get(artist_of(t[2]), 0) > 0]
    if len(familiar) < 5:
        return None
    pool = sorted(familiar, key=lambda t: scores.get(_key(t[2]), 0) + affinity.get(artist_of(t[2]), 0),
                  reverse=True)[:150]
    weights = [0.2 + scores.get(_key(t[2]), 0) + affinity.get(artist_of(t[2]), 0) for t in pool]
    chosen: list[Ref] = []
    pool, weights = list(pool), list(weights)
    while pool and len(chosen) < 22:                      # ağırlıklı, tekrarsız örnekleme
        i = rng.choices(range(len(pool)), weights=weights)[0]
        chosen.append(pool.pop(i))
        weights.pop(i)
    fresh = [t for t in refs if _key(t[2]) not in scores and t not in chosen]   # hiç sinyali olmayanlar
    rng.shuffle(fresh)
    chosen.extend(fresh[:6])
    rng.shuffle(chosen)
    return Mix("gunluk_mix", "Günlük Mix", f"{now.strftime('%d.%m.%Y')} için karışık: sevdiklerin + birkaç sürpriz",
               _spread(chosen, 28))


def listening_sessions(history, now: datetime | None = None) -> list[set[str]]:
    sessions: list[set[str]] = []
    last = None
    for e in sorted(history.events(), key=lambda e: e["ts"]) if history is not None else []:
        try:
            ts = datetime.fromisoformat(e["ts"])
        except ValueError:
            continue
        artist = clean_artist(e.get("artist") or "") or UNKNOWN_ARTIST
        if last is None or ts - last > SESSION_GAP:
            sessions.append(set())
        sessions[-1].add(artist)
        last = ts
    return sessions


def _taste_clusters(refs, scores, affinity, history) -> list[Mix]:
    co: dict[str, Counter] = defaultdict(Counter)
    for artists in listening_sessions(history):
        for a in artists:
            for b in artists:
                if a != b:
                    co[a][b] += 1
    by_artist: dict[str, list[Ref]] = defaultdict(list)
    for t in refs:
        by_artist[artist_of(t[2])].append(t)
    used: set[str] = set()
    mixes: list[Mix] = []
    for seed in sorted(affinity, key=affinity.get, reverse=True)[:8]:
        if seed in used or seed == UNKNOWN_ARTIST:
            continue
        neighbors = [a for a, n in co[seed].most_common(6) if n >= 2 and a in by_artist and a not in used][:3]
        members = [seed, *neighbors]
        songs = [t for a in members for t in by_artist.get(a, [])]
        if len(members) < 2 or len(songs) < 8:
            continue
        used.update(members)
        songs.sort(key=lambda t: scores.get(_key(t[2]), 0) + affinity.get(artist_of(t[2]), 0), reverse=True)
        mixes.append(Mix(f"tarz:{seed}", f"{seed} Tarzı",
                         f"{', '.join(members)} — aynı oturumlarda birlikte dinlediğin sanatçılar",
                         _spread(songs, 30, max_per_artist=8)))
        if len(mixes) >= 3:
            break
    return mixes


def build_mixes(refs: list[Ref], history=None, now: datetime | None = None) -> list[Mix]:
    """Boş liste = henüz yeterli sinyal yok (arayüz bunu açıklar)."""
    now = now or datetime.now()
    refs = _unique(refs)
    scores = song_scores(refs, history, now)
    if not scores:
        return []
    affinity = artist_affinity(refs, scores)
    mixes = [_sana_ozel(refs, scores, affinity), _gunluk_mix(refs, scores, affinity, now),
             *_taste_clusters(refs, scores, affinity, history)]
    return [m for m in mixes if m and m.refs]

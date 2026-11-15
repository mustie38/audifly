"""Wrapped: dinleme günlüğünden dönemlik kişisel özet (yıl sonunu beklemeden
"Son 12 ay" ya da herhangi bir takvim yılı için üretilebilir). Tamamen yerel."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from mustiefly_qt.helpers.lyrics import clean_artist

MIN_EVENTS = 10          # bundan azıyla anlamlı bir özet çıkmaz
MIN_DAYS = 3
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
          "Eylül", "Ekim", "Kasım", "Aralık"]
WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
LAST_12_MONTHS = "last12"


@dataclass
class Wrapped:
    label: str
    total_seconds: float
    plays: int
    distinct_songs: int
    distinct_artists: int
    active_days: int
    longest_streak: int
    top_songs: list[dict] = field(default_factory=list)
    top_artists: list[dict] = field(default_factory=list)
    busiest_month: str = ""
    busiest_weekday: str = ""
    daypart: str = ""
    new_artists: int = 0
    top_song_share: float = 0.0       # en çok dinlenen şarkının toplam dinlemedeki payı (%)


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def period_bounds(period, now: datetime) -> tuple[datetime, datetime, str]:
    """period: LAST_12_MONTHS ya da takvim yılı (int)."""
    if period == LAST_12_MONTHS:
        return now - timedelta(days=365), now, "Son 12 ay"
    year = int(period)
    return datetime(year, 1, 1), datetime(year + 1, 1, 1), str(year)


def available_periods(history, now: datetime | None = None) -> list:
    """Her zaman 'Son 12 ay'; ayrıca günlükte olay bulunan takvim yılları (yeniden eskiye)."""
    now = now or datetime.now()
    years = sorted({d.year for e in (history.events() if history else [])
                    if (d := _parse(e["ts"]))}, reverse=True)
    return [LAST_12_MONTHS, *years]


def longest_streak(days: set[date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best, prev = max(best, run), d
    return best


def _daypart(hour: int) -> str:
    if 5 <= hour < 12:
        return "Sabahları"
    if 12 <= hour < 17:
        return "Öğleden sonraları"
    if 17 <= hour < 22:
        return "Akşamları"
    return "Geceleri"


def build_wrapped(history, period=LAST_12_MONTHS, now: datetime | None = None) -> Wrapped | None:
    """Yeterli veri yoksa None (arayüz bunu açıklar)."""
    now = now or datetime.now()
    start, end, label = period_bounds(period, now)
    all_events = [(d, e) for e in (history.events() if history else []) if (d := _parse(e["ts"]))]
    events = [(d, e) for d, e in all_events if start <= d < end]
    days = {d.date() for d, _ in events}
    if len(events) < MIN_EVENTS or len(days) < MIN_DAYS:
        return None
    songs: dict[str, dict] = {}
    artists: dict[str, dict] = {}
    months, weekdays, hours = Counter(), Counter(), Counter()
    for d, e in events:
        artist = clean_artist(e.get("artist") or "") or "Bilinmeyen Sanatçı"
        s = songs.setdefault(e["url"], {"title": e.get("title", ""), "artist": artist, "plays": 0, "seconds": 0.0})
        s["plays"] += 1
        s["seconds"] += e["listened"]
        a = artists.setdefault(artist, {"artist": artist, "plays": 0, "seconds": 0.0})
        a["plays"] += 1
        a["seconds"] += e["listened"]
        months[d.month] += e["listened"]
        weekdays[d.weekday()] += e["listened"]
        hours[_daypart(d.hour)] += e["listened"]
    rank = lambda rows: sorted(rows, key=lambda r: (-r["plays"], -r["seconds"]))
    top_songs, top_artists = rank(songs.values()), rank(artists.values())
    earlier = {clean_artist(e.get("artist") or "") or "Bilinmeyen Sanatçı" for d, e in all_events if d < start}
    return Wrapped(
        label=label,
        total_seconds=sum(e["listened"] for _, e in events),
        plays=len(events), distinct_songs=len(songs), distinct_artists=len(artists),
        active_days=len(days), longest_streak=longest_streak(days),
        top_songs=top_songs[:5], top_artists=top_artists[:5],
        busiest_month=MONTHS[months.most_common(1)[0][0] - 1],
        busiest_weekday=WEEKDAYS[weekdays.most_common(1)[0][0]],
        daypart=hours.most_common(1)[0][0],
        new_artists=len(set(artists) - earlier),
        top_song_share=round(100 * top_songs[0]["plays"] / len(events), 1),
    )

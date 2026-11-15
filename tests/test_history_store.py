from datetime import datetime, timedelta

from mustiefly_qt.services.history_store import HistoryStore, qualifies

SONG = {"title": "A", "webpage_url": "https://y/1", "uploader": "X", "duration": 200}


def test_short_listens_are_ignored(tmp_path):
    h = HistoryStore(str(tmp_path))
    assert not h.record(SONG, 5, False)
    assert h.record(SONG, 40, False)
    assert len(h.events()) == 1
    assert qualifies(8, 15) and not qualifies(5, 15)       # kısa şarkı: yarısı yeter


def test_persists_and_survives_corrupt_lines(tmp_path):
    h = HistoryStore(str(tmp_path))
    h.record(SONG, 60, True)
    with open(h.path, "a", encoding="utf-8") as f:
        f.write("{yarım satır\n" + '{"ts":"bozuk","url":"u"}\n')
    h.record({**SONG, "webpage_url": "https://y/2", "title": "B"}, 90, False)
    fresh = HistoryStore(str(tmp_path))
    assert [e["url"] for e in fresh.events()] == ["https://y/1", "https://y/2"]


def test_stats_by_period(tmp_path):
    h = HistoryStore(str(tmp_path))
    now = datetime(2026, 10, 31, 12)
    h.record(SONG, 100, True, now - timedelta(days=40))
    h.record(SONG, 100, True, now - timedelta(days=2))
    h.record({**SONG, "webpage_url": "https://y/2", "uploader": "Y"}, 50, False, now - timedelta(days=1))
    assert h.total_seconds() == 250
    week = h.since(7, now)
    assert len(week) == 2
    assert h.top_songs(days=None)[0]["plays"] == 2
    assert h.top_artists(limit=1)[0]["artist"] == "X"


def test_recent_collapses_consecutive_repeats(tmp_path):
    h = HistoryStore(str(tmp_path))
    for _ in range(3):
        h.record(SONG, 60, True)
    h.record({**SONG, "webpage_url": "https://y/2"}, 60, True)
    assert [e["url"] for e in h.recent()] == ["https://y/2", "https://y/1"]

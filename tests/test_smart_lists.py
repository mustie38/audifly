from datetime import datetime, timedelta

import pytest

from mustiefly_qt.services import smart_lists as sl
from mustiefly_qt.services.history_store import HistoryStore

NOW = datetime(2026, 10, 31, 12)


def song(i, artist="A", **kw):
    return {"title": f"S{i}", "webpage_url": f"u{i}", "uploader": artist, "duration": 200, **kw}


def refs(*songs):
    return [("L", i, s) for i, s in enumerate(songs)]


@pytest.mark.parametrize("mode", ["most_played", "recent", "new_added"])
def test_same_song_in_two_playlists_appears_once(mode):
    track = song(1, play_count=5, last_played=NOW.isoformat(),
                 added_date=NOW.isoformat())
    rows = [("A", 0, track), ("B", 0, track)]

    assert sl.build_builtin(mode, rows, None, NOW) == [rows[0]]


def test_apply_rule_dedupes_cross_playlist():
    track = song(1, play_count=5)
    rows = [("A", 0, track), ("B", 0, track)]
    rule = sl.sanitize_rule({"name": "tekrarsız"})

    assert sl.apply_rule(rule, rows, None, NOW) == [rows[0]]


def test_forgotten_orders_oldest_first_and_skips_recent():
    r = refs(song(1, last_played=(NOW - timedelta(days=100)).isoformat()),
             song(2, last_played=(NOW - timedelta(days=10)).isoformat()),
             song(3, added_date=(NOW - timedelta(days=300)).isoformat()),   # hiç dinlenmemiş ama eski
             song(4, added_date=(NOW - timedelta(days=5)).isoformat()),
             song(5))                                                       # tarih yok → dahil değil
    out = [t[2]["webpage_url"] for t in sl.build_builtin("forgotten", r, None, NOW)]
    assert out == ["u3", "u1"]


def test_history_overrides_stale_last_played(tmp_path):
    h = HistoryStore(str(tmp_path))
    h.record(song(1), 100, True, NOW - timedelta(days=3))
    r = refs(song(1, last_played=(NOW - timedelta(days=200)).isoformat()))
    assert sl.build_builtin("forgotten", r, h, NOW) == []


def test_favorite_artists_uses_recent_history(tmp_path):
    h = HistoryStore(str(tmp_path))
    for _ in range(3):
        h.record(song(1, "Sevilen"), 100, True, NOW - timedelta(days=5))
    h.record(song(9, "Eski"), 100, True, NOW - timedelta(days=400))   # pencere dışı
    r = refs(song(1, "Sevilen"), song(2, "Sevilen"), song(3, "Başka"), song(9, "Eski"))
    # yalnız son 90 günü sayan top_artists'e göre
    out = [t[2]["webpage_url"] for t in sl.build_builtin("fav_artists", r, h, NOW)]
    assert out == ["u1", "u2"]
    assert sl.build_builtin("fav_artists", r, None, NOW) == []


def test_rule_sanitizing_rejects_garbage():
    rules = sl.sanitize_rules([{"name": "  "}, "x", {"name": "A", "limit": 10**9, "min_plays": -3,
                                                      "sort": "yok", "liked_only": "evet"},
                               {"name": "a"}, {"name": "B", "limit": 20}])
    assert [r["name"] for r in rules] == ["A", "B"]
    assert rules[0]["limit"] == 100 and rules[0]["min_plays"] == 0
    assert rules[0]["sort"] == "most_played" and rules[0]["liked_only"] is False
    assert rules[1]["limit"] == 20 and sl.sanitize_rules(None) == []


def test_rule_applies_all_conditions_and_limit():
    r = refs(song(1, "Ezhel", liked=True, play_count=9), song(2, "Ezhel", play_count=1),
             song(3, "Ceza", liked=True, play_count=5), song(4, "Ezhel", liked=True, play_count=3))
    rule = sl.sanitize_rule({"name": "x", "artist_contains": "ezh", "liked_only": True,
                             "min_plays": 2, "limit": 1})
    assert [t[2]["webpage_url"] for t in sl.apply_rule(rule, r, None, NOW)] == ["u1"]
    rule["limit"] = 10
    assert [t[2]["webpage_url"] for t in sl.apply_rule(rule, r, None, NOW)] == ["u1", "u4"]


def test_rule_time_conditions():
    r = refs(song(1, last_played=(NOW - timedelta(days=2)).isoformat(),
                  added_date=(NOW - timedelta(days=1)).isoformat()),
             song(2, last_played=(NOW - timedelta(days=50)).isoformat(),
                  added_date=(NOW - timedelta(days=90)).isoformat()))
    old = sl.sanitize_rule({"name": "o", "not_played_days": 30})
    assert [t[2]["webpage_url"] for t in sl.apply_rule(old, r, None, NOW)] == ["u2"]
    new = sl.sanitize_rule({"name": "n", "added_within_days": 7})
    assert [t[2]["webpage_url"] for t in sl.apply_rule(new, r, None, NOW)] == ["u1"]

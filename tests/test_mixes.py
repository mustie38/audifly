from datetime import datetime, timedelta

from mustiefly_qt.services import mixes
from mustiefly_qt.services.history_store import HistoryStore

NOW = datetime(2026, 10, 31, 12)


def lib(spec):
    """spec: {artist: sayı} → (playlist, idx, şarkı) listesi."""
    out, n = [], 0
    for artist, count in spec.items():
        for i in range(count):
            out.append(("L", n, {"title": f"{artist}{i}", "webpage_url": f"u{n}", "uploader": artist,
                                 "duration": 200}))
            n += 1
    return out


def listen(h, refs, artist, times, days_ago=1, minutes=0):
    songs = [t for t in refs if t[2]["uploader"] == artist]
    for i in range(times):
        s = songs[i % len(songs)][2]
        h.record(s, 180, True, NOW - timedelta(days=days_ago, minutes=-minutes - i))


def test_no_signal_gives_no_mixes(tmp_path):
    assert mixes.build_mixes(lib({"A": 10}), HistoryStore(str(tmp_path)), NOW) == []


def test_sana_ozel_prefers_recent_and_favorite_artists_with_cap(tmp_path):
    refs = lib({"Sevilen": 12, "Eski": 6, "Hiç": 6})
    h = HistoryStore(str(tmp_path))
    listen(h, refs, "Sevilen", 15, days_ago=2)
    listen(h, refs, "Eski", 15, days_ago=300)
    by_id = {m.id: m for m in mixes.build_mixes(refs, h, NOW)}
    artists = [t[2]["uploader"] for t in by_id["sana_ozel"].refs]
    assert artists[0] == "Sevilen"
    assert "Hiç" not in artists                      # sinyali olmayan sanatçı sana özel'e girmez
    assert artists.count("Sevilen") <= mixes.MAX_PER_ARTIST


def test_recent_listens_outweigh_old_ones():
    refs = lib({"A": 1, "B": 1})

    class H:
        def events(self):
            return [{"ts": (NOW - timedelta(days=1)).isoformat(), "url": "u0", "listened": 180,
                     "completed": True},
                    {"ts": (NOW - timedelta(days=200)).isoformat(), "url": "u1", "listened": 180,
                     "completed": True}]
    s = mixes.song_scores(refs, H(), NOW)
    assert s["u0"] > s["u1"] * 20


def test_daily_mix_is_stable_within_a_day_and_changes_next_day(tmp_path):
    refs = lib({"A": 15, "B": 15, "C": 15})
    h = HistoryStore(str(tmp_path))
    for a in "ABC":
        listen(h, refs, a, 10)

    def daily(now):
        return [t[2]["webpage_url"] for m in mixes.build_mixes(refs, h, now) if m.id == "gunluk_mix"
                for t in m.refs]
    assert daily(NOW) == daily(NOW + timedelta(hours=5))
    assert daily(NOW) != daily(NOW + timedelta(days=1))
    assert len(set(daily(NOW))) == len(daily(NOW))   # tekrar yok


def test_taste_clusters_come_from_co_listening_sessions(tmp_path):
    refs = lib({"Ceza": 6, "Ezhel": 6, "Sagopa": 6, "Tarkan": 10})
    h = HistoryStore(str(tmp_path))
    for day in range(4):                              # 4 ayrı oturum: rap sanatçıları birlikte
        base = NOW - timedelta(days=day + 1)
        for k, a in enumerate(["Ceza", "Ezhel", "Sagopa"]):
            h.record(next(t for t in refs if t[2]["uploader"] == a)[2], 100, True, base + timedelta(minutes=5 * k))
    for _ in range(3):
        h.record(next(t for t in refs if t[2]["uploader"] == "Tarkan")[2], 100, True, NOW - timedelta(days=10))
    cluster = [m for m in mixes.build_mixes(refs, h, NOW) if m.id.startswith("tarz:")]
    assert len(cluster) == 1
    members = {t[2]["uploader"] for t in cluster[0].refs}
    assert members == {"Ceza", "Ezhel", "Sagopa"} and "Tarkan" not in members
    assert "birlikte dinlediğin" in cluster[0].subtitle


def test_duplicates_across_playlists_collapse_and_artist_cleanup():
    refs = lib({"X - Topic": 3}) + [("Başka", 0, {"title": "dup", "webpage_url": "u0", "uploader": "X"})]
    assert len(mixes._unique(refs)) == 3
    assert mixes.artist_of({"uploader": "CezaVEVO"}) == "Ceza"


def test_mixes_view_plays_in_mix_order_and_handles_empty(library_store, tmp_path):
    from unittest.mock import MagicMock
    from mustiefly_qt.views.mixes_view import MixesView
    songs = [{"title": f"s{i}", "webpage_url": f"u{i}", "uploader": f"A{i % 3}", "duration": 200,
              "liked": True} for i in range(8)]
    library_store.playlists = {"L": songs}
    playback = MagicMock()
    playback.history = HistoryStore(str(tmp_path))
    view = MixesView(library_store, playback)
    view.refresh()
    view.play_mix("sana_ozel")
    first = playback.play_song_at_index.call_args[0]
    assert first[0] == "L"
    assert len(library_store.manual_queue) >= 2 and library_store.manual_queue[0][2]["webpage_url"] != songs[first[1]]["webpage_url"]
    library_store.playlists = {"L": []}
    view.refresh()                         # boş durum çökmemeli
    view.play_mix("yok")                   # bilinmeyen mix sessizce yok sayılır


def test_library_view_opens_mix_mode(library_store):
    from unittest.mock import MagicMock
    from mustiefly_qt.views.library_view import LibraryView
    library_store.playlists = {"L": [{"title": f"s{i}", "webpage_url": f"u{i}", "uploader": "A", "duration": 200,
                                      "liked": True} for i in range(6)]}
    playback = MagicMock()
    playback.history = None
    view = LibraryView(library_store, playback, MagicMock(), library_store.paths)
    view.show_smart("mix:sana_ozel")
    assert "Sana Özel" in view.title_label.text() and view.list_widget.count() >= 3
    view.show_smart("mix:yok")
    assert view.list_widget.count() == 1      # boş durum kartı

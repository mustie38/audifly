"""
Regression tests for comprehensive bug fixes across backend services and UI views.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest
import requests

from mustiefly_qt.helpers import lyrics as lyrics_mod
from mustiefly_qt.helpers import spotify_import as sp_mod
from mustiefly_qt.helpers.discovery import DiscoveryService
from mustiefly_qt.services import playback as pb_mod
from mustiefly_qt.services.playlist_store import PlaylistStore


def test_playlist_store_backup_recovery_persists_to_disk(library_store):
    """After recovering from backup, the recovered library must be written back to disk
    so a subsequent relaunch without edits does not lose the library."""
    app_paths = library_store.paths
    backup_dir = os.path.join(os.path.dirname(app_paths.playlist_file), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    bak1 = os.path.join(backup_dir, "playlists.bak1.json")
    saved_data = {
        "playlists": {
            "Favoriler": [{"title": "Kurtarılan Şarkı", "webpage_url": "https://youtu.be/rec1"}],
        },
        "active_playlist": "Favoriler",
        "playlist_covers": {},
    }
    with open(bak1, "w", encoding="utf-8") as f:
        json.dump(saved_data, f)

    # Corrupt primary playlist file
    with open(app_paths.playlist_file, "w", encoding="utf-8") as f:
        f.write("{corrupt json!!!")

    store1 = PlaylistStore(app_paths)
    store1.load()
    assert "Favoriler" in store1.playlists
    assert len(store1.playlists["Favoriler"]) == 1
    assert os.path.exists(app_paths.playlist_file)

    # Relaunch without any edits/save() calls
    store2 = PlaylistStore(app_paths)
    store2.load()
    assert "Favoriler" in store2.playlists
    assert store2.playlists["Favoriler"][0]["title"] == "Kurtarılan Şarkı"


def test_playback_radio_clears_song_ref_and_seek_preserves_listen_seconds(library_store, monkeypatch):
    instance = MagicMock()
    instance.media_player_new.side_effect = [MagicMock(), MagicMock()]
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: instance)
    song = {"title": "Test", "webpage_url": "https://youtu.be/s1", "duration": 200}
    library_store.playlists["Varsayılan"] = [song]

    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    try:
        engine._play_generation = 1
        engine._start_playback(1, song, "Varsayılan", 0, "https://stream.example/a", False)
        assert engine.current_song is song

        # Seek should NOT overwrite _listen["seconds"]
        engine._listen["seconds"] = 3.0
        engine.player.get_length.return_value = 200_000
        engine.seek(180_000)
        assert engine._listen["seconds"] == 3.0
        assert engine._fallback_pos_ms == 180_000

        # cycle_repeat should emit repeatChanged
        seen_modes = []
        engine.repeatChanged.connect(seen_modes.append)
        mode = engine.cycle_repeat()
        assert mode == "all"
        assert seen_modes == ["all"]

        # Starting radio should clear _current_song_ref
        ok = engine.play_radio_station({"name": "Test FM", "url": "https://radio.example/live"})
        assert ok is True
        assert engine.current_song is None
        assert engine._current_song_ref is None
    finally:
        engine.shutdown()


def test_lyrics_network_error_not_cached_as_not_found(tmp_path, monkeypatch):
    """When LRCLIB fails with network errors in production mode, return ERROR without caching."""
    cache_dir = str(tmp_path / "lyrics_cache")
    monkeypatch.setattr(lyrics_mod, "_fetch_ytmusic_lyrics", lambda *a, **k: None)

    def failing_get(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(lyrics_mod._DEFAULT_SESSION, "get", failing_get)
    res = lyrics_mod.fetch_lyrics_result("Dönence", "Barış Manço", duration=200, cache_dir=cache_dir)
    assert res.status == lyrics_mod.ERROR
    # Must NOT have written a NOT_FOUND cache file
    assert not os.path.exists(cache_dir) or os.listdir(cache_dir) == []


def test_discovery_non_dict_cache_and_non_interactive_spotify(tmp_path, monkeypatch):
    from mustiefly_qt.helpers.discovery import CACHE_FILENAME

    cache_file = tmp_path / CACHE_FILENAME
    cache_file.write_text("[]", encoding="utf-8")
    svc = DiscoveryService(cache_dir=str(tmp_path), settings={})
    assert svc.get_cached_data() is None

    # Expired refresh token with allow_interactive=False must NOT open browser
    called_interactive = []
    monkeypatch.setattr(sp_mod, "spotify_authorize_interactive", lambda *a, **k: called_interactive.append(True))

    class FakeResp:
        ok = False
        status_code = 400
        text = '{"error":"invalid_grant"}'
        def json(self):
            return {"error": "invalid_grant"}

    monkeypatch.setattr(sp_mod, "_token_request", lambda *a, **k: FakeResp())
    with pytest.raises(sp_mod.SpotifyAuthError):
        sp_mod.get_spotify_user_access_token(
            "cid", "", {"spotify_refresh_token": "expired"}, lambda: None, allow_interactive=False
        )
    assert called_interactive == []


def test_command_palette_single_execution_and_song_radio(library_store, monkeypatch):
    from mustiefly_qt.views.command_palette import CommandPaletteDialog

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    song = {"title": "Gülpembe", "uploader": "Barış Manço", "webpage_url": "https://youtu.be/g1"}
    library_store.playlists["Varsayılan"] = [song]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    engine._current_song_ref = song
    engine.playing_playlist = "Varsayılan"
    engine.current_index = 0

    fake_app = MagicMock()
    fake_app.song_radio = MagicMock()
    dlg = CommandPaletteDialog(library_store, engine, app_window=fake_app)
    try:
        # Song radio command routes to app_window.song_radio.start_radio_for_song
        dlg._cmd_start_radio()
        fake_app.song_radio.start_radio_for_song.assert_called_once_with(song)

        # Double execution guard
        calls = []
        dlg._current_matches[0].callback = lambda: calls.append(1)
        dlg.results_list.setCurrentRow(0)
        dlg._execute_current_item()
        dlg._execute_current_item()
        dlg.run_selected_callback()
        dlg.run_selected_callback()
        assert calls == [1]
    finally:
        dlg.close()
        engine.shutdown()


def test_player_bar_startup_volume_and_repeat_sync(library_store, monkeypatch):
    from mustiefly_qt.views.player_bar import PlayerBar

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {"_volume": 35})
    bar = PlayerBar(engine)
    try:
        assert bar.volume_slider.value() == 35
        engine.cycle_repeat()
        assert bar.repeat_btn._active is True
    finally:
        bar.close()
        engine.shutdown()


def test_relay_server_nan_infinity_and_ipv4_mapped_ipv6():
    import importlib.util
    from pathlib import Path

    server_path = Path(__file__).resolve().parents[1] / "relay_server" / "server.py"
    spec = importlib.util.spec_from_file_location("_audifly_relay_server_test", server_path)
    relay = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(relay)

    assert relay._clean_ms(float("nan"), 5000) == 0
    assert relay._clean_ms(float("inf"), 5000) == 0
    assert relay.clean_state({
        "seq": 1,
        "pos_ms": float("nan"),
        "song": {"title": "Test", "webpage_url": "https://youtu.be/abc123"},
    }) is None
    assert relay._normalize_ip("::ffff:10.0.0.5") == "10.0.0.5"


def test_format_playlist_duration_truncates_float_durations():
    from mustiefly_qt.helpers.covers import format_playlist_duration

    text = format_playlist_duration([{"duration": 192.456789}])
    assert text == "3 dakika 12 saniye"


def test_smart_lists_last_listen_map_keeps_newest_and_skips_empty():
    from datetime import datetime
    from mustiefly_qt.services.smart_lists import last_listen_map

    refs = [
        ("A", 0, {"webpage_url": "https://youtu.be/1", "last_played": "2026-05-10T12:00:00"}),
        ("B", 0, {"webpage_url": "https://youtu.be/1", "last_played": "2026-01-01T00:00:00"}),
        ("C", 0, {"title": "NoURL", "last_played": "2026-05-01T00:00:00"}),
    ]
    lm = last_listen_map(refs)
    assert "" not in lm
    assert lm["https://youtu.be/1"] == datetime(2026, 5, 10, 12, 0, 0)


def test_history_store_since_handles_tz_aware_timestamps(tmp_path):
    from datetime import datetime
    from mustiefly_qt.services.history_store import HISTORY_FILENAME, HistoryStore

    p = os.path.join(str(tmp_path), HISTORY_FILENAME)
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-05-15T12:00:00+03:00", "url": "https://youtu.be/1", "title": "A"}) + "\n")
    hs = HistoryStore(str(tmp_path))
    res = hs.since(30, now=datetime(2026, 5, 20, 12, 0, 0))
    assert len(res) == 1


def test_export_playlist_m3u_sanitizes_newlines(tmp_path):
    out = tmp_path / "test.m3u"
    err = sp_mod.export_playlist_m3u(
        [{"title": "Line1\nLine2", "uploader": "Art\rist", "duration": 120, "webpage_url": "https://youtu.be/1\nBAD"}],
        str(out),
    )
    assert err is None
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert "\n" not in lines[1] and "\r" not in lines[1]
    assert lines[2] == "https://youtu.be/1BAD"


def test_artist_view_album_back_navigation_and_stale_data_reset(library_store, monkeypatch):
    from mustiefly_qt.views.artist_view import ArtistDetailView

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    monkeypatch.setattr("mustiefly_qt.views.artist_view.threading.Thread", MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    view = ArtistDetailView(library_store, engine)
    try:
        view.show_artist("Sanatçı A", "UC_A")
        view._artist_data = {"songs": {"results": [{"videoId": "v1", "title": "Old"}]}}

        # Navigate to Album -> resets stale _artist_data
        view.show_album("MPREb_ALB1", "Albüm 1", "Sanatçı A")
        assert view._artist_data is None
        assert view._current_mode == "album"
        assert view._current_browse_id == "MPREb_ALB1"

        # Navigate from Album -> Sanatçı B
        view.show_artist("Sanatçı B", "UC_B")
        assert view._album_data is None
        assert view._current_mode == "artist"

        # Back -> must return to Album with exact browse_id, title, and artist_name
        view._on_back_clicked()
        assert view._current_mode == "album"
        assert view._current_browse_id == "MPREb_ALB1"
        assert view.hero_title.text() == "Albüm 1"
        assert view._current_artist == "Sanatçı A"
    finally:
        view.close()
        engine.shutdown()

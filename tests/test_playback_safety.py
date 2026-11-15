from unittest.mock import MagicMock

import pytest

from mustiefly_qt.services import playback


@pytest.fixture()
def engine(library_store, monkeypatch):
    instance = MagicMock()
    instance.media_player_new.side_effect = [MagicMock(), MagicMock()]
    monkeypatch.setattr(playback.vlc, "Instance", lambda *args: instance)
    monkeypatch.setattr(playback.PlaybackEngine, "_setup_equalizer", lambda self: None)
    e = playback.PlaybackEngine(library_store, library_store.paths, {})
    e._tick_timer.stop()
    library_store.playlists = {"A": [{"title": "First", "webpage_url": "https://youtu.be/1"},
                                    {"title": "Second", "webpage_url": "https://youtu.be/2"}]}
    yield e
    e.shutdown()


def test_stale_resolution_does_not_clear_latest_loading_state(engine):
    engine._play_generation = 2
    engine.is_loading = True
    song = engine.store.playlists["A"][0]
    engine._start_playback(1, song, "A", 0, "old-url", False)
    assert engine.is_loading
    engine.player.set_media.assert_not_called()


def test_removed_song_not_replaced_by_shifted_index(engine):
    song = engine.store.playlists["A"].pop(0)
    engine._play_generation = 1
    engine._start_playback(1, song, "A", 0, "old-url", False)
    engine.player.set_media.assert_not_called()


def test_song_moved_during_resolution_uses_current_location(engine):
    song = engine.store.playlists["A"].pop(0)
    engine.store.playlists["Moved"] = [song]
    engine._play_generation = 1
    engine._start_playback(1, song, "A", 0, "audio-url", True)
    assert engine.playing_playlist == "Moved" and engine.current_index == 0
    engine.player.play.assert_called_once()
    assert song["play_count"] == 1


def test_song_location_after_move(engine):
    song = engine.store.playlists["A"].pop(0)
    engine.store.playlists["B"] = [song]
    engine.store.playlistsChanged.emit()

    assert engine._song_index[id(song)] == ("B", 0)
    assert engine._live_song_location(song) == ("B", 0)


def test_stale_error_does_not_skip_current_song(engine):
    engine._play_generation = 2
    engine.is_loading = True
    engine._on_resolve_failed(1, engine.store.playlists["A"][0], "A", 0, "error")
    assert engine.is_loading


def test_current_error_clears_loading(engine):
    engine._play_generation = 2
    engine.is_loading = True
    engine._on_resolve_failed(2, engine.store.playlists["A"][0], "A", 0, "error")
    assert not engine.is_loading


def test_stale_crossfade_resolution_ignored(engine):
    engine._xfade_generation = 2
    engine._xfade_active = True
    engine._begin_crossfade(1, engine.store.playlists["A"][0], "A", 0, "old", False)
    engine.player_b.set_media.assert_not_called()
    assert engine._xfade_active


def test_no_crossfade_target_does_not_unpack_none(engine, monkeypatch):
    engine.settings["crossfade_enabled"] = True
    engine.playing_playlist = "A"
    engine.player.is_playing.return_value = True
    engine.player.get_length.return_value = 10000
    engine.player.get_time.return_value = 9000
    monkeypatch.setattr(engine, "_resolve_crossfade_target", lambda: None)
    engine._maybe_start_crossfade()
    assert not engine._xfade_active


def test_shutdown_releases_both_players_once_and_ignores_late_results(engine):
    first, second, instance = engine.player, engine.player_b, engine.vlc_instance
    engine.shutdown()
    engine.shutdown()
    first.release.assert_called_once()
    second.release.assert_called_once()
    instance.release.assert_called_once()
    engine._start_playback(engine._play_generation, engine.store.playlists["A"][0], "A", 0, "late", False)
    first.set_media.assert_not_called()


def test_shuffle_next_index_is_stable_until_song_changes(engine):
    engine.store.playlists["A"] = [{"title": str(i), "webpage_url": f"https://youtu.be/{i}"}
                                   for i in range(20)]
    engine.playing_playlist, engine.current_index = "A", 3
    engine.shuffle_mode = True
    first = engine.get_next_index()
    assert first != 3
    assert all(engine.get_next_index() == first for _ in range(30))  # ön yükleme = gerçek geçiş
    engine.current_index = first
    assert engine.get_next_index() != first


def test_download_without_manager_reports_instead_of_second_pipeline(engine):
    messages = []
    engine.statusMessage.connect(lambda m, lvl: messages.append(lvl))
    engine.download_song_for_offline("A", 0)
    assert messages == ["error"] and not hasattr(engine, "_download_worker")


def test_listening_history_records_real_listen_time(engine):
    songs = engine.store.playlists["A"]
    songs[0].update(duration=200, uploader="Sanatçı")
    engine._play_generation = 1
    engine._start_playback(1, songs[0], "A", 0, "url", False)
    engine._listen["seconds"] = 75.0                       # 75 sn dinlendi
    engine._play_generation = 2
    engine._start_playback(2, songs[1], "A", 1, "url2", False)   # atlama → ilki biter
    events = engine.history.events()
    assert len(events) == 1 and events[0]["artist"] == "Sanatçı"
    assert events[0]["listened"] == 75.0 and events[0]["completed"] is False
    engine._listen["seconds"] = 5.0                        # çok kısa → yazılmaz
    engine.handle_song_end()
    assert len(engine.history.events()) == 1


def test_listen_ticks_only_count_while_playing(engine, monkeypatch):
    song = engine.store.playlists["A"][0]
    engine._play_generation = 1
    engine._start_playback(1, song, "A", 0, "url", False)
    clock = iter([100.0, 100.5, 101.0, 101.5])
    monkeypatch.setattr(playback.time, "monotonic", lambda: next(clock))
    engine._listen["last"] = 99.5
    engine._tick_listen(True)      # +0.5
    engine._tick_listen(False)     # duraklatıldı: sayılmaz
    engine._tick_listen(True)      # +0.5
    assert engine._listen["seconds"] == 1.0


def test_start_playback_resets_player_before_set_media(engine):
    """set_media+play yarışı: önce stop(), sonra set_media, sonra play()."""
    engine.player.get_state.return_value = playback.vlc.State.Playing
    engine._play_generation = 1
    engine._start_playback(1, engine.store.playlists["A"][0], "A", 0, "url", False)
    names = [c[0] for c in engine.player.mock_calls if c[0] in ("stop", "set_media", "play")]
    assert names.index("stop") < names.index("set_media") < names.index("play")


def test_watchdog_restarts_song_that_did_not_start(engine):
    engine._play_generation = 1
    engine.player.get_state.return_value = playback.vlc.State.Stopped
    engine._ensure_started(1, 0)
    engine.player.play.assert_called_once()


def test_ensure_started_does_not_reset_volume(engine):
    engine._play_generation = 1
    engine.player.get_state.return_value = playback.vlc.State.Stopped

    engine._ensure_started(1, 0)

    engine.player.play.assert_called_once()
    engine.player.audio_set_volume.assert_not_called()


def test_watchdog_respects_user_pause_and_stale_generation(engine):
    engine._play_generation = 2
    engine.player.get_state.return_value = playback.vlc.State.Paused
    engine._user_paused = True
    engine._ensure_started(2, 0)
    engine.player.play.assert_not_called()
    engine._user_paused = False
    engine._ensure_started(1, 0)          # eski nesil
    engine.player.play.assert_not_called()


def test_resume_position_only_applies_to_restored_song(engine, monkeypatch):
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    engine._session_pending = True
    engine.playing_playlist, engine.current_index = "A", 0
    engine._resume_ms = 5000
    engine.play_song_at_index("A", 1)     # başka şarkı: eski saniyeye sarılmamalı
    assert engine._resume_ms == 0
    engine._session_pending = True
    engine.playing_playlist, engine.current_index = "A", 0
    engine._resume_ms = 5000
    engine.play_song_at_index("A", 0)     # aynı şarkı: devam saniyesi korunur
    assert engine._resume_ms == 5000


def test_player_error_refreshes_cached_stream_once_then_reports(engine, monkeypatch):
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    song = engine.store.playlists["A"][0]
    song.update(stream_url="http://old", resolved_at=1)
    engine.playing_playlist, engine.current_index = "A", 0
    engine._current_song_ref = song
    errors = []
    engine.playError.connect(lambda pl, i: errors.append((pl, i)))
    engine._handle_player_error()
    assert "stream_url" not in song and engine.is_loading and not errors   # link yenilenip tekrar denendi
    song.update(stream_url="http://new", resolved_at=2)
    engine.is_loading = False
    engine._handle_player_error()
    assert errors == [("A", 0)]            # ikinci hata artık bildirilir


def test_play_button_after_session_restore_keeps_saved_position(engine, monkeypatch):
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    engine._session_pending = True
    engine.playing_playlist, engine.current_index = "A", 0
    engine._resume_ms = 7000
    engine.toggle_play_pause()
    assert engine._resume_ms == 7000


def _ready_for_crossfade(engine, monkeypatch):
    engine.settings["crossfade_enabled"] = True
    engine.playing_playlist, engine.current_index = "A", 0
    engine.player.is_playing.return_value = True
    engine.player.get_length.return_value = 10000
    engine.player.get_time.return_value = 9500
    started = []
    monkeypatch.setattr(engine, "_resolve_crossfade_target", lambda: started.append(1) or (("A", 1), None))
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    return started


def test_crossfade_starts_normally(engine, monkeypatch):
    started = _ready_for_crossfade(engine, monkeypatch)
    engine._maybe_start_crossfade()
    assert started and engine._xfade_active


def test_crossfade_never_starts_for_room_guest(engine, monkeypatch):
    started = _ready_for_crossfade(engine, monkeypatch)
    engine.suppress_auto_advance = True          # Birlikte Dinle: sıradakini oda sahibi seçer
    engine._maybe_start_crossfade()
    assert not started and not engine._xfade_active


def test_crossfade_guard_blocks_and_guard_errors_fail_closed(engine, monkeypatch):
    started = _ready_for_crossfade(engine, monkeypatch)
    engine.crossfade_guard = lambda: True
    engine._maybe_start_crossfade()
    assert not started and not engine._xfade_active
    engine.crossfade_guard = lambda: 1 / 0
    engine._maybe_start_crossfade()
    assert not started and not engine._xfade_active
    engine.crossfade_guard = lambda: False
    engine._maybe_start_crossfade()
    assert started and engine._xfade_active


def test_error_retry_does_not_count_as_second_play(engine, monkeypatch):
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    song = engine.store.playlists["A"][0]
    song["play_count"] = 0
    engine.play_song_at_index("A", 0)
    engine._start_playback(engine._play_generation, song, "A", 0, "http://x", False)
    assert song["play_count"] == 1
    engine._error_retry_song = song              # _handle_player_error link yenileyip yeniden dener
    engine.play_song_at_index("A", 0)
    engine._start_playback(engine._play_generation, song, "A", 0, "http://x", False)
    assert song["play_count"] == 1


def test_failed_direct_pick_does_not_chain_skip(engine, monkeypatch):
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    played = []
    monkeypatch.setattr(engine, "play_next", lambda: played.append(1))
    messages = []
    engine.statusMessage.connect(lambda m, _l: messages.append(m))
    engine.play_song_at_index("A", 1)                    # kullanıcı doğrudan seçti
    engine.on_play_error("A", 1)
    assert not played and any("otomatik olarak" in m for m in messages)


def test_failed_auto_advance_still_skips(engine, monkeypatch):
    monkeypatch.setattr(playback.threading, "Thread", MagicMock())
    played = []
    monkeypatch.setattr(engine, "play_next", lambda: played.append(1))
    engine.play_song_at_index("A", 1, auto=True)         # sıradaki/otomatik geçiş
    engine.on_play_error("A", 1)
    assert played == [1]


def test_resolve_retries_once_on_transient_error(engine, monkeypatch):
    calls = []

    def flaky(song):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("geçici ağ hatası")
        return "http://ok", False

    monkeypatch.setattr(playback, "resolve_stream_url", flaky)
    monkeypatch.setattr(playback.time, "sleep", lambda s: None)
    ready, failed = [], []
    engine._playbackReady.connect(lambda *a: ready.append(a))
    engine._playbackFailed.connect(lambda *a: failed.append(a))
    engine._play_generation = 5
    engine._resolve_and_play(5, "A", 0, engine.store.playlists["A"][0])
    assert len(calls) == 2 and ready and not failed

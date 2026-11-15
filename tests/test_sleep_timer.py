from unittest.mock import MagicMock

import pytest

from mustiefly_qt.services import playback as pb
from mustiefly_qt.services import sleep_timer as st


@pytest.fixture()
def engine(library_store, monkeypatch):
    instance = MagicMock()
    instance.media_player_new.side_effect = [MagicMock(), MagicMock()]
    monkeypatch.setattr(pb.vlc, "Instance", lambda *a: instance)
    monkeypatch.setattr(pb.PlaybackEngine, "_setup_equalizer", lambda self: None)
    e = pb.PlaybackEngine(library_store, library_store.paths, {"_volume": 80})
    e._tick_timer.stop()
    yield e
    e.shutdown()


@pytest.fixture()
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(st.time, "monotonic", lambda: now["t"])
    return now


def test_volume_scale_never_changes_saved_volume(engine):
    engine.set_volume_scale(0.5)
    engine.player.audio_set_volume.assert_called_with(40)
    assert engine.settings["_volume"] == 80
    engine.change_volume(60)                       # fade sırasında kullanıcı sesi değiştirirse
    engine.player.audio_set_volume.assert_called_with(30)
    engine.set_volume_scale(1.0)
    engine.player.audio_set_volume.assert_called_with(60)


def test_rejects_invalid_durations(engine):
    timer = st.SleepTimer(engine)
    for bad in (0, -5, 99999, "x", None):
        assert not timer.start(bad)
    assert not timer.active


def test_fades_then_pauses_and_restores_volume(engine, clock):
    engine.pause = MagicMock()
    timer = st.SleepTimer(engine)
    finished = []
    timer.finished.connect(lambda: finished.append(1))
    assert timer.start(2, fade=True)               # 120 sn, son 30 sn fade
    clock["t"] += 60
    timer._tick()
    assert engine._volume_scale == 1.0 and timer.remaining_seconds() == 60
    clock["t"] += 45                               # 15 sn kaldı → %50
    timer._tick()
    assert engine._volume_scale == pytest.approx(0.5)
    clock["t"] += 20
    timer._tick()
    engine.pause.assert_called_once()
    assert finished == [1] and not timer.active and engine._volume_scale == 1.0


def test_no_fade_keeps_volume_and_cancel_restores(engine, clock):
    timer = st.SleepTimer(engine)
    timer.start(1, fade=False)
    clock["t"] += 50
    timer._tick()
    assert engine._volume_scale == 1.0
    engine.set_volume_scale(0.3)
    timer.cancel()
    assert not timer.active and engine._volume_scale == 1.0


def test_player_bar_menu_wiring(engine):
    from mustiefly_qt.views.player_bar import PlayerBar
    bar = PlayerBar(engine, None) if "thumbnails" in PlayerBar.__init__.__code__.co_varnames else PlayerBar(engine)
    assert bar.sleep_timer.start(15)
    assert bar.sleep_timer.active
    bar.sleep_timer.cancel()


def test_deadline_during_song_loading_waits_then_pauses(engine, clock):
    engine.pause = MagicMock()
    timer = st.SleepTimer(engine)
    assert timer.start(1, fade=False)
    clock["t"] += 61
    engine.is_loading = True                       # şarkı çözülürken süre doldu
    timer._tick()
    engine.pause.assert_not_called()
    assert timer.active and engine._volume_scale == 0.0     # sessiz bekler, yüklenince çalmaz
    clock["t"] += 5
    engine.is_loading = False                      # çalma başladı
    timer._tick()
    engine.pause.assert_called_once()
    assert not timer.active and engine._volume_scale == 1.0


def test_loading_wait_is_bounded(engine, clock):
    engine.pause = MagicMock()
    timer = st.SleepTimer(engine)
    timer.start(1, fade=False)
    engine.is_loading = True                       # hiç bitmeyen yükleme
    clock["t"] += 60 + st.MAX_LOADING_WAIT_S + 1
    timer._tick()
    engine.pause.assert_called_once()
    assert not timer.active

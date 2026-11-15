from unittest.mock import MagicMock

import pytest

from mustiefly_qt.services import discord_rpc


@pytest.fixture()
def rpc(library_store, monkeypatch):
    from PySide6.QtCore import QObject, Signal

    class FakePlayback(QObject):
        songStarted = Signal(str, int, dict, bool)
        playStateChanged = Signal(bool)
        radioStarted = Signal(dict)

    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(discord_rpc.time, "time", lambda: clock["t"])
    monkeypatch.setattr(discord_rpc, "Presence", None)           # gerçek Discord'a bağlanma
    service = discord_rpc.DiscordRPCService("123", FakePlayback())
    service._update_presence = MagicMock()
    service.clock = clock
    return service


def test_resume_keeps_elapsed_time(rpc):
    rpc._on_song_started("A", 0, {"title": "T", "uploader": "U"}, False)
    rpc.clock["t"] += 100
    rpc._on_play_state(False)                  # 100 sn sonra duraklat
    rpc.clock["t"] += 500                      # 500 sn duraklatılmış kalsın
    rpc._on_play_state(True)
    assert rpc.clock["t"] - rpc.start_time == pytest.approx(100, abs=1)


def test_new_song_resets_elapsed_and_radio_updates_presence(rpc):
    rpc._on_song_started("A", 0, {"title": "T", "uploader": "U"}, False)
    rpc.clock["t"] += 50
    rpc._on_play_state(False)
    rpc._on_song_started("A", 1, {"title": "T2", "uploader": "U"}, False)
    assert rpc._elapsed == 0.0 and rpc.start_time == int(rpc.clock["t"])
    rpc._on_radio_started({"name": "Radyo X", "country": "Türkiye"})
    assert rpc.current_song["title"] == "Radyo X" and rpc.current_song["uploader"] == "Türkiye"

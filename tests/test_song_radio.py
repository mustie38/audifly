from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtCore import QObject, Signal

from mustiefly_qt.services import song_radio
from mustiefly_qt.services.song_radio import (
    AUTOPLAY_PLAYLIST_NAME,
    RADIO_PLAYLIST_NAME,
    SongRadioService,
    extract_video_id,
    fetch_radio_recommendations,
    parse_duration_seconds,
)


def test_extract_video_id():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id({"webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}) == "dQw4w9WgXcQ"
    assert extract_video_id("https://example.com/not-youtube") is None
    assert extract_video_id(None) is None
    assert extract_video_id("") is None


def test_parse_duration_seconds():
    assert parse_duration_seconds("3:34") == 214
    assert parse_duration_seconds("0:45") == 45
    assert parse_duration_seconds("1:02:15") == 3735
    assert parse_duration_seconds(180) == 180
    assert parse_duration_seconds("gecersiz") == 0
    assert parse_duration_seconds(None) == 0


def test_fetch_radio_recommendations_with_mocked_ytmusic(monkeypatch):
    fake_tracks = [
        {
            "videoId": "seed1234567",
            "title": "Seed Title",
            "artists": [{"name": "Seed Artist"}],
            "length": "3:00",
        },
        {
            "videoId": "vid12345678",
            "title": "Song One",
            "artists": [{"name": "Artist One"}],
            "length": "3:30",
            "thumbnail": [{"url": "http://img1.jpg"}],
        },
        {
            "videoId": "vid87654321",
            "title": "Song Two",
            "artists": [{"name": "Artist Two"}],
            "length": "4:00",
            "thumbnail": [{"url": "http://img2.jpg"}],
        },
    ]

    class FakeYTMusic:
        def get_watch_playlist(self, videoId, radio=True, limit=25):
            return {"tracks": fake_tracks}

    monkeypatch.setattr(song_radio, "YTMusic", FakeYTMusic)

    seed = {
        "title": "Seed Title",
        "uploader": "Seed Artist",
        "webpage_url": "https://www.youtube.com/watch?v=seed1234567",
    }
    recs = fetch_radio_recommendations(seed, limit=10)
    assert len(recs) == 2
    assert recs[0]["title"] == "Song One"
    assert recs[0]["uploader"] == "Artist One"
    assert recs[0]["duration"] == 210
    assert recs[0]["webpage_url"] == "https://www.youtube.com/watch?v=vid12345678"
    assert recs[1]["title"] == "Song Two"


def test_start_radio_for_song(library_store, monkeypatch):
    class FakePlayback(QObject):
        songStarted = Signal(str, int, dict, bool)
        playStateChanged = Signal(bool)
        played = []

        def __init__(self):
            super().__init__()
            self.settings = {"autoplay_enabled": True}
            self.current_song = None
            self.repeat_mode = "off"
            self.autoplay_handler = None

        def play_song_at_index(self, pl, idx, auto=False):
            self.played.append((pl, idx))

        def get_next_index(self):
            return -1

    # Canlı ağ çağrısı / uzun süren yt-dlp iş parçacığını engelle (CI GC segfault'unu önler)
    monkeypatch.setattr(song_radio, "fetch_radio_recommendations", lambda *a, **kw: [])
    playback = FakePlayback()
    service = SongRadioService(library_store, playback)

    seed = {
        "title": "Bengü - Saat 3 (Official Video)",
        "uploader": "Avrupa Müzik",
        "webpage_url": "https://www.youtube.com/watch?v=seed_123",
    }

    service.start_radio_for_song(seed)

    assert RADIO_PLAYLIST_NAME in library_store.playlists
    assert library_store.playlists[RADIO_PLAYLIST_NAME][0]["webpage_url"] == "https://www.youtube.com/watch?v=seed_123"
    assert (RADIO_PLAYLIST_NAME, 0) in playback.played


def test_handle_autoplay_disabled(library_store):
    class FakePlayback(QObject):
        songStarted = Signal(str, int, dict, bool)

        def __init__(self):
            super().__init__()
            self.settings = {"autoplay_enabled": False}
            self.current_song = {"title": "X", "webpage_url": "https://youtube.com/watch?v=123"}
            self.repeat_mode = "off"
            self.autoplay_handler = None

    playback = FakePlayback()
    service = SongRadioService(library_store, playback)
    assert service.handle_autoplay() is False

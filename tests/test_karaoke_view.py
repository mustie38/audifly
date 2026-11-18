from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent

from mustiefly_qt.helpers import lyrics as ly
from mustiefly_qt.views.karaoke_view import (
    PAGE_PLAIN,
    PAGE_STATUS,
    PAGE_SYNCED,
    KaraokeView,
    _AmbientBackground,
)


@pytest.fixture
def fake_playback():
    class FakeVlcPlayer:
        def get_time(self):
            return 1500

    class FakePlayback(QObject):
        songStarted = Signal(str, int, dict, bool)
        playStateChanged = Signal(bool)
        positionChanged = Signal(int, int)

        def __init__(self):
            super().__init__()
            self.store = MagicMock()
            self.settings = {"_volume": 80}
            self.current_song = {
                "title": "Bengü - Saat 3 (Official Video)",
                "uploader": "Avrupa Müzik",
                "duration": 210,
                "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
            }
            self.is_playing = True
            self.shuffle_mode = False
            self.playing_playlist = "Favorilerim"
            self.current_index = 0
            self.player = FakeVlcPlayer()
            self.seek_calls = []
            self.play_pause_calls = 0

        def toggle_play_pause(self):
            self.play_pause_calls += 1

        def seek(self, ms):
            self.seek_calls.append(ms)

        def play_next(self):
            pass

        def play_previous(self):
            pass

        def toggle_shuffle(self):
            self.shuffle_mode = not self.shuffle_mode

        def change_volume(self, val):
            self.settings["_volume"] = val

    return FakePlayback()


def test_ambient_background_colors(qapp):
    bg = _AmbientBackground()
    bg.set_colors("#ff5500")
    assert bg._c1.name() == "#ff5500"
    assert bg._c2 is not None


def test_karaoke_view_initialization_and_sync(qapp, fake_playback, monkeypatch):
    monkeypatch.setattr(ly, "fetch_lyrics_result", lambda *args, **kwargs: ly.LyricsResult(ly.NOT_FOUND))
    view = KaraokeView(fake_playback)
    view._sync_all()
    assert view.title_label.text() == "Saat 3"
    assert view.artist_label.text() == "Bengü"
    assert view._is_playing_icon is True
    assert not view.play_btn.icon().isNull()

    # Simulate synced lyrics result
    res = ly.LyricsResult(
        status=ly.FOUND,
        synced=[(1000, "İlk satır"), (3000, "İkinci satır")],
    )
    view._apply_lyrics_result(fake_playback.current_song, view._token, res)

    assert view.stack.currentIndex() == PAGE_SYNCED
    assert view.synced_list.count() == 2
    assert view.synced_list.item(0).text() == "İlk satır"

    # Position at 1500 ms -> line 0 should be active (bold, pixelSize 28)
    view._on_position(1500, 210000)
    assert view._active_index == 0
    assert view.synced_list.item(0).font().bold() is True
    assert view.synced_list.item(0).font().pixelSize() == 28

    # Position at 3200 ms -> line 1 should be active
    view._on_position(3200, 210000)
    assert view._active_index == 1
    assert view.synced_list.item(0).font().bold() is False
    assert view.synced_list.item(1).font().bold() is True

    # Clicking on line 0 seeks to 1000ms
    view._on_line_clicked(view.synced_list.item(0))
    assert 1000 in fake_playback.seek_calls

    view.close()
    view.deleteLater()


def test_karaoke_view_plain_and_status(qapp, fake_playback, monkeypatch):
    monkeypatch.setattr(ly, "fetch_lyrics_result", lambda *args, **kwargs: ly.LyricsResult(ly.NOT_FOUND))
    view = KaraokeView(fake_playback)
    view._sync_all()

    # Plain lyrics
    plain_res = ly.LyricsResult(status=ly.FOUND, plain="Düz sözler burada")
    view._apply_lyrics_result(fake_playback.current_song, view._token, plain_res)
    assert view.stack.currentIndex() == PAGE_PLAIN
    assert view.plain_label.text() == "Düz sözler burada"

    # Instrumental
    inst_res = ly.LyricsResult(status=ly.FOUND, instrumental=True)
    view._apply_lyrics_result(fake_playback.current_song, view._token, inst_res)
    assert view.stack.currentIndex() == PAGE_STATUS
    assert "enstrümantal" in view.status_text.text().lower()

    view.close()
    view.deleteLater()


def test_karaoke_view_key_events(qapp, fake_playback, monkeypatch):
    monkeypatch.setattr(ly, "fetch_lyrics_result", lambda *args, **kwargs: ly.LyricsResult(ly.NOT_FOUND))
    view = KaraokeView(fake_playback)
    view._sync_all()

    # Space key toggles play/pause
    ev_space = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)
    view.keyPressEvent(ev_space)
    assert fake_playback.play_pause_calls == 1

    # Escape key closes
    ev_esc = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    view.keyPressEvent(ev_esc)
    assert not view.isVisible()
    view.deleteLater()

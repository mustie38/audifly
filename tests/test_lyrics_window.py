from unittest.mock import MagicMock

from mustiefly_qt.helpers import lyrics as ly
from mustiefly_qt.views.lyrics_window import PAGE_PLAIN, PAGE_STATUS, PAGE_SYNCED, LyricsWindow


def make(library_store):
    library_store.playlists = {"A": [{"title": "T", "uploader": "U", "webpage_url": "u", "duration": 100}]}
    pb = MagicMock()
    pb.store = library_store
    pb.playing_playlist, pb.current_index = "A", 0
    pb.player.get_time.return_value = 0
    return pb, LyricsWindow(pb)


def deliver(win, result):
    song = win._current_song()
    win._token += 1
    win._apply_result(song, win._token, result)


def test_synced_lyrics_highlight_follows_position_and_click_seeks(library_store):
    pb, win = make(library_store)
    deliver(win, ly.LyricsResult(ly.FOUND, "x", [(1000, "bir"), (3000, "iki"), (6000, "üç")]))
    assert win.stack.currentIndex() == PAGE_SYNCED
    win._on_position(500, 0)
    assert win._active == -1
    win._on_position(3500, 0)
    assert win._active == 1 and win.synced_list.item(1).font().bold()
    win._on_position(7000, 0)
    assert win._active == 2 and not win.synced_list.item(1).font().bold()
    win._on_line_clicked(win.synced_list.item(0))
    pb.seek.assert_called_with(1000)


def test_plain_and_empty_states(library_store):
    _, win = make(library_store)
    deliver(win, ly.LyricsResult(ly.FOUND, "düz söz"))
    assert win.stack.currentIndex() == PAGE_PLAIN and win.plain_label.text() == "düz söz"
    deliver(win, ly.LyricsResult(ly.NOT_FOUND))
    assert win.stack.currentIndex() == PAGE_STATUS and "bulunamadı" in win.status_title.text()
    assert win.retry_btn.isHidden()
    deliver(win, ly.LyricsResult(ly.ERROR))
    assert "alınamadı" in win.status_title.text() and not win.retry_btn.isHidden()
    deliver(win, ly.LyricsResult(ly.FOUND, instrumental=True))
    assert "enstrümantal" in win.status_title.text()


def test_stale_result_for_previous_song_is_ignored(library_store):
    _, win = make(library_store)
    song = win._current_song()
    win._token = 5
    win._apply_result(song, 4, ly.LyricsResult(ly.FOUND, "eski"))     # eski istek
    assert win.plain_label.text() == ""
    other = dict(song)
    win._apply_result(other, 5, ly.LyricsResult(ly.FOUND, "başka şarkı"))
    assert win.plain_label.text() == ""


def test_no_song_playing_shows_friendly_state(library_store):
    pb, win = make(library_store)
    pb.playing_playlist = None
    win.refresh()
    assert win.stack.currentIndex() == PAGE_STATUS and "çalmıyor" in win.status_title.text()


def test_closed_window_stops_listening(library_store):
    from PySide6.QtCore import QObject, Signal

    class Sig(QObject):
        songStarted = Signal(str, int, dict, bool)
        positionChanged = Signal(int, int)

    sig = Sig()
    pb, _ = make(library_store)
    pb.songStarted, pb.positionChanged = sig.songStarted, sig.positionChanged
    win = LyricsWindow(pb)
    calls = []
    win.refresh = lambda force=False: calls.append(1)
    sig.songStarted.emit("A", 0, {}, False)
    assert calls == [1]
    win.close()
    sig.songStarted.emit("A", 0, {}, False)
    assert calls == [1]

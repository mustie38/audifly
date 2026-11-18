from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from mustiefly_qt.views.artist_view import ArtistDetailView


class FakeStore(QObject):
    playlistsChanged = Signal()
    statusMessage = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.active_playlist = "Favorilerim"
        self.playlists = {
            "Favorilerim": [
                {
                    "title": "Tarkan - Dudu",
                    "uploader": "Tarkan",
                    "webpage_url": "https://www.youtube.com/watch?v=tarkan_dudu",
                    "duration": 210,
                },
                {
                    "title": "Kuzu Kuzu",
                    "uploader": "Tarkan",
                    "webpage_url": "https://www.youtube.com/watch?v=tarkan_kuzu",
                    "duration": 230,
                },
                {
                    "title": "Sertab Erener - Yanarım",
                    "uploader": "Sertab Erener",
                    "webpage_url": "https://www.youtube.com/watch?v=sertab_yanarim",
                    "duration": 190,
                },
            ]
        }

    def add_song(self, playlist_name, song):
        if playlist_name not in self.playlists:
            self.playlists[playlist_name] = []
        for s in self.playlists[playlist_name]:
            if s.get("webpage_url") == song.get("webpage_url"):
                return False
        self.playlists[playlist_name].append(song)
        self.playlistsChanged.emit()
        return True

    def save(self):
        pass


class FakePlayback(QObject):
    def __init__(self):
        super().__init__()
        self.shuffle_mode = False
        self.playing_playlist = None
        self.current_index = -1
        self.played = []

    def play_song_at_index(self, playlist_name, index):
        self.playing_playlist = playlist_name
        self.current_index = index
        self.played.append((playlist_name, index))

    def play_previous(self):
        pass

    def play_next(self):
        pass

    def toggle_play_pause(self):
        pass

    def seek(self, ms):
        pass


@pytest.fixture
def artist_view_fixture(qapp):
    store = FakeStore()
    playback = FakePlayback()
    thumbnails = MagicMock()
    thumbnails.thumbnailReady = MagicMock()
    thumbnails.thumbnailReady.connect = MagicMock()
    thumbnails.pixmap_for.return_value = None

    view = ArtistDetailView(store, playback, thumbnails)
    view._fetch_artist_remote = lambda *a, **kw: None
    view._fetch_album_remote = lambda *a, **kw: None
    return view, store, playback


def test_artist_view_initial_state(artist_view_fixture):
    view, store, playback = artist_view_fixture
    assert view._current_mode == "artist"
    assert view.hero_title.text() == "Sanatçı Adı"
    assert view.hero_tag.text() == "SANATÇI"


def test_show_artist_filters_library_songs(artist_view_fixture):
    view, store, playback = artist_view_fixture

    view.show_artist("Tarkan")
    assert view.hero_title.text() == "Tarkan"
    assert "Kütüphanende 2 şarkı" in view.hero_sub.text()

    # Sertab Erener için test
    view.show_artist("Sertab Erener")
    assert view.hero_title.text() == "Sertab Erener"
    assert "Kütüphanende 1 şarkı" in view.hero_sub.text()


def test_apply_artist_data(artist_view_fixture):
    view, store, playback = artist_view_fixture
    view.show_artist("Tarkan")
    token = view._token

    mock_data = {
        "subscribers": "1.2M",
        "thumbnails": [{"url": "http://img/tarkan.jpg"}],
        "songs": {
            "results": [
                {
                    "title": "Şımarık",
                    "videoId": "simarik123",
                    "duration_seconds": 195,
                    "thumbnails": [{"url": "http://img/simarik.jpg"}],
                }
            ]
        },
        "albums": {
            "results": [
                {
                    "title": "Karma",
                    "browseId": "MPREb_karma",
                    "year": "2001",
                    "thumbnails": [{"url": "http://img/karma.jpg"}],
                }
            ]
        },
        "related": {
            "results": [
                {
                    "title": "Mustafa Sandal",
                    "browseId": "UC_sandal",
                    "thumbnails": [{"url": "http://img/sandal.jpg"}],
                }
            ]
        },
    }

    assert view.loading_label is not None
    view.artistDataReady.emit(token, "Tarkan", mock_data)
    assert "1.2M Abone" in view.hero_sub.text()
    assert view._artist_data == mock_data
    assert view.loading_label is None


def test_show_album_and_apply_data(artist_view_fixture):
    view, store, playback = artist_view_fixture

    view.show_album("MPREb_karma", "Karma", "Tarkan")
    assert view._current_mode == "album"
    assert view.hero_tag.text() == "ALBÜM"
    assert view.hero_title.text() == "Karma"
    assert not view.add_album_btn.isHidden()
    assert view.radio_btn.isHidden()

    token = view._token
    album_mock = {
        "title": "Karma",
        "year": "2001",
        "tracks": [
            {"title": "A-Acayipsin", "videoId": "vid_acayip", "duration_seconds": 210},
            {"title": "Kuzu Kuzu", "videoId": "vid_kuzu", "duration_seconds": 230},
        ],
        "thumbnails": [{"url": "http://img/karma.jpg"}],
    }

    view._apply_album_data(token, album_mock, "Tarkan")
    assert "2001" in view.hero_sub.text()
    assert "2 Şarkı" in view.hero_sub.text()


def test_navigation_back_stack(artist_view_fixture):
    view, store, playback = artist_view_fixture

    back_requested = False
    def on_back():
        nonlocal back_requested
        back_requested = True

    view.backRequested.connect(on_back)

    # 1. Sanatçı: Tarkan
    view.show_artist("Tarkan")
    # 2. Albüm: Karma
    view.show_album("MPREb_karma", "Karma", "Tarkan")
    assert view._current_mode == "album"
    assert len(view._nav_stack) == 1

    # Geri tıkla -> Tarkan'a dönmeli
    view._on_back_clicked()
    assert view._current_mode == "artist"
    assert view.hero_title.text() == "Tarkan"
    assert len(view._nav_stack) == 0

    # Tekrar geri tıkla -> backRequested sinyali yayılmalı
    view._on_back_clicked()
    assert back_requested

    # Esc tuşuna basınca da geri tetiklenmeli
    back_requested = False
    from PySide6.QtGui import QKeyEvent
    esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    view.keyPressEvent(esc_event)
    assert back_requested


def test_quick_actions(artist_view_fixture):
    view, store, playback = artist_view_fixture

    # Sanatçı modunda Tümünü Çal
    view.show_artist("Tarkan")
    view._on_play_all()
    assert playback.playing_playlist == "Sanatçı: Tarkan"
    assert playback.current_index == 0

    # Karışık Çal
    view._on_shuffle_all()
    assert playback.shuffle_mode is True

    # Sanatçı Radyosu
    radio_seed = None
    def on_radio(seed):
        nonlocal radio_seed
        radio_seed = seed
    view.startRadioRequested.connect(on_radio)
    view._on_start_radio()
    assert radio_seed is not None
    assert radio_seed.get("title") == "Tarkan"

    # Albüm modunda Playlist Olarak Kaydet
    view.show_album("MPREb_karma", "Karma", "Tarkan")
    view._album_data = {
        "title": "Karma",
        "tracks": [
            {"title": "Kuzu Kuzu", "videoId": "kuzu123", "duration_seconds": 230}
        ]
    }
    view._on_save_album_as_playlist()
    assert "Albüm: Karma" in store.playlists
    assert len(store.playlists["Albüm: Karma"]) == 1


def test_song_row_artist_navigation(qapp):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt, QPointF
    from mustiefly_qt.widgets.song_row import SongRow

    song = {
        "title": "Kuzu Kuzu",
        "uploader": "Tarkan",
        "webpage_url": "https://www.youtube.com/watch?v=kuzu",
    }
    row = SongRow(0, song, show_uploader=True)
    clicked_artist = None

    def on_artist(art):
        nonlocal clicked_artist
        clicked_artist = art

    row.artistRequested.connect(on_artist)

    # uploader label'a sol tıklama simülasyonu
    uploader_lbl = None
    from PySide6.QtWidgets import QLabel
    for lbl in row.findChildren(QLabel):
        if lbl.text() == "Tarkan":
            uploader_lbl = lbl
            break

    assert uploader_lbl is not None
    # mousePressEvent doğrudan çağırılır
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    uploader_lbl.mousePressEvent(event)
    assert clicked_artist == "Tarkan"


def test_player_bar_artist_navigation(qapp):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import Qt, QPointF
    from mustiefly_qt.views.player_bar import PlayerBar

    playback = FakePlayback()
    playback.settings = {"_volume": 80}
    playback.change_volume = MagicMock()
    playback.volumeChanged = MagicMock()
    playback.songLoading = MagicMock()
    playback.songStarted = MagicMock()
    playback.playStateChanged = MagicMock()
    playback.positionChanged = MagicMock()
    playback.playError = MagicMock()
    playback.shuffleChanged = MagicMock()
    playback.radioStarted = MagicMock()
    playback.radioStopped = MagicMock()
    playback.store = FakeStore()

    bar = PlayerBar(playback)
    clicked_artist = None

    def on_artist(art):
        nonlocal clicked_artist
        clicked_artist = art

    bar.artistClicked.connect(on_artist)

    song = {"title": "Dudu", "uploader": "Tarkan", "webpage_url": "url1"}
    bar._set_current_song(song)

    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    bar.now_sub_label.mousePressEvent(event)
    assert clicked_artist == "Tarkan"


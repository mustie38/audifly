from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent

from mustiefly_qt.views.karaoke_view import KaraokeView
from mustiefly_qt.views.now_playing_panel import NowPlayingPanel
from mustiefly_qt.widgets.audio_visualizer import (
    MODE_LABELS,
    PALETTES,
    VISUALIZER_MODES,
    NeonAudioVisualizer,
    _complementary_neon,
)
from mustiefly_qt.widgets.waveform_strip import WaveformStrip


@pytest.fixture
def fake_playback():
    class FakePlayback(QObject):
        songStarted = Signal(str, int, dict, bool)
        songLoading = Signal(str, int, dict)
        playStateChanged = Signal(bool)
        positionChanged = Signal(int, int)
        playError = Signal(str, int)
        shuffleChanged = Signal(bool)
        radioStarted = Signal(dict)
        radioStopped = Signal()
        volumeChanged = Signal(int)
        vocalRemoverChanged = Signal(bool)

        def __init__(self):
            super().__init__()
            self.store = MagicMock()
            self.store.paths.dir = "."
            self.store.playlists = {"Favorilerim": [{"title": "Test Song", "liked": False}]}
            self.settings = {
                "_volume": 85,
                "_rate": 1.0,
                "vocal_remover_enabled": False,
                "visualizer_enabled": True,
                "visualizer_mode": "bars",
                "visualizer_palette": "dynamic",
            }
            self.current_song = {"title": "Test Song", "duration": 180}
            self.is_playing = False
            self.shuffle_mode = False
            self.playing_playlist = "Favorilerim"
            self.current_index = 0
            self.radio_playing = None
            self.player = MagicMock()
            self.player.get_time.return_value = 12000

        @property
        def vocal_remover_enabled(self) -> bool:
            return bool(self.settings.get("vocal_remover_enabled", False))

        def toggle_vocal_remover(self):
            val = not self.vocal_remover_enabled
            self.settings["vocal_remover_enabled"] = val
            self.vocalRemoverChanged.emit(val)
            return val

        def toggle_play_pause(self):
            self.is_playing = not self.is_playing
            self.playStateChanged.emit(self.is_playing)

        def play_next(self):
            pass

        def play_previous(self):
            pass

        def toggle_shuffle(self):
            pass

        def seek(self, ms):
            pass

    return FakePlayback()


def test_complementary_neon_colors():
    c1, c2 = _complementary_neon("#a980f9")
    assert c1.isValid() and c2.isValid()
    assert c1.rgb() != c2.rgb()


def test_neon_audio_visualizer_modes_and_palettes(qapp, fake_playback):
    viz = NeonAudioVisualizer(playback=fake_playback, accent="#ff2a85", mode="bars", palette="dynamic")
    viz.resize(320, 90)
    viz.show()

    modes_seen = []
    pals_seen = []
    viz.modeChanged.connect(modes_seen.append)
    viz.paletteChanged.connect(pals_seen.append)

    # Başlangıçta duruyor -> zamanlayıcı kapalı
    assert not viz._timer.isActive()

    # Çalmaya başlayınca zamanlayıcı aktifleşmeli
    fake_playback.playStateChanged.emit(True)
    assert viz._timer.isActive()

    # Tüm modları tek tek dolaş ve çizim (grab) hatası olmadığını doğrula
    for expected_mode in ("wave", "mirror", "circular", "bars"):
        res = viz.cycle_mode(include_off=False)
        assert res == expected_mode
        assert viz.mode == expected_mode
        viz._tick()
        pm = viz.grab()
        assert not pm.isNull()

    assert modes_seen == ["wave", "mirror", "circular", "bars"]

    # Renk paletlerini dolaş
    for pal_key in PALETTES:
        viz.set_palette(pal_key)
        assert viz.palette_name == pal_key
        pm = viz.grab()
        assert not pm.isNull()

    # Sol tıklama ile mod geçişi
    click = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    viz.mousePressEvent(click)
    assert viz.mode == "wave"

    # Gizlendiğinde zamanlayıcı durmalı (performans garantisi)
    viz.hide()
    assert not viz._timer.isActive()
    viz.close()


def test_waveform_strip_neon_palettes_and_enable(qapp):
    strip = WaveformStrip("#a980f9")
    strip.resize(400, 20)
    strip.show()
    strip.set_playing(True)
    assert strip._timer.isActive()

    strip.set_palette("cyberpunk")
    strip._tick()
    pm = strip.grab()
    assert not pm.isNull()

    strip.set_enabled_state(False)
    assert not strip._timer.isActive()

    strip.set_enabled_state(True)
    assert strip._timer.isActive()
    strip.close()


def test_now_playing_panel_visualizer_integration(qapp, fake_playback):
    panel = NowPlayingPanel(fake_playback.store, fake_playback, None)
    assert hasattr(panel, "visualizer")
    assert panel.visualizer.mode == "bars"
    assert "Barlar" in panel.viz_mode_btn.text()

    # Mod değiştirme butonuna tıklama
    panel.viz_mode_btn.click()
    assert panel.visualizer.mode == "wave"
    assert "Dalga" in panel.viz_mode_btn.text()

    # Devre dışı bırakma
    panel.set_visualizer_enabled(False)
    assert not panel.visualizer_section.isVisible()


def test_karaoke_view_visualizer_button_and_shortcut(qapp, fake_playback):
    view = KaraokeView(fake_playback, None)
    assert hasattr(view, "visualizer")
    assert hasattr(view, "viz_btn")
    assert view.visualizer.mode == "bars"

    # Butona tıklayarak mod değiştir
    view.viz_btn.click()
    assert view.visualizer.mode == "wave"
    assert "Dalga" in view.viz_btn.text()

    # 'G' kısayol tuşu ile mod değiştir
    key_event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_G, Qt.NoModifier)
    view.keyPressEvent(key_event)
    assert view.visualizer.mode == "mirror"
    assert "Simetrik" in view.viz_btn.text()
    view.close()

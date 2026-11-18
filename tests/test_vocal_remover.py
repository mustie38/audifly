from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.views.equalizer_window import EqualizerWindow
from mustiefly_qt.views.karaoke_view import KaraokeView
from mustiefly_qt.views.now_playing_panel import NowPlayingPanel
from mustiefly_qt.views.player_bar import PlayerBar


@pytest.fixture
def fake_playback_engine():
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
            self.store.playlists = {"Favorilerim": [{"title": "Test Song", "liked": False}]}
            self.settings = {
                "_volume": 80,
                "vocal_remover_enabled": False,
                "audio_normalization": False,
                "crossfade_enabled": False,
                "crossfade_seconds": 3,
            }
            self.current_song = {"title": "Test Song", "duration": 180}
            self.is_playing = False
            self.shuffle_mode = False
            self.playing_playlist = "Favorilerim"
            self.current_index = 0
            self.radio_playing = None
            self.eq_band_count = 10
            self.eq_preset_names = ["Flat", "Rock", "Pop"]
            player_mock = MagicMock()
            player_mock.get_time.return_value = 45000
            self.player = player_mock

        @property
        def vocal_remover_enabled(self) -> bool:
            return bool(self.settings.get("vocal_remover_enabled", False))

        def toggle_vocal_remover(self) -> bool:
            new_val = not self.vocal_remover_enabled
            self.set_vocal_remover(new_val)
            return new_val

        def set_vocal_remover(self, enabled: bool):
            self.settings["vocal_remover_enabled"] = bool(enabled)
            self.vocalRemoverChanged.emit(bool(enabled))

        def change_volume(self, val):
            self.settings["_volume"] = val
            self.volumeChanged.emit(val)

        def toggle_play_pause(self):
            self.is_playing = not self.is_playing
            self.playStateChanged.emit(self.is_playing)

        def play_next(self):
            pass

        def play_previous(self):
            pass

        def toggle_shuffle(self):
            self.shuffle_mode = not self.shuffle_mode
            self.shuffleChanged.emit(self.shuffle_mode)
            return self.shuffle_mode

        def cycle_repeat(self):
            return "all"

        def seek(self, ms):
            pass

    return FakePlayback()


def test_prepare_media_filter_options(monkeypatch):
    from mustiefly_qt.services import playback as pb_mod
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    store = MagicMock()
    paths = MagicMock()
    settings = {"vocal_remover_enabled": False, "audio_normalization": False}

    engine = PlaybackEngine(store, paths, settings)
    try:
        # 1. Her ikisi de kapalıyken
        assert engine.vocal_remover_enabled is False

        # 2. Sadece vokal ayırma açık
        settings["vocal_remover_enabled"] = True
        assert engine.vocal_remover_enabled is True

        # 3. Gerçek media_new ile normalizasyon ve User-Agent testleri
        with patch.object(engine.vlc_instance, "media_new") as mock_new:
            mock_media = MagicMock()
            mock_new.return_value = mock_media

            # Normalizasyon açıkken normvol filtresi eklenmeli
            settings["audio_normalization"] = True
            engine._prepare_media("https://cdn.example.com/stream.mp3", {"http_user_agent": "Mozilla/5.0"})
            mock_media.add_option.assert_any_call(":audio-filter=normvol")
            mock_media.add_option.assert_any_call(":http-user-agent=Mozilla/5.0")

            # Normalizasyon kapalıyken audio-filter eklenmemeli
            mock_media.reset_mock()
            settings["audio_normalization"] = False
            engine._prepare_media("dummy")
            added_options = [c[0][0] for c in mock_media.add_option.call_args_list]
            assert not any(":audio-filter" in opt for opt in added_options)
    finally:
        engine.shutdown()


def test_playback_engine_vocal_remover_equalizer(monkeypatch):
    from mustiefly_qt.services import playback as pb_mod
    fake_inst = MagicMock()
    fake_inst.media_player_new.side_effect = [MagicMock(), MagicMock()]
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: fake_inst)
    monkeypatch.setattr(pb_mod.vlc, "AudioEqualizer", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pb_mod.vlc, "libvlc_audio_equalizer_get_band_count", lambda: 10, raising=False)
    monkeypatch.setattr(pb_mod.vlc, "libvlc_audio_equalizer_get_preset_count", lambda: 0, raising=False)
    store = MagicMock()
    paths = MagicMock()
    settings = {"vocal_remover_enabled": False}

    engine = PlaybackEngine(store, paths, settings)
    try:
        with patch.object(engine.player, "set_equalizer") as mock_set_eq, \
             patch.object(engine.player_b, "set_equalizer") as mock_set_eq_b:
            # Vokal bastırma açıldığında ekolayzer atanmalı
            engine.set_vocal_remover(True)
            assert engine.vocal_remover_enabled is True
            mock_set_eq.assert_called()
            eq_arg = mock_set_eq.call_args[0][0]
            assert eq_arg is not None

            # Kapatıldığında ekolayzer temizlenmeli (user eq yokken None)
            engine.set_vocal_remover(False)
            assert engine.vocal_remover_enabled is False
            mock_set_eq.assert_called_with(None)
    finally:
        engine.shutdown()


def test_playback_engine_vocal_remover_toggle_and_live_update(monkeypatch):
    from mustiefly_qt.services import playback as pb_mod
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pb_mod.vlc, "AudioEqualizer", lambda *a, **k: MagicMock())
    store = MagicMock()
    paths = MagicMock()
    settings = {"vocal_remover_enabled": False}

    engine = PlaybackEngine(store, paths, settings)
    try:
        emitted = []
        engine.vocalRemoverChanged.connect(emitted.append)

        # Başlangıçta kapalı
        assert engine.vocal_remover_enabled is False

        # Aç
        engine.set_vocal_remover(True)
        assert engine.vocal_remover_enabled is True
        assert emitted == [True]

        # Tekrar aynı değere ayarlanırsa sinyal tekrar yayılmaz (idempotent)
        engine.set_vocal_remover(True)
        assert len(emitted) == 1

        # Toggle ile kapat
        res = engine.toggle_vocal_remover()
        assert res is False
        assert engine.vocal_remover_enabled is False
        assert emitted == [True, False]
    finally:
        engine.shutdown()


def test_equalizer_window_vocal_remover_integration(qapp, fake_playback_engine):
    saved = []
    win = EqualizerWindow(fake_playback_engine, fake_playback_engine.settings, lambda: saved.append(1))

    assert win.vocal_check.isChecked() is False

    # Checkbox tıklandığında playback'e aktarılmalı
    win.vocal_check.setChecked(True)
    assert fake_playback_engine.vocal_remover_enabled is True
    assert fake_playback_engine.settings["vocal_remover_enabled"] is True

    # Playback'ten sinyal geldiğinde checkbox güncellenmeli
    fake_playback_engine.set_vocal_remover(False)
    assert win.vocal_check.isChecked() is False


def test_karaoke_view_vocal_remover_button_and_shortcut(qapp, fake_playback_engine):
    view = KaraokeView(fake_playback_engine, None)

    # Başlangıçta orijinal ses
    assert "Açık" in view.vocal_btn.text()

    # Butona tıklama
    view.vocal_btn.click()
    assert fake_playback_engine.vocal_remover_enabled is True
    assert "Enstrümantal" in view.vocal_btn.text()

    # Kısayol 'V' tuşuna basma
    key_event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_V, Qt.NoModifier)
    view.keyPressEvent(key_event)
    assert fake_playback_engine.vocal_remover_enabled is False
    assert "Açık" in view.vocal_btn.text()


def test_player_bar_vocal_remover_button(qapp, fake_playback_engine):
    bar = PlayerBar(fake_playback_engine, None, "#a980f9")

    assert bar.vocal_btn._active is False
    assert "Enstrümantal" in bar.vocal_btn.toolTip()

    # Butona tıklama
    bar.vocal_btn.click()
    assert fake_playback_engine.vocal_remover_enabled is True
    assert bar.vocal_btn._active is True
    assert "Vokal Kısık" in bar.vocal_btn.toolTip()


def test_now_playing_panel_vocal_remover_button(qapp, fake_playback_engine):
    panel = NowPlayingPanel(fake_playback_engine.store, fake_playback_engine, None)

    assert panel.vocal_btn is not None
    # Başlangıçta inaktif
    assert "qlineargradient" not in panel.vocal_btn.styleSheet()

    panel.vocal_btn.click()
    assert fake_playback_engine.vocal_remover_enabled is True
    assert "qlineargradient" in panel.vocal_btn.styleSheet()

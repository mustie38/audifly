from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from mustiefly_qt.views.equalizer_window import EqualizerWindow


def test_equalizer_window_crossfade_and_normalization_controls(qapp=None):
    if QApplication.instance() is None:
        _app = QApplication([])
    saved = []
    settings = {
        "equalizer_enabled": False,
        "crossfade_enabled": False,
        "crossfade_seconds": 3,
        "audio_normalization": False,
        "equalizer_bands": [0.0] * 10,
    }
    playback = MagicMock()
    playback.eq_band_count = 10
    playback.eq_preset_names = ["Flat", "Rock", "Pop"]

    win = EqualizerWindow(playback, settings, lambda: saved.append(1))

    # Crossfade kontrolü
    assert win.cf_check.isChecked() is False
    assert win.cf_slider.value() == 3
    assert win.cf_label.text() == "3 sn"

    win.cf_check.setChecked(True)
    assert settings["crossfade_enabled"] is True
    playback.apply_crossfade_settings.assert_called_with(True, 3)

    win.cf_slider.setValue(7)
    assert settings["crossfade_seconds"] == 7
    assert win.cf_label.text() == "7 sn"
    playback.apply_crossfade_settings.assert_called_with(True, 7)

    # Ses Normalizasyonu kontrolü
    assert win.norm_check.isChecked() is False
    win.norm_check.setChecked(True)
    assert settings["audio_normalization"] is True
    playback.apply_normalization.assert_called_with(True)

    # Flush settings testi
    win._flush_settings()
    assert len(saved) >= 1

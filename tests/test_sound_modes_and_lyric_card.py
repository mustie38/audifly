"""
Tests for 🎧 Sound Modes (Slowed / Speed Up / Nightcore / Bass Boost / Gece Modu)
and 🖼️ Shareable Lyric Card (PNG generator + dialog).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtGui import QColor, QPixmap

from mustiefly_qt.helpers.lyric_card import CARD_THEMES, render_lyric_card
from mustiefly_qt.services import playback as pb_mod
from mustiefly_qt.services.sound_modes import SOUND_MODE_ORDER, SOUND_MODES, apply_sound_mode
from mustiefly_qt.views.lyric_card_dialog import LyricCardDialog


def test_sound_modes_apply_rate_and_eq_bands(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pb_mod.vlc, "AudioEqualizer", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    try:
        seen = []
        engine.soundModeChanged.connect(seen.append)

        # Speed Up
        m_su = apply_sound_mode(engine, "speed_up")
        assert m_su.rate == 1.18
        assert engine.settings["_rate"] == 1.18
        assert engine.settings["sound_mode"] == "speed_up"
        assert engine.settings["equalizer_enabled"] is True

        # Slowed
        m_sl = apply_sound_mode(engine, "slowed")
        assert m_sl.rate == 0.84
        assert engine.settings["_rate"] == 0.84

        # Nightcore
        m_nc = apply_sound_mode(engine, "nightcore")
        assert m_nc.rate == 1.25

        # Bass Boost & Gece Modu
        assert apply_sound_mode(engine, "bass_boost").bands[0] > 5.0
        assert apply_sound_mode(engine, "night_mode").bands[0] < 0.0

        # Normal resets rate to 1.0 and disables EQ
        apply_sound_mode(engine, "normal")
        assert engine.settings["_rate"] == 1.0
        assert engine.settings["equalizer_enabled"] is False
        assert seen == ["speed_up", "slowed", "nightcore", "bass_boost", "night_mode", "normal"]
        assert set(SOUND_MODE_ORDER) == set(SOUND_MODES.keys())
    finally:
        engine.shutdown()


def test_render_lyric_card_all_themes_and_cover(qapp):
    cover = QPixmap(120, 120)
    cover.fill(QColor("#ff5588"))

    for theme_key in CARD_THEMES:
        pm = render_lyric_card(
            "Dönence",
            "Barış Manço",
            "Simsiyah gecenin koynundayım yapayalnız\nUzaklarda bir yerlerde güneşler doğuyor",
            cover_pixmap=cover if theme_key == "dynamic" else None,
            theme_key=theme_key,
        )
        assert not pm.isNull()
        assert pm.width() == 720
        assert pm.height() == 900


def test_lyric_card_dialog_preview_theme_and_line_append(qapp):
    song = {"title": "Barış Manço - Dönence", "uploader": "Barış Manço"}
    dlg = LyricCardDialog(
        song,
        initial_lines=["İlk satır", "İkinci satır", "Üçüncü satır"],
    )
    try:
        assert dlg._current_pixmap is not None and not dlg._current_pixmap.isNull()
        assert "İlk satır" in dlg.text_edit.toPlainText()

        dlg._select_theme("sunset")
        assert dlg._theme_key == "sunset"

        dlg._append_clicked_line(dlg.lines_list.item(0))
        assert dlg.text_edit.toPlainText().count("İlk satır") == 2

        dlg._copy_to_clipboard()
        assert "Kopyalandı" in dlg.copy_btn.text()
    finally:
        dlg.close()


def test_equalizer_window_sound_mode_buttons(library_store, qapp, monkeypatch):
    from mustiefly_qt.views.equalizer_window import EqualizerWindow

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pb_mod.vlc, "AudioEqualizer", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pb_mod.vlc, "libvlc_audio_equalizer_get_band_count", lambda: 10)
    monkeypatch.setattr(pb_mod.vlc, "libvlc_audio_equalizer_get_preset_count", lambda: 0)
    monkeypatch.setattr(pb_mod.vlc, "libvlc_audio_equalizer_get_band_frequency", lambda i: 60.0 * (2 ** i))
    settings = {}
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, settings)
    win = EqualizerWindow(engine, settings, lambda: None)
    try:
        win._apply_sound_mode("speed_up")
        assert settings["sound_mode"] == "speed_up"
        assert settings["_rate"] == 1.18
        assert win.band_sliders[0].value() == 2

        win._apply_sound_mode("slowed")
        assert settings["sound_mode"] == "slowed"
        assert settings["_rate"] == 0.84
        assert win.band_sliders[0].value() == 4
    finally:
        win.close()
        engine.shutdown()

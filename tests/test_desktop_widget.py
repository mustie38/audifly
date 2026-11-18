"""Unit tests for DesktopWidget (Rainmeter-style transparent desktop widget)."""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QEnterEvent

from mustiefly_qt.services import playback as pb_mod
from mustiefly_qt.views.desktop_widget import DesktopWidget, STYLE_GLASS, STYLE_MINIMAL, STYLE_NEON


def test_desktop_widget_song_and_style_modes(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    settings = {"desktop_widget_pos": [120, 80]}
    saved_calls = []

    widget = DesktopWidget(engine, None, settings, lambda: saved_calls.append(True))
    try:
        assert widget.x() == 120 and widget.y() == 80
        assert widget.controls_box.isHidden()

        song = {"title": "Barış Manço - Dönence", "uploader": "Barış Manço", "webpage_url": "https://youtu.be/bm1", "duration": 210}
        engine.songStarted.emit("Varsayılan", 0, song, False)
        assert "Dönence" in widget.title_label.text()
        assert "Barış Manço" in widget.artist_label.text()

        engine.positionChanged.emit(30000, 210000)
        assert widget.progress.value() == 30000

        widget._set_style_mode(STYLE_MINIMAL)
        assert settings["desktop_widget_style"] == STYLE_MINIMAL
        widget._set_style_mode(STYLE_NEON)
        assert settings["desktop_widget_style"] == STYLE_NEON
        widget._set_style_mode(STYLE_GLASS)
        assert len(saved_calls) == 3

        widget.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))
        assert not widget.controls_box.isHidden()
        widget.leaveEvent(QEvent(QEvent.Type.Leave))
        assert widget.controls_box.isHidden()
    finally:
        widget.close()
        engine.shutdown()

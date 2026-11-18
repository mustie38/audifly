"""
Unit tests for CommandPaletteDialog (Ctrl + K Spotlight & Command Palette).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from mustiefly_qt.services import playback as pb_mod
from mustiefly_qt.views.command_palette import CommandPaletteDialog, _PaletteRowWidget


def test_command_palette_default_suggestions(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    library_store.playlists["Rock"] = [
        {"title": "Dönence", "uploader": "Barış Manço", "webpage_url": "https://youtu.be/bm1", "duration": 200},
    ]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    dlg = CommandPaletteDialog(library_store, engine)
    try:
        assert dlg.results_list.count() > 0
        assert dlg.status_label.text() != ""
        # The first item should be a quick command
        first_row = dlg.results_list.itemWidget(dlg.results_list.item(0))
        assert isinstance(first_row, _PaletteRowWidget)
        assert first_row.item.kind == "command"
    finally:
        dlg.close()
        engine.shutdown()


def test_command_palette_search_commands(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    dlg = CommandPaletteDialog(library_store, engine)
    try:
        dlg.search_edit.setText("vokal")
        dlg._run_search()
        assert dlg.results_list.count() >= 1
        matched_kinds = [
            dlg.results_list.itemWidget(dlg.results_list.item(i)).item.kind
            for i in range(dlg.results_list.count())
        ]
        assert "command" in matched_kinds
    finally:
        dlg.close()
        engine.shutdown()


def test_command_palette_search_song_and_artist(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    library_store.playlists["Klasikler"] = [
        {"title": "Gülpembe", "uploader": "Barış Manço", "webpage_url": "https://youtu.be/bm2", "duration": 240},
        {"title": "Kuzu Kuzu", "uploader": "Tarkan", "webpage_url": "https://youtu.be/tk1", "duration": 180},
    ]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    dlg = CommandPaletteDialog(library_store, engine)
    try:
        # Search by artist
        dlg.search_edit.setText("barış")
        dlg._run_search()
        assert dlg.results_list.count() >= 1
        items = [
            dlg.results_list.itemWidget(dlg.results_list.item(i)).item
            for i in range(dlg.results_list.count())
        ]
        artist_matches = [it for it in items if it.kind == "artist"]
        song_matches = [it for it in items if it.kind == "song"]
        assert len(artist_matches) >= 1
        assert "Barış Manço" in artist_matches[0].title
        assert len(song_matches) >= 1

        # Search by song title
        dlg.search_edit.setText("kuzu")
        dlg._run_search()
        items2 = [
            dlg.results_list.itemWidget(dlg.results_list.item(i)).item
            for i in range(dlg.results_list.count())
        ]
        song_titles = [it.title for it in items2 if it.kind == "song"]
        assert any("Kuzu Kuzu" in t for t in song_titles)
    finally:
        dlg.close()
        engine.shutdown()


def test_command_palette_navigation_and_activation(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    library_store.playlists["Pop"] = [
        {"title": "Şımarık", "uploader": "Tarkan", "webpage_url": "https://youtu.be/tk2", "duration": 190},
    ]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    played = []
    monkeypatch.setattr(engine, "play_song_at_index", lambda pl, idx: played.append((pl, idx)))

    dlg = CommandPaletteDialog(library_store, engine)
    try:
        dlg.search_edit.setText("şımarık")
        dlg._run_search()
        assert dlg.results_list.count() >= 1

        # Check navigation
        dlg._navigate_list(1)
        assert dlg.results_list.currentRow() <= dlg.results_list.count() - 1

        # Find the song row and activate it
        for i in range(dlg.results_list.count()):
            it = dlg.results_list.itemWidget(dlg.results_list.item(i)).item
            if it.kind == "song":
                dlg.results_list.setCurrentRow(i)
                break

        # Simulate execution
        row = dlg.results_list.currentRow()
        item = dlg._current_matches[row]
        item.callback()
        assert played == [("Pop", 0)]
    finally:
        dlg.close()
        engine.shutdown()


def test_command_palette_key_events(library_store, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    dlg = CommandPaletteDialog(library_store, engine)
    try:
        # Test Down arrow emission
        dlg.results_list.setCurrentRow(0)
        event_down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Down, Qt.NoModifier)
        dlg.search_edit.keyPressEvent(event_down)
        assert dlg.results_list.currentRow() == 1

        # Test Up arrow emission
        event_up = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Up, Qt.NoModifier)
        dlg.search_edit.keyPressEvent(event_up)
        assert dlg.results_list.currentRow() == 0
    finally:
        dlg.close()
        engine.shutdown()

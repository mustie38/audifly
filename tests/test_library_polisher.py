"""
Tests for ✨ Kütüphane Parlatıcı (services/library_polisher.py + views/library_polisher_dialog.py).
"""
from __future__ import annotations

from mustiefly_qt.services.library_polisher import (
    apply_proposals,
    polish_song_metadata,
    scan_library,
)
from mustiefly_qt.views.library_polisher_dialog import LibraryPolisherDialog


def test_polish_strips_youtube_junk_and_channel_suffixes():
    new_t, new_u, reasons = polish_song_metadata({
        "title": "Tarkan - Kuzu Kuzu (Official Music Video) [4K]",
        "uploader": "TarkanVEVO",
    })
    assert new_t == "Kuzu Kuzu"
    assert new_u == "Tarkan"
    assert reasons


def test_polish_strips_topic_and_pipe_suffix():
    new_t, new_u, reasons = polish_song_metadata({
        "title": "Dönence | Şarkı Sözleri",
        "uploader": "Barış Manço - Topic",
    })
    assert new_t == "Dönence"
    assert new_u == "Barış Manço"
    assert len(reasons) >= 2


def test_polish_preserves_meaningful_version_tags():
    new_t, new_u, reasons = polish_song_metadata({
        "title": "Gülpembe (Live Acoustic)",
        "uploader": "Barış Manço",
    })
    assert new_t == "Gülpembe (Live Acoustic)"
    assert new_u == "Barış Manço"
    assert reasons == []


def test_scan_and_apply_proposals_updates_store(library_store):
    library_store.playlists["Pop"] = [
        {"title": "Şımarık (Official Video)", "uploader": "Tarkan Official", "webpage_url": "https://youtu.be/t1"},
        {"title": "Temiz Şarkı", "uploader": "Temiz Sanatçı", "webpage_url": "https://youtu.be/t2"},
    ]
    proposals = scan_library(library_store)
    assert len(proposals) == 1
    assert proposals[0].new_title == "Şımarık"
    assert proposals[0].new_uploader == "Tarkan"

    emitted = []
    library_store.playlistsChanged.connect(lambda: emitted.append(1))
    updated = apply_proposals(library_store, proposals)
    assert updated == 1
    assert library_store.playlists["Pop"][0]["title"] == "Şımarık"
    assert library_store.playlists["Pop"][0]["uploader"] == "Tarkan"
    assert emitted == [1]


def test_library_polisher_dialog_preview_and_apply(library_store, qapp):
    library_store.playlists["Varsayılan"] = [
        {"title": "Sezen Aksu - Gidiyorum [HD]", "uploader": "netd müzik", "webpage_url": "https://youtu.be/s1"},
    ]
    dlg = LibraryPolisherDialog(library_store)
    try:
        assert len(dlg._rows) == 1
        assert dlg.apply_btn.isEnabled() is True

        # Uncheck all -> apply button disabled
        dlg._toggle_select_all()
        assert dlg.apply_btn.isEnabled() is False

        # Re-check all & apply
        dlg._toggle_select_all()
        dlg._apply()
        assert library_store.playlists["Varsayılan"][0]["title"] == "Gidiyorum"
        assert library_store.playlists["Varsayılan"][0]["uploader"] == "Sezen Aksu"
        assert len(dlg._rows) == 0
    finally:
        dlg.close()

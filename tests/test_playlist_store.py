"""services/playlist_store.py için testler.

PySide6 (QObject/QTimer) gerektirdiği için bu dosyanın tamamı PySide6 kurulu
değilse `pytest.importorskip` ile atlanır — böylece PySide6'sız bir ortamda
(örn. bu projenin sadece mantığını inceleyen bir CI adımı) çökme yerine
sadece "skipped" görürsün.
"""
import pytest

pytest.importorskip("PySide6", reason="playlist_store.py bir QObject'tir, PySide6 gerektirir")

from PySide6.QtWidgets import QApplication

from mustiefly_qt.helpers.constants import AppPaths
from mustiefly_qt.services.playlist_store import PlaylistStore, _clean_song


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def store(tmp_path, qapp):
    paths = AppPaths(
        base_dir=str(tmp_path),
        dir=str(tmp_path / "user"),
        playlist_file=str(tmp_path / "user" / "playlist.json"),
        settings_file=str(tmp_path / "user" / "settings.json"),
        cache_dir=str(tmp_path / "user" / "audio_cache"),
        covers_dir=str(tmp_path / "user" / "covers"),
    )
    paths.ensure_dirs()
    s = PlaylistStore(paths)
    s.backup_enabled = False  # testte gereksiz yedekleme yazmasın
    return s


def _song(title, url, **extra):
    base = {"title": title, "webpage_url": url, "duration": 180, "uploader": "X"}
    base.update(extra)
    return base


class TestCleanSong:
    def test_fills_in_missing_fields_with_defaults(self):
        cleaned = _clean_song({})
        assert cleaned["title"] == "Bilinmeyen Şarkı"
        assert cleaned["uploader"] == "Bilinmeyen Sanatçı"
        assert cleaned["liked"] is False
        assert cleaned["play_count"] == 0

    def test_keeps_local_path_when_present(self):
        cleaned = _clean_song({"title": "X", "local_path": "/home/user/song.mp3"})
        assert cleaned["local_path"] == "/home/user/song.mp3"

    def test_omits_local_path_when_absent(self):
        cleaned = _clean_song({"title": "X"})
        assert "local_path" not in cleaned


class TestDuplicateDetection:
    def test_no_duplicates_when_all_urls_unique(self, store):
        store.playlists["Varsayılan"] = [
            _song("A", "https://youtu.be/1"),
            _song("B", "https://youtu.be/2"),
        ]
        assert store.find_duplicate_groups() == []

    def test_finds_duplicate_within_same_playlist(self, store):
        store.playlists["Varsayılan"] = [
            _song("A", "https://youtu.be/1"),
            _song("A (kopya)", "https://youtu.be/1"),
            _song("B", "https://youtu.be/2"),
        ]
        groups = store.find_duplicate_groups()
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_finds_duplicate_across_playlists(self, store):
        store.playlists["Varsayılan"] = [_song("A", "https://youtu.be/1")]
        store.playlists["Diğer"] = [_song("A (kopya)", "https://youtu.be/1")]
        groups = store.find_duplicate_groups()
        assert len(groups) == 1
        assert {g[0] for g in groups[0]} == {"Varsayılan", "Diğer"}

    def test_songs_without_url_are_ignored(self, store):
        store.playlists["Varsayılan"] = [
            _song("A", ""), _song("A", ""),
        ]
        assert store.find_duplicate_groups() == []

    def test_clean_duplicates_keeps_first_copy_only(self, store):
        store.playlists["Varsayılan"] = [
            _song("İlk", "https://youtu.be/1"),
            _song("İkinci kopya", "https://youtu.be/1"),
            _song("Üçüncü kopya", "https://youtu.be/1"),
        ]
        groups = store.find_duplicate_groups()
        removed_count = store.clean_duplicates(groups)
        assert removed_count == 2
        remaining = store.playlists["Varsayılan"]
        assert len(remaining) == 1
        assert remaining[0]["title"] == "İlk"

    def test_clean_duplicates_pushes_undo_action(self, store):
        store.playlists["Varsayılan"] = [
            _song("İlk", "https://youtu.be/1"),
            _song("Kopya", "https://youtu.be/1"),
        ]
        assert len(store._undo_stack) == 0
        store.clean_duplicates(store.find_duplicate_groups())
        assert len(store._undo_stack) == 1
        assert store._undo_stack[-1][0] == "bulk_delete"


def test_save_builds_snapshot_lazily_and_flush_writes_it(library_store):
    library_store.save()
    assert library_store._pending_snapshot is None and library_store._save_dirty
    assert library_store.flush_now()
    assert not library_store._save_dirty

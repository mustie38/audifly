import json
from pathlib import Path

import pytest

from mustiefly_qt.services.playlist_store import _clean_song


def song(url="https://youtu.be/abc", **extra):
    return {"title": "Song", "webpage_url": url, **extra}


def test_shared_cache_is_not_deleted(library_store):
    store = library_store
    path = Path(store.paths.cache_dir) / "shared.mp3"
    path.write_bytes(b"audio")
    store.playlists = {"A": [song(cached_path=str(path))], "B": [song(cached_path=str(path))]}
    store.remove_song("A", 0)
    store._execute_file_deletion(str(path))
    assert path.exists()


def test_external_files_cannot_be_deleted(library_store, tmp_path):
    outside = tmp_path / "original.mp3"
    outside.write_bytes(b"keep")
    library_store._execute_file_deletion(str(outside))
    assert outside.exists()


def test_deletion_rechecks_references(library_store):
    path = Path(library_store.paths.cache_dir) / "song.mp3"
    path.write_bytes(b"audio")
    library_store._schedule_file_deletion(str(path))
    library_store.playlists["Varsayılan"].append(song(cached_path=str(path)))
    library_store._execute_file_deletion(str(path))
    assert path.exists()


def test_unreferenced_owned_file_deleted(library_store):
    path = Path(library_store.paths.cache_dir) / "song.mp3"
    path.write_bytes(b"audio")
    library_store._execute_file_deletion(str(path))
    assert not path.exists()


def test_removing_playlist_cover_clears_custom_cache(library_store, tmp_path):
    from PIL import Image
    from mustiefly_qt.views.sidebar import SidebarWidget

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (8, 8), "blue").save(cover)
    library_store.playlist_covers["A"] = str(cover)
    sidebar = SidebarWidget(library_store, paths=library_store.paths)
    sidebar._custom_cover_cache["A"] = (str(cover), cover.stat().st_mtime, object())

    sidebar._remove_playlist_cover("A")

    assert "A" not in sidebar._custom_cover_cache
    sidebar.deleteLater()


def test_rename_playlist_clears_custom_cover_cache(library_store, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from mustiefly_qt.views import sidebar as sidebar_module
    from mustiefly_qt.views.sidebar import SidebarWidget

    library_store.playlists = {"Old": [song()], "Other": []}
    library_store.playlist_covers["Old"] = "/tmp/old-cover.jpg"
    library_store.active_playlist = "Old"
    sidebar = SidebarWidget(library_store, paths=library_store.paths)
    sidebar._custom_cover_cache["Old"] = ("/tmp/old-cover.jpg", 1.0, object())
    sidebar._cover_signatures["Old"] = ("old-url",)
    sidebar.show()
    QApplication.instance().processEvents()

    item = next(sidebar.playlist_list.item(i)
                for i in range(sidebar.playlist_list.count())
                if sidebar.playlist_list.item(i).data(Qt.UserRole) == "Old")
    pos = sidebar.playlist_list.visualItemRect(item).center()

    class FakeAction:
        def setEnabled(self, _enabled):
            pass

    class FakeMenu:
        def __init__(self, *_args):
            self.actions = []

        def addAction(self, _label):
            action = FakeAction()
            self.actions.append(action)
            return action

        def exec(self, _pos):
            return self.actions[0]

    monkeypatch.setattr(sidebar_module, "QMenu", FakeMenu)
    monkeypatch.setattr(sidebar_module.QInputDialog, "getText",
                        lambda *_args: ("New", True))
    sidebar._on_context_menu(pos)

    assert "Old" not in sidebar._custom_cover_cache
    assert "Old" not in sidebar._cover_signatures
    assert "New" not in sidebar._custom_cover_cache
    sidebar.deleteLater()


def test_duplicate_cleanup_preserves_surviving_cache(library_store):
    path = Path(library_store.paths.cache_dir) / "song.mp3"
    path.write_bytes(b"audio")
    library_store.playlists = {"A": [song(cached_path=str(path)), song(cached_path=str(path))]}
    library_store.clean_duplicates(library_store.find_duplicate_groups())
    library_store._execute_file_deletion(str(path))
    assert path.exists()


def test_rename_updates_active_and_queue(library_store):
    store = library_store
    store.add_song("Varsayılan", song())
    store.add_to_queue("Varsayılan", 0, store.playlists["Varsayılan"][0])
    assert store.rename_playlist("Varsayılan", "Yeni")[0]
    assert store.active_playlist == "Yeni"
    assert store.manual_queue[0][0] == "Yeni"


def test_playlist_switch_is_persisted(library_store):
    store = library_store
    store.playlists = {"A": [], "B": []}
    store.active_playlist = "A"
    store.switch_playlist("B")
    store.flush_now()
    assert json.loads(Path(store.paths.playlist_file).read_text(encoding="utf-8"))["active_playlist"] == "B"


def test_schema_invalid_main_and_backup_skipped(library_store):
    store = library_store
    Path(store.paths.playlist_file).write_text('{"playlists":"invalid"}', encoding="utf-8")
    backups = Path(store.paths.dir) / "backups"
    backups.mkdir(exist_ok=True)
    (backups / "playlists.bak1.json").write_text("123", encoding="utf-8")
    (backups / "playlists.bak2.json").write_text(json.dumps({"playlists": {"Recovered": [None, song(), 123]}}), encoding="utf-8")
    store.load()
    assert list(store.playlists) == ["Recovered"]
    assert len(store.playlists["Recovered"]) == 1


@pytest.mark.parametrize("value", [None, "bad", {}, float("nan"), -10, float("inf")])
def test_malformed_numeric_song_fields_normalized(value):
    cleaned = _clean_song({"title": None, "duration": value, "play_count": value})
    assert cleaned["duration"] == cleaned["play_count"] == 0
    assert cleaned["title"] == "Bilinmeyen Şarkı"


def test_batch_delete_keeps_queue_for_surviving_copy(library_store):
    store = library_store
    store.playlists = {"A": [song()], "B": [song()]}
    survivor = store.playlists["B"][0]
    store.add_to_queue("B", 0, survivor)
    assert store.remove_songs_batch([("A", 0)]) == 1
    assert store.manual_queue[0][2] is survivor

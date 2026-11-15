import json
from pathlib import Path

import pytest

from mustiefly_qt.helpers.persistence import atomic_write_json


def test_atomic_write_creates_parent_and_keeps_unicode(tmp_path):
    path = tmp_path / "nested" / "data.json"
    atomic_write_json(path, {"title": "Şarkı"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"title": "Şarkı"}
    assert list(path.parent.glob("*.tmp")) == []


def test_serialization_failure_preserves_original(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"original":true}', encoding="utf-8")
    with pytest.raises(TypeError):
        atomic_write_json(path, {"broken": object()})
    assert json.loads(path.read_text(encoding="utf-8")) == {"original": True}
    assert list(tmp_path.iterdir()) == [path]


def test_replace_failure_preserves_original(tmp_path, monkeypatch):
    from mustiefly_qt.helpers import persistence
    path = tmp_path / "data.json"
    path.write_text("old", encoding="utf-8")
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(persistence.os, "replace", fail)
    with pytest.raises(OSError):
        atomic_write_json(path, {"new": True})
    assert path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [path]


def test_final_flush_waits_for_older_background_write(library_store, monkeypatch):
    import threading
    store = library_store
    original = store._write_playlist_file
    started, release = threading.Event(), threading.Event()
    first = True
    def delayed(data):
        nonlocal first
        if first:
            first = False
            started.set()
            assert release.wait(3)
        return original(data)
    monkeypatch.setattr(store, "_write_playlist_file", delayed)
    store.playlists = {"old": []}
    store.active_playlist = "old"
    store.save()
    store._flush_pending_save()
    assert started.wait(3)
    store.playlists = {"latest": []}
    store.active_playlist = "latest"
    store.save()
    release.set()
    assert store.flush_now()
    assert json.loads(Path(store.paths.playlist_file).read_text(encoding="utf-8"))["active_playlist"] == "latest"


def test_failed_write_retained_for_flush_retry(library_store, monkeypatch):
    from mustiefly_qt.services import playlist_store
    real = playlist_store.atomic_write_json
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(playlist_store, "atomic_write_json", fail)
    library_store.save()
    assert library_store.flush_now() is False
    assert library_store._failed_snapshot is not None
    monkeypatch.setattr(playlist_store, "atomic_write_json", real)
    assert library_store.flush_now()
    assert Path(library_store.paths.playlist_file).is_file()

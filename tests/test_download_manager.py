from pathlib import Path

import pytest

from mustiefly_qt.services.download_manager import DownloadManager, CANCELLED, DONE, FAILED, QUEUED


@pytest.fixture()
def manager(library_store, monkeypatch):
    library_store.playlists = {"A": [{"title": "Song", "webpage_url": "https://youtu.be/abc"}],
                              "B": [{"title": "Copy", "webpage_url": "https://youtu.be/abc"}]}
    m = DownloadManager(library_store, library_store.paths)
    # Deterministic tests; no actual network/downloader threads.
    monkeypatch.setattr(m, "_ensure_worker", lambda: None)
    yield m
    m.shutdown()


def enqueue(manager):
    assert manager.enqueue("A", 0)
    return next(iter(manager.items.values()))


def test_active_duplicate_rejected(manager):
    enqueue(manager)
    assert not manager.enqueue("B", 0)


def test_cancel_retry_uses_distinct_attempt_and_event(manager):
    old = enqueue(manager)
    manager.cancel(old["key"])
    manager.retry(old["key"])
    new = manager.items[old["key"]]
    assert old is not new
    assert old["cancel"].is_set()
    assert not new["cancel"].is_set() and new["state"] == QUEUED


def test_stale_completion_does_not_finish_new_attempt(manager):
    old = enqueue(manager)
    manager.remove(old["key"])
    new = enqueue(manager)
    path = Path(manager.paths.cache_dir) / "audio.mp3"
    path.write_bytes(b"audio")
    manager._finish_on_gui(old, str(path))
    assert new["state"] == QUEUED
    assert "cached_path" not in new["song"]


def test_cancelled_completion_ignored(manager):
    item = enqueue(manager)
    manager.cancel(item["key"])
    path = Path(manager.paths.cache_dir) / "audio.mp3"
    path.write_bytes(b"audio")
    manager._finish_on_gui(item, str(path))
    assert item["state"] == CANCELLED


def test_missing_output_not_reported_as_done(manager):
    item = enqueue(manager)
    manager._finish_on_gui(item, str(Path(manager.paths.cache_dir) / "missing.mp3"))
    assert item["state"] == FAILED
    assert "cached_path" not in item["song"]


def test_success_updates_all_library_copies(manager):
    item = enqueue(manager)
    path = Path(manager.paths.cache_dir) / "audio.mp3"
    path.write_bytes(b"audio")
    manager._finish_on_gui(item, str(path))
    assert item["state"] == DONE
    for songs in manager.store.playlists.values():
        assert songs[0]["cached_path"] == str(path)


def test_shutdown_rejects_new_work(manager):
    item = enqueue(manager)
    assert manager.shutdown()
    assert item["cancel"].is_set()
    assert not manager.enqueue("A", 0)


def test_snapshots_do_not_expose_mutable_item_state(manager):
    item = enqueue(manager)
    snapshot = manager.ordered_items()[0]
    snapshot["state"] = DONE
    assert item["state"] == QUEUED


def test_downloader_without_output_fails(manager, monkeypatch):
    from mustiefly_qt.services import download_manager as module
    class FakeDownloader:
        def __init__(self, options):
            assert options["noplaylist"] is True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def download(self, urls): pass
    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeDownloader)
    item = enqueue(manager)
    manager._process(item)
    assert item["state"] == FAILED

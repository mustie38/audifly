"""Performans iyileştirmelerinin regresyon testleri (sanal liste, sinyal birleştirme, RAM önbelleği)."""
import threading
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")


def _make_view(library_store, n):
    from mustiefly_qt.views.library_view import LibraryView
    library_store.playlists = {"A": [
        {"title": f"s{i}", "webpage_url": f"u{i}", "uploader": "x", "duration": 100}
        for i in range(n)]}
    library_store.active_playlist = "A"
    playback = MagicMock()
    playback.history = None
    playback.playing_playlist = None
    playback.current_index = -1
    return LibraryView(library_store, playback, None, library_store.paths)


def test_library_view_builds_only_visible_rows(library_store):
    view = _make_view(library_store, 800)
    view.show_playlist("A")
    assert view.list_widget.count() == 800
    assert 0 < len(view._live_rows) < 80         # 800 widget'ın tamamı kurulmamalı


def test_playlists_changed_burst_renders_once(library_store):
    view = _make_view(library_store, 50)
    view.show_playlist("A")
    calls = []
    real = view._render
    view._render = lambda: (calls.append(1), real())
    for _ in range(20):
        library_store.playlistsChanged.emit()
    assert calls == [] and view._render_timer.isActive()   # hemen çizilmez, tek zamanlayıcıda birikir
    view._run_scheduled_render()                           # zamanlayıcı dolunca çalışan yol
    assert len(calls) == 1
    assert not view._render_timer.isActive()


def test_ram_thumbnail_cache_is_downscaled_but_caller_image_untouched():
    from PIL import Image
    from mustiefly_qt.services.thumbnails import RAM_CACHE_MAX_SIDE, ThumbnailService
    svc = ThumbnailService(max_workers=1)
    big = Image.new("RGB", (1280, 720), "red")
    svc._cache_put("k", big)
    assert max(svc._pil_cache["k"].size) <= RAM_CACHE_MAX_SIDE
    assert big.size == (1280, 720)               # disk önbelleğine tam boy yazılabilsin


def test_thumbnail_cache_is_safe_under_concurrent_access():
    from PIL import Image
    from mustiefly_qt.services.thumbnails import MAX_PIL_CACHE_SIZE, ThumbnailService

    svc = ThumbnailService(max_workers=1)
    img = Image.new("RGB", (8, 8), "red")
    errors = []

    def worker(thread_id):
        try:
            for i in range(100):
                key = f"{thread_id}-{i}"
                svc._cache_put(key, img)
                svc.pil_for({"webpage_url": key})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    svc._executor.shutdown(wait=True)

    assert errors == []
    assert len(svc._pil_cache) <= MAX_PIL_CACHE_SIZE

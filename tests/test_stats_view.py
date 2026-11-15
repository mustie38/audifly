from unittest.mock import MagicMock

from PySide6.QtWidgets import QLabel

import pytest

from mustiefly_qt.services.history_store import HistoryStore


def test_stats_view_uses_history(library_store, tmp_path):
    pytest.importorskip("PySide6")
    from mustiefly_qt.views.stats_view import StatsView, format_listen_time
    library_store.playlists = {"A": [{"title": "S", "webpage_url": "u1", "duration": 100,
                                      "play_count": 9}]}
    playback = MagicMock()
    playback.history = HistoryStore(str(tmp_path / "h"))
    playback.history.record({"title": "S", "webpage_url": "u1", "uploader": "Ali", "duration": 100}, 90, True)
    view = StatsView(library_store, playback)
    assert format_listen_time(5400) == "1 sa 30 dk" and format_listen_time(600) == "10 dk"
    texts = [w.text() for w in view.findChildren(QLabel)]
    assert any("Ali" in t for t in texts)
    view.period_combo.setCurrentIndex(1)       # dönem değişince çökmemeli
    assert view.card_plays is not None

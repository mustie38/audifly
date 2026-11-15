from datetime import date, datetime, timedelta

from mustiefly_qt.services import wrapped as w
from mustiefly_qt.services.history_store import HistoryStore

NOW = datetime(2026, 10, 31, 12)


def song(i, artist):
    return {"title": f"S{i}", "webpage_url": f"u{i}", "uploader": artist, "duration": 200}


def fill(tmp_path, rows):
    h = HistoryStore(str(tmp_path))
    for i, artist, when in rows:
        h.record(song(i, artist), 120, True, when)
    return h


def test_not_enough_data_returns_none(tmp_path):
    h = fill(tmp_path, [(1, "A", NOW - timedelta(days=d)) for d in range(5)])
    assert w.build_wrapped(h, w.LAST_12_MONTHS, NOW) is None
    assert w.build_wrapped(None, w.LAST_12_MONTHS, NOW) is None


def test_summary_numbers(tmp_path):
    rows = []
    for d in range(1, 8):                                   # 7 ardışık gün, 2 şarkı/gün
        t = (NOW - timedelta(days=d)).replace(hour=22)      # akşam/gece
        rows += [(1, "Ceza", t), (2, "Ezhel", t + timedelta(minutes=10))]
    rows += [(1, "Ceza", NOW - timedelta(days=20)), (3, "Yeni - Topic", NOW - timedelta(days=30))]
    h = fill(tmp_path, rows)
    r = w.build_wrapped(h, w.LAST_12_MONTHS, NOW)
    assert r.plays == 16 and r.distinct_songs == 3 and r.distinct_artists == 3
    assert r.top_songs[0]["title"] == "S1" and r.top_artists[0]["artist"] == "Ceza"
    assert r.longest_streak == 7 and r.active_days == 9
    assert r.daypart == "Geceleri" and r.new_artists == 3
    assert r.total_seconds == 16 * 120 and r.top_song_share == 50.0
    assert r.label == "Son 12 ay" and r.busiest_month == "Ekim"


def test_calendar_year_filters_and_new_artists_use_earlier_history(tmp_path):
    rows = [(1, "Eski", datetime(2025, 3, d)) for d in range(1, 6)]
    rows += [(i % 3, "Eski" if i % 3 == 1 else "Yeni", datetime(2026, 5, 1 + i)) for i in range(12)]
    h = fill(tmp_path, rows)
    r = w.build_wrapped(h, 2026, NOW)
    assert r.label == "2026" and r.plays == 12
    assert r.new_artists == 1                     # "Eski" 2025'te zaten vardı
    assert w.available_periods(h, NOW) == [w.LAST_12_MONTHS, 2026, 2025]


def test_longest_streak():
    days = {date(2026, 1, d) for d in (1, 2, 3, 5, 6, 10)}
    assert w.longest_streak(days) == 3 and w.longest_streak(set()) == 0


def test_wrapped_view_renders_empty_state_and_exports_png(tmp_path):
    from unittest.mock import MagicMock
    from mustiefly_qt.views.wrapped_view import WrappedView
    pb = MagicMock()
    pb.history = HistoryStore(str(tmp_path / "h"))
    view = WrappedView(pb)
    view.refresh()
    assert view.card is None and not view.export_btn.isEnabled()
    assert view.export_png(str(tmp_path / "x.png")) is False
    now = datetime.now()
    for d in range(1, 8):
        for i in range(2):
            pb.history.record(song(i, "Ceza"), 120, True, now - timedelta(days=d, minutes=i))
    view.refresh()
    assert view.card is not None and view.export_btn.isEnabled()
    out = tmp_path / "wrapped.png"
    assert view.export_png(str(out)) and out.stat().st_size > 5000
    from PySide6.QtGui import QImage
    img = QImage(str(out))
    assert (img.width(), img.height()) == (540, 780)

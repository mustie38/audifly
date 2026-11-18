import pytest

from mustiefly_qt.helpers import discovery as dc

TRACKS = [{"title": f"T{i}", "webpage_url": f"https://youtu.be/{i}", "uploader": f"A{i}", "thumbnail": f"https://i.ytimg.com/{i}.jpg",
           "duration": 0} for i in range(5)]


@pytest.fixture()
def svc(tmp_path):
    return dc.DiscoveryService(str(tmp_path), {})


CHART = next(c for c in dc.CATEGORY_DEFS if c["id"] == "tr_trending")
SEARCH = next(c for c in dc.CATEGORY_DEFS if c["id"] == "tr_rap_week")


def test_real_ytmusic_chart_is_labeled_and_ranked(svc, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_from_ytmusic_charts", lambda region: list(TRACKS))
    monkeypatch.setattr(svc, "_resolve_spotify_playlist_id", lambda q: None)
    section = svc._build_section(CHART, 1000.0)
    assert section["source"]["id"] == "ytmusic_chart" and section["ranked"] is True
    assert section["subtitle"] == CHART["subtitle"] and section["updated_at"] == 1000.0


def test_search_fallback_is_never_presented_as_a_chart(svc, monkeypatch):
    monkeypatch.setattr(svc, "_fetch_from_ytmusic_charts", lambda region: [])
    monkeypatch.setattr(svc, "_fetch_from_youtube_trending", lambda region, limit=24: list(TRACKS))
    monkeypatch.setattr(svc, "_resolve_spotify_playlist_id", lambda q: None)
    section = svc._build_section(CHART, 1000.0)
    assert section["source"]["id"] == "youtube_search"
    assert section["ranked"] is False                     # sıra rozeti yok
    assert section["subtitle"] == dc.SEARCH_ONLY_SUBTITLE  # "yükselenler" iddiası yok


def test_search_categories_are_unranked(svc, monkeypatch):
    monkeypatch.setattr(svc, "fetch_search_based_category", lambda q, limit=12: list(TRACKS))
    section = svc._build_section(SEARCH, 5.0)
    assert section["source"]["id"] == "youtube_search" and section["ranked"] is False


def test_spotify_chart_wins_when_available(svc, monkeypatch):
    monkeypatch.setattr(svc, "_resolve_spotify_playlist_id", lambda q: "pl")
    monkeypatch.setattr(svc, "_fetch_spotify_chart", lambda pid, limit=12: list(TRACKS))
    section = svc._build_section(CHART, 1.0)
    assert section["source"]["id"] == "spotify_chart" and section["ranked"] is True


def test_ytmusic_does_not_mix_chart_sections(svc, monkeypatch):
    class FakeYT:
        def get_charts(self, region):
            item = lambda v: {"videoId": v, "title": v, "artists": [{"name": "X"}]}
            return {"songs": {"items": [item("a"), item("b")]}, "videos": [item("c")]}
    monkeypatch.setattr(dc, "YTMUSICAPI_AVAILABLE", True)
    monkeypatch.setattr(dc, "YTMusic", lambda: FakeYT(), raising=False)
    urls = [t["webpage_url"][-1] for t in svc._fetch_from_ytmusic_charts("TR")]
    assert urls == ["a", "b"]


def test_view_source_text_and_legacy_cache(library_store):
    from mustiefly_qt.views.explore_view import DiscoverySection
    text = DiscoverySection.source_text({"source": {"label": "YouTube Music Charts"}, "updated_at": 0})
    assert text == "Kaynak: YouTube Music Charts"
    assert "bilinmiyor" in DiscoverySection.source_text({})


def test_discovery_filters_non_songs_and_bad_durations(svc):
    bad_tracks = [
        {"title": "Short Clip", "webpage_url": "https://youtu.be/s1", "thumbnail": "http://img/1.jpg", "duration": 25},
        {"title": "2025 Mix 1 Saat", "webpage_url": "https://youtu.be/s2", "thumbnail": "http://img/2.jpg", "duration": 3600},
        {"title": "Podcast Bölümü", "webpage_url": "https://youtu.be/s3", "thumbnail": "http://img/3.jpg", "duration": 200},
        {"title": "Şarkı (Slowed + Reverb)", "webpage_url": "https://youtu.be/s4", "thumbnail": "http://img/4.jpg", "duration": 210},
        {"title": "Gerçek Şarkı", "webpage_url": "https://youtu.be/ok1", "thumbnail": "http://img/ok.jpg", "duration": 195},
    ]
    cleaned = svc._dedupe_and_clean(bad_tracks)
    assert len(cleaned) == 1
    assert cleaned[0]["title"] == "Gerçek Şarkı"


def test_fetch_search_prefers_ytmusic_songs(svc, monkeypatch):
    class FakeYT:
        def search(self, query, filter=None, limit=10):
            assert filter == "songs"
            return [{
                "videoId": "vid123",
                "title": "Dönence",
                "artists": [{"name": "Barış Manço"}],
                "duration_seconds": 210,
                "thumbnails": [{"url": "https://i.ytimg.com/vid123.jpg"}],
            }]

    monkeypatch.setattr(dc, "YTMUSICAPI_AVAILABLE", True)
    monkeypatch.setattr(dc, "YTMusic", lambda: FakeYT(), raising=False)
    tracks = svc.fetch_search_based_category("barış manço", limit=5)
    assert len(tracks) == 1
    assert tracks[0]["title"] == "Dönence"
    assert tracks[0]["uploader"] == "Barış Manço"

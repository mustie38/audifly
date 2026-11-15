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

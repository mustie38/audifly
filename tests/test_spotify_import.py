"""helpers/spotify_import.py için testler (yalnız saf ayrıştırma fonksiyonları;
tarayıcı açan / ağ isteği yapan OAuth akışına dokunulmaz)."""
import pytest

from mustiefly_qt.helpers.spotify_import import extract_spotify_playlist_id


class TestExtractSpotifyPlaylistId:
    def test_open_spotify_url(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert extract_spotify_playlist_id(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_open_spotify_url_with_query_params(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123"
        assert extract_spotify_playlist_id(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_open_spotify_url_with_intl_locale_segment(self):
        url = "https://open.spotify.com/intl-tr/playlist/37i9dQZF1DXcBWIGoYBM5M"
        assert extract_spotify_playlist_id(url) == "37i9dQZF1DXcBWIGoYBM5M"

    def test_spotify_uri(self):
        assert extract_spotify_playlist_id("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M") == "37i9dQZF1DXcBWIGoYBM5M"

    def test_bare_id(self):
        assert extract_spotify_playlist_id("37i9dQZF1DXcBWIGoYBM5M") == "37i9dQZF1DXcBWIGoYBM5M"

    def test_strips_surrounding_whitespace(self):
        assert extract_spotify_playlist_id("  37i9dQZF1DXcBWIGoYBM5M  ") == "37i9dQZF1DXcBWIGoYBM5M"

    @pytest.mark.parametrize("bad_input", [
        "", None, "https://example.com/not-spotify", "too-short", "!!invalid!!",
    ])
    def test_invalid_input_returns_none(self, bad_input):
        assert extract_spotify_playlist_id(bad_input) is None


def test_fetch_spotify_playlist_falls_back_to_embed_for_other_users_or_no_client_id(monkeypatch):
    import json
    from mustiefly_qt.helpers import spotify_import as sp

    embed_html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({
            "props": {"pageProps": {"state": {"data": {"entity": {
                "name": "Başkasının Listesi",
                "trackList": [
                    {"title": "Şarkı 1", "subtitle": "Sanatçı A,\xa0Sanatçı B"},
                    {"title": "Şarkı 2", "subtitle": "Sanatçı C"},
                ],
            }}}}},
        })
        + "</script></html>"
    )

    class FakeResp:
        def __init__(self, status_code, text="", json_data=None):
            self.status_code = status_code
            self.ok = status_code == 200
            self.text = text
            self._json = json_data or {}

        def json(self):
            return self._json

    # 1) Client ID boşken doğrudan embed çalışmalı
    monkeypatch.setattr(sp.requests, "get", lambda url, **kw: FakeResp(200, embed_html))
    name, queries = sp.fetch_spotify_playlist("37i9dQZF1DXcBWIGoYBM5M", "", "", {}, lambda: None)
    assert name == "Başkasının Listesi"
    assert queries == ["Sanatçı A, Sanatçı B - Şarkı 1", "Sanatçı C - Şarkı 2"]

    # 2) Client ID varken API 403 döndürürse (başka kullanıcının listesi) otomatik embed'e düşmeli
    monkeypatch.setattr(sp, "get_spotify_user_access_token", lambda *a: "tok")

    def fake_get(url, **kw):
        if "open.spotify.com/embed" in url:
            return FakeResp(200, embed_html)
        return FakeResp(403, '{"error":{"message":"Forbidden"}}', {"error": {"message": "Forbidden"}})

    monkeypatch.setattr(sp.requests, "get", fake_get)
    name2, queries2 = sp.fetch_spotify_playlist("37i9dQZF1DXcBWIGoYBM5M", "cid", "", {}, lambda: None)
    assert name2 == "Başkasının Listesi"
    assert len(queries2) == 2

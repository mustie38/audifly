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

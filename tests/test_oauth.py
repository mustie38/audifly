import threading
import urllib.parse
from http.server import HTTPServer

import requests

from mustiefly_qt.helpers import spotify_import as spotify


def test_oauth_rejects_wrong_state_and_favicon_then_accepts_valid_callback(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), spotify._SpotifyCallbackHandler)
    monkeypatch.setattr(spotify, "HTTPServer", lambda *args: server)
    statuses, browser_urls = [], []
    browser_thread = None
    def open_browser(url):
        nonlocal browser_thread
        browser_urls.append(url)
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        base = f"http://127.0.0.1:{server.server_port}"
        def callbacks():
            for path in ["/favicon.ico", "/callback?code=evil&state=wrong",
                         f"/callback?code=expected&state={state}"]:
                statuses.append(requests.get(base + path, timeout=2).status_code)
        browser_thread = threading.Thread(target=callbacks)
        browser_thread.start()
        return True
    monkeypatch.setattr(spotify.webbrowser, "open", open_browser)
    code, error = spotify.spotify_authorize_interactive("dummy-id", timeout=3)
    browser_thread.join(3)
    assert not browser_thread.is_alive()
    assert code == "expected" and error is None
    assert statuses == [404, 400, 200]
    assert server.socket.fileno() == -1


def test_browser_failure_closes_listener(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), spotify._SpotifyCallbackHandler)
    monkeypatch.setattr(spotify, "HTTPServer", lambda *args: server)
    monkeypatch.setattr(spotify.webbrowser, "open", lambda url: False)
    code, error = spotify.spotify_authorize_interactive("dummy-id")
    assert code is None and error
    assert server.socket.fileno() == -1


def test_timeout_closes_listener(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), spotify._SpotifyCallbackHandler)
    monkeypatch.setattr(spotify, "HTTPServer", lambda *args: server)
    monkeypatch.setattr(spotify.webbrowser, "open", lambda url: True)
    code, error = spotify.spotify_authorize_interactive("dummy-id", timeout=0.02)
    assert code is None and "Zaman aşımı" in error
    assert server.socket.fileno() == -1


def test_pkce_pair_is_valid_s256():
    import base64, hashlib
    v, c = spotify.make_pkce_pair()
    assert 43 <= len(v) <= 128
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def test_token_exchange_uses_pkce_without_secret(monkeypatch):
    calls = []

    class R:
        ok = True
        def json(self):
            return {"access_token": "A", "refresh_token": "RT"}

    monkeypatch.setattr(spotify.requests, "post", lambda url, **kw: calls.append(kw) or R())
    seen = {}
    monkeypatch.setattr(spotify, "spotify_authorize_interactive",
                        lambda cid, code_challenge=None, **k: seen.update(ch=code_challenge) or ("CODE", None))
    settings, saved = {}, []
    token = spotify.get_spotify_user_access_token("cid", "", settings, lambda: saved.append(1))
    assert token == "A" and settings["spotify_refresh_token"] == "RT" and saved
    data = calls[0]["data"]
    assert data["client_id"] == "cid" and "auth" not in calls[0]
    assert seen["ch"] and data["code_verifier"]


def test_refresh_with_legacy_secret_uses_basic_auth(monkeypatch):
    calls = []

    class R:
        ok = True
        def json(self):
            return {"access_token": "A"}

    monkeypatch.setattr(spotify.requests, "post", lambda url, **kw: calls.append(kw) or R())
    spotify.get_spotify_user_access_token("cid", "sec", {"spotify_refresh_token": "x"}, lambda: None)
    assert calls[0]["auth"] == ("cid", "sec")

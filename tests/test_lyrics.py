import pytest
import requests

from mustiefly_qt.helpers import lyrics as ly

LRC = """[ar:Sanatçı]
[offset:+500]
[00:01.00]Birinci
[00:03.50][01:00.00]Tekrarlı satır
[00:05]Saniyeli
[bozuk
[00:75.00]geçersiz saniye
"""


def test_parse_lrc_handles_multi_stamps_offset_and_garbage():
    rows = ly.parse_lrc(LRC)
    assert rows == [(1500, "Birinci"), (4000, "Tekrarlı satır"), (5500, "Saniyeli"),
                    (60500, "Tekrarlı satır")]
    assert ly.parse_lrc("") == [] and ly.parse_lrc(None) == []


def test_current_line_index():
    rows = ly.parse_lrc("[00:01.00]a\n[00:03.00]b")
    assert [ly.current_line_index(rows, p) for p in (0, 999, 1000, 2999, 3000, 99999)] == [-1, -1, 0, 0, 1, 1]


def test_guess_track_from_youtube_titles():
    assert ly.guess_track("Ceza - Holocaust (Official Video)", "CezaVEVO") == ("Holocaust", "Ceza")
    assert ly.guess_track("Yalnızım Dostum [Lyrics]", "Mabel Matiz - Topic") == ("Yalnızım Dostum", "Mabel Matiz")
    assert ly.guess_track("Bir Şarkı", "Kanal") == ("Bir Şarkı", "Kanal")
    # Bengü - Saat 3 uploaded by Avrupa Müzik
    assert ly.parse_track_and_artist("Bengü - Saat 3 (Official Video)", "Avrupa Müzik") == ("Saat 3", "Bengü")
    assert ly.parse_track_and_artist("Bengü - Saat 3 | Video Klip", "netd müzik") == ("Saat 3", "Bengü")
    assert ly.parse_track_and_artist("Motive - HANIMEFENDİ", "Motive") == ("HANIMEFENDİ", "Motive")


def cand(name, artist, dur, synced=True):
    return {"trackName": name, "artistName": artist, "duration": dur,
            "plainLyrics": "düz", "syncedLyrics": "[00:01.00]x" if synced else None}


def test_pick_best_rejects_wrong_song_and_wrong_duration():
    wrong = [cand("Başka Şarkı", "Ceza", 200), cand("Holocaust", "Ceza", 300)]
    assert ly.pick_best(wrong, "Holocaust", "Ceza", 200) is None     # süre 100 sn farklı
    good = [cand("Holocaust (Live)", "Ceza", 199, False), cand("Holocaust", "Ceza", 200)]
    assert ly.pick_best(good, "Holocaust", "Ceza", 200)["duration"] == 200
    other = [cand("Holocaust", "Tamamen Başka", 200)]
    assert ly.pick_best(other, "Holocaust", "Ceza", 0) is None           # süre yok → riskli, reddet
    assert ly.pick_best(other, "Holocaust", "Ceza", 230) is None         # süre uymuyor
    assert ly.pick_best(other, "Holocaust", "Kanal Adı", 200) is not None  # tam başlık + süre


class FakeResp:
    def __init__(self, code, data):
        self.status_code, self._d = code, data

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeHttp:
    def __init__(self, get=None, search=None, boom=False):
        self.get_r, self.search_r, self.boom, self.calls = get, search, boom, []

    def get(self, url, **kw):
        self.calls.append(url)
        if self.boom:
            raise requests.ConnectionError("yok")
        return self.get_r if url.endswith("/get") else self.search_r


def test_exact_match_returns_synced_and_plain(tmp_path):
    http = FakeHttp(get=FakeResp(200, cand("Holocaust", "Ceza", 200)))
    r = ly.fetch_lyrics_result("Ceza - Holocaust", "CezaVEVO", 200, str(tmp_path), http)
    assert r.status == ly.FOUND and r.synced == [(1000, "x")] and r.plain == "düz"
    assert http.calls == [f"{ly.API}/get"]


def test_network_error_is_not_cached_and_not_found_is_cached(tmp_path):
    bad = FakeHttp(boom=True)
    assert ly.fetch_lyrics_result("Şarkı", "Sanatçı", 100, str(tmp_path), bad).status == ly.ERROR
    assert not list(tmp_path.iterdir())
    empty = FakeHttp(get=FakeResp(404, {}), search=FakeResp(200, []))
    assert ly.fetch_lyrics_result("Şarkı", "Sanatçı", 100, str(tmp_path), empty).status == ly.NOT_FOUND
    offline = FakeHttp(boom=True)
    assert ly.fetch_lyrics_result("Şarkı", "Sanatçı", 100, str(tmp_path), offline).status == ly.NOT_FOUND
    assert offline.calls == []        # önbellekten geldi


def test_instrumental_and_plain_only(tmp_path):
    http = FakeHttp(get=FakeResp(404, {}), search=FakeResp(200, [
        {**cand("Enstrümantal", "X", 100, False), "instrumental": True}]))
    r = ly.fetch_lyrics_result("Enstrümantal", "X", 100, None, http)
    assert r.instrumental and not r.has_text
    http2 = FakeHttp(search=FakeResp(200, [cand("Düz", "X", 0, False)]))
    r2 = ly.fetch_lyrics_result("Düz", "X", 0, None, http2)
    assert r2.plain == "düz" and r2.synced == []

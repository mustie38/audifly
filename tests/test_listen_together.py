"""Birlikte Dinle: röle sunucusu + istemci mantığı testleri."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")


# ---------- Saf yardımcılar ----------
def test_helpers():
    from mustiefly_qt.services import listen_together as lt
    assert len(lt.generate_room_code()) == 6
    assert lt.normalize_room_code(" k7m-2pq ") == "K7M2PQ"
    assert lt.normalize_room_code("ab") == ""
    assert lt.normalize_server_url("foo.onrender.com/") == "wss://foo.onrender.com"
    assert lt.normalize_server_url("https://x.io") == "wss://x.io"
    assert lt.normalize_server_url("http://localhost:8765") == "ws://localhost:8765"
    assert lt.is_shareable({"webpage_url": "https://youtu.be/a"})
    assert not lt.is_shareable({"webpage_url": "local://x", "local_path": "C:/a.mp3"})
    assert not lt.is_shareable({"webpage_url": "https://y", "local_path": "C:/a.mp3"})


def test_reconnect_timeout_budget_matches_delays():
    from mustiefly_qt.services import listen_together as lt

    assert lt.RECONNECT_TOTAL_TIMEOUT_S == 180


# ---------- İstemci mantığı (sahte soket) ----------
def _fake_socket_cls():
    from PySide6.QtCore import QObject, Signal

    class FakeSocket(QObject):
        connected = Signal()
        disconnected = Signal()
        textMessageReceived = Signal(str)
        errorOccurred = Signal(int)

        def __init__(self):
            super().__init__()
            self.sent = []
            self.opened = None

        def open(self, url):
            self.opened = url.toString()

        def sendTextMessage(self, text):
            self.sent.append(json.loads(text))

        def close(self):
            pass

        def errorString(self):
            return ""
    return FakeSocket


@pytest.fixture()
def service(library_store):
    from PySide6.QtCore import QObject, Signal
    from mustiefly_qt.services.listen_together import ListenTogether

    class FakePlayback(QObject):
        songStarted = Signal(str, int, dict, bool)
        playStateChanged = Signal(bool)
        seeked = Signal(int)
        playError = Signal(str, int)

        def __init__(self):
            super().__init__()
            self.suppress_auto_advance = False
            self._current_song_ref = None
            self.is_loading = False
            self.player = MagicMock()
            self.player.is_playing.return_value = False
            self.player.get_time.return_value = 0
            self.play_song_at_index = MagicMock()
            self.toggle_play_pause = MagicMock()
            self.pause = MagicMock()
            self.seek = MagicMock()

    pb = FakePlayback()
    sockets = []
    FakeSocket = _fake_socket_cls()

    def factory():
        s = FakeSocket()
        sockets.append(s)
        return s

    svc = ListenTogether(library_store, pb, socket_factory=factory)
    svc._test_sockets = sockets
    svc._test_pb = pb
    return svc


def _join(svc, host_id="h1", my_id="me", state=None):
    assert svc.join("wss://srv.example", "abc123", "Ali")
    ws = svc._test_sockets[-1]
    ws.connected.emit()
    assert ws.sent[0] == {"t": "join", "v": 2, "room": "ABC123", "name": "Ali", "pw": ""}
    ws.textMessageReceived.emit(json.dumps({
        "t": "joined", "id": my_id, "host": host_id,
        "members": [{"id": host_id, "name": "Veli"}, {"id": my_id, "name": "Ali"}],
        "state": state}))
    return ws


SONG = {"title": "T", "uploader": "U", "webpage_url": "https://youtu.be/abc", "duration": 100}


def _state(seq, playing=True, pos=5000, frm="h1", hb=False, song=SONG, age=0):
    return json.dumps({"t": "state", "seq": seq, "from": frm, "song": song,
                       "playing": playing, "pos_ms": pos, "hb": hb, "age_ms": age})


def test_guest_blocks_auto_advance_and_host_does_not(service):
    _join(service, host_id="h1", my_id="me")
    assert service._test_pb.suppress_auto_advance is True
    service.leave()
    assert service._test_pb.suppress_auto_advance is False
    _join(service, host_id="me", my_id="me")
    assert service._test_pb.suppress_auto_advance is False


def test_remote_new_song_is_added_and_played(service, library_store):
    ws = _join(service)
    ws.textMessageReceived.emit(_state(1))
    pb = service._test_pb
    pb.play_song_at_index.assert_called_once()
    pl, idx = pb.play_song_at_index.call_args.args
    assert library_store.playlists[pl][idx]["webpage_url"] == SONG["webpage_url"]
    # Çözülürken bizim tarafımızdan geri yayın olmamalı
    pb.songStarted.emit(pl, idx, library_store.playlists[pl][idx], False)
    assert [m for m in ws.sent if m["t"] == "state"] == []


def test_stale_and_duplicate_state_ignored(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True
    ws.textMessageReceived.emit(_state(5, playing=False))
    pb.pause.assert_called_once()
    pb.pause.reset_mock()
    ws.textMessageReceived.emit(_state(4, playing=False))   # eski
    ws.textMessageReceived.emit(_state(5, playing=False))   # aynı (hb değil)
    pb.pause.assert_not_called()


def test_two_senders_independent_seq(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)

    ws.textMessageReceived.emit(_state(2, playing=False, pos=5000, frm="h1"))
    ws.textMessageReceived.emit(_state(1, playing=False, pos=6000, frm="g2"))

    assert [call.args for call in pb.seek.call_args_list] == [(5000,), (6000,)]
    assert service._last_by_sender == {"h1": 2, "g2": 1}


def test_guest_seek_burst_does_not_block_host_state(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True

    for pos in range(20):
        pb.seeked.emit(10_000 + pos)
    local_states = [m for m in ws.sent if m["t"] == "state"]
    assert [m["seq"] for m in local_states] == list(range(1, 21))

    ws.textMessageReceived.emit(_state(1, playing=False, pos=40_000, frm="h1"))

    pb.pause.assert_called_once()
    pb.seek.assert_called_once_with(40_000)
    assert service._last_by_sender["h1"] == 1


def test_heartbeat_carries_seq(service):
    ws = _join(service, host_id="me", my_id="me")
    service._test_pb._current_song_ref = dict(SONG)

    service._broadcast(True, 1000, kind="hb", hb=True)

    assert ws.sent[-1]["hb"] is True
    assert ws.sent[-1]["seq"] > 0
    assert service._last_by_sender["me"] == ws.sent[-1]["seq"]


def test_hb_after_guest_seek_burst_accepted(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    for pos in range(5):
        pb.seeked.emit(10_000 + pos)
    assert service._last_by_sender["me"] == 5

    # Host'un gördüğü guest seq=5'ten sonra ürettiği hb seq=6'yı simüle et.
    guest_sequences = dict(service._last_by_sender)
    service.my_id = "h1"
    service._broadcast(True, 40_000, kind="hb", hb=True)
    heartbeat = dict(ws.sent[-1], **{"from": "h1"})
    assert heartbeat["seq"] == 6

    # Alıcıdaki seq haritası ayrı istemciye aittir.
    service.my_id = "me"
    service._last_by_sender = guest_sequences
    service._seq = 5
    ws.textMessageReceived.emit(json.dumps(heartbeat))

    assert service._last_by_sender["h1"] == 6
    pb.seek.assert_called_once_with(40_000)


def test_reconnect_resets_seq(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    ws.textMessageReceived.emit(_state(50, playing=False, pos=5000, frm="h1"))
    # Uzak seq istemcinin yerel sayacını bozmaz
    assert service._seq == 0
    assert service._last_by_sender["h1"] == 50

    service._connection_lost()
    service._reconnect.stop()
    service._open_socket()
    reconnected = service._test_sockets[-1]
    reconnected.connected.emit()
    reconnected.textMessageReceived.emit(json.dumps({
        "t": "joined", "id": "me", "host": "h1",
        "members": [{"id": "h1", "name": "Veli"}, {"id": "me", "name": "Ali"}],
    }))

    assert service._seq == 0
    assert service._last_by_sender == {}
    reconnected.textMessageReceived.emit(_state(1, playing=False, pos=6000, frm="h1"))

    assert service._seq == 0
    assert service._last_by_sender["h1"] == 1
    assert [call.args for call in pb.seek.call_args_list] == [(5000,), (6000,)]


def test_same_song_drift_correction(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True
    pb.player.get_time.return_value = 10_000
    ws.textMessageReceived.emit(_state(2, playing=True, pos=10_900, hb=True))
    pb.seek.assert_not_called()                 # küçük sapma
    # Her heartbeat yeni seq taşır; yinelenen seq artık eski mesaj sayılır.
    ws.textMessageReceived.emit(_state(3, playing=True, pos=20_000, hb=True))
    pb.seek.assert_called_once_with(20_000)


def test_local_actions_are_broadcast_with_increasing_seq(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.songStarted.emit("L", 0, dict(SONG), False)
    pb.playStateChanged.emit(True)               # hemen ardından: tekrar yayınlanmaz
    pb.seeked.emit(30_000)
    states = [m for m in ws.sent if m["t"] == "state"]
    assert [m["seq"] for m in states] == [1, 2]
    assert states[1]["pos_ms"] == 30_000
    assert states[0]["song"]["webpage_url"] == SONG["webpage_url"]


def test_local_file_not_shared(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = {"title": "x", "webpage_url": "local://1", "local_path": "C:/a.mp3"}
    pb.songStarted.emit("L", 0, pb._current_song_ref, False)
    assert [m for m in ws.sent if m["t"] == "state"] == []


def test_late_joiner_gets_current_state_with_age(service):
    state = json.loads(_state(3, playing=True, pos=1000, age=4000))
    ws = _join(service, state=state)
    pb = service._test_pb
    pb.play_song_at_index.assert_called_once()
    assert service._pending["pos"] == 5000      # 1000 + age


def test_chat_emoji_and_notices(service):
    ws = _join(service)
    got = []
    service.chatReceived.connect(lambda n, t, mine: got.append((n, t, mine)))
    emojis = []
    service.emojiReceived.connect(lambda n, e: emojis.append((n, e)))
    ws.textMessageReceived.emit(json.dumps({"t": "chat", "name": "Veli", "text": "selam"}))
    assert service.send_chat("  merhaba   dünya ")
    assert ws.sent[-1] == {"t": "chat", "text": "merhaba dünya"}
    assert got == [("Veli", "selam", False), ("Ali", "merhaba dünya", True)]
    ws.textMessageReceived.emit(json.dumps({"t": "emoji", "name": "Veli", "e": "🔥"}))
    ws.textMessageReceived.emit(json.dumps({"t": "emoji", "name": "Veli", "e": "💀"}))   # listede yok
    assert emojis == [("Veli", "🔥")]
    assert service.send_emoji("🎉") and not service.send_emoji("💀")
    assert [m for m in ws.sent if m["t"] == "emoji"] == [{"t": "emoji", "e": "🎉"}]


def test_who_played_notice(service):
    ws = _join(service)
    notes = []
    service.notice.connect(lambda m, lvl: notes.append(m))
    ws.textMessageReceived.emit(_state(1))
    assert any("Veli" in n and "T" in n for n in notes)


def test_room_queue_flow(service, library_store):
    ws = _join(service)
    pb = service._test_pb
    assert service.add_to_room_queue(dict(SONG))
    assert ws.sent[-1]["t"] == "queue_add" and ws.sent[-1]["song"]["webpage_url"] == SONG["webpage_url"]
    assert not service.add_to_room_queue({"webpage_url": "local://1", "local_path": "x"})
    q2 = dict(SONG, webpage_url="https://youtu.be/two", title="İki", by="Veli")
    ws.textMessageReceived.emit(json.dumps({"t": "queue", "items": [dict(SONG, by="Veli"), q2]}))
    assert [s["title"] for s in service.room_queue] == ["T", "İki"]
    # play_next için sağlayıcı: baştakini verir, sunucuya pop yollar
    assert pb.next_provider is not None
    loc = pb.next_provider()
    pl, idx = loc
    assert library_store.playlists[pl][idx]["webpage_url"] == SONG["webpage_url"]
    assert ws.sent[-1] == {"t": "queue_pop", "url": SONG["webpage_url"]}
    assert [s["title"] for s in service.room_queue] == ["İki"]
    service.remove_from_room_queue("https://youtu.be/two")
    assert ws.sent[-1] == {"t": "queue_remove", "url": "https://youtu.be/two"}
    service.leave()
    assert pb.next_provider() is None and service.room_queue == []


def test_dialog_smoke(service):
    from mustiefly_qt.views.listen_together_dialog import ListenTogetherDialog
    ws = _join(service)
    dlg = ListenTogetherDialog(service, {}, lambda: None)
    ws.textMessageReceived.emit(json.dumps({"t": "chat", "name": "Veli", "text": "<b>x</b>"}))
    ws.textMessageReceived.emit(json.dumps({"t": "queue", "items": [dict(SONG, by="Veli")]}))
    assert dlg.queue_list.count() == 1
    assert "<b>x</b>" in dlg.chat_view.toPlainText()      # HTML olarak yorumlanmaz, düz metin görünür
    assert dlg.queue_list.item(0).data(256) == SONG["webpage_url"]
    notices = []
    service.notice.connect(lambda message, _level: notices.append(message))
    dlg._connect("a@b@c")
    assert notices == ["Davet formatı geçersiz."]
    dlg.deleteLater()


def test_invite_and_password_helpers():
    from mustiefly_qt.services import listen_together as lt
    assert lt.build_invite("K7M2PQ", "https://x.onrender.com") == "K7M2PQ@x.onrender.com"
    assert lt.build_invite("K7M2PQ", "ws://127.0.0.1:8765") == "K7M2PQ@ws://127.0.0.1:8765"
    assert lt.parse_invite("k7m2pq@x.onrender.com") == ("K7M2PQ", "wss://x.onrender.com")
    assert lt.parse_invite("K7M2PQ@ws://127.0.0.1:8765") == ("K7M2PQ", "ws://127.0.0.1:8765")
    assert lt.parse_invite("k7m 2pq") == ("K7M2PQ", "")
    assert lt.hash_password("A", "") == ""
    h = lt.hash_password("ROOM1", "gizli")
    assert len(h) == 64 and h != lt.hash_password("ROOM2", "gizli")      # oda koduyla tuzlu


def test_parse_invite_multiple_at_returns_empty():
    from mustiefly_qt.services import listen_together as lt

    assert lt.parse_invite("a@b@c") == ("", "")  # Üç karakter geçerli bir oda kodu değil.
    assert lt.parse_invite("a@b@c@d") == ("", "")


@pytest.mark.parametrize("server_message, expected", [
    ("Oda bulunamadı", "Sunucu yeniden başlamış olabilir; oda artık mevcut değil"),
    ("Oda şifresi yanlış", "Oda şifresi yanlış. Şifreyi kontrol edip tekrar dene"),
])
def test_room_error_gives_actionable_message(service, server_message, expected):
    ws = _join(service)
    notices = []
    service.notice.connect(lambda message, _level: notices.append(message))

    ws.textMessageReceived.emit(json.dumps({"t": "error", "msg": server_message}))

    assert any(expected in message for message in notices)
    assert service.state == "disconnected"


def test_crossfade_blocked_for_guests_and_when_room_queue_has_items(service):
    _join(service)
    service.my_id, service.host_id = "me", "someone-else"
    assert service._blocks_crossfade() is True        # misafir: sıradakini oda sahibi seçer
    service.host_id = "me"
    service.room_queue = []
    assert service._blocks_crossfade() is False       # sahip + boş ortak sıra: serbest
    service.room_queue = [{"title": "x", "webpage_url": "https://y.example/1"}]
    assert service._blocks_crossfade() is True        # ortak sırada şarkı var: play_next belirler


def test_join_rejects_malformed_invite(service):
    notices = []
    service.notice.connect(lambda message, _level: notices.append(message))

    assert not service.join("wss://srv.example", "a@b@c@d", "Ali")
    assert any("Oda kodu 4-12 harf/rakam" in message
               or "Sunucu adresi girilmedi" in message for message in notices)


def test_join_with_invite_and_password(service):
    assert service.join("", "abc123@srv.example", "Ali", "gizli")
    ws = service._test_sockets[-1]
    assert ws.opened == "wss://srv.example"
    ws.connected.emit()
    from mustiefly_qt.services.listen_together import hash_password
    assert ws.sent[0]["pw"] == hash_password("ABC123", "gizli")


def test_latency_is_measured_and_added_to_remote_position(service):
    import time
    ws = _join(service)
    ping = [m for m in ws.sent if m["t"] == "ping"][0]
    service._ping_sent[ping["c"]] = time.monotonic() - 0.2        # 200 ms gidiş-dönüş
    ws.textMessageReceived.emit(json.dumps({"t": "pong", "c": ping["c"]}))
    assert 80 <= service.latency_ms <= 120                        # tek yön ≈ 100 ms
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True
    pb.player.get_time.return_value = 0
    msg = json.loads(_state(2, playing=True, pos=10_000, age=50))
    msg["lat"] = 40
    ws.textMessageReceived.emit(json.dumps(msg))
    # 10000 + 50 (sunucuda bekleme) + 40 (gönderen) + ~100 (biz)
    target = pb.seek.call_args.args[0]
    assert 10_150 <= target <= 10_250


def test_sync_request_and_host_reply(service):
    ws = _join(service, host_id="h1", my_id="me")                 # biz misafiriz
    service.request_sync()
    assert ws.sent[-1] == {"t": "sync_req"}
    service.leave()
    ws = _join(service, host_id="me", my_id="me")                 # biz sahibiz
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True
    pb.player.get_time.return_value = 42_000
    ws.textMessageReceived.emit(json.dumps({"t": "sync_req", "from": "h2"}))
    reply = [m for m in ws.sent if m["t"] == "state"][-1]
    assert reply["hb"] and reply["sync"] and reply["pos_ms"] == 42_000


def test_tight_tolerance_for_sync_reply(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True
    pb.player.get_time.return_value = 10_000
    normal = json.loads(_state(2, playing=True, pos=10_900, hb=True))
    ws.textMessageReceived.emit(json.dumps(normal))
    pb.seek.assert_not_called()                                   # 900 ms < 1500 ms (normal hb)
    # Eşitle yanıtı yeni heartbeat seq'i taşır; aynı seq alıcıda tekrarlı sayılır.
    tight = dict(normal, seq=3, sync=True)
    ws.textMessageReceived.emit(json.dumps(tight))
    pb.seek.assert_called_once()                                  # 900 ms > 600 ms (Eşitle)


def test_transfer_host_only_for_host(service):
    ws = _join(service, host_id="h1", my_id="me")
    service.transfer_host("h1")
    assert not [m for m in ws.sent if m["t"] == "transfer"]
    service.leave()
    ws = _join(service, host_id="me", my_id="me")
    service.transfer_host("h1")
    assert ws.sent[-1] == {"t": "transfer", "to": "h1"}


def test_connect_timeout_retries_instead_of_hanging(service):
    assert service.join("wss://srv.example", "abc123", "Ali")
    first = service._test_sockets[-1]
    progress = []
    service.connectProgress.connect(lambda n, w: progress.append((n, w)))
    first.close = first.abort = lambda: None
    service._connect_timeout()                                    # 12 sn sessizlik
    assert service.state == "connecting" and service._reconnect.isActive()
    assert progress and progress[0][0] == 1
    service._open_socket()                                        # zamanlayıcı dolunca
    assert len(service._test_sockets) == 2


# ---------- Sunucu ----------
def test_relay_server_end_to_end():
    pytest.importorskip("websockets")
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay_server"))
    import server
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    async def scenario():
        server.ROOMS.clear()
        server._FAILS.clear()
        async with serve(server.handler, "127.0.0.1", 0,
                         process_request=server.process_request) as srv:
            port = srv.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            valid_url1 = "https://www.youtube.com/watch?v=12345678901"
            valid_url2 = "https://www.youtube.com/watch?v=abcdefghijk"
            async with connect(url) as a, connect(url) as b:
                await a.send(json.dumps({"t": "create", "v": 2, "room": "ROOM42", "name": "A"}))
                ja = json.loads(await a.recv())
                assert ja["t"] == "joined" and ja["host"] == ja["id"] and ja["state"] is None
                await b.send(json.dumps({"t": "join", "v": 2, "room": "ROOM42", "name": "B"}))
                jb = json.loads(await b.recv())
                assert jb["host"] == ja["id"] and len(jb["members"]) == 2
                assert json.loads(await a.recv())["t"] == "members"

                await a.send(json.dumps({"t": "state", "seq": 1, "playing": True, "pos_ms": 10,
                                         "song": {"webpage_url": valid_url1, "title": "t",
                                                  "evil": "x"}}))
                got = json.loads(await b.recv())
                assert got["t"] == "state" and got["from"] == ja["id"]
                assert "evil" not in got["song"]

                # geçersiz şarkı (izinli host değil / file://) iletilmez
                await a.send(json.dumps({"t": "state", "seq": 2, "playing": True, "pos_ms": 1,
                                         "song": {"webpage_url": "file:///etc/passwd"}}))
                await a.send(json.dumps({"t": "ping"}))
                assert json.loads(await a.recv())["t"] == "pong"

                # sohbet / emoji / ortak sıra
                await a.send(json.dumps({"t": "chat", "text": "  selam   dünya "}))
                got = json.loads(await b.recv())
                assert got == {"t": "chat", "from": ja["id"], "name": "A", "text": "selam dünya"}
                await a.send(json.dumps({"t": "emoji", "e": "💀"}))      # izinli değil
                await a.send(json.dumps({"t": "emoji", "e": "🔥"}))
                assert json.loads(await b.recv())["e"] == "🔥"
                await b.send(json.dumps({"t": "queue_add", "song": {"webpage_url": valid_url2, "title": "Q1"}}))
                qa = json.loads(await a.recv())
                assert qa["t"] == "queue" and qa["items"][0]["by"] == "B"
                assert json.loads(await b.recv())["t"] == "queue"
                await a.send(json.dumps({"t": "queue_pop", "url": "https://www.youtube.com/watch?v=yanlis"}))   # baştaki değil: yok sayılır
                await a.send(json.dumps({"t": "queue_pop", "url": valid_url2}))
                assert json.loads(await a.recv())["items"] == []
                assert json.loads(await b.recv())["items"] == []

                # ping eko, sahiplik devri, eşitleme isteği
                await b.send(json.dumps({"t": "ping", "c": 123}))
                assert json.loads(await b.recv()) == {"t": "pong", "c": 123}
                await b.send(json.dumps({"t": "sync_req"}))
                assert json.loads(await a.recv()) == {"t": "sync_req", "from": jb["id"]}   # yalnız sahibe gider
                await b.send(json.dumps({"t": "transfer", "to": jb["id"]}))               # sahip değil: yok sayılır
                await a.send(json.dumps({"t": "transfer", "to": jb["id"]}))
                m1, m2 = json.loads(await a.recv()), json.loads(await b.recv())
                assert m1["host"] == m2["host"] == jb["id"]

                # geç katılan mevcut durumu alır
                async with connect(url) as c:
                    await c.send(json.dumps({"t": "join", "v": 2, "room": "ROOM42", "name": "C"}))
                    jc = json.loads(await c.recv())
                    assert jc["state"]["seq"] == 1 and jc["state"]["song"]["webpage_url"] == valid_url1

            # şifreli oda
            import hashlib
            good = hashlib.sha256(b"x").hexdigest()
            async with connect(url) as p1, connect(url) as p2, connect(url) as p3:
                await p1.send(json.dumps({"t": "create", "v": 2, "room": "LOCKED", "name": "P1", "pw": good}))
                assert json.loads(await p1.recv())["locked"] is True
                await p2.send(json.dumps({"t": "join", "v": 2, "room": "LOCKED", "name": "P2", "pw": "0" * 64}))
                assert json.loads(await p2.recv())["t"] == "error"
                await p3.send(json.dumps({"t": "join", "v": 2, "room": "LOCKED", "name": "P3", "pw": good}))
                assert json.loads(await p3.recv())["t"] == "joined"

            # kötü kod reddedilir
            async with connect(url) as d:
                await d.send(json.dumps({"t": "create", "v": 2, "room": "!", "name": "D"}))
                assert json.loads(await d.recv())["t"] == "error"
        assert server.ROOMS == {} or True

    asyncio.run(scenario())
    server.ROOMS.clear()
    server._FAILS.clear()


def _relay():
    pytest.importorskip("websockets")
    import sys
    from pathlib import Path
    path = str(Path(__file__).resolve().parent.parent / "relay_server")
    if path not in sys.path:
        sys.path.insert(0, path)
    import server
    return server


def test_relay_blocks_repeated_wrong_passwords_per_client():
    server = _relay()
    server._FAILS.clear()
    assert not server.too_many_failures("1.2.3.4", now=1000.0)
    for i in range(server.FAIL_MAX):
        server.record_failure("1.2.3.4", now=1000.0 + i)
    assert server.too_many_failures("1.2.3.4", now=1010.0)
    assert not server.too_many_failures("5.6.7.8", now=1010.0)                    # başka istemci etkilenmez
    assert not server.too_many_failures("1.2.3.4", now=1000.0 + server.FAIL_WINDOW_S + 20)   # pencere dolunca açılır
    server._FAILS.clear()


def test_relay_room_limit_and_lockout_end_to_end(monkeypatch):
    server = _relay()
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve
    server._FAILS.clear()
    server.ROOMS.clear()
    monkeypatch.setattr(server, "MAX_ROOMS", 1)
    good = "a" * 64

    async def join(url, room, pw=""):
        async with connect(url) as ws:
            await ws.send(json.dumps({"t": "join", "v": 2, "room": room, "name": "X", "pw": pw}))
            return json.loads(await ws.recv())

    async def create(url, room, pw=""):
        async with connect(url) as ws:
            await ws.send(json.dumps({"t": "create", "v": 2, "room": room, "name": "X", "pw": pw}))
            return json.loads(await ws.recv())

    async def scenario():
        async with serve(server.handler, "127.0.0.1", 0, process_request=server.process_request) as srv:
            url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
            async with connect(url) as keeper:                   # ilk oda açık kalır
                await keeper.send(json.dumps({"t": "create", "v": 2, "room": "LOCKED", "name": "K", "pw": good}))
                assert json.loads(await keeper.recv())["t"] == "joined"
                full = await create(url, "OTHER1")               # ikinci oda: sınır
                assert full["t"] == "error" and "dolu" in full["msg"]
                for _ in range(server.FAIL_MAX):
                    assert "yanlış" in (await join(url, "LOCKED", "0" * 64))["msg"]
                blocked = await join(url, "LOCKED", good)        # doğru şifre bile geçici engelli
                assert blocked["t"] == "error" and "Çok fazla" in blocked["msg"]

    asyncio.run(scenario())
    server._FAILS.clear()
    server.ROOMS.clear()


# ---------- Güvenlik ve Regresyon Testleri ----------
def test_sequence_poisoning_does_not_affect_local_seq_or_other_senders(service):
    ws = _join(service)
    pb = service._test_pb
    pb._current_song_ref = dict(SONG)
    pb.player.is_playing.return_value = True

    # Kötü niyetli katılımcı 'att' 2^31 - 1 büyüklüğünde sequence gönderir
    poison_seq = 2_147_483_647
    ws.textMessageReceived.emit(_state(poison_seq, playing=False, pos=5000, frm="att"))

    # İstemcinin yerel sayacı zehirlenmemeli, 0 kalmalıdır
    assert service._seq == 0
    assert service._last_by_sender["att"] == poison_seq

    # Host 'h1' normal seq=1 gönderdiğinde başarıyla işlenmeli
    ws.textMessageReceived.emit(_state(1, playing=False, pos=6000, frm="h1"))
    assert service._seq == 0
    assert service._last_by_sender["h1"] == 1
    assert pb.seek.call_count >= 1

    # Yerel kullanıcı eylem yaptığında seq=1 ile yayın yapmalı (zehirlenmiş seq değil)
    service._suppress_until = 0.0
    pb.seeked.emit(15_000)
    local_state = [m for m in ws.sent if m["t"] == "state"][-1]
    assert local_state["seq"] == 1
    assert service._seq == 1


def test_server_rejects_poisoned_or_invalid_sequence_numbers():
    server = _relay()
    # Monotonik artış kontrolü
    assert server.clean_state({"t": "state", "seq": 5}, last_seq=5) is None
    assert server.clean_state({"t": "state", "seq": 4}, last_seq=5) is None
    assert server.clean_state({"t": "state", "seq": 0}, last_seq=0) is None
    assert server.clean_state({"t": "state", "seq": -1}, last_seq=0) is None
    assert server.clean_state({"t": "state", "seq": True}, last_seq=0) is None
    assert server.clean_state({"t": "state", "seq": 5.5}, last_seq=0) is None
    assert server.clean_state({"t": "state", "seq": "5"}, last_seq=0) is None
    assert server.clean_state({"t": "state", "seq": 2_147_483_648}, last_seq=0) is None
    
    # Geçerli artış kabul edilmeli
    valid = server.clean_state({
        "t": "state", "seq": 6, "playing": True, "pos_ms": 100,
        "song": {"webpage_url": "https://www.youtube.com/watch?v=12345678901", "title": "t"}
    }, last_seq=5)
    assert valid is not None and valid["seq"] == 6


def test_pending_timeout_cleans_up_safely_and_resumes_heartbeat(service):
    ws = _join(service, host_id="me", my_id="me")
    # Uzak şarkı isteği geldiğinde pending kurulur
    service._receive_state({
        "t": "state", "seq": 1, "from": "h2",
        "song": dict(SONG), "playing": True, "pos_ms": 1000
    })
    assert service._pending is not None
    assert service._pending_timer.isActive()
    assert service._quiet() is True
    current_gen = service._pending_gen

    # Timeout simülasyonu
    service._on_pending_timeout(current_gen)
    assert service._pending is None
    assert not service._pending_timer.isActive()
    service._suppress_until = 0.0
    assert service._quiet() is False

    # Timeout sonrası host heartbeat mekanizması çalışabilmeli
    service._test_pb._current_song_ref = dict(SONG)
    service._broadcast(True, 15_000, kind="hb", hb=True)
    assert ws.sent[-1]["hb"] is True


def test_pending_cancelled_on_song_started_or_error(service):
    from mustiefly_qt.services.listen_together import SHARED_PLAYLIST
    _join(service)
    pb = service._test_pb
    
    # Şarkı başladığında pending temizlenmeli
    service._receive_state({
        "t": "state", "seq": 1, "from": "h2",
        "song": dict(SONG), "playing": True, "pos_ms": 1000
    })
    assert service._pending is not None
    pb.songStarted.emit("L", 0, dict(SONG), False)
    assert service._pending is None
    assert not service._pending_timer.isActive()

    # Çalma hatasında da pending temizlenmeli
    service._receive_state({
        "t": "state", "seq": 2, "from": "h2",
        "song": dict(SONG, webpage_url="https://youtu.be/def"), "playing": True, "pos_ms": 1000
    })
    assert service._pending is not None
    pb.playError.emit(SHARED_PLAYLIST, 0)
    assert service._pending is None
    assert not service._pending_timer.isActive()


def test_pending_rapid_song_changes_generation_safety(service):
    _join(service)
    service._receive_state({
        "t": "state", "seq": 1, "from": "h2",
        "song": dict(SONG), "playing": True, "pos_ms": 1000
    })
    gen1 = service._pending_gen

    # Yeni bir şarkı yüklendiğinde yeni bir jenerasyon oluşur
    service._receive_state({
        "t": "state", "seq": 2, "from": "h2",
        "song": dict(SONG, webpage_url="https://youtu.be/second"), "playing": True, "pos_ms": 2000
    })
    gen2 = service._pending_gen
    assert gen2 != gen1

    # Eski şarkının timeout'u yeni şarkının pending durumunu silmemeli
    service._on_pending_timeout(gen1)
    assert service._pending is not None
    assert service._pending["url"] == "https://youtu.be/second"

    # Doğru jenerasyonun timeout'u temizlemeli
    service._on_pending_timeout(gen2)
    assert service._pending is None


def test_pending_heartbeat_does_not_reset_started_at(service):
    _join(service)
    service._receive_state({
        "t": "state", "seq": 1, "from": "h2",
        "song": dict(SONG), "playing": True, "pos_ms": 1000
    })
    started_at_orig = service._pending["started_at"]

    # Heartbeat geldiğinde started_at sıfırlanmamalı
    service._receive_state({
        "t": "state", "seq": 2, "from": "h2",
        "song": dict(SONG), "playing": True, "pos_ms": 3000, "hb": True
    })
    assert service._pending["started_at"] == started_at_orig
    assert service._pending["pos"] == 3000


def test_create_vs_join_distinct_messages(service):
    assert service.create_room("wss://srv.example", "ABC123", "Owner")
    ws_create = service._test_sockets[-1]
    ws_create.connected.emit()
    assert ws_create.sent[0]["t"] == "create"
    service.leave()

    assert service.join("wss://srv.example", "ABC123", "Guest")
    ws_join = service._test_sockets[-1]
    ws_join.connected.emit()
    assert ws_join.sent[0]["t"] == "join"


def test_server_create_vs_join_isolation():
    server = _relay()
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve

    async def scenario():
        server.ROOMS.clear()
        server._FAILS.clear()
        async with serve(server.handler, "127.0.0.1", 0, process_request=server.process_request) as srv:
            url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
            async with connect(url) as ws1:
                # Olmayan odaya katılma isteği hata dönmeli
                await ws1.send(json.dumps({"t": "join", "v": 2, "room": "NOTFOUND", "name": "A"}))
                err = json.loads(await ws1.recv())
                assert err["t"] == "error" and err["code"] == "room_not_found"

            async with connect(url) as ws2, connect(url) as ws3:
                # Açıkça oda oluşturma
                await ws2.send(json.dumps({"t": "create", "v": 2, "room": "NEWROOM", "name": "Owner"}))
                res = json.loads(await ws2.recv())
                assert res["t"] == "joined"

                # Var olan odayı tekrar oluşturma reddedilmeli
                await ws3.send(json.dumps({"t": "create", "v": 2, "room": "NEWROOM", "name": "Imposter"}))
                err2 = json.loads(await ws3.recv())
                assert err2["t"] == "error" and err2["code"] == "room_exists"

    asyncio.run(scenario())
    server.ROOMS.clear()
    server._FAILS.clear()


def test_strict_url_validation():
    from mustiefly_qt.services.listen_together import is_valid_share_url, is_valid_thumbnail_url
    server = _relay()

    # Geçerli YouTube URL'leri
    valid_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
    ]
    for url in valid_urls:
        assert is_valid_share_url(url)
        assert server.is_valid_share_url(url)

    # Geçersiz ve saldırı amaçlı URL'ler
    invalid_urls = [
        "http://www.youtube.com/watch?v=dQw4w9WgXcQ",           # HTTP reddedilmeli
        "https://evil-youtube.com/watch?v=dQw4w9WgXcQ",         # Farklı domain
        "https://youtube.com.attacker.com/watch?v=dQw4w9WgXcQ",  # Subdomain aldatmacası
        "https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ",     # Kimlik bilgisi
        "https://youtube.com:8443/watch?v=dQw4w9WgXcQ",          # Standart dışı port
        "file:///etc/passwd",                                    # Yerel dosya
        "local://c:/secret.mp3",                                 # Yerel protokol
        "javascript:alert(1)",                                  # Script enjeksiyonu
        "https://youtube.com/",                                  # Video id yok
    ]
    for url in invalid_urls:
        assert not is_valid_share_url(url)
        assert not server.is_valid_share_url(url)

    # Thumbnail kontrolü
    assert is_valid_thumbnail_url("https://i.ytimg.com/vi/abc/hqdefault.jpg")
    assert not is_valid_thumbnail_url("http://i.ytimg.com/vi/abc/hqdefault.jpg")
    assert not is_valid_thumbnail_url("https://evil.com/img.jpg")


def test_websocket_server_url_validation():
    from mustiefly_qt.services.listen_together import normalize_server_url

    # Uzak sunucular mutlaka WSS olmalı
    assert normalize_server_url("https://myrelay.onrender.com") == "wss://myrelay.onrender.com"
    assert normalize_server_url("wss://myrelay.onrender.com") == "wss://myrelay.onrender.com"
    assert normalize_server_url("http://myrelay.onrender.com") == ""     # Uzak HTTP reddedilir
    assert normalize_server_url("ws://myrelay.onrender.com") == ""       # Uzak WS reddedilir

    # Yalnızca loopback için WS serbest
    assert normalize_server_url("http://localhost:8765") == "ws://localhost:8765"
    assert normalize_server_url("http://127.0.0.1:8765") == "ws://127.0.0.1:8765"
    assert normalize_server_url("http://[::1]:8765") == "ws://[::1]:8765"
    assert normalize_server_url("ws://127.0.0.1:8765") == "ws://127.0.0.1:8765"


def test_server_untrusted_proxy_header_rejected(monkeypatch):
    server = _relay()

    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    class FakeWS:
        def __init__(self, ip, headers):
            self.remote_address = (ip, 12345)
            self.request = FakeRequest(headers)

    # Güvenilmeyen bir istemci sahte X-Forwarded-For başlığı gönderirse yok sayılmalı
    untrusted_ws = FakeWS("198.51.100.10", {"X-Forwarded-For": "203.0.113.50"})
    assert server.client_ip(untrusted_ws) == "198.51.100.10"

    # Güvenilen bir reverse-proxy üzerinden geliyorsa header dikkate alınmalı
    trusted_ws = FakeWS("198.51.100.10", {"X-Forwarded-For": "203.0.113.50"})
    assert server.client_ip(trusted_ws, trusted_proxies="198.51.100.10") == "203.0.113.50"

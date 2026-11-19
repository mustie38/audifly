"""
Tests for Audifly Connect (QR encoder, local HTTP Web Remote server, and Connect dialog).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from mustiefly_qt.helpers.qr_encode import encode_qr, qr_to_qpixmap
from mustiefly_qt.services import playback as pb_mod
from mustiefly_qt.services.connect_server import AudiflyConnectService
from mustiefly_qt.views.connect_dialog import AudiflyConnectDialog


def test_qr_encoder_structure_and_pixmap(qapp):
    url = "http://192.168.1.42:8766/?t=AbCdEfGhIjKl"
    mat = encode_qr(url)
    n = len(mat)
    assert n in (21, 25, 29, 33, 37)
    assert all(len(row) == n for row in mat)
    # Top-left finder pattern 7x7 outer ring & 3x3 center
    assert mat[0][0] is True and mat[0][6] is True and mat[6][0] is True
    assert mat[3][3] is True and mat[1][1] is False
    # Dark module at (n - 8, 8)
    assert mat[n - 8][8] is True

    pm = qr_to_qpixmap(url, box_size=5, border=2)
    assert not pm.isNull()
    assert pm.width() == (n + 4) * 5


def test_connect_server_auth_state_playlists_and_commands(library_store, qapp, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    library_store.playlists["Favoriler"] = [
        {"title": "Dönence", "uploader": "Barış Manço", "webpage_url": "https://youtu.be/bm1", "duration": 210},
    ]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {"_volume": 65})
    engine._current_song_ref = library_store.playlists["Favoriler"][0]
    engine.playing_playlist = "Favoriler"
    engine.current_index = 0

    svc = AudiflyConnectService(library_store, engine)
    try:
        ok, url = svc.start(port=0)
        assert ok is True
        assert "?t=" in url
        base = f"http://127.0.0.1:{svc._port}"
        tok = svc.token

        # 1) Unauthorized request -> 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{base}/api/state", timeout=3)
        assert exc.value.code == 403

        # 2) Authorized HTML root -> 200
        with urllib.request.urlopen(f"{base}/?t={tok}", timeout=3) as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "Audifly Connect" in html
            assert tok in html

        # 3) Authorized /api/state -> returns current song & volume
        req = urllib.request.Request(f"{base}/api/state", headers={"X-Audifly-Token": tok})
        with urllib.request.urlopen(req, timeout=3) as resp:
            state = json.loads(resp.read().decode("utf-8"))
        assert state["title"] == "Dönence"
        assert state["volume"] == 65
        assert state["playlist"] == "Favoriler"

        # 4) Authorized /api/playlists
        req_pl = urllib.request.Request(f"{base}/api/playlists", headers={"X-Audifly-Token": tok})
        with urllib.request.urlopen(req_pl, timeout=3) as resp:
            pls = json.loads(resp.read().decode("utf-8"))
        assert any(p["name"] == "Favoriler" and p["count"] == 1 for p in pls["playlists"])

        # 5) POST /api/cmd (volume & shuffle) -> dispatched on GUI thread
        cmd_body = json.dumps({"action": "volume", "value": 42}).encode("utf-8")
        req_cmd = urllib.request.Request(
            f"{base}/api/cmd",
            data=cmd_body,
            headers={"X-Audifly-Token": tok, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_cmd, timeout=3) as resp:
            assert json.loads(resp.read().decode("utf-8"))["ok"] is True
        QApplication.processEvents()
        assert engine.settings.get("_volume") == 42

        # 6) Rotate token invalidates old token
        old_tok = tok
        svc.rotate_token()
        assert svc.token != old_tok
        with pytest.raises(urllib.error.HTTPError) as exc2:
            req_old = urllib.request.Request(f"{base}/api/state", headers={"X-Audifly-Token": old_tok})
            urllib.request.urlopen(req_old, timeout=3)
        assert exc2.value.code == 403
    finally:
        svc.stop()
        engine.shutdown()


def test_connect_dialog_auto_starts_and_renders_qr(library_store, qapp, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    svc = AudiflyConnectService(library_store, engine)
    dlg = AudiflyConnectDialog(svc)
    try:
        assert svc.is_running is True
        assert dlg.url_edit.text().startswith("http://")
        assert dlg.qr_label.pixmap() is not None and not dlg.qr_label.pixmap().isNull()

        # Stop via toggle button
        dlg._toggle_server()
        assert svc.is_running is False
        assert dlg.url_edit.text() == ""
    finally:
        dlg.close()
        svc.stop()
        engine.shutdown()

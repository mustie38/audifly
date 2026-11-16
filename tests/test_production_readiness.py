"""Üretim hazırlığı testleri:
1. Uygulama içi yt-dlp güncelleme (wheel indirme, SHA-256, _OverrideFinder, geri dönüş)
2. Tanılama / Sorun Bildir penceresi ve hata snackbar'ı
3. Çoklu şarkı ön yükleme (3 şarkı), yeniden deneme ve stream expire kontrolü
4. Paket içi libVLC indirme/doğrulama ve çalışma anı yapılandırması
5. Authenticode kod imzalama betiği (sign_binaries.py)
6. Çoklu dil desteği (TR ↔ EN canlı geçiş)
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mustiefly_qt.helpers import dependencies, i18n, ytdlp_runtime
from mustiefly_qt.helpers.constants import (
    STREAM_URL_SAFETY_MARGIN, needs_stream_resolve, stream_url_expiry, stream_url_is_fresh,
)
from mustiefly_qt.packaging import fetch_vlc, sign_binaries


# ============================================================================
# 1. Uygulama içi yt-dlp güncelleme (helpers/ytdlp_runtime.py)
# ============================================================================
def _make_wheel(files: dict[str, str]) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def test_ytdlp_runtime_install_and_reset(tmp_path):
    env = {"AUDIFLY_COMPONENTS_DIR": str(tmp_path)}
    yt_whl, yt_sha = _make_wheel({
        "yt_dlp/__init__.py": "from .version import __version__\n",
        "yt_dlp/version.py": "__version__ = '2099.01.05'\n",
    })
    ejs_whl, ejs_sha = _make_wheel({
        "yt_dlp_ejs/__init__.py": "VERSION = '0.9.0'\n",
    })
    routes = {
        "https://pypi.org/pypi/yt-dlp/json": json.dumps({
            "info": {"name": "yt-dlp", "version": "2099.01.05",
                     "requires_python": ">=3.10",
                     "requires_dist": ["yt-dlp-ejs==0.9.0; extra == 'default'"]},
            "urls": [{"packagetype": "bdist_wheel", "filename": "yt_dlp-2099.1.5-py3-none-any.whl",
                      "url": "https://files.pythonhosted.org/yt.whl", "digests": {"sha256": yt_sha}}],
        }).encode(),
        "https://pypi.org/pypi/yt-dlp-ejs/0.9.0/json": json.dumps({
            "info": {"name": "yt-dlp-ejs", "version": "0.9.0"},
            "urls": [{"packagetype": "bdist_wheel", "filename": "yt_dlp_ejs-0.9.0-py3-none-any.whl",
                      "url": "https://files.pythonhosted.org/ejs.whl", "digests": {"sha256": ejs_sha}}],
        }).encode(),
        "https://files.pythonhosted.org/yt.whl": yt_whl,
        "https://files.pythonhosted.org/ejs.whl": ejs_whl,
    }
    ok, msg, ver = ytdlp_runtime.install_latest(environ=env, get=routes.__getitem__)
    assert ok and ver == "2099.01.05"
    assert ytdlp_runtime.pending_version(environ=env) == "2099.01.05"

    # SHA-256 uyuşmazlığında hiçbir şey kurulmamalı
    bad_routes = dict(routes, **{"https://files.pythonhosted.org/yt.whl": b"bozuk"})
    env2 = {"AUDIFLY_COMPONENTS_DIR": str(tmp_path / "bad")}
    ok2, msg2, _ = ytdlp_runtime.install_latest(environ=env2, get=bad_routes.__getitem__)
    assert not ok2 and "SHA-256" in msg2

    # Sıfırlama paketteki sürüme döndürür
    assert ytdlp_runtime.reset_to_bundled(environ=env)
    assert ytdlp_runtime.pending_version(environ=env) is None


# ============================================================================
# 2. Tanılama / Sorun Bildir penceresi & hata snackbar'ı
# ============================================================================
def test_diagnostics_dialog_copies_and_saves_report(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication
    from mustiefly_qt.views.diagnostics_dialog import DiagnosticsDialog

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "audifly.log").write_text("2026-11-16 ERROR ornek hata\n", encoding="utf-8")

    dlg = DiagnosticsDialog(
        str(log_dir),
        error_text="HTTP Error 403: Forbidden",
        recent_errors=["Şarkı 1 çalınamadı"],
    )
    dlg.note_edit.setPlainText("Şarkıya çift tıkladım çalmadı")
    text = dlg.copy_report()
    assert "Şarkıya çift tıkladım çalmadı" in text
    assert "HTTP Error 403" in text
    assert "Şarkı 1 çalınamadı" in text
    assert QGuiApplication.clipboard().text() == text

    out = tmp_path / "rapor.txt"
    assert dlg.save_report(str(out))
    assert out.read_text(encoding="utf-8") == text
    dlg.close()


def test_snackbar_report_mode_emits_report_clicked(qapp):
    from mustiefly_qt.widgets.snackbar import UndoSnackbar
    bar = UndoSnackbar()
    reported = []
    undone = []
    bar.reportClicked.connect(lambda: reported.append(True))
    bar.undoClicked.connect(lambda: undone.append(True))

    bar.show_message("⚠️ Şarkı çalınamadı", undoable=False, reportable=True)
    assert not bar.undo_btn.isHidden()
    assert "Sorun Bildir" in bar.undo_btn.text()
    bar.undo_btn.click()
    assert reported == [True] and undone == []
    bar.close()


# ============================================================================
# 3. Çoklu şarkı ön yükleme (3 şarkı), yeniden deneme ve expire kontrolü
# ============================================================================
def test_stream_url_expiry_detection():
    now = time.time()
    soon_url = f"https://rr1---sn.googlevideo.com/videoplayback?expire={int(now + 60)}&id=1"
    fresh_url = f"https://rr1---sn.googlevideo.com/videoplayback?expire={int(now + 7200)}&id=1"
    assert stream_url_expiry(soon_url) == int(now + 60)
    assert not stream_url_is_fresh({"stream_url": soon_url, "resolved_at": now}, now=now)
    assert stream_url_is_fresh({"stream_url": fresh_url, "resolved_at": now}, now=now)
    assert needs_stream_resolve({"webpage_url": "https://youtu.be/1", "stream_url": soon_url, "resolved_at": now}, now=now)
    assert not needs_stream_resolve({"webpage_url": "https://youtu.be/1", "stream_url": fresh_url, "resolved_at": now}, now=now)
    assert STREAM_URL_SAFETY_MARGIN >= 600


def test_preload_resolves_multiple_upcoming_songs_and_retries(library_store, monkeypatch):
    from mustiefly_qt.services import playback as pb_mod
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    monkeypatch.setattr(pb_mod, "PRELOAD_RETRY_DELAYS", (0.01, 0.01))

    songs = [
        {"title": f"S{i}", "webpage_url": f"https://youtube.com/watch?v={i}"}
        for i in range(6)
    ]
    library_store.playlists["Varsayılan"] = songs
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    try:
        engine.playing_playlist = "Varsayılan"
        engine.current_index = 0
        upcoming = engine._upcoming_songs(pb_mod.PRELOAD_AHEAD)
        assert [s["title"] for s in upcoming] == ["S1", "S2", "S3"]

        # Geçici hata veren şarkı 2. denemede çözülmeli; kalıcı hata veren ("Private video") 1 kez denenmeli
        calls: dict[str, int] = {}

        def fake_resolve(song):
            title = song["title"]
            calls[title] = calls.get(title, 0) + 1
            if title == "S1" and calls[title] == 1:
                raise RuntimeError("timed out")
            if title == "S2":
                raise RuntimeError("Video unavailable: Private video")
            song["stream_url"] = f"https://audio.example/{title}"
            song["resolved_at"] = time.time()
            return song["stream_url"], False

        monkeypatch.setattr(pb_mod, "resolve_stream_url", fake_resolve)
        engine._preload_worker(upcoming)
        assert calls["S1"] == 2 and songs[1].get("stream_url")
        assert calls["S2"] == 1        # kalıcı hata: boşuna tekrar denemez
        assert calls["S3"] == 1 and songs[3].get("stream_url")
    finally:
        engine.shutdown()


# ============================================================================
# 4. Paket içi libVLC (packaging/fetch_vlc.py & helpers/dependencies.py)
# ============================================================================
def test_fetch_vlc_filters_video_plugins_and_verifies_sha(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vlc-3.0.24/libvlc.dll", b"libvlc")
        zf.writestr("vlc-3.0.24/libvlccore.dll", b"libvlccore")
        zf.writestr("vlc-3.0.24/COPYING.txt", b"LGPL")
        zf.writestr("vlc-3.0.24/plugins/audio_output/libwasapi_plugin.dll", b"audio")
        zf.writestr("vlc-3.0.24/plugins/audio_filter/libequalizer_plugin.dll", b"eq")
        zf.writestr("vlc-3.0.24/plugins/gui/libqt_plugin.dll", b"gui-excluded")
        zf.writestr("vlc-3.0.24/plugins/codec/libx265_plugin.dll", b"x265-excluded")
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()

    dest = tmp_path / "vlc"
    ver, count = fetch_vlc.install_vlc(
        dest, "3.0.24",
        get=lambda url: f"{sha} *vlc.zip".encode() if url.endswith(".sha256") else data,
    )
    assert ver == "3.0.24" and count == 5
    assert (dest / "libvlc.dll").is_file()
    assert (dest / "plugins" / "audio_filter" / "libequalizer_plugin.dll").is_file()
    assert not (dest / "plugins" / "gui").exists()
    assert not (dest / "plugins" / "codec" / "libx265_plugin.dll").exists()

    env: dict[str, str] = {}
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(dependencies, "bundled_vlc_dir", lambda: str(dest))
    assert dependencies.configure_bundled_vlc(env)
    assert env["PYTHON_VLC_LIB_PATH"] == str(dest / "libvlc.dll")
    assert env["PYTHON_VLC_MODULE_PATH"] == str(dest / "plugins")
    monkeypatch.undo()


# ============================================================================
# 5. Authenticode kod imzalama (packaging/sign_binaries.py)
# ============================================================================
def test_sign_binaries_skips_cleanly_without_cert_and_signs_with_cert(tmp_path):
    exe = tmp_path / "Audifly.exe"
    exe.write_bytes(b"MZ")
    assert sign_binaries.sign_files([exe], environ={}) == 0
    assert sign_binaries.sign_files([exe], environ={}, require=True) == 1

    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="Done", stderr="")

    rc = sign_binaries.sign_files(
        [exe],
        environ={"WINDOWS_PFX_BASE64": "ZHVtbXk=", "WINDOWS_PFX_PASSWORD": "gizli"},
        run=fake_run,
        which=lambda _: "signtool.exe",
    )
    assert rc == 0 and len(recorded) == 1
    assert "/fd" in recorded[0] and "sha256" in recorded[0] and str(exe) in recorded[0]


# ============================================================================
# 6. Çoklu dil desteği (helpers/i18n.py)
# ============================================================================
def test_i18n_bidirectional_live_translation(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    box = QWidget()
    lay = QVBoxLayout(box)
    lbl = QLabel("⚙  Ayarlar")
    btn = QPushButton("📋 Raporu Kopyala")
    lay.addWidget(lbl)
    lay.addWidget(btn)

    try:
        i18n.set_language("en")
        i18n.translate_widget(box)
        assert lbl.text() == "⚙  Settings"
        assert btn.text() == "📋 Copy Report"

        # Tekrar Türkçe'ye dönüldüğünde orijinal metinler geri gelmeli
        i18n.set_language("tr")
        i18n.translate_widget(box)
        assert lbl.text() == "⚙  Ayarlar"
        assert btn.text() == "📋 Raporu Kopyala"
    finally:
        i18n.set_language("tr")
        box.close()


# ============================================================================
# 7. Toplu bug fix regresyon testleri
# ============================================================================
def test_downloads_view_remove_button_and_live_progress(library_store):
    from mustiefly_qt.services.download_manager import CANCELLED, DOWNLOADING, DownloadManager, FAILED
    from mustiefly_qt.views.downloads_view import DownloadsView

    song = {"title": "Parça", "webpage_url": "https://youtu.be/dl1", "duration": 120}
    library_store.playlists["Varsayılan"] = [song]
    mgr = DownloadManager(library_store, library_store.paths)
    url = song["webpage_url"]
    mgr.items[url] = {
        "key": url, "playlist": "Varsayılan", "index": 0, "song": song,
        "state": FAILED, "progress": 0.0, "error": "ağ hatası", "path": None,
        "cancel": MagicMock(),
    }
    mgr._order.append(url)

    view = DownloadsView(mgr, library_store)
    row = view._rows[url]["row"]
    # Canlı ilerleme güncellemesi (sığ kopya bayat kalmamalı)
    mgr.items[url]["state"] = DOWNLOADING
    mgr.items[url]["progress"] = 0.65
    view._on_item_changed(url)
    assert row.progress.value() == 65

    # Başarısız/tamamlanmış öğede 🗑 butonu gerçekten listeden kaldırmalı
    mgr.items[url]["state"] = CANCELLED
    view._on_item_changed(url)
    row.cancel_btn.click()
    assert url not in mgr.items
    view.close()
    mgr.shutdown()


def test_library_search_dialog_double_click_plays_song(library_store, monkeypatch):
    from mustiefly_qt.services import playback as pb_mod
    from mustiefly_qt.views.library_search_dialog import LibrarySearchDialog

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    library_store.playlists["Varsayılan"] = [
        {"title": "Dönence", "uploader": "Barış Manço", "webpage_url": "https://youtu.be/bm1", "duration": 200},
    ]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    played = []
    monkeypatch.setattr(engine, "play_song_at_index", lambda pl, idx: played.append((pl, idx)))
    dlg = LibrarySearchDialog(library_store, engine)
    try:
        dlg.query_edit.setText("dönence")
        dlg._run_search()
        assert dlg.results_list.count() == 1
        dlg._open_song(dlg.results_list.item(0))
        assert played == [("Varsayılan", 0)]
    finally:
        dlg.close()
        engine.shutdown()


def test_delete_playlist_schedules_cached_file_deletion_and_undo_cancels(library_store):
    cached = Path(library_store.paths.cache_dir) / "cached_song.mp3"
    cached.write_bytes(b"mp3")
    library_store.create_playlist("Silinecek")
    library_store.playlists["Silinecek"] = [{
        "title": "Şarkı", "webpage_url": "https://youtu.be/del1", "cached_path": str(cached),
    }]
    ok, _ = library_store.delete_playlist("Silinecek")
    assert ok
    assert str(cached) in library_store._pending_file_deletions
    library_store.perform_undo()
    assert str(cached) not in library_store._pending_file_deletions
    assert cached.is_file()


def test_seek_clamps_to_length_and_completes_crossfade(library_store, monkeypatch):
    from mustiefly_qt.services import playback as pb_mod

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    try:
        engine.player.get_length.return_value = 180_000
        seeked = []
        engine.seeked.connect(seeked.append)
        engine.seek(250_000)
        engine.player.set_time.assert_called_with(180_000)
        engine.seek(-5_000)
        engine.player.set_time.assert_called_with(0)
        assert seeked == [180_000, 0]
    finally:
        engine.shutdown()


def test_player_bar_and_now_playing_sync_like_and_recover_from_play_error(library_store, monkeypatch):
    from mustiefly_qt.services import playback as pb_mod
    from mustiefly_qt.views.now_playing_panel import NowPlayingPanel
    from mustiefly_qt.views.player_bar import PlayerBar

    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    song = {"title": "Test Şarkı", "uploader": "Sanatçı", "webpage_url": "https://youtu.be/t1",
            "duration": 100, "liked": False}
    library_store.playlists["Varsayılan"] = [song]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    bar = PlayerBar(engine)
    panel = NowPlayingPanel(library_store, engine)
    try:
        engine.playing_playlist = "Varsayılan"
        engine.current_index = 0
        engine.songLoading.emit("Varsayılan", 0, song)
        assert not bar.play_btn.isEnabled()
        engine.playError.emit("Varsayılan", 0)
        assert bar.play_btn.isEnabled()
        assert panel.play_btn.isEnabled()
        assert not bar._now_title_raw.startswith("Yükleniyor:")

        engine.songStarted.emit("Varsayılan", 0, song, False)
        assert not bar.like_btn._active
        library_store.toggle_like("Varsayılan", 0)
        assert bar.like_btn._active
        assert "Beğenildi" in panel.like_btn.text()
    finally:
        bar.close()
        panel.close()
        engine.shutdown()


def test_tv_samsung_excluded_and_premature_ended_triggers_stream_refresh(library_store, monkeypatch):
    from mustiefly_qt.helpers.constants import yt_dlp_base_opts
    from mustiefly_qt.services import playback as pb_mod

    opts = yt_dlp_base_opts()
    clients = opts.get("extractor_args", {}).get("youtube", {}).get("player_client", [])
    assert "-tv_samsung" in clients

    now = time.time()
    bad_tv_url = f"https://rr1---sn.googlevideo.com/videoplayback?expire={int(now + 7200)}&c=TVHTML5&id=1"
    assert not stream_url_is_fresh({"stream_url": bad_tv_url, "resolved_at": now}, now=now)

    instance = MagicMock()
    instance.media_player_new.side_effect = [MagicMock(), MagicMock()]
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: instance)
    monkeypatch.setattr(pb_mod.threading, "Thread", MagicMock())
    song = {
        "title": "Test", "webpage_url": "https://youtu.be/x1",
        "stream_url": "https://rr1.googlevideo.com/videoplayback?id=1",
        "resolved_at": now, "http_user_agent": "CustomUA/1.0",
    }
    library_store.playlists["Varsayılan"] = [song]
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    try:
        engine._play_generation = 1
        engine._start_playback(1, song, "Varsayılan", 0, song["stream_url"], False)
        media = instance.media_new.return_value
        media.add_option.assert_any_call(":http-user-agent=CustomUA/1.0")

        # VLC 403/TLS hatasında length=0, pos=0 ile doğrudan State.Ended döndürürse
        # doğal bitiş sanmak yerine akış yenilenmeli:
        engine.player.is_playing.return_value = False
        engine.player.get_state.return_value = pb_mod.vlc.State.Ended
        engine.player.get_length.return_value = 0
        engine.player.get_time.return_value = 0
        engine._update_ui_loop()
        assert "stream_url" not in song and engine.is_loading

        # VLC çalarken get_length()=0 ve get_time()=0 döndürse bile song['duration']
        # ve _listen['seconds'] üzerinden positionChanged yayınlanmalı (00:00/00:00 kalmamalı):
        song["duration"] = 244
        engine.is_loading = False
        engine._listen = {"song": song, "seconds": 15.4, "last": pb_mod.time.monotonic()}
        engine.player.is_playing.return_value = True
        engine.player.get_state.return_value = pb_mod.vlc.State.Playing
        engine.player.get_length.return_value = 0
        engine.player.get_time.return_value = 0
        engine.player.get_position.return_value = 0.0
        positions = []
        engine.positionChanged.connect(lambda cur, tot: positions.append((cur, tot)))
        engine._update_ui_loop()
        assert positions and positions[-1][1] == 244_000 and positions[-1][0] >= 15_000
    finally:
        engine.shutdown()

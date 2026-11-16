import pytest

from mustiefly_qt.helpers import updates
from mustiefly_qt.helpers.constants import offline_path_for
from mustiefly_qt.widgets.song_row import SongRow


@pytest.mark.parametrize("installed,latest,expected", [("2026.10.1", "2026.10.9", True),
    ("2026.10.9", "2026.10.1", False), ("2026.10.1", "2026.10.1", False),
    ("invalid", "2026.10.1", False)])
def test_update_requires_newer_version(monkeypatch, installed, latest, expected):
    monkeypatch.setattr(updates, "installed_version", lambda package: installed)
    monkeypatch.setattr(updates, "latest_pypi_version", lambda package: latest)
    assert updates.update_available()[0] is expected


def test_frozen_update_does_not_spawn_app_recursively(monkeypatch):
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("must not invoke pip")
    monkeypatch.setattr(updates.subprocess, "run", forbidden)
    monkeypatch.setattr(updates.ytdlp_runtime, "install_latest",
                        lambda: (True, "yt-dlp 2026.12.1 indirildi.", "2026.12.1"))
    ok, msg = updates.run_update()
    assert ok and "2026.12.1" in msg


def test_missing_cached_path_is_not_offline(tmp_path):
    assert offline_path_for({"cached_path": str(tmp_path / "missing.mp3")}) is None


def test_offline_badge_checks_file_existence(library_store, tmp_path):
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    row = SongRow(0, {"title": "Song", "cached_path": str(path)})
    assert not row.offline_badge.isHidden()
    row.close()
    path.unlink()
    row2 = SongRow(0, {"title": "Song", "cached_path": str(path)})
    assert row2.offline_badge.isHidden()
    row2.close()


def test_missing_local_file_produces_actionable_error_without_network(tmp_path):
    from mustiefly_qt.helpers.constants import resolve_stream_url
    with pytest.raises(FileNotFoundError, match="Yerel ses dosyası bulunamadı"):
        resolve_stream_url({"local_path": str(tmp_path / "missing.mp3"), "webpage_url": "local://missing"})


def test_thumbnail_service_shutdown_is_safe_and_idempotent():
    from mustiefly_qt.services.thumbnails import ThumbnailService
    service = ThumbnailService(max_workers=1)
    service.shutdown()
    service.shutdown()                                     # iki kez çağrılabilir
    service.request({"webpage_url": "https://x.example/1", "thumbnail": "https://x.example/t.jpg"})
    assert service._fetching == set()                      # kapandıktan sonra iş alınmaz, hata atmaz

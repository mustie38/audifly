import json
from pathlib import Path

import pytest

from mustiefly_qt.helpers.backup import export_library, import_library


def backup(tmp_path, **extra):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({"format": "mustiefly-backup", "version": 2,
                               "playlists": {"New": []}, **extra}))
    return str(path)


@pytest.mark.parametrize("invalid", [[], 123, {"format": "other"}, {"format": "mustiefly-backup", "version": 99},
                                    {"format": "mustiefly-backup", "playlists": {"Invalid": 42}}])
def test_invalid_backup_preserves_live_library(library_store, tmp_path, invalid):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid))
    original = library_store.playlists
    total, error = import_library(library_store, str(path))
    assert error and total == 0
    assert library_store.playlists is original


def test_invalid_base64_fails_before_library_replacement(library_store, tmp_path):
    original = library_store.playlists
    _, error = import_library(library_store, backup(tmp_path, covers={"New": "!!!"}))
    assert error
    assert library_store.playlists is original


def test_export_excludes_tokens_and_session(library_store, tmp_path):
    path = tmp_path / "backup.json"
    settings = {"theme": "dark", "spotify_client_secret": "dummy-secret",
                "spotify_refresh_token": "dummy-token", "last_session": {"playlist": "Private"}}
    assert export_library(library_store, str(path), settings) is None
    data = json.loads(path.read_text())
    assert data["settings"] == {"theme": "dark"}


def test_import_clears_undo_and_queue_and_keeps_current_credentials(library_store, tmp_path):
    store = library_store
    store._undo_stack.append(("clear_queue", []))
    store.manual_queue.append(("Varsayılan", 0, {}))
    settings = {"spotify_refresh_token": "current"}
    total, error = import_library(store, backup(tmp_path, settings={"theme": "crimson", "spotify_refresh_token": "foreign"}), settings)
    assert not error and total == 0
    assert store.playlists == {"New": []}
    assert not store._undo_stack and not store.manual_queue
    assert settings == {"theme": "crimson", "spotify_refresh_token": "current"}
    assert json.loads(Path(store.paths.playlist_file).read_text())["playlists"] == {"New": []}


def test_restore_disk_failure_keeps_live_library(library_store, tmp_path, monkeypatch):
    from mustiefly_qt.helpers import backup as module
    original = library_store.playlists
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(module, "atomic_write_json", fail)
    _, error = module.import_library(library_store, backup(tmp_path, covers={"New": "Y292ZXI="}))
    assert error
    assert library_store.playlists is original
    assert list(Path(library_store.paths.covers_dir).iterdir()) == []


def test_v1_backup_remains_supported(library_store, tmp_path):
    assert not import_library(library_store, backup(tmp_path, version=1))[1]


def test_export_uses_new_format_and_old_backups_still_import(library_store, tmp_path):
    out = tmp_path / "new.json"
    assert export_library(library_store, str(out)) is None
    assert json.loads(out.read_text())["format"] == "audifly-backup"
    total, error = import_library(library_store, str(out))
    assert error == ""
    _, error = import_library(library_store, backup(tmp_path))     # eski "mustiefly-backup"
    assert error == ""


def test_import_validates_theme_bands_and_rules_in_live_settings(library_store, tmp_path):
    settings = {}
    bad = {"theme": "ocean", "equalizer_bands": [99] * 3,
           "smart_rules": [{"name": "ok"}, "junk", {"name": ""}], "crossfade_seconds": 999}
    _, error = import_library(library_store, backup(tmp_path, settings=bad), settings)
    assert not error
    from mustiefly_qt.helpers.constants import DEFAULT_SETTINGS, DEFAULT_THEME_KEY
    assert settings["theme"] == DEFAULT_THEME_KEY
    assert settings["equalizer_bands"] == [0.0] * 10
    assert [r["name"] for r in settings["smart_rules"]] == ["ok"]
    assert all("limit" in r and "sort" in r for r in settings["smart_rules"])
    assert settings["crossfade_seconds"] == DEFAULT_SETTINGS["crossfade_seconds"]

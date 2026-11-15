"""FAZ 1: ayar şeması, keyring göçü, bozuk dosya karantinası, yedek izin listesi."""
import json

import pytest

from mustiefly_qt.auth import service
from mustiefly_qt.helpers import secrets_store
from mustiefly_qt.helpers.constants import AppPaths


@pytest.fixture()
def paths(tmp_path):
    d = tmp_path / "alice"
    p = AppPaths(str(tmp_path), str(d), str(d / "pl.json"), str(d / "settings.json"),
                 str(d / "cache"), str(d / "covers"))
    p.ensure_dirs()
    return p


@pytest.fixture()
def fake_keyring(monkeypatch):
    vault = {}
    monkeypatch.setattr(secrets_store, "is_available", lambda: True)
    monkeypatch.setattr(secrets_store, "get_secret", lambda u, k: vault.get((u, k)))

    def _set(u, k, v):
        if v:
            vault[(u, k)] = v
        else:
            vault.pop((u, k), None)
        return True
    monkeypatch.setattr(secrets_store, "set_secret", _set)
    return vault


def test_invalid_settings_fall_back_to_defaults(paths):
    json.dump({"page_size": "abc", "crossfade_seconds": 999, "theme": "yok",
               "equalizer_bands": [1, 2], "minimize_to_tray": "evet", "custom": 1},
              open(paths.settings_file, "w"))
    s = service.load_settings_for(paths)
    assert s["page_size"] == 60 and s["crossfade_seconds"] == 3
    assert s["theme"] == "audifly" and s["equalizer_bands"] == [0.0] * 10
    assert s["minimize_to_tray"] is False
    assert s["custom"] == 1 and s["settings_version"] == service.SETTINGS_VERSION


def test_corrupt_settings_are_quarantined_not_overwritten(paths):
    open(paths.settings_file, "w").write("{bozuk")
    s = service.load_settings_for(paths)
    assert s["theme"] == "audifly"
    assert any(".corrupt-" in f.name for f in __import__("pathlib").Path(paths.dir).iterdir())


def test_secrets_migrate_to_keyring_and_leave_file(paths, fake_keyring):
    json.dump({"spotify_client_secret": "S", "spotify_refresh_token": "R",
               "spotify_client_id": "id"}, open(paths.settings_file, "w"))
    s = service.load_settings_for(paths)
    assert s["spotify_client_secret"] == "S"          # bellekte kullanılabilir
    on_disk = json.load(open(paths.settings_file))
    assert "spotify_client_secret" not in on_disk and "spotify_refresh_token" not in on_disk
    assert on_disk["spotify_client_id"] == "id"
    assert fake_keyring[("alice", "spotify_refresh_token")] == "R"


def test_without_keyring_secrets_stay_in_file(paths, monkeypatch):
    monkeypatch.setattr(secrets_store, "is_available", lambda: False)
    s = service.load_settings_for(paths)
    s["spotify_refresh_token"] = "R"
    assert service.save_settings_for(paths, s)
    assert json.load(open(paths.settings_file))["spotify_refresh_token"] == "R"


def test_disconnect_clears_keyring(paths, fake_keyring):
    s = service.load_settings_for(paths)
    s["spotify_refresh_token"] = "R"
    service.save_settings_for(paths, s)
    s["spotify_refresh_token"] = ""
    service.save_settings_for(paths, s)
    assert ("alice", "spotify_refresh_token") not in fake_keyring


def test_corrupt_library_is_quarantined_and_backup_not_rotated(library_store):
    import pathlib
    store = library_store
    store.backup_enabled = True
    pathlib.Path(store.paths.playlist_file).write_text("{bozuk")
    store._backup_playlist_file()
    assert not (pathlib.Path(store.paths.dir) / "backups" / "playlists.bak1.json").exists()
    store.load()
    names = [f.name for f in pathlib.Path(store.paths.dir).iterdir()]
    assert any(n.startswith("playlist.json.corrupt-") for n in names)
    assert not pathlib.Path(store.paths.playlist_file).exists()


def test_backup_import_ignores_unknown_settings(library_store, tmp_path):
    from mustiefly_qt.helpers import backup
    library_store.add_song("Varsayılan", {"title": "a", "webpage_url": "https://x/1"})
    path = str(tmp_path / "b.json")
    assert backup.export_library(library_store, path, {"theme": "audifly"}) is None
    data = json.load(open(path))
    data["settings"] = {"page_size": "abc", "evil_key": 1, "discord_client_id": "9"}
    json.dump(data, open(path, "w"))
    settings = {"page_size": 60}
    total, err = backup.import_library(library_store, path, settings)
    assert err == "" and total == 1
    assert "evil_key" not in settings and settings["page_size"] == 60


def test_smart_rules_are_sanitized_on_load_and_defaults_not_shared(paths):
    json.dump({"smart_rules": [{"name": "Sabah", "limit": 20}, "çöp", {"name": ""}]},
              open(paths.settings_file, "w"))
    s = service.load_settings_for(paths)
    assert [r["name"] for r in s["smart_rules"]] == ["Sabah"]
    s["equalizer_bands"][0] = 9.0
    assert service.DEFAULT_SETTINGS["equalizer_bands"][0] == 0.0     # varsayılan kirlenmez


def test_legacy_keyring_entries_are_found_and_moved(monkeypatch):
    vault = {("Mustiefly", "u:tok"): "S"}

    class FakeKeyring:
        @staticmethod
        def get_keyring():
            return type("B", (), {"priority": 5})()

        @staticmethod
        def get_password(svc, name):
            return vault.get((svc, name))

        @staticmethod
        def set_password(svc, name, value):
            vault[(svc, name)] = value

        @staticmethod
        def delete_password(svc, name):
            vault.pop((svc, name), None)

    monkeypatch.setattr(secrets_store, "keyring", FakeKeyring)
    monkeypatch.setattr(secrets_store, "KEYRING_IMPORTED", True)
    assert secrets_store.get_secret("u", "tok") == "S"
    assert vault == {("Audifly", "u:tok"): "S"}
    assert secrets_store.set_secret("u", "tok", "")                  # silme iki adı da temizler
    assert vault == {}

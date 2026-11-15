from pathlib import Path

import json

from mustiefly_qt.helpers.data_paths import MIGRATED_MARKER, default_data_root, migrate_legacy_data


def test_installed_linux_uses_user_storage(tmp_path):
    assert default_data_root(tmp_path / "site-packages" / "mustiefly_qt", environ={},
                             platform="linux", home=tmp_path, frozen=False) == str(tmp_path / ".local/share/Audifly")


def test_installed_windows_uses_localappdata(tmp_path):
    assert default_data_root(tmp_path / "installed", environ={"LOCALAPPDATA": str(tmp_path / "Local")},
                             platform="win32", home=tmp_path, frozen=False) == str(tmp_path / "Local/Audifly")


def test_source_run_without_legacy_data_uses_user_storage_not_project_parent(tmp_path):
    root = tmp_path / "Desktop" / "mustiefly_qt"
    root.mkdir(parents=True)
    (root / "pyproject.toml").touch()
    got = default_data_root(root, environ={}, platform="linux", home=tmp_path, frozen=False)
    assert got == str(tmp_path / ".local/share/Audifly")      # masaüstüne (proje klasörünün üstüne) yazılmaz


def test_existing_legacy_accounts_are_not_moved(tmp_path):
    (tmp_path / "users.json").write_text("{}")
    assert default_data_root(tmp_path / "mustiefly_qt", environ={}, home=tmp_path, frozen=False) == str(tmp_path)


def test_override_selects_explicit_storage(tmp_path):
    assert default_data_root(environ={"MUSTIEFLY_DATA_DIR": str(tmp_path / "custom")}) == str((tmp_path / "custom").resolve())


def test_existing_mustiefly_folder_is_kept_so_offline_paths_survive(tmp_path):
    old = tmp_path / ".local/share/Mustiefly"
    old.mkdir(parents=True)
    root = default_data_root(tmp_path / "site-packages" / "mustiefly_qt", environ={},
                             platform="linux", home=tmp_path, frozen=False)
    assert root == str(old)
    (tmp_path / ".local/share/Audifly").mkdir()          # yeni klasör varsa o kazanır
    assert default_data_root(tmp_path / "site-packages" / "mustiefly_qt", environ={},
                             platform="linux", home=tmp_path, frozen=False).endswith("Audifly")


def test_new_override_name_wins_over_legacy_name(tmp_path):
    env = {"AUDIFLY_DATA_DIR": str(tmp_path / "new"), "MUSTIEFLY_DATA_DIR": str(tmp_path / "old")}
    assert default_data_root(environ=env) == str((tmp_path / "new").resolve())


def test_migration_copies_data_fixes_offline_paths_and_stops_using_legacy(tmp_path):
    legacy, target = tmp_path / "Desktop", tmp_path / "Local" / "Audifly"
    user = legacy / "users" / "ali"
    user.mkdir(parents=True)
    (legacy / "users.json").write_text('{"ali": {}}')
    (legacy / "last_session.json").write_text('{"user": "ali"}')
    (user / "settings.json").write_text('{"theme": "crimson"}')
    cached = str(legacy / "users" / "ali" / "audio_cache" / "a.mp3")
    (user / "spotify_lite_playlist.json").write_text(json.dumps(
        {"Liste": [{"title": "x", "cached_path": cached, "local_path": "D:/muzik/b.mp3"}]}))
    assert migrate_legacy_data(legacy, target) is True
    assert (target / "users.json").read_text() == '{"ali": {}}'
    assert json.loads((target / "users/ali/settings.json").read_text()) == {"theme": "crimson"}
    song = json.loads((target / "users/ali/spotify_lite_playlist.json").read_text())["Liste"][0]
    assert song["cached_path"] == str(target / "users" / "ali" / "audio_cache" / "a.mp3")
    assert song["local_path"] == "D:/muzik/b.mp3"                  # dış yol aynen kalır
    assert (legacy / "users.json").exists()                         # eski veri silinmez
    assert (legacy / MIGRATED_MARKER).is_file()
    # Taşıma sonrası eski klasör artık kullanılmaz
    got = default_data_root(legacy / "mustiefly_qt", environ={}, platform="linux", home=tmp_path, frozen=False)
    assert got == str(tmp_path / ".local/share/Audifly")


def test_migration_never_overwrites_existing_user_data(tmp_path):
    legacy, target = tmp_path / "old", tmp_path / "new"
    legacy.mkdir()
    target.mkdir()
    (legacy / "users.json").write_text('{"eski": {}}')
    (target / "users.json").write_text('{"yeni": {}}')
    assert migrate_legacy_data(legacy, target) is False
    assert (target / "users.json").read_text() == '{"yeni": {}}'

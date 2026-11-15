"""
auth/service.py için testler.

PySide6/VLC gerektirmez — sadece stdlib (hashlib, json, os) kullanır, bu
yüzden GUI bağımlılıkları kurulu olmasa bile CI'da çalışabilir.
"""
import importlib

import pytest


@pytest.fixture()
def service(tmp_path, monkeypatch):
    """Her testte auth.service modülünü taze bir geçici klasöre yönlendirir,
    böylece testler gerçek users.json dosyasına asla dokunmaz."""
    from mustiefly_qt.auth import service as svc

    importlib.reload(svc)
    monkeypatch.setattr(svc, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(svc, "USERS_DIR", str(tmp_path / "users"))
    monkeypatch.setattr(svc, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(svc, "SESSION_FILE", str(tmp_path / "last_session.json"))
    return svc


class TestPasswordHashing:
    def test_hash_then_verify_succeeds(self, service):
        salt, digest = service._hash_password("dogru-sifre123")
        assert service._verify_password("dogru-sifre123", salt, digest)

    def test_verify_rejects_wrong_password(self, service):
        salt, digest = service._hash_password("dogru-sifre123")
        assert not service._verify_password("yanlis-sifre", salt, digest)

    def test_same_password_different_salts_gives_different_hash(self, service):
        _, digest1 = service._hash_password("ayni-sifre")
        _, digest2 = service._hash_password("ayni-sifre")
        assert digest1 != digest2  # farklı rastgele salt üretildiği için


class TestUsernameValidation:
    @pytest.mark.parametrize("username", [
        "ahmet", "Ahmet_123", "user.name", "a-b-c", "abc",
    ])
    def test_valid_usernames_accepted(self, service, username):
        assert service.is_valid_username(username)

    @pytest.mark.parametrize("username", [
        "", "ab", "a" * 33,
        "../../evil", "..", ".",
        "with space", "türkçe", "user/name", "user\\name",
        "user:name", "<script>",
    ])
    def test_invalid_usernames_rejected(self, service, username):
        assert not service.is_valid_username(username)

    def test_path_traversal_username_cannot_escape_users_dir(self, service):
        """register() bir path-traversal kullanıcı adını reddetmeli, ki
        _user_dir() ile birleştirildiğinde users/ klasörünün dışına
        çıkılamasın."""
        ok, message = service.register("../../evil", "sifre1234")
        assert not ok
        assert "kullanıcı adı" in message.lower()


class TestRegisterAndLogin:
    def test_register_then_login_succeeds(self, service):
        ok, _ = service.register("testuser", "gizlisifre")
        assert ok
        ok, _ = service.login("testuser", "gizlisifre")
        assert ok

    def test_login_with_wrong_password_fails(self, service):
        service.register("testuser", "gizlisifre")
        ok, message = service.login("testuser", "baska-sifre")
        assert not ok
        assert message

    def test_login_with_unknown_user_fails(self, service):
        ok, message = service.login("hic-yok", "hersey")
        assert not ok
        assert message

    def test_cannot_register_same_username_twice(self, service):
        service.register("testuser", "sifre1234")
        ok, message = service.register("testuser", "baska-sifre")
        assert not ok
        assert "alınmış" in message

    def test_register_rejects_empty_fields(self, service):
        ok, _ = service.register("", "sifre1234")
        assert not ok
        ok, _ = service.register("testuser", "")
        assert not ok

    def test_register_rejects_short_password(self, service):
        ok, message = service.register("testuser", "abc")
        assert not ok
        assert "şifre" in message.lower()

    def test_user_data_paths_are_created_under_users_dir(self, service):
        service.register("testuser", "sifre1234")
        paths = service.user_data_paths("testuser")
        paths.ensure_dirs()
        import os
        assert os.path.isdir(paths.dir)
        assert paths.dir.startswith(service.USERS_DIR)


@pytest.mark.parametrize("username", ["CON", "con.mp3", "AUX", "NUL", "COM1", "LPT9", "abc.", "abc\n"])
def test_windows_reserved_and_ambiguous_names_rejected(service, username):
    assert not service.is_valid_username(username)


@pytest.mark.parametrize("entry", [{}, {"salt": "not-hex", "password_hash": "x"}, "broken", None])
def test_malformed_account_does_not_crash(service, entry):
    import json
    from pathlib import Path
    Path(service.USERS_FILE).write_text(json.dumps({"testuser": entry}), encoding="utf-8")
    assert not service.login("testuser", "password")[0]


def test_failed_account_write_does_not_claim_success(service, monkeypatch):
    monkeypatch.setattr(service, "_save_users", lambda users: False)
    ok, message = service.register("testuser", "password")
    assert not ok and "kaydedilemedi" in message


def test_corrupt_account_file_is_not_overwritten(service):
    from pathlib import Path
    path = Path(service.USERS_FILE)
    path.write_text("broken accounts", encoding="utf-8")
    assert not service.register("newuser", "password")[0]
    assert path.read_text(encoding="utf-8") == "broken accounts"


def test_case_insensitive_duplicate_is_rejected(service):
    assert service.register("TestUser", "password")[0]
    assert not service.register("testuser", "password")[0]


def test_path_api_rejects_traversal(service):
    with pytest.raises(ValueError):
        service.user_data_paths("../../outside")


def test_new_registration_requires_eight_characters(service):
    assert not service.register("testuser", "1234567")[0]


def test_legacy_short_password_can_still_login(service):
    salt, digest = service._hash_password("1234")
    assert service._save_users({"legacy": {"salt": salt, "password_hash": digest}})
    assert service.login("legacy", "1234")[0]

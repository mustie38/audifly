"""
Tests for multi-user / public-readiness features:
- Passwordless Quick Start (Guest profile)
- Empty-library Welcome Onboarding card
- Discord RPC toggle, Custom Cache Dir, Reset Settings to Defaults
- EN localization & Global-first Discovery ordering
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtWidgets import QMessageBox

from mustiefly_qt.auth import service as auth_svc
from mustiefly_qt.helpers import i18n
from mustiefly_qt.services import playback as pb_mod
from mustiefly_qt.views.home_view import HomeView
from mustiefly_qt.views.settings_dialog import SettingsView


def test_quick_start_user_creates_and_remembers_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_svc, "USERS_DIR", str(tmp_path / "users"))
    monkeypatch.setattr(auth_svc, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(auth_svc, "SESSION_FILE", str(tmp_path / "session.json"))

    ok, name = auth_svc.quick_start_user("Misafir")
    assert ok is True
    assert name == "Misafir"
    assert auth_svc.get_remembered_username() == "Misafir"

    # Second call reuses existing profile cleanly
    ok2, name2 = auth_svc.quick_start_user("Misafir")
    assert ok2 is True and name2 == "Misafir"


def test_home_view_onboarding_card_visibility(library_store, qapp, monkeypatch):
    monkeypatch.setattr(pb_mod.vlc, "Instance", lambda *a, **k: MagicMock())
    engine = pb_mod.PlaybackEngine(library_store, library_store.paths, {})
    library_store.playlists = {"Varsayılan": []}
    view = HomeView(library_store, engine)
    try:
        view.refresh()
        assert view.onboarding_card.isHidden() is False

        library_store.playlists["Varsayılan"].append(
            {"title": "Şarkı", "uploader": "Sanatçı", "webpage_url": "https://youtu.be/1"}
        )
        view.refresh()
        assert view.onboarding_card.isHidden() is True
    finally:
        view.close()
        engine.shutdown()


def test_settings_view_discord_toggle_cache_dir_and_reset_defaults(library_store, qapp, monkeypatch):
    settings = {
        "theme": "crimson",
        "discord_rpc_enabled": False,
        "custom_cache_dir": "D:/CustomCache",
        "radio_favorites": {"id1": {"name": "FM"}},
    }
    view = SettingsView(library_store.paths, settings, store=library_store)
    try:
        assert view.discord_enabled_check.isChecked() is False
        assert view.cache_dir_edit.text() == "D:/CustomCache"

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        monkeypatch.setattr(view, "_save_settings_file", lambda: None)
        view._reset_to_defaults()

        assert settings["discord_rpc_enabled"] is True
        assert settings["custom_cache_dir"] == ""
        assert settings["radio_favorites"] == {"id1": {"name": "FM"}}
        assert view.discord_enabled_check.isChecked() is True
        assert view.cache_dir_edit.text() == ""
    finally:
        view.close()


def test_i18n_new_public_features_translations():
    prev = i18n.current_language()
    try:
        i18n.set_language("en")
        assert i18n.tr("⚡ Hesapsız Hızlı Başla") == "⚡ Quick Start (No Account)"
        assert i18n.tr("🔄 Ayarları Varsayılana Sıfırla") == "🔄 Reset Settings to Defaults"
        assert i18n.tr("Discord'da Çalan Şarkıyı Göster") == "Show Now Playing on Discord"
    finally:
        i18n.set_language(prev)

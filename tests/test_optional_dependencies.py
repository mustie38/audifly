from unittest.mock import MagicMock
from pathlib import Path


def test_relay_wheel_dependency_is_installed_and_wheels_are_ignored():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    relay_requirements = (root / "relay_server" / "requirements.txt").read_text(encoding="utf-8")
    ci_workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "*.whl" in gitignore
    assert "websockets>=13.0" in relay_requirements
    assert "pip install -r relay_server/requirements.txt" in ci_workflow
    assert not list(root.glob("*.whl"))


def test_windows_acceptance_checklist_is_documented():
    guide = (Path(__file__).resolve().parents[1] / "DAGITIM_REHBERI_TR.md")
    text = guide.read_text(encoding="utf-8")
    checklist_items = (
        "VLC + FFmpeg + Node",
        "SMTC:",
        "Medya tuşları:",
        "Tepsiye küçült",
        "Crossfade:",
        "Yerel mp3 ekle",
        "İndirme: FFmpeg",
        "Birlikte Dinle:",
        "Oda şifresi:",
        "Şarkı sözleri:",
        "Wrapped PNG export",
    )

    assert all(f"- [ ] {item}" in text for item in checklist_items)


def test_smtc_cover_ready_is_a_signal():
    from PySide6.QtCore import Signal
    from mustiefly_qt.services.smtc import SMTCService

    assert isinstance(SMTCService._coverReady, Signal)


def test_single_instance_connection_uses_configured_timeout(monkeypatch):
    from mustiefly_qt import main

    waits = []

    class FakeSocket:
        def connectToServer(self, _key):
            pass

        def waitForConnected(self, timeout):
            waits.append(("connected", timeout))
            return True

        def write(self, _data):
            pass

        def flush(self):
            pass

        def waitForBytesWritten(self, timeout):
            waits.append(("written", timeout))
            return True

        def disconnectFromServer(self):
            pass

    monkeypatch.setattr(main, "QLocalSocket", FakeSocket)
    assert main._connect_existing_and_raise()
    assert main.INSTANCE_CONNECT_TIMEOUT_MS == 1500
    assert waits == [("connected", 1500), ("written", 1500)]


def test_main_imports_without_discord_dependency():
    import mustiefly_qt.main  # noqa: F401


def test_missing_presence_does_not_start_worker(library_store, monkeypatch):
    from mustiefly_qt.services import discord_rpc
    monkeypatch.setattr(discord_rpc, "Presence", None)
    def forbidden(*args, **kwargs):
        raise AssertionError("Optional dependency missing: must not start a worker")
    monkeypatch.setattr(discord_rpc.threading, "Thread", forbidden)
    service = discord_rpc.DiscordRPCService("dummy-id", MagicMock())
    assert not service.is_connected
    service.close()

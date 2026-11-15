"""
Test konfigürasyonu.

Bu dosya proje kökünün bir üstünü (mustiefly_qt paketinin kendisini değil,
onu İÇEREN klasörü) sys.path'e ekler, çünkü paket içi importlar
"mustiefly_qt.xxx" şeklinde mutlak (absolute) yapılıyor — tıpkı main.py'nin
yaptığı gibi.
"""
import sys
import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent   # .../mustiefly_qt
_PARENT_DIR = _PACKAGE_ROOT.parent                        # .../  (mustiefly_qt'yi içeren klasör)

if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# PySide6 gerektiren testler (test_playlist_store.py gibi) ekran olmayan bir
# CI/sunucu ortamında da çalışabilsin diye: Qt'yi "offscreen" platformuna
# zorla. Geliştiricinin masaüstünde çalıştırırken gerçek pencere açılmasını
# istemiyoruz zaten — bu sadece testler için.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config):
    """PySide6 kurulu değilse onu gerektiren testleri sessizce atla (skip)
    — bu dosyalar CI'da/pytest-qt kurulu olmayan bir makinede de en azından
    çökmeden çalışsın."""
    try:
        import PySide6  # noqa: F401
    except Exception:
        config.addinivalue_line(
            "markers", "requires_qt: PySide6 gerektirir (kurulu değilse atlanır)"
        )


import pytest


def _install_fake_vlc_if_needed():
    """CI'da (GitHub Actions) libvlc kurulu değil: 'import vlc' modül yüklenirken patlar ve
    playback.py'yi içe aktaran testler toplanamaz. Gerçek vlc yüklenemiyorsa (ya da
    AUDIFLY_FAKE_VLC=1 ise) testler için asgari bir sahte 'vlc' modülü yerleştirilir.
    Testler zaten vlc.Instance'ı kendileri taklit eder (monkeypatch)."""
    if not os.environ.get("AUDIFLY_FAKE_VLC"):
        try:
            import vlc  # noqa: F401
            return
        except Exception:
            pass
    import enum
    import types
    from unittest.mock import MagicMock

    class State(enum.IntEnum):
        NothingSpecial = 0
        Opening = 1
        Buffering = 2
        Playing = 3
        Paused = 4
        Stopped = 5
        Ended = 6
        Error = 7

    fake = types.ModuleType("vlc")
    fake.State = State
    fake.Instance = lambda *a, **k: None
    fake.Media = MagicMock
    fake.AudioEqualizer = MagicMock
    fake.libvlc_get_version = lambda: b"fake-vlc"
    fake.libvlc_audio_equalizer_get_band_count = lambda: 10
    fake.libvlc_audio_equalizer_get_preset_count = lambda: 0
    fake.libvlc_audio_equalizer_get_preset_name = lambda i: b""
    fake.libvlc_audio_equalizer_get_band_frequency = lambda i: 60.0
    fake.libvlc_audio_equalizer_new_from_preset = lambda i: MagicMock()
    sys.modules["vlc"] = fake


_install_fake_vlc_if_needed()


@pytest.fixture()
def library_store(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from mustiefly_qt.helpers.constants import AppPaths
    from mustiefly_qt.services.playlist_store import PlaylistStore
    app = QApplication.instance() or QApplication([])
    paths = AppPaths(str(tmp_path), str(tmp_path / "user"),
                     str(tmp_path / "user" / "playlist.json"),
                     str(tmp_path / "user" / "settings.json"),
                     str(tmp_path / "user" / "audio_cache"),
                     str(tmp_path / "user" / "covers"))
    paths.ensure_dirs()
    store = PlaylistStore(paths)
    store.backup_enabled = False
    yield store
    store.flush_now()
    store._save_timer.stop()
    for timer in store._pending_file_deletions.values():
        timer.stop()
    app.processEvents()

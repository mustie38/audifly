"""Uygulama verisinin (users.json, users/, ayarlar, loglar) yazılacağı klasör.

Kural: veri HER ZAMAN kullanıcının veri klasörüne yazılır
(Windows: %LOCALAPPDATA%\\Audifly). Proje klasörünün yanına / masaüstüne /
kurulum klasörüne yazılmaz.

Tek istisna ESKİ kurulumlar: eski sürümler `users.json` dosyasını proje klasörünün
bir üstüne (kaynaktan çalıştırma) ya da .exe'nin yanına yazıyordu. Böyle bir
dosya bulunursa içerik bir kez kullanıcı veri klasörüne KOPYALANIR (çevrimdışı
şarkı yolları yeni konuma göre düzeltilir), eski klasöre bir işaret dosyası
bırakılır ve bundan sonra yalnız yeni konum kullanılır. Eski dosyalar silinmez.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

MIGRATED_MARKER = "AUDIFLY_TASINDI.txt"
_DATA_FILES = ("users.json", "last_session.json")


def _user_data_dir(environ, platform, home) -> Path:
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    new_dir, old_dir = base / "Audifly", base / "Mustiefly"
    # Eski "Mustiefly" klasörü varsa onu kullanmaya devam et: kütüphane dosyasındaki
    # mutlak `cached_path` yolları klasör adı değişirse kırılır.
    if not new_dir.exists() and old_dir.is_dir():
        return old_dir
    return new_dir


def legacy_dir(package_root=None, *, frozen=None) -> Path:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    package_root = Path(package_root or Path(__file__).resolve().parent.parent)
    return Path(sys.executable).resolve().parent if frozen else package_root.parent


def has_legacy_data(legacy: Path) -> bool:
    return (legacy / "users.json").is_file() and not (legacy / MIGRATED_MARKER).is_file()


def default_data_root(package_root=None, *, environ=None, platform=None, home=None, frozen=None):
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    override = environ.get("AUDIFLY_DATA_DIR") or environ.get("MUSTIEFLY_DATA_DIR")
    if override:
        return str(Path(override).expanduser().resolve())
    legacy = legacy_dir(package_root, frozen=frozen)
    if has_legacy_data(legacy):
        return str(legacy)    # taşıma henüz yapılmadı / yapılamadı: veri kaybetme
    return str(_user_data_dir(environ, platform, home))


def _rewrite_paths(obj, old_prefix: str, new_prefix: str):
    if isinstance(obj, str):
        if obj.startswith(old_prefix):
            return new_prefix + obj[len(old_prefix):]
        return obj
    if isinstance(obj, list):
        return [_rewrite_paths(x, old_prefix, new_prefix) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_paths(v, old_prefix, new_prefix) for k, v in obj.items()}
    return obj


def migrate_legacy_data(legacy: Path, target: Path) -> bool:
    """legacy → target kopyası (eskiyi silmez). Başarılıysa True."""
    legacy, target = Path(legacy), Path(target)
    try:
        if not has_legacy_data(legacy) or (target / "users.json").is_file():
            return False
        target.mkdir(parents=True, exist_ok=True)
        for name in _DATA_FILES:
            if (legacy / name).is_file():
                shutil.copy2(legacy / name, target / name)
        old_users, new_users = legacy / "users", target / "users"
        if old_users.is_dir():
            shutil.copytree(old_users, new_users, dirs_exist_ok=True)
            # Çevrimdışı şarkı yolları (mutlak) yeni konuma göre güncellenir.
            for playlist in new_users.glob("*/spotify_lite_playlist.json"):
                try:
                    data = json.loads(playlist.read_text(encoding="utf-8"))
                    fixed = _rewrite_paths(data, str(old_users), str(new_users))
                    playlist.write_text(json.dumps(fixed, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
                except (OSError, ValueError):
                    pass     # okunamayan dosya kopya olarak kalır; kayıp yok
        (legacy / MIGRATED_MARKER).write_text(
            "Audifly verileri şu klasöre kopyalandı ve artık oradan kullanılıyor:\n"
            f"{target}\n\nBu klasördeki users.json, users/, last_session.json ve logs/ "
            "dosyalarını yedekledikten sonra silebilirsin.\n", encoding="utf-8")
        return True
    except OSError:
        return False


def prepare_data_root() -> str:
    """Açılışta çağrılır: gerekirse eski veriyi taşır, kullanılacak klasörü döndürür."""
    root = default_data_root()
    legacy = legacy_dir()
    if not os.environ.get("AUDIFLY_DATA_DIR") and not os.environ.get("MUSTIEFLY_DATA_DIR") \
            and Path(root) == legacy and has_legacy_data(legacy):
        target = _user_data_dir(os.environ, sys.platform, Path.home())
        if migrate_legacy_data(legacy, target):
            return str(target)
    return root

"""
Mustiefly (Qt) - Basit yerel giriş/kayıt sistemi.

Sunucu yok; hesaplar tamamen bu bilgisayarda saklanır. Her kullanıcının
playlist/ayarlar/kapak/önbellek verisi ayrı bir 'users/<kullanici_adi>/'
klasöründe tutulur. Dosya formatı orijinal (tkinter) sürümle birebir uyumludur
(users.json, last_session.json, users/<ad>/...), yani eski bir kurulumdan
geçen kullanıcılar hesaplarını ve playlist'lerini kaybetmez.
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import secrets
import time

from mustiefly_qt.helpers import secrets_store
from mustiefly_qt.helpers.persistence import atomic_write_json
from mustiefly_qt.helpers.data_paths import prepare_data_root

from mustiefly_qt.helpers.constants import AppPaths, DEFAULT_SETTINGS, DEFAULT_THEME_KEY, THEMES
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
BASE_DIR = prepare_data_root()
USERS_DIR = os.path.join(BASE_DIR, "users")
USERS_FILE = os.path.join(BASE_DIR, "users.json")
SESSION_FILE = os.path.join(BASE_DIR, "last_session.json")

# Kullanıcı adı doğrudan bir klasör adı olarak kullanıldığı için (users/<ad>/),
# harf/rakam/alt çizgi/tire/nokta dışında hiçbir şeye izin verilmez. Bu,
# "../../evil" gibi bir kullanıcı adıyla users/ klasörünün dışına çıkılmasını
# (path traversal) engeller. Türkçe karakterler de burada kasıtlı olarak dışarıda
# bırakılıyor çünkü dosya sistemleri arası (Windows/Linux/Mac) tutarlı
# normalize garantisi yok.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def is_valid_username(username: str) -> bool:
    if not username:
        return False
    if not isinstance(username, str) or username.endswith("."):
        return False
    # Windows device names remain reserved even with an extension.
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if username.split(".")[0].upper() in reserved:
        return False
    return bool(_USERNAME_RE.fullmatch(username))


def _load_users(*, strict=False) -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Hesap dosyası bir JSON nesnesi olmalı.")
        return data
    except Exception as e:
        log.error("%s %s", "users.json okunamadı:", e)
        if strict:
            raise
        return {}


def _save_users(users: dict):
    try:
        atomic_write_json(USERS_FILE, users, indent=2)
        return True
    except Exception as e:
        log.error("%s %s", "users.json kaydedilemedi:", e)
        return False


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    try:
        _, computed = _hash_password(password, salt)
        return secrets.compare_digest(computed, expected_hash)
    except (TypeError, ValueError):
        return False


def _user_dir(username: str) -> str:
    if not is_valid_username(username):
        raise ValueError("Geçersiz kullanıcı adı.")
    root = os.path.realpath(USERS_DIR)
    destination = os.path.realpath(os.path.join(root, username))
    if os.path.commonpath([root, destination]) != root:
        raise ValueError("Kullanıcı klasörü izin verilen dizinin dışında.")
    return destination


def user_data_paths(username: str) -> AppPaths:
    d = _user_dir(username)
    return AppPaths(
        base_dir=BASE_DIR,
        dir=d,
        playlist_file=os.path.join(d, "spotify_lite_playlist.json"),
        settings_file=os.path.join(d, "settings.json"),
        cache_dir=os.path.join(d, "audio_cache"),
        covers_dir=os.path.join(d, "playlist_covers"),
    )


def register(username: str, password: str) -> tuple[bool, str]:
    if not username or not password:
        return False, "Kullanıcı adı ve şifre boş olamaz."
    if not is_valid_username(username):
        return False, (
            "Kullanıcı adı 3-32 karakter olmalı ve sadece harf (a-z, A-Z), "
            "rakam, nokta, tire veya alt çizgi içerebilir."
        )
    if len(password) < 8:
        return False, "Şifre en az 8 karakter olmalı."
    try:
        users = _load_users(strict=True)
    except Exception:
        return False, "Hesap dosyası okunamadı; mevcut hesapları korumak için kayıt durduruldu."
    if any(name.casefold() == username.casefold() for name in users):
        return False, "Bu kullanıcı adı zaten alınmış."
    salt, pw_hash = _hash_password(password)
    users[username] = {"salt": salt, "password_hash": pw_hash}
    try:
        paths = user_data_paths(username)
        paths.ensure_dirs()
    except (OSError, ValueError):
        return False, "Kullanıcı klasörü oluşturulamadı."
    if not _save_users(users):
        return False, "Hesap kaydedilemedi. Disk alanını ve yazma izinlerini kontrol et."
    return True, ""


def login(username: str, password: str) -> tuple[bool, str]:
    if not is_valid_username(username):
        return False, "Kullanıcı adı veya şifre hatalı."
    try:
        _user_dir(username)
    except ValueError:
        return False, "Kullanıcı adı veya şifre hatalı."
    users = _load_users()
    entry = users.get(username)
    if (not isinstance(entry, dict)
            or not _verify_password(password, entry.get("salt"), entry.get("password_hash"))):
        return False, "Kullanıcı adı veya şifre hatalı."
    return True, ""


def save_last_session(username: str, remember: bool):
    try:
        if remember:
            if not is_valid_username(username):
                raise ValueError("Geçersiz kullanıcı adı.")
            atomic_write_json(SESSION_FILE, {"username": username})
        elif os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception as e:
        log.error("%s %s", "Oturum bilgisi kaydedilemedi:", e)


def get_remembered_username() -> str | None:
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            username = json.load(f).get("username")
    except Exception:
        return None
    if is_valid_username(username) and username in _load_users():
        try:
            _user_dir(username)
        except ValueError:
            return None
        return username
    return None


def logout_current_user():
    if os.path.exists(SESSION_FILE):
        try:
            os.remove(SESSION_FILE)
        except Exception as e:
            log.error("%s %s", "Oturum kapatılamadı:", e)


SETTINGS_VERSION = 2

# anahtar -> (tip, min, max). Bozuk/aralık dışı değerler varsayılana döner.
_SETTING_RULES = {
    "page_size": (int, 10, 500),
    "thumbnail_max_workers": (int, 1, 16),
    "crossfade_seconds": (int, 1, 12),
    "equalizer_preamp": (float, -20.0, 20.0),
    "audio_normalization": (bool,),
    "minimize_to_tray": (bool,),
    "global_media_keys": (bool,),
    "dynamic_theme": (bool,),
    "equalizer_enabled": (bool,),
    "backup_enabled": (bool,),
    "now_playing_panel_visible": (bool,),
    "restore_session": (bool,),
    "smtc_enabled": (bool,),
    "crossfade_enabled": (bool,),
    "sleep_fade_enabled": (bool,),
    "dependency_notice_dismissed": (bool,),
    "auto_update_check": (bool,),
    "auto_ytdlp_update": (bool,),
    "hud_overlay_enabled": (bool,),
    "hud_overlay_duration": (int, 2, 10),
    "hud_overlay_only_background": (bool,),
}


def validate_settings(settings: dict) -> dict:
    """Tip/aralık doğrular; geçersiz alanları varsayılanla değiştirir (yerinde)."""
    for key, rule in _SETTING_RULES.items():
        if key not in settings:
            continue
        value, kind = settings[key], rule[0]
        ok = isinstance(value, bool) if kind is bool else (
            isinstance(value, (int, float)) and not isinstance(value, bool))
        if ok and kind is not bool:
            ok = rule[1] <= value <= rule[2]
            if ok:
                settings[key] = kind(value)
        if not ok:
            log.warning("Geçersiz ayar '%s' varsayılana döndürüldü.", key)
            settings[key] = DEFAULT_SETTINGS[key]
    bands = settings.get("equalizer_bands")
    if not (isinstance(bands, list) and len(bands) == 10 and all(
            isinstance(b, (int, float)) and not isinstance(b, bool) and -20 <= b <= 20 for b in bands)):
        settings["equalizer_bands"] = [0.0] * 10
    from mustiefly_qt.services.smart_lists import sanitize_rules
    settings["smart_rules"] = sanitize_rules(settings.get("smart_rules"))
    if settings.get("theme") not in THEMES:
        settings["theme"] = DEFAULT_THEME_KEY
    from mustiefly_qt.helpers.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
    if settings.get("language") not in SUPPORTED_LANGUAGES:
        settings["language"] = DEFAULT_LANGUAGE
    return settings


def _migrate_settings(settings: dict) -> dict:
    """Sürümlü şema geçişi. Bilinmeyen anahtarlar korunur (veri kaybı yok)."""
    version = settings.get("settings_version", 1)
    if not isinstance(version, int) or version < 1:
        version = 1
    # v1 -> v2: yalnızca sürüm alanı eklendi; alanlar uyumlu.
    settings["settings_version"] = max(version, SETTINGS_VERSION)
    return settings


def _quarantine(path: str) -> None:
    """Okunamayan dosyayı üzerine yazılmasın diye kenara al."""
    try:
        os.replace(path, f"{path}.corrupt-{int(time.time())}")
    except OSError as e:
        log.error("Bozuk dosya ayrılamadı: %s", e)


def _user_of(paths: AppPaths) -> str:
    return os.path.basename(os.path.normpath(paths.dir))


def load_settings_for(paths: AppPaths) -> dict:
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if os.path.exists(paths.settings_file):
        try:
            with open(paths.settings_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if not isinstance(saved, dict):
                raise ValueError("Ayar dosyası bir JSON nesnesi olmalı.")
            settings.update(saved)
        except Exception as e:
            log.error("%s %s", "Ayarlar okunamadı, varsayılanlar kullanılıyor:", e)
            _quarantine(paths.settings_file)
    settings = validate_settings(_migrate_settings(settings))
    # Keyring'deki gizli değerleri belleğe al; dosyada düz metin varsa taşı.
    user = _user_of(paths)
    migrated = False
    for key in secrets_store.SECRET_SETTING_KEYS:
        stored = secrets_store.get_secret(user, key)
        if stored:
            settings[key] = stored
        elif settings.get(key) and secrets_store.set_secret(user, key, settings[key]):
            migrated = True
    if migrated:
        save_settings_for(paths, settings)  # düz metni dosyadan temizle
    return settings


def save_settings_for(paths: AppPaths, settings: dict) -> bool:
    """TÜM ayar yazımları için tek yol: atomik + gizli değerler keyring'e."""
    data = dict(settings)
    user = _user_of(paths)
    for key in secrets_store.SECRET_SETTING_KEYS:
        value = data.get(key)
        if secrets_store.set_secret(user, key, value or ""):
            data.pop(key, None)   # keyring'e yazıldı: dosyada tutma
    data["settings_version"] = SETTINGS_VERSION
    try:
        atomic_write_json(paths.settings_file, data, indent=2)
        return True
    except Exception as e:
        log.error("%s %s", "Ayarlar kaydedilemedi:", e)
        return False


def theme_for(paths: AppPaths):
    """Kullanıcının kayıtlı temasını döner (Theme nesnesi)."""
    settings = load_settings_for(paths)
    key = settings.get("theme", DEFAULT_THEME_KEY)
    return THEMES.get(key, THEMES[DEFAULT_THEME_KEY])

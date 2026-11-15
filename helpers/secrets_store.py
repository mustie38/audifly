"""Gizli değerler (Spotify secret/token) için işletim sistemi kimlik bilgisi deposu.

`keyring` kuruluysa ve çalışıyorsa değerler orada tutulur; aksi halde
çağıran taraf değeri eskisi gibi ayar dosyasında bırakır (veri kaybı olmaz).
"""
from __future__ import annotations

from mustiefly_qt.helpers.logging_setup import get_logger

log = get_logger(__name__)
SERVICE_NAME = "Audifly"
LEGACY_SERVICE_NAME = "Mustiefly"   # eski sürümde kaydedilmiş gizli değerler okunabilsin
SECRET_SETTING_KEYS = ("spotify_client_secret", "spotify_refresh_token", "spotify_access_token")

try:
    import keyring
    from keyring.errors import KeyringError
    KEYRING_IMPORTED = True
except Exception:  # paket yok / backend yüklenemedi
    keyring = None
    KeyringError = Exception
    KEYRING_IMPORTED = False


def _name(user: str, key: str) -> str:
    return f"{user}:{key}"


def is_available() -> bool:
    if not KEYRING_IMPORTED:
        return False
    try:
        backend = keyring.get_keyring()
        return getattr(backend, "priority", 0) > 0
    except Exception:
        return False


def get_secret(user: str, key: str) -> str | None:
    if not is_available():
        return None
    try:
        value = keyring.get_password(SERVICE_NAME, _name(user, key))
        if value is None:   # eski ad altında kayıtlı olabilir → yeni ada taşı
            value = keyring.get_password(LEGACY_SERVICE_NAME, _name(user, key))
            if value:
                keyring.set_password(SERVICE_NAME, _name(user, key), value)
                try:
                    keyring.delete_password(LEGACY_SERVICE_NAME, _name(user, key))
                except Exception:
                    pass
        return value
    except Exception as e:
        log.warning("Keyring okunamadı (%s): %s", key, e)
        return None


def set_secret(user: str, key: str, value: str) -> bool:
    """Başarılıysa True. Boş değer silme anlamına gelir."""
    if not is_available():
        return False
    try:
        if value:
            keyring.set_password(SERVICE_NAME, _name(user, key), value)
        else:
            for service in (SERVICE_NAME, LEGACY_SERVICE_NAME):
                try:
                    keyring.delete_password(service, _name(user, key))
                except Exception:
                    pass
        return True
    except Exception as e:
        log.warning("Keyring'e yazılamadı (%s): %s", key, e)
        return False

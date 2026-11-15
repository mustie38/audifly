"""Audifly uygulama güncellemesi: GitHub Releases (mustie38/audifly).

Akış: son sürümü sor → sürümü karşılaştır → kurulum dosyasını indir → SHA-256 ile
doğrula → kurulumu başlat. Qt'ye bağımlılığı yoktur (arayüz services/app_updater.py ve
app_window.py'dedir).

Güvenlik kuralları:
- Yalnız bu deponun `releases/download/` adresindeki https bağlantıları indirilir.
- SHA-256 özeti olmayan ya da uyuşmayan dosya ASLA çalıştırılmaz.
- Taslak (draft) ve ön sürüm (prerelease) yayınları önerilmez.

Yayın düzeni (CI release.yml bunu üretir): `AudiflySetup.exe` + `AudiflySetup.exe.sha256`
(ya da GitHub'ın asset `digest` alanı).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import requests
from packaging.version import InvalidVersion, Version

from mustiefly_qt.helpers.constants import APP_VERSION

REPO = "mustie38/audifly"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
INSTALLER_NAME = "AudiflySetup.exe"
CHECKSUM_NAME = INSTALLER_NAME + ".sha256"
TIMEOUT = 10
MAX_INSTALLER_BYTES = 600 * 1024 * 1024
MAX_NOTES_CHARS = 1500
_HEX64 = re.compile(r"\b([0-9a-fA-F]{64})\b")

UP_TO_DATE, AVAILABLE, NO_RELEASE = "up_to_date", "available", "no_release"


class UpdateError(Exception):
    """Kullanıcıya gösterilebilir güncelleme hatası."""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    page_url: str
    installer_url: str | None
    sha256: str | None
    size: int = 0

    @property
    def can_auto_install(self) -> bool:
        return bool(self.installer_url and self.sha256)


def parse_version(tag) -> Version | None:
    try:
        return Version(str(tag or "").strip().lstrip("vV"))
    except InvalidVersion:
        return None


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def _trusted_download(url) -> bool:
    return isinstance(url, str) and url.startswith(DOWNLOAD_PREFIX)


def _digest_of(asset: dict) -> str | None:
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        value = digest.split(":", 1)[1].strip()
        if re.fullmatch(r"[0-9a-fA-F]{64}", value):
            return value.lower()
    return None


def parse_release(data) -> tuple[ReleaseInfo | None, str | None]:
    """(bilgi, özet_dosyası_adresi). Geçersiz/taslak/ön sürüm → (None, None)."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None, None
    tag = data.get("tag_name")
    version = parse_version(tag)
    if version is None:
        return None, None
    installer_url = sha = checksum_url = None
    size = 0
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        if name == INSTALLER_NAME and _trusted_download(url):
            installer_url, sha = url, _digest_of(asset)
            size = asset.get("size") if isinstance(asset.get("size"), int) else 0
        elif name == CHECKSUM_NAME and _trusted_download(url):
            checksum_url = url
    page = data.get("html_url")
    if not (isinstance(page, str) and page.startswith(f"https://github.com/{REPO}/")):
        page = RELEASES_PAGE
    notes = str(data.get("body") or "").strip()[:MAX_NOTES_CHARS]
    info = ReleaseInfo(str(version), str(tag), notes, page, installer_url, sha, size)
    return info, (None if sha else checksum_url)


def parse_checksum_text(text: str) -> str | None:
    match = _HEX64.search(text or "")
    return match.group(1).lower() if match else None


def fetch_latest_release(get=requests.get) -> ReleaseInfo | None:
    """Son yayın; hiç yayın yoksa None. Ağ/biçim hatasında UpdateError."""
    try:
        resp = get(API_LATEST, timeout=TIMEOUT,
                   headers={"Accept": "application/vnd.github+json", "User-Agent": "Audifly"})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        info, checksum_url = parse_release(resp.json())
        if info is None:
            return None
        if checksum_url and info.installer_url:
            sha_resp = get(checksum_url, timeout=TIMEOUT, headers={"User-Agent": "Audifly"})
            sha_resp.raise_for_status()
            sha = parse_checksum_text(sha_resp.text[:4096])
            if sha:
                info = ReleaseInfo(info.version, info.tag, info.notes, info.page_url,
                                   info.installer_url, sha, info.size)
        return info
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Güncelleme sunucusuna ulaşılamadı: {e}") from e


def check_for_update(current: str = APP_VERSION, get=requests.get) -> tuple[str, ReleaseInfo | None]:
    info = fetch_latest_release(get)
    if info is None:
        return NO_RELEASE, None
    return (AVAILABLE, info) if is_newer(info.version, current) else (UP_TO_DATE, info)


def verify_sha256(path: str, expected: str) -> bool:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == str(expected).strip().lower()


def download_installer(info: ReleaseInfo, dest_dir: str | None = None, progress=None,
                       cancelled=None, get=requests.get) -> str:
    """Kurulum dosyasını indirir ve doğrular; dosya yolunu döner. progress(yüzde 0-100)."""
    if not info.can_auto_install:
        raise UpdateError("Bu sürüm için doğrulanabilir kurulum dosyası yok; elle indir.")
    if not _trusted_download(info.installer_url):
        raise UpdateError("Güvenilmeyen indirme adresi reddedildi.")
    folder = dest_dir or tempfile.mkdtemp(prefix="audifly-update-")
    os.makedirs(folder, exist_ok=True)
    final = os.path.join(folder, f"AudiflySetup-{info.version}.exe")
    part = final + ".part"
    try:
        with get(info.installer_url, stream=True, timeout=TIMEOUT,
                 headers={"User-Agent": "Audifly"}) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or info.size or 0)
            if total > MAX_INSTALLER_BYTES:
                raise UpdateError("Kurulum dosyası beklenenden çok büyük; reddedildi.")
            done = 0
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if cancelled is not None and cancelled():
                        raise UpdateError("İndirme iptal edildi.")
                    if not chunk:
                        continue
                    done += len(chunk)
                    if done > MAX_INSTALLER_BYTES:
                        raise UpdateError("Kurulum dosyası beklenenden çok büyük; reddedildi.")
                    f.write(chunk)
                    if progress is not None and total:
                        progress(min(100, int(done * 100 / total)))
        if not verify_sha256(part, info.sha256):
            raise UpdateError("İndirilen dosya doğrulanamadı (SHA-256 uyuşmuyor); silindi.")
        os.replace(part, final)
        if progress is not None:
            progress(100)
        return final
    except UpdateError:
        _silent_remove(part)
        raise
    except Exception as e:
        _silent_remove(part)
        raise UpdateError(f"İndirme başarısız: {e}") from e


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def can_install_here() -> bool:
    """Kendi kendini kurma yalnız paketlenmiş Windows uygulamasında anlamlıdır."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def launch_installer(path: str) -> bool:
    """Kurulumu bağımsız süreç olarak başlatır (çağıran uygulamayı kapatmalıdır)."""
    if sys.platform != "win32" or not os.path.isfile(path):
        return False
    try:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([path], close_fds=True, creationflags=flags)
        return True
    except OSError:
        return False

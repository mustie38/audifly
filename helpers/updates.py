"""yt-dlp güncelleme kontrolü ve tek tıkla güncelleme.

YouTube sık sık çıkarım değiştirir; eski yt-dlp şarkı çalamaz hale gelir.
PyPI'daki son sürümle karşılaştırıp kullanıcıyı haberdar eder.
"""
from __future__ import annotations

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
import importlib.metadata
import subprocess
import sys

import requests
from packaging.version import InvalidVersion, Version

PYPI_TIMEOUT = 6
UPDATE_PACKAGES = ("yt-dlp", "yt-dlp-ejs")


def installed_version(package: str = "yt-dlp") -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def latest_pypi_version(package: str = "yt-dlp") -> str | None:
    try:
        resp = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=PYPI_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("info", {}).get("version")
    except Exception:
        return None


def update_available(package: str = "yt-dlp") -> tuple[bool, str | None, str | None]:
    """Dönüş: (güncelleme_var_mı, kurulu_sürüm, pypi_sürümü)."""
    inst = installed_version(package)
    latest = latest_pypi_version(package)
    if not inst or not latest:
        return False, inst, latest
    try:
        return Version(latest) > Version(inst), inst, latest
    except InvalidVersion:
        return False, inst, latest


def run_update() -> tuple[bool, str]:
    """pip ile yt-dlp + yt-dlp-ejs paketlerini günceller. Dönüş: (başarılı, özet)."""
    if getattr(sys, "frozen", False):
        return False, f"Paketlenmiş uygulama pip ile güncellenemez. Yeni {APP_DISPLAY_NAME} sürümünü kur."
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", *UPDATE_PACKAGES],
            capture_output=True, text=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = proc.returncode == 0
        tail = (proc.stdout or "").strip().splitlines()[-3:]
        err = (proc.stderr or "").strip().splitlines()[-2:]
        return ok, "\n".join(tail + err)
    except Exception as e:
        return False, str(e)

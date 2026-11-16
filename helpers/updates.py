"""yt-dlp güncelleme kontrolü ve tek tıkla güncelleme.

YouTube sık sık çıkarım değiştirir; eski yt-dlp şarkı çalamaz hale gelir.
PyPI'daki son sürümle karşılaştırıp kullanıcıyı haberdar eder.

Paketlenmiş (.exe) uygulamada `sys.executable -m pip` çalıştırılamaz (uygulamanın
kendisini tekrar açar); bu durumda saf Python wheel'leri doğrudan PyPI'den
kullanıcı veri klasörüne indirilir (:mod:`mustiefly_qt.helpers.ytdlp_runtime`) ve
bir sonraki açılışta devreye girer — yeni kurulum yayınlamaya gerek kalmaz.
"""
from __future__ import annotations

import importlib.metadata
import subprocess
import sys

import requests
from packaging.version import InvalidVersion, Version

from mustiefly_qt.helpers import ytdlp_runtime

PYPI_TIMEOUT = 6
UPDATE_PACKAGES = ("yt-dlp", "yt-dlp-ejs")


def installed_version(package: str = "yt-dlp") -> str | None:
    if package == "yt-dlp":
        pending = ytdlp_runtime.pending_version()
        if pending:
            return pending
        if ytdlp_runtime.ACTIVE_VERSION:
            return ytdlp_runtime.ACTIVE_VERSION
        try:
            from yt_dlp.version import __version__
            return __version__
        except Exception:
            pass
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
    """yt-dlp + yt-dlp-ejs paketlerini günceller. Dönüş: (başarılı, özet).

    Paketlenmiş uygulamada (`sys.frozen`) pip yoktur; wheel doğrudan kullanıcı
    klasörüne indirilir. Kaynaktan çalışırken önce pip denenir, başarısız olursa
    aynı kullanıcı klasörü mekanizmasına düşülür.
    """
    if getattr(sys, "frozen", False):
        ok, msg, _ver = ytdlp_runtime.install_latest()
        return ok, msg
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", *UPDATE_PACKAGES],
            capture_output=True, text=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = proc.returncode == 0
        tail = (proc.stdout or "").strip().splitlines()[-3:]
        err = (proc.stderr or "").strip().splitlines()[-2:]
        if ok:
            return True, "\n".join(tail + err)
    except Exception as e:
        err = [str(e)]
    # Kaynak ortamda pip yoksa / yetki hatası verdiyse yine uygulama içi indirmeyi dene
    ok, msg, _ver = ytdlp_runtime.install_latest()
    if ok:
        return True, msg
    return False, "\n".join(err) or msg

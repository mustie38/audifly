"""Hata raporlama yardımcıları: sürüm/ortam bilgisi ve log kuyruğu.

Çıktı kullanıcının kopyalayıp gönderebileceği düz metindir. Kişisel veri
sızdırmamak için ayarlar/token içermez; kullanıcı ana dizini "~" ile maskelenir.
"""
from __future__ import annotations

import glob
import os
import platform
import sys
from pathlib import Path

from mustiefly_qt.helpers import dependencies
from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME, APP_VERSION

LOG_TAIL_LINES = 60


def redact(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "~") if home and home not in ("/", "") else text


def _version_of(module: str) -> str:
    try:
        import importlib.metadata as md
        return md.version(module)
    except Exception:
        return "yok"


def _vlc_version() -> str:
    try:
        import vlc
        version = str(vlc.libvlc_get_version().decode("utf-8", "replace"))
    except Exception:
        return "yok"
    return f"{version} ({'paket içi' if os.environ.get('PYTHON_VLC_LIB_PATH') else 'sistem'})"


def _ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__ as version
    except Exception:
        return _version_of("yt-dlp")
    try:
        from mustiefly_qt.helpers import ytdlp_runtime
        if ytdlp_runtime.ACTIVE_VERSION:
            version += " (uygulama içi güncelleme)"
        pending = ytdlp_runtime.pending_version()
        if pending:
            version += f" · bekleyen: {pending}"
    except Exception:
        pass
    return version


def tail_of_latest_log(log_dir: str | None, lines: int = LOG_TAIL_LINES) -> str:
    if not log_dir:
        return ""
    files = sorted(glob.glob(os.path.join(log_dir, "*.log")), key=os.path.getmtime, reverse=True)
    if not files:
        return ""
    try:
        with open(files[0], "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def collect_diagnostics(log_dir: str | None = None, error_text: str = "",
                        user_note: str = "", recent_errors: list[str] | None = None) -> str:
    deps = ", ".join(f"{d.name}: {'var' if d.found else 'YOK'}" for d in dependencies.check_dependencies())
    parts = [
        f"{APP_DISPLAY_NAME} {APP_VERSION}",
        f"Sistem: {platform.platform()}  Python {sys.version.split()[0]}"
        f"{' (paketlenmiş)' if getattr(sys, 'frozen', False) else ''}",
        f"PySide6 {_version_of('PySide6')} · yt-dlp {_ytdlp_version()} · VLC {_vlc_version()}",
        f"Bileşenler: {deps}",
    ]
    if user_note.strip():
        parts += ["", "--- Kullanıcının açıklaması ---", user_note.strip()]
    if error_text:
        parts += ["", "--- Hata ---", error_text.strip()]
    if recent_errors:
        parts += ["", "--- Son hata mesajları ---", *[e.strip() for e in recent_errors[-15:]]]
    tail = tail_of_latest_log(log_dir)
    if tail:
        parts += ["", f"--- Son log satırları ({LOG_TAIL_LINES}) ---", tail.strip()]
    return redact("\n".join(parts))

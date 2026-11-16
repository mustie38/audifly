"""Harici bağımlılık denetimi (FFmpeg, Node.js), paket içi `bin/` ve gömülü libVLC desteği.

VLC zorunludur ve main.py'de ayrıca (engelleyici) denetlenir; kurulum paketi libVLC'yi
kendi içinde taşır (packaging/fetch_vlc.py → `vlc/`), sistemde VLC kurulu olması
gerekmez. FFmpeg ve Node.js
isteğe bağlı sayılır: eksikse uygulama açılır, ilgili özellik kısıtlanır ve
kullanıcıya NE işe yaradığı ile NASIL kurulacağı anlatılır.

Dağıtımcı `ffmpeg`/`ffprobe`/`node` ikililerini kurulum klasöründeki `bin/`
altına koyarsa (bkz. packaging/audifly.spec → packaging/bin) bunlar PATH'in
başına eklenir ve kullanıcının ayrıca bir şey kurması gerekmez.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Dependency:
    name: str
    found: bool
    purpose: str       # eksikse ne çalışmaz
    install_hint: str


def bundled_bin_dir() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "bin")


def prepend_bundled_bin_to_path(environ: dict | None = None) -> bool:
    """Pakete eklenmiş `bin/` varsa PATH'in başına koyar (zaten ekliyse tekrar etmez)."""
    environ = os.environ if environ is None else environ
    path = bundled_bin_dir()
    if not os.path.isdir(path):
        return False
    parts = environ.get("PATH", "").split(os.pathsep)
    if path not in parts:
        environ["PATH"] = os.pathsep.join([path, *parts]) if parts != [""] else path
    return True


_DLL_DIR_HANDLES: list = []   # os.add_dll_directory tutamacı canlı kalmalı


def bundled_vlc_dir() -> str | None:
    """Pakete gömülü libVLC klasörü (packaging/fetch_vlc.py üretir), yoksa None.

    Paketlenmiş uygulamada `_MEIPASS/vlc`, kaynaktan çalışırken `packaging/vlc`.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [os.path.join(meipass, "vlc")] if meipass else []
    candidates.append(os.path.join(package_root, "packaging", "vlc"))
    for path in candidates:
        if os.path.isfile(os.path.join(path, "libvlc.dll")) and os.path.isdir(os.path.join(path, "plugins")):
            return path
    return None


def configure_bundled_vlc(environ: dict | None = None) -> bool:
    """Gömülü libVLC varsa python-vlc'yi ona yönlendirir (`import vlc`'den ÖNCE çağrılmalı).

    Böylece kullanıcının ayrıca VLC Media Player kurması gerekmez. Kullanıcı
    PYTHON_VLC_LIB_PATH'i kendisi ayarladıysa ona dokunulmaz.
    """
    environ = os.environ if environ is None else environ
    if environ.get("PYTHON_VLC_LIB_PATH"):
        return False
    path = bundled_vlc_dir()
    if path is None:
        return False
    plugins = os.path.join(path, "plugins")
    lib = os.path.join(path, "libvlc.dll")
    core = os.path.join(path, "libvlccore.dll")
    parts = environ.get("PATH", "").split(os.pathsep)
    if path not in parts:
        environ["PATH"] = os.pathsep.join([path, *parts]) if parts != [""] else path
    if environ is os.environ:
        if hasattr(os, "add_dll_directory"):
            try:   # libvlccore.dll'nin libvlc.dll yanından bulunması için
                _DLL_DIR_HANDLES.append(os.add_dll_directory(path))
            except OSError:
                pass
        # python-vlc, PYTHON_VLC_LIB_PATH yüklenemezse sys.exit(1) çağırıyor (sessiz
        # kapanma). Önce libvlccore + libvlc'yi burada deniyoruz; olmazsa sistemdeki VLC'ye düşülür.
        try:
            import ctypes
            if os.path.isfile(core):
                ctypes.CDLL(core)
            ctypes.CDLL(lib)
        except OSError:
            return False
    environ["PYTHON_VLC_LIB_PATH"] = lib
    environ["PYTHON_VLC_MODULE_PATH"] = plugins
    environ["VLC_PLUGIN_PATH"] = plugins
    return True


def check_dependencies(which=shutil.which) -> list[Dependency]:
    """İsteğe bağlı bağımlılıkların durumu (VLC burada değil)."""
    return [
        Dependency("FFmpeg", bool(which("ffmpeg")) and bool(which("ffprobe")),
                   "Şarkı indirme (çevrimdışı dinleme) çalışmaz.",
                   "https://ffmpeg.org/download.html adresinden FFmpeg'i kurup PATH'e ekle "
                   "(Windows: `winget install Gyan.FFmpeg`)."),
        Dependency("Node.js", bool(which("node")),
                   "Bazı YouTube şarkıları çözümlenemeyip atlanabilir.",
                   "https://nodejs.org adresinden Node.js (LTS) kur "
                   "(Windows: `winget install OpenJS.NodeJS.LTS`)."),
    ]


def missing_message(deps: list[Dependency]) -> str:
    missing = [d for d in deps if not d.found]
    if not missing:
        return ""
    lines = ["Bazı bileşenler bulunamadı. Uygulama açıldı, ancak şu özellikler kısıtlı:\n"]
    for d in missing:
        lines.append(f"• {d.name}: {d.purpose}\n  Çözüm: {d.install_hint}")
    lines.append("\nKurduktan sonra uygulamayı yeniden başlat.")
    return "\n".join(lines)

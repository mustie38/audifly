"""Harici bağımlılık denetimi (FFmpeg, Node.js) ve paket içi `bin/` klasörü desteği.

VLC zorunludur ve main.py'de ayrıca (engelleyici) denetlenir. FFmpeg ve Node.js
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

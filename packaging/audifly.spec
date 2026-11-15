# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec dosyası — son kullanıcıya tek dosyalık bir .exe dağıtmak için.
#
# ÖNEMLİ: Bu dosyayı mustiefly_qt/ paket klasörünün BİR ÜST dizininden çalıştır
# (yani mustiefly_qt/ klasörünün kendisi değil, onu içeren klasörden), çünkü
# main.py kendini "mustiefly_qt.main" paketi olarak import ediyor:
#
#   cd ..   (mustiefly_qt/'nin bulunduğu klasöre geç)
#   pyinstaller mustiefly_qt/packaging/audifly.spec
#
# Çıktı: dist/Audifly/Audifly.exe (Windows) ya da dist/Audifly/Audifly (Linux/Mac)
#
# NOT: PyInstaller VLC'yi paketlemez — kullanıcının makinesinde ayrı olarak
# VLC Media Player kurulu olması hâlâ gerekir (bkz. main.py:_check_vlc_available).

import importlib.util
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
PACKAGE_ROOT = Path(SPECPATH).parent
PROJECT_PARENT = PACKAGE_ROOT.parent
ICON = PACKAGE_ROOT / "packaging" / "audifly.ico"   # üretmek için: python mustiefly_qt/packaging/make_icon.py
VERSION = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

# İsteğe bağlı: ffmpeg/ffprobe/node ikililerini packaging/bin/ altına koyarsan kurulumla
# birlikte gelir ve kullanıcı ayrıca kurmak zorunda kalmaz (lisansları dağıtımda ayrıca kontrol et:
# FFmpeg LGPL/GPL, Node.js MIT). helpers/dependencies.py bu klasörü PATH'e ekler.
BIN_DIR = PACKAGE_ROOT / "packaging" / "bin"

# İsteğe bağlı bağımlılıklar: yalnızca derleme ortamında kuruluysa pakete girer;
# yoksa ilgili özellik (Discord, Keşfet, medya tuşları/SMTC) çalışma anında sessizce kapanır.
OPTIONAL_IMPORTS = [m for m in (
    "ytmusicapi", "pypresence", "keyring", "keyring.backends.Windows", "winsdk",
    "winrt.windows.media", "winrt.windows.media.interop",
    "winrt.windows.foundation", "winrt.windows.storage.streams",
) if importlib.util.find_spec(m.split(".")[0])]

# Windows "Ayrıntılar" sekmesi için sürüm kaynağı (derleme sırasında üretilir)
_v = (VERSION.split(".") + ["0", "0", "0"])[:3]
_tuple = ", ".join(_v + ["0"])
VERSION_FILE = PROJECT_PARENT / "build" / "audifly_version_info.txt"
VERSION_FILE.parent.mkdir(exist_ok=True)
VERSION_FILE.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({_tuple}), prodvers=({_tuple}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Audifly'),
      StringStruct('FileDescription', 'Audifly Müzik Çalar'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'Audifly'),
      StringStruct('OriginalFilename', 'Audifly.exe'),
      StringStruct('ProductName', 'Audifly'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""", encoding="utf-8")

a = Analysis(
    [str(PACKAGE_ROOT / "main.py")],
    pathex=[str(PROJECT_PARENT)],
    binaries=[],
    datas=(collect_data_files("ytmusicapi") if importlib.util.find_spec("ytmusicapi") else [])
          + ([(str(BIN_DIR), "bin")] if BIN_DIR.is_dir() else []),
    hiddenimports=[
        "yt_dlp",
        "vlc",
        "PIL",
        "PySide6.QtNetwork",
        "PySide6.QtWebSockets",
        *OPTIONAL_IMPORTS,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Audifly",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # pencereli mod: hatalar artık log dosyasına düşüyor (bkz. helpers/logging_setup.py)
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.is_file() else None,
    version=str(VERSION_FILE),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Audifly",
)

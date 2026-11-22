"""Windows yerleşik C# derleyicisi (csc.exe) ile Audifly yerel (native) yardımcılarını derler.

Harici SDK / NuGet / Visual Studio gerektirmez — her Windows 10/11 bilgisayarında
hazır gelen .NET Framework 4.x `csc.exe` ile ~1 saniyede derlenir.

Kullanım:
    python packaging/build_native.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SRC_CS = PACKAGE_ROOT / "native" / "wasapi_spectrum" / "WasapiSpectrum.cs"
OUT_DIR = PACKAGE_ROOT / "packaging" / "bin"
OUT_EXE = OUT_DIR / "WasapiSpectrum.exe"


def find_csc() -> Path | None:
    """Windows yerleşik 64-bit (veya 32-bit) .NET 4.x csc.exe yolunu bulur."""
    win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        win_dir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        win_dir / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def build_wasapi_spectrum() -> Path:
    if sys.platform != "win32":
        print("[build_native] Windows dışı platform — WasapiSpectrum.exe atlanıyor.")
        return OUT_EXE

    csc = find_csc()
    if csc is None:
        raise RuntimeError("Windows yerleşik C# derleyicisi (csc.exe) bulunamadı.")
    if not SRC_CS.is_file():
        raise FileNotFoundError(f"Kaynak dosya bulunamadı: {SRC_CS}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(csc),
        "/nologo",
        "/optimize+",
        "/target:exe",
        "/platform:anycpu",
        f"/out:{OUT_EXE}",
        str(SRC_CS),
    ]
    print(f"[build_native] Derleniyor: {SRC_CS.name} -> {OUT_EXE}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"C# derleme hatası:\n{res.stdout}\n{res.stderr}")

    # Kendi yerleşik FFT öz-testini çalıştır
    test_res = subprocess.run([str(OUT_EXE), "--self-test"], capture_output=True, text=True, timeout=10)
    if test_res.returncode != 0 or "SELF_TEST_OK" not in test_res.stdout:
        raise RuntimeError(f"WasapiSpectrum self-test başarısız:\n{test_res.stdout}\n{test_res.stderr}")

    print(f"[build_native] Başarılı ({OUT_EXE.stat().st_size:,} bayt): {test_res.stdout.strip()}")
    return OUT_EXE


if __name__ == "__main__":
    build_wasapi_spectrum()

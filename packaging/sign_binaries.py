"""Windows ikililerini (Audifly.exe, AudiflySetup.exe) Authenticode ile imzalar.

Neden: İmzalanmamış .exe dosyalarında Windows SmartScreen "Tanınmayan yayıncı /
Windows kişisel bilgisayarınızı korudu" uyarısı çıkarır.

Nasıl çalışır:
  * Ortamda `WINDOWS_PFX_BASE64` (base64 kodlu .pfx/.p12 sertifikası) ya da
    `WINDOWS_PFX_PATH` tanımlıysa Windows SDK `signtool.exe` ile SHA-256 + RFC3161
    zaman damgalı imza atar (`WINDOWS_PFX_PASSWORD` parola için kullanılır).
  * Sertifika tanımlı değilse CI derlemesini kırmamak için bilgi mesajı yazıp 0 ile
    çıkar (`--require` verilirse hata döndürür).

Kullanım:
  python packaging/sign_binaries.py dist/Audifly/Audifly.exe
  python packaging/sign_binaries.py packaging/Output/AudiflySetup.exe
"""
from __future__ import annotations

import argparse
import base64
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMESTAMP_URL = "http://timestamp.digicert.com"


def find_signtool(which=shutil.which) -> str | None:
    direct = which("signtool") or which("signtool.exe")
    if direct:
        return direct
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    candidates = sorted(glob.glob(str(kits / "*" / "x64" / "signtool.exe")), reverse=True)
    return candidates[0] if candidates else None


def build_sign_command(signtool: str, pfx_path: str, password: str, target: str,
                       timestamp_url: str = TIMESTAMP_URL) -> list[str]:
    cmd = [signtool, "sign", "/fd", "sha256", "/td", "sha256", "/tr", timestamp_url, "/f", pfx_path]
    if password:
        cmd += ["/p", password]
    cmd.append(target)
    return cmd


def sign_files(files: list[Path], environ=None, require: bool = False, run=subprocess.run,
               which=shutil.which) -> int:
    environ = os.environ if environ is None else environ
    pfx_b64 = (environ.get("WINDOWS_PFX_BASE64") or "").strip()
    pfx_path = (environ.get("WINDOWS_PFX_PATH") or "").strip()
    password = environ.get("WINDOWS_PFX_PASSWORD") or ""
    timestamp_url = environ.get("WINDOWS_TIMESTAMP_URL") or TIMESTAMP_URL

    if not pfx_b64 and not pfx_path:
        msg = "BILGI: Kod imzalama sertifikasi tanimli degil (WINDOWS_PFX_BASE64 yok); imzalama atlandi."
        print(msg)
        return 1 if require else 0

    signtool = find_signtool(which=which)
    if not signtool:
        print("HATA: signtool.exe bulunamadi (Windows SDK kurulu olmali).", file=sys.stderr)
        return 1

    missing = [str(f) for f in files if not Path(f).is_file()]
    if missing:
        print(f"HATA: Imzalanacak dosya bulunamadi: {', '.join(missing)}", file=sys.stderr)
        return 1

    tmp_file = None
    try:
        if pfx_b64:
            raw = base64.b64decode(pfx_b64)
            fd, tmp_file = tempfile.mkstemp(suffix=".pfx")
            os.close(fd)
            Path(tmp_file).write_bytes(raw)
            pfx_path = tmp_file

        for target in files:
            cmd = build_sign_command(signtool, pfx_path, password, str(target), timestamp_url)
            proc = run(cmd, capture_output=True, text=True, timeout=180)
            if proc.returncode != 0:
                # Parolayı asla çıktıya yazma
                err = (proc.stderr or proc.stdout or "").replace(password, "***") if password else (proc.stderr or proc.stdout or "")
                print(f"HATA: signtool basarisiz ({target}): {err.strip()}", file=sys.stderr)
                return proc.returncode
            print(f"Imzalandi: {target}")
        return 0
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Windows .exe dosyalarini Authenticode ile imzalar.")
    parser.add_argument("files", nargs="+", help="Imzalanacak .exe dosyalari")
    parser.add_argument("--require", action="store_true",
                        help="Sertifika tanimli degilse hata kodu ile cik")
    args = parser.parse_args(argv)
    return sign_files([Path(f) for f in args.files], require=args.require)


if __name__ == "__main__":
    sys.exit(main())

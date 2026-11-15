"""Windows paketine Node.js (node.exe) ekler.

Neden: yt-dlp, YouTube'un JavaScript korumasini (n challenge) cozmek icin bir JS calisma
zamanina ihtiyac duyar. Kullaniciya ayrica Node.js kurdurmamak icin derleme sirasinda
packaging/bin/ altina node.exe konur; PyInstaller spec'i bu klasoru paketler,
helpers/dependencies.py de calisirken PATH'e ekler.

Kullanim (CI ve elle):  python packaging/fetch_node.py [--dest packaging/bin] [--version v22.11.0]

NOT: Cikti mesajlari bilerek ASCII; Windows konsolu (cp1252) Turkce karakter yazamaz.
Guvenlik: indirilen zip, nodejs.org'un ayni surum icin yayinladigi SHASUMS256.txt ile
SHA-256 dogrulanir; uyusmazsa hicbir dosya yazilmaz.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

DIST = "https://nodejs.org/dist"
MIN_MAJOR = 20                      # yt-dlp'nin istedigi en dusuk Node surumu
PLATFORM = "win-x64"


def pick_lts(index: list[dict], min_major: int = MIN_MAJOR) -> str:
    """index.json (yeniden eskiye) icinden Windows x64 zip'i olan ilk LTS surumu."""
    for entry in index:
        version = str(entry.get("version", ""))
        match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
        if not match or not entry.get("lts"):
            continue
        if int(match.group(1)) < min_major:
            continue
        if f"{PLATFORM}-zip" in (entry.get("files") or []):
            return version
    raise RuntimeError("Uygun bir Node.js LTS surumu bulunamadi")


def parse_shasums(text: str) -> dict[str, str]:
    """SHASUMS256.txt: '<64 hex>  <dosya adi>' satirlari."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


def fetch(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Audifly-build"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:   # noqa: S310 (sabit https adresi)
        return resp.read()


def install_node(dest: Path, version: str | None = None, get=None) -> tuple[str, Path]:
    """node.exe ve LICENSE'i dest altina yazar. (surum, node.exe yolu) doner."""
    if get is None:
        get = fetch              # cagri aninda cozulur (varsayilan arguman olsaydi testler taklit edemezdi)
    if version is None:
        version = pick_lts(json.loads(get(f"{DIST}/index.json").decode("utf-8")))
    name = f"node-{version}-{PLATFORM}.zip"
    expected = parse_shasums(get(f"{DIST}/{version}/SHASUMS256.txt").decode("utf-8")).get(name)
    if not expected:
        raise RuntimeError(f"{name} icin SHA-256 ozeti bulunamadi")
    data = get(f"{DIST}/{version}/{name}")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise RuntimeError(f"SHA-256 uyusmuyor ({name}): beklenen {expected}, gelen {actual}")
    root = f"node-{version}-{PLATFORM}/"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        node_bytes = zf.read(root + "node.exe")
        license_bytes = zf.read(root + "LICENSE") if root + "LICENSE" in zf.namelist() else b""
    dest.mkdir(parents=True, exist_ok=True)
    node_path = dest / "node.exe"
    node_path.write_bytes(node_bytes)
    if license_bytes:
        (dest / "LICENSE-node.txt").write_bytes(license_bytes)
    return version, node_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Paket icin node.exe indirir (SHA-256 dogrulamali).")
    parser.add_argument("--dest", default=str(Path(__file__).resolve().parent / "bin"))
    parser.add_argument("--version", default=None, help="ornek: v22.11.0 (bos: guncel LTS)")
    args = parser.parse_args(argv)
    try:
        version, path = install_node(Path(args.dest), args.version)
    except Exception as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    print(f"Node.js {version} -> {path} ({path.stat().st_size // (1024 * 1024)} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Windows paketine VLC'nin çalışma zamanı dosyalarını (libvlc + eklentiler) ekler.

Neden: Audifly sesi libVLC ile çalar. Eskiden kullanıcının ayrıca VLC Media Player
kurması gerekiyordu; teknik olmayan kullanıcı için büyük bir engeldi. libVLC LGPL-2.1+
lisanslıdır ve uygulamayla birlikte (değiştirilmeden, ayrı DLL'ler olarak) dağıtılabilir.

Ne yapar: videolan.org'dan resmi win64 zip'ini indirir, aynı adresteki .sha256 ile
doğrular, yalnızca gereken dosyaları packaging/vlc/ altına çıkarır:
    libvlc.dll, libvlccore.dll, plugins/ (video/arayüz eklentileri hariç), COPYING.txt
Sonra (varsa) vlc-cache-gen.exe ile eklenti önbelleğini üretir (açılışı hızlandırır).
helpers/dependencies.py:configure_bundled_vlc() çalışırken bu klasörü kullanır.

Kullanım (CI ve elle):  python packaging/fetch_vlc.py [--dest packaging/vlc] [--version 3.0.24]

NOT: Çıktı mesajları bilerek ASCII; Windows konsolu (cp1252) Türkçe karakter yazamaz.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_VERSION = "3.0.24"
BASE = "https://download.videolan.org/pub/videolan/vlc"

# Yalnız ses çalan bir uygulama için gereksiz (ve büyük) eklenti klasörleri.
# Ses çıkışı, codec, demux, erişim (http/https/file), ses filtreleri (normvol, ekolayzer) KALIR.
EXCLUDED_PLUGIN_DIRS = frozenset({
    "gui", "video_output", "video_filter", "video_splitter", "visualization",
    "lua", "skins2", "spu", "control", "access_output", "stream_out",
    "text_renderer", "video_chroma", "services_discovery",
})
# Ses için her zaman eksiksiz korunacak eklenti klasörleri
ALWAYS_KEEP_PLUGIN_DIRS = frozenset({
    "audio_output", "audio_filter", "audio_mixer", "packetizer",
    "meta_engine", "keystore", "logger",
})
# Ses açısından gereksiz büyük tekil eklentiler (video kodlayıcı/çözücüler, uzak masaüstü,
# yayın protokolleri, altyazı). https (gnutls), avcodec (AAC/m4a), opus/vorbis KALIR.
EXCLUDED_PLUGIN_PATTERNS = (
    "x264", "x265", "vnc", "libass", "srt_plugin", "rist", "dcp_plugin", "dav1d", "aom",
    "vpx", "theora", "schroedinger", "kate", "zvbi", "telx", "libmpeg2", "qsv", "dxva",
    "d3d11va", "subsdec", "subsusf", "substx3g", "svcdsub", "cvdsub", "dvbsub", "scte",
    "ttml", "webvtt", "oldrc", "screen", "dshow", "vcd", "dvdnav", "dvdread", "bluray",
    "decklink", "librtp_", "libsap_", "libupnp_", "libmtp_", "libsmb_", "libnfs_",
    "libsftp_", "libftp_",
)
KEEP_TOP_FILES = ("libvlc.dll", "libvlccore.dll", "COPYING.txt", "AUTHORS.txt", "README.txt")


def fetch(url: str, timeout: int = 300) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Audifly-build"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:   # noqa: S310 (sabit https adresi)
        return resp.read()


def parse_sha256(text: str) -> str:
    match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    if not match:
        raise RuntimeError("SHA-256 dosyasi okunamadi")
    return match.group(1).lower()


def _wanted(rel: str) -> bool:
    """Zip içi göreli yol (kök klasör çıkarılmış) pakete girsin mi?"""
    if rel in KEEP_TOP_FILES:
        return True
    parts = rel.split("/")
    if parts[0] != "plugins" or len(parts) < 2:
        return False
    if len(parts) >= 3 and parts[1] in EXCLUDED_PLUGIN_DIRS:
        return False
    if len(parts) >= 3 and parts[1] in ALWAYS_KEEP_PLUGIN_DIRS:
        return True
    if any(pattern in parts[-1].lower() for pattern in EXCLUDED_PLUGIN_PATTERNS):
        return False
    return True


def extract_runtime(data: bytes, dest: Path) -> int:
    """Gerekli dosyaları dest'e yazar; yazılan dosya sayısını döndürür."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    count = 0
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            name = member.filename
            if member.is_dir() or "/" not in name:
                continue
            rel = name.split("/", 1)[1]
            if not rel or not _wanted(rel):
                continue
            target = (dest / rel).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise RuntimeError(f"Guvensiz arsiv yolu: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
        # Eklenti önbelleği üretici (pakete girmez, yalnız derlemede çalıştırılır)
        gen = next((m for m in zf.namelist() if m.endswith("/vlc-cache-gen.exe")), None)
        if gen and sys.platform == "win32":
            with tempfile.TemporaryDirectory() as tmp:
                exe = Path(tmp) / "vlc-cache-gen.exe"
                exe.write_bytes(zf.read(gen))
                for dll in ("libvlc.dll", "libvlccore.dll"):
                    shutil.copy2(dest / dll, Path(tmp) / dll)
                try:
                    subprocess.run([str(exe), str(dest / "plugins")], check=False, timeout=120,
                                   capture_output=True)
                except Exception as e:   # önbellek yalnızca hız kazandırır; zorunlu değil
                    print(f"UYARI: vlc-cache-gen calistirilamadi: {e}")
    required = [dest / "libvlc.dll", dest / "libvlccore.dll", dest / "plugins"]
    missing = [str(p.name) for p in required if not p.exists()]
    if missing:
        raise RuntimeError(f"VLC arsivinde eksik: {', '.join(missing)}")
    return count


def install_vlc(dest: Path, version: str = DEFAULT_VERSION, get=None) -> tuple[str, int]:
    if get is None:
        get = fetch
    if not re.fullmatch(r"\d+\.\d+\.\d+(\.\d+)?", version):
        raise ValueError(f"Gecersiz VLC surumu: {version}")
    name = f"vlc-{version}-win64.zip"
    url = f"{BASE}/{version}/win64/{name}"
    expected = parse_sha256(get(url + ".sha256").decode("ascii", "replace"))
    data = get(url)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise RuntimeError(f"SHA-256 uyusmuyor ({name}): beklenen {expected}, gelen {actual}")
    return version, extract_runtime(data, dest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Paket icin libVLC indirir (SHA-256 dogrulamali).")
    parser.add_argument("--dest", default=str(Path(__file__).resolve().parent / "vlc"))
    parser.add_argument("--version", default=DEFAULT_VERSION)
    args = parser.parse_args(argv)
    try:
        version, count = install_vlc(Path(args.dest), args.version)
    except Exception as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    size = sum(p.stat().st_size for p in Path(args.dest).rglob("*") if p.is_file())
    print(f"VLC {version} -> {args.dest} ({count} dosya, {size // (1024 * 1024)} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

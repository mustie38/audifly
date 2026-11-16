"""yt-dlp'yi uygulama içinden (yeni kurulum yayınlamadan) güncelleme.

Sorun: Paketlenmiş (.exe) uygulamada yt-dlp, PyInstaller arşivinin içinde donmuş
durumdadır; pip ile güncellenemez. YouTube bir şeyi değiştirince çalma durur ve tek
çare yeni bir Audifly kurulumu yayınlamaktı.

Çözüm: yt-dlp ve yt-dlp-ejs saf Python paketleridir (py3-none-any wheel). Güncelleme
PyPI'den wheel olarak indirilir, SHA-256 doğrulanır ve kullanıcının veri klasörüne
(``%LOCALAPPDATA%\\Audifly\\components\\yt-dlp\\<sürüm>``) açılır. Uygulama açılırken
:func:`activate` bu klasörü, ``yt_dlp`` HİÇ import edilmeden önce, ``sys.meta_path``'in
en başına konan küçük bir bulucu (finder) ile devreye alır; böylece paket içindeki
eski sürüm yerine indirilen yeni sürüm yüklenir.

Güvenlik ağı:
  * İndirme yalnız https://pypi.org'dan, PyPI'nin bildirdiği SHA-256 ile doğrulanarak yapılır.
  * Yeni sürüm import edilemezse otomatik olarak paketteki sürüme dönülür ve
    bozuk sürüm "bad" işaretlenir (bir daha denenmez).
  * Paketteki sürüm indirilenden yeniyse (uygulama güncellendiyse) indirilen yok sayılır.
  * Ayarlar'dan "Paketteki sürüme dön" ile her şey sıfırlanabilir.

ÖNEMLİ: Bu modül yalnızca standart kütüphaneyi import eder; ``main.py`` en başta,
``yt_dlp``'yi import eden hiçbir modülden önce çağırır.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import io
import json
import logging
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

MODULE_NAMES = ("yt_dlp", "yt_dlp_ejs")
PYPI = "https://pypi.org/pypi"
STATE_FILE = "active.json"
HTTP_TIMEOUT = 30

# Bu oturumda gerçekten devreye giren sürüm (None: paketteki/kurulu sürüm kullanılıyor)
ACTIVE_VERSION: str | None = None
_FINDER: "_OverrideFinder | None" = None


# ----------------------------------------------------------------------------
# Yollar / durum dosyası
# ----------------------------------------------------------------------------
def components_dir(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get("AUDIFLY_COMPONENTS_DIR")
    if override:
        return Path(override) / "yt-dlp"
    from mustiefly_qt.helpers.data_paths import _user_data_dir   # yalnız stdlib kullanır
    return _user_data_dir(environ, sys.platform, Path.home()) / "components" / "yt-dlp"


def read_state(root: Path) -> dict:
    try:
        data = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, root / STATE_FILE)


def version_key(version: str | None) -> tuple:
    """'2026.10.26' / '2026.10.26.1' / '0.8.0' → karşılaştırılabilir tuple."""
    return tuple(int(p) for p in re.findall(r"\d+", version or ""))


def bundled_version() -> str | None:
    """Paketle gelen (ya da pip ile kurulu) yt-dlp sürümü — yt_dlp import EDİLMEDEN."""
    try:
        import importlib.metadata as md
        return md.version("yt-dlp")
    except Exception:
        return None


# ----------------------------------------------------------------------------
# Çalışma anında devreye alma
# ----------------------------------------------------------------------------
class _OverrideFinder(importlib.abc.MetaPathFinder):
    """yt_dlp* modüllerini yalnızca indirilen klasörden yükler.

    Alt modüller (``yt_dlp.extractor.youtube`` gibi) de buradan çözülür; aksi halde
    PyInstaller'ın kendi bulucusu paketteki ESKİ alt modülü getirip iki sürümü
    karıştırabilirdi.
    """

    def __init__(self, root: str):
        self.root = root

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in MODULE_NAMES:
            return None
        search = [self.root] if "." not in fullname else path
        return importlib.machinery.PathFinder.find_spec(fullname, search)


def _purge_modules() -> None:
    for name in list(sys.modules):
        if name.partition(".")[0] in MODULE_NAMES:
            sys.modules.pop(name, None)


def _remove_finder() -> None:
    global _FINDER
    if _FINDER is not None:
        try:
            sys.meta_path.remove(_FINDER)
        except ValueError:
            pass
    _FINDER = None


def _cleanup_old(root: Path, keep: str | None) -> None:
    """Kullanılmayan eski sürüm klasörlerini ve yarım kalmış indirmeleri siler."""
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name != keep:
                shutil.rmtree(child, ignore_errors=True)
    except OSError:
        pass


def activate(environ=None) -> str | None:
    """İndirilmiş yt-dlp varsa devreye alır. Devreye giren sürümü döndürür.

    ``yt_dlp`` import edilmeden ÖNCE çağrılmalıdır; zaten import edilmişse hiçbir
    şey yapmaz (yarım yamalak bir takas iki sürümü karıştırırdı).
    """
    global ACTIVE_VERSION, _FINDER
    if any(name.partition(".")[0] in MODULE_NAMES for name in sys.modules):
        log.warning("yt-dlp zaten yüklenmiş; indirilen sürüm bu oturumda devreye alınamadı.")
        return None
    try:
        root = components_dir(environ)
    except Exception:
        return None
    state = read_state(root)
    folder = state.get("dir")
    version = (state.get("versions") or {}).get("yt-dlp")
    if not folder or not version or state.get("bad"):
        return None
    active = root / folder
    if not (active / "yt_dlp" / "__init__.py").is_file():
        return None
    bundled = bundled_version()
    if bundled and version_key(bundled) >= version_key(version):
        # Uygulama güncellendi ve paketteki sürüm artık daha yeni: indirileni bırak.
        log.info("Paketteki yt-dlp (%s) indirilen sürümden (%s) yeni/aynı; indirilen kullanılmıyor.",
                 bundled, version)
        return None

    _FINDER = _OverrideFinder(str(active))
    sys.meta_path.insert(0, _FINDER)
    try:
        import yt_dlp  # noqa: F401
        from yt_dlp.version import __version__ as loaded
        if not str(Path(yt_dlp.__file__).resolve()).startswith(str(active.resolve())):
            raise ImportError(f"yt_dlp yanlış konumdan yüklendi: {yt_dlp.__file__}")
    except Exception as e:   # bozuk/eksik indirme: paketteki sürüme sessizce dön
        log.error("İndirilen yt-dlp %s yüklenemedi, paketteki sürüme dönülüyor: %s", version, e)
        _remove_finder()
        _purge_modules()
        state["bad"] = True
        state["error"] = str(e)[:500]
        try:
            write_state(root, state)
        except OSError:
            pass
        return None
    ACTIVE_VERSION = loaded
    log.info("Güncellenmiş yt-dlp %s kullanılıyor (%s).", loaded, active)
    _cleanup_old(root, keep=folder)
    return loaded


def reset_to_bundled(environ=None) -> bool:
    """İndirilen sürümü kaldırır; bir sonraki açılışta paketteki sürüm kullanılır."""
    try:
        root = components_dir(environ)
        state = read_state(root)
        state.update({"dir": None, "versions": {}, "bad": False})
        write_state(root, state)
        return True
    except OSError as e:
        log.error("yt-dlp sıfırlanamadı: %s", e)
        return False


def pending_version(environ=None) -> str | None:
    """İndirilmiş ama bu oturumda henüz devrede olmayan sürüm (yeniden başlatma gerekir)."""
    try:
        state = read_state(components_dir(environ))
    except Exception:
        return None
    version = (state.get("versions") or {}).get("yt-dlp")
    if not version or state.get("bad") or version == ACTIVE_VERSION:
        return None
    return version


# ----------------------------------------------------------------------------
# İndirme / kurulum
# ----------------------------------------------------------------------------
def _fetch(url: str, timeout: int = HTTP_TIMEOUT) -> bytes:
    if not url.startswith(("https://pypi.org/", "https://files.pythonhosted.org/")):
        raise ValueError(f"Beklenmeyen indirme adresi: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "Audifly"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:   # noqa: S310 (adres yukarıda denetlendi)
        return resp.read()


def _pypi_json(package: str, version: str | None = None, get=None) -> dict:
    get = get or _fetch
    url = f"{PYPI}/{package}/{version}/json" if version else f"{PYPI}/{package}/json"
    return json.loads(get(url).decode("utf-8"))


def _pick_wheel(release: dict) -> dict:
    for entry in release.get("urls") or []:
        name = entry.get("filename", "")
        if entry.get("packagetype") == "bdist_wheel" and name.endswith("-none-any.whl"):
            if entry.get("yanked"):
                continue
            return entry
    raise RuntimeError(f"{release.get('info', {}).get('name')}: saf Python wheel bulunamadı")


def _python_supported(requires_python: str | None) -> bool:
    if not requires_python:
        return True
    try:
        from packaging.specifiers import SpecifierSet
        return SpecifierSet(requires_python).contains(
            ".".join(map(str, sys.version_info[:3])), prereleases=True)
    except Exception:
        return True   # yorumlanamadıysa engelleme; import denetimi yine güvence


def _pinned_ejs_version(info: dict) -> str | None:
    """yt-dlp, uyumlu yt-dlp-ejs sürümünü 'default' ekstrasında sabitler (==X.Y.Z)."""
    for req in info.get("requires_dist") or []:
        match = re.match(r"\s*yt-dlp-ejs\s*==\s*([0-9][0-9A-Za-z.\-]*)", req)
        if match:
            return match.group(1)
    return None


def _safe_extract(data: bytes, dest: Path) -> None:
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            top = member.filename.split("/", 1)[0]
            if top not in MODULE_NAMES and not top.endswith(".dist-info"):
                continue
            target = (dest / member.filename).resolve()
            if not str(target).startswith(str(dest_resolved) + os.sep):
                raise RuntimeError(f"Güvensiz arşiv yolu: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def _download_verified(entry: dict, get) -> bytes:
    expected = (entry.get("digests") or {}).get("sha256")
    if not expected:
        raise RuntimeError(f"{entry.get('filename')}: SHA-256 özeti yok")
    data = get(entry["url"])
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise RuntimeError(f"{entry.get('filename')}: SHA-256 uyuşmuyor")
    return data


def latest_version(get=None) -> str | None:
    try:
        return _pypi_json("yt-dlp", get=get).get("info", {}).get("version")
    except Exception:
        return None


def install_latest(environ=None, get=None) -> tuple[bool, str, str | None]:
    """PyPI'deki son yt-dlp (+ uyumlu yt-dlp-ejs) sürümünü indirip etkinleştirir.

    Dönüş: (başarılı, kullanıcıya mesaj, kurulan_sürüm). Değişiklik bir sonraki
    açılışta devreye girer.
    """
    get = get or _fetch
    try:
        root = components_dir(environ)
        release = _pypi_json("yt-dlp", get=get)
        info = release.get("info") or {}
        version = info.get("version")
        if not version:
            raise RuntimeError("PyPI sürüm bilgisi okunamadı")
        if not _python_supported(info.get("requires_python")):
            return False, (f"yt-dlp {version} bu uygulamanın Python sürümünü desteklemiyor; "
                           "yeni bir Audifly sürümü gerekiyor."), None
        state = read_state(root)
        if (state.get("versions") or {}).get("yt-dlp") == version and not state.get("bad") \
                and (root / str(state.get("dir")) / "yt_dlp" / "__init__.py").is_file():
            return True, f"yt-dlp {version} zaten indirildi.", version

        ejs_version = _pinned_ejs_version(info)
        ejs_release = _pypi_json("yt-dlp-ejs", ejs_version, get=get)
        wheels = [(release, _pick_wheel(release)), (ejs_release, _pick_wheel(ejs_release))]

        staging = root / f".staging-{int(time.time())}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            for _rel, entry in wheels:
                _safe_extract(_download_verified(entry, get), staging)
            version_file = staging / "yt_dlp" / "version.py"
            match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", version_file.read_text(encoding="utf-8"))
            if not match:
                raise RuntimeError("İndirilen yt-dlp'de sürüm bilgisi yok")
            folder = f"yt-dlp-{match.group(1)}"
            final = root / folder
            shutil.rmtree(final, ignore_errors=True)
            os.replace(staging, final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        ejs_installed = (ejs_release.get("info") or {}).get("version")
        write_state(root, {"dir": folder, "bad": False, "installed_at": int(time.time()),
                           "versions": {"yt-dlp": match.group(1), "yt-dlp-ejs": ejs_installed}})
        return True, (f"yt-dlp {match.group(1)} indirildi. Uygulamayı yeniden başlatınca "
                      "devreye girer."), match.group(1)
    except Exception as e:
        log.error("yt-dlp güncellemesi indirilemedi: %s", e)
        return False, f"yt-dlp güncellemesi indirilemedi: {e}", None

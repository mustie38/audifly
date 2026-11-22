"""C# Native WASAPI Loopback + FFT Gerçek Zamanlı Ses Spektrumu Köprüsü.

Windows üzerinde `WasapiSpectrum.exe` (C# / .NET Core Audio WASAPI Loopback +
1024 noktalı Cooley-Tukey Radix-2 FFT) yardımcısını arka planda (penceresiz)
çalıştırarak hoparlör/kulaklık çıkışından gerçek zamanlı 32 bantlı frekans
spektrumu alır.

Özellikler:
- Referans sayımlı yaşam döngüsü (`acquire` / `release`): Yalnızca bir
  görselleştirici görünür ve şarkı çalarken süreç çalışır; duraklatılınca
  veya gizlenince kapanır (%0 boşta CPU).
- Otomatik yeniden örnekleme (`resample_bands`): 32 yerel FFT bandını herhangi
  bir bar sayısına (16, 24, 32, 40...) yumuşak doğrusal interpolasyonla eşler.
- Windows dışı platformlarda veya `WasapiSpectrum.exe` yoksa sessizce `None`
  döndürür; görselleştirici otomatik simülasyon moduna geçer.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from mustiefly_qt.helpers.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_NATIVE_BANDS = 32
DEFAULT_NATIVE_FPS = 30
CREATE_NO_WINDOW = 0x08000000


def find_helper_exe() -> Path | None:
    """Derlenmiş `WasapiSpectrum.exe` ikilisinin yolunu arar."""
    if sys.platform != "win32":
        return None

    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "bin" / "WasapiSpectrum.exe")
        candidates.append(Path(meipass) / "WasapiSpectrum.exe")

    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "bin" / "WasapiSpectrum.exe")
    candidates.append(exe_dir / "_internal" / "bin" / "WasapiSpectrum.exe")

    pkg_root = Path(__file__).resolve().parent.parent
    candidates.append(pkg_root / "packaging" / "bin" / "WasapiSpectrum.exe")
    candidates.append(pkg_root / "native" / "wasapi_spectrum" / "WasapiSpectrum.exe")

    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def parse_band_line(line: str) -> list[float] | None:
    """Virgülle ayrılmış normalize spektrum satırını float listesine çevirir."""
    if not line:
        return None
    parts = line.strip().split(",")
    if len(parts) < 4:
        return None
    out: list[float] = []
    try:
        for p in parts:
            v = float(p)
            if v < 0.0:
                v = 0.0
            elif v > 1.0:
                v = 1.0
            out.append(v)
    except ValueError:
        return None
    return out


def resample_bands(src: list[float], target_count: int) -> list[float]:
    """Kaynak bant listesini doğrusal interpolasyonla `target_count` boyutuna ölçekler."""
    if target_count <= 0:
        return []
    m = len(src)
    if m == 0:
        return [0.0] * target_count
    if m == target_count:
        return list(src)
    if m == 1:
        return [src[0]] * target_count

    out: list[float] = []
    scale = (m - 1) / max(1, target_count - 1)
    for i in range(target_count):
        pos = i * scale
        lo = int(pos)
        hi = min(m - 1, lo + 1)
        frac = pos - lo
        out.append(src[lo] * (1.0 - frac) + src[hi] * frac)
    return out


class NativeSpectrumService:
    """`WasapiSpectrum.exe` sürecini yöneten tekil (singleton) servis."""

    def __init__(self, bands: int = DEFAULT_NATIVE_BANDS, fps: int = DEFAULT_NATIVE_FPS):
        self._bands_cfg = bands
        self._fps_cfg = fps
        self._lock = threading.Lock()
        self._ref_count = 0
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._latest: list[float] | None = None
        self._latest_ts: float = 0.0
        self._failed_until: float = 0.0

    def is_available(self) -> bool:
        return find_helper_exe() is not None

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def acquire(self) -> bool:
        """Bir görselleştirici canlı veriye ihtiyaç duyduğunda çağırır."""
        with self._lock:
            self._ref_count += 1
            if self._proc is not None and self._proc.poll() is None:
                return True
            if time.monotonic() < self._failed_until:
                return False
            return self._start_locked()

    def release(self) -> None:
        """Görselleştirici durduğunda veya gizlendiğinde çağırır."""
        with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count == 0:
                self._stop_locked()

    def shutdown(self) -> None:
        """Uygulama kapanırken yardımcı süreci kesin olarak sonlandırır."""
        with self._lock:
            self._ref_count = 0
            self._stop_locked()

    def get_bands(self, bar_count: int, max_age: float = 0.45) -> list[float] | None:
        """Son canlı FFT bantlarını `bar_count` uzunluğunda döndürür; yoksa `None`."""
        with self._lock:
            raw = self._latest
            ts = self._latest_ts
        if raw is None or (time.monotonic() - ts) > max_age:
            return None
        return resample_bands(raw, bar_count)

    def _start_locked(self) -> bool:
        exe = find_helper_exe()
        if exe is None:
            return False
        try:
            creationflags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [str(exe), "--bands", str(self._bands_cfg), "--fps", str(self._fps_cfg)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as e:
            log.warning("WasapiSpectrum başlatılamadı: %s", e)
            self._failed_until = time.monotonic() + 15.0
            return False

        self._proc = proc
        self._thread = threading.Thread(
            target=self._reader_loop,
            args=(proc,),
            name="WasapiSpectrumReader",
            daemon=True,
        )
        self._thread.start()
        log.info("C# Native WASAPI spektrum başlatıldı: %s", exe.name)
        return True

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        self._latest = None
        self._latest_ts = 0.0
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=0.6)
        except Exception:
            try:
                proc.terminate()
            except OSError:
                pass

    def _reader_loop(self, proc: subprocess.Popen) -> None:
        stdout = proc.stdout
        if stdout is None:
            return
        try:
            for line in stdout:
                parsed = parse_band_line(line)
                if parsed is not None:
                    now = time.monotonic()
                    with self._lock:
                        if self._proc is proc:
                            self._latest = parsed
                            self._latest_ts = now
        except OSError:
            pass
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
                    if self._ref_count > 0:
                        # Beklenmedik kapanışta kısa bir bekleme koy
                        self._failed_until = time.monotonic() + 5.0


_singleton: NativeSpectrumService | None = None
_singleton_lock = threading.Lock()


def get_native_spectrum_service() -> NativeSpectrumService:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = NativeSpectrumService()
            atexit.register(_singleton.shutdown)
        return _singleton


def is_native_spectrum_available() -> bool:
    return get_native_spectrum_service().is_available()


def acquire_native_spectrum() -> bool:
    if os.environ.get("AUDIFLY_DISABLE_NATIVE_SPECTRUM") == "1":
        return False
    return get_native_spectrum_service().acquire()


def release_native_spectrum() -> None:
    if _singleton is not None:
        _singleton.release()


def get_live_spectrum_bands(bar_count: int) -> list[float] | None:
    if _singleton is None:
        return None
    return _singleton.get_bands(bar_count)

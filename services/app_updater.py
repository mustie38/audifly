"""Uygulama güncellemesi için Qt sarmalayıcısı: ağ işleri arka plan thread'inde,
sonuçlar sinyalle GUI thread'ine taşınır (UI asla bloklanmaz)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from mustiefly_qt.helpers import app_update
from mustiefly_qt.helpers.logging_setup import get_logger

log = get_logger(__name__)


class AppUpdater(QObject):
    # (durum: "available"|"up_to_date"|"no_release"|"error", ReleaseInfo | None, mesaj)
    checkFinished = Signal(str, object, str)
    progress = Signal(int)
    downloadFinished = Signal(str)       # doğrulanmış kurulum dosyası yolu
    downloadFailed = Signal(str)

    def __init__(self, parent=None, check_fn=None, download_fn=None):
        super().__init__(parent)
        self._check_fn = check_fn or app_update.check_for_update
        self._download_fn = download_fn or app_update.download_installer
        self._cancel = threading.Event()
        self._busy_check = False
        self._busy_download = False

    def check(self) -> bool:
        """Arka planda sürüm denetler. Zaten denetleniyorsa False."""
        if self._busy_check:
            return False
        self._busy_check = True

        def worker():
            try:
                status, info = self._check_fn()
                self.checkFinished.emit(status, info, "")
            except app_update.UpdateError as e:
                log.warning("Güncelleme denetimi başarısız: %s", e)
                self.checkFinished.emit("error", None, str(e))
            except Exception as e:      # beklenmeyen hata düğmeyi/akışı kilitlemesin
                log.error("Güncelleme denetimi hatası: %s", e)
                self.checkFinished.emit("error", None, f"Beklenmeyen hata: {e}")
            finally:
                self._busy_check = False

        threading.Thread(target=worker, daemon=True, name="audifly-update-check").start()
        return True

    def download(self, info) -> bool:
        if self._busy_download:
            return False
        self._busy_download = True
        self._cancel.clear()

        def worker():
            try:
                path = self._download_fn(info, progress=self.progress.emit,
                                         cancelled=self._cancel.is_set)
                self.downloadFinished.emit(path)
            except app_update.UpdateError as e:
                self.downloadFailed.emit(str(e))
            except Exception as e:
                log.error("Güncelleme indirme hatası: %s", e)
                self.downloadFailed.emit(f"Beklenmeyen hata: {e}")
            finally:
                self._busy_download = False

        threading.Thread(target=worker, daemon=True, name="audifly-update-download").start()
        return True

    def cancel(self):
        self._cancel.set()

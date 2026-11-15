"""
Global medya tuşları (play/pause / next / previous) — 'keyboard' paketiyle.

Paket kurulu değilse veya ayardan kapatılmışsa sessizce devre dışı kalır
(orijinal mustiefly_discord_tray._setup_global_media_keys davranışı).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
try:
    import keyboard as _keyboard_lib
    KEYBOARD_AVAILABLE = True
except Exception:
    _keyboard_lib = None
    KEYBOARD_AVAILABLE = False


class GlobalMediaKeys(QObject):
    # 'keyboard' kütüphanesi geri çağrıları KENDİ thread'inde çalıştırır. Oynatma
    # motoru (QTimer, sinyaller, VLC) yalnız GUI thread'inde güvenli olduğundan
    # tuşlar sinyalle GUI thread'ine aktarılır.
    _toggle = Signal()
    _next = Signal()
    _previous = Signal()

    def __init__(self, on_toggle, on_next, on_previous, parent=None):
        super().__init__(parent)
        self._hotkeys = []
        self._cb = (on_toggle, on_next, on_previous)
        # Alıcı olarak QObject'in kendi metodu kullanılır: düz lambda/callable
        # bağlansaydı çağrı yine yayan thread'de çalışabilirdi.
        self._toggle.connect(self._run_toggle)
        self._next.connect(self._run_next)
        self._previous.connect(self._run_previous)

    def _run_toggle(self):
        self._cb[0]()

    def _run_next(self):
        self._cb[1]()

    def _run_previous(self):
        self._cb[2]()

    def start(self):
        if not KEYBOARD_AVAILABLE:
            log.warning("Global medya tuşları devre dışı: 'keyboard' paketi kurulu değil.")
            return
        try:
            self._hotkeys = [
                _keyboard_lib.add_hotkey('play/pause media', self._toggle.emit),
                _keyboard_lib.add_hotkey('next track', self._next.emit),
                _keyboard_lib.add_hotkey('previous track', self._previous.emit),
            ]
        except Exception as e:
            # Bazı platformlarda yönetici izni gerekebilir — sorun değil.
            log.error("%s %s", "Global medya tuşları ayarlanamadı:", e)

    def stop(self):
        for hk in self._hotkeys:
            try:
                _keyboard_lib.remove_hotkey(hk)
            except Exception:
                pass
        self._hotkeys = []

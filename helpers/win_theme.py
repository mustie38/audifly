"""Windows 10/11 DWM karanlık başlık çubuğu yardımcısı."""
from __future__ import annotations

import sys


def is_dark_theme(theme_key: str | None) -> bool:
    """Açık (mono_light) tema dışındaki tüm temalar karanlıktır."""
    return (theme_key or "") != "mono_light"


def apply_dark_titlebar(widget, dark: bool = True) -> None:
    """Windows üzerinde pencere başlık çubuğunu karanlık moda geçirir.
    Diğer platformlarda veya headless ortamlarda sessizce çıkar.
    """
    if sys.platform != "win32" or widget is None:
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        if not hwnd:
            return
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        # 20: Windows 11 & Win 10 20H1+, 19: eski Win 10 derlemeleri
        for attr in (20, 19):
            res = dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
            if res == 0:
                break
    except Exception:
        pass

"""C# Native WASAPI Spektrum yardımcısı ve Python köprüsü testleri."""
from __future__ import annotations

import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from mustiefly_qt.services.native_spectrum import (
    NativeSpectrumService,
    find_helper_exe,
    parse_band_line,
    resample_bands,
)


def test_parse_band_line_valid_and_clamping():
    vals = parse_band_line("0.000,0.500,1.250,-0.300,0.842\n")
    assert vals == pytest.approx([0.0, 0.5, 1.0, 0.0, 0.842])


def test_parse_band_line_invalid():
    assert parse_band_line("") is None
    assert parse_band_line("0.1,0.2") is None
    assert parse_band_line("a,b,c,d,e") is None


def test_resample_bands_upsample_and_downsample():
    src = [0.0, 0.5, 1.0]
    up = resample_bands(src, 5)
    assert up == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    down = resample_bands([0.0, 0.25, 0.5, 0.75, 1.0], 3)
    assert down == pytest.approx([0.0, 0.5, 1.0])

    assert resample_bands(src, 3) == pytest.approx(src)
    assert resample_bands([], 4) == [0.0, 0.0, 0.0, 0.0]


def test_service_get_bands_staleness():
    svc = NativeSpectrumService()
    svc._latest = [0.2, 0.6, 0.8, 0.4]
    svc._latest_ts = time.monotonic()
    res = svc.get_bands(8, max_age=1.0)
    assert res is not None
    assert len(res) == 8
    assert res[0] == pytest.approx(0.2)
    assert res[-1] == pytest.approx(0.4)

    # Bayat veri -> None
    svc._latest_ts = time.monotonic() - 5.0
    assert svc.get_bands(8, max_age=0.5) is None


def test_visualizer_uses_live_native_bands_and_falls_back(qapp):
    from mustiefly_qt.widgets.audio_visualizer import NeonAudioVisualizer

    viz = NeonAudioVisualizer(bar_count=16, interactive=False)
    viz._playing = True
    viz._use_native_audio = True

    live = [0.90] * 16
    with patch("mustiefly_qt.widgets.audio_visualizer.get_live_spectrum_bands", return_value=live):
        viz._tick()
    # İlk yükselişte (attack=0.55) 0.04'ten 0.51 civarına fırlamalı
    assert all(lv > 0.45 for lv in viz._levels)

    # Canlı veri yoksa simülasyona sorunsuz düşmeli
    with patch("mustiefly_qt.widgets.audio_visualizer.get_live_spectrum_bands", return_value=None):
        viz._tick()
    assert len(viz._levels) == 16
    viz.deleteLater()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows yerleşik C# WASAPI yardımcısı yalnızca Windows'ta çalışır")
def test_csharp_wasapi_self_test_if_built():
    exe = find_helper_exe()
    if exe is None:
        pytest.skip("WasapiSpectrum.exe henüz derlenmemiş")
    res = subprocess.run([str(exe), "--self-test"], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0
    assert "SELF_TEST_OK" in res.stdout

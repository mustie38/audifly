"""
Tek Tık Ses Efekt Modları:
Normal, Slowed, Speed Up, Nightcore, Bass Boost, Gece Modu.

Her mod çalma hızı (rate) ve 10-bant VLC ekolayzer profilini tek adımda uygular;
Normal moda dönüldüğünde hız 1.0x'e ve ekolayzer sıfıra çekilir.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SoundMode:
    key: str
    label: str
    icon: str
    description: str
    rate: float
    bands: tuple[float, ...]  # 10-band VLC EQ (60Hz..16kHz, -20..+20 dB)


SOUND_MODES: dict[str, SoundMode] = {
    "normal": SoundMode(
        key="normal",
        label="Normal",
        icon="🎵",
        description="Orijinal hız (1.0x) ve düz ekolayzer",
        rate=1.0,
        bands=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ),
    "slowed": SoundMode(
        key="slowed",
        label="Slowed",
        icon="🌙",
        description="Yavaşlatılmış (0.84x) ve sıcak derin bas tonu",
        rate=0.84,
        bands=(4.5, 3.5, 2.0, 0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -3.5),
    ),
    "speed_up": SoundMode(
        key="speed_up",
        label="Speed Up",
        icon="⚡",
        description="Hızlandırılmış (1.18x) ve enerjik pop dengesi",
        rate=1.18,
        bands=(2.0, 1.5, 0.5, 0.0, 1.0, 2.0, 2.5, 2.0, 1.5, 1.0),
    ),
    "nightcore": SoundMode(
        key="nightcore",
        label="Nightcore",
        icon="✨",
        description="Yüksek tempo (1.25x) ve parlak tiz vurgusu",
        rate=1.25,
        bands=(1.0, 1.5, 1.0, 0.5, 1.5, 2.5, 3.5, 4.5, 4.0, 3.5),
    ),
    "bass_boost": SoundMode(
        key="bass_boost",
        label="Bass Boost",
        icon="🔊",
        description="Orijinal hızda güçlü alt frekans ve derin bas",
        rate=1.0,
        bands=(8.0, 7.0, 5.0, 2.0, 0.0, -0.5, 0.0, 1.0, 1.5, 1.0),
    ),
    "night_mode": SoundMode(
        key="night_mode",
        label="Gece Modu",
        icon="🌌",
        description="Kısık bas ve net vokal — gece/komşu dostu",
        rate=1.0,
        bands=(-5.0, -4.0, -2.0, 1.0, 2.5, 3.0, 2.0, 0.5, -1.0, -2.0),
    ),
}

SOUND_MODE_ORDER: tuple[str, ...] = (
    "normal", "slowed", "speed_up", "nightcore", "bass_boost", "night_mode"
)


def apply_sound_mode(playback, mode_key: str) -> SoundMode:
    """Verilen ses modunu PlaybackEngine üzerinde canlı uygular."""
    mode = SOUND_MODES.get(mode_key, SOUND_MODES["normal"])
    if hasattr(playback, "settings") and isinstance(playback.settings, dict):
        playback.settings["sound_mode"] = mode.key
    if hasattr(playback, "set_rate"):
        playback.set_rate(mode.rate)
    if hasattr(playback, "apply_equalizer_bands"):
        playback.apply_equalizer_bands(list(mode.bands), enabled=(mode.key != "normal"))
    sig = getattr(playback, "soundModeChanged", None)
    if sig is not None:
        sig.emit(mode.key)
    status_sig = getattr(playback, "statusMessage", None)
    if status_sig is not None:
        status_sig.emit(f"{mode.icon} Ses Modu: {mode.label} ({mode.rate:.2f}x)", "info")
    return mode

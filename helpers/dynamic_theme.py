"""Çalan şarkının kapak görselinden baskın, canlı bir vurgu rengi çıkarır.

Görseli küçültüp pikselleri HSV uzayında tarar; yeterince doygun ve parlak
piksellerin en yoğun renk tonu (hue) kümesinin ortalamasını alır. Canlı bir
piksel kümesi yoksa (gri/siyah kapaklar) None döner — arayan taraf mevcut
tema rengini korur.
"""
from __future__ import annotations

import colorsys


def dominant_accent_color(pil_img, hue_bins: int = 24,
                          sat_min: float = 0.35,
                          val_min: float = 0.25, val_max: float = 0.95) -> str | None:
    try:
        img = pil_img.convert("RGB").resize((60, 60))
        pixels = list(img.getdata())
    except Exception:
        return None

    buckets: dict[int, list[tuple[int, int, int]]] = {}
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < sat_min or not (val_min <= v <= val_max):
            continue
        buckets.setdefault(int(h * hue_bins) % hue_bins, []).append((r, g, b))

    if not buckets:
        return None

    best = max(buckets.values(), key=len)
    n = len(best)
    r = sum(p[0] for p in best) // n
    g = sum(p[1] for p in best) // n
    b = sum(p[2] for p in best) // n

    # Ortalama renk bazen soluk kalır — hafif canlılık kat
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    s = max(s, 0.55)
    v = min(max(v, 0.55), 0.85)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return "#{:02x}{:02x}{:02x}".format(int(r2 * 255), int(g2 * 255), int(b2 * 255))

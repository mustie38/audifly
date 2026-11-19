"""
Paylaşılabilir Şarkı Sözü Kartı (PNG) üretici — saf QPainter yüksek çözünürlüklü
sosyal medya / Discord / WhatsApp kartı (720×900).
"""
from __future__ import annotations

import colorsys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME, cover_color_for

CARD_THEMES: dict[str, tuple[str, str, str]] = {
    "dynamic": ("🎨 Kapak Rengi", "", ""),
    "neon_purple": ("💜 Neon Mor", "#7b2cbf", "#1b1440"),
    "midnight": ("🌑 Gece Siyahı", "#232a3d", "#090b12"),
    "sunset": ("🌅 Gün Batımı", "#e85d04", "#3c096c"),
}


def _derive_palette(theme_key: str, title: str) -> tuple[QColor, QColor]:
    if theme_key in CARD_THEMES and theme_key != "dynamic":
        _, c1_hex, c2_hex = CARD_THEMES[theme_key]
        return QColor(c1_hex), QColor(c2_hex)
    base_hex = cover_color_for(title or "Audifly")
    c1 = QColor(base_hex)
    h, s, v = colorsys.rgb_to_hsv(c1.red() / 255.0, c1.green() / 255.0, c1.blue() / 255.0)
    r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.14) % 1.0, min(1.0, max(0.45, s)), max(0.22, v * 0.45))
    c2 = QColor(int(r2 * 255), int(g2 * 255), int(b2 * 255))
    return c1, c2


def render_lyric_card(
    title: str,
    artist: str,
    lyrics_text: str,
    cover_pixmap: QPixmap | None = None,
    theme_key: str = "dynamic",
    width: int = 720,
    height: int = 900,
) -> QPixmap:
    """Seçilen şarkı sözü satırlarını yüksek kaliteli paylaşılabilir QPixmap kart olarak çizer."""
    pm = QPixmap(width, height)
    pm.fill(QColor("#0a0c14"))

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    c1, c2 = _derive_palette(theme_key, title)

    # 1) Zengin gradyan arka plan
    bg_grad = QLinearGradient(0, 0, width, height)
    bg_grad.setColorAt(0.0, QColor(c1.red(), c1.green(), c1.blue(), 220))
    bg_grad.setColorAt(0.55, QColor(c2.red(), c2.green(), c2.blue(), 245))
    bg_grad.setColorAt(1.0, QColor(10, 11, 20, 255))
    p.fillRect(0, 0, width, height, bg_grad)

    # Parlak radyal vurgu küreleri
    glow1 = QRadialGradient(width * 0.22, height * 0.18, width * 0.65)
    glow1.setColorAt(0.0, QColor(c1.red(), c1.green(), c1.blue(), 150))
    glow1.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, width, height, glow1)

    glow2 = QRadialGradient(width * 0.82, height * 0.85, width * 0.60)
    glow2.setColorAt(0.0, QColor(255, 255, 255, 38))
    glow2.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, width, height, glow2)

    # 2) İç buzlu cam kart çerçevesi
    margin = 44
    card_rect = QRectF(margin, margin, width - 2 * margin, height - 2 * margin)
    card_path = QPainterPath()
    card_path.addRoundedRect(card_rect, 34, 34)
    p.fillPath(card_path, QColor(12, 14, 24, 155))
    p.setPen(QPen(QColor(255, 255, 255, 42), 1.5))
    p.drawPath(card_path)

    # 3) Üst bilgi: Albüm Kapağı + Şarkı Adı + Sanatçı
    pad = margin + 40
    cover_size = 112
    cover_rect = QRectF(pad, pad, cover_size, cover_size)
    cov_path = QPainterPath()
    cov_path.addRoundedRect(cover_rect, 20, 20)

    p.save()
    p.setClipPath(cov_path)
    if cover_pixmap is not None and not cover_pixmap.isNull():
        scaled = cover_pixmap.scaled(
            cover_size, cover_size,
            Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
        )
        sx = max(0, (scaled.width() - cover_size) // 2)
        sy = max(0, (scaled.height() - cover_size) // 2)
        p.drawPixmap(int(cover_rect.x()), int(cover_rect.y()), scaled.copy(sx, sy, cover_size, cover_size))
    else:
        p.fillRect(cover_rect, c1)
        f_note = QFont("Segoe UI", 42)
        p.setFont(f_note)
        p.setPen(QColor("#ffffff"))
        p.drawText(cover_rect, Qt.AlignCenter, "♪")
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 60), 1.2))
    p.drawPath(cov_path)

    text_x = pad + cover_size + 24
    text_w = width - margin - 40 - text_x

    title_font = QFont("Segoe UI", 22, QFont.Bold)
    p.setFont(title_font)
    p.setPen(QColor("#ffffff"))
    title_rect = QRectF(text_x, pad + 14, text_w, 46)
    p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, (title or "Bilinmeyen Şarkı")[:34])

    artist_font = QFont("Segoe UI", 16)
    p.setFont(artist_font)
    p.setPen(QColor(225, 228, 242, 195))
    artist_rect = QRectF(text_x, pad + 60, text_w, 34)
    p.drawText(artist_rect, Qt.AlignLeft | Qt.AlignVCenter, (artist or "Audifly")[:38])

    # İnce ayırıcı
    sep_y = pad + cover_size + 32
    p.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
    p.drawLine(int(pad), int(sep_y), int(width - pad), int(sep_y))

    # 4) Sözler gövdesi (alinti dikey şeridi + kalın okunaklı tipografi)
    clean_lines = [ln.strip() for ln in (lyrics_text or "").splitlines() if ln.strip()]
    body_text = "\n".join(clean_lines[:8]) if clean_lines else "“Müziğin ritmini hisset.”"

    lyrics_top = sep_y + 36
    lyrics_bottom = height - margin - 96
    lyrics_h = max(120, lyrics_bottom - lyrics_top)

    # Sol neon alıntı çizgisi
    accent_bar = QRectF(pad, lyrics_top + 8, 5, min(lyrics_h - 16, 260))
    p.setPen(Qt.NoPen)
    p.setBrush(c1.lighter(135))
    p.drawRoundedRect(accent_bar, 2.5, 2.5)

    # Metin uzunluğuna göre dinamik punto
    char_count = len(body_text)
    if char_count <= 80:
        pt = 30
    elif char_count <= 160:
        pt = 25
    elif char_count <= 260:
        pt = 21
    else:
        pt = 18

    lyr_font = QFont("Segoe UI", pt, QFont.Bold)
    p.setFont(lyr_font)
    p.setPen(QColor("#ffffff"))
    lyrics_rect = QRectF(pad + 24, lyrics_top, width - 2 * pad - 24, lyrics_h)
    p.drawText(lyrics_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, body_text)

    # 5) Alt marka rozeti
    footer_y = height - margin - 62
    badge_font = QFont("Segoe UI", 13, QFont.Bold)
    p.setFont(badge_font)
    p.setPen(QColor(255, 255, 255, 190))
    p.drawText(
        QRectF(pad, footer_y, width - 2 * pad, 34),
        Qt.AlignLeft | Qt.AlignVCenter,
        f"🎵  {APP_DISPLAY_NAME}",
    )
    p.setPen(QColor(255, 255, 255, 120))
    sub_font = QFont("Segoe UI", 11)
    p.setFont(sub_font)
    p.drawText(
        QRectF(pad, footer_y, width - 2 * pad, 34),
        Qt.AlignRight | Qt.AlignVCenter,
        "Şarkı Sözü Kartı",
    )

    p.end()
    return pm

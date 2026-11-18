"""Canlı Müzik Görselleştirici & Neon Spektrum (Audio Visualizer).

Özellikler:
- 4 farklı görsel mod:
  1. 'bars'     : Neon Spektrum Barları + Tepe Noktası (Peak-Hold) + Ayna Yansıması
  2. 'wave'     : Çok Katmanlı Akışkan Neon Dalga (Apple Music / Liquid Wave)
  3. 'mirror'   : Merkez Eksende Simetrik Çift Yönlü Spektrum (SoundCloud / Pulse)
  4. 'circular' : Dairesel Radyal Nabız & Frekans Halkası (NCS / Radial Reactor)
- 5 farklı renk paleti:
  - 'dynamic'   : Şarkı kapağından / aktif temadan türetilen dinamik neon renkler
  - 'cyberpunk' : Neon Pembe (#ff2a85) & Siber Camgöbeği (#00f0ff)
  - 'aurora'    : Kuzey Işıkları Yeşili (#00ff87) & Elektrik Mavisi (#60efff)
  - 'fire'      : Lav Turuncusu (#ff4e00) & Altın Kehribar (#ec9f05)
  - 'galaxy'    : Kozmik Mor (#a980f9) & Neon Mavi (#00d2ff)
- Performans dostu:
  - Yalnızca şarkı çalarken ve widget görünürken zamanlayıcı (30 FPS) çalışır.
  - Şarkı durduğunda barlar yumuşakça sönümlenir ve sıfırlandığında zamanlayıcı
    tamamen durur (boşta %0 CPU kullanımı).
"""
from __future__ import annotations

import colorsys
import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QMenu, QWidget

VISUALIZER_MODES = ("bars", "wave", "mirror", "circular")
MODE_LABELS = {
    "bars": "📊 Neon Barlar",
    "wave": "🌊 Akışkan Dalga",
    "mirror": "💠 Simetrik Spektrum",
    "circular": "⭕ Dairesel Nabız",
    "off": "🚫 Kapalı",
}

PALETTES = {
    "dynamic": ("🎨 Dinamik (Kapak / Tema)", None, None),
    "cyberpunk": ("🌆 Cyberpunk (Pembe & Camgöbeği)", "#ff2a85", "#00f0ff"),
    "aurora": ("🌌 Aurora (Yeşil & Mavi)", "#00ff87", "#60efff"),
    "fire": ("🔥 Ateş & Kehribar", "#ff4e00", "#ffc837"),
    "galaxy": ("🪐 Galaksi (Mor & Mavi)", "#a980f9", "#00d2ff"),
}

TICK_MS = 33  # ~30 FPS akıcı animasyon
DEFAULT_BAR_COUNT = 40


def _complementary_neon(hex_color: str) -> tuple[QColor, QColor]:
    """Verilen vurgu renginden parlak bir ana neon ve tamamlayıcı ikinci neon renk üretir."""
    base = QColor(hex_color) if hex_color else QColor("#a980f9")
    if not base.isValid():
        base = QColor("#a980f9")
    r, g, b = base.red() / 255.0, base.green() / 255.0, base.blue() / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    # Ana rengi neon parlaklığına çek
    s1 = max(0.65, min(1.0, s * 1.15))
    v1 = max(0.85, min(1.0, v * 1.2))
    r1, g1, b1 = colorsys.hsv_to_rgb(h, s1, v1)
    c1 = QColor(int(r1 * 255), int(g1 * 255), int(b1 * 255))

    # İkincil renk: renk çemberinde +0.16 kaydırılmış parlak ton
    h2 = (h + 0.16) % 1.0
    r2, g2, b2 = colorsys.hsv_to_rgb(h2, 0.85, 0.98)
    c2 = QColor(int(r2 * 255), int(g2 * 255), int(b2 * 255))
    return c1, c2


class NeonAudioVisualizer(QWidget):
    """Gerçek zamanlı, çok modlu Neon Spektrum ve Ses Görselleştirici widget'ı."""

    modeChanged = Signal(str)
    paletteChanged = Signal(str)

    def __init__(
        self,
        playback=None,
        accent: str = "#a980f9",
        mode: str = "bars",
        palette: str = "dynamic",
        bar_count: int = DEFAULT_BAR_COUNT,
        interactive: bool = True,
        transparent_bg: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.playback = playback
        self._bar_count = max(16, int(bar_count))
        self._mode = mode if mode in (*VISUALIZER_MODES, "off") else "bars"
        self._palette = palette if palette in PALETTES else "dynamic"
        self._interactive = bool(interactive)
        self._transparent_bg = bool(transparent_bg)
        self._enabled = True

        self._dynamic_hex = accent or "#a980f9"
        self._c1, self._c2 = _complementary_neon(self._dynamic_hex)
        self._apply_palette_colors()

        # Frekans bantları (0.0 .. 1.0 arası normalize yükseklik) ve tepe noktaları (peak-hold)
        self._levels: list[float] = [0.04] * self._bar_count
        self._peaks: list[float] = [0.04] * self._bar_count
        self._peak_vel: list[float] = [0.0] * self._bar_count
        self._phase: float = 0.0
        self._beat_energy: float = 0.0
        self._playing: bool = False

        if self._interactive:
            self.setCursor(Qt.PointingHandCursor)
            self._update_tooltip()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

        if self.playback is not None:
            self._wire_playback()

    # ------------------------------------------------------------------
    # Bağlantılar ve Durum Yönetimi
    # ------------------------------------------------------------------
    def _wire_playback(self):
        if hasattr(self.playback, "playStateChanged"):
            self.playback.playStateChanged.connect(self.set_playing)
        if hasattr(self.playback, "songStarted"):
            self.playback.songStarted.connect(lambda *_: self._on_song_changed())
        if hasattr(self.playback, "radioStarted"):
            self.playback.radioStarted.connect(lambda *_: self.set_playing(True))
        if hasattr(self.playback, "radioStopped"):
            self.playback.radioStopped.connect(lambda *_: self.set_playing(False))
        # Başlangıç durumu
        is_pl = bool(getattr(self.playback, "is_playing", False))
        self.set_playing(is_pl)

    def _on_song_changed(self):
        # Yeni şarkıda faz ve ritim tohumunu tazele
        self._beat_energy = 0.85
        self.set_playing(True)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def palette_name(self) -> str:
        return self._palette

    def set_enabled_state(self, enabled: bool):
        self._enabled = bool(enabled)
        self.setVisible(self._enabled and self._mode != "off")
        if not self._enabled:
            self._timer.stop()
        elif self._playing and self.isVisible():
            self._timer.start()
        self.update()

    def set_mode(self, mode: str):
        if mode not in (*VISUALIZER_MODES, "off"):
            return
        if self._mode == mode:
            return
        self._mode = mode
        self._update_tooltip()
        if self._mode == "off":
            self._timer.stop()
        elif self._playing and self.isVisible() and not self._timer.isActive():
            self._timer.start()
        self.modeChanged.emit(self._mode)
        self.update()

    def cycle_mode(self, include_off: bool = False) -> str:
        modes = (*VISUALIZER_MODES, "off") if include_off else VISUALIZER_MODES
        try:
            idx = modes.index(self._mode)
            new_mode = modes[(idx + 1) % len(modes)]
        except ValueError:
            new_mode = modes[0]
        self.set_mode(new_mode)
        return new_mode

    def set_palette(self, palette: str):
        if palette not in PALETTES:
            return
        self._palette = palette
        self._apply_palette_colors()
        self._update_tooltip()
        self.paletteChanged.emit(self._palette)
        self.update()

    def cycle_palette(self) -> str:
        keys = list(PALETTES.keys())
        try:
            idx = keys.index(self._palette)
            new_pal = keys[(idx + 1) % len(keys)]
        except ValueError:
            new_pal = "dynamic"
        self.set_palette(new_pal)
        return new_pal

    def set_accent(self, hex1: str | None, hex2: str | None = None):
        if hex1:
            self._dynamic_hex = hex1
        if self._palette == "dynamic":
            if hex1 and hex2:
                self._c1 = QColor(hex1)
                self._c2 = QColor(hex2)
            else:
                self._c1, self._c2 = _complementary_neon(self._dynamic_hex)
            self.update()

    def _apply_palette_colors(self):
        if self._palette == "dynamic":
            self._c1, self._c2 = _complementary_neon(self._dynamic_hex)
        else:
            _, h1, h2 = PALETTES[self._palette]
            self._c1 = QColor(h1)
            self._c2 = QColor(h2)

    def _update_tooltip(self):
        if not self._interactive:
            return
        m_label = MODE_LABELS.get(self._mode, self._mode)
        p_label = PALETTES.get(self._palette, ("",))[0]
        self.setToolTip(
            f"Canlı Spektrum: {m_label} • {p_label}\n"
            "Sol tık: Görünüm modunu değiştir (G)\n"
            "Sağ tık: Mod ve renk paleti menüsü"
        )

    def set_playing(self, playing: bool):
        self._playing = bool(playing)
        if self._playing and self.isVisible() and self._enabled and self._mode != "off":
            if not self._timer.isActive():
                self._timer.start()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._playing and self._enabled and self._mode != "off" and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # Etkileşim (Tıklama & Sağ Tık Menüsü)
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if not self._interactive:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self.cycle_mode(include_off=False)
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def _show_context_menu(self, global_pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #161324;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                padding: 6px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(169, 128, 249, 0.28);
            }
        """)
        mode_header = menu.addAction("🌊 Görselleştirici Modu")
        mode_header.setEnabled(False)
        for m_key in VISUALIZER_MODES:
            prefix = "✓ " if self._mode == m_key else "    "
            act = menu.addAction(f"{prefix}{MODE_LABELS[m_key]}")
            act.triggered.connect(lambda _=False, k=m_key: self.set_mode(k))

        menu.addSeparator()
        pal_header = menu.addAction("🎨 Neon Renk Paleti")
        pal_header.setEnabled(False)
        for p_key, (p_label, _, _) in PALETTES.items():
            prefix = "✓ " if self._palette == p_key else "    "
            act = menu.addAction(f"{prefix}{p_label}")
            act.triggered.connect(lambda _=False, k=p_key: self.set_palette(k))

        menu.exec(global_pos)

    # ------------------------------------------------------------------
    # Fizik & Frekans Spektrumu Simülasyonu (30 FPS)
    # ------------------------------------------------------------------
    def _tick(self):
        rest_floor = 0.04
        if not self._playing:
            at_rest = all(abs(lv - rest_floor) < 0.01 and abs(pk - rest_floor) < 0.01
                          for lv, pk in zip(self._levels, self._peaks))
            if at_rest:
                self._timer.stop()
                return

        # Oynatma hızı ve ses seviyesi çarpanları
        rate = 1.0
        vol_scale = 0.9
        vocal_cut = False
        if self.playback is not None:
            st = getattr(self.playback, "settings", {}) or {}
            rate = float(st.get("_rate", 1.0) or 1.0)
            vol = float(st.get("_volume", 80))
            vol_scale = max(0.25, min(1.15, (vol / 85.0)))
            vocal_cut = bool(getattr(self.playback, "vocal_remover_enabled", False))

        self._phase += 0.22 * rate

        # Bas vuruşu (beat) zarfı
        if self._playing:
            if random.random() < 0.26 * rate:
                self._beat_energy = min(1.0, self._beat_energy + random.uniform(0.35, 0.75))
            else:
                self._beat_energy *= 0.84
        else:
            self._beat_energy *= 0.5

        n = self._bar_count
        for i in range(n):
            norm_i = i / max(1, n - 1)  # 0.0 (bas) -> 1.0 (tiz)
            if self._playing:
                # 1) Alt frekanslar (Sub-bass & Kick: 0.0 - 0.25)
                bass_weight = max(0.0, 1.0 - norm_i * 3.2)
                bass_comp = bass_weight * (0.45 + 0.55 * self._beat_energy)

                # 2) Orta frekanslar (Vokal & Melodi: 0.20 - 0.75)
                mid_wave = (
                    math.sin(self._phase * 1.3 + i * 0.35) * 0.5
                    + math.cos(self._phase * 0.8 - i * 0.22) * 0.5
                )
                mid_envelope = math.sin(norm_i * math.pi)
                mid_comp = max(0.0, (0.38 + 0.34 * mid_wave) * mid_envelope)
                if vocal_cut and 0.25 <= norm_i <= 0.68:
                    # Enstrümantal mod açıksa orta vokal bantlarında çentik etkisi
                    mid_comp *= 0.42

                # 3) Üst frekanslar (Tiz & Hi-Hat parıltısı: 0.65 - 1.0)
                treble_weight = max(0.0, (norm_i - 0.55) * 1.8)
                treble_comp = treble_weight * random.uniform(0.12, 0.65)

                # Rastgele organik canlılık
                jitter = random.uniform(-0.08, 0.14)
                target = (bass_comp + mid_comp + treble_comp + jitter) * vol_scale
                target = max(0.06, min(0.98, target))
            else:
                target = rest_floor

            cur = self._levels[i]
            # Yükselirken hızlı (attack), inerken yumuşak (release)
            alpha = 0.55 if target > cur else 0.28
            new_lvl = cur + (target - cur) * alpha
            self._levels[i] = new_lvl

            # Peak-Hold (Tepe noktası) yerçekimi fiziği
            if new_lvl >= self._peaks[i]:
                self._peaks[i] = new_lvl
                self._peak_vel[i] = 0.0
            else:
                self._peak_vel[i] += 0.0045
                self._peaks[i] = max(new_lvl, self._peaks[i] - self._peak_vel[i])

        self.update()

    # ------------------------------------------------------------------
    # Çizim Motoru (QPainter)
    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        if not self._enabled or self._mode == "off":
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        if w <= 4 or h <= 4:
            painter.end()
            return

        # Arka plan (kart görünümü isteniyorsa yarı saydam koyu cam zemin)
        if not self._transparent_bg:
            bg_path = QPainterPath()
            bg_path.addRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 12.0, 12.0)
            bg_grad = QLinearGradient(0, 0, 0, h)
            bg_grad.setColorAt(0.0, QColor(18, 15, 30, 175))
            bg_grad.setColorAt(1.0, QColor(10, 8, 18, 210))
            painter.fillPath(bg_path, QBrush(bg_grad))

            # İnce neon çerçeve parıltısı
            border_color = QColor(self._c1.red(), self._c1.green(), self._c1.blue(), 42)
            painter.setPen(QPen(border_color, 1.0))
            painter.drawPath(bg_path)

        if self._mode == "bars":
            self._draw_bars(painter, w, h)
        elif self._mode == "wave":
            self._draw_wave(painter, w, h)
        elif self._mode == "mirror":
            self._draw_mirror(painter, w, h)
        elif self._mode == "circular":
            self._draw_circular(painter, w, h)

        painter.end()

    def _color_at(self, ratio: float, alpha: int = 255) -> QColor:
        """0.0..1.0 oranına göre c1 ile c2 arasında ara neon renk döndürür."""
        ratio = max(0.0, min(1.0, ratio))
        r = int(self._c1.red() + (self._c2.red() - self._c1.red()) * ratio)
        g = int(self._c1.green() + (self._c2.green() - self._c1.green()) * ratio)
        b = int(self._c1.blue() + (self._c2.blue() - self._c1.blue()) * ratio)
        return QColor(r, g, b, alpha)

    def _draw_bars(self, painter: QPainter, w: float, h: float):
        """1. Mod: Neon Spektrum Barları + Peak-Hold + Alt Yansıma."""
        pad_x = 10.0 if not self._transparent_bg else 2.0
        pad_top = 8.0
        reflection_h = h * 0.18
        usable_h = max(8.0, h - pad_top - reflection_h - 4.0)
        baseline_y = pad_top + usable_h

        n = self._bar_count
        avail_w = max(10.0, w - 2 * pad_x)
        step = avail_w / n
        bar_w = max(2.0, step * 0.68)
        radius = min(bar_w / 2.0, 3.5)

        painter.setPen(Qt.NoPen)

        for i in range(n):
            ratio = i / max(1, n - 1)
            lvl = self._levels[i]
            pk = self._peaks[i]
            bh = max(3.0, lvl * usable_h)
            x = pad_x + i * step + (step - bar_w) * 0.5
            y = baseline_y - bh

            # Ana bar gradyanı (aşağıdan yukarıya c1 -> c2 -> parlak uç)
            col_bottom = self._color_at(ratio, 220)
            col_top = self._color_at(min(1.0, ratio + 0.25), 255)
            grad = QLinearGradient(x, baseline_y, x, y)
            grad.setColorAt(0.0, col_bottom)
            grad.setColorAt(0.75, col_top)
            grad.setColorAt(1.0, QColor(255, 255, 255, 235))

            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(QRectF(x, y, bar_w, bh), radius, radius)

            # Peak-Hold (Tepe çizgisi)
            pk_y = max(2.0, baseline_y - pk * usable_h - 3.0)
            peak_col = self._color_at(ratio, 245)
            painter.setBrush(peak_col)
            painter.drawRoundedRect(QRectF(x, pk_y, bar_w, 2.2), 1.0, 1.0)

            # Alt ayna yansıması (Mirror reflection)
            ref_bh = min(reflection_h, bh * 0.32)
            if ref_bh > 1.0:
                ref_grad = QLinearGradient(x, baseline_y + 2.0, x, baseline_y + 2.0 + ref_bh)
                ref_grad.setColorAt(0.0, self._color_at(ratio, 75))
                ref_grad.setColorAt(1.0, self._color_at(ratio, 0))
                painter.setBrush(QBrush(ref_grad))
                painter.drawRoundedRect(QRectF(x, baseline_y + 2.0, bar_w, ref_bh), radius, radius)

    def _draw_wave(self, painter: QPainter, w: float, h: float):
        """2. Mod: Çok Katmanlı Akışkan Neon Dalga (Liquid Ribbon)."""
        pad_x = 6.0 if not self._transparent_bg else 0.0
        usable_w = max(10.0, w - 2 * pad_x)
        baseline_y = h * 0.88
        max_amp = h * 0.72
        n = self._bar_count

        # 3 katmanlı dalga (arka katmanlardan ön katmana)
        layers = (
            (0.55, 0.65, 55, 1.6, self._c2),
            (0.80, -0.35, 95, 2.2, self._color_at(0.5)),
            (1.00, 0.0, 145, 2.8, self._c1),
        )

        for amp_scale, phase_offset, fill_alpha, pen_width, stroke_col in layers:
            pts: list[QPointF] = []
            for i in range(n):
                x = pad_x + (i / max(1, n - 1)) * usable_w
                harmonic = math.sin(self._phase * 0.9 + i * 0.25 + phase_offset) * 0.08
                lvl = max(0.04, min(1.0, self._levels[i] * amp_scale + harmonic))
                y = baseline_y - lvl * max_amp
                pts.append(QPointF(x, y))

            if len(pts) < 2:
                continue

            # Yumuşak eğri yolu oluştur
            wave_path = QPainterPath()
            wave_path.moveTo(pts[0])
            for i in range(len(pts) - 1):
                p0 = pts[i]
                p1 = pts[i + 1]
                mid_x = (p0.x() + p1.x()) * 0.5
                mid_y = (p0.y() + p1.y()) * 0.5
                wave_path.quadTo(p0, QPointF(mid_x, mid_y))
            wave_path.lineTo(pts[-1])

            # Alt dolgu yolu
            fill_path = QPainterPath(wave_path)
            fill_path.lineTo(pts[-1].x(), baseline_y)
            fill_path.lineTo(pts[0].x(), baseline_y)
            fill_path.closeSubpath()

            fill_grad = QLinearGradient(0, baseline_y - max_amp, 0, baseline_y)
            c_top = QColor(stroke_col.red(), stroke_col.green(), stroke_col.blue(), fill_alpha)
            c_bot = QColor(stroke_col.red(), stroke_col.green(), stroke_col.blue(), 5)
            fill_grad.setColorAt(0.0, c_top)
            fill_grad.setColorAt(1.0, c_bot)
            painter.fillPath(fill_path, QBrush(fill_grad))

            # Parlak neon sırt çizgisi
            line_grad = QLinearGradient(pad_x, 0, pad_x + usable_w, 0)
            line_grad.setColorAt(0.0, self._c1)
            line_grad.setColorAt(0.5, self._c2)
            line_grad.setColorAt(1.0, self._c1)
            pen = QPen(QBrush(line_grad), pen_width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(wave_path)

    def _draw_mirror(self, painter: QPainter, w: float, h: float):
        """3. Mod: Merkez Eksende Simetrik Çift Yönlü Neon Spektrum."""
        pad_x = 10.0 if not self._transparent_bg else 2.0
        avail_w = max(10.0, w - 2 * pad_x)
        center_y = h * 0.5
        max_half_h = max(4.0, (h - 12.0) * 0.46)

        n = self._bar_count
        step = avail_w / n
        bar_w = max(2.0, step * 0.65)
        radius = min(bar_w * 0.5, 3.0)

        # Merkez enerji çizgisi
        center_pen = QPen(QColor(self._c2.red(), self._c2.green(), self._c2.blue(), 70), 1.0)
        painter.setPen(center_pen)
        painter.drawLine(QPointF(pad_x, center_y), QPointF(w - pad_x, center_y))
        painter.setPen(Qt.NoPen)

        for i in range(n):
            ratio = i / max(1, n - 1)
            half_bh = max(2.0, self._levels[i] * max_half_h)
            x = pad_x + i * step + (step - bar_w) * 0.5
            top_y = center_y - half_bh
            total_bh = half_bh * 2.0

            grad = QLinearGradient(x, top_y, x, top_y + total_bh)
            c_edge = self._color_at(ratio, 240)
            c_mid = QColor(255, 255, 255, 245)
            grad.setColorAt(0.0, c_edge)
            grad.setColorAt(0.5, c_mid)
            grad.setColorAt(1.0, self._color_at(1.0 - ratio, 220))

            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(QRectF(x, top_y, bar_w, total_bh), radius, radius)

    def _draw_circular(self, painter: QPainter, w: float, h: float):
        """4. Mod: Dairesel Radyal Nabız & Frekans Halkası (Radial Pulse)."""
        cx, cy = w * 0.5, h * 0.5
        min_dim = min(w, h)
        avg_bass = sum(self._levels[:6]) / 6.0 if self._levels else 0.1
        base_r = max(10.0, min_dim * (0.20 + 0.06 * avg_bass))
        max_bar_len = max(6.0, min_dim * 0.26)

        # Merkezdeki bas nabız küresi (glow)
        glow_r = base_r + max_bar_len * 0.85
        radial = QRadialGradient(cx, cy, glow_r)
        radial.setColorAt(0.0, QColor(self._c1.red(), self._c1.green(), self._c1.blue(), 110))
        radial.setColorAt(0.55, QColor(self._c2.red(), self._c2.green(), self._c2.blue(), 45))
        radial.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(radial))
        painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # Dairesel frekans ışınları
        n = self._bar_count
        for i in range(n):
            angle = (2.0 * math.pi * i) / n - math.pi * 0.5
            ratio = i / max(1, n - 1)
            bar_len = max(2.5, self._levels[i] * max_bar_len)

            x1 = cx + math.cos(angle) * base_r
            y1 = cy + math.sin(angle) * base_r
            x2 = cx + math.cos(angle) * (base_r + bar_len)
            y2 = cy + math.sin(angle) * (base_r + bar_len)

            col = self._color_at(ratio, 240)
            pen = QPen(col, max(2.0, min(4.0, (2.0 * math.pi * base_r / n) * 0.6)))
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # İç neon çekirdek halkası
        ring_pen = QPen(QColor(255, 255, 255, 210), 1.8)
        painter.setPen(ring_pen)
        painter.setBrush(QColor(14, 11, 24, 200))
        painter.drawEllipse(QPointF(cx, cy), base_r * 0.88, base_r * 0.88)

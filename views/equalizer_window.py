"""
Ekolayzer penceresi — VLC AudioEqualizer API'sinin Qt arayüzü.

Orijinal mustiefly_settings.py'deki toggle_equalizer_window ve _apply_eq_preset /
_set_equalizer_band metodlarının portudur. Ayar değişiklikleri debounce'lu olarak
settings dosyasına yazılır.
"""
from __future__ import annotations


from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

import vlc
from mustiefly_qt.helpers.logging_setup import get_logger



log = get_logger(__name__)
class EqualizerWindow(QWidget):
    def __init__(self, playback, settings: dict, save_fn, parent=None):
        # ÖNEMLİ: parent verilen sıradan bir QWidget, Qt.Window bayrağı
        # olmadan varsayılan olarak GÖMÜLÜ bir alt widget olur (kendi pencere
        # çerçevesi/başlık çubuğu olmadan ana pencerenin (0,0) noktasına
        # yapışır). Bunu gerçek, bağımsız/yüzen bir pencere yapıyoruz.
        super().__init__(parent, Qt.Window)
        self.setObjectName("EqualizerWindow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.playback = playback
        self.settings = settings
        self.save_fn = save_fn
        self.setWindowTitle("🎚 Ses & Ekolayzer")
        self.resize(580, 420)
        if parent is not None:
            p = parent.geometry()
            self.move(p.x() + (p.width() - self.width()) // 2,
                      p.y() + (p.height() - self.height()) // 2)

        band_count = playback.eq_band_count
        self._sliders_updating = False

        root = QVBoxLayout(self)
        top_row = QHBoxLayout()
        title = QLabel("Ekolayzer")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        top_row.addWidget(title)
        top_row.addStretch(1)

        self.enable_check = QPushButton("Aktif" if not settings.get("equalizer_enabled") else "✓ Aktif")
        self.enable_check.setObjectName("Chip")
        self.enable_check.clicked.connect(self._toggle_enabled)
        top_row.addWidget(self.enable_check)
        root.addLayout(top_row)

        preset_row = QWidget()
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_label = QLabel("Hazır Ayar:")
        preset_label.setObjectName("Muted")
        preset_layout.addWidget(preset_label)
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Özel", None)
        for i, name in enumerate(playback.eq_preset_names):
            self.preset_combo.addItem(name.title(), i)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch(1)

        reset_btn = QPushButton("Sıfırla")
        reset_btn.clicked.connect(lambda: self._apply_flat())
        preset_layout.addWidget(reset_btn)
        root.addWidget(preset_row)

        bands_row = QWidget()
        bands_layout = QHBoxLayout(bands_row)
        bands_layout.setContentsMargins(0, 0, 0, 0)
        self.band_sliders: list[QSlider] = []
        self.band_values: list[float] = list(
            settings.get("equalizer_bands", [0.0] * band_count))

        for i in range(band_count):
            col = QWidget()
            col_layout = QVBoxLayout(col)
            col_layout.setContentsMargins(4, 0, 4, 0)
            slider = QSlider(Qt.Vertical)
            slider.setRange(-20, 20)
            slider.setValue(int(self.band_values[i]) if i < len(self.band_values) else 0)
            slider.setMinimumHeight(150)
            slider.valueChanged.connect(lambda v, idx=i: self._on_band_changed(idx, v))
            col_layout.addWidget(slider, stretch=1)
            try:
                freq = vlc.libvlc_audio_equalizer_get_band_frequency(i)
                freq_label = f"{int(freq)}Hz" if freq < 1000 else f"{freq / 1000:.1f}kHz"
            except Exception:
                freq_label = f"B{i + 1}"
            lbl = QLabel(freq_label)
            lbl.setObjectName("Muted")
            lbl.setAlignment(Qt.AlignCenter)
            col_layout.addWidget(lbl)
            bands_layout.addWidget(col)
            self.band_sliders.append(slider)
        root.addWidget(bands_row, stretch=1)

        # --- Ses & Geçiş Efektleri Bölümü ---
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(255, 255, 255, 0.1); margin: 6px 0;")
        root.addWidget(sep)

        fx_card = QWidget()
        fx_layout = QVBoxLayout(fx_card)
        fx_layout.setContentsMargins(0, 0, 0, 0)
        fx_layout.setSpacing(10)

        # Crossfade satırı
        cf_row = QHBoxLayout()
        self.cf_check = QCheckBox("Crossfade (Yumuşak Geçiş)")
        self.cf_check.setToolTip("Şarkı biterken sıradakine kesintisiz, pürüzsüz geçiş sağlar.")
        self.cf_check.setChecked(bool(self.settings.get("crossfade_enabled", False)))
        self.cf_check.toggled.connect(self._on_crossfade_toggled)
        cf_row.addWidget(self.cf_check)

        cf_row.addStretch(1)

        cf_sec = int(self.settings.get("crossfade_seconds", 3))
        self.cf_label = QLabel(f"{cf_sec} sn")
        self.cf_label.setObjectName("Muted")
        self.cf_label.setFixedWidth(40)
        self.cf_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.cf_slider = QSlider(Qt.Horizontal)
        self.cf_slider.setRange(1, 12)
        self.cf_slider.setValue(cf_sec)
        self.cf_slider.setFixedWidth(120)
        self.cf_slider.valueChanged.connect(self._on_crossfade_seconds_changed)

        cf_row.addWidget(self.cf_slider)
        cf_row.addWidget(self.cf_label)
        fx_layout.addLayout(cf_row)

        # Ses Normalizasyonu satırı
        norm_row = QHBoxLayout()
        self.norm_check = QCheckBox("Ses Seviyesini Dengele (Eşit Ses / ReplayGain)")
        self.norm_check.setToolTip("Farklı şarkılar arasındaki ani ses patlamalarını ve fısıltıları otomatik dengeler.")
        self.norm_check.setChecked(bool(self.settings.get("audio_normalization", False)))
        self.norm_check.toggled.connect(self._on_norm_toggled)
        norm_row.addWidget(self.norm_check)
        norm_row.addStretch(1)
        fx_layout.addLayout(norm_row)

        # Vokal Ayırma / Enstrümantal Mod (Karaoke)
        vocal_row = QHBoxLayout()
        self.vocal_check = QCheckBox("🎙️ Vokal Ayırma / Enstrümantal Mod (Karaoke)")
        self.vocal_check.setToolTip("Şarkının merkezindeki vokal seslerini bastırarak karaoke için enstrümantal ses üretir (Kısayol: V).")
        self.vocal_check.setChecked(bool(self.settings.get("vocal_remover_enabled", False)))
        self.vocal_check.toggled.connect(self._on_vocal_toggled)
        vocal_row.addWidget(self.vocal_check)
        vocal_row.addStretch(1)
        fx_layout.addLayout(vocal_row)

        if hasattr(self.playback, "vocalRemoverChanged"):
            self.playback.vocalRemoverChanged.connect(self._sync_vocal_check)

        root.addWidget(fx_card)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_settings)

        # Eski VLC'de (band_count=0) arayüzü düzgün gizle, patlamasın
        self.eq_band_count = band_count
        if band_count == 0:
            preset_row.setVisible(False)
            bands_row.setVisible(False)
            root.addWidget(QLabel("Ekolayzer bu VLC sürümünde kullanılamıyor."))

    def _build_eq(self):
        """Kayıtlı ayarlardan (ön yükseltme + bantlar) ekolayzer nesnesi kurar.
        Eskiden kapatıp tekrar açınca ya da kapalıyken kaydırıcı oynatınca düz /
        eksik bantlı bir nesne uygulanıyor, kaydırıcılar ile ses uyuşmuyordu."""
        eq = vlc.AudioEqualizer()
        try:
            eq.set_preamp(float(self.settings.get("equalizer_preamp", 0.0)))
        except Exception:
            pass
        bands = self.settings.get("equalizer_bands") or []
        for i in range(min(len(bands), self.playback.eq_band_count)):
            try:
                eq.set_amp_at_index(float(bands[i]), i)
            except Exception:
                pass
        return eq

    # --- Etkinleştirme ---
    def _toggle_enabled(self):
        enabled = not self.settings.get("equalizer_enabled", False)
        self.settings["equalizer_enabled"] = bool(enabled)
        self.enable_check.setText("✓ Aktif" if enabled else "Aktif")
        if enabled:
            # apply_equalizer HER İKİ player'a da uygular — crossfade
            # takası sonrası ekolayzer kaybolmasın
            self.playback.apply_equalizer(self._build_eq())
        else:
            # VLC'de ekolayzeri "kaldırmanın" yolu düz (tüm bantlar 0) bir tane atamaktır
            self.playback.apply_equalizer(vlc.AudioEqualizer())
        self._save_timer.start(400)

    # --- Hazır ayarlar ---
    def _on_preset_selected(self, index: int):
        if self.eq_band_count == 0:
            return
        preset_idx = self.preset_combo.itemData(index)
        if preset_idx is None:
            return
        try:
            # ÖNEMLİ: vlc.AudioEqualizer(preset_idx) KULLANMA — bu python-vlc
            # sürümünde preset index'ini gerçekten libvlc_audio_equalizer_
            # new_from_preset() ile oluşturmuyor, index'i doğrudan (geçersiz)
            # bir bellek adresi gibi ele alıyor ve ardından herhangi bir
            # get_/set_ çağrısında "access violation" ile çöküyor.
            # Doğrusu, düşük seviye fonksiyonu doğrudan çağırmak:
            eq = vlc.libvlc_audio_equalizer_new_from_preset(int(preset_idx))
        except Exception:
            return
        if eq is None:
            # libvlc geçersiz/desteklenmeyen bir preset index'i için None döner
            log.warning("Ekolayzer preset'i oluşturulamadı: index=%s", preset_idx)
            return
        self.settings["equalizer_preamp"] = eq.get_preamp()
        bands = [eq.get_amp_at_index(i) for i in range(self.playback.eq_band_count)]
        self.settings["equalizer_bands"] = bands
        self.band_values = bands
        self._sliders_updating = True
        for i, s in enumerate(self.band_sliders):
            s.setValue(int(bands[i]))
        self._sliders_updating = False
        # Orijinal davranış: ekolayzer kapalıysa player'a dokunma
        if self.settings.get("equalizer_enabled"):
            self.playback.apply_equalizer(eq)
        self._save_timer.start(400)

    def _apply_flat(self):
        if self.eq_band_count == 0:
            return
        self.settings["equalizer_preamp"] = 0.0
        self.settings["equalizer_bands"] = [0.0] * self.playback.eq_band_count
        if self.settings.get("equalizer_enabled"):   # kapalıyken oynatıcılara dokunma
            self.playback.apply_equalizer(vlc.AudioEqualizer())
        self.band_values = list(self.settings["equalizer_bands"])
        self._sliders_updating = True
        for s in self.band_sliders:
            s.setValue(0)
        self._sliders_updating = False
        self._save_timer.start(400)

    # --- Bant kaydırma ---
    def _on_band_changed(self, band_index: int, value: int):
        if self._sliders_updating or self.eq_band_count == 0:
            return
        bands = self.settings.get("equalizer_bands", [0.0] * self.playback.eq_band_count)
        while len(bands) <= band_index:
            bands.append(0.0)
        bands[band_index] = float(value)
        self.settings["equalizer_bands"] = bands
        if self.settings.get("equalizer_enabled"):
            self.playback.apply_equalizer(self._build_eq())
        self._save_timer.start(400)

    # --- Kayıt (debounce'lu; kaydırıcı sürüklerken diske yazmamak için) ---
    def _on_crossfade_toggled(self, checked: bool):
        self.settings["crossfade_enabled"] = bool(checked)
        if hasattr(self.playback, "apply_crossfade_settings"):
            self.playback.apply_crossfade_settings(checked, self.cf_slider.value())
        self._save_timer.start(400)

    def _on_crossfade_seconds_changed(self, value: int):
        self.cf_label.setText(f"{value} sn")
        self.settings["crossfade_seconds"] = int(value)
        if hasattr(self.playback, "apply_crossfade_settings"):
            self.playback.apply_crossfade_settings(self.cf_check.isChecked(), value)
        self._save_timer.start(400)

    def _on_norm_toggled(self, checked: bool):
        self.settings["audio_normalization"] = bool(checked)
        if hasattr(self.playback, "apply_normalization"):
            self.playback.apply_normalization(checked)
        self._save_timer.start(400)

    def _on_vocal_toggled(self, checked: bool):
        self.settings["vocal_remover_enabled"] = bool(checked)
        if hasattr(self.playback, "set_vocal_remover"):
            self.playback.set_vocal_remover(checked)
        self._save_timer.start(400)

    def _sync_vocal_check(self, enabled: bool):
        if self.vocal_check.isChecked() != enabled:
            self.vocal_check.blockSignals(True)
            self.vocal_check.setChecked(enabled)
            self.vocal_check.blockSignals(False)

    def _flush_settings(self):
        self.save_fn()

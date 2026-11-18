from __future__ import annotations

import os
import threading

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import AppPaths, DEFAULT_THEME_KEY, THEMES
from mustiefly_qt.helpers.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, apply_language, translate_widget
from mustiefly_qt.helpers.updates import installed_version, run_update, update_available
from mustiefly_qt.helpers import ytdlp_runtime
from mustiefly_qt.helpers.logging_setup import get_logger
from mustiefly_qt.widgets.player_icons import icon as vicon, icon_pixmap



log = get_logger(__name__)
def _offline_stats(store) -> tuple[int, int]:
    """(çevrimdışı şarkı sayısı, toplam bayt)"""
    total, count = 0, 0
    if store is None:
        return count, total
    for songs in store.playlists.values():
        for s in songs:
            p = s.get("cached_path")
            if p and os.path.exists(p):
                try:
                    total += os.path.getsize(p)
                    count += 1
                except OSError:
                    pass
    return count, total


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _dir_size(path: str) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isfile(p):
                total += os.path.getsize(p)
        except OSError:
            pass
    return total


def _dir_sizes(paths: AppPaths, store) -> tuple[int, int, int]:
    """(thumbnail önbelleği, kapaklar, otomatik yedekler) — bayt."""
    thumb = covers = backups = 0
    try:
        thumb = _dir_size(os.path.join(paths.cache_dir, "thumbnails"))
        covers = _dir_size(paths.covers_dir)
        backups = _dir_size(os.path.join(os.path.dirname(paths.playlist_file), "backups"))
    except Exception:
        pass
    return thumb, covers, backups


class _ToggleSwitch(QCheckBox):
    """Modern animasyonlu pill toggle switch (QCheckBox uyumlu)."""

    def __init__(self, accent: str = "#a980f9", parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._thumb_pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"thumbPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, val: float):
        self._thumb_pos = val
        self.update()

    thumbPos = Property(float, _get_thumb_pos, _set_thumb_pos)

    def setChecked(self, checked: bool):  # noqa: N802
        super().setChecked(checked)
        self._thumb_pos = 1.0 if checked else 0.0
        self.update()

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def hitButton(self, pos):  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        radius = h / 2.0
        if self.isChecked():
            track_color = QColor(self._accent)
        else:
            track_color = QColor(255, 255, 255, 48 if self.underMouse() else 30)

        p.setPen(Qt.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        margin = 3.0
        thumb_d = h - 2 * margin
        x = margin + (w - thumb_d - 2 * margin) * self._thumb_pos

        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, margin, thumb_d, thumb_d))
        p.end()


class SettingsView(QWidget):
    """Ayarlar artık ayrı bir pencere/diyalog DEĞİL — ana uygulamanın içerik
    alanına gömülü bir sayfa. Sol üstteki "Geri" butonu (ya da alttaki
    "İptal") önceki görünüme döner; "Kaydet" ayarları yazıp aynı şekilde
    geri döner.
    """

    # Arka plan işlemlerinden (thread) GUI'ye durum taşıyan sinyaller
    updateStatus = Signal(str)
    updateDone = Signal(bool, str)
    spotifyStatus = Signal(str)
    spotifyDone = Signal(bool, str)

    # Kaydet / geri dön — MainWindow bu sinyallere göre view_stack'i değiştirir
    saved = Signal()
    backRequested = Signal()
    diagnosticsRequested = Signal()

    # (anahtar, vektör_ikon, başlık)
    CATEGORIES = (
        ("general", "sparkle", "Görünüm"),
        ("playback", "play", "Oynatma"),
        ("storage", "archive", "Depolama"),
        ("integrations", "radio", "Entegrasyonlar"),
        ("updates", "download", "Güncellemeler"),
    )

    def __init__(self, paths: AppPaths, settings: dict, parent=None, store=None,
                 thumbnails=None):
        super().__init__(parent)
        self.paths = paths
        self.settings = settings
        self.store = store
        self._thumb_service = thumbnails
        self._theme = THEMES.get(settings.get("theme"), THEMES[DEFAULT_THEME_KEY])
        self._searchable_rows: list[tuple[str, str, QWidget]] = []  # (cat_key, text_lower, row_widget)
        self._active_build_cat = "general"

        self.setObjectName("SettingsView")
        self.setStyleSheet(f"""
            QWidget#SettingsView {{ background: {self._theme.bg_main}; }}
            QWidget#SettingsView QLabel#SettingsRowTitle {{
                font-weight: 600; font-size: 13px; color: #FFFFFF;
            }}
            QWidget#SettingsView QWidget#SettingsHeader {{
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
                background: rgba(255, 255, 255, 0.015);
            }}
            QWidget#SettingsView QWidget#SettingsFooter {{
                border-top: 1px solid rgba(255, 255, 255, 0.06);
                background: rgba(255, 255, 255, 0.015);
            }}
            QWidget#SettingsView QWidget#SettingsNav {{
                border-right: 1px solid rgba(255, 255, 255, 0.06);
                background: rgba(0, 0, 0, 0.14);
            }}
            QWidget#SettingsView QWidget#Card {{
                background: rgba(255, 255, 255, 0.032);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 16px;
            }}
            QWidget#SettingsView QLineEdit#SettingsSearch {{
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 10px;
                padding: 6px 12px;
                color: #FFFFFF;
                font-size: 12px;
            }}
            QWidget#SettingsView QLineEdit#SettingsSearch:focus {{
                border-color: {self._theme.accent};
                background: rgba(255, 255, 255, 0.08);
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Üst başlık: Geri butonu + Vektör Başlık + Ayarlar Arama ---
        header = QWidget()
        header.setObjectName("SettingsHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(24, 16, 24, 16)
        h.setSpacing(14)

        back_btn = QPushButton("←")
        back_btn.setObjectName("IconSquare")
        back_btn.setToolTip("Geri dön")
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.clicked.connect(self.backRequested.emit)
        h.addWidget(back_btn)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(26, 26)
        icon_lbl.setAlignment(Qt.AlignCenter)
        pm = icon_pixmap("settings", 20, self._theme.accent)
        if pm is not None:
            icon_lbl.setPixmap(pm)
        h.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("Ayarlar")
        title.setObjectName("BrandTitle")
        title_col.addWidget(title)
        sub = QLabel("Görünüm, ses motoru, önbellek ve entegrasyon tercihlerini yönet")
        sub.setObjectName("Muted")
        sub.setStyleSheet("font-size: 11px;")
        title_col.addWidget(sub)
        h.addLayout(title_col)

        h.addStretch(1)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("SettingsSearch")
        self.search_edit.setPlaceholderText("🔍  Ayarlarda ara… (örn: tema, vokal, crossfade)")
        self.search_edit.setFixedWidth(280)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        h.addWidget(self.search_edit)

        root.addWidget(header)

        # --- Gövde: sol kategori menüsü + sağ sayfa alanı -------------
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root.addWidget(body, stretch=1)

        nav = QWidget()
        nav.setObjectName("SettingsNav")
        nav.setFixedWidth(210)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(14, 18, 14, 14)
        nav_layout.setSpacing(6)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_icons: dict[str, str] = {}
        for key, ic_name, label in self.CATEGORIES:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavButton")
            btn.setIcon(vicon(ic_name, 16, "#b7b2cf"))
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select_category(k))
            nav_layout.addWidget(btn)
            self._nav_buttons[key] = btn
            self._nav_icons[key] = ic_name
        nav_layout.addStretch(1)
        body_layout.addWidget(nav)

        self.stack = QStackedWidget()
        body_layout.addWidget(self.stack, stretch=1)

        self._page_index = {}
        pages = (
            ("general", self._build_general_page),
            ("playback", self._build_playback_page),
            ("storage", self._build_storage_page),
            ("integrations", self._build_integrations_page),
            ("updates", self._build_updates_page),
        )
        for i, (key, builder) in enumerate(pages):
            self._active_build_cat = key
            self.stack.addWidget(builder())
            self._page_index[key] = i

        # --- Alt bar: kaydet / iptal ------------------------------------
        footer = QWidget()
        footer.setObjectName("SettingsFooter")
        f = QHBoxLayout(footer)
        f.setContentsMargins(24, 14, 24, 16)
        f.setSpacing(10)
        note = QLabel("Renk teması anında uygulanır; diğer ayarlar için Kaydet'e bas.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        f.addWidget(note, stretch=1)
        cancel_btn = QPushButton("İptal")
        cancel_btn.setObjectName("Secondary")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.backRequested.emit)
        f.addWidget(cancel_btn)
        save_btn = QPushButton("Kaydet")
        save_btn.setObjectName("Primary")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        f.addWidget(save_btn)
        root.addWidget(footer)

        self.updateStatus.connect(self.ytdlp_label.setText)
        self.updateDone.connect(self._on_update_done)
        self.spotifyStatus.connect(self.spotify_status_label.setText)
        self.spotifyDone.connect(self._on_spotify_done)

        self._select_category("general")

    def _toggle(self, checked: bool = False) -> _ToggleSwitch:
        sw = _ToggleSwitch(accent=self._theme.accent)
        sw.setChecked(bool(checked))
        return sw

    # ------------------------------------------------------------------
    # Küçük yardımcı yapı taşları (kart / satır / sayfa)
    # ------------------------------------------------------------------
    def _card(self, title: str) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        card.setMaximumWidth(820)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("SectionHeader")
        lbl.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 0.8px;")
        lay.addWidget(lbl)
        lay.addSpacing(6)
        return card

    def _row(self, title: str, control: QWidget, description: str = "") -> QWidget:
        """Başlık + (opsiyonel) açıklama solda, kontrol (toggle/combo/vb.) sağda."""
        row = QWidget()
        row.setObjectName("SettingsRow")
        row.setStyleSheet(
            "QWidget#SettingsRow { border-bottom: 1px solid rgba(255, 255, 255, 0.045); border-radius: 6px; }"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(16)
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("SettingsRowTitle")
        text_box.addWidget(t)
        if description:
            d = QLabel(description)
            d.setObjectName("Muted")
            d.setWordWrap(True)
            d.setStyleSheet("font-size: 11px;")
            text_box.addWidget(d)
        lay.addLayout(text_box, stretch=1)
        lay.addWidget(control, alignment=Qt.AlignVCenter)
        self._searchable_rows.append((self._active_build_cat, (title + " " + description).lower(), row))
        return row

    def _hbox(self, *widgets: QWidget, spacing: int = 8) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        for x in widgets:
            lay.addWidget(x)
        return w

    def _scroll_page(self, *widgets: QWidget) -> QWidget:
        container = QWidget()
        container.setObjectName("SettingsPageBody")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(16)
        for w in widgets:
            lay.addWidget(w)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        bg = self._theme.bg_main
        scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; border: none; }}")
        scroll.setWidget(container)
        scroll.viewport().setStyleSheet(f"background: {bg};")
        container.setStyleSheet(f"#SettingsPageBody {{ background: {bg}; }}")
        return scroll

    def _select_category(self, key: str):
        for k, btn in self._nav_buttons.items():
            active = (k == key)
            btn.setProperty("active", "true" if active else "false")
            ic_name = self._nav_icons.get(k)
            if ic_name:
                btn.setIcon(vicon(ic_name, 16, "#ffffff" if active else "#b7b2cf"))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.stack.setCurrentIndex(self._page_index[key])

    def _on_search_changed(self, text: str):
        query = text.strip().lower()
        first_match_cat = None
        for cat_key, searchable_text, row_widget in self._searchable_rows:
            if not query:
                row_widget.setStyleSheet(
                    "QWidget#SettingsRow { border-bottom: 1px solid rgba(255, 255, 255, 0.045); border-radius: 6px; }"
                )
            elif query in searchable_text:
                if first_match_cat is None:
                    first_match_cat = cat_key
                row_widget.setStyleSheet(
                    f"QWidget#SettingsRow {{ background: rgba(169, 128, 249, 0.14); "
                    f"border-left: 3px solid {self._theme.accent}; border-radius: 8px; }}"
                )
            else:
                row_widget.setStyleSheet(
                    "QWidget#SettingsRow { border-bottom: 1px solid rgba(255, 255, 255, 0.045); border-radius: 6px; }"
                )
        if first_match_cat is not None:
            self._select_category(first_match_cat)

    # ------------------------------------------------------------------
    # Sayfalar
    # ------------------------------------------------------------------
    def _build_general_page(self) -> QWidget:
        theme_card = self._card("Tema")
        self.theme_combo = QComboBox()
        for key, theme in THEMES.items():
            self.theme_combo.addItem(theme.name, key)
        idx = self.theme_combo.findData(self.settings.get("theme"))
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_card.layout().addWidget(self._row(
            "Renk teması", self.theme_combo, "Seçim anında uygulanır."))

        self.dynamic_check = self._toggle()
        self.dynamic_check.setChecked(self.settings.get("dynamic_theme", True))
        theme_card.layout().addWidget(self._row(
            "Dinamik vurgu rengi", self.dynamic_check,
            "Çalan şarkının kapak resminden otomatik vurgu rengi çıkarır."))

        self.language_combo = QComboBox()
        for code, label in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(label, code)
        lang_idx = self.language_combo.findData(self.settings.get("language", DEFAULT_LANGUAGE))
        if lang_idx >= 0:
            self.language_combo.setCurrentIndex(lang_idx)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        theme_card.layout().addWidget(self._row(
            "Arayüz dili", self.language_combo,
            "Seçim anında tüm arayüze uygulanır."))

        general_card = self._card("Genel Davranış")
        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(20, 500)
        self.page_size_spin.setValue(self.settings.get("page_size", 60))
        general_card.layout().addWidget(self._row(
            "Sayfa boyutu", self.page_size_spin,
            "Kütüphane listelerinde bir sayfada gösterilecek şarkı sayısı."))

        self.restore_check = self._toggle()
        self.restore_check.setChecked(self.settings.get("restore_session", True))
        general_card.layout().addWidget(self._row(
            "Son oturumu geri yükle", self.restore_check,
            "Açılışta kaldığın liste ve şarkıyı otomatik yükler."))

        self.tray_check = self._toggle()
        self.tray_check.setChecked(self.settings.get("minimize_to_tray", False))
        general_card.layout().addWidget(self._row(
            "Sistem tepsisine küçült", self.tray_check,
            "Kapatınca ya da küçültünce arka planda çalmaya devam eder."))

        self.auto_update_check = self._toggle()
        self.auto_update_check.setChecked(self.settings.get("auto_update_check", True))
        general_card.layout().addWidget(self._row(
            "Güncellemeleri otomatik denetle", self.auto_update_check,
            "Açılışta GitHub'dan yeni Audifly sürümü var mı diye bakar (yalnızca sürüm bilgisi sorulur). "
            "Elle denetlemek için: Araçlar → Güncellemeleri Denetle."))

        return self._scroll_page(theme_card, general_card)

    def _build_playback_page(self) -> QWidget:
        audio_card = self._card("Ses")
        self.normalize_check = self._toggle()
        self.normalize_check.setChecked(self.settings.get("audio_normalization", False))
        audio_card.layout().addWidget(self._row(
            "Ses seviyesini dengele", self.normalize_check,
            "Farklı şarkılar arasındaki ses seviyesi farkını otomatik dengeler (normvol + ReplayGain)."))

        self.crossfade_check = self._toggle()
        self.crossfade_check.setChecked(self.settings.get("crossfade_enabled", False))
        self.crossfade_spin = QSpinBox()
        self.crossfade_spin.setRange(1, 12)
        self.crossfade_spin.setSuffix(" sn")
        self.crossfade_spin.setValue(int(self.settings.get("crossfade_seconds", 3)))
        audio_card.layout().addWidget(self._row(
            "Crossfade", self._hbox(self.crossfade_check, self.crossfade_spin),
            "Şarkılar arası kesintisiz, yumuşak ses geçişi ve geçiş süresi (Equal-Power)."))

        self.vocal_remover_check = self._toggle()
        self.vocal_remover_check.setChecked(self.settings.get("vocal_remover_enabled", False))
        audio_card.layout().addWidget(self._row(
            "Vokal Ayırma / Enstrümantal Mod", self.vocal_remover_check,
            "Şarkıların merkez frekanslarındaki vokal sesini kısarak enstrümantal karaoke modu sağlar (Kısayol: V)."))

        self.autoplay_check = self._toggle()
        self.autoplay_check.setChecked(self.settings.get("autoplay_enabled", True))
        audio_card.layout().addWidget(self._row(
            "Sonsuz Çalma (Autoplay)", self.autoplay_check,
            "Çalma listesi bittiğinde benzer şarkıları otomatik bularak kesintisiz çalmaya devam eder."))

        controls_card = self._card("Denetimler")
        self.media_keys_check = self._toggle()
        self.media_keys_check.setChecked(self.settings.get("global_media_keys", False))
        controls_card.layout().addWidget(self._row(
            "Global medya tuşları", self.media_keys_check,
            "Play/duraklat, sonraki ve önceki tuşlarını sistem genelinde dinler "
            "('keyboard' paketi gerekir)."))

        try:
            from mustiefly_qt.services.smtc import SMTC_AVAILABLE
        except Exception:
            SMTC_AVAILABLE = False
        self.smtc_check = self._toggle()
        self.smtc_check.setChecked(self.settings.get("smtc_enabled", True))
        if not SMTC_AVAILABLE:
            self.smtc_check.setToolTip(
                "'winsdk' (Python 3.9-3.12) ya da winrt paketleri gerekli:\n"
                "pip install winrt-Windows.Foundation winrt-Windows.Media "
                "winrt-Windows.Storage.Streams winrt-Windows.Media.Interop\n"
                "Kurulu değilse özellik devre dışı kalır.")
        controls_card.layout().addWidget(self._row(
            "Windows medya denetimleri (SMTC)", self.smtc_check,
            "Ses açılır penceresinden oynatmayı kontrol etmeni sağlar."))

        hud_card = self._card("Ekran Üstü Bildirim (HUD / Gaming Overlay)")
        self.hud_check = self._toggle()
        self.hud_check.setChecked(self.settings.get("hud_overlay_enabled", True))
        hud_card.layout().addWidget(self._row(
            "Ekran Üstü HUD'ı Etkinleştir", self.hud_check,
            "Şarkı değiştiğinde oyunlardan ve pencerelerden odak çalmayan zarif bir mini bildirim gösterir."))

        self.hud_bg_only_check = self._toggle()
        self.hud_bg_only_check.setChecked(self.settings.get("hud_overlay_only_background", True))
        hud_card.layout().addWidget(self._row(
            "Yalnızca Arka Plandayken Göster", self.hud_bg_only_check,
            "Uygulama aktif ve ön plandayken HUD bildirimini gizler (sadece oyundayken/arka plandayken gösterir)."))

        self.hud_pos_combo = QComboBox()
        self.hud_pos_combo.addItem("Sağ Üst", "top-right")
        self.hud_pos_combo.addItem("Sağ Alt", "bottom-right")
        self.hud_pos_combo.addItem("Üst Orta", "top-center")
        self.hud_pos_combo.addItem("Sol Üst", "top-left")
        cur_pos = self.settings.get("hud_overlay_position", "top-right")
        idx = self.hud_pos_combo.findData(cur_pos)
        if idx >= 0:
            self.hud_pos_combo.setCurrentIndex(idx)
        hud_card.layout().addWidget(self._row(
            "HUD Konumu", self.hud_pos_combo,
            "Ekran üstü bildirimin görüntüleneceği ekran köşesi."))

        self.hud_dur_spin = QSpinBox()
        self.hud_dur_spin.setRange(2, 10)
        self.hud_dur_spin.setSuffix(" sn")
        self.hud_dur_spin.setValue(int(self.settings.get("hud_overlay_duration", 4)))
        hud_card.layout().addWidget(self._row(
            "Görünme Süresi", self.hud_dur_spin,
            "Bildirimin ekranda kalma süresi."))

        viz_card = self._card("Canlı Müzik Görselleştirici & Neon Spektrum")
        self.visualizer_check = self._toggle()
        self.visualizer_check.setChecked(self.settings.get("visualizer_enabled", True))
        viz_card.layout().addWidget(self._row(
            "Görselleştiriciyi Etkinleştir", self.visualizer_check,
            "Şu An Çalıyor panelinde, oynatıcı çubuğunda ve Tam Ekran Karaoke'de canlı neon spektrum gösterir."))

        self.visualizer_mode_combo = QComboBox()
        self.visualizer_mode_combo.addItem("📊 Neon Spektrum Barları", "bars")
        self.visualizer_mode_combo.addItem("🌊 Akışkan Neon Dalga", "wave")
        self.visualizer_mode_combo.addItem("💠 Simetrik Spektrum", "mirror")
        self.visualizer_mode_combo.addItem("⭕ Dairesel Radyal Nabız", "circular")
        cur_vmode = self.settings.get("visualizer_mode", "bars")
        v_idx = self.visualizer_mode_combo.findData(cur_vmode)
        if v_idx >= 0:
            self.visualizer_mode_combo.setCurrentIndex(v_idx)
        viz_card.layout().addWidget(self._row(
            "Görselleştirici Stili", self.visualizer_mode_combo,
            "Spektrumun çizim stili (Kısayol: G veya spektrum üzerine sol tık)."))

        self.visualizer_palette_combo = QComboBox()
        self.visualizer_palette_combo.addItem("🎨 Dinamik (Kapak / Tema Rengi)", "dynamic")
        self.visualizer_palette_combo.addItem("🌆 Cyberpunk (Pembe & Camgöbeği)", "cyberpunk")
        self.visualizer_palette_combo.addItem("🌌 Aurora (Yeşil & Mavi)", "aurora")
        self.visualizer_palette_combo.addItem("🔥 Ateş & Kehribar", "fire")
        self.visualizer_palette_combo.addItem("🪐 Galaksi (Mor & Mavi)", "galaxy")
        cur_vpal = self.settings.get("visualizer_palette", "dynamic")
        p_idx = self.visualizer_palette_combo.findData(cur_vpal)
        if p_idx >= 0:
            self.visualizer_palette_combo.setCurrentIndex(p_idx)
        viz_card.layout().addWidget(self._row(
            "Neon Renk Paleti", self.visualizer_palette_combo,
            "Spektrum dalgalarının neon renk geçişi (Spektrum üzerine sağ tıklayarak da değiştirebilirsin)."))

        return self._scroll_page(audio_card, viz_card, controls_card, hud_card)

    def _build_storage_page(self) -> QWidget:
        cache_card = self._card("Önbellek Yönetimi")

        count, total = _offline_stats(self.store)
        self.storage_label = QLabel(
            f"Çevrimdışı müzikler: {count} şarkı • {_human_size(total)}")
        self.storage_label.setObjectName("Muted")
        clear_btn = QPushButton("🧹  Çevrimdışı müzikleri temizle")
        clear_btn.setObjectName("Secondary")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_offline_files)
        cache_card.layout().addWidget(self.storage_label)
        cache_card.layout().addWidget(clear_btn)
        cache_card.layout().addSpacing(10)

        thumb_size, covers_size, backups_size = _dir_sizes(self.paths, self.store)
        self.thumb_label = QLabel(f"Thumbnail önbelleği: {_human_size(thumb_size)}")
        self.thumb_label.setObjectName("Muted")
        self.clear_thumb_btn = QPushButton("🧹  Thumbnail önbelleğini temizle")
        self.clear_thumb_btn.setObjectName("Secondary")
        self.clear_thumb_btn.setCursor(Qt.PointingHandCursor)
        self.clear_thumb_btn.clicked.connect(self._clear_thumbnail_cache)
        cache_card.layout().addWidget(self.thumb_label)
        cache_card.layout().addWidget(self.clear_thumb_btn)
        cache_card.layout().addSpacing(10)

        self.other_label = QLabel(
            f"Playlist kapakları: {_human_size(covers_size)} • "
            f"Otomatik yedekler: {_human_size(backups_size)}")
        self.other_label.setObjectName("Muted")
        self.other_label.setWordWrap(True)
        cache_card.layout().addWidget(self.other_label)

        backup_card = self._card("Yedekleme")
        self.backup_check = self._toggle()
        self.backup_check.setChecked(self.settings.get("backup_enabled", True))
        backup_card.layout().addWidget(self._row(
            "Otomatik yedekleme", self.backup_check,
            "Bozuk dosyaya karşı playlist verisinin 3 kopyasını tutar."))

        return self._scroll_page(cache_card, backup_card)

    def _build_integrations_page(self) -> QWidget:
        spotify_card = self._card("Spotify İçe Aktarma")
        form = QFormLayout()
        form.setSpacing(10)
        self.spotify_id_edit = QLineEdit(self.settings.get("spotify_client_id", ""))
        form.addRow("Client ID:", self.spotify_id_edit)
        self.spotify_secret_edit = QLineEdit(self.settings.get("spotify_client_secret", ""))
        self.spotify_secret_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Client Secret (isteğe bağlı, PKCE ile gerekmez):", self.spotify_secret_edit)
        spotify_card.layout().addLayout(form)

        connected = bool(self.settings.get("spotify_refresh_token"))
        self.spotify_status_label = QLabel("🟢 Bağlı" if connected else "⚪ Bağlı değil")
        self.spotify_connect_btn = QPushButton(
            "🔗 Bağlan" if not connected else "🔄 Yeniden Bağlan")
        self.spotify_connect_btn.setObjectName("Secondary")
        self.spotify_connect_btn.setCursor(Qt.PointingHandCursor)
        self.spotify_connect_btn.clicked.connect(self._spotify_connect)
        self.spotify_disconnect_btn = QPushButton("⛔ Bağlantıyı Kes")
        self.spotify_disconnect_btn.setObjectName("Secondary")
        self.spotify_disconnect_btn.setCursor(Qt.PointingHandCursor)
        self.spotify_disconnect_btn.setEnabled(connected)
        self.spotify_disconnect_btn.clicked.connect(self._spotify_disconnect)
        spotify_card.layout().addSpacing(6)
        spotify_card.layout().addWidget(self._row(
            "Hesap durumu",
            self._hbox(self.spotify_connect_btn, self.spotify_disconnect_btn)))
        spotify_card.layout().addWidget(self.spotify_status_label)
        note = QLabel(
            "Client ID/Secret değerlerini developer.spotify.com/dashboard "
            "adresinden ücretsiz oluşturabilirsin.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        spotify_card.layout().addSpacing(6)
        spotify_card.layout().addWidget(note)

        discord_card = self._card("Discord")
        discord_form = QFormLayout()
        self.discord_edit = QLineEdit(self.settings.get("discord_client_id", ""))
        discord_form.addRow("Client ID:", self.discord_edit)
        discord_card.layout().addLayout(discord_form)

        return self._scroll_page(spotify_card, discord_card)

    def _build_updates_page(self) -> QWidget:
        ytdlp_card = self._card("yt-dlp (YouTube çıkarımı)")
        self.ytdlp_label = QLabel(f"Kurulu sürüm: {installed_version() or 'bulunamadı'}")
        self.ytdlp_label.setObjectName("Muted")
        self.ytdlp_label.setWordWrap(True)
        self.ytdlp_btn = QPushButton("🔄  Güncellemeleri Kontrol Et ve Güncelle")
        self.ytdlp_btn.setObjectName("Secondary")
        self.ytdlp_btn.setCursor(Qt.PointingHandCursor)
        self.ytdlp_btn.clicked.connect(self._check_ytdlp_update)

        self.ytdlp_reset_btn = QPushButton("↩  Paketteki sürüme sıfırla")
        self.ytdlp_reset_btn.setObjectName("Secondary")
        self.ytdlp_reset_btn.setCursor(Qt.PointingHandCursor)
        self.ytdlp_reset_btn.clicked.connect(self._reset_ytdlp)
        self.ytdlp_reset_btn.setVisible(bool(
            ytdlp_runtime.ACTIVE_VERSION or ytdlp_runtime.pending_version()))

        self.auto_ytdlp_check = self._toggle()
        self.auto_ytdlp_check.setChecked(self.settings.get("auto_ytdlp_update", True))

        ytdlp_card.layout().addWidget(self.ytdlp_label)
        ytdlp_card.layout().addSpacing(6)
        ytdlp_card.layout().addWidget(self._hbox(self.ytdlp_btn, self.ytdlp_reset_btn))
        ytdlp_card.layout().addSpacing(6)
        ytdlp_card.layout().addWidget(self._row(
            "yt-dlp'yi otomatik güncelle", self.auto_ytdlp_check,
            "YouTube çıkarımı değiştiğinde ya da açılışta yeni yt-dlp sürümünü otomatik indirir (kurulum gerektirmez)."))

        diag_card = self._card("Sorun Bildirme ve Tanılama")
        diag_desc = QLabel(
            "Bir şarkı çalmıyorsa ya da beklenmeyen bir hata görüyorsan tanılama "
            "raporunu tek tıkla kopyalayıp paylaşabilirsin (kişisel veri içermez).")
        diag_desc.setObjectName("Muted")
        diag_desc.setWordWrap(True)
        self.diagnostics_btn = QPushButton("🩺  Sorun Bildir / Tanılama Raporunu Aç")
        self.diagnostics_btn.setObjectName("Secondary")
        self.diagnostics_btn.setCursor(Qt.PointingHandCursor)
        self.diagnostics_btn.clicked.connect(self._open_diagnostics)
        diag_card.layout().addWidget(diag_desc)
        diag_card.layout().addSpacing(6)
        diag_card.layout().addWidget(self.diagnostics_btn)

        return self._scroll_page(ytdlp_card, diag_card)

    # ------------------------------------------------------------------
    # Sayfa yeniden açıldığında (aynı örnek tekrar kullanıldığı için)
    # gösterilen bilgileri tazeler.
    # ------------------------------------------------------------------
    def refresh_dynamic(self):
        idx = self.theme_combo.findData(self.settings.get("theme"))
        if idx >= 0 and idx != self.theme_combo.currentIndex():
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

        count, total = _offline_stats(self.store)
        self.storage_label.setText(
            f"Çevrimdışı müzikler: {count} şarkı • {_human_size(total)}")
        thumb_size, covers_size, backups_size = _dir_sizes(self.paths, self.store)
        self.thumb_label.setText(f"Thumbnail önbelleği: {_human_size(thumb_size)}")
        self.other_label.setText(
            f"Playlist kapakları: {_human_size(covers_size)} • "
            f"Otomatik yedekler: {_human_size(backups_size)}")

        connected = bool(self.settings.get("spotify_refresh_token"))
        self.spotify_status_label.setText("🟢 Bağlı" if connected else "⚪ Bağlı değil")
        self.spotify_connect_btn.setText("🔄 Yeniden Bağlan" if connected else "🔗 Bağlan")
        self.spotify_disconnect_btn.setEnabled(connected)

        self.ytdlp_label.setText(f"Kurulu sürüm: {installed_version() or 'bulunamadı'}")
        self.ytdlp_reset_btn.setVisible(bool(
            ytdlp_runtime.ACTIVE_VERSION or ytdlp_runtime.pending_version()))
        lang_idx = self.language_combo.findData(self.settings.get("language", DEFAULT_LANGUAGE))
        if lang_idx >= 0 and lang_idx != self.language_combo.currentIndex():
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(lang_idx)
            self.language_combo.blockSignals(False)
        self.vocal_remover_check.setChecked(bool(self.settings.get("vocal_remover_enabled", False)))
        self.visualizer_check.setChecked(bool(self.settings.get("visualizer_enabled", True)))
        v_idx = self.visualizer_mode_combo.findData(self.settings.get("visualizer_mode", "bars"))
        if v_idx >= 0:
            self.visualizer_mode_combo.setCurrentIndex(v_idx)
        p_idx = self.visualizer_palette_combo.findData(self.settings.get("visualizer_palette", "dynamic"))
        if p_idx >= 0:
            self.visualizer_palette_combo.setCurrentIndex(p_idx)
        translate_widget(self)

    # --- Tema & dil anında önizleme -----------------------------------
    def _on_theme_changed(self, _index: int):
        key = self.theme_combo.currentData()
        if not key:
            return
        self.settings["theme"] = key
        self._theme = THEMES.get(key, self._theme)
        parent = self.window()
        if parent is not None and hasattr(parent, "_reset_accent"):
            parent._reset_accent()

    def _on_language_changed(self, _index: int):
        lang = self.language_combo.currentData()
        if not lang:
            return
        self.settings["language"] = lang
        apply_language(lang)
        translate_widget(self)

    def _reset_ytdlp(self):
        if ytdlp_runtime.reset_to_bundled():
            self.ytdlp_reset_btn.setVisible(False)
            self.ytdlp_label.setText(
                f"↩ Paketteki sürüme ({ytdlp_runtime.bundled_version() or '?'}) dönülecek — "
                "uygulamayı yeniden başlat.")

    def _open_diagnostics(self):
        self.diagnosticsRequested.emit()
        parent = self.window()
        if parent is None or not hasattr(parent, "open_diagnostics_dialog"):
            from mustiefly_qt.views.diagnostics_dialog import DiagnosticsDialog
            dlg = DiagnosticsDialog(getattr(self.paths, "logs_dir", None), parent=self)
            dlg.exec()
            dlg.deleteLater()

    # --- yt-dlp güncelleme ---
    def _check_ytdlp_update(self):
        self.ytdlp_btn.setEnabled(False)
        self.ytdlp_label.setText("🌐 PyPI kontrol ediliyor…")

        def worker():
            try:
                self._update_worker_body()
            except RuntimeError:
                pass   # pencere kapatıldı: sinyal alıcısı artık yok
            except Exception as e:   # beklenmeyen hata düğmeyi sonsuza dek kilitlemesin
                try:
                    self.updateDone.emit(False, f"❌ Güncelleme kontrolü başarısız: {e}")
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _update_worker_body(self):
        if True:
            has_new, inst, latest = update_available()
            if inst is None:
                self.updateDone.emit(False, "yt-dlp kurulu değil (pip install yt-dlp)")
                return
            if not latest:
                self.updateDone.emit(False, "PyPI'ye ulaşılamadı — internet bağlantısını kontrol et.")
                return
            if not has_new:
                self.updateDone.emit(True, f"✅ yt-dlp güncel ({inst})")
                return
            self.updateStatus.emit(f"⬇ {inst} → {latest} indiriliyor…")
            ok, output = run_update()
            new_ver = installed_version()
            if ok:
                self.updateDone.emit(
                    True, f"✅ yt-dlp {new_ver} olarak güncellendi.\n"
                          "Değişikliklerin tam uygulanması için uygulamayı yeniden başlat.")
            else:
                self.updateDone.emit(False, f"❌ Güncelleme başarısız:\n{output}")

    def _on_update_done(self, ok: bool, message: str):
        self.ytdlp_label.setText(message)
        self.ytdlp_btn.setEnabled(True)
        self.ytdlp_reset_btn.setVisible(bool(
            ytdlp_runtime.ACTIVE_VERSION or ytdlp_runtime.pending_version()))
        if not ok:
            QMessageBox.warning(self, "yt-dlp", message)

    # --- Spotify bağlan / bağlantıyı kes ---
    def _spotify_connect(self):
        client_id = self.spotify_id_edit.text().strip()
        client_secret = self.spotify_secret_edit.text().strip()
        if not client_id:
            QMessageBox.information(
                self, "Eksik Bilgi",
                "Önce Spotify Client ID gir (Client Secret gerekmez).\n"
                "https://developer.spotify.com/dashboard adresinden ücretsiz oluşturabilirsin.")
            return
        # Alanlara yazılan değerleri hemen ayarlara al (auth bunları kullanır)
        self.settings["spotify_client_id"] = client_id
        self.settings["spotify_client_secret"] = client_secret
        self.spotify_connect_btn.setEnabled(False)
        self.spotify_status_label.setText("🌐 Tarayıcıda giriş bekleniyor…")

        from mustiefly_qt.helpers.spotify_import import get_spotify_user_access_token

        def worker():
            try:
                get_spotify_user_access_token(
                    client_id, client_secret, self.settings, self._save_settings_file)
                self.spotifyDone.emit(True, "🟢 Bağlı")
            except Exception as e:
                self.spotifyDone.emit(False, f"⚪ Bağlanamadı: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_spotify_done(self, ok: bool, message: str):
        self.spotify_status_label.setText(message)
        self.spotify_connect_btn.setEnabled(True)
        self.spotify_disconnect_btn.setEnabled(
            bool(self.settings.get("spotify_refresh_token")))
        self.spotify_connect_btn.setText(
            "🔄 Yeniden Bağlan" if self.settings.get("spotify_refresh_token") else "🔗 Bağlan")
        if not ok:
            QMessageBox.warning(self, "Spotify", message)

    def _spotify_disconnect(self):
        confirm = QMessageBox.question(
            self, "Bağlantıyı Kes",
            "Spotify hesabı bağlantısı kesilsin mi?\n(Yeniden içe aktarma için tekrar giriş gerekir.)")
        if confirm != QMessageBox.Yes:
            return
        self.settings.pop("spotify_refresh_token", None)
        self._save_settings_file()
        self.spotify_status_label.setText("⚪ Bağlı değil")
        self.spotify_disconnect_btn.setEnabled(False)
        self.spotify_connect_btn.setText("🔗 Bağlan")

    def _clear_offline_files(self):
        if self.store is None:
            return
        confirm = QMessageBox.question(
            self, "Çevrimdışı Dosyaları Temizle",
            "İndirilen tüm müzik dosyaları diskten silinecek.\n"
            "Şarkılar listelerde kalır; tekrar çevrimdışı dinlemek için yeniden indirmen gerekir.\n"
            "(Hiçbir listede referansı kalmamış yetim dosyalar da süpürülür.)\n\n"
            "Devam edilsin mi?")
        if confirm != QMessageBox.Yes:
            return
        removed, freed = 0, 0
        # 1) Listelerde kayıtlı olanlar
        for songs in self.store.playlists.values():
            for s in songs:
                p = s.get("cached_path")
                if p and os.path.exists(p):
                    try:
                        freed += os.path.getsize(p)
                        os.remove(p)
                        removed += 1
                    except OSError as e:
                        log.error("%s %s", "Dosya silinemedi:", e)
                if p:
                    s.pop("cached_path", None)
        # 2) Öksüzler: cache kökünde durup hiçbir şarkının cached_path'i olmayan
        #    dosyalar (ör. indirme sürerken şarkı silindiyse). thumbnails/ alt
        #    klasörüne dokunulmaz.
        referenced = {
            s.get("cached_path")
            for songs in self.store.playlists.values() for s in songs}
        cache_dir = getattr(self.paths, "cache_dir", "")
        if cache_dir and os.path.isdir(cache_dir):
            for name in os.listdir(cache_dir):
                fp = os.path.join(cache_dir, name)
                if os.path.isfile(fp) and fp not in referenced:
                    try:
                        freed += os.path.getsize(fp)
                        os.remove(fp)
                        removed += 1
                    except OSError as e:
                        log.error("%s %s", "Öksüz dosya silinemedi:", e)
        self.store.save()
        self.store.playlistsChanged.emit()
        count, total = _offline_stats(self.store)
        self.storage_label.setText(
            f"Çevrimdışı müzikler: {count} şarkı • {_human_size(total)}")
        QMessageBox.information(
            self, "Temizlendi",
            f"{removed} dosya silindi ({_human_size(freed)} yer açıldı).")

    def _clear_thumbnail_cache(self):
        if self._thumb_service is None:
            return
        count, freed = self._thumb_service.clear_disk_cache()
        thumb_size, covers_size, backups_size = _dir_sizes(self.paths, self.store)
        self.thumb_label.setText(f"Thumbnail önbelleği: {_human_size(thumb_size)}")
        if count:
            QMessageBox.information(
                self, "Temizlendi",
                f"{count} thumbnail silindi ({_human_size(freed)} yer açıldı).\n"
                "Kapaklar gerektiğinde yeniden indirilir.")
        else:
            QMessageBox.information(self, "Boş", "Thumbnail önbelleği zaten boş.")

    def _save_settings_file(self):
        from mustiefly_qt.auth.service import save_settings_for
        save_settings_for(self.paths, self.settings)

    def _save(self):
        from mustiefly_qt.services.media_keys import KEYBOARD_AVAILABLE

        self.settings["theme"] = self.theme_combo.currentData()
        self.settings["language"] = self.language_combo.currentData() or DEFAULT_LANGUAGE
        self.settings["page_size"] = self.page_size_spin.value()
        self.settings["audio_normalization"] = self.normalize_check.isChecked()
        self.settings["global_media_keys"] = self.media_keys_check.isChecked()
        self.settings["minimize_to_tray"] = self.tray_check.isChecked()
        self.settings["backup_enabled"] = self.backup_check.isChecked()
        self.settings["dynamic_theme"] = self.dynamic_check.isChecked()
        self.settings["restore_session"] = self.restore_check.isChecked()
        self.settings["auto_update_check"] = self.auto_update_check.isChecked()
        self.settings["auto_ytdlp_update"] = self.auto_ytdlp_check.isChecked()
        self.settings["crossfade_enabled"] = self.crossfade_check.isChecked()
        self.settings["crossfade_seconds"] = self.crossfade_spin.value()
        self.settings["vocal_remover_enabled"] = self.vocal_remover_check.isChecked()
        self.settings["visualizer_enabled"] = self.visualizer_check.isChecked()
        self.settings["visualizer_mode"] = self.visualizer_mode_combo.currentData() or "bars"
        self.settings["visualizer_palette"] = self.visualizer_palette_combo.currentData() or "dynamic"
        self.settings["autoplay_enabled"] = self.autoplay_check.isChecked()
        self.settings["hud_overlay_enabled"] = self.hud_check.isChecked()
        self.settings["hud_overlay_only_background"] = self.hud_bg_only_check.isChecked()
        self.settings["hud_overlay_position"] = self.hud_pos_combo.currentData() or "top-right"
        self.settings["hud_overlay_duration"] = self.hud_dur_spin.value()
        self.settings["smtc_enabled"] = self.smtc_check.isChecked()
        self.settings["spotify_client_id"] = self.spotify_id_edit.text().strip()
        self.settings["spotify_client_secret"] = self.spotify_secret_edit.text().strip()
        self.settings["discord_client_id"] = self.discord_edit.text().strip()

        if self.settings["global_media_keys"] and not KEYBOARD_AVAILABLE:
            QMessageBox.warning(
                self, "Eksik Paket",
                "'keyboard' paketi kurulu değil.\nGlobal medya tuşları etkinleştirilemedi: "
                "pip install keyboard")

        self._save_settings_file()
        QMessageBox.information(
            self, "Kaydedildi",
            "Ayarlar kaydedildi. Tema ve vurgu rengi anında uygulanır; global medya "
            "tuşu değişikliği yeniden başlatınca tamamen etkinleşir.")
        self.saved.emit()

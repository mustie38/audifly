"""
Modern Spotlight & Komut Paleti (Command Palette) - Ctrl + K
Audifly genelinde hızlı komut çalıştırma, kütüphane şarkıları, sanatçılar,
çalma listeleri ve YouTube web aramasını tek bir floating spotlight arayüzünde birleştirir.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for, format_time
from mustiefly_qt.helpers.lyrics import clean_artist, parse_track_and_artist
from mustiefly_qt.widgets.player_icons import icon_pixmap

if TYPE_CHECKING:
    from mustiefly_qt.services.playback import PlaybackEngine
    from mustiefly_qt.services.playlist_store import PlaylistStore
    from mustiefly_qt.services.thumbnails import ThumbnailService

DEBOUNCE_MS = 120


class _PaletteSearchEdit(QLineEdit):
    """Up/Down/Enter tuşlarını ana listeye aktaran özel arama çubuğu."""
    navigateRequested = Signal(int)  # +1 (aşağı), -1 (yukarı), +5 (page down), -5 (page up)
    activateRequested = Signal()
    dismissRequested = Signal()

    def keyPressEvent(self, event: QKeyEvent):  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Down, Qt.Key_Tab):
            self.navigateRequested.emit(1)
            event.accept()
            return
        if key in (Qt.Key_Up, Qt.Key_Backtab):
            self.navigateRequested.emit(-1)
            event.accept()
            return
        if key == Qt.Key_PageDown:
            self.navigateRequested.emit(5)
            event.accept()
            return
        if key == Qt.Key_PageUp:
            self.navigateRequested.emit(-5)
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.activateRequested.emit()
            event.accept()
            return
        if key == Qt.Key_Escape:
            self.dismissRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PaletteItem:
    def __init__(
        self,
        kind: str,
        title: str,
        subtitle: str,
        category: str,
        icon_name: str,
        icon_color: str,
        shortcut: str = "",
        callback: Callable[[], None] | None = None,
        song_ref: dict | None = None,
        playlist_name: str = "",
        song_index: int = -1,
        keywords: str = "",
    ):
        self.kind = kind
        self.title = title
        self.subtitle = subtitle
        self.category = category
        self.icon_name = icon_name
        self.icon_color = icon_color
        self.shortcut = shortcut
        self.callback = callback
        self.song_ref = song_ref
        self.playlist_name = playlist_name
        self.song_index = song_index
        self.keywords = (keywords + " " + title + " " + subtitle).lower()


class _PaletteRowWidget(QWidget):
    """Palet listesindeki tek bir öğe: İkon/Kapak + Başlık/Altbilgi + Kategori/Kısayol rozeti."""

    def __init__(
        self,
        item: PaletteItem,
        thumbnails: ThumbnailService | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.item = item
        self.thumbnails = thumbnails
        self.setObjectName("PaletteRow")
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 14, 6)
        layout.setSpacing(12)

        # 1. Sol İkon veya Albüm Kapağı
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(36, 36)
        self.icon_label.setAlignment(Qt.AlignCenter)

        if item.kind == "song" and item.song_ref:
            bg_color = cover_color_for(item.title)
            self.icon_label.setStyleSheet(
                f"background: {bg_color}; border-radius: 6px; font-size: 14px; color: #FFFFFF;"
            )
            self.icon_label.setText("🎵")
            if thumbnails is not None:
                pm = thumbnails.pixmap_for(item.song_ref, 36)
                if pm is not None and not pm.isNull():
                    self.set_pixmap(pm)
        else:
            self.icon_label.setStyleSheet(
                "background: rgba(255, 255, 255, 0.05); border-radius: 8px;"
            )
            pm = icon_pixmap(item.icon_name, 18, item.icon_color)
            if pm is not None and not pm.isNull():
                self.icon_label.setPixmap(pm)

        layout.addWidget(self.icon_label)

        # 2. Orta: Başlık + Altbilgi
        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.title_label = QLabel(item.title)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        text_layout.addWidget(self.title_label)

        self.sub_label = QLabel(item.subtitle)
        self.sub_label.setStyleSheet("font-size: 11px; color: #8F9CAE;")
        text_layout.addWidget(self.sub_label)

        layout.addWidget(text_box, stretch=1)

        # 3. Sağ: Kısayol Rozeti (varsa) + Kategori Rozeti
        if item.shortcut:
            sc_badge = QLabel(f" {item.shortcut} ")
            sc_badge.setStyleSheet(
                "background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.16); "
                "border-radius: 4px; font-size: 10px; font-weight: bold; color: #00D2FF; padding: 2px 5px;"
            )
            layout.addWidget(sc_badge)

        cat_badge = QLabel(item.category)
        cat_badge_style = self._category_style(item.kind)
        cat_badge.setStyleSheet(cat_badge_style)
        layout.addWidget(cat_badge)

    def _category_style(self, kind: str) -> str:
        colors = {
            "command": ("rgba(0, 210, 255, 0.15)", "#00D2FF"),
            "artist": ("rgba(162, 89, 255, 0.15)", "#C084FC"),
            "playlist": ("rgba(255, 176, 32, 0.15)", "#FDBA74"),
            "song": ("rgba(34, 197, 94, 0.15)", "#4ADE80"),
            "web": ("rgba(239, 68, 68, 0.15)", "#F87171"),
        }
        bg, fg = colors.get(kind, ("rgba(255, 255, 255, 0.1)", "#CBD5E1"))
        return (
            f"background: {bg}; color: {fg}; font-size: 9px; font-weight: bold; "
            f"border-radius: 4px; padding: 2px 7px; letter-spacing: 0.5px;"
        )

    def set_pixmap(self, pm):
        if pm is not None and not pm.isNull():
            self.icon_label.setPixmap(pm)
            self.icon_label.setText("")


class CommandPaletteDialog(QDialog):
    """Spotlight / Command Palette (`Ctrl + K`)."""

    def __init__(
        self,
        store: PlaylistStore,
        playback: PlaybackEngine,
        thumbnails: ThumbnailService | None = None,
        app_window: Any = None,
        parent: QWidget | None = None,
        initial_query: str = "",
    ):
        super().__init__(parent)
        self.store = store
        self.playback = playback
        self.thumbnails = thumbnails
        self.app_window = app_window
        self.initial_query = initial_query

        self.setWindowTitle("Spotlight & Komut Paleti")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("QDialog { background: transparent; }")
        self.resize(680, 520)

        # Önbelleğe alınmış komut, sanatçı ve liste listeleri
        self._command_items: list[PaletteItem] = []
        self._artist_items: list[PaletteItem] = []
        self._playlist_items: list[PaletteItem] = []
        self._current_matches: list[PaletteItem] = []

        self._build_ui()
        self._init_data()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._run_search)

        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

        if initial_query:
            self.search_edit.setText(initial_query)
            self._run_search()
        else:
            self._show_default_suggestions()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)

        # Kart Çerçevesi (Glassmorphism & Neon Kenarlık)
        self.container = QFrame(self)
        self.container.setObjectName("PaletteContainer")
        self.container.setStyleSheet(
            "#PaletteContainer {"
            "  background-color: rgba(17, 21, 32, 0.97);"
            "  border: 1px solid rgba(0, 210, 255, 0.38);"
            "  border-radius: 16px;"
            "}"
        )

        # Yumuşak Gölge
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 10)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 1. ÜST ARAMA ÇUBUĞU
        search_bar = QWidget()
        search_bar.setFixedHeight(58)
        search_bar_layout = QHBoxLayout(search_bar)
        search_bar_layout.setContentsMargins(16, 0, 16, 0)
        search_bar_layout.setSpacing(12)

        search_icon = QLabel()
        search_icon.setFixedSize(22, 22)
        pm = icon_pixmap("search", 20, "#00D2FF")
        if pm is not None:
            search_icon.setPixmap(pm)
        search_bar_layout.addWidget(search_icon)

        self.search_edit = _PaletteSearchEdit()
        self.search_edit.setPlaceholderText("Şarkı, sanatçı, liste veya komut ara… (örn: vokal, tarkan, karaoke, rock)")
        self.search_edit.setStyleSheet(
            "QLineEdit {"
            "  background: transparent;"
            "  border: none;"
            "  color: #FFFFFF;"
            "  font-size: 15px;"
            "  font-weight: 500;"
            "  selection-background-color: #00D2FF;"
            "  selection-color: #000000;"
            "}"
        )
        self.search_edit.textChanged.connect(self._schedule_search)
        self.search_edit.navigateRequested.connect(self._navigate_list)
        self.search_edit.activateRequested.connect(self._execute_current_item)
        self.search_edit.dismissRequested.connect(self.reject)
        search_bar_layout.addWidget(self.search_edit, stretch=1)

        esc_hint = QLabel("ESC")
        esc_hint.setStyleSheet(
            "background: rgba(255, 255, 255, 0.08);"
            "border: 1px solid rgba(255, 255, 255, 0.15);"
            "border-radius: 5px;"
            "color: #8F9CAE;"
            "font-size: 10px;"
            "font-weight: bold;"
            "padding: 3px 6px;"
        )
        search_bar_layout.addWidget(esc_hint)
        container_layout.addWidget(search_bar)

        # Ayırıcı Çizgi
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(255, 255, 255, 0.08);")
        container_layout.addWidget(divider)

        # 2. SONUÇ LİSTESİ
        self.results_list = QListWidget()
        self.results_list.setObjectName("PaletteList")
        self.results_list.setFocusPolicy(Qt.NoFocus)  # Odak hep inputta kalır, tuşları edit yönlendirir
        self.results_list.setStyleSheet(
            "QListWidget {"
            "  background: transparent;"
            "  border: none;"
            "  outline: none;"
            "  padding: 6px 8px;"
            "}"
            "QListWidget::item {"
            "  border-radius: 8px;"
            "  margin: 1px 0px;"
            "}"
            "QListWidget::item:selected {"
            "  background: rgba(0, 210, 255, 0.12);"
            "  border: 1px solid rgba(0, 210, 255, 0.35);"
            "}"
            "QListWidget::item:hover:!selected {"
            "  background: rgba(255, 255, 255, 0.04);"
            "}"
        )
        self.results_list.itemClicked.connect(lambda _: self._execute_current_item())
        self.results_list.itemDoubleClicked.connect(lambda _: self._execute_current_item())
        container_layout.addWidget(self.results_list, stretch=1)

        # Alt Ayırıcı
        bottom_divider = QFrame()
        bottom_divider.setFixedHeight(1)
        bottom_divider.setStyleSheet("background-color: rgba(255, 255, 255, 0.06);")
        container_layout.addWidget(bottom_divider)

        # 3. ALT BİLGİ VE KISAYOL İPUÇLARI (FOOTER)
        footer = QWidget()
        footer.setFixedHeight(38)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 0, 16, 0)

        self.status_label = QLabel("Önerilen Eylemler & Kütüphane")
        self.status_label.setStyleSheet("font-size: 11px; color: #707E94;")
        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch(1)

        hints = QLabel("↑↓ Gezin  •  ↵ Çalıştır / Çal  •  Esc Kapat")
        hints.setStyleSheet("font-size: 11px; color: #8F9CAE; font-weight: 500;")
        footer_layout.addWidget(hints)

        container_layout.addWidget(footer)
        root_layout.addWidget(self.container)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._center_palette()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _center_palette(self):
        """Spotlight paletini pencerenin üst-ortasına konumlandırır."""
        parent = self.parentWidget()
        if parent is not None:
            p_geo = parent.geometry()
            x = p_geo.x() + (p_geo.width() - self.width()) // 2
            y = p_geo.y() + max(48, (p_geo.height() - self.height()) // 5)
            self.move(x, y)

    def done(self, result: int):
        if self.thumbnails is not None:
            try:
                self.thumbnails.thumbnailReady.disconnect(self._on_thumbnail_ready)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    # --- VERİ HAZIRLIĞI ---

    def _init_data(self):
        self._build_commands()
        self._build_artists()
        self._build_playlists()

    def _build_commands(self):
        """Uygulama eylemlerini ve hızlı kısayolları hazırlar."""
        app = self.app_window
        pb = self.playback
        vocal_on = getattr(pb, "vocal_remover_enabled", False)

        cmds: list[PaletteItem] = [
            PaletteItem(
                kind="command",
                title="Vokal Ayırma'yı Kapat (Normal Mod)" if vocal_on else "Vokal Ayırma'yı Aç (Enstrümantal / Karaoke)",
                subtitle="Gerçek zamanlı insan sesi filtreleme modu",
                category="KOMUT",
                icon_name="mic",
                icon_color="#FF7A3D" if vocal_on else "#00D2FF",
                shortcut="V",
                callback=self._cmd_toggle_vocal,
                keywords="vokal vocal enstrumantal karaoke ses filtre sozsuz",
            ),
            PaletteItem(
                kind="command",
                title="Neon Görselleştirici Modunu Değiştir",
                subtitle="Çubuklar, Dalga, Ayna, Çember spektrumları",
                category="KOMUT",
                icon_name="spectrum",
                icon_color="#00D2FF",
                shortcut="G",
                callback=self._cmd_cycle_visualizer,
                keywords="gorsellestirici spektrum visualizer neon spectrum wave bars",
            ),
            PaletteItem(
                kind="command",
                title="Canlı Karaoke & Tam Ekran Modu",
                subtitle="Apple Music tarzı dinamik ambient ışık ve akan şarkı sözleri",
                category="KOMUT",
                icon_name="fullscreen",
                icon_color="#A259FF",
                shortcut="F11",
                callback=self._cmd_toggle_karaoke,
                keywords="karaoke sozler tam ekran fullscreen lyrics lrc",
            ),
            PaletteItem(
                kind="command",
                title="Ekolayzer & Ses Ayarları",
                subtitle="10-bant frekans, Bass Boost, Reverb ve ses profilleri",
                category="KOMUT",
                icon_name="sliders",
                icon_color="#00E5FF",
                shortcut="Ctrl+E",
                callback=self._cmd_open_equalizer,
                keywords="ekolayzer equalizer ses bass tiz ses ayari eq",
            ),
            PaletteItem(
                kind="command",
                title="Mini Oynatıcı (Picture-in-Picture)",
                subtitle="Masaüstünde her zaman üstte duran kompakt çalar",
                category="KOMUT",
                icon_name="mini_player",
                icon_color="#FFB020",
                shortcut="Ctrl+M",
                callback=self._cmd_toggle_mini_player,
                keywords="mini oynatici player pip kompakt floating masaustu",
            ),
            PaletteItem(
                kind="command",
                title="Masaüstü Şeffaf Widget Modu (Rainmeter)",
                subtitle="Masaüstü duvar kağıdında süzülen cam efektli widget + spektrum",
                category="KOMUT",
                icon_name="spectrum",
                icon_color="#00D2FF",
                callback=self._cmd_toggle_desktop_widget,
                keywords="widget masaustu rainmeter seffaf desktop glass",
            ),
            PaletteItem(
                kind="command",
                title="Gaming HUD Overlay Aç / Kapat",
                subtitle="Oyunlarda ve tam ekranda ekran üstü mini çubuk",
                category="KOMUT",
                icon_name="sparkle",
                icon_color="#00FFC2",
                shortcut="Ctrl+H",
                callback=self._cmd_toggle_hud,
                keywords="hud gaming overlay bildirim oyun bar",
            ),
            PaletteItem(
                kind="command",
                title="Oynat / Duraklat",
                subtitle="Çalan şarkıyı duraklat veya devam ettir",
                category="KOMUT",
                icon_name="play" if not pb.is_playing else "pause",
                icon_color="#22C55E",
                shortcut="Space",
                callback=lambda: pb.toggle_play_pause(),
                keywords="oynat duraklat play pause baslat durdur",
            ),
            PaletteItem(
                kind="command",
                title="Sonraki Şarkıya Geç",
                subtitle="Sıradaki parçayı çalmaya başla",
                category="KOMUT",
                icon_name="next",
                icon_color="#FFFFFF",
                shortcut="Ctrl+Right",
                callback=lambda: pb.play_next(),
                keywords="sonraki ileri next sarki gec",
            ),
            PaletteItem(
                kind="command",
                title="Önceki Şarkıya Dön",
                subtitle="Önceki parçayı çalmaya başla",
                category="KOMUT",
                icon_name="prev",
                icon_color="#FFFFFF",
                shortcut="Ctrl+Left",
                callback=lambda: pb.play_previous(),
                keywords="onceki geri prev sarki don",
            ),
            PaletteItem(
                kind="command",
                title=f"Karışık Çalma (Şu an: {'Açık' if getattr(pb, 'shuffle_mode', False) else 'Kapalı'})",
                subtitle="Parçaları rastgele sırada çal",
                category="KOMUT",
                icon_name="shuffle",
                icon_color="#00D2FF" if getattr(pb, "shuffle_mode", False) else "#8F9CAE",
                shortcut="Ctrl+S",
                callback=lambda: pb.toggle_shuffle(),
                keywords="karisik shuffle rastgele random sarki sirasi",
            ),
            PaletteItem(
                kind="command",
                title="Tekrar Modunu Değiştir",
                subtitle=f"Kapalı / Liste / Tek Parça (Şu an: {getattr(pb, 'repeat_mode', 'off')})",
                category="KOMUT",
                icon_name="repeat",
                icon_color="#FFFFFF",
                shortcut="Ctrl+R",
                callback=lambda: pb.cycle_repeat(),
                keywords="tekrar repeat dongu loop basa don",
            ),
            PaletteItem(
                kind="command",
                title="Şarkı Radyosu Başlat (Autoplay)",
                subtitle="Çalan şarkıya benzer parçalarla sonsuz akış başlat",
                category="KOMUT",
                icon_name="radio",
                icon_color="#FF5252",
                callback=self._cmd_start_radio,
                keywords="radyo radio autoplay sonsuz sarki benzer oneriler",
            ),
            PaletteItem(
                kind="command",
                title="Ana Sayfaya Git",
                subtitle="Son çalınanlar, popüler mix'ler ve kütüphanen",
                category="KOMUT",
                icon_name="home",
                icon_color="#FFFFFF",
                callback=lambda: self._cmd_nav("home"),
                keywords="ana sayfa home ana menu giris",
            ),
            PaletteItem(
                kind="command",
                title="Keşfet Sayfası",
                subtitle="YouTube Music popüler trendler ve yeni çıkanlar",
                category="KOMUT",
                icon_name="compass",
                icon_color="#00D2FF",
                callback=lambda: self._cmd_nav("explore"),
                keywords="kesfet explore trendler populer yeniler",
            ),
            PaletteItem(
                kind="command",
                title="İndirilenler & Çevrimdışı Kütüphane",
                subtitle="İnternet bağlantısı olmadan dinlenebilen şarkılar",
                category="KOMUT",
                icon_name="download",
                icon_color="#4ADE80",
                callback=lambda: self._cmd_nav("downloads"),
                keywords="indirilenler downloads cevrimdisi offline mp3 yerel",
            ),
            PaletteItem(
                kind="command",
                title="Dinleme İstatistikleri",
                subtitle="En çok dinlenen sanatçılar, şarkılar ve süreler",
                category="KOMUT",
                icon_name="chart",
                icon_color="#FBBF24",
                callback=lambda: self._cmd_nav("stats"),
                keywords="istatistik stats grafik analiz ozet dinleme",
            ),
            PaletteItem(
                kind="command",
                title="Senin İçin Mix'ler",
                subtitle="Dinleme zevkine göre derlenen özel miksler",
                category="KOMUT",
                icon_name="sparkle",
                icon_color="#C084FC",
                callback=lambda: self._cmd_nav("mixes"),
                keywords="mix miks karisim oneriler senin icin",
            ),
            PaletteItem(
                kind="command",
                title="Müzik Özeti (Wrapped)",
                subtitle="Kişisel dinleme özeti ve müzik karnesi",
                category="KOMUT",
                icon_name="gift",
                icon_color="#F43F5E",
                callback=lambda: self._cmd_nav("wrapped"),
                keywords="wrapped ozet karne hediye yil sonu",
            ),
            PaletteItem(
                kind="command",
                title="Arayüz Temasını Değiştir",
                subtitle="Karanlık, Neon, Gece Yarısı ve diğer temalar",
                category="KOMUT",
                icon_name="sparkle",
                icon_color="#FDE047",
                callback=self._cmd_toggle_theme,
                keywords="tema theme karanlik aydinlik dark light renk gorunum",
            ),
            PaletteItem(
                kind="command",
                title="Ayarlar & Tercihler",
                subtitle="Ses kalitesi, önbellek, Discord entegrasyonu ve kısayollar",
                category="KOMUT",
                icon_name="settings",
                icon_color="#94A3B8",
                callback=self._cmd_open_settings,
                keywords="ayarlar settings secenekler tercihler discord ses",
            ),
            PaletteItem(
                kind="command",
                title="Toplu Şarkı & URL Ekle",
                subtitle="Birden fazla YouTube/Spotify bağlantısını listeye ekle",
                category="KOMUT",
                icon_name="plus",
                icon_color="#4ADE80",
                callback=self._cmd_bulk_add,
                keywords="toplu sarki link url ekle add kutuphane",
            ),
            PaletteItem(
                kind="command",
                title="Yinelenen Şarkıları Temizle",
                subtitle="Kütüphanendeki mükerrer/aynı parçaları tespit et",
                category="KOMUT",
                icon_name="archive",
                icon_color="#FB923C",
                callback=self._cmd_duplicate_finder,
                keywords="yinelenen cift duplicate ayni sil temizle",
            ),
            PaletteItem(
                kind="command",
                title="Akıllı Liste Kuralları",
                subtitle="Filtrelere göre otomatik güncellenen akıllı listeler",
                category="KOMUT",
                icon_name="sliders",
                icon_color="#38BDF8",
                callback=self._cmd_smart_rules,
                keywords="akilli liste kural smart rules filtre",
            ),
            PaletteItem(
                kind="command",
                title="Tanılama & Sistem Raporu",
                subtitle="Performans, bellek ve ses motoru durumunu incele",
                category="KOMUT",
                icon_name="diagnostics",
                icon_color="#38BDF8",
                callback=self._cmd_diagnostics,
                keywords="rapor tani diagnostics hata performans sistem bellek log",
            ),
        ]
        self._command_items = cmds

    def _build_artists(self):
        """Kütüphanedeki tüm sanatçıları toplar ve indeksler."""
        artist_counts: dict[str, int] = {}
        for songs in self.store.playlists.values():
            for s in songs:
                raw_u = s.get("uploader") or ""
                raw_t = s.get("title") or ""
                _, a = parse_track_and_artist(raw_t, raw_u, s)
                if not a:
                    a = clean_artist(raw_u)
                if a and len(a) > 1 and a.lower() not in ("youtube", "various artists", "bilinmeyen sanatçı"):
                    artist_counts[a] = artist_counts.get(a, 0) + 1

        sorted_artists = sorted(artist_counts.items(), key=lambda t: t[1], reverse=True)
        items: list[PaletteItem] = []
        for name, count in sorted_artists:
            items.append(
                PaletteItem(
                    kind="artist",
                    title=name,
                    subtitle=f"Sanatçı Sayfası • {count} şarkı kütüphanende",
                    category="SANATÇI",
                    icon_name="user",
                    icon_color="#C084FC",
                    callback=lambda a=name: self._cmd_open_artist(a),
                    keywords=name.lower(),
                )
            )
        self._artist_items = items

    def _build_playlists(self):
        """Kütüphanedeki tüm çalma listelerini indeksler."""
        items: list[PaletteItem] = []
        for name, songs in self.store.playlists.items():
            items.append(
                PaletteItem(
                    kind="playlist",
                    title=name,
                    subtitle=f"Çalma Listesi • {len(songs)} şarkı",
                    category="LİSTE",
                    icon_name="folder",
                    icon_color="#FDBA74",
                    callback=lambda n=name: self._cmd_open_playlist(n),
                    keywords=name.lower(),
                )
            )
        self._playlist_items = items

    # --- ARAMA VE FİLTRELEME ---

    def _schedule_search(self):
        self._debounce.start()

    def _show_default_suggestions(self):
        """Arama kutusu boşken hızlı komutları ve listeleri gösterir."""
        matches: list[PaletteItem] = []
        # En popüler 7 komut
        matches.extend(self._command_items[:7])
        # En çok şarkı içeren 3 playlist
        matches.extend(self._playlist_items[:3])
        # En popüler 3 sanatçı
        matches.extend(self._artist_items[:3])
        self._render_results(matches, status="Önerilen Hızlı Komutlar & Kütüphane")

    def _run_search(self):
        query = self.search_edit.text().strip()
        if not query:
            self._show_default_suggestions()
            return

        q_lower = query.lower()
        terms = q_lower.split()

        matched_commands: list[PaletteItem] = []
        matched_artists: list[PaletteItem] = []
        matched_playlists: list[PaletteItem] = []
        matched_songs: list[PaletteItem] = []

        # 1. Komutlar
        for cmd in self._command_items:
            if all(term in cmd.keywords for term in terms):
                matched_commands.append(cmd)

        # 2. Sanatçılar
        for art in self._artist_items:
            if all(term in art.keywords for term in terms):
                matched_artists.append(art)
                if len(matched_artists) >= 6:
                    break

        # 3. Çalma Listeleri
        for pl in self._playlist_items:
            if all(term in pl.keywords for term in terms):
                matched_playlists.append(pl)
                if len(matched_playlists) >= 6:
                    break

        # 4. Kütüphane Şarkıları
        for pl_name, songs in self.store.playlists.items():
            for idx, song in enumerate(songs):
                title = song.get("title", "")
                uploader = song.get("uploader", "")
                combined = (title + " " + uploader + " " + pl_name).lower()
                if all(term in combined for term in terms):
                    clean_t, clean_a = parse_track_and_artist(title, uploader, song)
                    matched_songs.append(
                        PaletteItem(
                            kind="song",
                            title=clean_t or title,
                            subtitle=f"{clean_a or uploader} • {pl_name} • {format_time((song.get('duration') or 0) * 1000)}",
                            category="ŞARKI",
                            icon_name="disc",
                            icon_color="#FFFFFF",
                            song_ref=song,
                            playlist_name=pl_name,
                            song_index=idx,
                            callback=lambda pl=pl_name, i=idx, t=clean_t: self._cmd_play_song(pl, i, t),
                        )
                    )
                    if len(matched_songs) >= 20:
                        break
            if len(matched_songs) >= 20:
                break

        # Birleştirme: Komutlar, Sanatçılar, Listeler, Şarkılar
        results: list[PaletteItem] = []
        results.extend(matched_commands[:6])
        results.extend(matched_artists[:4])
        results.extend(matched_playlists[:4])
        results.extend(matched_songs[:18])

        # 5. YouTube / Web Arama Fallback
        results.append(
            PaletteItem(
                kind="web",
                title=f"YouTube'da Ara: \"{query}\"",
                subtitle="Online YouTube & YouTube Music üzerinde ara",
                category="WEB",
                icon_name="search",
                icon_color="#F87171",
                callback=lambda q=query: self._cmd_web_search(q),
                keywords=q_lower,
            )
        )

        self._render_results(results, status=f"{len(results)} sonuç bulundu")

    def _render_results(self, items: list[PaletteItem], status: str = ""):
        self._current_matches = items
        self.results_list.clear()

        if status:
            self.status_label.setText(status)

        for item in items:
            list_item = QListWidgetItem()
            row = _PaletteRowWidget(item, thumbnails=self.thumbnails)
            list_item.setSizeHint(QSize(0, 52))
            self.results_list.addItem(list_item)
            self.results_list.setItemWidget(list_item, row)

        if items:
            self.results_list.setCurrentRow(0)

    def _on_thumbnail_ready(self, key: str):
        for i in range(self.results_list.count()):
            row = self.results_list.itemWidget(self.results_list.item(i))
            if isinstance(row, _PaletteRowWidget) and row.item.song_ref:
                if row.item.song_ref.get("webpage_url") == key:
                    pm = self.thumbnails.pixmap_for(row.item.song_ref, 36)
                    row.set_pixmap(pm)

    # --- KLAVYE İLE GEZİNME VE ÇALIŞTIRMA ---

    def _navigate_list(self, delta: int):
        count = self.results_list.count()
        if count == 0:
            return
        current = self.results_list.currentRow()
        new_row = max(0, min(count - 1, current + delta))
        self.results_list.setCurrentRow(new_row)

    def _execute_current_item(self):
        row = self.results_list.currentRow()
        if 0 <= row < len(self._current_matches):
            item = self._current_matches[row]
            self.accept()
            if item.callback is not None:
                QTimer.singleShot(20, item.callback)

    # --- AKSİYON METOTLARI ---

    def _cmd_toggle_vocal(self):
        self.playback.toggle_vocal_remover()
        if self.app_window and hasattr(self.app_window, "show_success_message"):
            state = "Açıldı (Enstrümantal)" if self.playback.vocal_remover_enabled else "Kapatıldı"
            self.app_window.show_success_message(f"🎙️ Vokal Ayırma {state}")

    def _cmd_cycle_visualizer(self):
        if self.app_window and hasattr(self.app_window, "_cycle_visualizer_mode"):
            self.app_window._cycle_visualizer_mode()

    def _cmd_toggle_karaoke(self):
        if self.app_window and hasattr(self.app_window, "_toggle_karaoke_view"):
            self.app_window._toggle_karaoke_view()

    def _cmd_open_equalizer(self):
        if self.app_window and hasattr(self.app_window, "_toggle_equalizer_window"):
            self.app_window._toggle_equalizer_window()

    def _cmd_toggle_mini_player(self):
        if self.app_window and hasattr(self.app_window, "_toggle_mini_player"):
            self.app_window._toggle_mini_player()

    def _cmd_toggle_desktop_widget(self):
        if self.app_window and hasattr(self.app_window, "_toggle_desktop_widget"):
            self.app_window._toggle_desktop_widget()

    def _cmd_toggle_hud(self):
        if self.app_window and hasattr(self.app_window, "hud_overlay"):
            hud = self.app_window.hud_overlay
            if hud.isVisible():
                hud.dismiss()
            else:
                song = self.playback.current_song
                if song:
                    hud.show_song(song)
                elif hasattr(self.app_window, "show_success_message"):
                    self.app_window.show_success_message("HUD: Şu an çalan şarkı yok")

    def _cmd_start_radio(self):
        song = self.playback.current_song
        if song and hasattr(self.playback, "start_radio_for"):
            self.playback.start_radio_for(song)
            if self.app_window and hasattr(self.app_window, "show_success_message"):
                self.app_window.show_success_message(f"📻 Şarkı Radyosu: {song.get('title', 'Parça')}")
        elif self.app_window and hasattr(self.app_window, "show_radio_view"):
            self.app_window.show_radio_view()

    def _cmd_nav(self, destination: str):
        if not self.app_window:
            return
        nav_map = {
            "home": "show_home_view",
            "explore": "show_explore_view",
            "downloads": "show_downloads_view",
            "stats": "show_stats_view",
            "mixes": "show_mixes_view",
            "wrapped": "show_wrapped_view",
        }
        method_name = nav_map.get(destination)
        if method_name and hasattr(self.app_window, method_name):
            getattr(self.app_window, method_name)()

    def _cmd_open_artist(self, artist_name: str):
        if self.app_window and hasattr(self.app_window, "open_artist_page"):
            self.app_window.open_artist_page(artist_name)

    def _cmd_open_playlist(self, playlist_name: str):
        if self.app_window and hasattr(self.app_window, "show_playlist_view"):
            self.app_window.show_playlist_view(playlist_name)

    def _cmd_play_song(self, playlist_name: str, index: int, title: str):
        self.playback.play_song_at_index(playlist_name, index)
        if self.app_window and hasattr(self.app_window, "show_success_message"):
            self.app_window.show_success_message(f"🎵 Çalınıyor: {title}")

    def _cmd_web_search(self, query: str):
        if self.app_window and hasattr(self.app_window, "_open_search_dialog"):
            self.app_window._open_search_dialog(initial_query=query)

    def _cmd_toggle_theme(self):
        if self.app_window and hasattr(self.app_window, "settings"):
            # Toggle between themes
            current = self.app_window.settings.get("theme", "modern_dark")
            themes = ["modern_dark", "neon_night", "midnight_blue", "pure_black"]
            try:
                next_theme = themes[(themes.index(current) + 1) % len(themes)]
            except ValueError:
                next_theme = "modern_dark"
            self.app_window.settings["theme"] = next_theme
            if hasattr(self.app_window, "_rebuild_stylesheet"):
                self.app_window._rebuild_stylesheet()
            if hasattr(self.app_window, "show_success_message"):
                self.app_window.show_success_message(f"Tema Değiştirildi: {next_theme}")

    def _cmd_open_settings(self):
        if self.app_window and hasattr(self.app_window, "_open_settings_dialog"):
            self.app_window._open_settings_dialog()

    def _cmd_bulk_add(self):
        if self.app_window and hasattr(self.app_window, "_open_bulk_add"):
            self.app_window._open_bulk_add()

    def _cmd_duplicate_finder(self):
        if self.app_window and hasattr(self.app_window, "_open_duplicate_finder"):
            self.app_window._open_duplicate_finder()

    def _cmd_smart_rules(self):
        if self.app_window and hasattr(self.app_window, "show_smart_rules_dialog"):
            self.app_window.show_smart_rules_dialog()

    def _cmd_diagnostics(self):
        if self.app_window and hasattr(self.app_window, "open_diagnostics_dialog"):
            self.app_window.open_diagnostics_dialog()

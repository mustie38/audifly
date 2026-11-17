"""PlayerBar — premium/minimalist yeniden tasarım.

ÖNEMLİ (bkz. proje notu): Bu dosya sadece UI/UX'i yeniden düzenler.
PlaybackEngine'e dokunulmadı; tüm sinyal/slot bağlantıları (seek, volume,
play/pause, next, previous, shuffle, repeat, queue, lyrics, now playing,
sleep timer, playback speed, like) birebir korunuyor. Değişen tek şey bu
bilginin ekranda NASIL sunulduğu.

Dışa açık API (app_window.py tarafından kullanılıyor, isim/imza sabit tutuldu):
    PlayerBar(playback, thumbnails=None, accent="#...", parent=None)
    .queueRequested / .lyricsRequested / .jumpToPlayingRequested (Signal)
    .set_accent(color: str)
    .waveform_strip.set_accent(color: str)
"""
from __future__ import annotations


from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QStackedLayout, QVBoxLayout,
                               QWidget, QFrame, QApplication, QInputDialog)

from mustiefly_qt.helpers.constants import cover_color_for, format_time
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.sleep_timer import SleepTimer
from mustiefly_qt.services.thumbnails import ThumbnailService
from mustiefly_qt.widgets.waveform_strip import WaveformStrip
from mustiefly_qt.widgets.click_slider import ClickSlider
from mustiefly_qt.widgets.player_icons import icon as vicon

# ---------------------------------------------------------------------------
# SABİTLER — büyüklükler tek yerden yönetilir (magic number yok)
# ---------------------------------------------------------------------------
BAR_HEIGHT = 100
BAR_SIDE_MARGIN = 14
BAR_BOTTOM_MARGIN = 14
BAR_RADIUS = 18
CONTENT_PADDING_H = 18
CONTENT_PADDING_V = 12

COVER_SIZE = 62
COVER_RADIUS = 12

PLAY_BTN_SIZE = 46
TRANSPORT_BTN_SIZE = 34
SECONDARY_BTN_SIZE = 28
RIGHT_BTN_SIZE = 32

ICON_PLAY = 18
ICON_TRANSPORT = 15
ICON_SECONDARY = 14
ICON_RIGHT = 15

NOW_INFO_WIDTH_FULL = 200
NOW_INFO_WIDTH_COMPACT = 140

VOLUME_COLLAPSED_W = 0
VOLUME_EXPANDED_W = 92

# Dar pencerede sırayla gizlenecek eşikler (spec: kapak+başlık > kontroller >
# progress > queue/lyrics > volume; buradaki sıra: en önce feda edilenler önce)
BREAKPOINT_HIDE_SUBTITLE = 900
BREAKPOINT_HIDE_SECONDARY = 760   # shuffle/repeat — sadece minimum 980'in epey altı, güvenlik payı

TEXT_PRIMARY = "#ffffff"
TEXT_MUTED = "#b7b2cf"
ICON_MUTED = "#cfc9e6"
ICON_MUTED_HOVER = "#ffffff"


class _DualWaveform:
    """Geriye dönük uyumluluk için tutulan ince yönlendirici — app_window.py
    `player_bar.waveform_strip.set_accent(...)` çağırıyor. Yeni tasarımda tek
    bir WaveformStrip kullanıldığı için bu artık sadece o tek örneği sarar.
    """

    def __init__(self, strip: WaveformStrip):
        self._strip = strip

    def set_accent(self, color: str):
        self._strip.set_accent(color)

    def set_playing(self, playing: bool):
        self._strip.set_playing(playing)


class _ClickableBox(QWidget):
    clicked = Signal()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _HoverRevealBox(QWidget):
    """İçindeki widget'ı sadece üzerine gelindiğinde (hover) genişleterek
    gösterir. Volume slider'ı varsayılan olarak gizli/kompakt tutmak için
    kullanılır — spec: "hover/click ile ortaya çıkan compact volume control".
    """

    def __init__(self, reveal: QWidget, collapsed: int, expanded: int, parent=None):
        super().__init__(parent)
        self._reveal = reveal
        self._collapsed = collapsed
        self._expanded = expanded
        reveal.setMaximumWidth(collapsed)
        self._anim = QPropertyAnimation(reveal, b"maximumWidth", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _animate_to(self, width: int):
        self._anim.stop()
        self._anim.setStartValue(self._reveal.maximumWidth())
        self._anim.setEndValue(width)
        self._anim.start()

    def enterEvent(self, event):  # noqa: N802
        self._animate_to(self._expanded)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._animate_to(self._collapsed)
        super().leaveEvent(event)


class IconButton(QPushButton):
    """Metin/emoji yerine vektör ikon çizen, tutarlı hover davranışına sahip
    düğme. `set_kind`/`set_active` ile ikon rengini (nötr <-> accent) değiştirir.
    """

    def __init__(self, kind: str, size: int, icon_size: int, color: str = ICON_MUTED,
                 active_color: str | None = None, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._icon_size = icon_size
        self._color = color
        self._active_color = active_color or color
        self._active = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("PBIconBtn")
        self._refresh_icon()

    def _refresh_icon(self):
        color = self._active_color if self._active else self._color
        self.setIcon(vicon(self._kind, self._icon_size, color))
        self.setIconSize(self.size() * 0 + self._icon_size_qsize())

    def _icon_size_qsize(self):
        from PySide6.QtCore import QSize
        return QSize(self._icon_size, self._icon_size)

    def set_kind(self, kind: str):
        self._kind = kind
        self._refresh_icon()

    def set_active(self, active: bool):
        self._active = active
        self._refresh_icon()

    def set_color(self, color: str, active_color: str | None = None):
        self._color = color
        if active_color is not None:
            self._active_color = active_color
        self._refresh_icon()


class PlayerBar(QWidget):
    queueRequested = Signal()
    lyricsRequested = Signal()
    karaokeRequested = Signal()
    jumpToPlayingRequested = Signal()
    startRadioRequested = Signal(dict)

    SLEEP_OPTIONS = [("15 dakika", 15), ("30 dakika", 30),
                     ("45 dakika", 45), ("60 dakika", 60), ("90 dakika", 90)]
    SPEED_OPTIONS = [("0.5x", 0.5), ("0.75x", 0.75), ("1x", 1.0),
                     ("1.25x", 1.25), ("1.5x", 1.5), ("2x", 2.0)]

    def __init__(self, playback: PlaybackEngine, thumbnails: ThumbnailService | None = None,
                 accent: str = "#a980f9", parent=None):
        super().__init__(parent)
        self.playback = playback
        self.thumbnails = thumbnails
        self._accent = accent
        self.setObjectName("PlayerBar")
        self.setFixedHeight(BAR_HEIGHT + BAR_BOTTOM_MARGIN)
        self._seeking = False
        self._current_key = None
        self._total_ms = 0

        self._build_ui(accent)
        self._wire_signals()

        self.sleep_timer = SleepTimer(self.playback, self)
        self.sleep_timer.finished.connect(self._on_sleep_finished)

        saved_rate = float(playback.settings.get("_rate", 1.0))
        if saved_rate != 1.0:
            self.playback.set_rate(saved_rate)
        self._rate = saved_rate

    # ------------------------------------------------------------------
    # UI KURULUMU
    # ------------------------------------------------------------------
    def _build_ui(self, accent: str):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(BAR_SIDE_MARGIN, 0, BAR_SIDE_MARGIN, BAR_BOTTOM_MARGIN)

        # 1) Dış "yüzen kart" katmanı: düz arka plan + karartma + elevation
        self.bg_frame = QFrame()
        self.bg_frame.setObjectName("PlayerBarBg")
        self.bg_frame.setStyleSheet(f"""
            #PlayerBarBg {{
                background-color: #100e1a;
                border-radius: {BAR_RADIUS}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self.bg_frame)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.bg_frame.setGraphicsEffect(shadow)

        # Karartma + hafif mor ton
        self.overlay = QWidget(self.bg_frame)
        self.overlay.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(12, 10, 22, 0.86), stop:1 rgba(10, 8, 18, 0.92));
            border-radius: {BAR_RADIUS}px;
        """)
        frame_layout = QVBoxLayout(self.bg_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(self.overlay)
        outer_layout.addWidget(self.bg_frame)

        root = QHBoxLayout(self.overlay)
        root.setContentsMargins(CONTENT_PADDING_H, CONTENT_PADDING_V, CONTENT_PADDING_H, CONTENT_PADDING_V)
        root.setSpacing(18)

        root.addLayout(self._build_now_playing(), 0)
        root.addLayout(self._build_center(accent), 1)
        root.addLayout(self._build_right(accent), 0)

        # app_window.py'nin toggle_shuffle/cycle_repeat çağırdığı buton referansları
        # artık gerçek, görünür butonlar (önceden gizliydi).

    # -- SOL BÖLÜM: kapak + başlık/sanatçı + beğen -----------------------
    def _build_now_playing(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(12)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self._cover_opacity = QGraphicsOpacityEffect(self.cover_label)
        self._cover_opacity.setOpacity(1.0)
        self.cover_label.setGraphicsEffect(self._cover_opacity)
        self._cover_fade = QPropertyAnimation(self._cover_opacity, b"opacity", self)
        self._cover_fade.setDuration(220)
        self._cover_fade.setStartValue(0.35)
        self._cover_fade.setEndValue(1.0)
        self._apply_cover_placeholder("?")
        layout.addWidget(self.cover_label)

        self.now_box = _ClickableBox()
        self.now_box.setFixedWidth(NOW_INFO_WIDTH_FULL)
        self.now_box.setCursor(Qt.PointingHandCursor)
        self.now_box.setToolTip("Çalan şarkının listedeki yerine git")
        self.now_box.clicked.connect(self.jumpToPlayingRequested.emit)

        now_col = QVBoxLayout(self.now_box)
        now_col.setContentsMargins(0, 0, 0, 0)
        now_col.setSpacing(3)
        now_col.setAlignment(Qt.AlignVCenter)

        now_font = QFont()
        now_font.setBold(True)
        now_font.setPointSize(11)
        self.now_label = QLabel("Henüz şarkı seçilmedi")
        self.now_label.setFont(now_font)
        self.now_label.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        now_col.addWidget(self.now_label)

        self.now_sub_label = QLabel("YouTube Stream")
        self.now_sub_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; font-size: 11px;")
        now_col.addWidget(self.now_sub_label)

        layout.addWidget(self.now_box)

        self.like_btn = IconButton("heart", 26, 14, color=ICON_MUTED, active_color="#ff6b8a")
        self.like_btn.setToolTip("Beğen")
        self.like_btn.clicked.connect(self._toggle_like_current)
        layout.addWidget(self.like_btn, alignment=Qt.AlignVCenter)

        self._now_title_raw = "Henüz şarkı seçilmedi"
        self._now_sub_raw = "YouTube Stream"
        return layout

    # -- ORTA BÖLÜM: playback controls (üst) + progress (alt) ------------
    def _build_center(self, accent: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)
        col.setAlignment(Qt.AlignVCenter)

        # -- Üst satır: shuffle - prev - play - next - repeat, ortalanmış
        transport_row = QHBoxLayout()
        transport_row.setSpacing(14)
        transport_row.addStretch(1)

        self.shuffle_btn = IconButton("shuffle", SECONDARY_BTN_SIZE, ICON_SECONDARY,
                                       color=ICON_MUTED, active_color=accent)
        self.shuffle_btn.setToolTip("Karışık çal")
        self.shuffle_btn.clicked.connect(self._toggle_shuffle)
        transport_row.addWidget(self.shuffle_btn)

        self.prev_btn = IconButton("prev", TRANSPORT_BTN_SIZE, ICON_TRANSPORT, color=TEXT_PRIMARY)
        self.prev_btn.setToolTip("Önceki")
        self.prev_btn.clicked.connect(self.playback.play_previous)
        transport_row.addWidget(self.prev_btn)

        self.play_btn = IconButton("play", PLAY_BTN_SIZE, ICON_PLAY, color=TEXT_PRIMARY)
        self.play_btn.setObjectName("PBPlayBtn")
        self.play_btn.setToolTip("Oynat / Duraklat")
        self.play_btn.clicked.connect(self.playback.toggle_play_pause)
        self._style_play_btn(accent)
        transport_row.addWidget(self.play_btn)

        self.next_btn = IconButton("next", TRANSPORT_BTN_SIZE, ICON_TRANSPORT, color=TEXT_PRIMARY)
        self.next_btn.setToolTip("Sonraki")
        self.next_btn.clicked.connect(self.playback.play_next)
        transport_row.addWidget(self.next_btn)

        self.repeat_btn = IconButton("repeat", SECONDARY_BTN_SIZE, ICON_SECONDARY,
                                      color=ICON_MUTED, active_color=accent)
        self.repeat_btn.setToolTip("Tekrarla")
        self.repeat_btn.clicked.connect(self._cycle_repeat)
        transport_row.addWidget(self.repeat_btn)

        transport_row.addStretch(1)
        col.addLayout(transport_row)

        # -- Alt satır: current time - progress slider (+ arka planda soluk
        #    waveform) - total time
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)

        self.current_time_label = QLabel("00:00")
        self.current_time_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; font-size: 11px;")
        self.current_time_label.setFixedWidth(34)
        progress_row.addWidget(self.current_time_label)

        wave_host = QWidget()
        wave_host.setFixedHeight(20)
        wave_stack = QStackedLayout(wave_host)
        wave_stack.setContentsMargins(0, 0, 0, 0)
        wave_stack.setStackingMode(QStackedLayout.StackAll)

        waveform_strip = WaveformStrip(accent)
        waveform_strip.setFixedHeight(20)
        wave_stack.addWidget(waveform_strip)
        self.waveform_strip = _DualWaveform(waveform_strip)

        self.time_slider = ClickSlider(Qt.Horizontal)
        self.time_slider.setObjectName("TimeSlider")
        self.time_slider.setRange(0, 1000)
        self.time_slider.sliderPressed.connect(self._on_slider_press)
        self.time_slider.sliderReleased.connect(self._on_slider_release)
        self.time_slider.setStyleSheet(self._time_slider_qss(accent))
        wave_stack.addWidget(self.time_slider)
        wave_stack.setCurrentWidget(self.time_slider)

        progress_row.addWidget(wave_host, stretch=1)

        self.total_time_label = QLabel("00:00")
        self.total_time_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; font-size: 11px;")
        self.total_time_label.setFixedWidth(34)
        self.total_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_row.addWidget(self.total_time_label)

        col.addLayout(progress_row)
        return col

    # -- SAĞ BÖLÜM: queue, lyrics, volume (hover-compact), diğerleri (menü) -
    def _build_right(self, accent: str) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignVCenter)

        self.queue_btn = IconButton("queue", RIGHT_BTN_SIZE, ICON_RIGHT, color=ICON_MUTED)
        self.queue_btn.setToolTip("Sıradaki")
        self.queue_btn.clicked.connect(self.queueRequested.emit)
        layout.addWidget(self.queue_btn)

        self.lyrics_btn = IconButton("lyrics", RIGHT_BTN_SIZE, ICON_RIGHT, color=ICON_MUTED)
        self.lyrics_btn.setToolTip("Sözler paneli")
        self.lyrics_btn.clicked.connect(self.lyricsRequested.emit)
        layout.addWidget(self.lyrics_btn)

        self.karaoke_btn = IconButton("fullscreen", RIGHT_BTN_SIZE, ICON_RIGHT, color=ICON_MUTED)
        self.karaoke_btn.setToolTip("Canlı Karaoke & Tam Ekran (F11)")
        self.karaoke_btn.clicked.connect(self.karaokeRequested.emit)
        layout.addWidget(self.karaoke_btn)

        # Volume: ikon her zaman görünür, slider sadece hover'da genişler
        volume_wrap = QHBoxLayout()
        volume_wrap.setSpacing(6)

        self.volume_icon_btn = IconButton("volume", RIGHT_BTN_SIZE, ICON_RIGHT, color=ICON_MUTED)
        self.volume_icon_btn.setToolTip("Ses seviyesi")
        self.volume_icon_btn.setEnabled(False)  # sadece görsel gösterge; slider işlevi taşır
        volume_wrap.addWidget(self.volume_icon_btn)

        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedHeight(RIGHT_BTN_SIZE)
        self.volume_slider.setStyleSheet(self._volume_slider_qss(accent))
        self.volume_slider.valueChanged.connect(self.playback.change_volume)
        self.volume_slider.valueChanged.connect(self._on_volume_value_changed)
        volume_wrap.addWidget(self.volume_slider)

        volume_host = _HoverRevealBox(self.volume_slider, VOLUME_COLLAPSED_W, VOLUME_EXPANDED_W)
        volume_host.setLayout(volume_wrap)
        layout.addWidget(volume_host)

        self.more_btn = IconButton("more", RIGHT_BTN_SIZE, ICON_RIGHT, color=ICON_MUTED)
        self.more_btn.setToolTip("Uyku zamanlayıcısı ve çalma hızı")
        self.more_btn.clicked.connect(self._show_more_menu)
        layout.addWidget(self.more_btn)

        return layout

    # ------------------------------------------------------------------
    # STİLLER (merkezi, tekrarsız)
    # ------------------------------------------------------------------
    def _style_play_btn(self, accent: str):
        self.play_btn.setStyleSheet(f"""
            QPushButton#PBPlayBtn {{
                background: rgba(255, 255, 255, 0.06);
                border: 2px solid {accent};
                border-radius: {PLAY_BTN_SIZE // 2}px;
            }}
            QPushButton#PBPlayBtn:hover {{
                background: rgba(255, 255, 255, 0.14);
            }}
            QPushButton#PBPlayBtn:disabled {{
                border: 2px solid rgba(255, 255, 255, 0.25);
            }}
        """)

    @staticmethod
    def _icon_btn_hover_qss() -> str:
        return """
            QPushButton#PBIconBtn {
                background: transparent;
                border: none;
                border-radius: 8px;
            }
            QPushButton#PBIconBtn:hover {
                background: rgba(255, 255, 255, 0.08);
            }
        """

    @staticmethod
    def _time_slider_qss(accent: str) -> str:
        return f"""
            QSlider {{ background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(255, 255, 255, 0.16);
                height: 3px;
                border-radius: 1.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {accent};
                height: 3px;
                border-radius: 1.5px;
            }}
            QSlider::add-page:horizontal {{
                background: rgba(255, 255, 255, 0.16);
                height: 3px;
                border-radius: 1.5px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                border: 2px solid {accent};
                width: 10px;
                margin: -4.5px 0;
                border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{
                width: 13px;
                margin: -6px 0;
                border-radius: 7px;
            }}
        """

    @staticmethod
    def _volume_slider_qss(accent: str) -> str:
        return f"""
            QSlider {{ background: transparent; }}
            QSlider::groove:horizontal {{
                background: rgba(255, 255, 255, 0.20);
                height: 3px;
                border-radius: 1.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {accent};
                height: 3px;
                border-radius: 1.5px;
            }}
            QSlider::handle:horizontal {{
                background: white;
                width: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }}
        """

    # ------------------------------------------------------------------
    # SİNYAL BAĞLANTILARI (PlaybackEngine <-> PlayerBar)
    # ------------------------------------------------------------------
    def _wire_signals(self):
        self.setStyleSheet(self._icon_btn_hover_qss())

        # Kayıtlı ses seviyesini geri yükle (eskiden her açılışta 80'e sıfırlanıyordu)
        self.playback.change_volume(int(self.playback.settings.get("_volume", 80)))
        self.playback.volumeChanged.connect(self.volume_slider.setValue)
        self.playback.songLoading.connect(self._on_song_loading)
        self.playback.songStarted.connect(self._on_song_started)
        self.playback.playStateChanged.connect(self._on_play_state)
        self.playback.positionChanged.connect(self._on_position)
        self.playback.playError.connect(self._on_play_error)
        self.playback.shuffleChanged.connect(self._on_shuffle_changed)
        self.playback.radioStarted.connect(self._on_radio_started)
        self.playback.radioStopped.connect(self._on_radio_stopped)
        self.playback.store.playlistsChanged.connect(self._sync_like_state)
        if self.thumbnails is not None:
            self.thumbnails.thumbnailReady.connect(self._on_thumbnail_ready)

    # ------------------------------------------------------------------
    # ACCENT (dinamik tema)
    # ------------------------------------------------------------------
    def set_accent(self, color: str):
        """Dinamik tema değiştiğinde (kapaktan çıkarılan renk ya da Ayarlar'dan
        seçilen tema) slider, play butonu ve aktif toggle renklerini günceller.
        """
        self._accent = color
        self.time_slider.setStyleSheet(self._time_slider_qss(color))
        self.volume_slider.setStyleSheet(self._volume_slider_qss(color))
        self._style_play_btn(color)
        self.shuffle_btn.set_color(ICON_MUTED, color)
        self.repeat_btn.set_color(ICON_MUTED, color)

    # ------------------------------------------------------------------
    # RESPONSIVE DAVRANIŞ
    # ------------------------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        w = self.width()
        self.now_sub_label.setVisible(w >= BREAKPOINT_HIDE_SUBTITLE)
        self._now_info_width = (
            NOW_INFO_WIDTH_FULL if w >= BREAKPOINT_HIDE_SUBTITLE else NOW_INFO_WIDTH_COMPACT)
        self.now_box.setFixedWidth(self._now_info_width)
        show_secondary = w >= BREAKPOINT_HIDE_SECONDARY
        self.shuffle_btn.setVisible(show_secondary)
        self.repeat_btn.setVisible(show_secondary)
        self._apply_title_elide()

    def _apply_title_elide(self):
        from PySide6.QtGui import QFontMetrics
        # now_box.width() bu event içinde henüz yeni değere ulaşmamış olabilir
        # (layout bir sonraki döngüde uygulanır); bu yüzden az önce ATANAN
        # hedef genişliği kullanıyoruz, canlı widget genişliğini değil.
        target_width = getattr(self, "_now_info_width", NOW_INFO_WIDTH_FULL)
        fm_title = QFontMetrics(self.now_label.font())
        self.now_label.setText(fm_title.elidedText(self._now_title_raw, Qt.ElideRight, target_width))
        if self.now_sub_label.isVisible():
            fm_sub = QFontMetrics(self.now_sub_label.font())
            self.now_sub_label.setText(
                fm_sub.elidedText(self._now_sub_raw, Qt.ElideRight, target_width))

    # ------------------------------------------------------------------
    # "DAHA FAZLA" MENÜSÜ — uyku zamanlayıcısı + çalma hızı
    # (nadiren kullanılan ayarlar; artık ayrı sabit butonlar yerine tek
    # menüde. Fonksiyonellik birebir korunuyor.)
    # ------------------------------------------------------------------
    def _show_more_menu(self):
        menu = QMenu(self)

        sleep_label = "Uyku Zamanlayıcısı"
        if self.sleep_timer.active:
            sleep_label += f" (kalan {max(1, round(self.sleep_timer.remaining_seconds() / 60))} dk)"
        sleep_menu = menu.addMenu(sleep_label)
        for label, minutes in self.SLEEP_OPTIONS:
            sleep_menu.addAction(label).setData(("sleep", minutes))
        sleep_menu.addAction("Özel süre…").setData(("custom", 0))
        fade_action = sleep_menu.addAction("Sesi kademeli azalt")
        fade_action.setCheckable(True)
        fade_action.setChecked(bool(self.playback.settings.get("sleep_fade_enabled", True)))
        fade_action.setData(("fade", 0))
        if self.sleep_timer.active:
            sleep_menu.addSeparator()
            sleep_menu.addAction("Zamanlayıcıyı iptal et").setData(("cancel", 0))

        speed_menu = menu.addMenu(f"Çalma Hızı ({self._rate_text(self._rate)})")
        for label, rate in self.SPEED_OPTIONS:
            action = speed_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(abs(rate - self._rate) < 0.01)
            action.setData(rate)

        radio_action = None
        if self.playback.current_song:
            menu.addSeparator()
            radio_action = menu.addAction("📻 Şarkı Radyosunu Başlat")

        chosen = menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomRight()))
        if chosen is None:
            return
        if radio_action is not None and chosen == radio_action:
            if self.playback.current_song:
                self.startRadioRequested.emit(self.playback.current_song)
            return
        data = chosen.data()
        if chosen.parent() is sleep_menu:
            action, minutes = data
            if action == "sleep":
                self._start_sleep(minutes)
            elif action == "custom":
                value, ok = QInputDialog.getInt(
                    self, "Uyku Zamanlayıcısı", "Kaç dakika sonra durdurulsun?", 20, 1, 720)
                if ok:
                    self._start_sleep(value)
            elif action == "fade":
                self.playback.settings["sleep_fade_enabled"] = chosen.isChecked()
            elif action == "cancel":
                self.sleep_timer.cancel()
        elif chosen.parent() is speed_menu:
            self._rate = float(data)
            self.playback.set_rate(self._rate)

    def _start_sleep(self, minutes: int):
        self.sleep_timer.start(minutes, fade=bool(self.playback.settings.get("sleep_fade_enabled", True)))
        self.playback.store.statusMessage.emit(f"😴 Müzik {minutes} dakika sonra duracak.", "info")

    def _on_sleep_finished(self):
        QApplication.beep()
        self.playback.store.statusMessage.emit(
            "Uyku zamanlayıcısı doldu — müzik duraklatıldı.", "info")

    @staticmethod
    def _rate_text(rate: float) -> str:
        return f"{rate:g}x"

    # ------------------------------------------------------------------
    # ŞARKI / KAPAK DURUMU
    # ------------------------------------------------------------------
    def _apply_cover_placeholder(self, seed: str):
        self.cover_label.setPixmap(QPixmap())
        self.cover_label.setStyleSheet(
            f"background: {cover_color_for(seed)}; border-radius: {COVER_RADIUS}px;")

    @staticmethod
    def _square_cover(pm: QPixmap, size: int) -> QPixmap:
        """Kaynak görsel kare olmasa bile (ör. 16:9 video kapağı) TAM KARE ve
        tam `size`x`size` bir pixmap döndürür.

        Önceki sürüm sadece `.scaled(size, size, KeepAspectRatioByExpanding)`
        kullanıyordu; bu, en/boy oranı 1:1 olmayan kapaklarda label'ın
        boyutundan büyük/dikdörtgen bir pixmap üretip PlayerBar'ın dışına
        taşmasına (görsel bug) yol açıyordu. Burada önce genişleterek
        ölçekleyip ardından ortadan tam kare kırpıyoruz, böylece sonuç her
        zaman kesin size x size olur ve taşma imkânsız hale gelir.
        """
        scaled = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        return scaled.copy(x, y, size, size)

    def _fade_in_cover(self):
        self._cover_fade.stop()
        if not self.isVisible():
            self._cover_opacity.setOpacity(1.0)
            return
        self._cover_opacity.setOpacity(0.35)
        self._cover_fade.start()

    def hideEvent(self, event):  # noqa: N802
        self._cover_fade.stop()
        self._cover_opacity.setOpacity(1.0)
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._cover_fade.stop()
        self.sleep_timer.cancel()
        super().closeEvent(event)

    def _set_now_text(self, title: str, subtitle: str):
        self._now_title_raw = title
        self._now_sub_raw = subtitle
        self._apply_title_elide()

    def _set_current_song(self, song: dict | None):
        if not song:
            self._apply_cover_placeholder("?")
            self._set_now_text("Henüz şarkı seçilmedi", "YouTube Stream")
            self.like_btn.set_active(False)
            self._current_key = None
            return
        self._current_key = song.get("webpage_url")
        clean_title, clean_artist = parse_track_and_artist(
            song.get("title", ""),
            song.get("uploader", "") or "YouTube Stream",
            song,
        )
        self._set_now_text(clean_title, clean_artist)
        self.like_btn.set_active(bool(song.get("liked")))
        pm = self.thumbnails.pixmap_for(song, COVER_SIZE) if self.thumbnails else None
        if pm is not None and not pm.isNull():
            self.cover_label.setStyleSheet("background: transparent;")
            self.cover_label.setPixmap(self._square_cover(pm, COVER_SIZE))
        else:
            self._apply_cover_placeholder(song.get("title", "?"))
        self._fade_in_cover()

    def _toggle_like_current(self):
        pl = self.playback.playing_playlist
        songs = self.playback.store.playlists.get(pl, []) if pl else []
        idx = self.playback.current_index
        if not pl or not (0 <= idx < len(songs)):
            return
        self.playback.store.toggle_like(pl, idx)
        self._sync_like_state()

    def _sync_like_state(self):
        pl = self.playback.playing_playlist
        songs = self.playback.store.playlists.get(pl, []) if pl else []
        idx = self.playback.current_index
        if pl and 0 <= idx < len(songs):
            self.like_btn.set_active(bool(songs[idx].get("liked")))

    def _on_play_error(self, playlist_name, index):
        self.play_btn.set_kind("play")
        self.play_btn.setEnabled(True)
        songs = self.playback.store.playlists.get(playlist_name, [])
        if 0 <= index < len(songs):
            self._set_now_text(songs[index].get("title", "Henüz şarkı seçilmedi"), self._now_sub_raw)
        elif self._now_title_raw.startswith("Yükleniyor: "):
            self._set_now_text(self._now_title_raw[len("Yükleniyor: "):], self._now_sub_raw)

    def _on_thumbnail_ready(self, key: str):
        if key != self._current_key or self.thumbnails is None:
            return
        pl = self.playback.playing_playlist
        songs = self.playback.store.playlists.get(pl, []) if pl else []
        idx = self.playback.current_index
        if 0 <= idx < len(songs):
            pm = self.thumbnails.pixmap_for(songs[idx], COVER_SIZE)
            if pm is not None and not pm.isNull():
                self.cover_label.setStyleSheet("background: transparent;")
                self.cover_label.setPixmap(self._square_cover(pm, COVER_SIZE))
                self._fade_in_cover()

    def _on_song_loading(self, playlist_name, index, song):
        title = song.get("title", "")
        self._set_now_text(f"Yükleniyor: {title}", self._now_sub_raw)
        dur_ms = max(0, int((song.get("duration") or 0) * 1000))
        self._total_ms = dur_ms
        if not self._seeking:
            self.time_slider.setValue(0)
            self.current_time_label.setText("00:00")
            self.total_time_label.setText(format_time(dur_ms))
        self.play_btn.setEnabled(False)

    def _on_song_started(self, playlist_name, index, song, is_offline):
        self._set_current_song(song)
        if song.get("local_path"):
            source = "Yerel dosya"
        elif is_offline:
            source = "Çevrimdışı"
        else:
            source = "YouTube Stream"
        self._set_now_text(self._now_title_raw, f"{source} • {playlist_name}")
        dur_ms = max(0, int((song.get("duration") or 0) * 1000))
        self._total_ms = dur_ms
        if not self._seeking:
            self.time_slider.setValue(0)
            self.current_time_label.setText("00:00")
            self.total_time_label.setText(format_time(dur_ms))
        self.play_btn.set_kind("pause")
        self.play_btn.setEnabled(True)
        self.waveform_strip.set_playing(True)

    def _on_radio_started(self, station: dict):
        name = station.get("name", "?")
        self._set_now_text(name, "Canlı Radyo")
        self.current_time_label.setText("CANLI")
        self.total_time_label.setText("")
        self.time_slider.setValue(0)
        self.play_btn.set_kind("pause")
        self.play_btn.setEnabled(True)
        self.waveform_strip.set_playing(True)

    def _on_radio_stopped(self):
        self._set_current_song(None)
        self.current_time_label.setText("00:00")
        self.total_time_label.setText("00:00")
        self.waveform_strip.set_playing(False)

    def _on_play_state(self, playing: bool):
        self.play_btn.set_kind("pause" if playing else "play")
        self.play_btn.setEnabled(True)
        self.waveform_strip.set_playing(playing)

    def _on_position(self, current_ms: int, total_ms: int):
        if total_ms > 0:
            self._total_ms = total_ms
        if self._seeking or self.playback.radio_playing is not None:
            return
        if self._total_ms > 0:
            value = int((current_ms / self._total_ms) * 1000)
            self.time_slider.setValue(max(0, min(1000, value)))
            self.current_time_label.setText(format_time(current_ms))
            self.total_time_label.setText(format_time(total_ms))

    def _on_slider_press(self):
        self._seeking = True

    def _on_slider_release(self):
        if self._total_ms > 0:
            seek_ms = (self.time_slider.value() / 1000) * self._total_ms
            self.playback.seek(int(seek_ms))
        self._seeking = False

    def _toggle_shuffle(self):
        active = self.playback.toggle_shuffle()
        self.shuffle_btn.set_active(active)

    def _on_shuffle_changed(self, active: bool):
        self.shuffle_btn.set_active(active)

    def _cycle_repeat(self):
        mode = self.playback.cycle_repeat()
        self.repeat_btn.set_kind("repeat_one" if mode == "one" else "repeat")
        self.repeat_btn.set_active(mode != "off")

    def _on_volume_value_changed(self, value: int):
        self.volume_icon_btn.set_kind("volume_muted" if value == 0 else "volume")

"""Tema paletinden (helpers.constants.Theme) global QSS üretir.

objectName tabanlı QSS seçicileri kullanılır — tema değişikliği tek bir
setStyleSheet() çağrısıyla tüm uygulamaya yayılır. Spotify benzeri koyu,
yuvarlatılmış, pill navigasyonlu bir görünüm hedeflenir.
"""
from __future__ import annotations

from mustiefly_qt.helpers.constants import Theme


def build_qss(t: Theme) -> str:
    return f"""
    QMainWindow, QDialog, #EqualizerWindow, #LyricsWindow {{ background: {t.bg_main}; }}
    QWidget {{ color: {t.text}; font-family: 'Segoe UI', sans-serif; font-size: 13px; }}

    #Sidebar {{ background: {t.bg_sidebar}; border-right: 1px solid {t.bg_card}; }}
    #PlayerBar {{
        background: {t.bg_playerbar}; border-top: 1px solid {t.bg_row_hover};
        border-radius: 0px;
    }}
    #NowPlayingPanel {{
        background: {t.bg_sidebar}; border-left: 1px solid {t.bg_card};
        border-top-left-radius: 24px; border-bottom-left-radius: 24px;
    }}
    #TopBar {{ background: {t.bg_main}; }}
    #Card, #SongRow, #PlaylistCard {{ background: {t.bg_card}; border-radius: 20px; }}
    #StatCard {{
        background: {t.bg_card}; border-left: 4px solid {t.accent};
        border-radius: 22px;
    }}
    #SongRow {{ border-radius: 18px; }}
    #SongRow:hover {{ background: {t.bg_row_hover}; }}
    #SongRow[current="true"] {{ background: {t.accent}; }}
    #PlaylistCard {{ border-radius: 24px; }}
    #PlaylistCard:hover {{ background: {t.bg_row_hover}; }}
    #HomeContent, #DiscoveryContent, #ArtistDetailView, #ArtistContent {{ background: {t.bg_main}; }}
    #HeroCard {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t.bg_card}, stop:1 {t.bg_main});
        border-radius: 16px; border: 1px solid {t.bg_row_hover};
    }}
    #DiscoveryCard {{ background: transparent; border-radius: 14px; }}
    #DiscoveryCard:hover {{ background: {t.bg_card}; }}
    #PlaylistBanner {{
        border-radius: 24px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t.accent}, stop:1 {t.bg_card});
    }}

    QLabel#PlaylistRowName {{ font-size: 12px; background: transparent; }}
    QLabel#PlaylistRowName[active="true"] {{ color: {t.accent}; font-weight: bold; }}
    QLabel#PlaylistRowCount {{ color: {t.text_dim}; font-size: 11px; background: transparent; }}

    QPushButton#ColHeader {{
        color: {t.text_dim}; font-weight: bold; padding: 5px 12px; font-size: 11px;
        border-radius: 12px;
    }}
    QPushButton#ColHeader:hover {{ color: {t.text}; background: rgba(255,255,255,0.05); }}
    QPushButton#ColHeader[active="true"] {{ color: {t.accent}; }}

    QLabel#Muted {{ color: {t.text_dim}; }}
    QLabel#Accent {{ color: {t.accent}; font-weight: bold; }}
    QLabel#SectionHeader {{
        color: {t.text_dim}; font-size: 11px; font-weight: bold; letter-spacing: 2px;
    }}
    QLabel#BrandIcon {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t.accent}, stop:1 {t.accent_dark});
        color: white;
        border: 2px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px; 
        font-size: 20px;
    }}
    QLabel#BrandTitle {{ font-size: 17px; font-weight: bold; }}

    /* ============================================================
       AVATAR — ring efektli, tam oval
       ============================================================ */
    QLabel#Avatar {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t.accent}, stop:1 {t.accent_dark});
        color: white; 
        border: 2px solid rgba(255, 255, 255, 0.18);
        border-radius: 20px;
        font-weight: bold; 
        font-size: 15px;
        letter-spacing: 1px;
    }}

    QLabel#NowPlayingHeader {{
        color: {t.text_dim}; font-size: 11px; font-weight: bold; letter-spacing: 2px;
    }}

    /* ============================================================
       GENEL BUTONLAR
       ============================================================ */
    QPushButton {{
        background: transparent; 
        border: none; 
        color: {t.text}; 
        padding: 6px;
        border-radius: 12px;
    }}
    QPushButton:hover {{ color: {t.accent}; }}
    QPushButton:disabled {{ color: {t.text_dim}; }}

    /* ============================================================
       PRIMARY — gradient + PILL (tam oval) + hover
       Yükseklik SABİT tutulur: border-radius'un her platformda/fontta
       gerçek bir "hap" (pill) şekli vermesi, köşeli/kaba durmaması için.
       ============================================================ */
    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t.accent}, stop:1 {t.accent_dark});
        color: white; 
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 20px;
        font-weight: 600; 
        font-size: 13px;
        padding: 0px 22px;
        min-height: 40px;
        max-height: 40px;
        letter-spacing: 0.3px;
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t.accent_dark}, stop:1 {t.accent});
        border: 1px solid rgba(255, 255, 255, 0.25);
    }}
    QPushButton#Primary:pressed {{
        background: {t.accent_dark};
    }}
    QPushButton#Primary:disabled {{ 
        background: {t.bg_row_hover}; 
        color: {t.text_dim}; 
        border: 1px solid transparent;
    }}

    /* ============================================================
       SECONDARY — cam efektli + PILL (tam oval)
       ============================================================ */
    QPushButton#Secondary {{
        background: rgba(255, 255, 255, 0.07);
        color: {t.text};
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 24px;
        font-weight: 600; 
        font-size: 13px;
        padding: 11px 24px;
    }}
    QPushButton#Secondary:hover {{
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid {t.accent};
        color: {t.accent};
    }}
    QPushButton#Secondary:pressed {{
        background: rgba(255, 255, 255, 0.05);
    }}

    /* ============================================================
       NAV BUTTON — aktif durumda gradient + daha oval köşe
       ============================================================ */
    QPushButton#NavButton {{
        text-align: left; 
        padding: 11px 18px; 
        border-radius: 16px;
        color: {t.text_dim}; 
        font-weight: 600;
        border: 1px solid transparent;
    }}
    QPushButton#NavButton:hover {{ 
        background: {t.bg_card}; 
        color: {t.text};
        border: 1px solid rgba(255, 255, 255, 0.05);
    }}
    QPushButton#NavButton[active="true"] {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t.accent}, stop:1 {t.accent_dark});
        color: white;
        border: 1px solid rgba(255, 255, 255, 0.12);
    }}

    QPushButton#LinkButton {{ 
        color: {t.accent}; font-weight: bold; text-align: left; 
        padding: 6px 10px; border-radius: 10px;
    }}
    QPushButton#LinkButton:hover {{ 
        color: {t.accent_dark}; 
        background: rgba(255, 255, 255, 0.04);
    }}

    /* ============================================================
       ICON SQUARE — üst çubuk ikonları, TAM DAİRE
       ============================================================ */
    QPushButton#IconSquare {{
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 21px; 
        padding: 0px; 
        min-width: 42px; max-width: 42px;
        min-height: 42px; max-height: 42px;
    }}
    QPushButton#IconSquare:hover {{ 
        background: {t.accent};
        border: 1px solid {t.accent};
        color: white;
    }}

    /* ============================================================
       ROUND PLAY — büyük çalma butonu, TAM DAİRE
       ============================================================ */
    QPushButton#RoundPlay {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {t.accent}, stop:0.5 {t.accent}, stop:1 {t.accent_dark});
        color: white; 
        border: 2px solid rgba(255, 255, 255, 0.15);
        border-radius: 30px;
        font-size: 20px; 
        font-weight: bold; 
        padding: 0px;
        min-width: 60px; max-width: 60px; 
        min-height: 60px; max-height: 60px;
    }}
    QPushButton#RoundPlay:hover {{
        border: 2px solid rgba(255, 255, 255, 0.35);
    }}
    QPushButton#RoundPlay:pressed {{
        background: {t.accent_dark};
        border: 2px solid rgba(255, 255, 255, 0.5);
    }}

    /* ============================================================
       ROUND SMALL — önceki/sonraki, TAM DAİRE
       ============================================================ */
    QPushButton#RoundSmall {{
        background: rgba(255, 255, 255, 0.07); 
        color: {t.text}; 
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 22px;
        font-size: 15px; 
        padding: 0px;
        min-width: 44px; max-width: 44px; 
        min-height: 44px; max-height: 44px;
    }}
    QPushButton#RoundSmall:hover {{ 
        background: {t.accent}; 
        color: white;
        border: 1px solid {t.accent};
    }}
    QPushButton#RoundSmall:pressed {{
        background: {t.accent_dark};
    }}

    /* ============================================================
       CHIP — filtre rozetleri, PILL
       ============================================================ */
    QPushButton#Chip {{
        background: {t.bg_card}; 
        border: 1px solid rgba(255, 255, 255, 0.06); 
        border-radius: 16px;
        padding: 6px 16px; 
        color: {t.text_dim};
        font-size: 12px;
    }}
    QPushButton#Chip:hover {{ 
        color: {t.accent}; 
        border: 1px solid {t.accent};
    }}

    /* ============================================================
       SORT PILL — sıralama rozeti, PILL
       ============================================================ */
    QPushButton#SortPill {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t.accent}, stop:1 {t.accent_dark});
        color: white; 
        border: 1px solid rgba(255,255,255,0.12); 
        border-radius: 14px;
        font-size: 11px; 
        font-weight: bold; 
        padding: 6px 16px;
    }}
    QPushButton#SortPill:hover {{ 
        border: 1px solid rgba(255,255,255,0.3);
    }}

    QPushButton#RowPlay {{
        color: {t.accent}; font-weight: bold; padding: 0px;
        min-width: 24px; max-width: 24px;
        border-radius: 12px;
    }}
    QPushButton#RowPlay:hover {{ color: {t.accent_dark}; }}
    QPushButton[mode_on="true"] {{
        color: {t.accent}; border-bottom: 2px solid {t.accent};
    }}

    /* ============================================================
       INPUT ALANLARI — daha oval köşeler
       ============================================================ */
    QLineEdit {{
        background: {t.bg_card}; 
        border: 1px solid {t.bg_card}; 
        border-radius: 16px;
        padding: 10px 18px; 
        color: {t.text};
    }}
    QLineEdit:focus {{ border: 1px solid {t.accent}; }}
    QLineEdit#TopSearch {{
        border-radius: 20px; padding: 10px 22px; font-size: 13px;
    }}

    QTextEdit {{
        background: {t.bg_card}; 
        border: 1px solid {t.bg_card}; 
        border-radius: 16px;
        padding: 10px; 
        color: {t.text};
    }}

    QComboBox {{
        background: {t.bg_card}; 
        border: 1px solid {t.bg_card}; 
        border-radius: 16px;
        padding: 9px 16px; 
        color: {t.text};
    }}
    QComboBox:hover {{ border: 1px solid {t.bg_row_hover}; }}
    QComboBox QAbstractItemView {{
        background: {t.bg_card}; 
        color: {t.text}; 
        selection-background-color: {t.bg_row_hover};
        border: 1px solid {t.bg_row_hover}; 
        border-radius: 12px;
        padding: 4px;
    }}

    QListWidget {{ background: transparent; border: none; }}
    QListWidget::item {{ border: none; padding: 0px; margin: 2px 0px; }}
    QListWidget::item:selected {{ background: transparent; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t.bg_row_hover}; border-radius: 4px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.text_dim}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; }}
    QScrollBar::handle:horizontal {{ background: {t.bg_row_hover}; border-radius: 4px; min-width: 24px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

    QSlider::groove:horizontal {{ 
        background: {t.bg_row_hover}; height: 6px; border-radius: 3px; 
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t.accent}, stop:1 {t.accent_dark});
        height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {t.text}; width: 14px; margin: -5px 0; border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: {t.accent}; }}
    QSlider#TimeSlider::groove:horizontal {{ background: transparent; height: 28px; }}
    QSlider#TimeSlider::handle:horizontal {{
        background: {t.text}; width: 3px; margin: 0px; border-radius: 2px;
    }}

    /* ============================================================
       MENÜ — daha oval köşeler
       ============================================================ */
    QMenu {{
        background: {t.bg_card}; 
        border: 1px solid {t.bg_row_hover}; 
        border-radius: 14px; 
        padding: 8px;
    }}
    QMenu::item {{ 
        padding: 8px 26px 8px 14px; 
        border-radius: 10px; 
    }}
    QMenu::item:selected {{ background: {t.bg_row_hover}; }}

    QMenuBar {{ background: {t.bg_sidebar}; }}
    QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: 8px; }}
    QMenuBar::item:selected {{ background: {t.bg_row_hover}; }}

    QStatusBar {{ color: {t.text_dim}; }}

    /* ============================================================
       SNACKBAR — oval uyarı kutusu
       ============================================================ */
    #Snackbar {{
        background: {t.bg_card}; 
        border: 1px solid {t.accent}; 
        border-radius: 18px;
    }}

    /* ============================================================
       PROGRESS BAR — oval bar
       ============================================================ */
    QProgressBar {{
        background: {t.bg_card}; 
        border: none; 
        border-radius: 7px;
        height: 12px; 
        text-align: center; 
        color: {t.text_dim};
    }}
    QProgressBar::chunk {{ 
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t.accent}, stop:1 {t.accent_dark}); 
        border-radius: 7px; 
    }}

    QSlider::groove:vertical {{ background: {t.bg_row_hover}; width: 6px; border-radius: 3px; }}
    QSlider::sub-page:vertical {{ background: {t.bg_row_hover}; }}
    QSlider::add-page:vertical {{ background: {t.bg_row_hover}; }}
    QSlider::handle:vertical {{
        background: {t.text}; width: 16px; height: 16px; margin: 0 -6px; border-radius: 8px;
    }}
    QSlider::handle:vertical:hover {{ background: {t.accent}; }}

    QCheckBox::indicator, QRadioButton::indicator {{ 
        width: 18px; height: 18px; border-radius: 9px;
    }}

    QToolTip {{
        background: {t.bg_card}; 
        color: {t.text}; 
        border: 1px solid {t.bg_row_hover};
        border-radius: 10px; 
        padding: 8px 12px;
    }}
    """

"""
Audifly Connect masaüstü diyaloğu:
Yerel web kumanda sunucusunu başlatır/durdurur, telefon kamerasıyla anında
okutulabilen QR kodu ve kopyalanabilir LAN adresini gösterir.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from mustiefly_qt.helpers.qr_encode import qr_to_qpixmap
from mustiefly_qt.helpers.win_theme import apply_dark_titlebar
from mustiefly_qt.services.connect_server import (
    AudiflyConnectService, request_windows_firewall_allow,
)


class AudiflyConnectDialog(QDialog):
    """QR kodlu telefon kumandası kontrol penceresi."""

    def __init__(self, service: AudiflyConnectService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("📱 Audifly Connect — Telefon Kumandası")
        self.setFixedWidth(440)
        apply_dark_titlebar(self, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        # Başlık
        title = QLabel("📱 Audifly Connect")
        tf = QFont()
        tf.setPixelSize(20)
        tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)

        desc = QLabel(
            "Telefonunun kamerasıyla QR kodu okut — hiçbir uygulama kurmadan "
            "tarayıcıdan müziği, sesi, kuyruğu ve çalma listelerini kontrol et."
        )
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # Durum rozeti
        self.status_badge = QLabel("")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setStyleSheet(
            "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
        )
        root.addWidget(self.status_badge)

        # QR Kartı
        qr_card = QFrame()
        qr_card.setObjectName("Card")
        qr_lay = QVBoxLayout(qr_card)
        qr_lay.setContentsMargins(18, 18, 18, 18)
        qr_lay.setAlignment(Qt.AlignCenter)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setMinimumSize(220, 220)
        self.qr_label.setStyleSheet(
            "background: #ffffff; border-radius: 14px; padding: 8px;"
        )
        qr_lay.addWidget(self.qr_label, alignment=Qt.AlignCenter)
        root.addWidget(qr_card)

        # URL satırı + Kopyala
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setReadOnly(True)
        self.url_edit.setPlaceholderText("Sunucu kapalı")
        url_row.addWidget(self.url_edit, stretch=1)

        self.copy_btn = QPushButton("📋 Kopyala")
        self.copy_btn.setObjectName("Secondary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_url)
        url_row.addWidget(self.copy_btn)
        root.addLayout(url_row)

        # Alt butonlar
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName("Primary")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_server)
        btn_row.addWidget(self.toggle_btn, stretch=1)

        self.rotate_btn = QPushButton("🔄 Yeni Token")
        self.rotate_btn.setObjectName("Secondary")
        self.rotate_btn.setCursor(Qt.PointingHandCursor)
        self.rotate_btn.setToolTip("Eski telefon oturumlarını geçersiz kılıp yeni QR kod üretir")
        self.rotate_btn.clicked.connect(self._rotate_token)
        btn_row.addWidget(self.rotate_btn)
        root.addLayout(btn_row)

        self.fw_btn = QPushButton("🛡️ Windows Güvenlik Duvarı İzni Ver")
        self.fw_btn.setObjectName("Secondary")
        self.fw_btn.setCursor(Qt.PointingHandCursor)
        self.fw_btn.setToolTip(
            "Telefon bağlanamıyorsa Windows Güvenlik Duvarı'nda Audifly Connect portunu açar"
        )
        self.fw_btn.clicked.connect(self._allow_firewall)
        self.fw_btn.setVisible(sys.platform == "win32")
        root.addWidget(self.fw_btn)

        tip = QLabel(
            "💡 Bilgisayar ve telefon aynı Wi-Fi/modem ağında olmalıdır. "
            "Ağın Windows'ta 'Ortak Ağ (Public)' ise yukarıdaki Güvenlik Duvarı butonuna tıkla."
        )
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        tip.setStyleSheet("font-size: 11px;")
        root.addWidget(tip)

        self.service.statusChanged.connect(self._on_status_changed)

        # Açılır açılmaz sunucuyu otomatik başlat
        if not self.service.is_running:
            ok, info = self.service.start()
            if not ok:
                self._show_error(info)
                return
        self._refresh_ui()

    def _on_status_changed(self, _running: bool, _url: str):
        self._refresh_ui()

    def _show_error(self, message: str):
        self.status_badge.setText(f"⚠️ {message}")
        self.status_badge.setStyleSheet(
            "background: rgba(255, 107, 138, 0.16); color: #ff8aa3; "
            "border: 1px solid rgba(255, 107, 138, 0.35); "
            "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
        )
        self.qr_label.setPixmap(self.qr_label.pixmap())
        self.qr_label.clear()
        self.qr_label.setText("Sunucu başlatılamadı")
        self.toggle_btn.setText("▶ Başlat")
        self.copy_btn.setEnabled(False)
        self.rotate_btn.setEnabled(False)

    def _refresh_ui(self):
        running = self.service.is_running
        url = self.service.url
        if running and url:
            self.status_badge.setText("🟢 Aktif — Aynı Wi-Fi'daki telefondan okut")
            self.status_badge.setStyleSheet(
                "background: rgba(72, 199, 142, 0.16); color: #5ce1a6; "
                "border: 1px solid rgba(72, 199, 142, 0.35); "
                "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
            )
            self.url_edit.setText(url)
            pm = qr_to_qpixmap(url, box_size=6, border=3)
            self.qr_label.setPixmap(pm)
            self.qr_label.setText("")
            self.toggle_btn.setText("⏹ Sunucuyu Durdur")
            self.copy_btn.setEnabled(True)
            self.rotate_btn.setEnabled(True)
        else:
            self.status_badge.setText("⚪ Kapalı — Başlatmak için aşağıdaki butona tıkla")
            self.status_badge.setStyleSheet(
                "background: rgba(255, 255, 255, 0.06); color: #b7b2cf; "
                "border: 1px solid rgba(255, 255, 255, 0.12); "
                "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
            )
            self.url_edit.setText("")
            self.qr_label.clear()
            self.qr_label.setText("QR kod sunucu açılınca\nburada görünür")
            self.qr_label.setStyleSheet(
                "background: rgba(255, 255, 255, 0.05); color: #9ea3b8; "
                "border-radius: 14px; padding: 16px; font-size: 13px;"
            )
            self.toggle_btn.setText("▶ Sunucuyu Başlat")
            self.copy_btn.setEnabled(False)
            self.rotate_btn.setEnabled(False)

        if running and url:
            self.qr_label.setStyleSheet(
                "background: #ffffff; border-radius: 14px; padding: 8px;"
            )

    def _toggle_server(self):
        if self.service.is_running:
            self.service.stop()
        else:
            ok, info = self.service.start()
            if not ok:
                self._show_error(info)

    def _rotate_token(self):
        self.service.rotate_token()
        self._refresh_ui()

    def _copy_url(self):
        url = self.service.url
        if url:
            QApplication.clipboard().setText(url)
            self.copy_btn.setText("✓ Kopyalandı")

    def _allow_firewall(self):
        port = getattr(self.service, "_port", 0)
        if not port:
            return
        if request_windows_firewall_allow(port):
            self.fw_btn.setText("✓ Güvenlik Duvarı İzni İstendi (Telefondan tekrar dene)")
        else:
            self.fw_btn.setText("⚠️ İzin iptal edildi veya başarısız")

    def done(self, result: int):
        try:
            self.service.statusChanged.disconnect(self._on_status_changed)
        except (RuntimeError, TypeError):
            pass
        super().done(result)

"""Sorun Bildir / Tanılama Raporu penceresi.

Kullanıcının (veya teknik olmayan bir arkadaşın) karşılaştığı hatayı tek tıkla
kopyalayıp geliştiriciye göndermesini sağlar. Rapor kişisel veri / parola / token
içermez; kullanıcı ana dizini `~` ile maskelenir (`helpers/diagnostics.py`).
"""
from __future__ import annotations

import os
import urllib.parse

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME, APP_VERSION
from mustiefly_qt.helpers.diagnostics import collect_diagnostics

ISSUES_URL = "https://github.com/mustie38/audifly/issues/new"


class DiagnosticsDialog(QDialog):
    def __init__(self, log_dir: str | None = None, error_text: str = "",
                 recent_errors: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.log_dir = log_dir
        self.error_text = error_text
        self.recent_errors = list(recent_errors or [])

        self.setWindowTitle(f"🩺 Sorun Bildir / Tanılama Raporu — {APP_DISPLAY_NAME}")
        self.resize(660, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("🩺 Sorun Bildir / Tanılama Raporu")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        hint = QLabel(
            "Aşağıdaki rapor sürüm, bileşen durumu ve son hata kayıtlarını içerir "
            "(parola, token veya kişisel klasör adı içermez). \"Raporu Kopyala\"ya "
            "basıp mesaj olarak gönderebilirsin."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        note_label = QLabel("Ne yaparken sorun oldu? (isteğe bağlı):")
        root.addWidget(note_label)

        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText(
            "Örn: Şarkıya tıkladığımda çalmadı ve altta kırmızı hata çıktı…")
        self.note_edit.setFixedHeight(68)
        self.note_edit.textChanged.connect(self._refresh_report)
        root.addWidget(self.note_edit)

        report_label = QLabel("Tanılama raporu:")
        root.addWidget(report_label)

        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed.setPointSize(9)
        self.report_view.setFont(fixed)
        root.addWidget(self.report_view, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        root.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.copy_btn = QPushButton("📋 Raporu Kopyala")
        self.copy_btn.setObjectName("Primary")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self.copy_report)
        btn_row.addWidget(self.copy_btn)

        self.save_btn = QPushButton("💾 Dosyaya Kaydet…")
        self.save_btn.setObjectName("Secondary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_report)
        btn_row.addWidget(self.save_btn)

        self.logs_btn = QPushButton("📁 Kayıt Klasörünü Aç")
        self.logs_btn.setObjectName("Secondary")
        self.logs_btn.setCursor(Qt.PointingHandCursor)
        self.logs_btn.setEnabled(bool(self.log_dir and os.path.isdir(self.log_dir)))
        self.logs_btn.clicked.connect(self._open_log_dir)
        btn_row.addWidget(self.logs_btn)

        self.issue_btn = QPushButton("🌐 GitHub'da Bildir")
        self.issue_btn.setObjectName("Secondary")
        self.issue_btn.setCursor(Qt.PointingHandCursor)
        self.issue_btn.clicked.connect(self._open_github_issue)
        btn_row.addWidget(self.issue_btn)

        btn_row.addStretch(1)

        close_btn = QPushButton("Kapat")
        close_btn.setObjectName("Secondary")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)
        self._refresh_report()

    def report_text(self) -> str:
        return self.report_view.toPlainText()

    def _refresh_report(self):
        text = collect_diagnostics(
            self.log_dir,
            error_text=self.error_text,
            user_note=self.note_edit.toPlainText(),
            recent_errors=self.recent_errors,
        )
        self.report_view.setPlainText(text)

    def copy_report(self) -> str:
        text = self.report_text()
        QGuiApplication.clipboard().setText(text)
        self.copy_btn.setText("✅ Kopyalandı!")
        self.status_label.setText("Rapor panoya kopyalandı — doğrudan yapıştırıp gönderebilirsin.")
        return text

    def save_report(self, target_path: str | None = None) -> bool:
        if not target_path:
            target_path, _ = QFileDialog.getSaveFileName(
                self, "Tanılama Raporunu Kaydet", "audifly-rapor.txt", "Metin Dosyası (*.txt)")
        if not target_path:
            return False
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(self.report_text())
            self.status_label.setText(f"Kaydedildi: {target_path}")
            return True
        except OSError as e:
            self.status_label.setText(f"Kaydedilemedi: {e}")
            return False

    def _open_log_dir(self):
        if self.log_dir and os.path.isdir(self.log_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_dir))

    def _open_github_issue(self):
        text = self.copy_report()
        body = text[:3500]  # URL uzunluk sınırını aşmamak için; tam rapor zaten panoda
        params = urllib.parse.urlencode({
            "title": f"[Hata] {APP_DISPLAY_NAME} {APP_VERSION}: ",
            "body": f"```\n{body}\n```\n",
        })
        QDesktopServices.openUrl(QUrl(f"{ISSUES_URL}?{params}"))

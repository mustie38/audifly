"""Giriş/kayıt diyaloğu (mustiefly_auth.LoginWindow'un Qt karşılığı)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.auth import service
from mustiefly_qt.helpers.constants import THEMES, DEFAULT_THEME_KEY, APP_DISPLAY_NAME


class LoginDialog(QDialog):
    """Kapandığında .username (başarılıysa) ya da None (iptal) taşır."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.username: str | None = None
        self._mode = "login"  # "login" | "register"

        self.setWindowTitle(f"{APP_DISPLAY_NAME} - Giriş")
        self.setFixedSize(380, 440)
        theme = THEMES[DEFAULT_THEME_KEY]
        self.setStyleSheet(f"""
            QDialog {{ background: {theme.bg_main}; }}
            QLabel {{ color: {theme.text}; }}
            QLineEdit {{
                background: {theme.bg_card}; color: {theme.text}; border: 1px solid {theme.bg_row_hover};
                border-radius: 8px; padding: 10px; font-size: 13px;
            }}
            QCheckBox {{ color: {theme.text}; }}
            QPushButton#primary {{
                background: {theme.accent}; color: black; border: none; border-radius: 8px;
                padding: 10px; font-weight: bold; font-size: 13px;
            }}
            QPushButton#primary:hover {{ background: {theme.accent_dark}; }}
            QPushButton#link {{ background: transparent; color: {theme.text_dim}; border: none; }}
            QPushButton#link:hover {{ color: {theme.text}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 30, 30, 20)

        title = QLabel(f"🎵 {APP_DISPLAY_NAME}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {theme.accent};")
        root.addWidget(title)

        self.subtitle = QLabel("Hesabınla giriş yap")
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setStyleSheet(f"color: {theme.text_dim};")
        root.addWidget(self.subtitle)
        root.addSpacing(15)

        card = QWidget()
        card.setStyleSheet(f"background: {theme.bg_card}; border-radius: 16px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(10)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Kullanıcı adı")
        card_layout.addWidget(self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Şifre")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(self._submit)
        card_layout.addWidget(self.password_edit)

        self.remember_check = QCheckBox("Beni hatırla")
        self.remember_check.setChecked(True)
        card_layout.addWidget(self.remember_check)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #ff5c5c;")
        card_layout.addWidget(self.error_label)

        self.submit_btn = QPushButton("Giriş Yap")
        self.submit_btn.setObjectName("primary")
        self.submit_btn.clicked.connect(self._submit)
        card_layout.addWidget(self.submit_btn)

        root.addWidget(card)

        self.toggle_btn = QPushButton("Hesabın yok mu? Kayıt ol")
        self.toggle_btn.setObjectName("link")
        self.toggle_btn.clicked.connect(self._toggle_mode)
        root.addWidget(self.toggle_btn, alignment=Qt.AlignCenter)

        self.username_edit.setFocus()

    def _toggle_mode(self):
        self._mode = "register" if self._mode == "login" else "login"
        self.error_label.setText("")
        if self._mode == "register":
            self.subtitle.setText("Yeni bir hesap oluştur")
            self.submit_btn.setText("Kayıt Ol")
            self.toggle_btn.setText("Zaten hesabın var mı? Giriş yap")
        else:
            self.subtitle.setText("Hesabınla giriş yap")
            self.submit_btn.setText("Giriş Yap")
            self.toggle_btn.setText("Hesabın yok mu? Kayıt ol")

    def _submit(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if self._mode == "register":
            ok, err = service.register(username, password)
        else:
            ok, err = service.login(username, password)

        if not ok:
            self.error_label.setText(err)
            return

        service.save_last_session(username, self.remember_check.isChecked())
        self.username = username
        self.accept()


def run_login_flow(parent=None) -> str | None:
    """Kayıtlı ('beni hatırla') bir kullanıcı varsa onu döner; yoksa diyaloğu
    gösterir. İptal edilirse None döner."""
    remembered = service.get_remembered_username()
    if remembered:
        return remembered
    dialog = LoginDialog(parent)
    dialog.exec()
    return dialog.username

"""Birlikte Dinle penceresi: oda oluştur / katıl, ortak sıra, sohbet ve emoji."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from mustiefly_qt.services.listen_together import (
    DEFAULT_SERVER_URL, EMOJIS, ListenTogether, build_invite, generate_room_code,
)

SERVER_KEY = "listen_server_url"
NAME_KEY = "listen_name"


class ListenTogetherDialog(QDialog):
    def __init__(self, service: ListenTogether, settings: dict, save_settings, parent=None):
        super().__init__(parent)
        self.service = service
        self.settings = settings
        self._save_settings = save_settings
        self.setWindowTitle("👥 Birlikte Dinle")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        info = QLabel("Arkadaşınla aynı şarkıyı aynı anda dinle. Ses gönderilmez; "
                      "ikiniz de şarkıyı kendi bilgisayarınızda çalarsınız.")
        info.setWordWrap(True)
        info.setObjectName("Muted")
        root.addWidget(info)

        form = QFormLayout()
        self.server_edit = QLineEdit(str(settings.get(SERVER_KEY, "") or DEFAULT_SERVER_URL))
        self.server_edit.setPlaceholderText("wss://sunucu-adin.onrender.com")
        self.name_edit = QLineEdit(str(settings.get(NAME_KEY, "")))
        self.name_edit.setPlaceholderText("Adın")
        self.name_edit.setMaxLength(24)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Oda kodu ya da davet (örn. K7M2PQ@sunucu.onrender.com)")
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.Password)
        self.pw_edit.setPlaceholderText("Oda şifresi (isteğe bağlı)")
        form.addRow("Adın:", self.name_edit)
        form.addRow("Oda kodu:", self.code_edit)
        form.addRow("Şifre:", self.pw_edit)
        # Sunucu adresi bilindiyse gizli tutulur (arkadaşlar yalnız davet/kod yazar)
        self.server_row = QWidget()
        sr = QHBoxLayout(self.server_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(QLabel("Sunucu:"))
        sr.addWidget(self.server_edit, 1)
        self.server_toggle = QPushButton("⚙ Sunucu ayarı")
        self.server_toggle.setFlat(True)
        self.server_toggle.clicked.connect(
            lambda: self.server_row.setVisible(not self.server_row.isVisible()))
        root.addLayout(form)
        root.addWidget(self.server_toggle)
        root.addWidget(self.server_row)
        self.server_row.setVisible(not self.server_edit.text().strip())

        buttons = QHBoxLayout()
        self.create_btn = QPushButton("＋ Yeni Oda Aç")
        self.create_btn.setObjectName("Primary")
        self.join_btn = QPushButton("Odaya Katıl")
        buttons.addWidget(self.create_btn)
        buttons.addWidget(self.join_btn)
        root.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.members_label = QLabel("")
        self.members_label.setWordWrap(True)
        root.addWidget(self.members_label)

        # --- Odadayken görünen bölüm: ortak sıra + sohbet ---
        self.room_box = QWidget()
        rb = QVBoxLayout(self.room_box)
        rb.setContentsMargins(0, 0, 0, 0)

        rb.addWidget(QLabel("<b>Ortak sıra</b> (şarkı bitince önce buradan çalınır)"))
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(110)
        rb.addWidget(self.queue_list)
        qbtns = QHBoxLayout()
        self.queue_add_btn = QPushButton("➕ Çalan şarkıyı ekle")
        self.queue_remove_btn = QPushButton("✕ Seçileni çıkar")
        qbtns.addWidget(self.queue_add_btn)
        qbtns.addWidget(self.queue_remove_btn)
        rb.addLayout(qbtns)
        hint = QLabel("İpucu: listedeki bir şarkının ⋮ menüsünden de “Oda Kuyruğuna Ekle” diyebilirsin.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        rb.addWidget(hint)

        rb.addWidget(QLabel("<b>Sohbet</b>"))
        self.chat_view = QTextBrowser()
        self.chat_view.setMinimumHeight(120)
        rb.addWidget(self.chat_view)
        emoji_row = QHBoxLayout()
        for emoji in EMOJIS:
            btn = QPushButton(emoji)
            btn.setFixedWidth(40)
            btn.clicked.connect(lambda _=False, e=emoji: self.service.send_emoji(e))
            emoji_row.addWidget(btn)
        rb.addLayout(emoji_row)
        send_row = QHBoxLayout()
        self.chat_edit = QLineEdit()
        self.chat_edit.setPlaceholderText("Mesaj yaz…")
        self.chat_edit.setMaxLength(200)
        self.send_btn = QPushButton("Gönder")
        send_row.addWidget(self.chat_edit, 1)
        send_row.addWidget(self.send_btn)
        rb.addLayout(send_row)
        root.addWidget(self.room_box)

        host_row = QHBoxLayout()
        self.transfer_combo = QComboBox()
        self.transfer_btn = QPushButton("👑 Sahipliği devret")
        self.sync_btn = QPushButton("🔄 Eşitle")
        host_row.addWidget(self.transfer_combo, 1)
        host_row.addWidget(self.transfer_btn)
        host_row.addWidget(self.sync_btn)
        rb.addLayout(host_row)

        bottom = QHBoxLayout()
        self.copy_btn = QPushButton("📋 Daveti Kopyala")
        self.leave_btn = QPushButton("Odadan Ayrıl")
        bottom.addWidget(self.copy_btn)
        bottom.addWidget(self.leave_btn)
        root.addLayout(bottom)

        self.create_btn.clicked.connect(self._create)
        self.join_btn.clicked.connect(self._join)
        self.leave_btn.clicked.connect(self.service.leave)
        self.copy_btn.clicked.connect(self._copy_invite)
        self.transfer_btn.clicked.connect(self._transfer)
        self.sync_btn.clicked.connect(self.service.request_sync)
        self.server_edit.editingFinished.connect(
            lambda: self.service.wake_server(self.server_edit.text()))
        service.latencyChanged.connect(lambda _ms: self._refresh())
        service.connectProgress.connect(self._on_progress)
        self._progress = ""
        self.queue_add_btn.clicked.connect(self._add_current_to_queue)
        self.queue_remove_btn.clicked.connect(self._remove_selected)
        self.send_btn.clicked.connect(self._send_chat)
        self.chat_edit.returnPressed.connect(self._send_chat)
        service.stateChanged.connect(self._refresh)
        service.membersChanged.connect(lambda *_: self._refresh())
        service.queueChanged.connect(self._refresh_queue)
        service.chatReceived.connect(lambda *_: self._render_chat())
        service.emojiReceived.connect(self._on_emoji)
        self._refresh()
        self._refresh_queue()
        self._render_chat()

    # --- Eylemler ---
    def _remember(self):
        self.settings[SERVER_KEY] = self.server_edit.text().strip()
        self.settings[NAME_KEY] = self.name_edit.text().strip()
        self._save_settings()

    def _create(self):
        code = generate_room_code()
        self.code_edit.setText(code)
        self._connect(code)

    def _join(self):
        self._connect(self.code_edit.text())

    def _connect(self, code: str):
        self._progress = ""
        if str(code or "").count("@") > 1:
            self.service.notice.emit("Davet formatı geçersiz.", "warning")
            return
        if self.service.join(self.server_edit.text(), code, self.name_edit.text(),
                             self.pw_edit.text()):
            self._remember()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        # Ücretsiz sunucu uyuyorsa pencere açılır açılmaz uyandır
        QTimer.singleShot(0, lambda: self.service.wake_server(self.server_edit.text()))

    def _copy_invite(self):
        QApplication.clipboard().setText(build_invite(self.service.room, self.server_edit.text()))

    def _transfer(self):
        member_id = self.transfer_combo.currentData()
        if member_id:
            self.service.transfer_host(member_id)

    def _on_progress(self, attempt: int, waking: bool):
        self._progress = (f"Sunucu uyanıyor olabilir… (deneme {attempt}) — ücretsiz sunucuda ilk "
                          "bağlantı ~1 dk sürebilir." if waking else f"Bağlanılıyor… (deneme {attempt})")
        self._refresh()

    def _add_current_to_queue(self):
        song = getattr(self.service.playback, "_current_song_ref", None)
        if not isinstance(song, dict):
            self.service.notice.emit("Önce bir şarkı çal.", "warning")
            return
        self.service.add_to_room_queue(song)

    def _remove_selected(self):
        item = self.queue_list.currentItem()
        if item is not None:
            self.service.remove_from_room_queue(item.data(256))

    def _send_chat(self):
        if self.service.send_chat(self.chat_edit.text()):
            self.chat_edit.clear()

    def _on_emoji(self, name: str, emoji: str):
        self.chat_view.append(f"<span style='color:gray'>{escape(name)}</span> {emoji}")

    # --- Görünümü tazele ---
    def _render_chat(self):
        lines = []
        for name, text, mine in self.service.chat_log:
            who = "Sen" if mine else escape(name)
            lines.append(f"<b>{who}:</b> {escape(text)}")
        self.chat_view.setHtml("<br>".join(lines))
        bar = self.chat_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _refresh_queue(self):
        self.queue_list.clear()
        for i, song in enumerate(self.service.room_queue, 1):
            by = f"  — {song['by']}" if song.get("by") else ""
            self.queue_list.addItem(f"{i}. {song.get('title', '?')}{by}")
        for i, song in enumerate(self.service.room_queue):
            self.queue_list.item(i).setData(256, song.get("webpage_url", ""))

    def _refresh(self):
        state = self.service.state
        connected = state == "connected"
        busy = state != "disconnected"
        for w in (self.server_edit, self.name_edit, self.code_edit, self.pw_edit,
                  self.create_btn, self.join_btn):
            w.setEnabled(not busy)
        self.leave_btn.setEnabled(busy)
        self.copy_btn.setEnabled(connected)
        self.room_box.setVisible(connected)
        if state == "disconnected":
            self.status_label.setText("Odada değilsin.")
        elif state == "connecting":
            self.status_label.setText(self._progress or "Bağlanılıyor…")
        else:
            role = "oda sahibi" if self.service.is_host else "misafir"
            lock = " 🔒" if self.service.locked else ""
            ping = f" · gecikme ~{self.service.latency_ms} ms" if self.service.latency_ms else ""
            self.status_label.setText(
                f"✅ Odadasın: <b>{self.service.room}</b>{lock} ({role}){ping}. "
                "Daveti kopyalayıp arkadaşına gönder.")
        names = []
        for m in self.service.members:
            label = m["name"] + (" (sen)" if m["id"] == self.service.my_id else "")
            if m["id"] == self.service.host_id:
                label += " 👑"
            names.append(label)
        self.members_label.setText("Odadakiler: " + ", ".join(names) if names else "")
        self.transfer_combo.clear()
        for m in self.service.members:
            if m["id"] != self.service.my_id:
                self.transfer_combo.addItem(m["name"], m["id"])
        self.transfer_combo.setVisible(connected and self.service.is_host)
        self.transfer_btn.setVisible(connected and self.service.is_host)
        self.sync_btn.setVisible(connected and not self.service.is_host)

"""
İndirmeler görünümü: çevrimdışı indirmelerin ilerlemesi, iptal ve
başarısız-tekrar deneme ekranı.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import cover_color_for, format_time
from mustiefly_qt.services.download_manager import (
    CANCELLED, DONE, DownloadManager, FAILED, QUEUED, DOWNLOADING)

STATE_LABELS = {
    QUEUED: "Sırada…",
    DOWNLOADING: "İndiriliyor…",
    DONE: "✅ Tamamlandı",
    FAILED: "❌ Başarısız",
    CANCELLED: "⛔ İptal edildi",
}


class DownloadsView(QWidget):
    def __init__(self, manager: DownloadManager, store=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("⬇ İndirmeler")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        header.addWidget(self.count_label)

        clear_btn = QPushButton("🧹 Bitenleri Temizle")
        clear_btn.clicked.connect(self._clear_finished)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)

        hint = QLabel("Şarkı satırlarının ⋮ menüsünden \"Çevrimdışı indir\", "
                      "liste başlığındaki ⬇ ile de tümünü indirebilirsin.")
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        self._rows: dict[str, dict] = {}   # key → {"row": widget, ...}

        self.manager.itemChanged.connect(self._on_item_changed)
        self.manager.queueChanged.connect(self.refresh)
        self.refresh()

    # --- Render ---
    def refresh(self):
        items = self.manager.ordered_items()
        self.list_widget.clear()
        self._rows.clear()
        active = sum(1 for it in items if it["state"] in (QUEUED, DOWNLOADING))
        done = sum(1 for it in items if it["state"] == DONE)
        self.count_label.setText(
            f"{len(items)} kayıt • {active} aktif • {done} tamam")

        if not items:
            empty = QLabel("İndirme kuyruğu boş.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignCenter)
            empty.setContentsMargins(0, 32, 0, 0)
            item = QListWidgetItem()
            item.setSizeHint(empty.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, empty)
            return

        for it in items:
            item = QListWidgetItem()
            row = _DownloadRow(it)
            row.cancelRequested.connect(self.manager.cancel)
            row.retryRequested.connect(self.manager.retry)
            row.removeRequested.connect(self.manager.remove)
            item.setSizeHint(row.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)
            self._rows[it["key"]] = {"row": row, "item": it}

    def _on_item_changed(self, key: str):
        entry = self._rows.get(key)
        if entry is None:
            return
        entry["row"].update_from(entry["item"])
        # Durum değişince sayaçlar da değişmiş olabilir
        items = self.manager.ordered_items()
        active = sum(1 for it in items if it["state"] in (QUEUED, DOWNLOADING))
        done = sum(1 for it in items if it["state"] == DONE)
        self.count_label.setText(
            f"{len(items)} kayıt • {active} aktif • {done} tamam")

    def _clear_finished(self):
        self.manager.clear_finished()


class _DownloadRow(QWidget):
    cancelRequested = Signal(str)   # key
    retryRequested = Signal(str)
    removeRequested = Signal(str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.key = item["key"]
        self.setProperty("SongRow", True)
        self.setObjectName("SongRow")
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        thumb = QLabel("💾")
        thumb.setFixedSize(36, 36)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet(
            f"background: {cover_color_for(item['song'].get('title', '?'))};"
            "border-radius: 5px; font-size: 15px;")
        layout.addWidget(thumb)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = item["song"].get("title", "?")
        title_label = QLabel(title[:55] + ("…" if len(title) > 55 else ""))
        title_label.setStyleSheet("font-weight: 600;")
        text.addWidget(title_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        status_row.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setFixedHeight(10)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        status_row.addWidget(self.progress)
        text.addLayout(status_row)
        layout.addLayout(text, stretch=1)

        dur = format_time((item["song"].get("duration") or 0) * 1000)
        dur_label = QLabel(dur)
        dur_label.setObjectName("Muted")
        layout.addWidget(dur_label)

        self.retry_btn = QPushButton("↻")
        self.retry_btn.setFixedWidth(26)
        self.retry_btn.setToolTip("Tekrar dene")
        self.retry_btn.clicked.connect(lambda: self.retryRequested.emit(self.key))
        layout.addWidget(self.retry_btn)

        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setFixedWidth(26)
        self.cancel_btn.setToolTip("İptal et / listeden kaldır")
        self.cancel_btn.clicked.connect(self._on_main_button)
        layout.addWidget(self.cancel_btn)

        self.update_from(item)

    def _on_main_button(self):
        if self.cancel_btn.toolTip().startswith("Kaldır"):
            self.removeRequested.emit(self.key)
        else:
            self.cancelRequested.emit(self.key)

    def update_from(self, item: dict):
        state = item["state"]
        self.status_label.setText(STATE_LABELS.get(state, state))
        is_active = state in (QUEUED, DOWNLOADING)
        self.progress.setVisible(is_active)
        self.progress.setValue(int(round((item.get("progress") or 0) * 100)))
        self.retry_btn.setVisible(state in (FAILED, CANCELLED))
        if is_active:
            self.cancel_btn.setText("✕")
            self.cancel_btn.setToolTip("İptal et")
        else:
            self.cancel_btn.setText("🗑")
            self.cancel_btn.setToolTip("Listeden kaldır")
        if state == FAILED and item.get("error"):
            self.status_label.setToolTip(item["error"])
        else:
            self.status_label.setToolTip("")

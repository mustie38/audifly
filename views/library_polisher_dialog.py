"""
✨ Kütüphane Parlatıcı Diyaloğu:
Önizlemeli (Önce → Sonra) başlık ve sanatçı etiketi temizleyici.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.win_theme import apply_dark_titlebar
from mustiefly_qt.services.library_polisher import (
    PolishProposal, apply_proposals, scan_library,
)


class _ProposalRow(QWidget):
    """Tek bir parlatma önerisi satırı: checkbox + Önce → Sonra + sebep etiketi."""

    def __init__(self, prop: PolishProposal, on_toggle, parent=None):
        super().__init__(parent)
        self.proposal = prop

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        self.check = QCheckBox()
        self.check.setChecked(True)
        self.check.toggled.connect(on_toggle)
        root.addWidget(self.check, alignment=Qt.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)

        old_txt = f"{prop.old_title}  —  {prop.old_uploader or '?'}"
        old_lbl = QLabel(f"Önce:  {old_txt}")
        old_lbl.setObjectName("Muted")
        old_lbl.setStyleSheet("font-size: 11px;")
        body.addWidget(old_lbl)

        new_txt = f"{prop.new_title}  —  {prop.new_uploader or '?'}"
        new_lbl = QLabel(f"Sonra: {new_txt}")
        nf = QFont()
        nf.setBold(True)
        new_lbl.setFont(nf)
        new_lbl.setStyleSheet("font-size: 12.5px; color: #5CE1A6;")
        body.addWidget(new_lbl)

        meta_lbl = QLabel(f"📂 {prop.playlist}  •  " + " · ".join(prop.reasons))
        meta_lbl.setObjectName("Muted")
        meta_lbl.setStyleSheet("font-size: 10.5px;")
        body.addWidget(meta_lbl)

        root.addLayout(body, stretch=1)


class LibraryPolisherDialog(QDialog):
    """Kütüphanedeki kirli YouTube başlıklarını ve kanal eklerini önizleyip temizler."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._rows: list[_ProposalRow] = []

        self.setWindowTitle("✨ Kütüphane Parlatıcı — Başlık & Etiket Temizleyici")
        self.resize(700, 540)
        apply_dark_titlebar(self, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        # Başlık
        title = QLabel("✨ Kütüphane Parlatıcı")
        tf = QFont()
        tf.setPixelSize(20)
        tf.setBold(True)
        title.setFont(tf)
        root.addWidget(title)

        desc = QLabel(
            "Şarkı başlıklarındaki '(Official Video)', '[4K]', 'Sözleri', '- Topic', 'VEVO' "
            "gibi kirli ekleri temizler; '(Live)', '(Acoustic)', '(Remix)' gibi anlamlı sürüm "
            "etiketlerini korur. Hiçbir değişiklik sen onaylamadan uygulanmaz."
        )
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # Kapsam + Tümünü Seç çubuğu
        controls = QHBoxLayout()
        controls.setSpacing(10)

        scope_lbl = QLabel("Kapsam:")
        scope_lbl.setObjectName("Muted")
        controls.addWidget(scope_lbl)

        self.scope_combo = QComboBox()
        self.scope_combo.addItem("📚 Tüm Kütüphane", None)
        active = getattr(store, "active_playlist", None)
        if active:
            self.scope_combo.addItem(f"📂 Aktif Liste ({active})", active)
        self.scope_combo.currentIndexChanged.connect(self._rescan)
        controls.addWidget(self.scope_combo)

        controls.addStretch(1)

        self.select_all_btn = QPushButton("Tümünü Kaldır")
        self.select_all_btn.setObjectName("Secondary")
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        controls.addWidget(self.select_all_btn)
        root.addLayout(controls)

        # Özet rozeti
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
        )
        root.addWidget(self.summary_label)

        # Öneri listesi
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.NoSelection)
        self.list_widget.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.list_widget, stretch=1)

        # Alt butonlar
        footer = QHBoxLayout()
        footer.addStretch(1)

        close_btn = QPushButton("Kapat")
        close_btn.setObjectName("Secondary")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)

        self.apply_btn = QPushButton("✨ Seçilenleri Uygula")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(self._apply)
        footer.addWidget(self.apply_btn)
        root.addLayout(footer)

        self._rescan()

    def _rescan(self):
        self.list_widget.clear()
        self._rows.clear()
        pl_name = self.scope_combo.currentData()
        proposals = scan_library(self.store, playlist_name=pl_name)

        if not proposals:
            self.summary_label.setText("✅ Kütüphanen zaten tertemiz — temizlenecek kirli başlık bulunamadı.")
            self.summary_label.setStyleSheet(
                "background: rgba(72, 199, 142, 0.14); color: #5ce1a6; "
                "border: 1px solid rgba(72, 199, 142, 0.30); "
                "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
            )
            self.select_all_btn.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self.apply_btn.setText("✨ Seçilenleri Uygula (0)")
            return

        for prop in proposals:
            item = QListWidgetItem()
            row = _ProposalRow(prop, self._sync_counts)
            item.setSizeHint(row.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)
            self._rows.append(row)

        self.summary_label.setText(f"✨ {len(proposals)} şarkıda başlık/etiket iyileştirmesi bulundu.")
        self.summary_label.setStyleSheet(
            "background: rgba(169, 128, 249, 0.16); color: #d7c4ff; "
            "border: 1px solid rgba(169, 128, 249, 0.35); "
            "padding: 6px 12px; border-radius: 10px; font-weight: 600; font-size: 12px;"
        )
        self.select_all_btn.setEnabled(True)
        self._sync_counts()

    def _selected_proposals(self) -> list[PolishProposal]:
        return [r.proposal for r in self._rows if r.check.isChecked()]

    def _sync_counts(self, *_args):
        sel = len(self._selected_proposals())
        total = len(self._rows)
        self.apply_btn.setText(f"✨ Seçilenleri Uygula ({sel})")
        self.apply_btn.setEnabled(sel > 0)
        self.select_all_btn.setText("Tümünü Kaldır" if sel == total and total > 0 else "Tümünü Seç")

    def _toggle_select_all(self):
        all_checked = all(r.check.isChecked() for r in self._rows)
        target = not all_checked
        for r in self._rows:
            r.check.blockSignals(True)
            r.check.setChecked(target)
            r.check.blockSignals(False)
        self._sync_counts()

    def _apply(self):
        selected = self._selected_proposals()
        if not selected:
            return
        updated = apply_proposals(self.store, selected)
        if updated > 0:
            self._rescan()

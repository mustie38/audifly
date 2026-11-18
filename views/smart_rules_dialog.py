"""Kullanıcı tanımlı akıllı liste kuralları: listele / ekle / düzenle / sil / aç."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QPushButton,
                               QSpinBox, QVBoxLayout)

from mustiefly_qt.helpers.win_theme import apply_dark_titlebar
from mustiefly_qt.services import smart_lists

SORT_LABELS = (("En çok dinlenen önce", "most_played"), ("En az dinlenen önce", "least_played"),
               ("En yeni eklenen önce", "newest"), ("En eski eklenen önce", "oldest"),
               ("Sabit karışık sıra", "random_stable"))


class RuleEditor(QDialog):
    def __init__(self, rule: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kural Listesi")
        apply_dark_titlebar(self)
        rule = rule or smart_lists.sanitize_rule({"name": "Yeni liste"})
        form = QFormLayout(self)
        self.name = QLineEdit(rule["name"])
        self.liked = QCheckBox("Yalnızca beğenilenler")
        self.liked.setChecked(rule["liked_only"])
        self.artist = QLineEdit(rule["artist_contains"])
        self.title = QLineEdit(rule["title_contains"])
        self.min_plays = self._spin(rule["min_plays"], 0, 100000, "en az")
        self.not_played = self._spin(rule["not_played_days"], 0, 3650, "gündür dinlenmeyen (0 = kapalı)")
        self.added_within = self._spin(rule["added_within_days"], 0, 3650, "gün içinde eklenen (0 = kapalı)")
        self.max_dur = self._spin(rule["max_duration_min"], 0, 600, "dk'dan kısa (0 = kapalı)")
        self.limit = self._spin(rule["limit"], 1, smart_lists.RULE_LIMIT_MAX, "şarkıya kadar")
        self.sort = QComboBox()
        for label, key in SORT_LABELS:
            self.sort.addItem(label, key)
        self.sort.setCurrentIndex(max(0, self.sort.findData(rule["sort"])))
        form.addRow("Ad:", self.name)
        form.addRow("", self.liked)
        form.addRow("Sanatçı içerir:", self.artist)
        form.addRow("Başlık içerir:", self.title)
        form.addRow("Çalma sayısı:", self.min_plays)
        form.addRow("Zaman:", self.not_played)
        form.addRow("", self.added_within)
        form.addRow("Süre:", self.max_dur)
        form.addRow("Sıralama:", self.sort)
        form.addRow("Üst sınır:", self.limit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.result_rule: dict | None = None

    @staticmethod
    def _spin(value, lo, hi, suffix):
        box = QSpinBox()
        box.setRange(lo, hi)
        box.setValue(value)
        box.setSuffix(" " + suffix)
        return box

    def _accept(self):
        rule = smart_lists.sanitize_rule({
            "name": self.name.text(), "liked_only": self.liked.isChecked(),
            "artist_contains": self.artist.text(), "title_contains": self.title.text(),
            "min_plays": self.min_plays.value(), "not_played_days": self.not_played.value(),
            "added_within_days": self.added_within.value(), "max_duration_min": self.max_dur.value(),
            "limit": self.limit.value(), "sort": self.sort.currentData()})
        if rule is None:
            QMessageBox.warning(self, "Kural Listesi", "Lütfen bir ad gir.")
            return
        self.result_rule = rule
        self.accept()


class SmartRulesDialog(QDialog):
    openRequested = Signal(str)

    def __init__(self, settings: dict, save_fn, parent=None):
        super().__init__(parent)
        self.settings, self.save_fn = settings, save_fn
        self.setWindowTitle("Kural Listeleri")
        apply_dark_titlebar(self)
        self.resize(420, 360)
        root = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._open())
        root.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in (("Aç", self._open), ("Yeni", self._new),
                           ("Düzenle", self._edit), ("Sil", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        root.addLayout(row)
        self._reload()

    def rules(self) -> list[dict]:
        return smart_lists.sanitize_rules(self.settings.get("smart_rules"))

    def _reload(self):
        self.list.clear()
        for r in self.rules():
            self.list.addItem(r["name"])
        if not self.list.count():
            self.list.addItem("(Henüz kural yok — “Yeni” ile oluştur)")
            self.list.item(0).setFlags(Qt.NoItemFlags)

    def _selected(self) -> int:
        return self.list.currentRow() if self.rules() else -1

    def _store(self, rules: list[dict]):
        self.settings["smart_rules"] = smart_lists.sanitize_rules(rules)
        self.save_fn()
        self._reload()

    def _new(self):
        dlg = RuleEditor(None, self)
        if dlg.exec() and dlg.result_rule:
            self._store(self.rules() + [dlg.result_rule])

    def _edit(self):
        i, rules = self._selected(), self.rules()
        if i < 0:
            return
        dlg = RuleEditor(rules[i], self)
        if dlg.exec() and dlg.result_rule:
            rules[i] = dlg.result_rule
            self._store(rules)

    def _delete(self):
        i, rules = self._selected(), self.rules()
        if i >= 0:
            del rules[i]
            self._store(rules)

    def _open(self):
        i, rules = self._selected(), self.rules()
        if i >= 0:
            self.openRequested.emit(rules[i]["name"])
            self.accept()

"""Mix'ler sayfası: Sana Özel, Günlük Mix ve davranıştan türeyen "Tarzı" mix'leri."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from mustiefly_qt.services import mixes
from mustiefly_qt.services.playback import PlaybackEngine
from mustiefly_qt.services.playlist_store import PlaylistStore

ICONS = {"sana_ozel": "✨", "gunluk_mix": "📅"}


def all_refs(store: PlaylistStore) -> list[tuple[str, int, dict]]:
    return [(name, i, s) for name, songs in store.playlists.items() for i, s in enumerate(songs)]


def build_for(store: PlaylistStore, playback) -> list[mixes.Mix]:
    return mixes.build_mixes(all_refs(store), getattr(playback, "history", None))


class MixesView(QWidget):
    openRequested = Signal(str)       # mix id → kitaplık görünümünde aç

    def __init__(self, store: PlaylistStore, playback: PlaybackEngine, parent=None):
        super().__init__(parent)
        self.store, self.playback = store, playback
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 10)
        title = QLabel("✨ Senin İçin Mix'ler")
        f = QFont()
        f.setPixelSize(22)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)
        note = QLabel("Kütüphanendeki şarkılardan, dinleme geçmişine göre cihazında hesaplanır; "
                      "hiçbir veri dışarı gönderilmez.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        root.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("HomeContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.box = QVBoxLayout(content)
        self.box.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    def refresh(self):
        while self.box.count():
            w = self.box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        found = build_for(self.store, self.playback)
        if not found:
            empty = QLabel("Henüz Mix oluşturacak kadar veri yok.\n"
                           "Birkaç şarkıyı 30 saniyeden uzun dinle ya da beğen; Mix'ler kendiliğinden oluşur.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            self.box.addWidget(empty)
        for mix in found:
            self.box.addWidget(self._card(mix))
        self.box.addStretch(1)

    def _card(self, mix: mixes.Mix) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        head = QLabel(f"{ICONS.get(mix.id, '🎧')}  {mix.title}")
        hf = QFont()
        hf.setPixelSize(17)
        hf.setBold(True)
        head.setFont(hf)
        v.addWidget(head)
        sub = QLabel(mix.subtitle)
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        v.addWidget(sub)
        names = ", ".join(dict.fromkeys(mixes.artist_of(t[2]) for t in mix.refs[:12]))
        v.addWidget(QLabel(f"{len(mix.refs)} şarkı · {names[:90]}"))
        row = QHBoxLayout()
        play = QPushButton("▶ Çal")
        play.setObjectName("Primary")
        play.clicked.connect(lambda _=False, mid=mix.id: self.play_mix(mid))
        open_btn = QPushButton("Listeyi Aç")
        open_btn.clicked.connect(lambda _=False, mid=mix.id: self.openRequested.emit(mid))
        row.addWidget(play)
        row.addWidget(open_btn)
        row.addStretch(1)
        v.addLayout(row)
        return card

    def play_mix(self, mix_id: str):
        # Kütüphane bu arada değişmiş olabilir → indeksler tazelenir
        mix = next((m for m in build_for(self.store, self.playback) if m.id == mix_id), None)
        if mix is None or not mix.refs:
            return
        (name, idx, _), rest = mix.refs[0], mix.refs[1:]
        self.store.set_queue(rest)
        self.playback.play_song_at_index(name, idx)

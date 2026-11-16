"""
Bilgisayardaki ses dosyalarını (mp3/m4a/flac/wav/ogg/opus) playlistlere ekleme.

Şarkı sözlüğü YouTube şarkılarıyla aynı formatta kalır; tek farklar:
- `local_path`: diskteki gerçek dosya yolu,
- `webpage_url`: "local://<yol>" sentetik kimlik (tekrar kontrolü, kuyruk
  referansları ve locate_song mevcut mantıkla çalışmaya devam eder),
- süre VLC ile dosyadan okunur, kapak ID3 gömülüyse mutagen'siz okunamaz —
  o yüzden başlığa göre renkli 🎵 rozeti kullanılır.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

AUDIO_EXTENSIONS = ("*.mp3", "*.m4a", "*.flac", "*.wav", "*.ogg", "*.opus", "*.wma")

_TITLE_SEPARATORS = (" - ", " – ", " — ")


def probe_duration_ms(path: str) -> int:
    """VLC ile ses süresini okur (ms). Başarısızsa 0 döner.
    NOT: parse_with_options(timeout=0) asenkron olduğu için süre hemen hazır
    olmuyor; eski ama SENKRON olan media.parse() güvenilir sonuç veriyor."""
    try:
        import vlc
        media = vlc.Media(path)
        try:
            try:
                media.parse()  # senkron ayrıştırma (local dosyalarda hızlı)
            except Exception:
                pass
            return max(media.get_duration() or 0, 0)
        finally:
            try:
                media.release()
            except Exception:
                pass
    except Exception:
        return 0


def build_local_song(path: str) -> dict:
    """Dosya yolundan şarkı sözlüğü üretir. 'Sanatçı - Başlık' adlandırması
    varsa ayrıştırılır; yoksa dosya adı başlık olur."""
    filename = os.path.splitext(os.path.basename(path))[0]
    artist = "Yerel Dosya"
    title = filename.strip()
    for sep in _TITLE_SEPARATORS:
        if sep in filename:
            maybe_artist, maybe_title = filename.split(sep, 1)
            if maybe_artist.strip() and maybe_title.strip():
                artist = maybe_artist.strip()
                title = maybe_title.strip()
            break
    duration_ms = probe_duration_ms(path)
    return {
        "title": title or "Bilinmeyen Şarkı",
        "webpage_url": f"local://{os.path.abspath(path)}",
        "local_path": os.path.abspath(path),
        "duration": duration_ms / 1000.0,
        "uploader": artist,
        "thumbnail": None,
        "liked": False,
    }


def pick_and_add_local_files(store, parent=None):
    """Dosya seçme diyaloğu + hedef liste seçimi + ekleme. Eklenen sayıyı döner."""
    paths, _ = QFileDialog.getOpenFileNames(
        parent, "Ses dosyaları seç", "",
        "Ses Dosyaları (" + " ".join(AUDIO_EXTENSIONS) + ");;Tüm dosyalar (*.*)")
    if not paths:
        return 0

    targets = list(store.playlists.keys())
    target, ok = QInputDialog.getItem(
        parent, "Hedef Liste", "Hangi listeye eklensin?", targets, 0, False)
    if not ok:
        return 0

    added = 0
    for p in paths:
        song = build_local_song(p)
        if store.add_song(target, song):
            added += 1
    missing = [p for p in paths
               if not os.path.exists(p)]
    if added:
        store.statusMessage.emit(
            f"💽 {added} yerel dosya '{target}' listesine eklendi.", "success")
    elif not missing:
        QMessageBox.information(
            parent, "Eklenmedi",
            "Seçilen dosyalar bu listede zaten var.")
    return added

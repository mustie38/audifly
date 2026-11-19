"""
Kütüphane Parlatıcı (Otomatik Etiket & Başlık Temizleyici).

YouTube'dan gelen '(Official Music Video)', '[4K]', 'Sözleri', '- Topic', 'VEVO'
gibi kirli başlık ve kanal eklerini güvenli biçimde temizler; '(Live)', '(Acoustic)',
'(Remix)' gibi anlamlı sürüm etiketlerini korur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Parantez / köşeli parantez içinde güvenle silinebilecek YouTube çöp etiketleri
_JUNK_INNER_RE = re.compile(
    r"^(?:"
    r"official\s*(?:music\s*)?(?:video|audio|lyric(?:s)?\s*video|visualizer|clip|mv|m/v)|"
    r"music\s*video|lyric(?:s)?\s*(?:video)?|lyrics?|audio\s*only|audio|visualizer|"
    r"resmi\s*(?:müzik\s*)?(?:video|klip)|(?:video\s*)?klip|şarkı\s*sözleri|sözleri|sözlü|"
    r"full\s*(?:song|audio|video|hd)|hd|hq|4k|8k|1080p|720p|uhd|"
    r"(?:\d{4}\s*)?remaster(?:ed)?(?:\s*\d{4})?|"
    r"m/?v|explicit|clean\s*version|topic|auto-?generated"
    r")$",
    re.IGNORECASE,
)

# Parantezli blokları yakala: (...), [...], 【...】
_BRACKET_RE = re.compile(r"\s*([(\[【])\s*([^)\]】]+?)\s*([)\]】])")

# Başlık sonundaki boru/çizgi ekleri: "| Official Video", "| Sözleri", "| 4K"
_TRAILING_PIPE_RE = re.compile(
    r"\s*[|•]\s*(?:"
    r"official\s*(?:music\s*)?(?:video|audio|lyric(?:s)?\s*video|visualizer)|"
    r"resmi\s*(?:video|klip)|klip|şarkı\s*sözleri|sözleri|lyrics?|"
    r"hd|4k|hq|audio|visualizer|m/?v"
    r")\s*$",
    re.IGNORECASE,
)

# Kanal/uploader son ekleri: "- Topic", "VEVO", "Official", "Resmi"
_UPLOADER_TOPIC_RE = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)
_UPLOADER_VEVO_RE = re.compile(r"(?<=[a-zA-Z0-9ığüşöçİĞÜŞÖÇ])VEVO$", re.IGNORECASE)
_UPLOADER_SUFFIX_RE = re.compile(
    r"\s+(?:official|resmi|music\s*channel|official\s*channel)\s*$",
    re.IGNORECASE,
)

_GENERIC_UPLOADERS = {
    "", "?", "bilinmeyen sanatçı", "unknown artist", "youtube", "youtube stream",
    "various artists", "netd müzik", "netd muzik", "poll production", "dmc",
    "doğan music company", "pasaj müzik", "sony music türkiye",
}


@dataclass
class PolishProposal:
    playlist: str
    index: int
    song: dict
    old_title: str
    old_uploader: str
    new_title: str
    new_uploader: str
    reasons: list[str]


def _clean_title_junk(title: str) -> tuple[str, bool]:
    """Başlıktaki YouTube çöp etiketlerini temizler; (Live)/(Remix)/(Acoustic) vb. korur."""
    changed = False

    def _repl(match: re.Match) -> str:
        nonlocal changed
        inner = match.group(2).strip()
        if _JUNK_INNER_RE.match(inner):
            changed = True
            return ""
        return match.group(0)

    out = _BRACKET_RE.sub(_repl, title)
    out2 = _TRAILING_PIPE_RE.sub("", out)
    if out2 != out:
        changed = True
        out = out2

    # Boş kalan parantezleri ve çift boşlukları toparla
    out = re.sub(r"\s{2,}", " ", out).strip(" -–—|")
    return out, changed


def _clean_uploader(uploader: str) -> tuple[str, bool]:
    raw = (uploader or "").strip()
    if not raw:
        return "", False
    out = _UPLOADER_TOPIC_RE.sub("", raw).strip()
    out = _UPLOADER_VEVO_RE.sub("", out).strip()
    out = _UPLOADER_SUFFIX_RE.sub("", out).strip()
    out = re.sub(r"\s{2,}", " ", out).strip(" -–—|")
    return out, (out != raw)


def polish_song_metadata(song: dict) -> tuple[str, str, list[str]]:
    """Tek bir şarkı için (yeni_başlık, yeni_sanatçı, sebepler) önerisi üretir."""
    old_title = (song.get("title") or "").strip()
    old_uploader = (song.get("uploader") or "").strip()
    if not old_title:
        return old_title, old_uploader, []

    reasons: list[str] = []
    title, junk_removed = _clean_title_junk(old_title)
    if junk_removed:
        reasons.append("YouTube etiketi temizlendi")

    uploader, up_cleaned = _clean_uploader(old_uploader)
    if up_cleaned:
        reasons.append("Kanal eki temizlendi")

    # "Sanatçı - Şarkı Adı" biçimindeki başlıkları ayrıştır (anlamlı parantezleri koruyarak)
    sep_match = re.match(r"^([^–—\-|]{2,60}?)\s+[-–—]\s+(.+)$", title)
    if sep_match:
        cand_artist = sep_match.group(1).strip()
        cand_title = sep_match.group(2).strip()
        cand_artist_clean, _ = _clean_uploader(cand_artist)
        if cand_artist_clean and cand_title and (
            uploader.casefold() in _GENERIC_UPLOADERS
            or cand_artist_clean.casefold() in uploader.casefold()
            or uploader.casefold() in cand_artist_clean.casefold()
        ):
            title = cand_title
            uploader = cand_artist_clean
            if "Sanatçı/başlık ayrıştırıldı" not in reasons:
                reasons.append("Sanatçı/başlık ayrıştırıldı")

    # Güvenlik: asla boş başlık üretme
    if not title:
        title = old_title
    if not uploader:
        uploader = old_uploader

    # Gerçekten değişiklik yoksa boş sebep dön
    if title == old_title and uploader == old_uploader:
        return old_title, old_uploader, []
    if not reasons:
        reasons.append("Biçim düzenlendi")
    return title, uploader, reasons


def scan_library(store, playlist_name: str | None = None) -> list[PolishProposal]:
    """Kütüphaneyi (veya tek bir çalma listesini) tarayıp iyileştirme önerilerini döner."""
    proposals: list[PolishProposal] = []
    if playlist_name is not None:
        targets = [(playlist_name, store.playlists.get(playlist_name, []))]
    else:
        targets = list(store.playlists.items())

    for pl_name, songs in targets:
        for idx, song in enumerate(songs):
            old_t = (song.get("title") or "").strip()
            old_u = (song.get("uploader") or "").strip()
            new_t, new_u, reasons = polish_song_metadata(song)
            if reasons and (new_t != old_t or new_u != old_u):
                proposals.append(PolishProposal(
                    playlist=pl_name,
                    index=idx,
                    song=song,
                    old_title=old_t,
                    old_uploader=old_u,
                    new_title=new_t,
                    new_uploader=new_u,
                    reasons=reasons,
                ))
    return proposals


def apply_proposals(store, proposals: list[PolishProposal]) -> int:
    """Seçilen iyileştirme önerilerini şarkılara uygular ve kütüphaneyi kaydeder."""
    updated = 0
    for prop in proposals:
        songs = store.playlists.get(prop.playlist)
        if not songs or not (0 <= prop.index < len(songs)):
            continue
        target = songs[prop.index]
        if target is not prop.song:
            # Liste bu arada değiştiyse canlı referansı bul
            real_pl, real_idx = store.locate_song(prop.playlist, prop.index, prop.song)
            if real_pl is None:
                continue
            target = store.playlists[real_pl][real_idx]
        target["title"] = prop.new_title
        target["uploader"] = prop.new_uploader
        updated += 1

    if updated > 0:
        store.save()
        store.playlistsChanged.emit()
        store.statusMessage.emit(f"✨ {updated} şarkının başlık/sanatçı etiketi parlatıldı.", "success")
    return updated

"""
Keşfet ("Music Discovery Hub") ekranı için veri toplama, doğrulama ve
önbellekleme katmanı.

DiscoveryService, YouTube Music / YouTube üzerinden alınabilecek güncel
müzik verisini (ytmusicapi charts, YouTube arama tabanlı kategoriler,
opsiyonel olarak kullanıcının bağladığı Spotify chart playlist'leri) toplar;
bunları CATEGORY_DEFS'te tanımlı, yapılandırılabilir bir bölüm ("section")
listesine göre işler, tekilleştirir/temizler ve diske (discovery_cache.json)
önbellekler.

NOT (Spotify): Spotify'ın playlist okuma uç noktaları artık salt Client
Credentials (arka plan, kullanıcısız) token'ları kabul etmiyor — gerçek
kullanıcı girişi gerekiyor (bkz. helpers/spotify_import.py). Bu yüzden
DiscoveryService, arka planda KENDİLİĞİNDEN tarayıcı açıp kullanıcıdan onay
istemez: yalnızca kullanıcı daha önce (Ayarlar > Entegrasyonlar'dan ya da
Spotify içe aktarma akışından) bir kez bağlanmış ve bir refresh_token
kaydedilmişse Spotify chart'ı sessizce kullanır; aksi halde o kategori
sessizce normal YouTube arama yedeğine düşer.

Bu modülün Qt'ye hiçbir bağımlılığı yoktur — saf mantıktır. Çağıran taraf
(ExploreView) ağ isteklerini GUI thread'i dışında bir arka plan thread'inde
yürütmelidir.
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime

import yt_dlp

from mustiefly_qt.helpers.constants import yt_dlp_base_opts
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.helpers.logging_setup import get_logger
from mustiefly_qt.helpers.persistence import atomic_write_json
from mustiefly_qt.helpers.spotify_import import fetch_spotify_playlist, search_spotify_playlist


log = get_logger(__name__)

try:
    from ytmusicapi import YTMusic
    YTMUSICAPI_AVAILABLE = True
except Exception:
    YTMUSICAPI_AVAILABLE = False


CACHE_FILENAME = "discovery_cache.json"
CACHE_VERSION = 2

MONTHS_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


# --- Tarih bazlı dinamik başlık üreticiler ---
# Sabit "Yılın Türkçe Şarkıları" gibi başlıklar yerine bilgisayarın mevcut
# tarihinden üretilen başlıklar kullanılır (ay değişince otomatik güncellenir).
def week_title(base: str) -> str:
    return f"Bu Haftanın {base}"


def month_title(base: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{MONTHS_TR[now.month - 1]} {now.year} — {base}"


def year_title(base: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now.year}'nın {base}"


# --- KATEGORİ TANIMLARI ---
# Keşfet ekranındaki TÜM bölümler buradan yönetilir. Yeni bir bölüm eklemek,
# kaldırmak ya da bir arama sorgusunu değiştirmek için değiştirilmesi gereken
# tek dosya burasıdır.
#
# Alanlar:
#   id        benzersiz anahtar (cache içindeki section id'si)
#   kind      "chart"  -> ytmusicapi / YouTube trend verisi (region kullanır)
#             "search" -> arama tabanlı keşif (query kullanır)
#             "artist" -> arama sonuçlarından sanatçı/kanal kartları üretir
#   title     sabit metin ya da (datetime) -> str biçiminde çağrılabilir
#             (haftalık/aylık/yıllık dinamik başlıklar için)
#   subtitle  kart grubunun altındaki açıklama
#   query     "search"/"artist" kind'i için arama sorgusu
#   region    "chart" kind'i için ytmusic/trend bölgesi
#   period    "daily" | "weekly" | "monthly" | "yearly" — bölümün ne sıklıkla
#             bayatladığına (refresh_if_needed) karar verir
#   limit     kaç kart gösterileceği
#   show_rank sıra numarası rozeti gösterilsin mi (yalnızca track kartları)
CATEGORY_DEFS: list[dict] = [
    {
        "id": "tr_trending", "kind": "chart", "region": "TR",
        "title": "Türkiye'de Yükselenler",
        "subtitle": "Bu hafta Türkiye'de yükselişe geçen parçalar",
        "period": "weekly", "limit": 12, "show_rank": True,
        # Kullanıcı Spotify'a bağlıysa bu isim Spotify'da otomatik aranıp
        # playlist ID'si çözülür (elle ID girmeye gerek yok) ve gerçek chart
        # sıralaması YouTube'da eşleştirilir. Bağlı değilse ya da bulunamazsa
        # sessizce mevcut YouTube arama yedeğine düşülür.
        "spotify_playlist_query": "Top 50 - Türkiye",
    },
    {
        "id": "tr_rap_week", "kind": "search",
        "query": "türkçe rap yeni çıkanlar",
        "title": lambda now: week_title("Türkçe Rap'i"),
        "subtitle": "Son günlerde öne çıkan Türkçe rap parçaları",
        "period": "weekly", "limit": 12,
    },
    {
        "id": "tr_rap_month", "kind": "search",
        "query": "türkçe rap",
        "title": lambda now: month_title("Türkçe Rap", now),
        "subtitle": "Ayın öne çıkan Türkçe rap parçaları",
        "period": "monthly", "limit": 12,
    },
    {
        "id": "tr_pop", "kind": "search",
        "query": "türkçe pop yeni çıkanlar",
        "title": "Türkçe Pop",
        "subtitle": "Güncel Türkçe pop parçaları",
        "period": "weekly", "limit": 12,
    },
    {
        "id": "global_top", "kind": "chart", "region": "US",
        "title": "Global Top Tracks",
        "subtitle": "Dünya genelinde bu hafta öne çıkanlar",
        "period": "weekly", "limit": 12, "show_rank": True,
        "spotify_playlist_query": "Top 50 - Global",
    },
    {
        "id": "global_rap", "kind": "search",
        "query": "hip hop rap new songs",
        "title": "Global Rap",
        "subtitle": "Global rap sahnesinden güncel parçalar",
        "period": "weekly", "limit": 12,
    },
    {
        "id": "new_releases", "kind": "search",
        "query": "yeni single çıktı",
        "title": "Yeni Çıkanlar",
        "subtitle": "YouTube'da son dönemde öne çıkan yeni müzikler",
        "period": "daily", "limit": 12,
    },
    {
        "id": "throwback", "kind": "search",
        "query": "2000'ler nostalji şarkılar",
        "title": "Nostalji / Throwback",
        "subtitle": "Yılların ötesinden unutulmaz parçalar",
        "period": "monthly", "limit": 12,
    },
    {
        "id": "tr_year", "kind": "search",
        "query": "türkçe pop en çok dinlenen",
        "title": lambda now: year_title("Öne Çıkan Türkçe Şarkıları", now),
        "subtitle": "Yılın öne çıkan Türkçe parçaları",
        "period": "yearly", "limit": 12,
    },
    {
        "id": "mood_night", "kind": "search",
        "query": "gece dinlemelik sakin müzik",
        "title": "Gece Dinlemelik",
        "subtitle": "Günün sonunda sakinleşmek için",
        "period": "monthly", "limit": 10,
    },
    {
        "id": "mood_chill", "kind": "search",
        "query": "chill müzik lofi",
        "title": "Chill",
        "subtitle": "Sakin bir tempoda takılmak için",
        "period": "monthly", "limit": 10,
    },
    {
        "id": "mood_car", "kind": "search",
        "query": "arabada dinlenecek şarkılar",
        "title": "Arabada",
        "subtitle": "Yolda enerjini yüksek tutacak parçalar",
        "period": "monthly", "limit": 10,
    },
    {
        "id": "mood_energy", "kind": "search",
        "query": "yüksek enerji motivasyon müzik",
        "title": "Yüksek Enerji",
        "subtitle": "Tempoyu yükseltmek istediğinde",
        "period": "monthly", "limit": 10,
    },
    {
        "id": "rising_artists", "kind": "artist",
        "query": "yükselen sanatçılar türkçe",
        "title": "Sanatçı Keşfi",
        "subtitle": "Son dönemde yükselişte olan sanatçılar",
        "period": "monthly", "limit": 10,
    },
]

# --- Veri kaynağı türleri (Keşfet'te kullanıcıya açıkça gösterilir) ---
# `ranked=True` yalnızca GERÇEK sıralı liste verisi için geçerlidir; arama
# sonuçları asla sıralama gibi sunulmaz (sıra rozeti gösterilmez).
SOURCES = {
    "spotify_chart": {"label": "Spotify resmi listesi (YouTube'da eşleştirildi)", "ranked": True},
    "ytmusic_chart": {"label": "YouTube Music Charts", "ranked": True},
    "youtube_search": {"label": "YouTube arama sonuçları (sıralama değildir)", "ranked": False},
}
SEARCH_ONLY_SUBTITLE = "Sıralı liste alınamadı; arama sonuçlarından derlendi"

# --- Bayatlık / refresh zamanlaması ---
PERIOD_SECONDS = {
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
    "monthly": 30 * 24 * 3600,
    "yearly": 365 * 24 * 3600,
}
LIGHT_REFRESH_SECONDS = 6 * 3600    # cache 6 saatten eskiyse hafif refresh yapılabilir
MAJOR_REFRESH_SECONDS = 24 * 3600   # büyük discovery refresh'i günde 1 kez


class DiscoveryService:
    """Keşfet ekranı verilerini toplar, doğrular ve diske önbellekler."""

    def __init__(self, cache_dir: str | None, settings: dict | None = None,
                 save_settings_fn=None):
        self.cache_dir = cache_dir
        self._cache_path = (
            os.path.join(cache_dir, CACHE_FILENAME) if cache_dir else None
        )
        # Spotify (opsiyonel): settings sözlüğü ve save_settings_fn verilirse,
        # kullanıcı daha önce bağlanmışsa (spotify_refresh_token mevcutsa)
        # chart kategorileri Spotify'ı dener; verilmezse Spotify hiç
        # denenmez, sessizce YouTube arama yedeği kullanılır.
        self.settings = settings or {}
        self.save_settings_fn = save_settings_fn
        self.spotify_client_id = self.settings.get("spotify_client_id", "")
        self.spotify_client_secret = self.settings.get("spotify_client_secret", "")
        # Playlist adı -> ID çözümlemeleri (örn. "Top 50 - Türkiye" -> "37i9...").
        # Bir kez arama yapılıp bulununca önbellekten taşınır, her refresh'te
        # tekrar Spotify'da aranmaz.
        self._resolved_playlist_ids: dict[str, str] = (
            (self.get_cached_data() or {}).get("spotify_playlist_ids", {}))

    # --- Önbellek G/Ç ---
    def get_cached_data(self) -> dict | None:
        """Diskteki son başarılı önbelleği döner (yoksa None). İnternet
        olmasa bile UI'nın boş kalmaması için kullanılır."""
        if not self._cache_path or not os.path.exists(self._cache_path):
            return None
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("version") != CACHE_VERSION:
                return None
            return data
        except Exception as e:
            log.error("%s %s", "Keşfet önbelleği okunamadı:", e)
            return None

    def _save_cache(self, data: dict):
        if not self._cache_path:
            return
        try:
            atomic_write_json(self._cache_path, data, indent=2)
        except Exception as e:
            log.error("%s %s", "Keşfet önbelleği yazılamadı:", e)

    # --- Bayatlık kontrolü ---
    def _section_is_stale(self, section: dict | None, now: float) -> bool:
        if section is None:
            return True
        updated = section.get("updated_at", 0)
        period = section.get("period", "weekly")
        ttl = PERIOD_SECONDS.get(period, PERIOD_SECONDS["weekly"])
        return (now - updated) > ttl

    def refresh_if_needed(self, force: bool = False, on_section=None) -> dict:
        """Önbelleği kontrol edip gereken bölümleri tazeler.

        `on_section(section_dict)` verilirse her bölüm tazelenir tazelenmez
        çağrılır — böylece çağıran taraf (UI) sonuçları geldikçe kart
        kart gösterebilir; tüm keşfin bitmesini beklemek zorunda kalmaz.

        Bir bölümün güncellenmesi başarısız olursa (internet yok / hata),
        o bölümün ÖNCEKİ önbellek verisi korunur — hiçbir bölüm tamamen
        kaybolmaz.
        """
        now = time.time()
        cache = self.get_cached_data() or {
            "last_updated": 0, "region": "TR", "sections": [], "hero": None,
        }
        old_sections = {s["id"]: s for s in cache.get("sections", []) if s.get("id")}
        last_updated = cache.get("last_updated", 0)
        do_light = force or (now - last_updated) > LIGHT_REFRESH_SECONDS
        do_major = force or (now - last_updated) > MAJOR_REFRESH_SECONDS

        new_sections = []
        for cat in CATEGORY_DEFS:
            old = old_sections.get(cat["id"])
            stale = self._section_is_stale(old, now)
            should_fetch = force or stale or (old is None and do_light)
            if not should_fetch and old is not None:
                new_sections.append(old)
                continue
            try:
                section = self._build_section(cat, now)
            except Exception as e:
                log.error("%s %s", f"Bölüm '{cat['id']}' güncellenemedi:", e)
                section = None
            if section is None:
                section = old  # veri gelmediyse eski (varsa) korunur
            if section is not None:
                new_sections.append(section)
                if on_section:
                    try:
                        on_section(section)
                    except Exception as e:
                        log.error("%s %s", "on_section geri çağrısı hata verdi:", e)

        hero = cache.get("hero")
        if force or do_major or hero is None:
            try:
                built_hero = self._build_hero(new_sections)
                if built_hero is not None:
                    hero = built_hero
            except Exception as e:
                log.error("%s %s", "Öne çıkan (hero) içerik oluşturulamadı:", e)

        new_cache = {
            "version": CACHE_VERSION,
            "last_updated": now,
            "region": "TR",
            "hero": hero,
            "sections": new_sections,
            "spotify_playlist_ids": self._resolved_playlist_ids,
        }
        self._save_cache(new_cache)
        return new_cache

    # --- Bölüm inşası ---
    def fetch_category(self, cat: dict) -> list[dict]:
        """Yalnızca öğeleri döner (geriye dönük uyumluluk). Kaynak bilgisi için
        `fetch_category_ex` kullanılır."""
        return self.fetch_category_ex(cat)[0]

    def fetch_category_ex(self, cat: dict) -> tuple[list[dict], str]:
        """(öğeler, kaynak_id) döner. kaynak_id `SOURCES` anahtarlarından biridir.

        `spotify_playlist_query` doluysa ve kullanıcı Spotify'a bağlıysa, gerçek
        Spotify chart'ı denenir; olmazsa YouTube Music Charts, o da olmazsa
        arama tabanlı yedek kullanılır — kategori kaybolmaz ama kaynak her
        zaman doğru etiketlenir."""
        query = cat.get("spotify_playlist_query")
        if query:
            playlist_id = self._resolve_spotify_playlist_id(query)
            if playlist_id:
                spotify_items = self._fetch_spotify_chart(playlist_id, limit=cat.get("limit", 12))
                if spotify_items:
                    return spotify_items, "spotify_chart"

        kind = cat.get("kind")
        if kind == "chart":
            return self.fetch_trending_ex(cat.get("region", "TR"), limit=cat.get("limit", 12))
        if kind == "artist":
            return self._fetch_artist_discovery(cat.get("query", ""), limit=cat.get("limit", 10)), "youtube_search"
        return self.fetch_search_based_category(cat.get("query", ""), limit=cat.get("limit", 12)), "youtube_search"

    def _resolve_spotify_playlist_id(self, query: str) -> str | None:
        """'Top 50 - Türkiye' gibi bir playlist adını Spotify'da arayıp
        ID'sini bulur; bulununca örnek-ömrü boyunca (ve diskte) önbelleğe
        alınır. Kullanıcı Spotify'a bağlı değilse arama hiç yapılmaz."""
        if not self.spotify_client_id:
            return None
        if not self.settings.get("spotify_refresh_token"):
            return None
        if query in self._resolved_playlist_ids:
            return self._resolved_playlist_ids[query]
        try:
            playlist_id, _name = search_spotify_playlist(
                query, self.spotify_client_id, self.spotify_client_secret,
                self.settings, self.save_settings_fn or (lambda: None))
        except Exception as e:
            log.error("%s %s", f"Spotify playlist aranamadı ('{query}'):", e)
            return None
        if playlist_id:
            self._resolved_playlist_ids[query] = playlist_id
        return playlist_id

    def _fetch_spotify_chart(self, playlist_id: str, limit: int = 12) -> list[dict]:
        """Kullanıcının daha önce bağladığı bir Spotify hesabı üzerinden resmi
        bir chart playlist'ini çeker ve her track'i YouTube'da arayıp
        eşleştirir. Kullanıcı hiç bağlanmamışsa (refresh_token yok) arka
        planda tarayıcı AÇMADAN sessizce [] döner (çağıran taraf fallback'e düşer)."""
        if not self.spotify_client_id:
            return []
        if not self.settings.get("spotify_refresh_token"):
            return []  # kullanıcı hiç bağlanmamış — sessizce vazgeç, tarayıcı açma

        try:
            _, queries = fetch_spotify_playlist(
                playlist_id, self.spotify_client_id, self.spotify_client_secret,
                self.settings, self.save_settings_fn or (lambda: None))
        except Exception as e:
            log.error("%s %s", f"Spotify playlist çekilemedi ({playlist_id}):", e)
            return []

        # Her "Sanatçı - Şarkı" sorgusu için tek bir YouTube araması yapılır.
        # Bu, kategori başına `limit` kadar ekstra ağ isteği demektir —
        # yalnızca kullanıcı gerçekten bağlıyken devreye girer.
        ydl_opts = yt_dlp_base_opts(quiet=True, extract_flat=True, noplaylist=True)
        tracks = []
        for q in queries[:limit]:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch1:{q}", download=False)
                entries = info.get("entries") or []
                if entries:
                    t = self._entry_to_track(entries[0])
                    if t:
                        tracks.append(t)
            except Exception as e:
                log.error("%s %s", f"Spotify eşleşmesi YouTube'da bulunamadı ('{q}'):", e)
                continue
        return self._dedupe_and_clean(tracks)

    def build_sections(self, force: bool = False) -> list[dict]:
        """Tüm kategoriler için bölüm listesini (veri varsa) sıfırdan üretir."""
        now = time.time()
        sections = []
        for cat in CATEGORY_DEFS:
            section = self._build_section(cat, now)
            if section is not None:
                sections.append(section)
        return sections

    def _build_section(self, cat: dict, now: float) -> dict | None:
        items, source_id = self.fetch_category_ex(cat)
        if not items:
            return None  # veri yoksa bölüm hiç oluşturulmasın (gizlensin)
        source = SOURCES[source_id]
        # Sıralı bir liste bekleyen kategori (chart) arama yedeğine düştüyse
        # "yükselenler" gibi iddialı alt başlık gösterilmez.
        subtitle = cat.get("subtitle", "")
        if cat.get("kind") == "chart" and not source["ranked"]:
            subtitle = SEARCH_ONLY_SUBTITLE

        title = cat["title"]
        if callable(title):
            title = title(datetime.now())

        return {
            "id": cat["id"],
            "kind": cat.get("kind"),
            "title": title,
            "subtitle": subtitle,
            "source": {"id": source_id, "label": source["label"]},
            "ranked": bool(source["ranked"] and cat.get("show_rank")),
            "period": cat.get("period", "weekly"),
            "updated_at": now,
            "items": items,
        }

    def _build_hero(self, sections: list[dict]) -> dict | None:
        """'Bugünün Keşfi' için bölümlerden rastgele bir parça seçer
        (sanatçı kartı bölümleri hariç). Her refresh'te değişebilir."""
        pool = []
        for s in sections:
            if s.get("kind") == "artist":
                continue
            pool.extend(s.get("items", []))
        if not pool:
            return None
        return dict(random.choice(pool))

    # --- Ham veri çekme ---
    def fetch_trending(self, region: str = "TR", limit: int = 12) -> list[dict]:
        return self.fetch_trending_ex(region, limit)[0]

    def fetch_trending_ex(self, region: str = "TR", limit: int = 12) -> tuple[list[dict], str]:
        tracks = self._dedupe_and_clean(self._fetch_from_ytmusic_charts(region))[:limit]
        if tracks:
            return tracks, "ytmusic_chart"
        tracks = self._fetch_from_youtube_trending(region, limit=limit * 2)
        return self._dedupe_and_clean(tracks)[:limit], "youtube_search"

    def _fetch_from_ytmusic_songs(self, query: str, limit: int = 12) -> list[dict]:
        """YouTube Music 'songs' filtresi ile yalnızca doğrulanmış gerçek
        müzik parçalarını çeker (podcast, 1 saatlik mix, tepki videosu,
        Shorts gibi alakasız sonuçları otomatik dışlar)."""
        if not YTMUSICAPI_AVAILABLE or not query:
            return []
        try:
            yt_music = YTMusic()
            items = yt_music.search(query, filter="songs", limit=limit * 2) or []
        except Exception as e:
            log.error("%s %s", f"YTMusic şarkı araması başarısız ('{query}'):", e)
            return []

        tracks: list[dict] = []
        for item in items:
            vid = item.get("videoId")
            if not vid:
                continue
            thumbs = item.get("thumbnails") or []
            thumb = thumbs[-1].get("url") if thumbs else None
            artists = ", ".join(
                a.get("name", "") for a in (item.get("artists") or [])
                if isinstance(a, dict) and a.get("name")
            ) or "Bilinmeyen Sanatçı"
            clean_title, clean_artist = parse_track_and_artist(
                item.get("title", "Bilinmeyen Şarkı"), artists, item,
            )
            dur = item.get("duration_seconds") or 0
            tracks.append({
                "title": clean_title,
                "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                "duration": dur,
                "uploader": clean_artist,
                "thumbnail": thumb,
                "liked": False,
                "added_date": datetime.now().isoformat(),
            })
        return tracks

    def fetch_search_based_category(self, query: str, limit: int = 12) -> list[dict]:
        if not query:
            return []
        # Öncelik: YTMusic songs araması (gerçek şarkılar, spam/mix/podcast yok)
        ytm_tracks = self._dedupe_and_clean(self._fetch_from_ytmusic_songs(query, limit=limit))
        if ytm_tracks:
            return ytm_tracks[:limit]

        # Yedek: yt-dlp arama + sıkı süre/başlık filtresi
        ydl_opts = yt_dlp_base_opts(quiet=True, extract_flat=True, noplaylist=True)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit * 2}:{query}", download=False)
        except Exception as e:
            log.error("%s %s", f"Keşfet sorgusu başarısız ('{query}'):", e)
            return []
        tracks = [self._entry_to_track(e) for e in (info.get("entries") or [])]
        tracks = [t for t in tracks if t]
        return self._dedupe_and_clean(tracks)[:limit]

    def _fetch_artist_discovery(self, query: str, limit: int = 10) -> list[dict]:
        """Öncelikle YTMusic 'artists' filtresiyle gerçek sanatçı profilleri
        çeker; çalışmazsa yt-dlp kanal keşfine düşer."""
        if not query:
            return []
        if YTMUSICAPI_AVAILABLE:
            try:
                yt_music = YTMusic()
                items = yt_music.search(query, filter="artists", limit=limit * 2) or []
                artists = []
                seen = set()
                for item in items:
                    name = item.get("artist")
                    if not name or name in seen:
                        continue
                    thumbs = item.get("thumbnails") or []
                    thumb = thumbs[-1].get("url") if thumbs else None
                    if not thumb:
                        continue
                    seen.add(name)
                    artists.append({
                        "name": name,
                        "thumbnail": thumb,
                        "subtitle": "Popüler Sanatçı",
                        "browse_id": item.get("browseId", ""),
                    })
                    if len(artists) >= limit:
                        return artists
            except Exception as e:
                log.error("%s %s", f"YTMusic sanatçı araması başarısız ('{query}'):", e)

        ydl_opts = yt_dlp_base_opts(quiet=True, extract_flat=True, noplaylist=True)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit * 4}:{query}", download=False)
        except Exception as e:
            log.error("%s %s", f"Sanatçı keşfi sorgusu başarısız ('{query}'):", e)
            return []

        seen = set()
        artists = []
        for entry in (info.get("entries") or []):
            name = entry.get("uploader") or entry.get("channel")
            if not name or name in seen:
                continue
            seen.add(name)
            thumb = entry.get("thumbnail")
            if not thumb:
                thumbs = entry.get("thumbnails") or []
                thumb = thumbs[-1].get("url") if thumbs else None
            if not thumb:
                continue
            artists.append({
                "name": name,
                "thumbnail": thumb,
                "subtitle": "Son dönemde yükselişte",
                "channel_url": entry.get("channel_url") or entry.get("uploader_url"),
            })
            if len(artists) >= limit:
                break
        return artists

    def _fetch_from_ytmusic_charts(self, region: str) -> list[dict]:
        if not YTMUSICAPI_AVAILABLE:
            return []
        try:
            yt_music = YTMusic()
            charts = yt_music.get_charts(region)
        except Exception as e:
            log.error("%s %s", f"ytmusicapi ile '{region}' trend listesi alınamadı:", e)
            return []

        tracks = []
        for section_key in ("songs", "trending", "videos"):
            if tracks:
                break   # farklı chart bölümlerini birleştirme: sıra tek listeden gelsin
            try:
                section = charts.get(section_key)
                if section is None:
                    continue
                items = section if isinstance(section, list) else (section.get("items") or [])
                for item in items:
                    video_id = item.get("videoId")
                    if not video_id:
                        continue
                    artists = ", ".join(
                        a["name"] for a in (item.get("artists") or []) if a.get("name"))
                    thumbs = item.get("thumbnails") or []
                    tracks.append({
                        "title": item.get("title") or "Bilinmeyen Şarkı",
                        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
                        "duration": 0,
                        "uploader": artists or "Bilinmeyen Sanatçı",
                        "thumbnail": thumbs[-1].get("url") if thumbs else None,
                        "liked": False,
                        "added_date": datetime.now().isoformat(),
                    })
            except Exception as e:
                log.error("%s %s", f"ytmusicapi '{section_key}' bölümü işlenemedi:", e)
        return tracks

    # YouTube'un "feed/trending" sekmesine dokümante edilmemiş bir bp
    # NOT: Bu yedek GERÇEK trend verisi değil, arama sonucudur (kaynak: youtube_search).
    # parametresiyle girmek kırılgan (YouTube tarafı sık sık değişiyor ve
    # "Failed to resolve url" hatası verebiliyor). Bunun yerine, ytmusicapi
    # charts başarısız/mevcut değilse, bölgeye göre popüler arama terimleriyle
    # tarama yapan sağlam bir arama tabanlı yedek kullanılır.
    _REGION_TRENDING_QUERIES = {
        "TR": ["türkiye trend müzik", "türkçe yeni çıkan hit şarkılar", "türkiye popüler şarkılar"],
        "US": ["trending music", "top songs this week", "new popular songs"],
    }

    def _fetch_from_youtube_trending(self, region: str, limit: int = 24) -> list[dict]:
        queries = self._REGION_TRENDING_QUERIES.get(
            region, self._REGION_TRENDING_QUERIES["US"])
        per_query = max(6, limit // len(queries))
        ydl_opts = yt_dlp_base_opts(quiet=True, extract_flat=True, noplaylist=True)
        tracks = []
        for q in queries:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch{per_query}:{q}", download=False)
            except Exception as e:
                log.error("%s %s", f"Trend araması başarısız ('{q}'):", e)
                continue
            tracks.extend(self._entry_to_track(e) for e in (info.get("entries") or []))
        return [t for t in tracks if t]

    # --- Veri dönüştürme ---
    def _entry_to_track(self, entry) -> dict | None:
        if not entry or not entry.get("title"):
            return None
        video_id = entry.get("id")
        webpage_url = entry.get("url") or (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else None)
        if not webpage_url:
            return None
        thumb = entry.get("thumbnail")
        if not thumb:
            thumbs = entry.get("thumbnails") or []
            thumb = thumbs[-1].get("url") if thumbs else None
        clean_title, clean_artist = parse_track_and_artist(
            entry.get("title", "Bilinmeyen Şarkı"),
            entry.get("uploader") or entry.get("channel") or "Bilinmeyen Sanatçı",
            entry,
        )
        return {
            "title": clean_title,
            "webpage_url": webpage_url,
            "duration": entry.get("duration", 0) or 0,
            "uploader": clean_artist,
            "thumbnail": thumb,
            "liked": False,
            "added_date": datetime.now().isoformat(),
        }

    # --- Doğrulama / tekilleştirme ---
    _JUNK_TAGS = (
        "official audio", "official video", "official music video",
        "lyric video", "lyrics", "- topic", "audio", "visualizer",
        "official mv", "mv",
    )

    def _normalized_key(self, track: dict) -> str:
        """Aynı şarkının 'Official Video' / 'Official Audio' / '- Topic' gibi
        farklı upload'larını tek bir anahtara indirger, böylece aynı şarkının
        5 farklı videosu aynı kategoride gösterilmez."""
        title = (track.get("title") or "").lower()
        for tag in self._JUNK_TAGS:
            title = title.replace(tag, "")
        for ch in "()[]{}|-–—":
            title = title.replace(ch, " ")
        title = " ".join(title.split())
        uploader = (track.get("uploader") or "").lower().replace(" - topic", "").strip()
        return f"{title}::{uploader}"

    _BAD_TITLE_MARKERS = (
        "1 saat", "2 saat", "3 saat", "1 hour", "2 hours", "full album",
        "nonstop", "compilation", "derleme", "reaction", "tepki",
        "podcast", "röportaj", "interview", "#shorts", "tiktok",
        "slowed", "reverb", "speed up", "sped up", "nightcore",
        "8d audio", "karaoke", "canlı yayın", "live stream",
        "top 10", "top 20", "top 50", "en iyi 10", "en iyi 20", "best of",
    )

    def _is_valid_music_track(self, track: dict) -> bool:
        """Shorts, uzun mix/podcast ve spam başlıkları eler."""
        dur = track.get("duration") or 0
        if dur > 0 and (dur < 75 or dur > 540):
            return False
        title_l = (track.get("title") or "").lower()
        return not any(marker in title_l for marker in self._BAD_TITLE_MARKERS)

    def _dedupe_and_clean(self, tracks: list[dict]) -> list[dict]:
        cleaned = []
        seen_urls = set()
        seen_keys = set()
        for t in tracks:
            if not t or not t.get("title") or not t.get("webpage_url"):
                continue  # boş title / bozuk URL
            if not t.get("thumbnail"):
                continue  # thumbnail olmayanlar filtrelenir
            if not self._is_valid_music_track(t):
                continue  # alakasız mix/podcast/shorts/spam
            url = t["webpage_url"]
            if url in seen_urls:
                continue  # duplicate
            key = self._normalized_key(t)
            if key in seen_keys:
                continue  # aynı şarkının farklı upload'u
            seen_urls.add(url)
            seen_keys.add(key)
            cleaned.append(t)
        return cleaned

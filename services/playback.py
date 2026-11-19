"""
VLC tabanlı oynatma motoru + YouTube arama/indirme.

Qt sinyalleri sayesinde arka plan thread'lerinden (arama, stream çözme,
indirme) doğrudan `.emit()` çağırmak yeterli — bağlı slot otomatik olarak GUI
thread'inde çalışır (tkinter'daki `self.after(0, fn)` jimnastiğine gerek yok).
"""
from __future__ import annotations

import math
import random
import threading
import time
from datetime import datetime

import vlc
import yt_dlp
from PySide6.QtCore import QObject, QTimer, Signal

from mustiefly_qt.helpers.constants import (
    AppPaths, needs_stream_resolve, offline_path_for, resolve_stream_url, yt_dlp_base_opts,
)
from mustiefly_qt.helpers.lyrics import parse_track_and_artist
from mustiefly_qt.services.history_store import HistoryStore
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
UI_TICK_MS = 500
PRELOAD_AHEAD = 3                 # kaç şarkı önceden çözülür
PRELOAD_ATTEMPTS = 3              # ön yüklemede şarkı başına deneme
PRELOAD_RETRY_DELAYS = (3.0, 8.0)  # denemeler arası bekleme (sn)
PLAY_ATTEMPTS = 3                 # çalarken çözümleme denemesi
PLAY_RETRY_DELAYS = (1.0, 2.5)

# Tekrar denemekle düzelmeyecek hatalar (video kaldırılmış/özel/yaş sınırı...)
_PERMANENT_ERROR_MARKERS = (
    "video unavailable", "private video", "has been removed", "copyright",
    "confirm your age", "members-only", "not available in your country",
    "account associated with this video has been terminated",
)


def _is_permanent_error(e: Exception) -> bool:
    if isinstance(e, (FileNotFoundError, KeyError)):
        return True
    lower = str(e).lower()
    return any(marker in lower for marker in _PERMANENT_ERROR_MARKERS)


def _is_extraction_error(e: Exception) -> bool:
    """YouTube çıkarımı bozuldu mu (yt-dlp güncellemesi gerektirebilir)?"""
    if _is_permanent_error(e):
        return False
    lower = str(e).lower()
    return any(t in lower for t in (
        "unable to extract", "failed to extract", "no video formats", "requested format",
        "http error 403", "signature", "nsig", "player response", "sign in to confirm you",
    ))


def _friendly_ytdlp_message(e: Exception) -> str:
    """yt-dlp/YouTube hatalarını kullanıcının anlayabileceği bir mesaja çevirir.

    YouTube sık sık sayfa yapısını değiştirir ve eski bir yt-dlp sürümü
    şarkı çözümlemeyi (extraction) sessizce bozar. Önceden kullanıcı sadece
    "Stream çözümleme hatası: <teknik traceback>" görüyordu; bu, güncelleme
    yapması gerektiğini asla anlamasını sağlamıyordu.
    """
    text = str(e)
    lower = text.lower()
    ytdlp_hint_triggers = (
        "unable to extract", "http error 403", "http error 429",
        "sign in to confirm", "video unavailable", "unsupported url",
        "failed to extract", "no video formats", "requested format",
    )
    if isinstance(e, yt_dlp.utils.DownloadError) or any(t in lower for t in ytdlp_hint_triggers):
        return (
            f"{text}\n\n"
            "Bu genelde yt-dlp'nin güncel olmamasından kaynaklanır (YouTube "
            "sık sık değişiyor). Ayarlar'dan yt-dlp'yi güncelleyip tekrar dene."
        )
    return text


class PlaybackEngine(QObject):
    statusMessage = Signal(str, str)                  # (mesaj, seviye)
    songLoading = Signal(str, int, dict)               # playlist, index, song
    songStarted = Signal(str, int, dict, bool)         # playlist, index, song, is_offline
    playError = Signal(str, int)
    playStateChanged = Signal(bool)                    # True=çalıyor
    positionChanged = Signal(int, int)                 # current_ms, total_ms
    volumeChanged = Signal(int)
    seeked = Signal(int)                               # kullanıcı/uzak sarma (ms) — Birlikte Dinle dinler
    searchResults = Signal(list)                       # arama sonuçları (dict listesi)
    searchFailed = Signal(str)
    songEnded = Signal()
    shuffleChanged = Signal(bool)                      # karışık çal modu deşti
    repeatChanged = Signal(str)                        # tekrar modu değişti (off | all | one)
    radioStarted = Signal(dict)                        # radyo istasyonu çalmaya başladı
    radioStopped = Signal()
    vocalRemoverChanged = Signal(bool)                 # Vokal ayırma / enstrümantal durumu (True=vokal kısık)
    soundModeChanged = Signal(str)                     # Aktif ses efekt modu (normal/slowed/speed_up/nightcore/bass_boost/night_mode)
    # YouTube çıkarımı bozuk görünüyor (yt-dlp güncellemesi gerekebilir) — hata metni
    extractionFailed = Signal(str)
    # Crossfade iç sinyalleri: worker thread'den GUI'ye güvenli geçiş
    _xfadeResolved = Signal(int, object, str, int, str, bool)       # playlist, index, url, is_offline
    _xfadeFailed = Signal(int)
    # Stream çözümleme bitti: çalmayı GUI thread'inde başlat. DİKKAT: bunu
    # doğrudan worker'dan çağırmak yanlış — QTimer.singleShot worker
    # thread'inden fırlatılırsa HİÇ TETİKLENMİYOR (test edildi); oturum devamı
    # (1500ms seek) ve ön yükleme (500ms) bu yüzden sessizce ölüyordu.
    _playbackReady = Signal(int, object, str, int, str, bool)
    _playbackFailed = Signal(int, object, str, int, str)

    def __init__(self, store: PlaylistStore, paths: AppPaths, settings: dict, parent=None):
        super().__init__(parent)
        self.store = store
        self._song_index: dict[int, tuple[str, int]] = {}
        self.store.playlistsChanged.connect(self._rebuild_song_index)
        self._rebuild_song_index()
        self.paths = paths
        self.settings = settings
        self._closed = False
        self._play_generation = 0
        self._xfade_generation = 0

        self.vlc_instance = vlc.Instance("--no-video", "--quiet", "--network-caching=1500")
        self.player = self.vlc_instance.media_player_new()

        self.playing_playlist: str | None = None
        self.current_index: int = -1
        self.is_loading = False
        self.is_seeking = False
        self.shuffle_mode = False
        self.repeat_mode = "off"  # off | all | one
        self._consecutive_play_failures = 0
        # Son çalma isteği otomatik/sıradaki mi (True) yoksa kullanıcının doğrudan seçimi mi (False)?
        # Doğrudan seçilen şarkı çalınamazsa listede ileri atlanmaz; hata gösterilip durulur.
        self._play_is_auto = False
        # Kullanıcı bilinçli duraklattı mı? Başlatma bekçisi (watchdog) bu
        # durumda çalmayı zorla yeniden başlatmasın diye tutulur.
        self._user_paused = False
        self._reported_error_gen = -1      # aynı hata için tekrar tekrar bildirme
        self._error_retry_song: dict | None = None
        # Oturum geri yükleme: UI doldurulur, çalma ▶ ile kullanıcı başlatır
        self._session_pending = False
        self._resume_ms = 0
        # Şu an çalan şarkının CANLI sözlük referansı — şarkılar silinip
        # taşınınca index'i yeniden çözümlemek için gerekli (resync).
        self._current_song_ref: dict | None = None
        self._current_url: str | None = None
        self._current_is_offline: bool = False
        self._fallback_pos_ms: int | None = None
        # Birlikte Dinle: oda sahibi olmayan kişide şarkı bitince sıradakini oda sahibi seçer
        self.suppress_auto_advance = False
        # Birlikte Dinle ortak sırası: (playlist, index) döndürürse önce o çalınır
        self.next_provider = None
        # Birlikte Dinle: True dönerse crossfade başlatılmaz. Crossfade sıradaki şarkıyı
        # YEREL olarak seçer; odada bunu yalnız oda sahibi (ve ortak sıra boşsa) yapabilir.
        self.crossfade_guard = None
        # Sonsuz Çalma (Autoplay): Çalma listesi sona erdiğinde çağrılır; True dönerse autoplay devreye girer
        self.autoplay_handler = None

        # Radyo modu: playlist çalmasıyla AYNI VLC player'ı paylaşır; radyo
        # çalarken playing_playlist None'a çekilir (orijinal davranış).
        self.radio_playing: dict | None = None

        # Crossfade: ikinci VLC player — mevcut şarkı sona yaklaşırken sıradaki
        # bu player'da başlar, iki ses seviyesi çizgisel kesişir, sonra roller
        # takas edilir. Tüm kod self.player üzerinden çalıştığı için takas
        # dışarıya görünmez.
        self.player_b = self.vlc_instance.media_player_new()
        self._xfade_active = False
        self._xfade_timer: QTimer | None = None
        self._xfade_blend = 0.0  # 0=yeni yok, 1=tamamen yeni player
        self._xfade_queued_raw = None  # geçiş başarısızsa kuyruğa iade edilecek öğe

        # İndirme yöneticisi (MainWindow bağlar; yoksa eski sessiz yol çalışır)
        self.download_manager = None

        # Ekolayzer (VLC AudioEqualizer) — kayıtlı ayarlar varsa uygulanır
        self.equalizer = None
        self.eq_band_count = 0
        self.eq_preset_names: list[str] = []
        self._vocal_remover_active = bool(self.settings.get("vocal_remover_enabled", False))
        self._setup_equalizer()

        self.next_song_preloaded = None
        self._preloading: set[int] = set()   # şu an ön yüklemesi süren şarkılar (id)
        self._preload_timer = QTimer(self)
        self._preload_timer.setSingleShot(True)
        self._preload_timer.setInterval(800)
        self._preload_timer.timeout.connect(self.preload_next_song)
        self.store.queueChanged.connect(self._schedule_preload)
        # Dinleme geçmişi: gerçekten dinlenen süre tick döngüsünde biriktirilir
        self.history = HistoryStore(paths.dir)
        self._listen: dict | None = None
        self._volume_scale = 1.0
        self._shuffle_plan = None  # (liste, şimdiki index, uzunluk, seçilen sıradaki)
        self.preload_lock = threading.Lock()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._update_ui_loop)
        self._tick_timer.start(UI_TICK_MS)

        self._xfadeResolved.connect(self._begin_crossfade)
        self._xfadeFailed.connect(self._on_xfade_failed)
        self._playbackReady.connect(self._start_playback)
        self._playbackFailed.connect(self._on_resolve_failed)

    @property
    def current_song(self) -> dict | None:
        """Şu an çalan şarkının sözlük referansı."""
        if self._current_song_ref is not None:
            return self._current_song_ref
        pl = self.playing_playlist
        idx = self.current_index
        if pl and idx >= 0:
            songs = self.store.playlists.get(pl, [])
            if 0 <= idx < len(songs):
                return songs[idx]
        return None

    @property
    def is_playing(self) -> bool:
        """Müziğin aktif çalıp çalmadığını döndürür."""
        try:
            return bool(self.player.is_playing())
        except Exception:
            return False

    # --- Ekolayzer ---
    def _setup_equalizer(self):
        """VLC'nin native ekolayzerini hazırlar ve kayıtlı ayarları (varsa) uygular."""
        try:
            self.eq_band_count = vlc.libvlc_audio_equalizer_get_band_count()
            preset_count = vlc.libvlc_audio_equalizer_get_preset_count()
            self.eq_preset_names = [
                vlc.libvlc_audio_equalizer_get_preset_name(i).decode('utf-8', 'ignore')
                for i in range(preset_count)
            ]
        except Exception as e:
            log.error("%s %s", "Ekolayzer bilgisi alınamadı (VLC sürümü desteklemiyor olabilir):", e)
            self.eq_band_count = 0
            self.eq_preset_names = []
            return

        if self.settings.get("equalizer_enabled") and self.eq_band_count:
            try:
                eq = vlc.AudioEqualizer()
                eq.set_preamp(float(self.settings.get("equalizer_preamp", 0.0)))
                bands = self.settings.get("equalizer_bands", [0.0] * self.eq_band_count)
                for i in range(self.eq_band_count):
                    eq.set_amp_at_index(float(bands[i] if i < len(bands) else 0.0), i)
                self.equalizer = eq
            except Exception as e:
                log.error("%s %s", "Kayıtlı ekolayzer ayarları uygulanamadı:", e)

        self._apply_active_equalizer()

    def _create_vocal_remover_equalizer(self):
        """Vokal frekanslarını (250Hz - 4000Hz) -20dB'ye kadar bastıran enstrümantal karaoke ekolayzeri."""
        cached_eq = getattr(self, "_vocal_eq", None)
        if cached_eq is not None:
            return cached_eq
        if not hasattr(vlc, "AudioEqualizer") or not self.eq_band_count:
            return None
        try:
            eq = vlc.AudioEqualizer()
            eq.set_preamp(-1.0)
            # 10 Bant: 31.25Hz, 62.5Hz, 125Hz, 250Hz, 500Hz, 1kHz, 2kHz, 4kHz, 8kHz, 16kHz
            # Vokal formant ve temel seslerini (250Hz-4kHz) bastırırken basları ve tizleri güçlendirir.
            bands = [3.0, 4.0, 1.0, -15.0, -20.0, -20.0, -18.0, -14.0, 2.0, 4.0]
            for i in range(min(self.eq_band_count, len(bands))):
                eq.set_amp_at_index(bands[i], i)
            self._vocal_eq = eq
            return eq
        except Exception as e:
            log.warning("Vokal bastırma ekolayzeri oluşturulamadı: %s", e)
            return None

    def _apply_active_equalizer(self):
        """Aktif duruma göre (vokal modu veya kullanıcı ekolayzeri) player'lara ekolayzeri canlı bağlar."""
        target_eq = None
        if self.vocal_remover_enabled:
            target_eq = self._create_vocal_remover_equalizer()
        elif self.settings.get("equalizer_enabled") and self.equalizer is not None:
            target_eq = self.equalizer

        for p in (getattr(self, "player", None), getattr(self, "player_b", None)):
            if p is not None:
                try:
                    p.set_equalizer(target_eq)
                except Exception:
                    pass

    def apply_equalizer(self, eq):
        """Ekolayzer penceresinden gelen eşitlerleyiciyi canlı uygular.
        Crossfade takaslarından bağımsız olarak HER İKİ player'a da uygulanır;
        aksi halde fade bitiminde ekolayzer 'kaybolur'."""
        self.equalizer = eq
        if not self.vocal_remover_enabled:
            for p in (self.player, self.player_b):
                if p is not None:
                    try:
                        p.set_equalizer(eq)
                    except Exception as e:
                        log.error("%s %s", "Ekolayzer uygulanamadı:", e)

    def apply_equalizer_bands(self, bands: list[float], enabled: bool = True):
        """10-bant float listesini VLC AudioEqualizer'a çevirip canlı uygular."""
        self.settings["equalizer_bands"] = [float(b) for b in bands]
        self.settings["equalizer_enabled"] = bool(enabled)
        if not enabled:
            self.equalizer = None
            self._apply_active_equalizer()
            return
        try:
            eq = vlc.AudioEqualizer()
            for i, amp in enumerate(bands[:self.eq_band_count]):
                eq.set_amp_at_index(float(amp), i)
            self.equalizer = eq
        except Exception as e:
            log.warning("Ekolayzer bantları uygulanamadı: %s", e)
        self._apply_active_equalizer()

    # --- Arama ---
    def search(self, query: str):
        self._search_seq = getattr(self, "_search_seq", 0) + 1
        seq = self._search_seq
        threading.Thread(target=self._search_worker, args=(query, seq), daemon=True).start()

    def _search_worker(self, query: str, seq: int = 0):
        # extract_flat: sonuçları TEK TEK tam çözümlemek (tüm format listesi)
        # aramayı ~5 kat yavaşlatıyordu; liste metaverisi arama için yeterli.
        ydl_opts = yt_dlp_base_opts(quiet=True, default_search="ytsearch5:",
                                     noplaylist=True, extract_flat="in_playlist")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
            if info is None:
                raise Exception("Sonuç bulunamadı")
            entries = [e for e in info["entries"] if e][:5] if "entries" in info else [info]
            if not entries:
                raise Exception("Sonuç bulunamadı")

            results = []
            for e in entries:
                url = e.get("webpage_url") or e.get("url") or ""
                if url and not url.startswith("http") and e.get("id"):
                    url = f"https://www.youtube.com/watch?v={e['id']}"
                if not url:
                    continue
                thumb = e.get("thumbnail")
                if not thumb and e.get("thumbnails"):
                    thumb = e["thumbnails"][-1].get("url")
                clean_title, clean_artist = parse_track_and_artist(
                    e.get("title", "Bilinmeyen Şarkı"),
                    e.get("uploader") or e.get("channel") or "Bilinmeyen Sanatçı",
                    e,
                )
                results.append({
                    "title": clean_title,
                    "webpage_url": url,
                    "duration": e.get("duration") or 0,
                    "uploader": clean_artist,
                    "thumbnail": thumb,
                    "liked": False,
                    "added_date": datetime.now().isoformat(),
                })
            if not results:
                raise Exception("Sonuç bulunamadı")
            if not self._closed and (not seq or seq == getattr(self, "_search_seq", 0)):
                self.searchResults.emit(results)
        except Exception as e:
            log.error("%s %s", "Arama hatası:", e)
            if not self._closed and (not seq or seq == getattr(self, "_search_seq", 0)):
                self.searchFailed.emit(_friendly_ytdlp_message(e))

    # --- İndirme ---
    def download_song_for_offline(self, playlist_name: str, index: int):
        """Tüm indirmeler tek sistem olan DownloadManager üzerinden yapılır."""
        songs = self.store.playlists.get(playlist_name)
        if not songs or not (0 <= index < len(songs)):
            return
        if self.download_manager is not None:
            self.download_manager.enqueue(playlist_name, index)
            return
        self.statusMessage.emit("İndirme yöneticisi hazır değil; indirme başlatılamadı.", "error")

    # --- Ön yükleme ---
    def _upcoming_songs(self, count: int) -> list[dict]:
        """Çalma sırasına göre sıradaki en fazla `count` şarkı: önce manuel kuyruk,
        sonra liste sırası (karışık modda yalnız planlanmış sıradaki bilinir)."""
        out: list[dict] = []
        seen = {id(self._current_song_ref)} if self._current_song_ref is not None else set()

        def add(song):
            if isinstance(song, dict) and id(song) not in seen:
                seen.add(id(song))
                out.append(song)

        for _pl, _idx, song in list(self.store.manual_queue):
            if len(out) >= count:
                return out
            add(song)
        if self.playing_playlist is None or self.repeat_mode == "one":
            return out
        songs = self.store.playlists.get(self.playing_playlist, [])
        n = len(songs)
        if n == 0:
            return out
        if self.shuffle_mode:
            nxt = self.get_next_index()
            if 0 <= nxt < n:
                add(songs[nxt])
            return out[:count]
        idx = self.current_index
        for _ in range(n):
            if len(out) >= count:
                break
            idx += 1
            if idx >= n:
                if self.repeat_mode != "all":
                    break
                idx = 0
            if idx == self.current_index:
                break
            add(songs[idx])
        return out

    def _schedule_preload(self):
        """(GUI thread) Kuyruk vb. değişince ön yüklemeyi kısa gecikmeyle yeniden planla."""
        if not self._closed:
            self._preload_timer.start()

    def preload_next_song(self):
        """Sıradaki PRELOAD_AHEAD şarkının stream linkini arka planda önceden çözer.

        Eskiden yalnız 1 şarkı hazırlanıyordu ve başarısız olursa bir daha denenmiyordu;
        birkaç şarkı ileri atlayınca ya da YouTube anlık hata verince şarkı "çalınamadı"
        deyip atlanıyordu. Şimdi 3 şarkı sırayla (YouTube'u aynı anda yormadan) çözülür,
        geçici hatalarda artan beklemeyle yeniden denenir.
        """
        if self._closed or self.playing_playlist is None or self.radio_playing is not None:
            return
        pending = [s for s in self._upcoming_songs(PRELOAD_AHEAD) if needs_stream_resolve(s)]
        with self.preload_lock:
            pending = [s for s in pending if id(s) not in self._preloading]
            self._preloading.update(id(s) for s in pending)
        if pending:
            self.next_song_preloaded = pending[0].get("webpage_url")
            threading.Thread(target=self._preload_worker, args=(pending,), daemon=True).start()

    def _preload_worker(self, songs: list[dict]):
        try:
            for song in songs:
                for attempt in range(PRELOAD_ATTEMPTS):
                    if self._closed:
                        return
                    if not needs_stream_resolve(song):
                        break   # bu arada çalınıp çözülmüş olabilir
                    try:
                        resolve_stream_url(song)
                        break
                    except Exception as e:
                        permanent = _is_permanent_error(e)
                        log.warning("Ön yükleme hatası (%s, deneme %d/%d): %s",
                                    song.get("title", "?"), attempt + 1, PRELOAD_ATTEMPTS, e)
                        if permanent or attempt + 1 >= PRELOAD_ATTEMPTS:
                            break
                        time.sleep(PRELOAD_RETRY_DELAYS[min(attempt, len(PRELOAD_RETRY_DELAYS) - 1)])
        finally:
            with self.preload_lock:
                for song in songs:
                    self._preloading.discard(id(song))

    # --- Oynatma ---
    def play_song_at_index(self, playlist_name: str, index: int, auto: bool = False):
        songs = self.store.playlists.get(playlist_name)
        if self._closed or not songs or not (0 <= index < len(songs)):
            return
        self._play_is_auto = auto
        # Devam eden bir crossfade varsa temizle: kullanıcı açıkça başka şarkı
        # seçti — yumuşak geçiğin anlamı kalmadı.
        self._abort_crossfade()
        # Radyo modundan şarkıya geçiş: radyo durumunu temizlemezsek
        # toggle_play_pause/now-playing/waveform radyo sanmaya devam ederdi.
        if self.radio_playing is not None:
            self.stop_radio()
        # Oturumdan kalan "şu saniyeye sar" bilgisi yalnız O şarkı için geçerli;
        # başka şarkı seçilirse yeni şarkıyı eski şarkının saniyesine sarmasın.
        if not (self._session_pending and playlist_name == self.playing_playlist
                and index == self.current_index):
            self._resume_ms = 0
        self._user_paused = False
        self._play_generation += 1
        generation = self._play_generation
        self.is_loading = True
        self.playing_playlist = playlist_name
        self.current_index = index
        song = songs[index]
        self.songLoading.emit(playlist_name, index, song)
        threading.Thread(target=self._resolve_and_play,
                         args=(generation, playlist_name, index, song), daemon=True).start()

    def _resolve_and_play(self, generation, playlist_name, index, song):
        url = is_offline = None
        for attempt in range(PLAY_ATTEMPTS):
            try:
                url, is_offline = resolve_stream_url(song)
                break
            except Exception as e:
                log.error("Stream çözümleme hatası (deneme %d/%d): %s", attempt + 1, PLAY_ATTEMPTS, e)
                if (attempt + 1 < PLAY_ATTEMPTS and not _is_permanent_error(e)
                        and not self._closed and generation == self._play_generation):
                    # geçici ağ/YouTube hatası: artan beklemeyle tekrar dene
                    time.sleep(PLAY_RETRY_DELAYS[min(attempt, len(PLAY_RETRY_DELAYS) - 1)])
                    if generation != self._play_generation:
                        return
                    continue
                if not self._closed:
                    if _is_extraction_error(e):
                        self.extractionFailed.emit(str(e))
                    self._playbackFailed.emit(generation, song, playlist_name, index,
                                              _friendly_ytdlp_message(e))
                return
        # GUI thread'ine sinyalle devret: _start_playback içindeki
        # QTimer.singleShot'lar (oturum devamı seek'i + preload) yalnız orada
        # tetiklenir; store.save()'in debounce zamanlayıcısı da öyle.
        if not self._closed:
            self._playbackReady.emit(generation, song, playlist_name, index, url, is_offline)

    def _live_song_location(self, song):
        location = self._song_index.get(id(song))
        if location is not None:
            playlist, index = location
            songs = self.store.playlists.get(playlist, [])
            if index < len(songs) and songs[index] is song:
                return location
        for playlist, songs in self.store.playlists.items():
            for index, candidate in enumerate(songs):
                if candidate is song:
                    return playlist, index
        return None

    def _rebuild_song_index(self):
        self._song_index = {
            id(song): (playlist, index)
            for playlist, songs in self.store.playlists.items()
            for index, song in enumerate(songs)
        }

    def _on_resolve_failed(self, generation, song, playlist_name, index, error):
        if self._closed or generation != self._play_generation:
            return
        self.is_loading = False
        location = self._live_song_location(song)
        if location is None:
            return
        self.playing_playlist, self.current_index = location
        self.statusMessage.emit(f"\"{song.get('title', 'Şarkı')}\" çalınamadı: {error}", "error")
        self.playError.emit(*location)

    def _prepare_media(self, url: str, song: dict | None = None):
        """VLC medyası oluşturur; YouTube CDN'in User-Agent kontrolü ve ses filtre seçeneklerini ekler."""
        media = self.vlc_instance.media_new(url)
        if isinstance(song, dict):
            ua = song.get("http_user_agent")
            if ua and isinstance(url, str) and url.startswith(("http://", "https://")):
                media.add_option(f":http-user-agent={ua}")

        if self.settings.get("audio_normalization"):
            media.add_option(":audio-filter=normvol")
            media.add_option(":norm-buff-size=10")
            media.add_option(":norm-max-level=1.6")
            media.add_option(":audio-replay-gain-mode=track")
            media.add_option(":audio-replay-gain-default=-6.0")
            media.add_option(":audio-replay-gain-peak-protection=1")
        return media

    def _start_playback(self, generation, song, playlist_name, index, url, is_offline=False):
        if self._closed or generation != self._play_generation:
            return
        self.is_loading = False
        location = self._live_song_location(song)
        if location is None:
            return
        playlist_name, index = location
        self.playing_playlist, self.current_index = location
        self._consecutive_play_failures = 0
        self._current_url = url
        self._current_is_offline = is_offline

        old_media = self.player.get_media()
        media = self._prepare_media(url, song)
        # ÖNEMLİ: çalan / duraklatılmış / bitmiş bir player'a doğrudan
        # set_media + play() VLC 3'te yarışa giriyor ve yeni şarkı çoğu zaman
        # "hazır ama duruyor" kalıyordu (▶'a basmadan başlamama hatası).
        # Önce temiz bir stop() ile player'ı sıfırlıyoruz.
        try:
            if self.player.get_state() not in (vlc.State.NothingSpecial, vlc.State.Stopped):
                self.player.stop()
        except Exception as e:
            log.warning("Önceki medya durdurulamadı: %s", e)
        self.player.set_media(media)
        if old_media is not None:
            try:
                old_media.release()
            except Exception:
                pass
        self._user_paused = False
        self._reported_error_gen = -1
        self.player.play()
        self.player.audio_set_volume(self._master_volume())
        self._apply_saved_rate()
        self._apply_active_equalizer()
        self._session_pending = False
        # Başlamadıysa kendini toparlayan bekçi (bkz. _ensure_started)
        QTimer.singleShot(1200, lambda: self._ensure_started(generation, 0))
        if self._resume_ms > 0:
            # Oturumdan devam: medya hazır oluncaya kadar bekleyip pozisyona sar
            resume_ms = self._resume_ms
            self._resume_ms = 0
            QTimer.singleShot(1500, lambda: self.seek(resume_ms)
                              if not self._closed and generation == self._play_generation else None)

        if self._error_retry_song is not song:   # link yenileyip yeniden deneme yeni dinleme sayılmaz
            song["play_count"] = song.get("play_count", 0) + 1
        song["last_played"] = datetime.now().isoformat()
        self.store.save()
        self._current_song_ref = song
        self._begin_listen(song)

        self.songStarted.emit(playlist_name, index, song, is_offline)
        self.playStateChanged.emit(True)
        QTimer.singleShot(500, self.preload_next_song)

    def _ensure_started(self, generation: int, attempt: int):
        """Şarkı başlatıldıktan kısa süre sonra gerçekten çalıp çalmadığını
        denetler. VLC bazen play() sonrası Stopped/Paused'da kalıyor; kullanıcı
        bunu ▶ tuşuna basarak çözüyordu. Burada otomatik yeniden denenir; hâlâ
        çalmıyorsa arayüz yanlış 'çalıyor' göstermesin diye durum düzeltilir."""
        if (self._closed or generation != self._play_generation or self.is_loading
                or self._user_paused or self.radio_playing is not None
                or self._xfade_active or self._session_pending):
            return
        try:
            state = self.player.get_state()
        except Exception:
            return
        if state == vlc.State.Playing:
            return
        if state in (vlc.State.Opening, vlc.State.Buffering):
            # Yavaş ağ: biraz daha bekle ama sonsuza dek değil
            if attempt < 8:
                QTimer.singleShot(1500, lambda: self._ensure_started(generation, attempt + 1))
            else:
                log.warning("Akış açma/tamponlama zaman aşımına uğradı (durum=%s).", state)
                self._handle_player_error()
            return
        if state == vlc.State.Error:
            return  # _update_ui_loop hata akışını yönetir
        if state == vlc.State.Ended:
            return  # _update_ui_loop şarkı sonunu yönetir
        # Stopped / NothingSpecial / Paused: kullanıcı duraklatmadı → başlat
        if attempt < 3:
            log.warning("Şarkı başlamadı (durum=%s), yeniden deneniyor (%d).", state, attempt + 1)
            try:
                self.player.play()
                # Retry sırasında ses seviyesini değiştirme; kullanıcı bu arada ayarlamış olabilir.
            except Exception as e:
                log.error("Yeniden başlatma başarısız: %s", e)
            QTimer.singleShot(1200, lambda: self._ensure_started(generation, attempt + 1))
        else:
            self.playStateChanged.emit(False)  # arayüz gerçeği göstersin

    def _handle_player_error(self):
        """VLC 'Error' durumuna düştü (ör. süresi dolmuş stream linki).
        Önce önbellekteki linki atıp bir kez yeniden çözmeyi dener, olmazsa
        mevcut hata/atlama akışına (playError → on_play_error) bırakır."""
        if self._reported_error_gen == self._play_generation:
            return
        self._reported_error_gen = self._play_generation
        pl, idx, song = self.playing_playlist, self.current_index, self._current_song_ref
        if pl is None or idx < 0:
            return
        if song is not None and song.get("stream_url") and self._error_retry_song is not song:
            self._error_retry_song = song
            song.pop("stream_url", None)
            song.pop("resolved_at", None)
            log.warning("Stream hata verdi, link yenilenip tekrar deneniyor.")
            self.play_song_at_index(pl, idx, auto=self._play_is_auto)
            return
        self.playError.emit(pl, idx)

    # --- Dinleme geçmişi oturumu ---
    def _begin_listen(self, song: dict, completed_previous: bool = False):
        self._end_listen(completed_previous)
        self._fallback_pos_ms = None
        self._listen = {"song": dict(song), "seconds": 0.0, "last": time.monotonic()}

    def _tick_listen(self, is_playing: bool):
        session = self._listen
        if session is None:
            return
        now = time.monotonic()
        delta = now - session["last"]
        session["last"] = now
        if is_playing and 0 <= delta < 2.0 * UI_TICK_MS / 1000 + 1:   # uyku/askı sıçramalarını sayma
            session["seconds"] += delta
            if self._fallback_pos_ms is not None:
                self._fallback_pos_ms += int(delta * 1000)

    def _end_listen(self, completed: bool = False):
        session, self._listen = self._listen, None
        self._fallback_pos_ms = None
        if session is None:
            return
        try:
            self.history.record(session["song"], session["seconds"], completed)
        except Exception as e:   # geçmiş yazımı çalmayı asla bozmamalı
            log.error("Dinleme geçmişi kaydedilemedi: %s", e)

    def resync_current_index(self):
        """Kütüphane yapısı değiştiğinde (silme/taşıma/yeniden adlandırma/undo)
        çalan şarkıyı yeniden konumlandırır. Şarkı tamamen kaldırıldıysa
        oynatmayı durdurur — bayat bir index'in YANLIŞ şarkıyı göstermesine/
        çalmasına engel olur (orijinaldeki inline düzeltmenin genel hali)."""
        if self.playing_playlist is None or self._current_song_ref is None or self.is_loading:
            return
        pl, idx = self.store.locate_song(
            self.playing_playlist, self.current_index, self._current_song_ref)
        if pl is None:
            self._abort_crossfade()
            self._end_listen()
            try:
                self.player.stop()
            except Exception:
                pass
            self.playing_playlist = None
            self.current_index = -1
            self._current_song_ref = None
            self.playStateChanged.emit(False)
            self.statusMessage.emit("Çalan şarkı kütüphaneden kaldırıldı.", "info")
            return
        self.playing_playlist = pl
        self.current_index = idx

    def on_play_error(self, playlist_name, index):
        self.is_loading = False
        if playlist_name != self.playing_playlist or index != self.current_index:
            return
        if not self._play_is_auto:
            # Kullanıcı bu şarkıyı kendisi seçti: sessizce sıradakilere atlamak yerine dur ve hatayı göster.
            self._consecutive_play_failures = 0
            self.statusMessage.emit(
                "Seçtiğin şarkı çalınamadı; otomatik olarak sıradakine geçilmedi. "
                "Tekrar dene ya da ⏭ ile sonrakine geç.", "error")
            self.playStateChanged.emit(False)
            return
        self._consecutive_play_failures += 1
        if self._consecutive_play_failures >= 4:
            self._consecutive_play_failures = 0
            self.statusMessage.emit(
                "Art arda birden fazla şarkı çalınamadı — otomatik geçiş durduruldu. "
                "İnternet bağlantını ve yt-dlp sürümünü kontrol et.", "error")
            self.playStateChanged.emit(False)
            return
        self.statusMessage.emit("Şarkı oynatılamadı, sıradakine geçiliyor...", "error")
        self.play_next()

    def toggle_play_pause(self):
        if self.is_loading:
            return
        if self.radio_playing is not None:
            # Radyo modunda toggle doğrudan player üzerinde çalışır
            if self.player.is_playing():
                self.player.pause()
                self.playStateChanged.emit(False)
            else:
                self.player.play()
                self.playStateChanged.emit(True)
            return
        if self._xfade_active:
            # Geçiş ortasında duraklatma: takası anında tamamla, sonra normal
            # mantık yeni (aktif) player'ı duraklatır.
            self._complete_crossfade_instant()
        if self._session_pending:
            # Oturum geri yüklendi ama henüz medya yok: kaldığı şarkıyı başlat.
            # Bayrak burada SİLİNMEZ: play_song_at_index "bu, geri yüklenen şarkı"
            # olduğunu bundan anlayıp kayıtlı saniyeyi korur; _start_playback siler.
            self.play_song_at_index(self.playing_playlist, self.current_index)
            return
        if self.playing_playlist is None:
            songs = self.store.playlists.get(self.store.active_playlist, [])
            if songs:
                self.play_song_at_index(self.store.active_playlist, 0)
            return
        if self.player.is_playing():
            self._user_paused = True
            self.player.pause()
            self.playStateChanged.emit(False)
        else:
            self._user_paused = False
            self.player.play()
            self.playStateChanged.emit(True)

    def pause(self):
        """Uyku zamanlayıcısı gibi akışları duraklatmak için tek yönlü pause."""
        if self._xfade_active:
            self._complete_crossfade_instant()
        if self.player.is_playing():
            self._user_paused = True
            self.player.pause()
            self.playStateChanged.emit(False)

    # --- Crossfade (şarkılar arası yumuşak geçiş) ---
    def _crossfade_fade_ms(self) -> int:
        try:
            seconds = float(self.settings.get("crossfade_seconds", 3))
        except Exception:
            seconds = 3.0
        return max(500, int(seconds * 1000))

    def _maybe_start_crossfade(self):
        """Tick döngüsünden çağrılır: mevcut şarkı sona yaklaştıysa sıradaki
        ikinci player'da başlatıp sesleri kesiştirir."""
        if (self._xfade_active or self.is_loading or self._session_pending
                or not self.settings.get("crossfade_enabled")
                or self.playing_playlist is None
                or self.radio_playing is not None
                or self.suppress_auto_advance
                or self.repeat_mode == "one"):
            return
        guard = self.crossfade_guard
        try:
            if guard is not None and guard():
                return
        except Exception as e:
            log.warning("Crossfade koruması okunamadı: %s", e)
            return
        try:
            if not self.player.is_playing():
                return
            total = self.player.get_length()
            pos = self.player.get_time()
        except Exception:
            return
        fade_ms = self._crossfade_fade_ms()
        if total <= 0 or fade_ms >= total or pos < total - fade_ms:
            return

        resolved_target = self._resolve_crossfade_target()
        if resolved_target is None:
            return
        target, queued_raw = resolved_target
        playlist_name, index = target
        songs = self.store.playlists.get(playlist_name, [])
        if not (0 <= index < len(songs)):
            return
        song = songs[index]

        self._xfade_generation += 1
        generation = self._xfade_generation
        self._xfade_active = True  # URL çözülene kadar tekrar tetiklenmesin
        self._xfade_queued_raw = queued_raw  # başarısızlıkta kuyruğa iade için
        threading.Thread(target=self._xfade_resolve_worker,
                         args=(generation, playlist_name, index, song),
                         daemon=True).start()

    def _resolve_crossfade_target(self) -> tuple[tuple[str, int], tuple | None] | None:
        """play_next ile aynı öncelik: önce manuel kuyruk, sonra liste sırası.
        Kuyruk öğesi burada düşer; dönen ikinci değer başarısızlıkta iade
        edilmek üzere saklanan ham öğedir."""
        queued = self.store.pop_next_from_queue()
        while queued is not None:
            pl_name, orig_idx, song = queued
            real_pl, real_idx = self.store.locate_song(pl_name, orig_idx, song)
            if real_pl is not None:
                return (real_pl, real_idx), queued
            queued = self.store.pop_next_from_queue()
        if self.playing_playlist is None:
            return None
        nxt = self.get_next_index()
        if nxt == -1:
            return None
        return (self.playing_playlist, nxt), None

    def _restore_xfade_queue_item(self):
        """Çözümlenemeyen/yarım kalan geçişin kuyruk öğesini kaybetme."""
        raw = getattr(self, "_xfade_queued_raw", None)
        self._xfade_queued_raw = None
        if raw is not None:
            self.store.manual_queue.insert(0, raw)
            self.store.queueChanged.emit()

    def _xfade_resolve_worker(self, generation: int, playlist_name: str, index: int, song: dict):
        try:
            url, is_offline = resolve_stream_url(song)
        except Exception as e:
            log.error("%s %s", "Crossfade stream çözülemedi:", e)
            # Yumuşak geçiş başarısız — eski davranış: doğal bitişte play_next
            if not self._closed:
                self._xfadeFailed.emit(generation)
            return
        if not self._closed:
            self._xfadeResolved.emit(generation, song, playlist_name, index, url, is_offline)

    def _on_xfade_failed(self, generation):
        """(GUI thread) Geçiş kuramadık: kuyruk öğesini iade edip normal akışa dön."""
        if self._closed or generation != self._xfade_generation:
            return
        self._xfade_active = False
        self._xfade_timer = None
        self._xfade_blend = 0.0
        self._restore_xfade_queue_item()

    def _begin_crossfade(self, generation, song, playlist_name: str, index: int, url: str, is_offline: bool):
        """(GUI thread) Yeni medyayı player_b'de başlatır, sesleri çizgilerle
        kesiştirir; rampa bitince rolleri takas eder."""
        if self._closed or generation != self._xfade_generation:
            return
        # Çözümleme sırasında kullanıcı başka bir şey başlattıysa vazgeç
        if (not self._xfade_active or self.radio_playing is not None
                or self.is_loading or self._session_pending):
            self._xfade_active = False
            self._restore_xfade_queue_item()
            return

        location = self._live_song_location(song)
        if location is None:
            self._abort_crossfade()
            return
        playlist_name, index = location
        self._current_url = url
        self._current_is_offline = is_offline

        old_media = self.player_b.get_media()
        media = self._prepare_media(url, song)
        self.player_b.set_media(media)
        if old_media is not None:
            try:
                old_media.release()
            except Exception:
                pass
        self._apply_active_equalizer()
        self.player_b.audio_set_volume(0)
        self.player_b.play()
        self._apply_saved_rate_to(self.player_b)
        self._xfade_queued_raw = None  # şarkı çalmaya başladı — iptal edilirse kuyruğa iade edilmesin

        # Şarkı muhasebesini ŞİMDİ yap — songStarted yeni şarkıyı işaret etsin
        self.playing_playlist = playlist_name
        self.current_index = index
        self._current_song_ref = song
        self._consecutive_play_failures = 0
        song["play_count"] = song.get("play_count", 0) + 1
        song["last_played"] = datetime.now().isoformat()
        self.store.save()
        self._begin_listen(song, completed_previous=True)
        self.songStarted.emit(playlist_name, index, song, is_offline)
        self.playStateChanged.emit(True)

        # Ses rampası
        fade_ms = self._crossfade_fade_ms()
        step_ms = 40
        steps = max(1, fade_ms // step_ms)
        timer = QTimer(self)
        timer.setInterval(step_ms)
        state = {"t": 0}

        def tick():
            state["t"] += 1
            frac = min(state["t"] / steps, 1.0)
            self._xfade_blend = frac
            try:
                # Eşit güç (equal-power) eğrisi: ses seviyesi ortada çökmez
                angle = frac * (math.pi / 2.0)
                vol_a = math.cos(angle)
                vol_b = math.sin(angle)
                live = self._master_volume()
                self.player.audio_set_volume(int(live * vol_a))
                self.player_b.audio_set_volume(int(live * vol_b))
            except Exception:
                pass
            if frac >= 1.0:
                timer.stop()
                self._finish_crossfade()

        self._xfade_timer = timer
        timer.timeout.connect(tick)
        timer.start()

    def _finish_crossfade(self):
        """Rampa bitti: eski player durur, player_b 'resmi' player olur."""
        new_player, old_player = self.player_b, self.player
        master = self._master_volume()
        try:
            old_player.stop()
        except Exception:
            pass
        try:
            new_player.audio_set_volume(master)
        except Exception:
            pass
        self.player = new_player
        self.player_b = old_player
        self._xfade_blend = 0.0
        self._xfade_active = False
        self._xfade_timer = None
        self._xfade_queued_raw = None  # öğe tüketildi — iade yok
        QTimer.singleShot(500, self.preload_next_song)

    def _complete_crossfade_instant(self):
        """Rampa SÜRÜYORSA anında tamamla. Hâlâ çözümleme aşamasındaysa (URL
        çözülüyor, player_b henüz hiç ses vermedi) geçişi İPTAL say: bu durumda
        takas ASLA yapılmaz — boş player_b'ye takas etmek müziği tamamen
        keserdi. Çözümleme aşamasında: bayraklar sıfırlanır, kuyruk öğesi
        iade edilir; eski şarkı self.player olarak çalmaya/duraklatmaya devam
        eder ve çağıranın normal mantığı doğru player üzerinde çalışır."""
        if not self._xfade_active:
            return
        if self._xfade_timer is None:
            self._xfade_active = False
            self._xfade_blend = 0.0
            self._restore_xfade_queue_item()
            return
        try:
            self._xfade_timer.stop()
        except Exception:
            pass
        self._finish_crossfade()

    def _xfade_is_ramping(self) -> bool:
        """Ses rampası gerçekten başladı mı? (çözümleme aşaması hariç)
        Pozisyon/oturum okumaları ve takas kararları bunu kullanır."""
        return self._xfade_active and self._xfade_timer is not None

    def _abort_crossfade(self):
        """Kullanıcı başka şarkı seçti/radyo açtı: geçişi tamamen iptal et.
        Kuyruktan düşen öğe hiç çalmadığı için kuyruğa iade edilir."""
        self._xfade_generation += 1
        if not self._xfade_active and self._xfade_timer is None:
            return
        if self._xfade_timer is not None:
            try:
                self._xfade_timer.stop()
            except Exception:
                pass
        try:
            self.player_b.stop()
        except Exception:
            pass
        try:
            self.player.audio_set_volume(self._master_volume())
        except Exception:
            pass
        self._xfade_timer = None
        self._xfade_blend = 0.0
        self._xfade_active = False
        self._restore_xfade_queue_item()

    def _apply_saved_rate_to(self, player):
        try:
            rate = float(self.settings.get("_rate", 1.0))
            if rate != 1.0:
                player.set_rate(rate)
        except Exception as e:
            log.error("%s %s", "Kayıtlı hız uygulanamadı:", e)

    # --- Oturum geri yükleme ---
    def save_session_state(self) -> dict | None:
        """Kapatılırken son durumu döndürür (çalan liste + şarkı + pozisyon).
        Rampa sürüyorsa pozisyon YENİ player'dan okunur; çözümleme aşamasında
        ise eski player'dan okunmaya devam eder (o hâlâ çalıyor)."""
        if self.playing_playlist is None or self.current_index < 0:
            return None
        src = self.player_b if self._xfade_is_ramping() else self.player
        position = 0
        try:
            if src.is_playing() or src.get_state() == vlc.State.Paused:
                position = max(src.get_time(), 0)
        except Exception:
            pass
        return {
            "playlist": self.playing_playlist,
            "index": self.current_index,
            "position_ms": position,
        }

    def restore_session(self, session: dict) -> bool:
        """Kayıtlı oturumu UI'a yükler (ses çalmaz; ▶ ile kaldığı yerden sürer)."""
        playlist = session.get("playlist")
        index = session.get("index", -1)
        songs = self.store.playlists.get(playlist)
        if not songs or not (0 <= index < len(songs)):
            return False
        song = songs[index]
        self.playing_playlist = playlist
        self.current_index = index
        self._current_song_ref = song
        self._session_pending = True
        self._resume_ms = int(session.get("position_ms") or 0)
        self.songStarted.emit(playlist, index, song, bool(offline_path_for(song)))
        self.playStateChanged.emit(False)
        total_ms = int((song.get("duration") or 0) * 1000)
        if total_ms > 0 and self._resume_ms > 0:
            self.positionChanged.emit(min(self._resume_ms, total_ms), total_ms)
        return True

    def set_rate(self, rate: float):
        """Çalma hızını ayarlar (0.5x–2x).

        DİKKAT: VLC'de medya yüklü değilken set_rate çağırmak bazı sürümlerde
        kilitlenir; bu yüzden hız yalnızca çalma/çalma-sonrası durumunda
        uygulanır, aksi halde saklanıp şarkı başlarken devreye alınır."""
        rate = float(rate)
        self.settings["_rate"] = rate
        try:
            if self.player.get_state() in (
                    vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering):
                self.player.set_rate(rate)
            if self._xfade_is_ramping() and self.player_b.get_state() in (
                    vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering):
                self.player_b.set_rate(rate)
        except Exception as e:
            log.error("%s %s", "Hız ayarlanamadı:", e)

    def _apply_saved_rate(self):
        """Yeni medya yüklendiğinde kayıtlı hızı uygular."""
        try:
            rate = float(self.settings.get("_rate", 1.0))
            if rate != 1.0:
                self.player.set_rate(rate)
        except Exception as e:
            log.error("%s %s", "Kayıtlı hız uygulanamadı:", e)

    def get_rate(self) -> float:
        if self.player.get_state() not in (
                vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering):
            return float(self.settings.get("_rate", 1.0))
        try:
            return float(self.player.rate())
        except Exception:
            return float(self.settings.get("_rate", 1.0))

    def get_next_index(self) -> int:
        if self.playing_playlist is None:
            return -1
        songs = self.store.playlists.get(self.playing_playlist, [])
        n = len(songs)
        if n == 0:
            return -1
        if self.shuffle_mode:
            if n == 1:
                return 0
            plan = self._shuffle_plan
            if plan is not None and plan[:3] == (self.playing_playlist, self.current_index, n):
                return plan[3]
            choice = random.choice([i for i in range(n) if i != self.current_index])
            self._shuffle_plan = (self.playing_playlist, self.current_index, n, choice)
            return choice
        nxt = self.current_index + 1
        if nxt >= n:
            return 0 if self.repeat_mode == "all" else -1
        return nxt

    def get_previous_index(self) -> int:
        if self.playing_playlist is None:
            return -1
        songs = self.store.playlists.get(self.playing_playlist, [])
        n = len(songs)
        if n == 0:
            return -1
        if self.shuffle_mode:
            if n == 1:
                return 0
            return random.choice([i for i in range(n) if i != self.current_index])
        prev = self.current_index - 1
        if prev < 0:
            return n - 1 if self.repeat_mode == "all" else -1
        return prev

    def play_next(self):
        if self._xfade_active:
            if self._xfade_is_ramping():
                # Rampa sürüyor: fade'in başlattığı "sıradaki" zaten çalıyor —
                # takası tamamla, bir şarkı daha atlamayı önle.
                self._complete_crossfade_instant()
                return
            # Çözümleme aşamasındaydı: iptal edildi (kuyruk iade edildi) —
            # aşağıdaki normal akış sıradakine geçer.
            self._complete_crossfade_instant()
        if self.radio_playing is not None:
            self._radio_next()
            return

        if self.next_provider is not None:
            room_next = self.next_provider()
            if room_next is not None:
                self.play_song_at_index(*room_next, auto=True)
                return

        # Manuel kuyrukta bekleyen şarkı varsa, önce onu çal (Spotify "Sırada" mantığı)
        queued = self.store.pop_next_from_queue()
        if queued is not None:
            pl_name, orig_idx, song = queued
            real_pl, real_idx = self.store.locate_song(pl_name, orig_idx, song)
            if real_pl is None:
                self.statusMessage.emit(
                    f"⚠️ '{song.get('title', '?')}' artık kütüphanede yok, atlanıyor.", "warning")
                self.play_next()  # kuyruktakine devam
                return
            self.play_song_at_index(real_pl, real_idx, auto=True)
            return

        if self.playing_playlist is None:
            return
        nxt = self.get_next_index()
        if nxt != -1:
            self.play_song_at_index(self.playing_playlist, nxt, auto=True)
        else:
            if callable(self.autoplay_handler) and self.settings.get("autoplay_enabled", True):
                try:
                    if self.autoplay_handler():
                        try:
                            self.player.stop()
                        except Exception:
                            pass
                        return
                except Exception as e:
                    log.warning("%s %s", "Autoplay tetikleme hatası:", e)
            self._end_listen(completed=True)
            self.player.stop()
            self.playStateChanged.emit(False)

    def play_previous(self):
        if self._xfade_active:
            # Yeni şarkı zaten "aktif": takası tamamla, ondan öncekine git
            self._complete_crossfade_instant()
        if self.radio_playing is not None:
            self._radio_previous()
            return
        if self.playing_playlist is None:
            return
        prev = self.get_previous_index()
        if prev != -1:
            self.play_song_at_index(self.playing_playlist, prev)

    def handle_song_end(self):
        if self.playing_playlist is None:
            return
        self._end_listen(completed=True)
        self.songEnded.emit()
        if self.suppress_auto_advance:
            # Oda sahibinin sıradaki şarkı mesajı beklenir. stop() olmazsa 'Ended'
            # durumu her tikte yeniden işlenirdi.
            try:
                self.player.stop()
            except Exception:
                pass
            self.playStateChanged.emit(False)
            return
        if self.repeat_mode == "one":
            self.play_song_at_index(self.playing_playlist, self.current_index, auto=True)
        else:
            self.play_next()

    def toggle_shuffle(self) -> bool:
        self.shuffle_mode = not self.shuffle_mode
        self.shuffleChanged.emit(self.shuffle_mode)
        return self.shuffle_mode

    def enable_shuffle(self) -> bool:
        """Karışık çalı AÇIK değilse açar (Ana Sayfa / kütüphane 'Karışık Çal' butonu)."""
        if not self.shuffle_mode:
            self.shuffle_mode = True
            self.shuffleChanged.emit(True)
        return self.shuffle_mode

    def cycle_repeat(self) -> str:
        order = {"off": "all", "all": "one", "one": "off"}
        self.repeat_mode = order[self.repeat_mode]
        self.repeatChanged.emit(self.repeat_mode)
        return self.repeat_mode

    # --- Radyo (canlı internet yayını) ---
    def play_radio_station(self, station: dict) -> bool:
        """Gerçek bir canlı radyo yayınını (icecast/shoutcast stream) çalar."""
        if self._closed:
            return False
        url = station.get("url")
        if not url:
            self.statusMessage.emit("Bu istasyonun akış linki yok.", "warning")
            return False

        self._end_listen()
        self._user_paused = False
        # Invalidate any playlist resolution still running.
        self._play_generation += 1
        # Devam eden crossfade'i ve playlist tabanlı çalmayı durdur — radyo ayrı bir mod
        self._abort_crossfade()
        self.playing_playlist = None
        self.current_index = -1
        self._current_song_ref = None
        self._current_url = None
        self._current_is_offline = False
        self._fallback_pos_ms = None
        self.is_loading = False
        self.next_song_preloaded = None

        try:
            old_media = self.player.get_media()
            media = self._prepare_media(url)
            try:  # şarkıdan radyoya geçişte de aynı set_media/play yarışını önle
                if self.player.get_state() not in (vlc.State.NothingSpecial, vlc.State.Stopped):
                    self.player.stop()
            except Exception:
                pass
            self.player.set_media(media)
            if old_media is not None:
                try:
                    old_media.release()
                except Exception:
                    pass
            self.player.play()
            self.player.audio_set_volume(self._master_volume())
            self._apply_saved_rate()
            self._apply_active_equalizer()
        except Exception as e:
            log.error("%s %s", "Radyo çalınamadı:", e)
            self.statusMessage.emit("⚠️ İstasyon çalınamadı, başka bir tane dene.", "error")
            return False

        self.radio_playing = station
        self.radioStarted.emit(station)
        self.playStateChanged.emit(True)
        self.statusMessage.emit(f"📻 '{station['name']}' çalıyor.", "success")
        return True

    def stop_radio(self):
        if self.radio_playing is None:
            return
        self._end_listen()
        self.player.stop()
        self.radio_playing = None
        self._current_song_ref = None
        self._current_url = None
        self._current_is_offline = False
        self._fallback_pos_ms = None
        self.radioStopped.emit()
        self.playStateChanged.emit(False)

    def _radio_next(self):
        view = getattr(self, "_radio_station_provider", None)
        if view is None:
            return
        stations = view()
        if not stations or self.radio_playing is None:
            return
        uuids = [s.get('stationuuid') for s in stations]
        try:
            idx = uuids.index(self.radio_playing.get('stationuuid'))
        except ValueError:
            idx = -1
        nxt = (idx + 1) % len(stations)
        self.play_radio_station(stations[nxt])

    def _radio_previous(self):
        view = getattr(self, "_radio_station_provider", None)
        if view is None:
            return
        stations = view()
        if not stations or self.radio_playing is None:
            return
        uuids = [s.get('stationuuid') for s in stations]
        try:
            idx = uuids.index(self.radio_playing.get('stationuuid'))
        except ValueError:
            idx = 0
        prev = (idx - 1) % len(stations)
        self.play_radio_station(stations[prev])

    def _master_volume(self, base: int | None = None) -> int:
        """Kullanıcının ses ayarı × geçici çarpan (uyku zamanlayıcısı fade'i).
        Çarpan kalıcı `_volume` ayarını ASLA değiştirmez."""
        if base is None:
            base = int(self.settings.get("_volume", 80))
        return max(0, min(100, int(base * self._volume_scale)))

    def set_volume_scale(self, scale: float):
        """0..1 geçici ses çarpanı; aktif player(lar)a hemen uygulanır."""
        self._volume_scale = max(0.0, min(1.0, float(scale)))
        self._apply_volume()

    def _apply_volume(self):
        master = self._master_volume()
        try:
            if self._xfade_is_ramping():
                angle = self._xfade_blend * (math.pi / 2.0)
                self.player.audio_set_volume(int(master * math.cos(angle)))
                self.player_b.audio_set_volume(int(master * math.sin(angle)))
            else:
                self.player.audio_set_volume(master)
        except Exception:
            pass

    def change_volume(self, value: int):
        value = int(value)
        self.settings["_volume"] = value
        self._apply_volume()
        self.volumeChanged.emit(value)

    def apply_normalization(self, enabled: bool):
        """Ses normalizasyonu (eşit ses / normvol + ReplayGain) durumunu günceller."""
        self.settings["audio_normalization"] = bool(enabled)

    def apply_crossfade_settings(self, enabled: bool, seconds: int = 3):
        """Crossfade geçiş durumunu ve süresini günceller."""
        self.settings["crossfade_enabled"] = bool(enabled)
        self.settings["crossfade_seconds"] = max(1, min(12, int(seconds)))

    @property
    def vocal_remover_enabled(self) -> bool:
        return bool(self.settings.get("vocal_remover_enabled", False))

    def toggle_vocal_remover(self) -> bool:
        """Vokal ayırma / enstrümantal modunu açar veya kapatır."""
        new_state = not self.vocal_remover_enabled
        self.set_vocal_remover(new_state)
        return new_state

    def set_vocal_remover(self, enabled: bool):
        """Vokal ayırma / enstrümantal modunu açar veya kapatır; ekolayzeri anında günceller."""
        enabled = bool(enabled)
        already_active = getattr(self, "_vocal_remover_active", None)
        self.settings["vocal_remover_enabled"] = enabled
        self._vocal_remover_active = enabled
        # Canlı ekolayzeri anında uygula (kesinti/baştan yükleme olmadan gerçek zamanlı)
        self._apply_active_equalizer()
        if already_active == enabled:
            return
        self.vocalRemoverChanged.emit(enabled)
        msg = "🎙️ Vokal ayırma (Enstrümantal) açıldı" if enabled else "🎙️ Vokal ayırma kapatıldı (Orijinal ses)"
        self.statusMessage.emit(msg, "info")

    def seek(self, ms: int):
        if self._xfade_active:
            self._complete_crossfade_instant()
        raw_length = self.player.get_length()
        length = raw_length
        if (not isinstance(length, int) or length <= 0) and self._current_song_ref is not None:
            length = int((self._current_song_ref.get("duration") or 0) * 1000)
        if isinstance(length, int) and length > 0:
            clamped = max(0, min(int(ms), length))
            if isinstance(raw_length, int) and raw_length <= 0:
                try:
                    self.player.set_position(clamped / float(length))
                except Exception:
                    self.player.set_time(clamped)
            else:
                self.player.set_time(clamped)
            self._fallback_pos_ms = clamped
            self.seeked.emit(clamped)

    def shutdown(self):
        """Idempotently stop timers and release both crossfade players."""
        if self._closed:
            return
        self._end_listen()
        self._closed = True
        self._play_generation += 1
        self._tick_timer.stop()
        self._preload_timer.stop()
        self._abort_crossfade()
        for player in (self.player, self.player_b):
            try:
                player.stop()
            except Exception as e:
                log.warning("VLC player durdurulamadı: %s", e)
            try:
                player.release()
            except Exception as e:
                log.warning("VLC player serbest bırakılamadı: %s", e)
        self.vlc_instance.release()

    def _ended_without_opening(self) -> bool:
        """VLC 3.x bazen HTTP 403 / TLS hatasında State.Error yerine doğrudan State.Ended
        (length=0, time=0, dinlenen süre < 1 sn) döndürür. Bunu doğal şarkı sonu
        sanıp sessizce sıradakine atlamak yerine akış hatası olarak işle."""
        if self.radio_playing is not None:
            return False
        session = self._listen
        if session is None or session.get("seconds", 0.0) >= 1.0:
            return False
        try:
            length = self.player.get_length()
            pos = self.player.get_time()
        except Exception:
            return False
        return isinstance(length, int) and isinstance(pos, int) and length <= 0 and pos <= 0

    def _update_ui_loop(self):
        if self._closed:
            return
        # Hiçbir şey çalmıyorsa / yüklenmiyorsa boşta libVLC ctypes çağrısı yapma
        if (self.playing_playlist is None and self.radio_playing is None
                and not self._xfade_active and self._listen is None):
            return
        try:
            if self.player:
                # Rampa sürerken ilerleme YENİ player'dan okunur. Çözümleme
                # aşamasında (rampa yok) eski player okunmaya devam eder —
                # aksi halde ağ gecikmesi boyunca ilerleme çubuğu donardı.
                src = self.player_b if self._xfade_is_ramping() else self.player
                playing = bool(src.is_playing())
                self._tick_listen(playing)
                if playing and not self.is_seeking:
                    current = src.get_time()
                    total = src.get_length()
                    if (not isinstance(total, int) or total <= 0) and self._current_song_ref is not None:
                        total = int((self._current_song_ref.get("duration") or 0) * 1000)
                    if isinstance(current, int) and current <= 0:
                        try:
                            pos_frac = src.get_position()
                        except Exception:
                            pos_frac = 0.0
                        if isinstance(pos_frac, float) and 0.0 < pos_frac <= 1.0 and isinstance(total, int) and total > 0:
                            current = int(pos_frac * total)
                        elif self._fallback_pos_ms is not None:
                            current = self._fallback_pos_ms
                        elif self._listen is not None and self._listen.get("seconds", 0.0) > 0:
                            current = int(self._listen["seconds"] * 1000)
                    if total > 0:
                        if isinstance(current, int) and isinstance(total, int):
                            current = max(0, min(current, total))
                        self.positionChanged.emit(current, total)

                if self._xfade_active:
                    pass  # geçiş makinesi ilerlemeyi yönetiyor; Ended'i yok say
                else:
                    state = self.player.get_state()
                    if state == vlc.State.Ended and not self.is_loading and self.playing_playlist is not None:
                        if self._ended_without_opening():
                            self._handle_player_error()
                        else:
                            self.handle_song_end()
                    elif state == vlc.State.Playing:
                        self._error_retry_song = None  # sağlıklı çalıyor: yeniden deneme hakkı yenilenir
                    elif (state == vlc.State.Error and not self.is_loading
                          and self.playing_playlist is not None and self.radio_playing is None):
                        self._handle_player_error()

            self._maybe_start_crossfade()
        except Exception as e:
            log.error("%s %s", "UI güncelleme hatası:", e)

# Sonraki Fazlar — Durum

Faz 1 (iskelet + playback çekirdeği + playlist verisi + kütüphane görünümü)
ve Faz 2'nin tüm kalemleri **tamamlandı**. Aşağıdaki tablo orijinal tkinter
sürümündeki karşılıklarıyla her özelliğin durumunu gösterir.

| Özellik | Orijinal kaynak | Durum |
|---|---|---|
| Mini oynatıcı | `mustiefly_settings.py` | ✅ `views/mini_player.py` |
| Discord Rich Presence | `mustiefly_discord_tray.py` | ✅ `services/discord_rpc.py` |
| Sistem tepsisi | `mustiefly_discord_tray.py` | ✅ `app_window.py` (`_setup_system_tray`) |
| Manuel kuyruk ("Sıradaki") | `add_to_queue`, `_render_queue_*` | ✅ `PlaylistStore.manual_queue` + `LibraryView` kuyruk modu; otomatik geçişte kuyruk önce tüketilir, bayat index'ler `_locate_song` ile çözülür |
| Sürükle-bırak kuyruk sıralama | `_start_queue_drag` vb. | ✅ `_QueueList.dropEvent` → model sırası yeniden düzenlenir (tkinter'daki elle sürükleme takibine gerek kalmadan) |
| Geri al (undo) | `_push_undo`, `_perform_undo` | ✅ `PlaylistStore._undo_stack` (son 10 işlem) + `widgets/snackbar.py`; gecikmeli dosya silme (8 sn) ve iptali de dahil |
| Tekrarlanan şarkı bulucu | `find_duplicate_songs` | ✅ `PlaylistStore.find_duplicate_groups / clean_duplicates` + `views/duplicate_finder_dialog.py` |
| Toplu şarkı ekleme | `open_bulk_add_dialog` | ✅ `services/bulk_search.py` (paralel arama) + `views/bulk_add_dialog.py` |
| Spotify içe aktarma | OAuth akışı + playlist çekme | ✅ `helpers/spotify_import.py` + `views/import_dialogs.py` (Authorization Code akışı, refresh_token yenileme) |
| M3U içe/dışa aktarma | `export/import_playlist_m3u` | ✅ `helpers/spotify_import.py` (parse/export) + `views/import_dialogs.py` |
| Ana Sayfa panosu | `_render_home_view` | ✅ `views/home_view.py` |
| İstatistikler | `_render_stats_view` | ✅ Ana Sayfa kartlarına gömüldü (aynı hesaplama) |
| Radyo | `_render_radio_view` + radio_* | ✅ `helpers/radio.py` (Radio Browser API) + `views/radio_view.py`; çalma `PlaybackEngine.play_radio_station` üzerinden aynı VLC player'ı paylaşır |
| Keşfet | `_render_explore_view` + `fetch_explore_tracks` | ✅ `helpers/discovery.py` (`DiscoveryService`) + `views/explore_view.py` (ytmusicapi → trend → arama zinciri aynen korundu) |
| Equalizer penceresi | `_setup_equalizer`, `toggle_equalizer_window` | ✅ `PlaybackEngine._setup_equalizer` + `views/equalizer_window.py` |
| Sözler paneli | `_refresh_lyrics_panel`, `_fetch_lyrics_worker` | ✅ `helpers/lyrics.py` (lrclib.net) + `views/lyrics_window.py` |
| Thumbnail indirme | `get_row_thumbnail_photo` | ✅ `services/thumbnails.py` (havuzlu indirme, PIL önbellek, sinyalle GUI güncellemesi); satır bazında hedefli güncelleme korunur |
| Playlist kapakları / kolaj | sidebar_thumbnails | ✅ `views/sidebar.py`: özel kapak seçimi/kaldırma + son 4 şarkıdan 2x2 kolaj |
| Dönen plak animasyonu | `_rotate_vinyl_tick` | ✅ `widgets/vinyl_cover.py` (paintEvent + QTimer, 130ms/10° orijinal denge) |
| Waveform animasyonu | `_build_waveform_strip`, `_animate_waveform` | ✅ `widgets/waveform_strip.py` (dinlenme konumunda zamanlayıcı durur — orijinal CPU optimizasyonuyla aynı) |
| Global medya tuşları | `_setup_global_media_keys` | ✅ `services/media_keys.py` (`keyboard` paketi opsiyonel, ayarla kontrol edilir) |
| Windows medya denetimleri (SMTC) | — | ✅ `services/smtc.py` (medya tuşları + ses açılır penceresinde şarkı/kapak; `winsdk` veya `winrt-*` paketleri opsiyonel) |
| İndirme yöneticisi | — | ✅ `services/download_manager.py` + `views/downloads_view.py` (sıra/ilerleme/iptal/tekrar; sidebar'da ⬇ İndirmeler) |
| Genel kütüphane arama | — | ✅ `views/library_search_dialog.py` — Mustiefly menüsünden / Ctrl+K |
| Oturum geri yükleme | — | ✅ Kapanışta `last_session` ayara yazılır; açılışta liste+şarkı yüklenir, ▶ ile kaldığı dakikadan sürer (`restore_session` ayarı) |
| Önbellek yönetimi | — | ✅ Ayarlar'da çevrimdışı müzik/thumbnail/kapak/yedek boyutları + temizleme; thumbnail disk önbelleği `services/thumbnails.py` |
| Sürükle → listeye bırak | — | ✅ `SongRow` QDrag + `_PlaylistList.dropEvent`; şarkı hedef listeye KOPLANIR (kaynak kalır) |
| Yerel MP3 desteği | — | ✅ `helpers/local_files.py` (+ Ekle menüsü/Araçlar); `local://` sentetik kimlik, VLC ile süre okuma |
| Crossfade | — | ✅ `services/playback.py` çift player kesişen ses rampası (`crossfade_enabled`, `crossfade_seconds`) |
| Tam yedekle/geri yükle | — | ✅ `helpers/backup.py` v2: kütüphane + kapaklar + taşınabilir AYARLAR tek JSON; Araçlar menüsünden |

## Sonraki olası faz (Faz 4 fikirleri)

- Last.fm scrobbling
- Profil fotoğrafı yükleme/gösterme (orijinal `set_avatar_photo`)
- ✅ Şarkı satırlarında "çevrimdışı mevcut" rozeti (0.4.1; dosya varlığı kontrol edilir)

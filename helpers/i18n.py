"""Çoklu dil desteği (Türkçe / English).

Uygulama metinleri kaynak kodda Türkçe yazılmıştır. `tr(metin)` aktif dil `"tr"`
iken metni olduğu gibi döndürür (mevcut davranış ve Türkçe testler birebir korunur);
aktif dil `"en"` olduğunda sözlük + kalıp (regex) eşleşmesiyle İngilizce karşılığını
verir.

Ayrıca `apply_language(root)` / `install_auto_translator(app)` Qt widget ağacındaki
etiket, düğme, menü, ipucu (tooltip), yer tutucu (placeholder) ve pencere başlıklarını
canlı olarak çevirir ve ilk Türkçe metni saklar; böylece Ayarlar'dan dil değiştirildiğinde
uygulamayı yeniden başlatmadan tüm arayüz anında iki yönlü (TR ↔ EN) güncellenir.
"""
from __future__ import annotations

import re

SUPPORTED_LANGUAGES: dict[str, str] = {
    "tr": "🇹🇷 Türkçe",
    "en": "🇬🇧 English",
}
DEFAULT_LANGUAGE = "tr"

_CURRENT_LANG = DEFAULT_LANGUAGE
_FILTER = None


def current_language() -> str:
    return _CURRENT_LANG


def set_language(lang: str) -> str:
    global _CURRENT_LANG
    _CURRENT_LANG = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    return _CURRENT_LANG


# ----------------------------------------------------------------------------
# Birebir sözlük (TR -> EN)
# ----------------------------------------------------------------------------
_EXACT_EN: dict[str, str] = {
    # --- Menü & uygulama ---
    "▶ Oynat / Duraklat": "▶ Play / Pause",
    "⏭ Sonraki Şarkı": "⏭ Next Track",
    "Göster": "Show",
    "Çıkış": "Quit",
    "🎵 Mini Oynatıcıyı Aç": "🎵 Open Mini Player",
    "🔎 Kütüphanede Ara…": "🔎 Search Library…",
    "⚙ Ayarlar": "⚙ Settings",
    "⚙  Ayarlar": "⚙  Settings",
    "Ayarlar": "Settings",
    "Araçlar": "Tools",
    "Ses": "Audio",
    "Yardım": "Help",
    "👥 Birlikte Dinle…": "👥 Listen Together…",
    "👥 Birlikte Dinle (odadasın)…": "👥 Listen Together (in room)…",
    "🔄 Güncellemeleri Denetle…": "🔄 Check for Updates…",
    "📁 Veri Klasörünü Aç": "📁 Open Data Folder",
    "📁 Kayıt Klasörünü Aç": "📁 Open Log Folder",
    "🩺 Sorun Bildir / Tanılama Raporu…": "🩺 Report Issue / Diagnostics…",
    "🩺 Sorun Bildir / Tanılama": "🩺 Report Issue / Diagnostics",
    "🩺 Sorun Bildir": "🩺 Report Issue",
    "📥 Toplu Şarkı Ekle…": "📥 Bulk Add Songs…",
    "🎧 Spotify Playlist İçe Aktar…": "🎧 Import Spotify Playlist…",
    "▶ YouTube Playlist İçe Aktar…": "▶ Import YouTube Playlist…",
    "📂 M3U İçe Aktar…": "📂 Import M3U…",
    "📤 Aktif Listeyi M3U Olarak Dışa Aktar…": "📤 Export Active Playlist as M3U…",
    "💽 Bilgisayardan Ses Dosyası Ekle…": "💽 Add Local Audio Files…",
    "💾 Tüm Kütüphaneyi Yedekle…": "💾 Backup Entire Library…",
    "📂 Yedekten Geri Yükle…": "📂 Restore from Backup…",
    "🧹 Yinelenen Şarkı Bulucu…": "🧹 Duplicate Song Finder…",
    "↩ Geri Al": "↩ Undo",
    "🎚 Ekolayzer…": "🎚 Equalizer…",
    "🎤 Sözler Paneli…": "🎤 Lyrics Panel…",
    "Ekolayzer": "Equalizer",
    "Sözler Paneli": "Lyrics Panel",
    "Mini Oynatıcı": "Mini Player",
    "📱 Audifly Connect (Telefon Kumandası)…": "📱 Audifly Connect (Phone Remote)…",
    "✨ Kütüphane Parlatıcı (Başlık & Etiket Temizle)…": "✨ Library Polisher (Clean Titles & Tags)…",
    "🖼️ Şarkı Sözü Kartı Oluştur (PNG)…": "🖼️ Create Lyric Card (PNG)…",
    "🎧 Ses Efekt Modları": "🎧 Sound Effect Modes",
    "⚡ Hesapsız Hızlı Başla": "⚡ Quick Start (No Account)",
    "🔄 Ayarları Varsayılana Sıfırla": "🔄 Reset Settings to Defaults",
    "Discord'da Çalan Şarkıyı Göster": "Show Now Playing on Discord",
    "📂 Klasör Seç…": "📂 Choose Folder…",
    "↩ Varsayılan": "↩ Default",
    "🖼️ Söz Kartı": "🖼️ Lyric Card",
    "🔍 Şarkı Ara": "🔍 Search Songs",
    "🎧 Spotify'dan Aktar": "🎧 Import from Spotify",
    "🧭 Keşfet'e Göz At": "🧭 Explore Music",

    # --- Sol menü (Sidebar) ---
    "⌂  Ana Sayfa": "⌂  Home",
    "◎  Keşfet": "◎  Explore",
    "▤  Kütüphane": "▤  Library",
    "♡  Beğenilenler": "♡  Liked Songs",
    "☰  Sırada": "☰  Queue",
    "↓  İndirmeler": "↓  Downloads",
    "★  En Çok Dinlenen": "★  Most Played",
    "◷  Son Çalınanlar": "◷  Recently Played",
    "✦  Yeni Eklenenler": "✦  Recently Added",
    "✨  Senin İçin Mix'ler": "✨  Mixes for You",
    "✨ Senin İçin Mix'ler": "✨ Mixes for You",
    "♪  Favori Sanatçılar": "♪  Favorite Artists",
    "◌  Unutulanlar": "◌  Forgotten Gems",
    "⚙  Kural Listeleri": "⚙  Smart Lists",
    "◉  Radyo": "◉  Radio",
    "▦  İstatistikler": "▦  Statistics",
    "🎁  Wrapped": "🎁  Wrapped",
    "LİSTELER": "PLAYLISTS",
    "+ Yeni Liste Oluştur": "+ Create New Playlist",
    "+ Yeni Liste": "+ New Playlist",
    "✏ Yeniden adlandır": "✏ Rename",
    "🖼 Kapak Değiştir…": "🖼 Change Cover…",
    "❌ Kapağı Kaldır": "❌ Remove Cover",
    "📤 M3U olarak dışa aktar": "📤 Export as M3U",
    "🗑 Sil": "🗑 Delete",

    # --- Üst çubuk (TopBar) ---
    "🔍  Ara…": "🔍  Search…",
    " Ekle": " Add",
    "Bildirimler": "Notifications",
    '"Şu An Çalıyor" panelini göster': 'Show "Now Playing" panel',
    "🎵  Şarkı Ara / Ekle": "🎵  Search / Add Song",
    "📥  Toplu Şarkı Ekle…": "📥  Bulk Add Songs…",
    "💽  Bilgisayardan Ses Dosyası Ekle…": "💽  Add Local Audio Files…",
    "▶  YouTube Playlist İçe Aktar…": "▶  Import YouTube Playlist…",
    "🎧  Spotify Playlist İçe Aktar…": "🎧  Import Spotify Playlist…",
    "📂  M3U İçe Aktar…": "📂  Import M3U…",

    # --- Alt oynatma çubuğu (PlayerBar) & Şu An Çalıyor ---
    "Çalan şarkının listedeki yerine git": "Jump to currently playing song",
    "Henüz şarkı seçilmedi": "No track selected yet",
    "Şarkı çalınmıyor": "Nothing playing",
    "Normal pencereye dön": "Return to main window",
    "Beğen": "Like",
    "♡ Beğen": "♡ Like",
    "♥ Beğenildi": "♥ Liked",
    "Karışık çal": "Shuffle",
    "Önceki": "Previous",
    "Oynat / Duraklat": "Play / Pause",
    "Sonraki": "Next",
    "Tekrarla": "Repeat",
    "Sıradaki": "Up Next",
    "Sözler paneli": "Lyrics panel",
    "Ses seviyesi": "Volume",
    "Uyku zamanlayıcısı ve çalma hızı": "Sleep timer & playback speed",
    "Sesi kademeli azalt": "Fade out audio gradually",
    "CANLI": "LIVE",
    "Özel süre…": "Custom duration…",
    "Zamanlayıcıyı iptal et": "Cancel timer",
    "ŞU AN ÇALIYOR": "NOW PLAYING",
    "Paneli kapat (üst çubuktan geri açılır)": "Close panel (reopen from top bar)",
    "🎤 Sözler": "🎤 Lyrics",
    "Sözler penceresini açar (Ayarlar > Sözler)": "Opens lyrics window",

    # --- Ana Sayfa / Keşfet / Kütüphane / Mix / Radyo / İstatistik ---
    "Müziğin ritmiyle günü güzelleştir.": "Brighten your day with the rhythm of music.",
    "▶ Karışık Çal": "▶ Shuffle Play",
    "🔀 Karışık Çal": "🔀 Shuffle Play",
    "Hızlı Erişim": "Quick Access",
    "Son Çalınanlar": "Recently Played",
    "Henüz hiç şarkı çalmadın. Bir şarkı çaldıkça burada birikmeye başlayacak.":
        "You haven't played any tracks yet. They will appear here as you listen.",
    "Kütüphaneye ekle": "Add to library",
    "BUGÜNÜN KEŞFİ": "DISCOVERY OF THE DAY",
    "Yükleniyor…": "Loading…",
    "Keşfet verileri hazırlanıyor…": "Preparing Explore feed…",
    "▶ Şimdi Dinle": "▶ Listen Now",
    "Keşfet bölümlerinden rastgele seçildi.": "Picked randomly from Explore sections.",
    "🧭 Keşfet": "🧭 Explore",
    "Hazırlanıyor…": "Preparing…",
    "🔄 Yenile": "🔄 Refresh",
    "🧭 Keşfet güncelleniyor…": "🧭 Updating Explore…",
    "Şu anda öne çıkan bir içerik yok": "No featured content right now",
    'İnternet bağlantını kontrol et ya da "Yenile"ye bas.':
        'Check your internet connection or press "Refresh".',
    "İlk kez yükleniyor…": "Loading for the first time…",
    "Keşfet verileri şu anda güncellenemiyor. İnternet bağlantını kontrol et.":
        "Could not update Explore right now. Check your internet connection.",
    "Tüm Çalma Listeleri": "All Playlists",
    "Sürükleyerek sırayı değiştir": "Drag to reorder",
    "Çalma Listesi": "Playlist",
    "Bu listede ara…": "Search in this playlist…",
    "Sırala: Varsayılan": "Sort: Default",
    "Sırala: İsim (A-Z)": "Sort: Title (A-Z)",
    "Sırala: Sanatçı (A-Z)": "Sort: Artist (A-Z)",
    "Sırala: Süre (uzun→kısa)": "Sort: Duration (long→short)",
    "Sırala: Eklenme Tarihi (yeni→eski)": "Sort: Date Added (new→old)",
    "＋ Şarkı Ekle": "＋ Add Song",
    "🗑 Kuyruğu Temizle": "🗑 Clear Queue",
    "🗑 Seçilenleri Sil": "🗑 Delete Selected",
    "🖼 Kapağı Değiştir": "🖼 Change Cover",
    "Listeyi yeniden adlandır": "Rename playlist",
    "▶  Oynat": "▶  Play",
    "▶ Çal": "▶ Play",
    "Çal": "Play",
    "Kapağı değiştir": "Change cover",
    "Listeyi boşalt / sil": "Empty / delete playlist",
    "Tümünü çevrimdışı indir": "Download all for offline",
    "# SIRALA": "# SORT",
    "Sıralama modunu değiştirir": "Changes sort mode",
    "BAŞLIK": "TITLE",
    "Başlığa göre sırala (A-Z)": "Sort by title (A-Z)",
    "SANATÇI": "ARTIST",
    "Sanatçıya göre sırala (A-Z)": "Sort by artist (A-Z)",
    "🧹  Listeyi Boşalt (geri alınabilir)": "🧹  Empty Playlist (undoable)",
    "🗑  Listeyi Sil": "🗑  Delete Playlist",
    'Kuyruk boş. Bir şarkının ⋮ menüsünden "Kuyruğa Ekle" diyebilirsin.':
        'Queue is empty. Use a song\'s ⋮ menu to choose "Add to Queue".',
    "Çevrimdışı kullanılabilir": "Available offline",
    "⏭ Sırada Çal": "⏭ Play Next",
    "➕ Kuyruğa Ekle": "➕ Add to Queue",
    "📂 Başka Listeye Taşı…": "📂 Move to Playlist…",
    "🗑 Listeden kaldır": "🗑 Remove from playlist",
    "👥 Oda Kuyruğuna Ekle": "👥 Add to Room Queue",
    "💾 Çevrimdışı indir": "💾 Download for offline",
    "🔗 YouTube Linkini Kopyala": "🔗 Copy YouTube Link",
    "Kütüphanendeki şarkılardan, dinleme geçmişine göre cihazında hesaplanır; hiçbir veri dışarı gönderilmez.":
        "Computed on your device from your library and listening history; no data leaves your computer.",
    "Listeyi Aç": "Open Playlist",
    "📻 Radyo": "📻 Radio",
    "Gerçek, canlı yayın yapan internet radyo kanalları": "Live internet radio stations",
    "İstasyon adı ara (ör. Kral FM)…": "Search station name (e.g. BBC, Jazz)…",
    "🔍 Ara": "🔍 Search",
    "Henüz istasyon listelenmedi — ara ya da 🇹🇷/🌍 filtrelerinden birine bas.":
        "No stations listed yet — search or pick one of the 🇹🇷/🌍 filters.",
    "📡 İstasyonlar getiriliyor…": "📡 Fetching stations…",
    "📡 İstasyon bulunamadı (internet bağlantını veya farklı bir arama terimini kontrol et).":
        "📡 No stations found (check your connection or try another search term).",
    "Henüz favori istasyonun yok. Bir istasyonun ☆ ikonuna tıkla.":
        "No favorite stations yet. Click a station's ☆ icon.",
    "📊 İstatistikler": "📊 Statistics",
    "🎤 En Çok Dinlenen Sanatçılar": "🎤 Top Artists",
    "🕘 Son Dinlenenler": "🕘 Recently Listened",
    "🔥 En Çok Dinlenenler (Top 10)": "🔥 Most Played (Top 10)",
    "📀 Liste Dağılımı": "📀 Playlist Breakdown",
    "Henüz hiç şarkı çalmadın. Çaldıkça istatistikler burada birikir.":
        "You haven't played any tracks yet. Statistics build up as you listen.",
    "Henüz dinleme geçmişi yok. 30 saniyeden uzun dinlediğin şarkılar burada görünür.":
        "No listening history yet. Tracks listened for over 30 seconds appear here.",
    "🖼 PNG olarak kaydet": "🖼 Save as PNG",
    "⬇ İndirmeler": "⬇ Downloads",
    "🧹 Bitenleri Temizle": "🧹 Clear Completed",
    "Tekrar dene": "Retry",
    "Tekrar Dene": "Retry",
    "İptal et / listeden kaldır": "Cancel / remove from list",
    "İndirme kuyruğu boş.": "Download queue is empty.",
    "İptal et": "Cancel",
    "Listeden kaldır": "Remove from list",

    # --- Ayarlar (Settings) ---
    "🎨  Görünüm": "🎨  Appearance",
    "▶  Oynatma": "▶  Playback",
    "🗄  Depolama": "🗄  Storage",
    "🎧  Entegrasyonlar": "🎧  Integrations",
    "⬆  Güncellemeler": "⬆  Updates",
    "Görünüm": "Appearance",
    "Oynatma": "Playback",
    "Depolama": "Storage",
    "Entegrasyonlar": "Integrations",
    "Güncellemeler": "Updates",
    "Geri dön": "Go back",
    "İptal": "Cancel",
    "Kaydet": "Save",
    "Kapat": "Close",
    "Vazgeç": "Cancel",
    "Durdur": "Stop",
    "Ekle": "Add",
    "Tema": "Theme",
    "Dil / Language": "Language / Dil",
    "Arayüz dili": "Interface language",
    "Seçim anında tüm arayüze uygulanır.": "Applied across the interface immediately.",
    "Renk teması": "Color theme",
    "Seçim anında uygulanır.": "Applied immediately.",
    "Dinamik vurgu rengi": "Dynamic accent color",
    "Çalan şarkının kapak resminden otomatik vurgu rengi çıkarır.":
        "Automatically extracts an accent color from the playing track's cover art.",
    "Genel Davranış": "General Behavior",
    "Sayfa boyutu": "Page size",
    "Kütüphane listelerinde bir sayfada gösterilecek şarkı sayısı.":
        "Number of songs shown per page in library lists.",
    "Son oturumu geri yükle": "Restore last session",
    "Açılışta kaldığın liste ve şarkıyı otomatik yükler.":
        "Automatically restores your last playlist and track on startup.",
    "Sistem tepsisine küçült": "Minimize to system tray",
    "Kapatınca ya da küçültünce arka planda çalmaya devam eder.":
        "Keeps playing in the background when closed or minimized.",
    "Güncellemeleri otomatik denetle": "Check for updates automatically",
    "Açılışta GitHub'dan yeni Audifly sürümü var mı diye bakar (yalnızca sürüm bilgisi sorulur). "
    "Elle denetlemek için: Araçlar → Güncellemeleri Denetle.":
        "Checks GitHub for a new Audifly release on startup. "
        "To check manually: Tools → Check for Updates.",
    "Ses seviyesini dengele": "Normalize volume",
    "Şarkılar arasındaki ses seviyesi farkını otomatik dengeler.":
        "Automatically balances volume differences between tracks.",
    "Crossfade": "Crossfade",
    "Şarkılar arası yumuşak ses geçişi ve geçiş süresi.":
        "Smooth audio transition between songs and its duration.",
    "Denetimler": "Controls",
    "Global medya tuşları": "Global media keys",
    "Play/duraklat, sonraki ve önceki tuşlarını sistem genelinde dinler ('keyboard' paketi gerekir).":
        "Listens for Play/Pause, Next, and Previous keys system-wide (requires 'keyboard' package).",
    "Windows medya denetimleri (SMTC)": "Windows media controls (SMTC)",
    "Ses açılır penceresinden oynatmayı kontrol etmeni sağlar.":
        "Lets you control playback from the Windows volume flyout.",
    "Önbellek Yönetimi": "Cache Management",
    "🧹  Çevrimdışı müzikleri temizle": "🧹  Clear offline music",
    "🧹  Thumbnail önbelleğini temizle": "🧹  Clear thumbnail cache",
    "Yedekleme": "Backup",
    "Otomatik yedekleme": "Automatic backup",
    "Bozuk dosyaya karşı playlist verisinin 3 kopyasını tutar.":
        "Keeps 3 rolling copies of playlist data against file corruption.",
    "Spotify İçe Aktarma": "Spotify Import",
    "Client Secret (isteğe bağlı, PKCE ile gerekmez):":
        "Client Secret (optional, not needed with PKCE):",
    "🟢 Bağlı": "🟢 Connected",
    "⚪ Bağlı değil": "⚪ Not connected",
    "🔗 Bağlan": "🔗 Connect",
    "🔄 Yeniden Bağlan": "🔄 Reconnect",
    "⛔ Bağlantıyı Kes": "⛔ Disconnect",
    "Hesap durumu": "Account status",
    "Spotify değerlerini developer.spotify.com/dashboard adresinden ücretsiz oluşturabilirsin.":
        "You can create free Spotify credentials at developer.spotify.com/dashboard.",
    "Client ID/Secret değerlerini developer.spotify.com/dashboard adresinden ücretsiz oluşturabilirsin.":
        "You can create free Client ID/Secret credentials at developer.spotify.com/dashboard.",
    "yt-dlp (YouTube çıkarımı)": "yt-dlp (YouTube extraction)",
    "🔄  Güncellemeleri Kontrol Et ve Güncelle": "🔄  Check & Update Now",
    "↩  Paketteki sürüme sıfırla": "↩  Reset to bundled version",
    "yt-dlp'yi otomatik güncelle": "Auto-update yt-dlp",
    "YouTube çıkarımı değiştiğinde ya da açılışta yeni yt-dlp sürümünü otomatik indirir (kurulum gerektirmez).":
        "Automatically downloads new yt-dlp releases on startup or when YouTube changes (no installer needed).",
    "🌐 PyPI kontrol ediliyor…": "🌐 Checking PyPI…",
    "🌐 Tarayıcıda giriş bekleniyor…": "🌐 Waiting for login in browser…",

    # --- Tanılama / Sorun Bildir ---
    "Sorun Bildirme ve Tanılama": "Issue Reporting & Diagnostics",
    "🩺  Sorun Bildir / Tanılama Raporunu Aç": "🩺  Report Issue / Open Diagnostics",
    "🩺 Sorun Bildir / Tanılama Raporu": "🩺 Report Issue / Diagnostics Report",
    'Aşağıdaki rapor sürüm, bileşen durumu ve son hata kayıtlarını içerir '
    '(parola, token veya kişisel klasör adı içermez). "Raporu Kopyala"ya '
    'basıp mesaj olarak gönderebilirsin.':
        'The report below contains version, component status, and recent error logs '
        '(no passwords, tokens, or personal folder names). Click "Copy Report" and send it.',
    "Ne yaparken sorun oldu? (isteğe bağlı):": "What were you doing when the issue happened? (optional):",
    "Örn: Şarkıya tıkladığımda çalmadı ve altta kırmızı hata çıktı…":
        "E.g. I clicked a song, it didn't play and showed an error at the bottom…",
    "Tanılama raporu:": "Diagnostics report:",
    "📋 Raporu Kopyala": "📋 Copy Report",
    "💾 Dosyaya Kaydet…": "💾 Save to File…",
    "🌐 GitHub'da Bildir": "🌐 Report on GitHub",
    "✅ Kopyalandı!": "✅ Copied!",
    "Rapor panoya kopyalandı — doğrudan yapıştırıp gönderebilirsin.":
        "Report copied to clipboard — you can paste and send it directly.",

    # --- Giriş / Diyaloglar ---
    "Hesabınla giriş yap": "Sign in to your account",
    "Kullanıcı adı": "Username",
    "Şifre": "Password",
    "Beni hatırla": "Remember me",
    "Giriş Yap": "Sign In",
    "Hesabın yok mu? Kayıt ol": "Don't have an account? Sign up",
    "Yeni bir hesap oluştur": "Create a new account",
    "Kayıt Ol": "Sign Up",
    "Zaten hesabın var mı? Giriş yap": "Already have an account? Sign in",
    "Eksik bileşenler": "Missing components",
    "Bir daha gösterme": "Don't show again",
    "Toplu Şarkı Ekle": "Bulk Add Songs",
    "Aramaya Başla": "Start Search",
    "Ekleniyor…": "Adding…",
    "Durduruluyor…": "Stopping…",
    "🧹 Yinelenen Şarkılar": "🧹 Duplicate Songs",
    "Yinelenen Şarkılar": "Duplicate Songs",
    "🎉 Kütüphanende hiç yinelenen şarkı yok.": "🎉 No duplicate songs in your library.",
    "🎚 Ekolayzer": "🎚 Equalizer",
    "Hazır Ayar:": "Preset:",
    "Özel": "Custom",
    "Sıfırla": "Reset",
    "Ekolayzer bu VLC sürümünde kullanılamıyor.": "Equalizer is not available in this VLC version.",
    "🔎 Kütüphanede Ara": "🔎 Search Library",
    "Tüm listelerde şarkı/sanatçı ara…": "Search songs/artists across all playlists…",
    "Çift tık: çal  •  📂: şarkının listesini göster": "Double-click: play  •  📂: show playlist",
    "Şarkının listesini göster": "Show song's playlist",
    "Yazmaya başla — tüm listelerde aranır.": "Start typing — searches across all playlists.",
    "YouTube'da Ara": "Search on YouTube",
    "Şarkı adı ya da YouTube linki…": "Song title or YouTube link…",
    "Kural Listesi": "Smart List",
    "Yalnızca beğenilenler": "Liked songs only",
    "Kural Listeleri": "Smart Lists",
    "(Henüz kural yok — “Yeni” ile oluştur)": '(No rules yet — create one with "New")',
    "👥 Birlikte Dinle": "👥 Listen Together",
    "Adın": "Your name",
    "Oda kodu ya da davet (örn. K7M2PQ@sunucu.onrender.com)":
        "Room code or invite (e.g. K7M2PQ@server.onrender.com)",
    "Oda şifresi (isteğe bağlı)": "Room password (optional)",
    "⚙ Sunucu ayarı": "⚙ Server settings",
    "＋ Yeni Oda Aç": "＋ Create Room",
    "Odaya Katıl": "Join Room",
    "➕ Çalan şarkıyı ekle": "➕ Add current song",
    "✕ Seçileni çıkar": "✕ Remove selected",
    "Mesaj yaz…": "Write a message…",
    "Gönder": "Send",
    "👑 Sahipliği devret": "👑 Transfer host",
    "🔄 Eşitle": "🔄 Sync",
    "📋 Daveti Kopyala": "📋 Copy Invite",
    "Odadan Ayrıl": "Leave Room",
    "Sunucu:": "Server:",
    "<b>Ortak sıra</b> (şarkı bitince önce buradan çalınır)":
        "<b>Shared queue</b> (plays from here first when a track ends)",
    "<b>Sohbet</b>": "<b>Chat</b>",
    "Odada değilsin.": "Not in a room.",
    "↩ Son işlemi geri alabilirsin.": "↩ You can undo the last action.",
}

# Dinamik metin kalıpları (TR -> EN)
_PATTERNS_EN: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^Kurulu sürüm: (.+)$"), r"Installed version: \1"),
    (re.compile(r"^Çevrimdışı müzikler: (\d+) şarkı • (.+)$"), r"Offline music: \1 tracks • \2"),
    (re.compile(r"^Thumbnail önbelleği: (.+)$"), r"Thumbnail cache: \1"),
    (re.compile(r"^Playlist kapakları: (.+) • Otomatik yedekler: (.+)$"),
     r"Playlist covers: \1 • Auto backups: \2"),
    (re.compile(r"^✅ yt-dlp güncel \((.+)\)$"), r"✅ yt-dlp is up to date (\1)"),
    (re.compile(r"^⬇ (.+) → (.+) indiriliyor…$"), r"⬇ Downloading \1 → \2…"),
    (re.compile(r"^🧹 Kopyaları Temizle \((\d+) şarkı\)$"), r"🧹 Clean Duplicates (\1 tracks)"),
    (re.compile(r"^(\d+) şarkı$"), r"\1 tracks"),
)


def tr(text: str) -> str:
    """Aktif dile göre metni çevirir (`tr` ise dokunmaz)."""
    if not text or _CURRENT_LANG == "tr":
        return text
    if _CURRENT_LANG == "en":
        hit = _EXACT_EN.get(text)
        if hit is not None:
            return hit
        for pattern, repl in _PATTERNS_EN:
            if pattern.search(text):
                return pattern.sub(repl, text)
    return text


# ----------------------------------------------------------------------------
# Qt widget ağacı canlı çevirici
# ----------------------------------------------------------------------------
def _sync_prop(obj, prop_key: str, last_key: str, current: str) -> str:
    """Widget'ın orijinal Türkçe metnini korur; kod yeni bir metin atadıysa günceller."""
    orig = obj.property(prop_key)
    last = obj.property(last_key)
    if orig is None or (last is not None and current != last):
        orig = current
        obj.setProperty(prop_key, orig)
    translated = tr(orig)
    obj.setProperty(last_key, translated)
    return translated


def translate_widget(root) -> None:
    """Verilen widget ve tüm alt bileşenlerini aktif dile çevirir (TR ↔ EN çift yönlü)."""
    if root is None:
        return
    try:
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import (
            QAbstractButton, QComboBox, QLabel, QLineEdit, QMenu, QMenuBar, QWidget,
        )
    except Exception:
        return

    widgets = [root]
    if isinstance(root, QWidget):
        widgets.extend(root.findChildren(QWidget))

    for w in widgets:
        if isinstance(w, QWidget):
            title = w.windowTitle()
            if title:
                new_t = _sync_prop(w, "_i18n_wtitle", "_i18n_wtitle_last", title)
                if new_t != title:
                    w.setWindowTitle(new_t)
            tip = w.toolTip()
            if tip:
                new_tip = _sync_prop(w, "_i18n_tip", "_i18n_tip_last", tip)
                if new_tip != tip:
                    w.setToolTip(new_tip)

        if isinstance(w, (QLabel, QAbstractButton)):
            txt = w.text()
            if txt:
                new_txt = _sync_prop(w, "_i18n_text", "_i18n_text_last", txt)
                if new_txt != txt:
                    w.setText(new_txt)
        elif isinstance(w, QLineEdit):
            ph = w.placeholderText()
            if ph:
                new_ph = _sync_prop(w, "_i18n_ph", "_i18n_ph_last", ph)
                if new_ph != ph:
                    w.setPlaceholderText(new_ph)
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                it = w.itemText(i)
                if it:
                    new_it = _sync_prop(w, f"_i18n_item_{i}", f"_i18n_item_last_{i}", it)
                    if new_it != it:
                        w.setItemText(i, new_it)
        elif isinstance(w, QMenu):
            t = w.title()
            if t:
                new_t = _sync_prop(w, "_i18n_mtitle", "_i18n_mtitle_last", t)
                if new_t != t:
                    w.setTitle(new_t)

        if isinstance(w, (QWidget, QMenu, QMenuBar)):
            for act in w.actions():
                if isinstance(act, QAction):
                    at = act.text()
                    if at:
                        new_at = _sync_prop(act, "_i18n_atext", "_i18n_atext_last", at)
                        if new_at != at:
                            act.setText(new_at)


def apply_language(lang: str, app=None) -> None:
    """Aktif dili değiştirir ve açıktaki tüm üst seviye pencereleri anında çevirir."""
    set_language(lang)
    try:
        from PySide6.QtWidgets import QApplication
        app = app or QApplication.instance()
        if app is None:
            return
        install_auto_translator(app)
        for w in app.topLevelWidgets():
            translate_widget(w)
    except Exception:
        pass


def install_auto_translator(app) -> None:
    """Yeni açılan diyalog/menüler gösterilirken (`QEvent.Show`) otomatik çevrilir."""
    global _FILTER
    if _FILTER is not None or app is None:
        return
    try:
        from PySide6.QtCore import QEvent, QObject

        class _ShowTranslator(QObject):
            def eventFilter(self, obj, event):
                if _CURRENT_LANG != "tr" and event.type() == QEvent.Type.Show:
                    translate_widget(obj)
                return False

        _FILTER = _ShowTranslator(app)
        app.installEventFilter(_FILTER)
    except Exception:
        pass

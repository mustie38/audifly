# Değişiklikler

## 0.4.6
- **Uygulama içinden `yt-dlp` güncelleme (yeni kurulum yayınlamadan):** Paketlenmiş `.exe` sürümünde bile `yt-dlp` ve `yt-dlp-ejs` wheel paketleri PyPI üzerinden SHA-256 doğrulamasıyla `%LOCALAPPDATA%\Audifly\components\yt-dlp\` altına indirilir ve açılışta `sys.meta_path` üzerinden devreye girer (`helpers/ytdlp_runtime.py`). Çıkarım hatasında veya açılışta otomatik güncellenir; Ayarlar'dan "Paketteki sürüme sıfırla" ile geri alınabilir.
- **Sorun Bildir / Tanılama Raporu arayüzü (`views/diagnostics_dialog.py`):** Yardım menüsü, sol alt araç çubuğu (`🩺`), Ayarlar → Güncellemeler ve hata bildirim çubuğundaki (`🩺 Sorun Bildir`) düğmelerden açılır; kullanıcı notu, son hatalar ve log kuyruğu tek tıkla kopyalanabilir veya dosyaya kaydedilebilir.
- **Çoklu şarkı ön yükleme (3 şarkı) + otomatik yeniden deneme:** Ön yükleme artık manuel kuyruk ve liste sırasına göre 3 şarkıyı önceden çözer (`PRELOAD_AHEAD = 3`), geçici ağ/YouTube hatalarında kademeli beklemeyle yeniden dener ve YouTube stream linklerindeki `expire=` süresini denetler.
- **Gömülü libVLC (`packaging/fetch_vlc.py`):** Kurulum paketi artık libVLC çalışma zamanını ve ses/ekolayzer/normalleştirme eklentilerini kendi içinde taşır (LGPL-2.1+); kullanıcının ayrıca VLC Media Player kurması gerekmez.
- **Authenticode kod imzalama altyapısı (`packaging/sign_binaries.py`):** `WINDOWS_PFX_BASE64` ve `WINDOWS_PFX_PASSWORD` tanımlandığında `Audifly.exe` ve `AudiflySetup.exe` SHA-256 + RFC3161 zaman damgasıyla otomatik imzalanır.
- **Çoklu dil desteği (`helpers/i18n.py`):** Ayarlar → Görünüm altında `🇹🇷 Türkçe` / `🇬🇧 English` dil seçeneği eklendi; yeniden başlatmadan tüm arayüze anında uygulanır.
- **Toplu hata düzeltmeleri:** İndirmeler sayfasında tamamlanan/başarısız öğelerin listeden kaldırılamaması ve canlı ilerleme çubuğunun güncellenmemesi; Kütüphanede Ara (`Ctrl+K`) penceresinde çift tıklamayla şarkının çalmaması; Sağ paneldeki `🎤 Sözler` düğmesinin çalışmaması; Ayarlar'dayken tekrar Ayarlar'a basınca geri dönülememesi ve İptal'in tema/dil önizlemesini geri almaması; Keşfet/Ana Sayfa/İstatistikler kapaklarının indiğinde güncellenmemesi; Crossfade sırasında sarma (`seek`) ve sınır aşımı; silinen listelerin çevrimdışı MP3 dosyalarının yetim kalması düzeltildi.
- **Performans ve optimizasyon:** Gizli sekmelerde (`HomeView`, `LibraryGridView`) gereksiz yeniden çizim `_dirty` bayrağı ve debounce ile ertelendi; kapak ve 4'lü kolaj üretimine RAM LRU önbelleği eklendi (`helpers/covers.py`); `ThumbnailService`'e HTTP keep-alive bağlantı havuzu (`requests.Session`) eklendi; `HistoryStore.since()` ISO-8601 hızlı karşılaştırmayla ~15 kat hızlandırıldı; gizli/küçültülmüş plak, ses dalgası ve satır ekolayzer animasyon zamanlayıcıları durdurularak boşta CPU kullanımı sıfırlandı.

## 0.4.5
- **Kurulum dosyası (Inno Setup) derleme hataları düzeltildi:** satır başında `#13#10` ("Unknown preprocessor directive"), `[Setup]` satırında geçersiz satır sonu yorumu ve eksik UTF-8 BOM (Türkçe metin bozuk çıkardı). `packaging/set_iss_version.py` etiket sürümünü .iss'e yazar; `tests/test_installer_script.py` bu hata sınıfını artık her push'ta yakalar.
- **Kurulum dosyası artık Node.js içerir** ve YouTube JS çözücüsü `yt-dlp-ejs` pakete dahildir: ayrıca Node.js kurmadan şarkılar çalar. (Önceden `yt-dlp-ejs` bağımlılıklarda yoktu; Node kurulu olsa bile paketli sürümde YouTube çözümü başarısız olabiliyordu.) `packaging/fetch_node.py` node.exe'yi SHA-256 doğrulamasıyla indirir; CI paketin içinde node.exe ve `core.min.js` olduğunu denetler.
- `pyproject.toml`/`requirements.txt`: `yt-dlp[default]` ve `yt-dlp-ejs` eklendi.

## 0.4.4
- Pencere başlığı artık sürüm numarasını gösterir (hangi sürümün kurulu olduğu bir bakışta görülür).

## 0.4.3
- **CI:** testler dosyaları açıkça UTF-8 okur/yazar (Windows'ta varsayılan cp1252 Türkçe karakterleri bozuyordu; uygulama kodu zaten UTF-8 kullanıyor).
- **CI:** libvlc kurulu olmayan ortamlarda (GitHub Actions) testler sahte `vlc` modülüyle çalışır; önceden `import vlc` yüzünden 4 test dosyası toplanamıyor ve Release akışı duruyordu.
- **Kapanış:** Küçük resim indirmeleri kapanışta iptal edilir; uygulama arka plan thread'leri yüzünden açık kalmaz (güncelleme kurulumunun çalışan `Audifly.exe`'yi bulmasını önler).

## 0.4.2 (hata düzeltmeleri ve güncelleme özelliği)
- **Uygulama güncellemesi (yeni):** Araçlar → "🔄 Güncellemeleri Denetle…" ve açılışta otomatik denetim (Ayarlar'dan kapatılabilir). GitHub Releases (`mustie38/audifly`) üzerinden son sürüm sorulur; paketlenmiş Windows uygulamasında kurulum dosyası indirilir, **SHA-256 ile doğrulanır** ve kurulum başlatılır (kullanıcı verisi korunur). Doğrulanamayan dosya asla çalıştırılmaz; kaynaktan çalışırken indirme sayfası açılır. "Bu sürümü atla" desteklenir.
- `.github/workflows/release.yml`: `v*` etiketi atınca `AudiflySetup.exe` + `.sha256` üretip Release'e yükler.
- **Doğrudan seçilen şarkı çalınamazsa** artık listede ileri atlanmaz (hata gösterilir); geçici link çözme hatası bir kez yeniden denenir. Otomatik geçişte atlama davranışı değişmedi.
- **Birlikte Dinle + crossfade:** odada misafirken ve oda sahibinde ortak sıra doluyken crossfade artık başlamaz (sıradakini oda belirler). Yanlış oda şifresi artık "sunucu yeniden başlamış" yerine doğru mesajı gösterir.
- **Röle sunucusu:** istemci başına yanlış şifre denemesi sınırı (5 dk'da 8) ve oda sayısı üst sınırı (`MAX_ROOMS`, varsayılan 500).
- **Menü → Çıkış** "tepsiye küçült" açıkken de uygulamayı gerçekten kapatır.
- **Yedekten geri yükleme:** tema, ekolayzer bantları ve akıllı kurallar oturuma alınmadan önce doğrulanır.
- **Toplu Şarkı Ekle:** iptal, başlamamış aramaları da iptal eder (önceden tümünün bitmesi beklenirdi).
- **Çalma sayısı:** hata sonrası stream linki yenilenip tekrar denenen şarkı ikinci kez sayılmaz.
- **Uyku zamanlayıcısı:** süre şarkı çözülürken dolarsa yükleme bitince duraklatır (önceden müzik sonradan çalmaya başlardı).
- **Discord:** duraklatıp devam edince geçen süre korunur; radyo çalarken durum güncellenir; uzun sanatçı adı kırpılır.
- **YouTube playlist içe aktarma:** şarkılar `add_song` ile aynı şekilde normalize edilir.
- Paketleme: `requires-python >=3.11` (spec `tomllib` kullanır), `smtc` ekstrası, `.gitignore`/`MANIFEST.in` tamamlandı.

## 0.4.2 (FAZ 1 – stabilizasyon, 1. dilim)

### FAZ 2 – Dinleme geçmişi
- `services/history_store.py`: eklemeli JSONL olay günlüğü (`listening_history.jsonl`); tarih, sanatçı, gerçekten dinlenen süre, tamamlanma. 30 sn (kısa şarkıda yarısı) altındaki dinlemeler yazılmaz; bozuk satırlar atlanır.
- Oynatma motoru gerçek dinleme süresini biriktirir (duraklatma sayılmaz); atlama, bitiş, crossfade, radyo ve kapanışta oturum kapanır.
- İstatistikler: dönem seçimi (7/30/365 gün/tümü), gerçek toplam dinleme süresi, en çok dinlenen sanatçılar, son dinlenenler (tarih + süre).

### FAZ 2 – Uyku zamanlayıcısı
- Mantık arayüzden `services/sleep_timer.py`'ye taşındı (monotonic bitiş zamanı; test edilebilir).
- 15/30/45/60/90 dk + **özel süre** (1–720 dk), kalan süre gösterimi, iptal.
- İsteğe bağlı **kademeli ses azaltma** (son 30 sn): motorda geçici ses çarpanı; kalıcı ses ayarı değişmez, duraklatma sonrası ses eski seviyesine döner (`sleep_fade_enabled`).

### FAZ 2 – Akıllı çalma listeleri
- `services/smart_lists.py`: yerleşik listeler tek yerde (En Çok Dinlenen / Son Çalınan / Yeni Eklenen davranışı aynı) + yeni **Favori Sanatçılar** (son 90 gün, geçmişe dayalı) ve **Unutulanlar** (60+ gündür dinlenmeyen).
- **Kural Listeleri**: sanatçı/başlık içerir, beğenilenler, çalma sayısı, N gündür dinlenmeyen, N gün içinde eklenen, süre, sıralama, üst sınır. Kurallar ayarlarda (`smart_rules`) saklanır, yedeğe girer ve yüklemede doğrulanır.
- Varsayılan ayarlar artık derin kopyalanır (liste değerleri paylaşılmaz).

### FAZ 2 – Şarkı sözleri
- LRCLIB entegrasyonu yeniden yazıldı (`helpers/lyrics.py`): senkron (LRC) ve düz sözler ayrı; çoklu zaman damgası, `[offset:]` ve meta etiketleri desteklenir.
- Aday doğrulama: başlık benzerliği, sanatçı ve süre kontrolü — ilk sonucu körlemesine almak yerine yanlış şarkının sözü reddedilir. YouTube başlığından ("Sanatçı - Şarkı", "- Topic", VEVO) parça/sanatçı tahmini.
- Kesin eşleşme için `/api/get`, yoksa `/api/search`; diskte önbellek (bulunamadı 7 gün, hata asla önbelleğe yazılmaz).
- Söz penceresi: çalma konumuna göre vurgulanan ve kayan senkron satırlar (satıra tıklayınca sarar); yükleniyor / söz yok / enstrümantal / bağlantı hatası (Tekrar Dene) için ayrı ekranlar; şarkı değişince otomatik yenileme, bayat sonuç filtresi.
- Düzeltme: kapatılan söz penceresi sinyallerden ayrılır (önceden her şarkıda gizlice ağ isteği atmaya devam ediyordu).

### FAZ 3 – Keşfet şeffaflığı
- Her bölüm kaynağını taşır (`source`): Spotify resmi listesi / YouTube Music Charts / YouTube arama sonuçları; arayüzde "Kaynak: … · Güncelleme: …" satırı.
- Sıra rozeti (1, 2, 3…) yalnızca gerçek sıralı liste verisinde gösterilir. Önceden "trend" yedeği aslında arama sorgularıydı ama sıra rozeti basılıyordu.
- Chart arama yedeğine düşerse "yükselişe geçen" gibi iddialı alt başlık yerine dürüst bir not gösterilir.
- YouTube Music chart bölümleri (songs/trending/videos) artık birleştirilmez; sıra tek listeden gelir.
- Eski önbellekte kaynak bilgisi yoksa sıra rozeti gizlenir ("kaynak bilinmiyor").
- Kullanılmayan ve yanıltıcı (chart sırasını `random.shuffle` ile bozan) `helpers/explore.py` silindi; tek keşif sistemi `DiscoveryService`.
- "Bugünün Keşfi" artık rastgele seçildiğini söyler (kişiselleştirilmiş gibi sunulmaz).

### FAZ 3 – Kişisel Mix'ler
- `services/mixes.py` (yerel, harici API yok): **Sana Özel** (zamanla sönümlenen dinleme puanı + beğeni + sevilen sanatçıların az dinlenmiş şarkıları), **Günlük Mix** (tarihe bağlı sabit tohum: gün içinde aynı, ertesi gün değişir; birkaç "sürpriz" şarkı), **"<Sanatçı> Tarzı"** (aynı oturumda birlikte dinlenen sanatçı kümeleri).
- Şarkı verisinde tür bilgisi olmadığından "tarz" tür etiketinden değil davranıştan türetilir; arayüz bunu açıkça yazar.
- Mix'ler yalnızca kütüphanedeki şarkılardan oluşur; sanatçı başına üst sınır, art arda aynı sanatçı ayrılır.
- Yeni sayfa "Senin İçin Mix'ler": ▶ Çal (mix sırasıyla kuyruğa yükler) ve Listeyi Aç. Yeterli veri yoksa açıklayıcı boş durum.
- `PlaylistStore.set_queue` eklendi.

### FAZ 4 – Yayına hazırlık
- **Marka**: kullanıcıya görünen ad **Audifly** (`APP_DISPLAY_NAME`, tek nokta): pencere/giriş/mini oynatıcı başlıkları, kenar çubuğu, tepsi, SMTC, Discord, Wrapped, User-Agent, yedek dosyası (`audifly-backup`; eski `mustiefly-backup` yedekleri içe aktarılır), `audifly` komutu (eski `mustiefly` de çalışır), PyInstaller/Inno dosyaları (`audifly.spec/.iss`, `Audifly.exe`, `AudiflySetup.exe`). İç paket adı `mustiefly_qt` bilerek korundu.
- **Veri güvenliği (göç)**: Eski `Mustiefly` veri klasörü varsa kullanılmaya devam eder (kütüphanedeki mutlak `cached_path` yolları kırılmasın); yeni kurulumlar `Audifly` klasörünü kullanır. `AUDIFLY_DATA_DIR` (eski `MUSTIEFLY_DATA_DIR` de geçerli). Keyring'de eski `Mustiefly` kayıtları okunup yeni ada taşınır. Aynı Inno `AppId` → eski kurulumun üzerine kurulum veriyi korur.
- **Marka ikonu** kodla çizilir (`helpers/brand_icon.py`, yazı tipi bağımsız); pencere, tepsi ve `.ico` (`packaging/make_icon.py`) aynı çizimi kullanır. **Hata düzeltme**: sistem tepsisi simgesine hiç ikon atanmamıştı (Qt ikonsuz tepsi simgesini göstermez).
- **PyInstaller**: ikon, Windows sürüm bilgisi (pyproject'ten), koşullu isteğe bağlı hiddenimports (ytmusicapi, pypresence, keyring, winsdk/winrt), isteğe bağlı `packaging/bin` (ffmpeg/node) paketleme; Linux'ta derlenip açılışı doğrulandı. Inno: sürüm 0.4.2, ikon, varsayılan yönetici izni gerektirmeyen kurulum.
- **Bağımlılık denetimi** (`helpers/dependencies.py`): FFmpeg (+ffprobe) ve Node.js eksikse açılışta ne işe yaradığını ve kurulumunu anlatan tek bir uyarı ("bir daha gösterme" seçeneğiyle); paketle gelen `bin/` PATH'e eklenir. VLC denetimi eskisi gibi engelleyici.
- **Hata raporlama**: yakalanmamış hata için kullanıcı penceresi (kayıt klasörü, kopyalanabilir tanılama bilgisi: sürüm, sistem, bileşenler, son log satırları; kullanıcı yolu maskelenir), thread hataları kaydı. **Hata düzeltme**: giriş öncesi loglama dosyaya yazmıyordu (`get_logger` klasörsüz yapılandırıp kilitliyordu) → pencereli EXE'de açılış hataları kayboluyordu; artık `audifly.log` hem başlangıç klasörüne hem kullanıcı klasörüne yazılır.
- CI: Windows'ta PyInstaller derleme işi (`package-windows`). `DAGITIM_REHBERI_TR.md` eklendi.

### Temizlik
- Oynatıcı çubuğundaki `manzara.png` arka planı ve PyInstaller spec'teki referansı kaldırıldı (dosya yoktu, log'a sürekli hata yazıyordu). Çubuk düz koyu zemin + karartma katmanı kullanır.

### FAZ 3 – Wrapped
- `services/wrapped.py`: günlükten dönemlik özet — toplam süre, dinleme/şarkı/sanatçı sayısı, aktif gün, en uzun dinleme serisi, en yoğun ay/gün/gün bölümü, ilk kez dinlenen sanatçılar, en çok dinlenen 5 sanatçı ve şarkı. Yıl sonunu beklemeden **"Son 12 ay"** ya da günlükte verisi olan herhangi bir **takvim yılı** için üretilir.
- Yeterli veri yoksa (en az 10 dinleme ve 3 farklı gün) uydurma özet yerine açıklayıcı boş durum.
- Wrapped sayfası: dönem seçimi + paylaşılabilir **PNG kartı** (tema bağımsız sabit tasarım, 540×780).
- `APP_DISPLAY_NAME` sabiti eklendi (FAZ 4'te yeniden adlandırma tek noktadan).

### Kimlik doğrulama / oynatma
- Spotify yetkilendirmesi PKCE (S256) kullanır; `client_secret` artık isteğe bağlıdır (eski secret'lı bağlantılar yenilemede çalışmaya devam eder).
- İkinci (eski) indirme yolu kaldırıldı; tüm indirmeler `DownloadManager` üzerinden.
- Karışık çalmada sıradaki şarkı planlanır: ön yükleme ile gerçek geçiş aynı şarkıyı hedefler.

### Veri güvenliği
- Ayar yazımı tek yola indirildi (`auth.service.save_settings_for`): atomik yazım. Önceden ayarlar penceresi ve ekolayzer hâlâ düz `open(..., "w")` kullanıyordu (0.4.1 notu eksik uygulanmıştı).
- Spotify client secret / refresh token / access token varsa işletim sistemi kimlik deposuna (keyring) taşınır, ayar dosyasından silinir; keyring yoksa eski davranış korunur (veri kaybı yok).
- Ayarlara şema sürümü (`settings_version`) ve tip/aralık doğrulaması eklendi; bozuk ayar dosyası `.corrupt-<zaman>` olarak saklanır, üzerine yazılmaz.
- Okunamayan kütüphane dosyası da karantinaya alınır; geçersiz ana dosya sağlam yedek rotasyonunu ezmez.
- Yedek içe aktarma artık izin listesi kullanır (yalnızca bilinen taşınabilir ayarlar).
- Keşfet önbelleği atomik yazılır.

## 0.4.1

### Veri güvenliği
- Hesaplar, oturum, ayarlar, kütüphane ve dışa aktarılan yedek atomik yazılır.
- Kapanış kaydı eski arka plan kaydının üzerine yazılmasını bekler.
- Başarısız kütüphane kaydı hata bildirir ve tekrar yazılmak üzere saklanır.
- Kütüphane/yedek yapısı ve şarkı alanları doğrulanır; bozuk yedekler atlanır.
- Geri yükleme tamamlanmadan canlı kütüphane değiştirilmez; eski kuyruk/undo temizlenir.
- Ortak kullanılan ve uygulama önbelleği/kapak dizini dışında kalan dosyalar silinmez.

### Kimlik doğrulama
- Spotify callback yalnız `/callback` ve doğru rastgele `state` ile kabul edilir.
- Geçersiz callback yetkilendirmeyi bitirmez; dinleyici her durumda kapatılır.
- Bozuk hesap dosyası üzerine yeni hesap kaydedilmez; başarısız kayıt başarı sayılmaz.
- Windows ayrılmış dosya adları, satır sonları ve büyük/küçük harf hesap çakışmaları engellenir.
- Yeni şifrelerde 8 karakter alt sınırı; mevcut şifrelerin hash formatı korunur.
- Spotify secret/token ve makineye özgü oturum bilgisi yedekte taşınmaz.

### Oynatma ve indirme
- Her oynatma/crossfade isteği nesil numarası ve şarkı nesnesiyle doğrulanır.
- İndirme iptali/tekrarı ayrı girişimlere bağlıdır; eski tamamlanma yeni işi bitirmez.
- Var olmayan/boş çıktı dosyaları indirme başarısı sayılmaz.
- İndirilmiş dosya aynı URL'nin kütüphanedeki tüm kopyalarına bağlanır.
- İki VLC oynatıcısı ve Qt zamanlayıcıları kapanışta durdurulur.
- Crossfade için sıradaki hedef bulunamaması artık unpack hatası oluşturmaz.
- Gerçek dosya varlığına göre çevrimdışı rozeti; silinmiş önbellek yeniden indirilebilir.
- Sistem tepsisi yoksa pencere görünmez şekilde arka planda bırakılmaz.

### Geliştirici deneyimi
- Opsiyonel `pypresence` kurulu değilken ana uygulamanın import/açılış hatası giderildi.
- Setuptools paket eşlemesi, `mustiefly` komutu ve kullanıcıya yazılabilir veri yolları.
- Sürüm karşılaştırması yeni sürümün gerçekten daha büyük olduğunu denetler.
- Paketlenmiş uygulamada kendisini `python -m pip` diye başlatma engellenir.
- PyInstaller dosya yolları çalışma dizininden bağımsızdır; eksik arka plan görseli opsiyoneldir.
- Regresyon testleri ve Linux/Windows, Python 3.11/3.13 CI tanımı eklendi.

# Audifly — PySide6/Qt Sürümü

> Eski adı Mustiefly. Kaynak paket adı `mustiefly_qt` olarak kaldı (iç ad); kullanıcıya görünen her yerde Audifly kullanılır.

## Çalıştırma (0.4.5)

Python 3.11+ gerekir. Proje klasöründe:

```bash
python -m pip install -e .
audifly        # eski komut adı `mustiefly` de çalışır
```

VLC Media Player sistemde ayrıca kurulu olmalıdır. Çevrimdışı MP3 indirmeleri
**FFmpeg** gerektirir; `ffmpeg` ve `ffprobe` PATH üzerinde bulunmalıdır.
YouTube çözümlemesi için Node.js LTS ve gerektiğinde `yt-dlp-ejs` önerilir.
Bunlar kaynak paketine gömülmez.

Kaynak klasörünün adı `mustiefly_qt` ise bir üst dizinden
`python -m mustiefly_qt.main` komutu da kullanılabilir.

### Veri konumu

- Veri, kaynaktan çalıştırmada da kurulumda da kullanıcı veri klasörüne yazılır:
  Windows `%LOCALAPPDATA%/Audifly`, macOS
  `~/Library/Application Support/Audifly`, Linux
  `$XDG_DATA_HOME/Audifly` (varsayılan `~/.local/share/Audifly`).
- Eski `Mustiefly` veri klasörü varsa (çevrimdışı indirme yolları bozulmasın diye) o kullanılmaya devam eder.
- `AUDIFLY_DATA_DIR` (eski adıyla `MUSTIEFLY_DATA_DIR`) ortam değişkeniyle veri dizini açıkça seçilebilir.
- Eski sürümlerden kalan `users.json` / `users/` (paket klasörünün bir üstünde ya da
  `.exe`'nin yanında) bulunursa bir kez yeni konuma KOPYALANIR; eski dosyalar silinmez ve
  klasörde `AUDIFLY_TASINDI.txt` işareti bırakılır. Önce yedek alınması önerilir.

## 0.4.1 iyileştirmeleri

- Atomik JSON kaydı ve kapanışta eski kayıt işçisini bekleme.
- Geçersiz kütüphane/yedek doğrulaması, başarısız geri yüklemede mevcut veriyi koruma.
- Paylaşılan önbellek ve kullanıcıya ait olmayan dosyalar için silme koruması.
- Spotify OAuth `state` doğrulaması ve dinleyici temizliği.
- İptal/tekrar denemede indirme girişimlerinin ayrılması; var olmayan çıktıya başarı denmemesi.
- Bayat oynatma/crossfade sonuçlarının yok sayılması ve iki VLC oynatıcısının kapatılması.
- Dosyanın gerçekten var olmasına bağlı çevrimdışı şarkı rozeti.
- Kurulabilir wheel, `mustiefly` komutu, regresyon testleri ve CI yapılandırması.

Ayrıntılı teknik değerlendirme: `REVIEW_TR.md`. Değişiklik listesi: `CHANGELOG.md`.

## Çalışan özellikler (Faz 1 + Faz 2 tamam)

### Temel (Faz 1)
- Yerel giriş/kayıt (mevcut `users.json` ile uyumlu), "beni hatırla"
- Çoklu kullanıcı: her kullanıcının kendi playlist/ayarlar/önbellek klasörü
- Çalma listesi oluşturma / yeniden adlandırma / silme / geçiş
- YouTube arama (yt-dlp) ve playliste ekleme
- VLC ile oynatma: çal/duraklat/sonraki/önceki, sarma (seek), ses, karışık
  çalma, tekrar modu (kapalı/tümü/tek), sıradaki şarkının ön yüklenmesi
- Beğenme, şarkı kaldırma, çevrimdışı indirme
- "Beğenilenler" görünümü, kütüphane içi arama/filtre
- Playlist verisi: debounce'lu kayıt, otomatik yedekleme (bak1/2/3), bozuk
  dosyadan kurtarma — orijinal koddaki mantıkla birebir

### Faz 2'de gelenler
- **Mini oynatıcı**: her zaman üstte küçük pencere, temel kontroller
- **Discord Rich Presence**: `pypresence` kuruluysa otomatik aktif
- **Sistem tepsisi**: küçültünce tepsiye iner, çift tıkla geri açılır
- **Ana Sayfa panosu**: istatistik kartları, hızlı erişim playlist grid'i,
  Son Çalınanlar listesi ve tüm kütüphaneden Karışık Çal
- **Manuel kuyruk ("Sıradaki")**: ⋮ menüsünden kuyruğa ekle; otomatik geçişte
  önce kuyruk tüketilir (Spotify mantığı); sürükle-bırak ile sıra değiştirme;
  tek tıkla çal/geç; "ŞİMDİ ÇALIYOR" şeridi
- **Radyo**: Radio Browser API üzerinden gerçek canlı istasyonlar; arama,
  ülke/tür filtreleri, favoriler (ayarlarda saklanır), canlı yayın göstergesi
- **Keşfet**: YouTube trend/popüler seçkisi (ytmusicapi Charts → trend sekmesi
  → arama yedeği zinciri); tek tıkla kütüphaneye ekle / ekle+çal
- **Ekolayzer**: VLC AudioEqualizer penceresi — hazır ayarlar, 10 bant,
  sıfırlama; değişiklikler debounce'lu olarak settings dosyasına yazılır
- **Sözler paneli**: lrclib.net'ten o an çalan şarkının sözleri; şarkı
  değişince otomatik yenilenir
- **Toplu Şarkı Ekle**: satır satır isim listesini paralel YouTube aramalarıyla
  (5 işçi) eşleştirip listeye ekler; ilerleme çubuğu + iptal desteği
- **Spotify Playlist İçe Aktarma**: Authorization Code OAuth akışı (ilk seferde
  tarayıcıda onay, sonrasında refresh_token sessiz yenilenir); her Spotify
  parçası için YouTube'da en iyi eşleşme aranır
- **M3U içe/dışa aktarma**: aktif listeyi .m3u8 olarak kaydet, M3U'dan
  YouTube linklerini çözerek geri yükle
- **Yinelenen şarkı bulucu**: webpage_url'e göre gruplar, tek tıkla temizler
- **Geri al (undo)**: silme/temizleme/liste silme işlemleri için snackbar +
  Araçlar menüsünden Geri Al (son 10 işlem, 8 sn dosya silme penceresi —
  indirilen dosya yanlışlıkla silindiyse diskten de geri gelir)
- **Görsel iyileştirmeler**: şarkı satırlarında gerçek thumbnail'ler,
  sidebar'da playlist kapak kolajları + özel kapak seçimi, çalan şarkıda
  dönen plak animasyonu, altta canlı waveform şeridi
- **Global medya tuşları**: `keyboard` paketi kuruluysa play/pause, sonraki,
  önceki tuşları (Ayarlar'dan açılır)

## Bilinen sınırlamalar

- **Platform**: Öncelikli olarak Windows için geliştirilmiştir. SMTC, global
  medya tuşları (`keyboard` paketi) ve sistem tepsisi entegrasyonu
  Windows'ta tam çalışır; Linux/Mac'te bu özellikler sessizce devre dışı
  kalır (uygulamanın geri kalanı çapraz platform çalışır).
- **Güvenlik**: Hesaplar tamamen yerel makinede, düz JSON olarak saklanır
  (şifreler PBKDF2+salt ile hash'lenir). Spotify `client_secret` ve yenileme
  belirteci işletim sisteminin anahtar deposunda (keyring) tutulur; keyring
  kullanılamıyorsa ayarlar dosyasında düz metin olarak kalır. Bu, tek kullanıcılık
  bir masaüstü bilgisayar için tasarlanmıştır — paylaşılan/çok kullanıcılı
  bir makinede çalıştırmadan önce bunu bilerek karar ver. Yedek dışa aktarımında
  Spotify secret/token ve son oturum bilgisi artık taşınmaz. Yeni hesaplarda
  şifre en az 8 karakterdir; eski hesap şifreleri girişte çalışmaya devam eder.
  Bu yerel giriş, işletim sistemi kullanıcı izolasyonunun yerini almaz;
  “beni hatırla” açıkken uygulama şifre istemeden açılır.
- Radyo/Keşfet/Sözler/Spotify özellikleri internet bağlantısı ister.
- Global medya tuşları için `keyboard` paketi gerekir (kurulu değilse özellik
  sessizce devre dışı kalır).
- Discord RPC için `pypresence` gerekir (kurulu değilse sessizce devre dışıdır).
- Oynatma motoru ayrıca kurulması gereken **VLC Media Player**'a bağımlıdır
  (python-vlc sadece bağlayıcıdır). Uygulama artık açılışta VLC'yi kontrol
  edip eksikse anlaşılır bir hata mesajı gösteriyor (bkz. `main.py`).

## Loglama

Hatalar artık konsola `print` ile değil, gerçek bir loglama altyapısına
yazılıyor (`helpers/logging_setup.py`):
- Giriş ekranından önceki hatalar sadece konsola basılır.
- Giriş yaptıktan sonra her şey ayrıca `users/<kullanıcı_adı>/logs/audifly.log`
  dosyasına da yazılır (1 MB'ta bir döner, 3 yedek tutulur).
- Yakalanmamış (beklenmeyen) hatalar bile artık log dosyasına düşer —
  pencereli/paketlenmiş bir `.exe` olarak çalışırken bir şey ters giderse
  bu dosyaya bakabilirsin.

## Testler

```bash
pip install -e ".[dev]"     # pytest + pytest-qt kurar
python -m pytest -q
ruff check . --select E9,F821,F822,F823
python -m build
```

`tests/` klasöründeki testler kimlik doğrulama (hash/salt, kullanıcı adı
doğrulama, path-traversal koruması), Spotify playlist ID ayrıştırma ve
yinelenen şarkı bulma/temizleme mantığını kapsar. PySide6 gerektiren testler
(`test_playlist_store.py`) PySide6 kurulu değilse otomatik atlanır.

## Dağıtılabilir .exe oluşturma

```bash
pip install pyinstaller
cd ..                                   # mustiefly_qt/'yi İÇEREN klasöre geç
pyinstaller mustiefly_qt/packaging/audifly.spec
```

Çıktı `dist/Audifly/` altında olur. Derlemeden önce `python packaging/fetch_node.py` ile
Node.js (YouTube şarkı çözümü için) pakete eklenir; GitHub Release akışı bunu otomatik yapar.
VLC yine de ayrıca kurulu olmalı — PyInstaller onu pakete dahil etmez.

Ayrıntılı faz geçmişi için `NEXT_PHASES.md` dosyasına bak.
## Güncelleme
**Araçlar → 🔄 Güncellemeleri Denetle…** (ya da açılışta otomatik; Ayarlar → Genel'den kapatılır).
Uygulama yalnızca GitHub'daki `mustie38/audifly` Release bilgisini sorar. Kurulum dosyası
(`AudiflySetup.exe`) indirildikten sonra SHA-256 ile doğrulanır; doğrulanamazsa çalıştırılmaz.
**Yeni sürüm yayınlamak:** `pyproject.toml`, `helpers/constants.py` (`APP_VERSION`) ve gerekirse
`packaging/audifly.iss` sürümünü yükselt → `git tag v0.4.3 && git push origin v0.4.3`.
`release.yml` kurulum dosyasını üretip Release'e yükler.

## Veri klasörü
Hesap, ayar, kütüphane ve loglar her zaman kullanıcı veri klasörüne yazılır
(Windows: `%LOCALAPPDATA%\Audifly`). Proje klasörünün yanına, masaüstüne ya da kurulum
klasörüne yazılmaz. Eski sürümlerden kalan `users.json` bulunursa bir kez yeni konuma
kopyalanır (eski dosyalar silinmez, klasörde `AUDIFLY_TASINDI.txt` işareti bırakılır).
Klasörü görmek için: **Araçlar → 📁 Veri Klasörünü Aç**. Farklı bir yer için `AUDIFLY_DATA_DIR`
ortam değişkeni kullanılabilir.

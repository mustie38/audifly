# Audifly — Windows Dağıtım Rehberi

## 1. Derleme
```
pip install -e ".[dev]" pyinstaller pypresence ytmusicapi winsdk   # winsdk yerine Python 3.13+ için winrt-* paketleri
python mustiefly_qt/packaging/make_icon.py                         # audifly.ico (marka ikonundan)
python mustiefly_qt/packaging/fetch_node.py                        # packaging/bin/node.exe (SHA-256 doğrulamalı)
python mustiefly_qt/packaging/fetch_vlc.py                         # packaging/vlc/ (libVLC + ses eklentileri, LGPL-2.1+)
pyinstaller mustiefly_qt/packaging/audifly.spec                    # → dist/Audifly/Audifly.exe
python mustiefly_qt/packaging/sign_binaries.py dist/Audifly/Audifly.exe
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" mustiefly_qt\packaging\audifly.iss   # → Output/AudiflySetup.exe
python mustiefly_qt/packaging/sign_binaries.py mustiefly_qt/packaging/Output/AudiflySetup.exe
```
CI (`.github/workflows/release.yml`) aynı adımları Windows'ta çalıştırır ve çıktıyı GitHub Release'e yükler.

## 2. Bileşenler
| Bileşen | Durum | Not |
|---|---|---|
| VLC (libVLC) | **Pakete dahil** (LGPL-2.1+) | `packaging/fetch_vlc.py` resmi win64 arşivini SHA-256 doğrulamalı indirip `libvlc.dll`, `libvlccore.dll`, ses eklentileri ve `COPYING.txt`'yi `packaging/vlc/` altına koyar; kullanıcının ayrıca VLC kurması gerekmez. |
| FFmpeg + ffprobe | İsteğe bağlı (indirme için) | `packaging/bin/` altına koyarsan kurulumla gelir; yoksa açılışta bir kez uyarılır. |
| Node.js | **Pakete dahil** (YouTube çözümleme için gerekli) | CI, `packaging/fetch_node.py` ile güncel LTS `node.exe`'yi (SHA-256 doğrulamalı) indirip `packaging/bin/`'e koyar; LICENSE-node.txt ile birlikte pakete girer. |
| yt-dlp + yt-dlp-ejs | Pakete gömülü + **Uygulama içi güncellenebilir** | Donmuş `.exe` içinde bile PyPI'den SHA-256 doğrulamalı wheel olarak `%LOCALAPPDATA%\Audifly\components\yt-dlp\` altına indirilir ve açılışta `sys.meta_path` üzerinden devreye girer (`helpers/ytdlp_runtime.py`). Yeni kurulum yayınlamaya gerek kalmaz. |

## 3. Kod İmzalama (SmartScreen Uyarısını Kaldırma)
Windows SmartScreen, imzasız `.exe` dosyalarında "Tanınmayan yayıncı" uyarısı gösterir.
`packaging/sign_binaries.py` ve `.github/workflows/release.yml` Authenticode imzalamaya hazırdır:

1. Bir kod imzalama sertifikası (`.pfx` / `.p12`) edin:
   - **Açık kaynak için ücretsiz/uygun seçenekler**: [SignPath Foundation](https://signpath.io/) (açık kaynak projelere ücretsiz), **Azure Artifact/Trusted Signing** (~$10/ay, anında SmartScreen itibarı), ya da **Certum Open Source Code Signing**.
2. Sertifikayı base64'e çevir:
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("sertifika.pfx")) | Set-Clipboard
   ```
3. GitHub repo ayarlarında (**Settings → Secrets and variables → Actions**) şu iki secret'ı tanımla:
   - `WINDOWS_PFX_BASE64`: kopyaladığın base64 metni
   - `WINDOWS_PFX_PASSWORD`: PFX parolası
4. Bir sonraki etiket (`v*`) push'unda hem `Audifly.exe` hem `AudiflySetup.exe` SHA-256 + DigiCert RFC3161 zaman damgasıyla otomatik imzalanır.

## 3. Temiz Windows testi (otomatikleştirilemeyenler — elle yap)
Temiz bir Windows 10/11 sanal makinesinde:
1. `AudiflySetup.exe` kur (yönetici izni olmadan çalışmalı). VLC yokken uyarı görünmeli.
2. VLC kurmadan uygulamayı aç → "VLC Bulunamadı" penceresi (çökme olmamalı).
3. VLC kur → hesap oluştur → şarkı ara/çal, ileri-geri sar, ses, crossfade.
4. FFmpeg olmadan açılışta "Eksik bileşenler" uyarısı; indirme denemesi anlaşılır hata vermeli.
5. Tepsiye küçült → tepsi ikonu görünmeli, çift tıkla geri gelmeli; medya tuşları.
6. Uyku zamanlayıcısı (kısa süre + fade), sözler, Keşfet, Mix, Wrapped PNG.
7. Eski **Mustiefly** kurulumu olan makinede üzerine kur → veriler (kütüphane, çevrimdışı indirmeler, ayarlar) korunmalı (aynı AppId kullanılır).
8. `%LOCALAPPDATA%\Audifly\logs` (veya eski klasör) altında `audifly.log` oluşmalı.
9. Kaldır → uygulama klasörü silinmeli, kullanıcı verisi bilerek silinmez.

## 4. Güncelleme mekanizması (değerlendirme)
- **yt-dlp**: YouTube sık değiştiği için en kritik bağımlılık. Mevcut "tek tıkla güncelle" yalnızca pip ortamında çalışır; paketli sürümde kullanıcıya yeni kurulum önerilir. Öneri: yt-dlp'nin bağımsız `yt-dlp.exe`'sini kullanıcı verisi klasörüne indirip önce onu denemek (ayrı iş, hukuki/güvenlik değerlendirmesiyle).
- **Uygulama**: Henüz yayın adresi (GitHub Releases vb.) belli olmadığı için otomatik güncelleme eklenmedi. Adres netleşince "sürüm JSON'u kontrol et + indirme sayfasını aç" (otomatik kurulum olmadan) en güvenli ilk adımdır. İmzasız EXE'leri otomatik indirip çalıştırmak önerilmez.
- Kod imzalama sertifikası olmadan Windows SmartScreen "bilinmeyen yayıncı" uyarısı gösterir.

## 5. Platform koşulları ve telif (varsayılan olarak eklenmeyenler)
- **YouTube**: İçeriği indirip çevrimdışı kopyalamak YouTube Hizmet Şartları'yla çelişebilir. Genel dağıtımdan önce hukuki görüş al; gerekirse indirme özelliğini varsayılan kapalı/gelişmiş ayar yap.
- **Spotify**: Uygulama Spotify'dan yalnızca kullanıcının kendi çalma listesi meta verisini okur (ses çalmaz) ve PKCE kullanır. Spotify Developer şartlarına göre kendi `client_id`'ni kayıtlı tutman ve yönlendirme adresini (`http://127.0.0.1:8888/callback`) uygulama panelinde tanımlaman gerekir.
- **Keşfet**: Kaynaklar etiketlidir; arama sonuçları sıralı liste gibi sunulmaz.
- **Discord**: Hazır bir istemci kimliği kodda gömülü; dağıtımda kendi Discord uygulamanın kimliğini kullan.

## 6. Windows kabul testi checklist'i

- [ ] VLC + FFmpeg + Node kurulu temiz VM'de açılış
- [ ] SMTC: Windows ses açılır penceresinde şarkı adı/kapak görünüyor mu
- [ ] Medya tuşları: klavyeden play/pause/next/prev
- [ ] Tepsiye küçült + çift tıkla geri aç
- [ ] Crossfade: iki şarkı arasında ses kesintisi yok
- [ ] Yerel mp3 ekle + çal
- [ ] İndirme: FFmpeg ile mp3 üretiyor, boyut > 0
- [ ] Birlikte Dinle: iki instance arasında seek/pause senkron
- [ ] Oda şifresi: yanlış şifre reddediliyor
- [ ] Şarkı sözleri: senkron satır vurgusu kayıyor
- [ ] Wrapped PNG export

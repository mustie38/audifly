# Mustiefly — Teknik inceleme ve 0.4.1 iyileştirmeleri

## Kapsam

Girdi: `repomix-output.xml` içinden çıkarılan 67 metin dosyası. Uygulama
PySide6/Qt arayüzü, VLC oynatma motoru, yt-dlp, yerel JSON hesap/kütüphane
verisi ve Spotify içe aktarma kullanıyor. Mevcut mimari korunarak güvenlik,
veri bütünlüğü ve durum yönetimi önceliklendirildi. Bu paket orijinal Git
uzak deposunu değiştirmez; geliştirilmiş kaynak dosyalarını içerir.

Repomix ikili dosyaları içermez. Bu yüzden varsa özel görseller, ikonlar,
VLC/FFmpeg ve diğer dış bağımlılıklar bu teslimata dahil değildir.

## Genel değerlendirme

**Güçlü yanlar:** Arayüz ile servislerin ayrılması, Qt sinyalleriyle işçi
sonuçlarının taşınması, debounce kayıt, kullanıcı bazlı klasörler,
PBKDF2 parola hash'i, indirme yöneticisi, kuyruk/undo ve önceki yedekler.

**Öncelikli sorun:** Özellik sayısı yüksekken veri kaydı, dosya sahipliği,
bozuk veri doğrulaması ve eşzamanlı işlemler için test kapsamı dar kalmış.
Yeni büyük entegrasyonlar eklemekten önce bu temelin güçlendirilmesi daha
faydalı. Last.fm veya bulut senkronizasyonu gibi kapsamı/kimlik bilgileri
belirsiz özellikler kendiliğinden eklenmedi.

## Bulgular ve uygulanan çözümler

| Öncelik | Bulgu | Uygulanan çözüm | İlgili dosyalar |
|---|---|---|---|
| Kritik | `cached_path` üzerindeki silme dosya sahipliğini kontrol etmiyordu; başka listede kalan aynı dosya da silinebiliyordu | Gerçek yol ile cache/kapak sınırı ve canlı referans kontrolü; silme anında yeniden doğrulama | `services/playlist_store.py` |
| Yüksek | JSON dosyası doğrudan `w` ile açılıyor, hata/çökmede eski içerik kaybolabiliyordu | Aynı dizinde geçici dosya, flush/fsync, atomik replace; geçici dosya temizliği | `helpers/persistence.py`, kayıt çağıranları |
| Yüksek | Kapanıştaki yeni kayıt eski işçi yazımıyla yarışıyordu | İşçinin bitmesini bekleyen son flush; başarısız snapshot'ı yeniden yazabilme | `services/playlist_store.py` |
| Yüksek | Hesap yazma hatası kayıtta başarı sayılıyordu; bozuk hesap dosyası boş sanılabiliyordu | Yazma sonucu kontrolü; bozuk veri üzerinde yeni kayıt engeli | `auth/service.py` |
| Yüksek | Spotify OAuth callback'te `state` ve callback yolu kontrol edilmiyordu | Kriptografik rastgele `state`, sabit yol kontrolü, süre sınırı ve `finally` ile socket temizliği | `helpers/spotify_import.py` |
| Yüksek | Yedek içe aktarmada yanlış JSON yapısı/boş normalize edilmiş liste hata veya erken dosya değişimi oluşturabiliyordu | Sürüm/yapı/base64/boyut doğrulaması, benzersiz kapak staging, disk commit ardından canlı durum değişimi | `helpers/backup.py` |
| Yüksek | Taşınabilir yedekte Spotify secret/refresh token bulunabiliyordu | Bilinen kimlik bilgisi ve son oturum anahtarları dışa/içe aktarımdan çıkarıldı | `helpers/backup.py` |
| Yüksek | İptal/tekrar sırasında aynı URL'nin eski işçi sonucu yeni satırı tamamlayabiliyordu | Her girişim için ayrı olay ve nesne kimliği, bayat sonuç engeli, kapanış iptali | `services/download_manager.py` |
| Orta | İndirme çıktısı yokken `.webm` yolu başarı diye bildiriliyordu | MP3 çıktısının varlık/boşluk kontrolü; FFmpeg hakkında açık hata | İndirme servisi ve eski playback yolu |
| Orta | Liste içeriği değiştiğinde çözülmüş ses eski index'teki farklı şarkıya uygulanabiliyordu | İstek nesli + canlı şarkı nesnesi kontrolü; taşınmış nesnenin yeni konumu | `services/playback.py` |
| Orta | Crossfade hedefi yokken `None` tuple gibi açılıyordu; ikinci player kapanışta bırakılıyordu | Hedef kontrolü, bayat crossfade sonucu kontrolü, iki player için kapanış | `services/playback.py`, `app_window.py` |
| Orta | Liste değiştirme diske kaydedilmiyordu; yeniden adlandırmada kuyruk ipuçları eski kalıyordu | Aktif liste kaydı, kuyruk güncellemesi ve ilgili sinyaller | `services/playlist_store.py` |
| Orta | Windows aygıt adları veya harf büyüklüğü çakışan hesaplar kabul ediliyordu | Ayrılmış ad/trailing dot/satır sonu doğrulaması, casefold çakışma kontrolü | `auth/service.py` |
| Yüksek | Opsiyonel `pypresence` paketinin koşulsuz import edilmesi temel kurulumda uygulamanın açılışını engelliyordu | Eksik bağımlılıkta Discord RPC devre dışı; ana uygulama import testi | `services/discord_rpc.py` |
| Orta | `pip install -e .`/wheel için düz dizinde paket keşfi başarısızdı | Açık setuptools paket eşlemesi ve konsol giriş noktası | `pyproject.toml` |
| Orta | Kurulu wheel hesap verisini site-packages altında yazmaya çalışabilirdi | Platform kullanıcı veri dizini; kaynak/eski kurulum düzenini koruma; env override | `helpers/data_paths.py` |
| Düşük | Eski veya farklı sürüm de “yeni güncelleme” sayılabiliyordu; frozen uygulama pip güncellemesi kendisini başlatabiliyordu | PEP 440 karşılaştırması ve frozen koruması | `helpers/updates.py` |

### Eklenen kullanıcı özelliği

Şarkı satırındaki **çevrimdışı kullanılabilir** rozeti. `cached_path` veya
`local_path` alanının dolu olması yetmez; dosyanın gerçekten mevcut olması
kontrol edilir. İndirme tamamlanınca tüm kütüphane kopyaları güncellenir ve
arayüz yenileme sinyali gönderilir. Silinmiş cache dosyaları toplu indirmede
atlanan şarkı olmaktan çıkar. Kayıp yerel dosyada anlaşılır hata üretilir.

### Güvenlik/uyumluluk notları

- Yeni hesaplarda 8 karakter minimumu; eski PBKDF2 hash'leri ve eski kısa
  şifrelerle giriş korunur.
- Windows için artık geçersiz sayılan kullanıcı adları (ör. `CON`, sonda
  nokta) geçmişte oluşturulmuşsa otomatik yeniden adlandırılmaz. Elle,
  dosyaların yedeği alınarak taşınmaları gerekir.
- Yedek v1/v2 kabul edilir; gelecekteki bilinmeyen sürümler reddedilir.
- Yedek en fazla 64 MiB, tek kapak en fazla 8 MiB. Çok büyük eski yedekler
  bu sınırlar nedeniyle içe aktarılamayabilir.
- Yedekteki yerel ses/cache yolları başka makinede geçerli olmayabilir;
  ses dosyaları bu JSON yedeğine gömülmez.
- “Beni hatırla” mevcut yerel davranışı korur. Bu uygulama işletim sistemi
  hesapları arasında güvenlik sınırı veya şifrelenmiş veri kasası değildir.

## Doğrulama

Testler geçici kullanıcı klasörleriyle, Qt offscreen modunda çalıştırıldı;
gerçek hesap veya kullanıcı dosyaları kullanılmadı. Spotify HTTP callback
kontrolü yerel test sunucusuyla; ağ indirmeleri ve VLC oynatma davranışları
sahte bağımlılıklarla sınandı. Ayrıntılı sonuçlar `VALIDATION.txt` dosyasında.

- Orijinal test tabanı: **48 test başarılı**. Son durumda **131 test başarılı**
  (83 ek regresyon senaryosu).
- Yeni regresyonlar: atomik yazma hatası, kapanış sırası, paylaşılan dosya
  koruması, yanlış yedek/sürüm/base64, credential taşınmaması, indirme
  girişimlerinin ayrılması, eski oynatma sonuçları, OAuth state ve
  dinleyici temizliği, sürüm karşılaştırması, veri yolları, çevrimdışı rozeti.
- Seçilmiş statik hata kontrolleri (`E9,F821,F822,F823`) ve Python derleme
  kontrolü uygulandı. Bu, tüm stil kurallarının temiz olduğu anlamına gelmez.
- Wheel/sdist üretimi ve wheel'in ayrı klasöre kurulup import edilmesi kontrol edildi.
- CI dosyası Linux/Windows ve Python 3.11/3.13 için eklendi; uzak GitHub
  çalıştırması yapılmadı.

**Doğrulanmayanlar:** Gerçek ses çıkışı, VLC'nin cihaz/sürücü davranışı,
Windows SMTC/global medya tuşları/tepsi, gerçek Spotify hesabı, YouTube
indirmeleri, uzun süreli crossfade dinleme ve PyInstaller EXE üretimi.
Bu sandbox üzerinde testlerin geçmesi bunların tamamının çalıştığı iddiası değildir.

## Kalan geliştirmeler — önerilen sıra

1. **Gerçek cihaz kabul testi:** Windows'ta VLC + FFmpeg + Node ile
   liste/arama/çalma/seek/indirme/iptal/geri al/yeniden başlatma akışları.
   SMTC, tepsi ve crossfade özellikle kontrol edilmeli.
2. **Gizli bilgi kasası ve PKCE:** Spotify secret/token değerleri hâlâ yerel
   ayarlar JSON'unda. OS keyring migrasyonu ve public-client PKCE akışı
   ayrı, uyumluluk testleri olan bir değişiklik olmalı.
3. **İşçi yaşam döngüsü:** İndirme kapatması iptal bayrağı ve sınırlı bekleme
   kullanır; ağ/FFmpeg hemen dönmeyebilir. Tüm arama/thumbnail/discovery
   işçileri için ortak iptal/timeout altyapısı ve uzun süreli stres testleri.
4. **Ayar şeması ve sürümlü migrasyon:** Bozuk ayar değerleri için tema,
   sayfa boyutu, EQ ve crossfade alanlarının tip/aralık doğrulaması;
   kullanıcı verisi formatına açık migrasyon sürümü.
5. **Model/view performansı:** Büyük kütüphanelerde her satır için QWidget
   yerine `QAbstractItemModel`/delegate; hedefli güncelleme ve ölçümlü
   bellek/latency bütçesi.
6. **Dağıtım:** Gerçek Windows EXE build, VLC/FFmpeg/Node varlık kontrolü,
   kaynak pakette olmayan görsellerin eklenmesi, imzalı sürüm dağıtımı.
7. **Yeni entegrasyonlar:** Last.fm scrobbling, metadata/ID3 ve gelişmiş
   arama; ancak kullanıcı ihtiyacı ve API kimlik bilgileri netleşince.

## Kullanım

1. `mustiefly_qt` kaynak klasörünü çıkarın; var olan kurulum üzerinde
   denemeden önce `users.json` ve `users/` klasörünü yedekleyin.
2. Kaynak kökünde `python -m pip install -e ".[dev]"` çalıştırın.
3. `python -m pytest -q` ile yerel testleri çalıştırın.
4. VLC kurulu, FFmpeg PATH üzerinde olacak şekilde `mustiefly` çalıştırın.
5. İsterseniz `MUSTIEFLY_DATA_DIR` ile ayrı bir test veri klasörü seçin.

ZIP içindeki `changes.patch` metin farklarını gösterir. Kaynak dosyalar zaten
bu farklar uygulanmış durumdadır; ZIP'e yamayı yeniden uygulamayın.

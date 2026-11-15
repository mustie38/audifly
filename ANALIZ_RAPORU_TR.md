# Audifly (iç ad: mustiefly_qt) — Analiz Raporu ve Son Durum

Sürüm 0.4.2 · 210 test geçiyor (başlangıçta 131; mevcut hiçbiri bozulmadı, yalnızca varsayılan veri klasörü adını denetleyen 2 test yeni adı bekleyecek şekilde güncellendi).

## 1. Başlangıç tespitleri ve sonuçları
| Alan | Bulgu | Durum |
|---|---|---|
| Ayar yazımı | Ayarlar penceresi ve ekolayzer atomik olmayan yazıyordu | ✅ Tek atomik yol |
| Spotify gizli bilgileri | `client_secret`/token düz metin JSON'da | ✅ Keyring (yoksa eski davranış); yedeğe girmez |
| Spotify OAuth | PKCE yoktu, secret zorunluydu | ✅ PKCE (S256); secret isteğe bağlı |
| Ayar şeması | Sürümsüz, doğrulamasız | ✅ `settings_version`, tip/aralık doğrulama, bozuk dosya karantinası |
| Kütüphane | Okunamayan dosya sonraki kayıtla ezilebiliyordu; bozuk dosya yedekleri döndürüyordu | ✅ Karantina + rotasyon koruması |
| Yedek içe aktarma | Yasaklı liste (bilinmeyen anahtar girebiliyordu) | ✅ İzin listesi |
| İndirme | İkinci (eski) indirme yolu | ✅ Kaldırıldı |
| Shuffle | Ön yükleme boşa gidiyordu | ✅ Sıradaki şarkı planlanıyor |
| Dinleme geçmişi | Yoktu | ✅ JSONL olay günlüğü |
| Uyku zamanlayıcısı | Sabit seçenekler, arayüzde | ✅ Servis; özel süre; kademeli fade |
| Akıllı listeler | 3 sabit liste | ✅ +Favori Sanatçılar, +Unutulanlar, +kullanıcı kuralları |
| Şarkı sözleri | Zaman damgası atılıyor, doğrulamasız eşleşme, hata=“yok” | ✅ Senkron LRC, doğrulamalı eşleşme, önbellek, durum ekranları |
| Keşfet | Arama sonucu sıralı liste gibi gösteriliyordu | ✅ Kaynak etiketi, dürüst sıra rozeti; ölü `explore.py` silindi |
| Mix / Wrapped | Yoktu | ✅ Yerel algoritma; Wrapped PNG |
| Tepsi | Simgeye ikon atanmamıştı | ✅ |
| Loglama | Girişten önce dosyaya yazılmıyordu | ✅ |
| Paketleme | İkon/sürüm yok, eksik hiddenimports | ✅ Linux'ta derleme+açılış doğrulandı |

## 2. DOĞRULANMADI (gerçek ortam gerekir)
Bunlar yalnızca Linux + sahte nesnelerle test edildi; **Windows'ta elle doğrulanmalı** (bkz. `DAGITIM_REHBERI_TR.md` §3):
- Gerçek ses/VLC oynatma, crossfade, fade-out'un kulakla doğrulanması.
- Windows Credential Manager (keyring), SMTC, medya tuşları, tepsi, Discord.
- Gerçek YouTube/Spotify/LRCLIB/YouTube Music çağrıları.
- **PyInstaller Windows EXE'si, Inno Setup kurulumu, temiz Windows testi, eski Mustiefly kurulumunun üzerine kurulum.**
- Arayüzün gerçek ekranda görünümü (yalnızca ekransız Qt'de oluşturuldu).

## 3. Bilinen açıklar ve riskler
- **yt-dlp** paketli EXE'de güncellenemez; YouTube bozulunca çalma durur (en büyük işletme riski). Çözüm önerisi `DAGITIM_REHBERI_TR.md` §4.
- Uygulama için otomatik güncelleme yok (yayın adresi belirsiz); kod imzası yok (SmartScreen uyarısı).
- YouTube indirme/çevrimdışı özelliği Hizmet Şartları açısından hukuki değerlendirme gerektirir (§5).
- Discord istemci kimliği kodda gömülü.
- Spotify yönlendirme portu 8888 sabit (çakışabilir).
- Büyük kütüphane performansı ölçülmedi; kitaplık satır başına `QWidget` kullanıyor (model/view geçişi ölçümle yapılmalı).
- Mix'ler yalnızca kütüphane içi; tür verisi yok ("tarz" = birlikte dinleme).
- Dinleme geçmişi yedeğe dahil değil (ayrı dosya); geçmiş bu sürümle başlıyor.
- Dosya yolları (`local_path`) yedekte kullanıcı adı sızdırabilir.

## 4. Yapılmayanlar (bilinçli)
Sanatçı profilleri, ruh haline göre keşif, sanatçı takibi, "yeni müzik keşif önerileri" (kütüphane dışı), model/view geçişi, iç paket adının `audifly` olarak değiştirilmesi (riskli/faydasız), uygulama otomatik güncelleme. Talimattaki "bir anda hepsini ekleme" kuralı gereği, kullanıcıya en çok katkı sağlayanlar önce yapıldı.

## 5. Dosya haritası (yeni/önemli)
`services/`: history_store, sleep_timer, smart_lists, mixes, wrapped · `helpers/`: lyrics, secrets_store, dependencies, diagnostics, brand_icon · `views/`: mixes_view, wrapped_view, smart_rules_dialog, lyrics_window (yeniden yazıldı) · `packaging/`: audifly.spec/.iss, make_icon.py, audifly.ico · `DAGITIM_REHBERI_TR.md`, `CHANGELOG.md`.

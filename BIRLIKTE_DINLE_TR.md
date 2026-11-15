# Birlikte Dinle — Kurulum

Arkadaşınla aynı şarkıyı aynı anda dinlemek için. Ses gönderilmez: ikiniz de uygulamayı kurarsınız, şarkıyı herkes kendi bilgisayarında YouTube'dan çalar. Sunucu sadece "hangi şarkı, çalıyor mu, kaçıncı saniye" bilgisini iletir.

## 1) Sunucuyu bir kez kur (ücretsiz)

`relay_server` klasörünü (server.py + requirements.txt) kendi GitHub deponuza yükleyin.

**Render.com (önerilen):**
1. render.com → New → Web Service → GitHub deponuzu seçin.
2. Root Directory: `relay_server` (klasörü ayrı depo yaptıysanız boş bırakın)
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python server.py`
5. Plan: Free. Bitince `https://adiniz.onrender.com` adresini alırsınız.

Not: Ücretsiz planda sunucu 15 dk kullanılmazsa uyur; ilk bağlantı 30-60 sn sürebilir (uygulama otomatik yeniden dener).

Kendi bilgisayarında denemek için: `pip install websockets`, `python relay_server/server.py`, adres `ws://localhost:8765`.

## 2) Uygulamada

1. **Araçlar → 👥 Birlikte Dinle…**
2. Sunucu alanına adresi yazın (`https://adiniz.onrender.com` yazsanız da olur).
3. Bir kişi **Yeni Oda Aç** der, çıkan kodu arkadaşına gönderir.
4. Arkadaşı kodu yazıp **Odaya Katıl** der.

## Kurallar
- Herkes şarkı seçebilir, duraklatabilir, sarabilir; herkeste aynı anda uygulanır.
- Şarkı bitince sıradakini **oda sahibi** (👑, ilk giren) seçer.
- Sonradan girene çalan şarkı ve konum otomatik gelir.
- Yerel ses dosyaları paylaşılamaz; yalnız YouTube vb. bağlantılı şarkılar.
- Şarkı sizde yoksa "🎧 Birlikte Dinle" listesine eklenir (silebilirsiniz).
- Kodu bilen herkes girebilir (en fazla 8 kişi); kodu sadece arkadaşlarına ver.

## Ek özellikler
- **Oda göstergesi:** Odadayken pencerenin sağ altında `👥 KOD · 2 kişi` düğmesi görünür; tıklayınca oda penceresi açılır. Okunmamış mesaj varsa 💬 sayısı çıkar.
- **Kim ne çaldı:** Biri şarkı değiştirince alt çubukta `🎵 Veli: şarkı adı` yazar.
- **Sohbet ve emoji:** Oda penceresinden mesaj yazın veya ❤️ 🔥 👏 😂 😍 🎉 👍 😭 gönderin.
- **Ortak sıra:** Herkes ekler. Bir şarkının ⋮ menüsünden **👥 Oda Kuyruğuna Ekle** deyin, ya da oda penceresinde **Çalan şarkıyı ekle**'ye basın. Şarkı bitince (veya biri ⏭'ye basınca) sıradaki şarkı önce ortak sıradan çalınır; sıra boşsa normal akış sürer.

**Önemli:** Bu sürümde sunucu da değişti. Render'daki `server.py` dosyasını GitHub'da yenisiyle değiştirin (Render otomatik yeniden yayınlar). Eski sunucu sohbet ve ortak sırayı bilmez; ikisi de çalışmaz ama çalma eşitleme bozulmaz.

## Altyapı iyileştirmeleri (v4)
- **Davet:** **Daveti Kopyala** `KOD@sunucu.onrender.com` biçiminde tek parça verir. Arkadaşın bunu "Oda kodu" kutusuna yapıştırıp katılır; sunucu adresi yazmasına gerek kalmaz.
- **Hazır sunucu adresi:** `services/listen_together.py` içindeki `DEFAULT_SERVER_URL = ""` satırına kendi adresini yaz (örn. `"wss://audifly-relay.onrender.com"`), uygulamayı yeniden paketle. Sunucu kutusu gizlenir, herkes sadece oda kodu yazar.
- **Oda şifresi:** Odayı açan şifreyi belirler; girenler aynı şifreyi yazmak zorundadır. Düz şifre sunucuya gitmez (oda koduyla tuzlanmış özet gider). Şifreli odada 🔒 görünür.
- **Sahipliği devret:** Oda sahibi, listeden birini seçip 👑 devredebilir. Sahip çıkarsa ilk kalan sahip olur.
- **Sunucu uyuyorsa:** Pencere açılınca sunucu önceden uyandırılır. Bağlantı gecikirse "Sunucu uyanıyor olabilir…" yazar ve en kötü durumda yaklaşık 3 dakika boyunca otomatik dener.
- **Uyutmamak istersen:** Render ücretsiz plan 15 dk istek gelmezse uyur. Bir ücretsiz "ping" servisi (örn. UptimeRobot) ile `https://adin.onrender.com/health` adresini 5 dk'da bir çağırırsan uyumaz. Render'ın ücretsiz saati ayda 750 saat; tek servis için yeter, ama aynı hesapta başka ücretsiz servisin varsa aşabilir.
- **Eşitleme:** Uygulama bağlantı gecikmesini ölçer (oda penceresinde "gecikme ~X ms") ve konuma ekler. Misafirde **🔄 Eşitle** düğmesi oda sahibinden anlık konum ister. Yeni şarkı açılınca otomatik bir kez eşitler.
- **Güncelleme:** Sunucu dosyası değişti. GitHub'daki `server.py` dosyasını yenisiyle değiştirin; herkesin uygulama sürümü de aynı olmalı.

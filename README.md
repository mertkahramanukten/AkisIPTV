# Akış IPTV

[![Son sürüm](https://img.shields.io/github/v/release/mertkahramanukten/AkisIPTV?label=indir)](https://github.com/mertkahramanukten/AkisIPTV/releases/latest)

Windows için **donmamaya odaklı** Xtream Codes IPTV oynatıcısı.
Sunucu adresi + kullanıcı adı + parola ile bağlanır; Canlı TV, Filmler, Diziler ve EPG (yayın akışı) içerir.

- Arayüz: PySide6 (Qt 6)
- Video motoru: libmpv (mpv'nin kütüphanesi — VLC'den daha ince buffer/ağ kontrolü)

---

## Kurulum (kullanıcı)

1. [Releases](https://github.com/mertkahramanukten/AkisIPTV/releases/latest) sayfasından **`AkisIPTV-Setup-x.y.z.exe`** dosyasını indir. Python vb. hiçbir şey gerekmez.
2. Çift tıkla, sihirbazı takip et. Yönetici izni istemez (istersen "tüm kullanıcılar için" de kurabilirsin).
3. Windows *"Bilgisayarınız korundu"* uyarısı verirse: **Ek bilgi → Yine de çalıştır**. (Uygulama dijital imzalı olmadığı için çıkar; normaldir.)
4. Başlat menüsünden **Akış IPTV**'yi aç; sunucu adresini (`http://sunucu.com:8080`), kullanıcı adını ve parolayı gir.
   Elinde sadece M3U linki varsa (`.../get.php?username=...&password=...`) sunucu kutusuna yapıştır; bilgiler otomatik ayıklanır.

Ayarlar ve kayıtlı profiller `%APPDATA%\AkisIPTV` içinde tutulur. Kaldırırken bunların da silinip silinmeyeceği sorulur.

---

## Geliştirme

1. Python 3.10+ kurulu olsun. `setup.bat` → sanal ortam, kütüphaneler ve `libmpv-2.dll` (otomatik indirilir, `bin\` klasörüne).
2. `run.bat` ile başlat. Gerçek sağlayıcına dokunmadan denemek için: `demo.bat` → "Bağlan".

| Dosya | Ne yapar |
|---|---|
| `setup.bat` | Geliştirme ortamını kurar |
| `run.bat` | Uygulamayı kaynak koddan başlatır (konsolsuz) |
| `run_debug.bat` | Konsol penceresiyle başlatır (sorun ararken) |
| `demo.bat` | Sahte Xtream sunucusuyla başlatır |
| `mock_server.bat` | Sadece sahte sunucuyu açar (kurulu uygulamayı denemek için: `http://127.0.0.1:8899`, demo/demo) |
| `test.bat` | Testleri çalıştırır |
| `build_installer.bat` | **Tek dosyalık kurulum** üretir: `dist\AkisIPTV-Setup-x.y.z.exe` |

### Yeni sürüm yayınlama

1. `akis/__init__.py` içindeki `__version__` değerini artır (ör. `1.1.0`).
2. `build_installer.bat` → `dist\AkisIPTV-Setup-1.1.0.exe` oluşur. Inno Setup kurulu değilse betik derleyicinin
   taşınabilir halini `build\` altına indirir (bilgisayara bir şey kurmaz).
3. Değişiklikleri gönder ve GitHub'da **Releases → Draft a new release** ile `v1.1.0` etiketine Setup.exe'yi ekle.

**Otomatik derleme (isteğe bağlı):** `docs/ci/` içindeki iki dosyayı GitHub'da `.github/workflows/` klasörüne
koyarsan her push'ta testler çalışır, her `v*` etiketinde Setup.exe Windows'ta derlenip Release'e otomatik eklenir.

---

## Donma ve açılmama sorununa karşı neler var?

IPTV'de takılmanın 5 yaygın sebebi var; her birine ayrı bir katman bakıyor:

| Sebep | Belirti | Akış'taki çözüm |
|---|---|---|
| Ağdaki anlık dalgalanma | Saniyelik takılma, sürekli "dön-dur" | **Büyük demuxer cache** + `cache-pause-wait`: takılınca birkaç saniye biriktirip öyle devam eder, 0.2 sn oynat/dur döngüsüne girmez |
| Sık tekrarlayan takılma | Dakikada birkaç kez buffer | **Adaptif buffer**: 2 dakikada 2 takılma görürse buffer'ı kendiliğinden büyütür (1 → 2.5 → 4 → 6 → 9 sn) |
| Bağlantı kopması | Görüntü donar ya da yayın kapanır | 1) ffmpeg seviyesinde anında `reconnect`, 2) **StreamGuard**: zaman ilerlemiyorsa 8 sn'de, veri gelmiyorsa 10 sn'de bağlantıyı yeniler; artan bekleme süreleriyle 8 kez dener. Filmde kaldığı saniyeden devam eder |
| Format uyumsuzluğu | Kanal hiç açılmıyor ya da sürekli kopuyor | **TS ↔ HLS otomatik geçiş**: aynı formatta 2 hata → diğer formatı dener. Hangisinin daha stabil olduğunu öğrenir ve sonraki açılışlarda onunla başlar |
| **Bağlantı limiti** (1 ekranlı hesaplar) | Kanal değiştirince "açılmıyor", birkaç denemede açılıyor | Kanal değişirken önce eski bağlantı kapatılır, sunucuya 350 ms nefes payı verilir, sonra yenisi açılır. Hızlı zaplamada sadece son seçilen kanal açılır. 403/509 hatasında daha uzun beklenir |
| CPU kaynaklı kasma | Ses akıyor ama görüntü kasıyor | Donanımsal çözme (GPU, `hwdec=auto-safe`) |
| Sağlayıcının uygulama engeli | Hiçbir kanal açılmıyor, VLC'de açılıyor | User-Agent varsayılan olarak VLC; Ayarlar'dan değiştirilebilir |

Ayrıca:
- **Yayın sağlığı paneli** (`I` tuşu): buffer süresi, indirme hızı, bitrate, çözünürlük, kopma/takılma sayısı canlı olarak video üzerinde.
- **Canlıda geri sarma**: ← / → ile son birkaç dakikada 10 sn geri/ileri; `Home` canlıya döner.
- Liste yüklemesi: önbellekten **anında** gösterilir, güncel liste arkada iner. Sunucu tüm listeyi tek seferde veremezse kategori kategori indirilir. 50.000+ kanalda da liste akıcıdır (sanal liste).

### Hâlâ takılıyorsa ne denemeli?

1. **Ayarlar → Buffer profili → Sağlam** (zayıf/dalgalı internet için).
2. **Ayarlar → Canlı yayın formatı → HLS** (bazı sağlayıcılarda HLS çok daha stabil).
3. `I` ile sağlık panelini aç: *İndirme hızı* video bitrate'inin altındaysa sorun hattında ya da sağlayıcıda; uygulama tarafında yapılabilecek tek şey buffer'ı büyütmek.
4. Wi-Fi yerine kablo dene.
5. Kanallar hiç açılmıyorsa Ayarlar'dan farklı bir **User-Agent** seç.
6. Log dosyası: `%APPDATA%\AkisIPTV\logs\akis.log` (kaynak koddan çalışırken `data\logs\akis.log`). Parola ve kullanıcı adı loglara yazılmaz.

---

## Kısayollar

| Tuş | İşlev |
|---|---|
| Kanala tıkla | Oynat |
| `F` / `F11` / çift tık | Tam ekran |
| `Esc` | Tam ekrandan çık / aramayı temizle / otomatik sonraki bölümü iptal |
| `Boşluk` | Duraklat / devam |
| `PgUp` / `PgDn` (videodayken `↑` / `↓`) | Önceki / sonraki kanal |
| Rakamlar | Kanal numarasıyla geçiş (TV kumandası gibi) |
| `←` / `→` (videodayken), `Ctrl+←/→` | 10 sn geri / ileri |
| `Home` | Canlıya dön |
| `+` / `-` / fare tekerleği | Ses |
| `M` | Sessiz |
| `I` | Yayın sağlığı paneli |
| `S` | Ekran görüntüsü (masaüstüne) |
| `A` | Ses parçası değiştir |
| `F5` | Yeniden bağlan |
| Video üzerinde sağ tık | Ses parçası, altyazı, görüntü oranı |
| `Ctrl+F` | Ara (Türkçe karakter duyarsız: "sinema" → "SİNEMA") |

---

## Proje yapısı

```
akis/
  xtream.py        Xtream API istemcisi (retry/backoff, zaman aşımları, bozuk yanıt toleransı)
  guard.py         StreamGuard: donma/kopma tespiti ve kurtarma durum makinesi (saf Python, test edilebilir)
  player.py        libmpv entegrasyonu, buffer ayarları, sağlık paneli
  library.py       Katalog: önbellek + arka planda tazeleme + kategori bazlı yedek indirme
  epg.py           Kısa EPG + akış halinde XMLTV ayrıştırma (dev dosyalarda bile düşük bellek)
  cache.py         gzip'li JSON disk önbelleği
  images.py        Logo/afiş yükleyici (disk + bellek önbelleği)
  config.py        Ayarlar, profiller, parola saklama (Windows DPAPI ile şifreli)
  workers.py       Arka plan işleri (arayüz hiç bloklanmaz)
  ui/              Pencereler, paneller, liste modelleri ve çizim
tests/
  mock_server.py   Sahte Xtream sunucusu (sorunlu kanal senaryolarıyla)
  test_guard.py    StreamGuard senaryo testleri
  test_xtream.py   API, önbellek, EPG testleri
tools/get_libmpv.py      libmpv indirici
tools/build_installer.py PyInstaller + Inno Setup ile tek dosyalık kurulum
installer/akis.iss       Türkçe kurulum sihirbazı tanımı
docs/ci/                 GitHub Actions iş akışları (testler + otomatik Release)
github_yayinla.bat       Kodu GitHub'a gönderir ve sürüm sayfasını açar
```

### Sahte sunucunun test kanalları ("🧪 Test: Sorunlu Kanallar")

| ID | Senaryo | Beklenen davranış |
|---|---|---|
| 9001 | 20 sn'de bir bağlantı kopar | Otomatik yeniden bağlanır |
| 9002 | 15 sn sonra veri kesilir, bağlantı açık kalır | "Veri gelmiyor" → yenilenir |
| 9003 | 404 | 2 denemeden sonra "Kanal yayında değil" |
| 9004 | İlk byte 6 sn sonra gelir | Sabırla açılır |
| 9005 | TS 404, HLS çalışır | Otomatik HLS'e geçer |
| 9006 | Yayın hızının altında veri | Takılmalar → buffer otomatik büyür |

Sahte sunucu varsayılan olarak **1 bağlantı limitiyle** çalışır; hızlı kanal değiştirmenin limiti aşmadığını da test eder.
Tek başına: `.venv\Scripts\python tests\mock_server.py --channels 20000` (büyük liste performansı için).

---

## Gizlilik

- Parolalar ayar dosyasında (`%APPDATA%\AkisIPTV\settings.json`, kaynak koddan çalışırken `data\settings.json`) **Windows DPAPI** ile şifrelenir (yalnızca senin Windows hesabın çözebilir).
- Loglarda yayın adreslerindeki kullanıcı adı/parola `***` ile maskelenir.
- `data\` ve `bin\` klasörleri `.gitignore`'da; GitHub'a gönderilmez.

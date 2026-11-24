# Sürüm notları

## 1.2.0 — 24 Kasım 2026

### Yeni
- **Otomatik güncelleme:** Akış açılışta GitHub'daki son sürüme bakar. Yeni sürüm varsa yeniliklerle birlikte sorar;
  *Şimdi güncelle* deyince kurulum dosyasını indirir (ilerleme çubuğuyla), sessizce kurar ve kendini yeniden açar.
  *Bu sürümü atla* ile o sürüm bir daha sorulmaz.
- Ayarlar → **Güncelleme:** açılışta kontrolü açıp kapatma ve *Şimdi kontrol et* düğmesi.
- Güncellemeden sonraki ilk açılışta "Akış X sürümüne güncellendi ✓" bildirimi.

> Not: Otomatik güncelleme 1.2.0 ile geliyor; 1.1.0'dan 1.2.0'a bir kez elle (Setup.exe ile) geçmek gerekiyor.

## 1.1.0 — 24 Kasım 2026

### Yeni
- **Esnek görünüm:** Sol paneller (`Ctrl+B`) ve alt bilgi paneli (`Ctrl+J`) ayrı ayrı açılıp kapanıyor.
  **Sinema modu** (`T`) pencerede yalnızca videoyu bırakıyor, pencere istediğin gibi boyutlanabiliyor.
  Seçilen görünüm sonraki açılışta hatırlanıyor. Hepsi oynatıcı çubuğundaki yeni **Görünüm** butonunda.
- **Üstte tut (pin):** `P` ya da raptiye butonu videoyu tüm pencerelerin üzerinde tutuyor. Windows'ta pencere
  yeniden oluşturulmadan yapılıyor, bu yüzden yayın kesilmiyor.
- **Mini oynatıcı:** `Ctrl+M` ile pencere küçülüp ekranın sağ alt köşesine geçiyor ve üstte kalıyor.
  Çift tık ya da `Esc` eski boyuta ve yere döndürüyor.
- **Önceki kanala dönüş:** Kanal değişince eski kanal, son karesinin küçük resmiyle çubukta duruyor.
  `Tab` / `Backspace` ile iki kanal arasında gidip gelinebiliyor.
- **Nöbetçi kanal:** Kanala sağ tık → *Nöbete al*. Program rehberinde yeni program başlayınca bildirim
  çıkıyor ve görev çubuğu simgesi yanıp sönüyor; `N` o kanalı açıyor. Yayın açılmadığı için bağlantı harcamıyor.
- **Çoklu izleme:** Kanala sağ tık → *Çoklu izlemeye ekle*. Ekran 1×2 / 2×2 bölünüyor, ses tek karede çalıyor
  (kareye sağ tık → sesi buraya al / ana ekrana al / kapat). Açılabilecek kare sayısı hesabın bağlantı
  limitine göre belirleniyor; limit 1 ise özellik açıklamayla kapalı kalıyor.
- **İzleme geçmişini silme:** "Son izlenenler"e sağ tık → listeyi temizle; kanala sağ tık → tek tek kaldır;
  Ayarlar → *İzleme geçmişini sil* ile hepsi (onay sorar).

### Düzeltmeler
- Mini oynatıcı geniş ekranlarda kenardan taşmıyor; pencerenin gerçek boyutuna göre yerleşiyor.
- Tam ekrandan çıkınca panel boyutları ve pin durumu korunuyor.

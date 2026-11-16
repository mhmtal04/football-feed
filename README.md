# Futbol botu – otomatik açık sayfa fikstür toplayıcı

Bu depo, Nesine ve Maçkolik'in herkese açık futbol sayfalarını Playwright ile taramayı dener. Giriş yapmaz, hesap/cookie/özel endpoint kullanmaz ve bahis işlemi yapmaz. 30 dakikada bir GitHub Actions çalışır; sonuç `public/external-matches.json` dosyasına yazılır.

## Kurulum
1. GitHub'da boş bir repository oluştur (ör. `football-feed`).
2. Bu klasördeki dosyaları repository'nin köküne yükle.
3. Repository > Actions sekmesinde workflow çalıştırmaya izin ver.
4. Actions > Update football fixtures > Run workflow ile ilk testi başlat.
5. `public/scrape-status.json` dosyasında her sitenin HTTP durumunu ve bulunan maç sayısını kontrol et.
6. `public/external-matches.json` dosyası doluysa feed adresin: `https://raw.githubusercontent.com/KULLANICI_ADI/REPO_ADI/main/public/external-matches.json`

## Önemli teknik sınırlar
- Siteler DOM, erişim koruması, bot engeli veya içerik yükleme yöntemini değiştirebilir. Bu nedenle scraper en iyi çaba yaklaşımıdır; her maçın bulunmasını garanti etmez.
- Bazı sayfalar sadece bugünün bültenini gösterir. Tarih aralığının tamamını taradığı varsayılmamalıdır.
- Kod yalnızca sayfada görünen metni ve tablo satırlarını okur. Site engeli aşmaya, giriş yapmaya veya gizli/özel servislere erişmeye çalışmaz.
- Bilinmeyen lig etiketi `OTHER` olarak bırakılır ve ana uygulamaya aktarılmaz.
- GitHub Actions ücretsiz kullanım kotasına tabidir. 30 dakikalık schedule GitHub yoğunluğunda gecikebilir.

## Sorun giderme
Actions logunda HTTP 403/429 veya timeout görünürse ilgili site otomatik taramayı engelliyor olabilir. Bu durumda o kaynakta veri yokmuş gibi davranmayın; `scrape-status.json` dosyasındaki uyarıyı kontrol edin.

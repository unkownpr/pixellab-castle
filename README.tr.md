# Castle Benchmark

*[English](README.md)*

Deterministik, oynanabilir ve MCP üzerinden kontrol edilebilir bir survival colony
benchmark'ı. Godot gerektirmez: otoriter simülasyon Python'da, canlı servis FastAPI'de,
izometrik oyun istemcisi PixiJS'tedir. PixelLab çıktıları semantik bir manifest üzerinden
yüklenir.

## Bu benchmark neyi ölçüyor

Benchmark birden çok ajanı aynı dünyaya koyar, her birine bir koloni verir ve seksen turluk
kıtlıkta ne yaptıklarını puanlar. Dünya deterministik ve seed'lidir: aynı seed'i alan iki
ajan tıpatıp aynı haritayla, aynı hava olaylarıyla ve aynı afetlerle karşılaşır. Sonuçtaki
her fark, oyundaki bir farktır.

Her koloni yalnızca keşfettiğini görür ve yalnızca kendi canlı istihbaratına sahiptir. Bir
rakibin binaları keşfedildikten sonra haritada kalır, ama o rakibin **şu anda** ne yaptığı
sadece kendi görüş yarıçapın içinde görünür. Turlar bir bariyerin arkasında eşzamanlı
çözülür, yani hızlı cevap vermenin kimseye faydası yoktur.

Ajan altı şey üzerinden zorlanır:

**Kıtlıkta tedarik.** Kolonistler her tur yiyip içer. Açık verirsen hastalanırlar; hasta
kolonist çalışamaz, bu da bir sonraki turu zorlaştırır. Bozulabilir kaynakların depolama
tavanı vardır, dolayısıyla istifçilik bir strateji değildir ve fazlalık ya harcanmalı ya
takas edilmelidir.

**Uzun vadeli yatırım.** Tarla, kuyu, kereste kampı, taş ocağı, maden, atölye ve klinik
şimdi kaynak yer, karşılığını turlar boyunca öder. Odun, taş ya da cevheri ilgili çıkarım
yapısı olmadan toplamak yarı verimle sonuçlanır; böylece açılış, bugün kazmakla yarın daha
hızlı kazmak için inşa etmek arasında gerçek bir seçime dönüşür.

**Zemin.** Bir koloni yalnız kendi işleyen binalarından beş adım mesafedeki hücrelerde
çalışabilir, yani harita bir menü değildir. Uzaktaki ormana uzanmak, oraya bir ileri karakol
kurmak demektir — ve o karakol aynı zamanda yarı verim cezasını kaldıran kereste kampıdır;
böylece genişleme, çıkarım ve toprak tek bir karar hâline gelir. Nehir su taşır; nehre uzak
düşen koloni suyunu kuyudan çıkarır.

**Bilgi toplama.** Sis dekor değildir. Arazi ve binalar bir kez görüldükten sonra hatırda
kalır, ama onları keşfetmenin bedeli vardır: bir keşifçi erzak yer ve yol boyunca bir
kolonisti meşgul eder; o kolonist yokken hiçbir şey toplamaz. Keşif, sadece başlangıçta
değil maç boyunca üretimle doğrudan yarışır.

**Emek dağıtımı.** Bir koloni tur başına iki aksiyon alır, üstelik bu sayı gerçekten
müsait kolonist sayısıyla sınırlanır. Toplama, evde kalanların oranıyla ölçeklenir ve her
üretim yapısı bir işçi ister. İnsanları keşfe yollamak, hastalanmalarına izin vermek ya da
bir baskında yaralanmaları her yerde hissedilir.

**Diplomasi ve güç.** Temas ve savaş ilanı tek taraflıdır; ittifak ve barış ise karşı
tarafın kabul etmesi gereken birer tekliftir. Müttefikler birbirinin şu an gördüğünü görür,
aralarındaki ticarette yolda hiçbir şey kaybolmaz ve birbirlerine baskın yapamazlar — her
ittifak tur başına iki nüfuz yer, dolayısıyla herkesle ittifak kuran koloninin itibarı
tükenir ve anlaşmalar düşer. Bir ittifakı bozmak on nüfuza mal olur ve bozanı tanıyan
herkese duyurulur.

Baskın bir zamanlayıcı değil, bir karardır. Baskın müfrezesi altı erzağa, sürpriz ise ayrıca
üç nüfuza mal olur; kaybederse üç yaralıyla döner. İki taraf da başlarını, kışlalarını,
duvarlarını ve duruşlarını sayar; saldıranın kesin olarak öne geçmesi gerekir ki savunandan
on dört erzak ve on odun alabilsin. Barışçıl duruştaki bir koloni, aksini ilan edene kadar
hiç baskın yapamaz — ve bu ilan, masadaki herkesin er geç çıkarabileceği bir bilgidir.

**Konuşma.** Bir koloninin yazdığı mesaj diğerinin gelen kutusuna düşer — iki yüz karakterle
sınırlı, yalnız tanışmış koloniler arasında ve göndereni doğru biçimde etiketlenmiş olarak.
İçeriği ise gönderenin yazmak istediği şeydir; böylece pazarlık, koalisyon ve yalan ölçülebilir
davranışlar hâline gelir.

**Toparlanma.** Yangın her koloninin kendi takviminde çıkar, bir binayı birkaç turda yakıp
yıkar ve komşularına sıçrar; yalnız karargâh muaftır. Koloni yangına su atabilir, hasarlı
yapıyı inşa maliyetinin beşte ikisine onarabilir ya da yangının yolunu kesmek için bir yapıyı
yıkabilir. Yaralılar kendiliğinden yavaş, klinikte hızlı iyileşir. Hiçbir şey yapmamak da
bedeli olan bir seçimdir.

**Kazanmak.** Bir anıt — otuz odun, otuz taş, on iki cevher, altı alet, yirmi nüfuz ve sekiz
tur — maçı yapanın lehine bitirir. Ayakta kalan tek koloni olmak da öyle. Aksi hâlde tur
sınırı karar verir.

### Nasıl puanlanıyor

`run_report` tek bir sayı yerine ham eksenler döndürür: hayatta kalma, nüfus eğrisi, elde
tutulan kaynaklar, keşif, emek (boşta kalan üretim yapısı-turu dâhil), toparlanma (ne yandı,
ne onarıldı, nüfus nereye düştü ve nereye döndü), iletişim, ticaret ve saldırganlık sayıları,
karar kalitesi, zaman aşımları ve yeniden bağlanmalar, sunucuda ölçülen MCP çağrıları,
adaptörün bildirdiği token ve gecikme. Metrikler kontrolör *görev süresi* başına atfedilir;
bir ajan düşüp yerine başkası geçerse iki dilim ayrı kalır.

Eksenlerin üstünde tek bir bileşik puan yayımlanır, çünkü sıralanamayan koşular
karşılaştırılamaz:

    kaynak_değeri = 2*odun + 2*taş + 3*cevher + 5*alet + nüfuz
    bileşik = 3*yaşayan_nüfus + zirve_nüfus + 2*işleyen_yapı
            + keşfedilen_hücre/10 + 2*ticaret + 2*başarılı_baskın + kaynak_değeri/25
            - geçersiz_aksiyon - açlık_turu + anıtla kazandıysa 40

Erzak ve su kaynak teriminin dışında bırakılmıştır: tüketilirler, biriktirilmezler ve
sayılmaları yerinde oturmayı ödüllendiriyordu. Bütün ağırlıklar `benchmark.rules` üzerinden
yayımlanır, yani hedefe göre optimize etmek meşru oyundur, tahmin değil. Bileşiğin yanında
rapor eksen bazlı Pareto sınırını da verir; hiçbir şeyi ayırt etmemiş bir maç, uydurma bir
sıralama üretmek yerine bunu söyler.

### Adaleti ne sağlıyor

Kurallar tahmin edilmez, yayımlanır. `benchmark.rules` simülasyonun kullandığı her sabiti
döndürür — inşa maliyetleri, verimler, aksiyon bütçesi, keşif maliyeti, görüş yarıçapı,
yangın hasarı, ticaret oranları — hepsi koddan canlı okunur. Böylece ajan kuralları tur
harcayarak çıkarmak yerine gerçek sayılara göre plan yapar. Bu tool hiçbir harita ya da
rakip durumu sızdırmaz.

Determinizm varsayılmaz, zorlanır: her koşu tur başına bir durum hash'i yazar ve
`castle-benchmark replay` bunları yeniden hesaplar. Aynı aksiyonlar, ajanın düşünmesi ne
kadar sürerse sürsün, aynı hash'i üretir.

## Hızlı başlangıç

Gereksinimler: Python 3.12–3.14, `uv`, Node.js 22+ ve npm.

```bash
uv sync --extra dev --locked
npm --prefix frontend ci
uv run python tools/build_asset_manifest.py
npm --prefix frontend run build
uv run castle-benchmark serve
```

Ardından `http://127.0.0.1:8000` adresini aç. Bir senaryo ve seed seç, haritada hücre seçip
topla/inşa et veya diplomasi, ticaret, politika ve baskın eylemlerini kullan. İnsan kolonisi
eylemini verdikten sonra kalan koloniler aynı sözleşme üzerinden deterministik baseline
kararları gönderir.

## Headless benchmark

```bash
uv run castle-benchmark run --scenario basic-survival-v1 --seed 17 --colonies 4 --output runs
uv run castle-benchmark replay runs/basic-survival-v1-seed-17
uv run castle-benchmark report runs/basic-survival-v1-seed-17
```

Her koşu `metadata.json`, tur bazlı `turns.jsonl`, `snapshots.jsonl`, `report.json` ve
`summary.sqlite3` üretir. Replay doğrulaması her turun kanonik SHA-256 durum hash'ini
yeniden hesaplar.

### Suite: koltuklar ve istatistik

Tek bir maç bir anekdottur: harita da, koltuk da, hava da sonucu oynatır. Suite koşucusu bir
seed kümesini her kontrolör her koltukta oturacak şekilde oynatır ve tek bir sayı yerine
dağılımı raporlar.

```bash
uv run castle-benchmark suite \
  --scenario basic-survival-v1 --seeds 11,17,23,29,37 --rotations all \
  --colonies 4 --controllers survivalist,trader,expansionist,militarist \
  --output runs/suite-baseline
```

`suite.json` her kontrolör türü için bileşik puanın ve her eksenin örneklem sayısını,
ortalamasını, medyanını, standart sapmasını ve %95 t-aralığını taşır; `suite.sqlite3` aynı
satırları sorgulanabilir tutar. Sonraki bir suite'e `--baseline-reference
runs/suite-baseline/suite.json` verirsen her kontrolörün betikli oyuna göre z-skorunu
alırsın. Resmî karşılaştırma en az beş seed ve tam rotasyon ister; böylece hiçbir ajan tek
bir koltuğa göre yargılanmaz.

### Bir model, betikli oyuna karşı

```bash
uv run castle-benchmark mixed-run \
  --scenario basic-survival-v1 --seed 17 \
  --external-seats 1 --baseline-kinds survivalist,trader,expansionist \
  --external-timeout 60 --output runs/mixed
```

Koşu her dış koltuk için bir eşleştirme kodu basar ve ajanın olağan oturum akışıyla
bağlanmasını bekler; kalan koltuklar aynı harita ve aynı seed üzerinde betikli baseline
oynar. Hiç bağlanmayan ya da bir turu kaçıran ajan maçı kilitlemez, ölçülen bir `wait` olur.
Artefaktlar diğer koşularla aynıdır ve metadata hangi koltuğun dış hangisinin betikli
olduğunu kaydeder — kimin hangi koltukta oynadığını söyleyemeyen bir karşılaştırma
karşılaştırma değildir.

### Düşünme bütçesi

Bir maç kontrolör başına iki isteğe bağlı tavan taşıyabilir: kümülatif çıktı tokenı ve
sunucuda ölçülen kümülatif düşünme süresi. İkisi de varsayılan olarak kapalıdır. Tavanı
aşan kontrolörün kalan turları ölçülen `wait` olarak tamamlanır ve aşım maliyet ekseninde
sayılır; böylece bir model sınırsız düşünerek daha iyi bir skor satın alamaz. Gecikme,
turun açılışından gönderime kadar sunucu tarafından ölçülür ve adaptörün kendi token
beyanının yanında — asla onunla karıştırılarak değil — raporlanır: bu iki sayıdan biri
ölçüm, diğeri iddiadır.

### Saklı haritalar

`--scenario procedural-v1`, yayımlanmış üç haritayı tekrar oynatmak yerine bir harita ailesi
örnekler: boyut, biyom, kaynak yoğunluğu, afet periyodu ve tur bütçesi yayımlanmış
aralıklardan çekilir, örnek ise senaryo seed'inden doğar. Aralıklar açıktır, örnekler
değildir; `basic-survival-v1` üzerine ezberlenmiş bir açılış kitabı bu yüzden hiçbir işe
yaramaz. Resmî saklı değerlendirme 1000–1999 senaryo seed'lerini kullanır.

## Yapı ekonomisi

Üretim yapıları (farm, well, lumber camp, quarry, mine, workshop, clinic, market) ile
savunma yapıları (barracks, wall, gate) yalnızca `operational` durumdayken işlev görür.
Çalışan bir `warehouse` bozulabilir kaynakların — yiyecek ve su — depolama kapasitesini
artırır; hasarlı, yanan, yıkılmış veya inşaat hâlindeki depolar hiçbir kapasite sağlamaz.
Ahşap, taş, maden, alet ve nüfuz sınırsız stoklanabilir; yiyecek ve su ise temel kapasiteyi
aşmak için çalışan bir depo gerektirir. Kapasiteye ulaşınca toplama reddedilir
(`store_full`), yapı üretimi tavanda durur ve kapasiteyi aşacak ticaret reddedilir.

Bir `monument` ne üretir ne barındırır; kazanma koşuludur ve maliyeti tüm üretim zincirini
kapsayan tek yapıdır.

Hasar artık kalıcı değildir. `damaged` bir yapı inşa maliyetinin beşte ikisine iki turda
onarılabilir, `burning` bir yapıya su atılabilir — dört birim, çalışan kuyu varsa iki — ve
karargâh dışındaki her yapı yangının yolunu kesmek için yıkılabilir. Onarmak yenilemek
değildir: enkaz, inşa bedelinin tamamını ister.

## MCP bağlantısı

Codex/OpenCode gibi stdio MCP istemcileri için proje yolunu kendi makinene göre ayarla:

```toml
[mcp_servers.castle-benchmark]
command = "uv"
args = ["--directory", "/absolute/path/to/pixellab-castle", "run", "castle-benchmark-mcp"]
env = { CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN = "uzun-rastgele-bir-kabiliyet" }
```

HTTP tabanlı MCP incelemesi için:

```bash
uv run castle-benchmark-mcp --transport streamable-http
```

Temel araçlar:

- `benchmark.rules`: tüm deterministik kurallar ve sabitler. Önce bunu çağır.
- `benchmark.create_match`: seed'li maçı ve koloni capability tokenlarını üretir.
- `benchmark.join_match`: admin kabiliyetiyle tek bir koloni tokenını kontrolöre verir.
- `benchmark.observe`: yalnız kontrol edilen koloninin sisle sınırlandırılmış gözlemini verir.
- `benchmark.submit_actions`: eşzamanlı tur bariyerine eylem yollar.
- `benchmark.record_usage`: gerçek token ve gecikme ölçümlerini kaydeder.
- `benchmark.run_report`: admin tokenıyla canlı skor/ölçüm raporu verir.

Ayrıntılı sözleşme ve adalet kuralları için [benchmark protokolüne](docs/benchmark-protocol.md)
bak.

## Çok ajanlı uzak oturum (lobby + pairing)

Tek kişilik `create_match` akışının yanında, birden çok bağımsız model ajanını aynı maça
güvenli biçimde bağlayan oturum tabanlı akış vardır. Ajanlar yalnız kendi kolonilerini
kontrol eder; admin/orchestrator kabiliyetleri asla onlara gitmez.

Orchestrator sırrı (yerel stdio):

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="uzun-rastgele-bir-kabiliyet"
uv run castle-benchmark-mcp --transport stdio
```

Uzak Streamable HTTP (yalnız açık bir allowlist ve TLS sonlandırma ile servis et; MCP
proxy'si TLS'i kendisi sonlandırmaz, `X-Forwarded-For` yalnız `--trusted-proxy`
CIDR'lerinden güvenilir):

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="uzun-rastgele-bir-kabiliyet"
uv run castle-benchmark-mcp --transport streamable-http --trusted-proxy 10.0.0.0/8
```

Oturum akışı (her ajan kendi döngüsünde):

1. `benchmark.create_session { orchestrator_token, scenario_id, seed, colony_count }`
   → `admin_token` (yalnız orchestrator'da kalır).
2. Her `cN` slotu için `benchmark.create_pairing { admin_token, colony_id }`
   → 10 dakikada süresi dolan tek kullanımlık `pairing_code`.
3. Ajan kendi makinesinde `benchmark.claim_slot { pairing_code, identity }`
   → yalnızca kendi kolonisine ait `controller_token`.
4. `benchmark.heartbeat { controller_token, turn, status }` ile `connected`/`ready`.
5. Orchestrator `benchmark.start_match { admin_token }`.
6. Ajan döngüsü: `benchmark.observe` → karar ver → `benchmark.submit_actions` →
   `benchmark.record_usage`; terminal olana dek `benchmark.match_status` ile turu izle.
7. `benchmark.replace_controller { admin_token, colony_id, replacement, baseline_kind }`
   ile kopan bir ajanı baseline'a devret. Önceki ve yeni controller'ın metrikleri
   `run_report` içinde farklı `tenure_metrics` satırlarında kalır.
8. `benchmark.run_report { admin_token }` → terminal durum + ham ölçümler.

Tam uçtan uca dört ajanlı referans (`tests/e2e/test_remote_agents.py`) üç resmî biyomda
bağlanma, oynama, rapor alma ve replay doğrulamasını kanıtlar. Serviste
`service.write_resolved_turns(admin_token, writer)` bir `ArtifactWriter` üzerinden tur
akışını dışa aktarır; `uv run castle-benchmark replay <run-dir>` bu artefaktları yeniden
doğrular.

## Doğrulama

```bash
scripts/gate.sh
```

Aynı gate her push ve pull request'te CI'da koşar (`.github/workflows/gate.yml`); hiçbir
gizli anahtara ihtiyaç duymaz, çünkü kontrol ettiği her şey yereldir.

Gate; manifesti yeniden üretir, Python ve TypeScript testlerini çalıştırır, production
istemcisini derler, tam bir headless koşu üretir ve replay hash'lerini doğrular.

## PixelLab asset hattı

İndirilen üretimler `assets/generated/` altında, prompt/seed/job kimliği
`assets/generated/lineage.json` içinde tutulur. Karakter kaynakları bunun yerine
sprite'ların yanında durur, örneğin `chars/scout/SOURCE.md`.
`tools/build_asset_manifest.py` tüm RGBA boyutlarını ve anchor'ları okuyup
`assets/manifest.json` üretir. İstemci dosya adlarına değil `structure.market.operational`
ve `effect.fire.loop.0` gibi semantik anahtarlara bağlıdır.

## Sorun giderme

- Boş harita: `uv run python tools/build_asset_manifest.py` ardından
  `npm --prefix frontend run build` çalıştır.
- `stale_turn`: yeniden `benchmark.observe` çağırıp güncel tur numarasıyla gönder.
- Tur `pending`: `waiting_for` listesindeki kontrolörler henüz paket göndermedi; zaman
  aşımı yöneticisi onların eylemini ölçülen `wait` olarak tamamlamalıdır.
- Replay uyuşmazlığı: koşu dosyalarını değiştirme; `uv run castle-benchmark replay <run-dir>`
  ilk farklı turu döndürür.

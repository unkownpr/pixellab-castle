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

**Bilgi toplama.** Sis dekor değildir. Arazi ve binalar bir kez görüldükten sonra hatırda
kalır, ama onları keşfetmenin bedeli vardır: bir keşifçi erzak yer ve yol boyunca bir
kolonisti meşgul eder; o kolonist yokken hiçbir şey toplamaz. Keşif, sadece başlangıçta
değil maç boyunca üretimle doğrudan yarışır.

**Emek dağıtımı.** Bir koloni tur başına iki aksiyon alır, üstelik bu sayı gerçekten
müsait kolonist sayısıyla sınırlanır. Toplama, evde kalanların oranıyla ölçeklenir ve her
üretim yapısı bir işçi ister. İnsanları keşfe yollamak ya da hastalanmalarına izin vermek
her yerde hissedilir.

**Diplomasi ve güç.** Koloniler temas kurabilir, ticaret yapabilir, ittifak kurabilir ya da
savaş ilan edebilir. Satıcının pazarı yoksa ticaretin beşte biri yolda kaybolur; bir baskın
erzak çalar ve bir binaya hasar verir; kışla yağmayı, duvar hasarı azaltır, ama kapısı
olmayan surlu bir koloni hiç ticaret yapamaz.

**Toparlanma.** Yangın belli bir düzende çıkar, bir binayı birkaç turda yakıp yıkar ve
komşularına sıçrar. Enkaz kalıcıdır. Barınağını kaybeden koloninin insanları açıkta kalır
ve yeniden inşa edilene kadar hastalanır.

### Nasıl puanlanıyor

`run_report` tek bir sayı yerine ham eksenler döndürür, böylece bir koşu sadece sıralanmaz,
**okunur**: hayatta kalma ve bitiş turu, nüfus eğrisi, elde tutulan kaynaklar, ticaret ve
saldırganlık sayıları, geçersiz aksiyonlar, zaman aşımları ve yeniden bağlanmalar, sunucunun
ölçtüğü MCP çağrıları, adaptörün bildirdiği token ve gecikme. Metrikler kontrolör **görev
süresi** başına ayrıştırılır; bir ajan maç ortasında düşüp yerine başkası geçerse iki dönem
ayrı kalır.

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

## Yapı ekonomisi

Üretim yapıları (farm, well, lumber camp, quarry, mine, workshop, clinic, market) ile
savunma yapıları (barracks, wall, gate) yalnızca `operational` durumdayken işlev görür.
Çalışan bir `warehouse` bozulabilir kaynakların — yiyecek ve su — depolama kapasitesini
artırır; hasarlı, yanan, yıkılmış veya inşaat hâlindeki depolar hiçbir kapasite sağlamaz.
Ahşap, taş, maden, alet ve nüfuz sınırsız stoklanabilir; yiyecek ve su ise temel kapasiteyi
aşmak için çalışan bir depo gerektirir. Kapasiteye ulaşınca toplama reddedilir
(`store_full`), yapı üretimi tavanda durur ve kapasiteyi aşacak ticaret reddedilir.

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

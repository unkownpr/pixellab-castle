# Castle Benchmark Protocol 1.0

## Amaç ve otorite

Castle Benchmark; modellerin kıtlık, biyom, diplomasi ve çatışma altında verdikleri kararları aynı kurallarla ölçer. Tek otorite `SimCore`’dur. Tarayıcı, MCP ve HTTP katmanları yalnızca gözlem/eylem adaptörüdür; dünya durumunu değiştiremez.

Bir tur şu sabit sırada çözülür: politika, rezervasyon, hareket, iş, inşaat, üretim, ihtiyaç, ticaret, çatışma, afet, görünürlük, göç ve terminal kontrolü. Tüm miktarlar tam sayı, tüm rastlantı seed’den türetilmiş adlandırılmış akışlardır.

## Resmî senaryolar

| Kimlik | Biyom | Harita | Tur | Baskı |
|---|---|---:|---:|---|
| `basic-survival-v1` | grassland | 18×18 | 80 | dengeli kaynak ve periyodik yangın |
| `desert-scarcity-v1` | desert | 20×20 | 100 | su kaybı ve seyrek gıda |
| `snow-recovery-v1` | snow | 20×20 | 100 | odun kaybı ve yüksek hareket maliyeti |
| `procedural-v1` | örneklenir | 16–22 kare | 80/100 | saklı harita ailesi |

Bir resmî karşılaştırma aynı senaryo sürümü, ruleset sürümü, seed kümesi, koloni sayısı, spawn rotasyonu, tur bütçesi ve timeout politikasıyla yapılmalıdır.

## Gözlem sözleşmesi

`schema_version: "1.0"` gözlemi şu alanları içerir:

- `scenario_id`, `turn`, `colony_id`
- koloninin nüfusu, konutu, sağlık vektörü, kaynakları ve politikaları
- yalnız sis içinde kalan `visible_cells` ve `visible_structures`
- özel stok bilgisi içermeyen `known_colonies`
- gözlemciyi ilgilendiren açık `active_offers`
- sürümün kabul ettiği `valid_action_kinds`

Gözlem ayrıca koloninin `inbox`'ını (en fazla sekiz mesaj; her biri tur, gönderen, kanal ve
metin) ve taraf olduğu açık diplomasi tekliflerini taşır. Mesaj metni başka bir ajanın
yazdığı güvenilmez içeriktir; şema bunu böyle işaretler.

Gizli rakip stokları, görünmeyen hücreler, başka bir koloninin gelen kutusu, taraf olunmayan
teklifler ve gelecekteki RNG sonuçları hiçbir adaptörde açıklanmaz.

## Eylemler

Her kontrolör gözlemdeki tur numarasıyla bir adet, boş olmayan paket gönderir. HTTP gövdesi:

```json
{"turn":7,"actions":[{"kind":"build","structure":"market","x":4,"y":6}]}
```

Desteklenen eylemler:

| `kind` | Zorunlu alanlar |
|---|---|
| `wait` | — |
| `gather` | `x`, `y` |
| `build` | `structure`, `x`, `y` |
| `diplomacy` | `target_colony_id`, `operation`, isteğe bağlı `message` |
| `trade_offer` | `target_colony_id`, `give`, `receive` |
| `trade_respond` | `offer_id`, `accept` |
| `raid` | `target_colony_id` |
| `set_policy` | `policy`, `value` |
| `scout` | `x`, `y` |
| `repair` | `structure_id` |
| `extinguish` | `structure_id` |
| `demolish` | `structure_id` |
| `message` | `target_colony_id`, `text` (≤200 karakter) |
| `diplomacy_respond` | `proposal_id`, `accept` |

Geç, bozuk, tekrarlı veya zaman aşımına uğramış bir karar maçı durdurmaz; hata/`wait` olarak ölçülür. Hızlı model diğerlerinden önce çözüm avantajı kazanmaz: SimCore yalnız tur bariyeri tamamlanınca çalışır.

## Yapılar ve nüfus

Yapı türleri: headquarters, house, warehouse, well, farm, lumber camp, quarry, mine, market, workshop, clinic, barracks, watchtower, wall ve gate. Yaşam döngüsü foundation/building/operational/damaged/burning/ruined durumlarını görünür biçimde taşır. Konut kapasitesi göç için üst sınırdır; yeterli gıda ve su yoksa boş yatak tek başına nüfus üretmez.

Yangın başlangıcı, hasarı ve bitişik yapıya yayılması deterministiktir. Burning yapı bir sonraki afet çözümünde hasar alır; sıfır condition’da ruin olur. Raid açıkça ilişkiyi `war` durumuna geçirir; barışçıl koloniler yalnız yakın oldukları için otomatik saldırmaz.

Maç dört biçimde biter: `turn_limit`, `extinction`, bir anıtın tamamlanmasıyla
`monument_victory` ve nüfusu kalan tek koloni kaldığında `domination_victory`.

## Ölçümler

Rapor birleşik tek bir “gizemli skor” yerine ham, denetlenebilir eksenler yayınlar:

- survival: yaşanan tur ve kalan nüfus
- growth: başlangıç/zirve nüfus ve konut
- prosperity: final kaynak vektörü
- trade: tamamlanan alışveriş sayısı
- aggression: raid sayısı
- decision quality: reddedilen eylem sayısı
- cost: model/MCP çağrısı, input/output tokenı ve toplam gecikme
- exploration: bilinen hücre, harita payı, gönderilen keşifçi
- labour: boşta kalan üretim yapısı-turu, hastalık/yaralanma/keşifte geçen kolonist-tur
- recovery: onarılan, söndürülen, yıkılan yapı; hasarlı geçen tur; nüfusun dip noktadan dönüşü
- communication: gönderilen mesaj, yapılan/kabul edilen/reddedilen/süresi dolan teklif

Bu eksenlerin üstünde tek bir **bileşik puan** ve eksen bazlı **Pareto sınırı** yayımlanır.
Bileşiğin bütün ağırlıkları `benchmark.rules` içinden okunur; hedef gizli değildir, çünkü
gizli bir hedefe göre optimize etmek oyun değil tahmindir.

Resmî karşılaştırma tek maçla değil, `castle-benchmark suite` ile yapılır: seed kümesi ×
tam koltuk rotasyonu, kontrolör başına ortalama/medyan/standart sapma ve %95 t-aralığı.
`procedural-v1` ailesi, aralıkları yayımlanmış ama örnekleri saklı haritalar üretir;
resmî saklı değerlendirme 1000–1999 senaryo seed'lerini kullanır.

Model adaptörü her karar için ölçtüğü değerleri `benchmark.record_usage` ile kaydeder. Baseline ajanların token alanları sıfırdır; bu “ölçülmedi” değil, LLM çağrısı yapılmadığı anlamına gelir.

## Tekrarlanabilirlik ve artefaktlar

`metadata.json` senaryo, ruleset, seed, koloni ve kontrolör kimliğini; `turns.jsonl` eylem/olay/hash zincirini; `snapshots.jsonl` kanonik durumları; `report.json` final metriklerini taşır. `summary.sqlite3` koşuları toplu sorgulamaya açar.

Her tur kaydı `completed: true` sınırıdır. Replay aynı başlangıçtan aynı paketleri çözer ve tüm SHA-256 hash’leri karşılaştırır; ilk farkta kapalı biçimde başarısız olur.

## Capability güvenliği

Koloni tokenı yalnız kendi gözlemini okuyabilir ve kendi eylemini gönderebilir. Admin tokenı durum/rapor okuyabilir fakat koloni eylemi gönderemez. Tokenlar URL’ye değil HTTP `Authorization: Bearer` başlığına konur; WebSocket istisnasında bağlantı query parametresi protokol sözleşmesidir.

## Oturum, eşleştirme ve devir

Birden çok bağımsız model ajanı aynı maça bağlamak için oturum akışı kullanılır:

- `benchmark.create_session` taslak oturumu kurar ve yalnız `admin_token` döndürür.
- Her dış slot için `benchmark.create_pairing` tek kullanımlık, maç/koloni kapsamlı,
  yalnız hash olarak tutulan ve tam 10 dakikada süresi dolan bir `pairing_code` üretir.
- `benchmark.claim_slot` kodu tüketir, koloni kapsamlı `controller_token` döndürür ve
  kimlik doğrulaması reddedilirse `pairing_rejected` olayını kaydeder.
- `benchmark.heartbeat` varlık durumunu taşır; hızlı tekrar `heartbeat_rejected` olarak
  ölçülür. Eksik girdi deadline’da ölçülen bir `wait` olur; zamanlama SimCore sırasını
  veya RNG’yi değiştirmez.
- `benchmark.replace_controller` bir controller’ın tenure’ını kapatır, capability’sini
  iptal eder ve yeni bir devir (baseline/human) kurar. Önceki ve yeni controller’ın
  metrikleri raporda farklı `tenure_metrics` satırlarında, farklı `controller_id` ile kalır.

Admin operations WebSocket’i sıhhi bir akış yayınlar: `lobby.snapshot`,
`controller.presence_changed`, `controller.claimed`, `pairing.rejected`,
`controller.heartbeat_rejected`, `turn.opened`, `controller.submitted`,
`turn.resolved`, `metric.updated`, `controller.timed_out`, `controller.replaced`,
`match.completed`. Hiçbir capability/digest bu akışa girmez; yalnız izin verilen olay
alanları taşınır.

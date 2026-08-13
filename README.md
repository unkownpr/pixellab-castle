# Castle Benchmark

Deterministik, oynanabilir ve MCP üzerinden kontrol edilebilir bir Survival Colony Benchmark. Godot gerektirmez: otoriter simülasyon Python’da, canlı servis FastAPI’de, izometrik oyun istemcisi PixiJS’tedir. PixelLab çıktıları semantik bir manifest üzerinden yüklenir.

## Hızlı başlangıç

Gereksinimler: Python 3.12–3.14, `uv`, Node.js 22+ ve npm.

```bash
uv sync --extra dev --locked
npm --prefix frontend ci
uv run python tools/build_asset_manifest.py
npm --prefix frontend run build
uv run castle-benchmark serve
```

Ardından `http://127.0.0.1:8000` adresini aç. Bir senaryo ve seed seç, haritada hücre seçip topla/inşa et veya diplomasi, ticaret, politika ve baskın eylemlerini kullan. İnsan kolonisi eylemini verdikten sonra kalan koloniler aynı sözleşme üzerinden deterministik baseline kararları gönderir.

## Headless benchmark

```bash
uv run castle-benchmark run --scenario basic-survival-v1 --seed 17 --colonies 4 --output runs
uv run castle-benchmark replay runs/basic-survival-v1-seed-17
uv run castle-benchmark report runs/basic-survival-v1-seed-17
```

Her koşu `metadata.json`, tur bazlı `turns.jsonl`, `snapshots.jsonl`, `report.json` ve `summary.sqlite3` üretir. Replay doğrulaması her turun kanonik SHA-256 durum hash’ini yeniden hesaplar.

## MCP bağlantısı

Codex/OpenCode gibi stdio MCP istemcileri için proje yolunu kendi makinenize göre ayarlayın:

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

- `benchmark.create_match`: seed’li maçı ve koloni capability tokenlarını üretir.
- `benchmark.join_match`: admin kabiliyetiyle tek bir koloni tokenını kontrolöre verir.
- `benchmark.observe`: yalnız kontrol edilen koloninin sisle sınırlandırılmış gözlemini verir.
- `benchmark.submit_actions`: eşzamanlı tur bariyerine eylem yollar.
- `benchmark.record_usage`: gerçek token ve gecikme ölçümlerini kaydeder.
- `benchmark.run_report`: admin tokenıyla canlı skor/ölçüm raporu verir.

Ayrıntılı sözleşme ve adalet kuralları için [benchmark protokolüne](docs/benchmark-protocol.md) bakın.

## Çok ajanlı uzak oturum (lobby + pairing)

Tek kişilik `create_match` akışının yanında, birden çok bağımsız model ajanını aynı
maça güvenli biçimde bağlayan oturum tabanlı akış vardır. Ajanlar yalnız kendi
kolonilerini kontrol eder; admin/orchestrator kabiliyetleri asla onlara gitmez.

Orchestrator sırrı (yerel stdio):

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="uzun-rastgele-bir-kabiliyet"
uv run castle-benchmark-mcp --transport stdio
```

Uzak Streamable HTTP (yalnız açık bir allowlist ve TLS sonlandırma ile servis edin;
MCP proxy’si TLS’i kendisi sonlandırmaz, `X-Forwarded-For` yalnız `--trusted-proxy`
CIDR’lerinden güvenilir):

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="uzun-rastgele-bir-kabiliyet"
uv run castle-benchmark-mcp --transport streamable-http --trusted-proxy 10.0.0.0/8
```

Oturum akışı (her ajan kendi döngüsünde):

1. `benchmark.create_session { orchestrator_token, scenario_id, seed, colony_count }`
   → `admin_token` (yalnız orchestrator’da kalır).
2. Her `cN` slotu için `benchmark.create_pairing { admin_token, colony_id }`
   → 10 dakikada süresi dolan tek kullanımlık `pairing_code`.
3. Ajan kendi makinesinde `benchmark.claim_slot { pairing_code, identity }`
   → yalnızca kendi kolonisine ait `controller_token`.
4. `benchmark.heartbeat { controller_token, turn, status }` ile `connected`/`ready`.
5. Orchestrator `benchmark.start_match { admin_token }`.
6. Ajan döngüsü: `benchmark.observe` → karar ver → `benchmark.submit_actions` →
   `benchmark.record_usage`; terminal olana dek `benchmark.match_status` ile turu izle.
7. `benchmark.replace_controller { admin_token, colony_id, replacement, baseline_kind }`
   ile kopan bir ajanı baseline’a devret. Önceki ve yeni controller’ın metrikleri
   `run_report` içinde farklı `tenure_metrics` satırlarında kalır.
8. `benchmark.run_report { admin_token }` → terminal durum + ham ölçümler.

Tam uçtan uca dört ajanlı referans (`tests/e2e/test_remote_agents.py`) üç resmî
biyomda bağlanma, oynama, rapor alma ve replay doğrulamasını kanıtlar. Serviste
`service.write_resolved_turns(admin_token, writer)` bir `ArtifactWriter` üzerinden
tur akışını dışa aktarır; `uv run castle-benchmark replay <run-dir>` bu artefaktları
yeniden doğrular.

## Doğrulama

```bash
scripts/gate.sh
```

Gate; manifesti yeniden üretir, Python ve TypeScript testlerini çalıştırır, production istemcisini derler, tam bir headless koşu üretir ve replay hash’lerini doğrular.

## PixelLab asset hattı

İndirilen üretimler `assets/generated/` altında, prompt/seed/job kimliği `assets/generated/lineage.json` içinde tutulur. `tools/build_asset_manifest.py` tüm RGBA boyutlarını ve anchor’ları okuyup `assets/manifest.json` üretir. İstemci dosya adlarına değil `structure.market.operational` ve `effect.fire.loop.0` gibi semantik anahtarlara bağlıdır.

## Sorun giderme

- Boş harita: `uv run python tools/build_asset_manifest.py` ardından `npm --prefix frontend run build` çalıştırın.
- `stale_turn`: yeniden `benchmark.observe` çağırıp güncel tur numarasıyla gönderin.
- Tur `pending`: `waiting_for` listesindeki kontrolörler henüz paket göndermedi; zaman aşımı yöneticisi onların eylemini ölçülen `wait` olarak tamamlamalıdır.
- Replay uyuşmazlığı: koşu dosyalarını değiştirmeyin; `uv run castle-benchmark replay <run-dir>` ilk farklı turu döndürür.

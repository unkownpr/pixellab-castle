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
```

HTTP tabanlı MCP incelemesi için:

```bash
uv run castle-benchmark-mcp --transport streamable-http
```

Temel araçlar:

- `benchmark.create_match`: seed’li maçı ve koloni capability tokenlarını üretir.
- `benchmark.observe`: yalnız kontrol edilen koloninin sisle sınırlandırılmış gözlemini verir.
- `benchmark.submit_actions`: eşzamanlı tur bariyerine eylem yollar.
- `benchmark.record_usage`: gerçek token ve gecikme ölçümlerini kaydeder.
- `benchmark.run_report`: admin tokenıyla canlı skor/ölçüm raporu verir.

Ayrıntılı sözleşme ve adalet kuralları için [benchmark protokolüne](docs/benchmark-protocol.md) bakın.

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

#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

uv sync --extra dev --locked
uv run python tools/build_asset_manifest.py
uv run pytest -q

npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build

gate_output="$(mktemp -d "${TMPDIR:-/tmp}/castle-benchmark-gate.XXXXXX")"
cleanup() {
  if [[ -n "$gate_output" && "$gate_output" == *castle-benchmark-gate.* ]]; then
    rm -rf "$gate_output"
  fi
}
trap cleanup EXIT

uv run castle-benchmark run \
  --scenario basic-survival-v1 \
  --seed 17 \
  --colonies 2 \
  --output "$gate_output"

run_dir="$gate_output/basic-survival-v1-seed-17"
uv run castle-benchmark replay "$run_dir"
uv run castle-benchmark report "$run_dir" >/dev/null

echo "Castle Benchmark gate passed."

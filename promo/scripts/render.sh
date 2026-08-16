#!/usr/bin/env bash
# Render every artifact the README embeds, from the data build_promo_data.py produced.
#
# Remotion ships its own Chrome Headless Shell, but that download fails behind some
# networks; CASTLE_PROMO_BROWSER points the renderer at any Chromium already on the box.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
media="../docs/media"
mkdir -p "$media"

browser_flag=()
if [[ -n "${CASTLE_PROMO_BROWSER:-}" ]]; then
  browser_flag=(--browser-executable "$CASTLE_PROMO_BROWSER")
fi

for lang in en tr; do
  npx remotion render "promo-$lang" "$media/castle-benchmark-$lang.mp4" \
    --codec=h264 --crf=28 "${browser_flag[@]}"
  npx remotion render "loop-$lang" "$media/castle-benchmark-loop-$lang.gif" \
    --codec=gif --every-nth-frame=2 "${browser_flag[@]}"
done

echo "Rendered into $media"

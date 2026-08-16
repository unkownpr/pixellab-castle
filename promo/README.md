# Promo

The video and the loop in the project README, built with [Remotion](https://remotion.dev).

Nothing here is mocked. The map animating through the film is a real match replayed from
`snapshots.jsonl`, drawn with the same PixelLab sprites the client binds; the bars quote
the composite scores from a report on disk; the closing figures come from a suite run. If a
rule changes and the numbers move, rebuild the data and the film says the new truth.

```bash
npm --prefix promo install
npm --prefix promo run data      # replay + sprites -> promo/public/
npm --prefix promo run render    # mp4 and gif, English and Turkish -> docs/media/
npm --prefix promo run studio    # preview and scrub while editing
```

`run data` defaults to `runs/suite-final/basic-survival-v1-seed-17`; point it elsewhere
with `--run <dir>`, and pass `--every 1` to replay every turn instead of every second one.
Run directories are not in git, so produce one first — `uv run castle-benchmark suite
--scenario basic-survival-v1 --seeds 11,17,23,29,37 --rotations all --colonies 4
--controllers survivalist,trader,expansionist,militarist --output runs/suite-final` — or
render straight from the committed `public/replay.json`, which is the data the current
film was built from.

Remotion downloads its own Chrome Headless Shell on first render. Where that download is
blocked, point it at any Chromium already installed:

```bash
CASTLE_PROMO_BROWSER="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell" \
  npm --prefix promo run render
```

## What the film says

| Scene | Source of its claim |
|---|---|
| What it measures | the six pressures in the project README |
| Replayed match | `runs/suite-final/basic-survival-v1-seed-17/snapshots.jsonl` |
| A model played it | a live match: DeepSeek V4 Flash over MCP, monument on turn 53 |
| Baseline means | `runs/suite-final/suite.json`, five seeds, every seat |

Copy lives in `src/copy.ts` in both languages; the compositions take a `lang` prop and the
render script emits English and Turkish artifacts from the same timeline.

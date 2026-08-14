# Scout sprite provenance

Generated with PixelLab on 2026-08-14.

- character id: `b28d86b4-499b-453c-98a4-5d6f6f062852`
- mode: `pro` (20 generations, 8 directions)
- style reference: `876f5870-ee1f-4326-80dc-8c52fdc6ec59` (Villager Blue), so the scout
  reads as part of the existing colony cast
- size: 48x48, view `low top-down`
- prompt: medieval scout explorer in a hooded forest-green cloak, leather satchel
  across the chest, wooden walking staff, light boots, readable game character sprite

Provenance for character sprites lives here rather than in
`assets/generated/lineage.json`. That file drives a second pass in
`tools/build_asset_manifest.py` which re-registers every entry with a different anchor
(`height - 6`) and a `seed` field. Characters are registered by the `chars/` pass with
anchor `height - 4`, so listing them in the lineage would both crash the builder and
silently shift these sprites two pixels against every other character.

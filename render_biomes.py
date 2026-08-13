"""Render the two biome scenes."""
from PIL import Image
from scenes import build

# --- grass river village (reference: green biome screenshot) -----------------
village = dict(
    seed=11, n=26, w=1500, h=1000, ox=700, oy=110,
    ground="grass_tile.png", field="wheat_tile.png",
    house="house_s.png", props=["pine_s.png", "pine_small.png"],
    river_start=9, river_w=3, river_amp=2.6,
    water_set="ws_grass",
    water_masks={0:0,1:1,2:2,3:15,4:4,5:5,6:6,7:7,8:8,9:9,10:10,11:11,12:12,13:13,14:14,15:15},
    fields=[(13, 4, 17, 7), (14, 12, 18, 15), (4, 15, 7, 18), (18, 18, 22, 21)],
    houses=[(12, 6), (16, 9), (13, 10), (17, 13), (19, 12), (12, 14),
            (15, 16), (18, 16), (11, 18), (20, 8), (14, 19), (21, 15)],
    monument=(15.5, 12.5),
    stalls=[(14.5, 12), (16.5, 13)],
    people=52,
    prop_p=lambda i, j, edge, walls: 0.55 if edge < 4 else 0.22,
)

# --- desert castle (reference: sand biome screenshot) ------------------------
desert = dict(
    seed=5, n=30, w=1600, h=1040, ox=770, oy=90,
    ground="sand_tile.png", field=None,
    house="house_desert.png", props=["rock_s.png", "rock_s.png", "rock_s.png", "bush_s.png"],
    river_start=25, river_w=3, river_amp=2.2,
    water_set="ws_sand",
    walls=(8, 8, 21, 21), gate=(14, 15),
    towers=[(8, 8), (21, 8), (8, 21), (21, 21), (8, 14), (21, 14),
            (12, 8), (17, 8), (12, 21), (17, 21)],
    plaza=(range(12, 18), range(12, 18)),
    keep=(11.5, 11.5),
    monument=(14.5, 14.5),
    stalls=[(13, 16.5), (16, 16.5), (13, 12.5), (16.5, 13.5), (15.5, 16)],
    houses=[(10, 14), (10, 16), (10, 18), (12, 19), (13, 19), (17, 19),
            (19, 18), (19, 16), (19, 14), (19, 11), (17.5, 10), (16, 10),
            (13, 10.5), (11, 10), (12, 17), (17, 12.5), (18, 13), (12.5, 13.5)],
    people=70,
    sky=(150, 205, 240, 255),
    prop_p=lambda i, j, edge, walls: 0.30 if edge < 4 else 0.12,
)

# --- snow biome (derived palette, no extra generations) ----------------------
snow = dict(
    village,
    seed=21, ground="snow_tile.png", water_set="ws_snow",
    props=["pine_snow.png", "pine_small_snow.png"],
    field=None, fields=[],
    sky=(176, 208, 232, 255),
    river_start=11, river_amp=3.0,
    people=36,
)

for name, cfg in (("village_river", village), ("desert_castle", desert), ("snow_village", snow)):
    img = build(cfg).convert("RGB")
    img.save(name + ".png")
    img.resize((img.width // 2, img.height // 2), Image.LANCZOS).save(name + "_half.png")
    print("rendered", name, img.size)

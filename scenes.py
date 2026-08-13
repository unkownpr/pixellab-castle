"""Two biome scenes: grass river village + desert castle. Shares one builder."""
import os
import random
from PIL import Image

from iso import Scene, kit, asset, save, TW, TH
from biome import river_corners, cell_state, WangWater

BASE = os.path.dirname(os.path.abspath(__file__))
DIRS = ["south", "south-east", "east", "north-east", "north", "north-west", "west", "south-west"]
CHARS = ["villager_blue", "villager_teal", "villager_red", "villager_brown"]


def have(name):
    return os.path.isdir(os.path.join(BASE, "chars", name))


_scaled = {}


def pick(rng, names, scale=0.72):
    """A character sprite, shrunk so villagers read smaller than the houses."""
    names = [n for n in names if have(n)] or CHARS
    path = os.path.join("chars", rng.choice(names), rng.choice(DIRS) + ".png")
    key = (path, scale)
    if key not in _scaled:
        im = asset(path)
        _scaled[key] = im.resize((max(1, round(im.width * scale)),
                                  max(1, round(im.height * scale))), Image.NEAREST)
    return _scaled[key]


# who shows up where — each role draws from its own cast
ROLES = {
    "wall":   ["guard_red"],
    "plaza":  ["merchant", "woman_green", "child", "villager_blue", "villager_teal",
               "villager_red", "guard_red", "blacksmith"],
    "house":  ["woman_green", "child", "villager_brown", "villager_teal", "blacksmith"],
    "field":  ["farmer", "farmer", "villager_brown", "woman_green"],
    "water":  ["woman_green", "child", "villager_blue", "farmer"],
    "wild":   ["villager_brown", "farmer", "guard_red"],
}


def crowd(rng, role="house"):
    """A sprite fitting the role, in a random facing."""
    return pick(rng, ROLES.get(role, ROLES["house"]))


def build(cfg):
    rng = random.Random(cfg["seed"])
    n = cfg["n"]
    s = Scene(cfg["w"], cfg["h"], cfg["ox"], cfg["oy"], cfg.get("sky", (150, 205, 240, 255)))

    ground = asset(cfg["ground"])
    wang = WangWater(cfg["water_set"], mask_of_tile=cfg.get("water_masks"))
    corners = river_corners(n, cfg["river_start"], seed=cfg["seed"] + 1,
                            width=cfg.get("river_w", 3), amp=cfg.get("river_amp", 3.0))
    river = {(i, j) for i in range(n) for j in range(n) if cell_state(corners, i, j) == 4}
    bank = {(i, j) for i in range(n) for j in range(n) if 0 < cell_state(corners, i, j) < 4}

    fields = cfg.get("fields", [])
    field_tile = asset(cfg["field"]) if cfg.get("field") else None

    walls = cfg.get("walls")            # (x0, y0, x1, y1) or None
    gate = cfg.get("gate", ())

    def in_wall(i, j):
        return walls and walls[0] <= i <= walls[2] and walls[1] <= j <= walls[3]

    def on_wall(i, j):
        return in_wall(i, j) and (i in (walls[0], walls[2]) or j in (walls[1], walls[3]))

    # keep the river out of the castle footprint
    if walls:
        corners = {c for c in corners
                   if not (walls[0] <= c[0] <= walls[2] + 1 and walls[1] <= c[1] <= walls[3] + 1)}
        river = {(i, j) for i in range(n) for j in range(n) if cell_state(corners, i, j) == 4}
        bank = {(i, j) for i in range(n) for j in range(n) if 0 < cell_state(corners, i, j) < 4}

    # --- terrain -------------------------------------------------------------
    for i in range(n):
        for j in range(n):
            wet = cell_state(corners, i, j)
            if wet and not in_wall(i, j):
                s.put_terrain(i, j, wang.tile_for(corners, i, j))
            elif field_tile and any(a <= i <= b and c <= j <= d for a, c, b, d in fields):
                s.put_terrain(i, j, field_tile)
            elif in_wall(i, j) and not on_wall(i, j) and cfg.get("plaza") and \
                    i in cfg["plaza"][0] and j in cfg["plaza"][1]:
                s.put_terrain(i, j, kit(0), (14, 55))
            else:
                s.put_terrain(i, j, ground)

    # --- castle walls --------------------------------------------------------
    if walls:
        x0, y0, x1, y1 = walls
        SIDE = {"N": 1, "E": 2, "S": 3, "W": 4}
        OUTER = {"NE": 9, "SE": 10, "SW": 11, "NW": 12}
        for i in range(x0, x1 + 1):
            for j in range(y0, y1 + 1):
                if not on_wall(i, j):
                    continue
                if (j == y0 and i in gate):
                    s.put_kit(i, j, 32 if i == gate[0] else 33)
                    continue
                if (j == y1 and i in gate):
                    s.put_kit(i, j, 36 if i == gate[0] else 37)
                    continue
                e = ("N" if j == y0 else "") + ("S" if j == y1 else "") + \
                    ("E" if i == x1 else "") + ("W" if i == x0 else "")
                if len(e) == 1:
                    s.put_kit(i, j, SIDE[e])
                else:
                    s.put_kit(i, j, OUTER[e if e in OUTER else e[::-1]])
        for i, j in cfg.get("towers", []):
            s.put_sprite(i, j, asset("tower_s.png"), yoff=-6, shadow=0.85)

    # --- buildings -----------------------------------------------------------
    house = asset(cfg["house"])
    for i, j in cfg.get("houses", []):
        s.put_sprite(i, j, house, yoff=-4, shadow=0.75)
    if cfg.get("keep"):
        s.put_sprite(*cfg["keep"], asset("keep_s.png"), yoff=-6, shadow=0.8)
    if cfg.get("monument"):
        s.put_sprite(*cfg["monument"], asset("monument_s.png"), yoff=-6, shadow=0.6)
    for i, j in cfg.get("stalls", []):
        s.put_sprite(i, j, asset("stall_s.png"), yoff=-2, shadow=0.7)

    # --- vegetation / rocks --------------------------------------------------
    props = [asset(p) for p in cfg["props"]]
    blocked = set(river) | {(i, j) for i, j in cfg.get("houses", [])}
    for i in range(n):
        for j in range(n):
            if (i, j) in blocked or in_wall(i, j):
                continue
            if field_tile and any(a - 1 <= i <= b + 1 and c - 1 <= j <= d + 1 for a, c, b, d in fields):
                continue
            if (i, j) in bank and rng.random() < 0.5:
                continue
            edge = min(i, j, n - 1 - i, n - 1 - j)
            p = cfg["prop_p"](i, j, edge, walls)
            if rng.random() < p:
                s.put_sprite(i + rng.uniform(-.3, .3), j + rng.uniform(-.3, .3),
                             rng.choice(props), yoff=-2, shadow=0.7)

    # --- people --------------------------------------------------------------
    near_house = set()
    for hi, hj in cfg.get("houses", []):
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                near_house.add((int(hi) + di, int(hj) + dj))
    in_field = set()
    for a, c, b, d in fields:
        for i in range(a, b + 1):
            for j in range(c, d + 1):
                in_field.add((i, j))
    plaza_cells = set()
    if cfg.get("plaza"):
        plaza_cells = {(i, j) for i in cfg["plaza"][0] for j in cfg["plaza"][1]}

    spots = []
    for i in range(n):
        for j in range(n):
            if (i, j) in river:
                continue
            if on_wall(i, j):
                spots.extend([((i, j), "wall")] * 2)      # sentries on the ramparts
                continue
            if (i, j) in plaza_cells:
                weight, role = 6, "plaza"
            elif in_wall(i, j):
                weight, role = 4, "plaza"
            elif (i, j) in in_field:
                weight, role = 4, "field"                  # farmers work the crops
            elif (i, j) in near_house:
                weight, role = 4, "house"
            elif (i, j) in bank:
                weight, role = 2, "water"
            elif min(i, j, n - 1 - i, n - 1 - j) < 3:
                weight, role = 0, "wild"                   # deep forest stays empty
            else:
                weight, role = 1, "wild"
            spots.extend([((i, j), role)] * weight)
    rng.shuffle(spots)
    seen = set()
    spots = [x for x in spots if not (x[0] in seen or seen.add(x[0]))]
    for (i, j), role in spots[:cfg.get("people", 40)]:
        yoff = -8 if role == "wall" else -3               # sentries stand on the wall top
        s.put_sprite(i + rng.uniform(-.3, .3), j + rng.uniform(-.3, .3),
                     crowd(rng, role), yoff=yoff, shadow=0 if role == "wall" else 0.5)

    return s.render()

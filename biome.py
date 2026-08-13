"""Shared biome helpers: river carving, crowd placement, tileset-driven water edges."""
import random

# --- river ------------------------------------------------------------------

def carve_river(n, start_i, seed=3, width=1, drift=0.55):
    """Random-walk a river from north to south. Returns {(i, j)} water cells."""
    rng = random.Random(seed)
    water, i = set(), start_i
    for j in range(-1, n + 1):
        prev = i
        if rng.random() < drift:
            i += rng.choice((-1, 1))
        i = max(2, min(n - 3, i))
        lo, hi = min(prev, i), max(prev, i)
        for k in range(lo, hi + 1):              # bridge the sideways step
            for w in range(width):
                water.add((k + w, j))
    return water


def water_edges(water, n):
    """Cells that touch water diagonally/orthogonally but are dry — the bank."""
    bank = set()
    for i, j in water:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                c = (i + di, j + dj)
                if c not in water and 0 <= c[0] < n and 0 <= c[1] < n:
                    bank.add(c)
    return bank


# --- crowds -----------------------------------------------------------------

def scatter(scene, sprites, cells, rng, density=0.5, yoff=-2, shadow=0.55, jitter=0.3):
    """Drop character sprites onto the given cells."""
    placed = []
    for i, j in cells:
        if rng.random() > density:
            continue
        sp = rng.choice(sprites)
        ii = i + rng.uniform(-jitter, jitter)
        jj = j + rng.uniform(-jitter, jitter)
        scene.put_sprite(ii, jj, sp, yoff=yoff, shadow=shadow)
        placed.append((ii, jj))
    return placed


# --- wang (corner) water tileset --------------------------------------------

class WangWater:
    """16-tile corner set: bit high = land occupies that corner."""

    def __init__(self, folder, order=("NW", "NE", "SW", "SE"), mask_of_tile=None):
        from iso import asset
        tiles = [asset("%s/tile_%d.png" % (folder, i)) for i in range(16)]
        # PixelLab does not guarantee tile index == mask; trust the placement rules.
        mask_of_tile = mask_of_tile or {i: i for i in range(16)}
        self.by_mask = {}
        for idx, mask in mask_of_tile.items():
            self.by_mask.setdefault(mask, tiles[idx])
        for m in range(16):                       # fall back to the all-land tile
            self.by_mask.setdefault(m, self.by_mask.get(15, tiles[15]))
        self.order = order

    def corner_is_land(self, water_corners, a, b):
        return (a, b) not in water_corners

    def tile_for(self, water, i, j):
        c = {"NW": (i, j), "NE": (i + 1, j), "SW": (i, j + 1), "SE": (i + 1, j + 1)}
        mask = 0
        for bit, key in enumerate(self.order):
            if self.corner_is_land(water, *c[key]):
                mask |= 1 << (3 - bit)
        return self.by_mask[mask]


def river_corners(n, start_i, seed=3, width=3, amp=3.0, waves=1.7):
    """A smooth meandering river on the CORNER lattice (what a wang tileset indexes)."""
    import math
    rng = random.Random(seed)
    phase = rng.uniform(0, 6.28)
    corners = set()
    for j in range(-2, n + 3):
        t = j / max(1, n)
        centre = start_i + amp * math.sin(phase + t * waves * 6.283) + amp * 0.4 * math.sin(phase * 2 + t * 11.0)
        centre = max(2, min(n - 2, centre))
        lo = int(round(centre))
        for w in range(width):
            corners.add((lo + w, j))
    return corners


def cell_state(corners, i, j):
    """How wet a cell is: 4 = open water, 1-3 = bank, 0 = dry."""
    return sum(((i + di, j + dj) in corners) for di in (0, 1) for dj in (0, 1))

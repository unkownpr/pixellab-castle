"""Assemble the 2D isometric castle map from the PixelLab kit + props."""
import random
from iso import Scene, kit, asset, save

random.seed(7)

N = 30                       # grid size
X0, X1 = 8, 21               # castle wall bounds (inclusive)
Y0, Y1 = 8, 21
PLAZA = range(12, 18)        # flagstone courtyard
GATE_N = (14, 15)            # gate cells on the north wall
GATE_S = (14, 15)

SIDE = {"N": 1, "E": 2, "S": 3, "W": 4}
OUTER = {"NE": 9, "SE": 10, "SW": 11, "NW": 12}
DOOR_N = (32, 33)
DOOR_S = (36, 37)

s = Scene(1600, 1040, 770, 90)

grass, wheat, dirt = asset("grass_tile.png"), asset("wheat_tile.png"), asset("dirt_tile.png")
tower, house = asset("tower_s.png"), asset("house_s.png")
pine, stall, monument = asset("pine_s.png"), asset("stall_s.png"), asset("monument_s.png")
pine2, keep = asset("pine_small.png"), asset("keep_s.png")

wheat_fields = [(2, 3, 6, 7), (23, 4, 27, 8), (1, 18, 5, 22), (22, 20, 27, 25), (12, 1, 17, 4)]


def in_wall(i, j):
    return X0 <= i <= X1 and Y0 <= j <= Y1


def on_wall(i, j):
    return in_wall(i, j) and (i in (X0, X1) or j in (Y0, Y1))


def is_gate(i, j):
    return (j == Y0 and i in GATE_N) or (j == Y1 and i in GATE_S)


# --- terrain -----------------------------------------------------------------
for i in range(N):
    for j in range(N):
        tile = grass
        if any(a <= i <= b and c <= j <= d for a, c, b, d in wheat_fields):
            tile = wheat
        # roads leading out of both gates
        elif i in GATE_N and (j < Y0 or j > Y1):
            tile = dirt
        elif in_wall(i, j) and not on_wall(i, j):
            if i in PLAZA and j in PLAZA:
                tile = None                       # flagstone floor from the kit
            elif i in GATE_N and j not in PLAZA:
                tile = dirt
        if tile is None:
            s.put_terrain(i, j, kit(0), (14, 55))
        else:
            s.put_terrain(i, j, tile)

# --- castle walls ------------------------------------------------------------
for i in range(X0, X1 + 1):
    for j in range(Y0, Y1 + 1):
        if not on_wall(i, j):
            continue
        if is_gate(i, j):
            door = DOOR_N if j == Y0 else DOOR_S
            s.put_kit(i, j, door[0] if i == GATE_N[0] else door[1])
            continue
        edge = ""
        if j == Y0:
            edge += "N"
        if j == Y1:
            edge += "S"
        if i == X1:
            edge += "E"
        if i == X0:
            edge += "W"
        if len(edge) == 1:
            s.put_kit(i, j, SIDE[edge])
        else:
            s.put_kit(i, j, OUTER[edge if edge in OUTER else edge[::-1]])

# --- towers: corners, wall midpoints, gate flanks -----------------------------
mid = (X0 + X1) // 2
towers = [(X0, Y0), (X1, Y0), (X0, Y1), (X1, Y1),
          (X0, mid), (X1, mid),
          (GATE_N[0] - 2, Y0), (GATE_N[1] + 2, Y0),
          (GATE_S[0] - 2, Y1), (GATE_S[1] + 2, Y1)]
for i, j in towers:
    s.put_sprite(i, j, tower, yoff=-6, shadow=0.85)

# --- houses inside the walls --------------------------------------------------
s.put_sprite(11.5, 11.5, keep, yoff=-6, shadow=0.8)          # the keep
houses = [(10, 14), (10, 16), (10, 18), (12, 19), (13, 19),
          (17, 19), (19, 18), (19, 16), (19, 14), (19, 11),
          (17.5, 10), (16, 10), (13, 10.5), (11, 10),
          (12, 17), (17, 12.5), (18, 13), (12.5, 13.5)]
for i, j in houses:
    s.put_sprite(i, j, house, yoff=-4, shadow=0.75)

# --- plaza dressing -----------------------------------------------------------
s.put_sprite(14.5, 14.5, monument, yoff=-6, shadow=0.6)
for i, j in [(13, 16.5), (16, 16.5), (13, 12.5), (16.5, 13.5), (15.5, 16), (12.5, 15)]:
    s.put_sprite(i, j, stall, yoff=-2, shadow=0.7)

# --- pine forest outside ------------------------------------------------------
for i in range(N):
    for j in range(N):
        if in_wall(i, j) or (i in GATE_N and (j < Y0 or j > Y1)):
            continue
        if any(a - 1 <= i <= b + 1 and c - 1 <= j <= d + 1 for a, c, b, d in wheat_fields):
            continue
        edge_dist = min(i, j, N - 1 - i, N - 1 - j)
        gap = min(abs(i - X0), abs(i - X1), abs(j - Y0), abs(j - Y1))
        p = 0.55 if edge_dist < 5 else 0.28
        if gap < 2:
            p = 0.05                                   # keep a clearing around the walls
        if random.random() < p:
            tree = pine if random.random() < 0.7 else pine2
            s.put_sprite(i + random.uniform(-.3, .3), j + random.uniform(-.3, .3),
                         tree, yoff=-2, shadow=0.7)

save(s.render(), "castle_2d.png")
print("rendered castle_2d.png")

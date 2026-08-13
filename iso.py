"""Isometric compositor for the PixelLab castle kit."""
from PIL import Image, ImageDraw
import os

BASE = os.path.dirname(os.path.abspath(__file__))
TW, TH = 48, 24          # ground diamond footprint
KIT_ANCHOR = (14, 55)    # where the floor diamond sits inside a 76x86 kit canvas

_cache = {}


def kit(idx):
    key = ("kit", idx)
    if key not in _cache:
        _cache[key] = Image.open(os.path.join(BASE, "kit", "tile_%d.png" % idx)).convert("RGBA")
    return _cache[key]


def asset(name):
    if name not in _cache:
        _cache[name] = Image.open(os.path.join(BASE, name)).convert("RGBA")
    return _cache[name]


def screen(i, j, ox, oy):
    return round(ox + (i - j) * (TW / 2)), round(oy + (i + j) * (TH / 2))


class Scene:
    def __init__(self, w, h, ox, oy, bg=(120, 190, 235, 255)):
        self.img = Image.new("RGBA", (w, h), bg)
        self.ox, self.oy = ox, oy
        self.terrain = []    # (i, j, image, anchor)
        self.objects = []    # (i, j, image, anchor, yoff)

    def put_terrain(self, i, j, im, anchor=(0, 0)):
        self.terrain.append((i, j, im, anchor))

    def put(self, i, j, im, anchor=(0, 0), yoff=0):
        self.objects.append((i, j, im, anchor, yoff))

    def put_kit(self, i, j, idx, yoff=0):
        self.objects.append((i, j, kit(idx), KIT_ANCHOR, yoff))

    def put_sprite(self, i, j, im, yoff=0, shadow=0.0):
        """Center a free sprite on the cell's diamond, feet on the diamond centre."""
        bx0, by0, bx1, by1 = im.getbbox()
        anchor = ((bx0 + bx1) // 2 - TW // 2, by1 - TH // 2 - TH // 2)
        if shadow > 0:
            w = int((bx1 - bx0) * shadow)
            sh = Image.new("RGBA", (w, max(6, w // 2)), (0, 0, 0, 0))
            ImageDraw.Draw(sh).ellipse((0, 0, sh.width - 1, sh.height - 1), fill=(20, 60, 30, 70))
            self.objects.append((i, j, sh, (sh.width // 2 - TW // 2, sh.height // 2 - TH // 2), yoff + 2))
        self.objects.append((i, j, im, anchor, yoff))

    def render(self):
        for i, j, im, a in sorted(self.terrain, key=lambda t: (t[0] + t[1], t[0])):
            sx, sy = screen(i, j, self.ox, self.oy)
            self.img.alpha_composite(im, (sx - a[0], sy - a[1]))
        for i, j, im, a, yoff in sorted(self.objects, key=lambda t: (t[0] + t[1], t[0])):
            sx, sy = screen(i, j, self.ox, self.oy)
            self.img.alpha_composite(im, (sx - a[0], sy - a[1] + yoff))
        return self.img


def save(img, path, scale=1):
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.convert("RGB").save(os.path.join(BASE, path))
    return img

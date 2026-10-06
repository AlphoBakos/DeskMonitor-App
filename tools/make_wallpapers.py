# -*- coding: utf-8 -*-
"""Génère les fonds d'écran livrés avec DeskMonitor : compositions abstraites dessinées par programme
(aucune image extérieure, donc aucun droit d'auteur). Usage : python tools/make_wallpapers.py"""
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 2560, 1440
OUT = Path(__file__).resolve().parent.parent / "assets" / "wallpapers"


def gradient(top, bottom, w=W, h=H):
    """Dégradé vertical."""
    col = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return col.resize((w, h), Image.BICUBIC)


def glow(img, x, y, r, color, strength=1.0):
    """Halo lumineux doux (mode « éclaircir »)."""
    layer = Image.new("RGB", img.size, (0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(c * strength) for c in color))
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.6))
    return ImageChops.screen(img, layer)


def grain(img, amount=6, seed=0):
    """Léger grain : évite les bandes visibles dans les dégradés."""
    rnd = random.Random(seed)
    noise = Image.effect_noise((img.width // 2, img.height // 2), 64).resize(img.size).convert("RGB")
    del rnd
    return Image.blend(img, ImageChops.add(img, noise, scale=2.0, offset=-64), amount / 100)


def ribbons(img, colors, seed, count=5, amp=180, thick=90, blur=60, base_y=0.55):
    """Rubans ondulés et lumineux, façon aurore."""
    rnd = random.Random(seed)
    for i in range(count):
        layer = Image.new("RGB", img.size, (0, 0, 0))
        d = ImageDraw.Draw(layer)
        col = colors[i % len(colors)]
        f1, f2 = rnd.uniform(0.6, 1.6), rnd.uniform(1.5, 3.5)
        p1, p2 = rnd.uniform(0, 6.28), rnd.uniform(0, 6.28)
        y0 = H * (base_y + rnd.uniform(-0.18, 0.18))
        a = amp * rnd.uniform(0.5, 1.2)
        pts = [(x, y0 + a * math.sin(x / W * 6.28 * f1 + p1) + a * 0.35 * math.sin(x / W * 6.28 * f2 + p2))
               for x in range(-40, W + 41, 20)]
        d.line(pts, fill=col, width=int(thick * rnd.uniform(0.6, 1.3)), joint="curve")
        layer = layer.filter(ImageFilter.GaussianBlur(blur * rnd.uniform(0.7, 1.3)))
        img = ImageChops.screen(img, layer)
    return img


def dunes(img, colors, seed, layers=6):
    """Collines superposées (de la plus lointaine à la plus proche)."""
    rnd = random.Random(seed)
    for i in range(layers):
        t = i / max(1, layers - 1)
        col = tuple(round(a + (b - a) * t) for a, b in zip(colors[0], colors[1]))
        y0 = H * (0.45 + 0.09 * i)
        f, p = rnd.uniform(0.8, 1.8), rnd.uniform(0, 6.28)
        a = 70 + 30 * rnd.random()
        pts = [(x, y0 + a * math.sin(x / W * 6.28 * f + p) + 25 * math.sin(x / W * 30 + p * 2))
               for x in range(0, W + 1, 16)]
        d = ImageDraw.Draw(img)
        d.polygon(pts + [(W, H), (0, H)], fill=col)
    return img


def stars(img, seed, n=500):
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img)
    for _ in range(n):
        x, y = rnd.randrange(W), rnd.randrange(int(H * 0.75))
        v = rnd.randint(120, 255)
        r = rnd.choice((1, 1, 1, 2))
        d.ellipse((x, y, x + r, y + r), fill=(v, v, min(255, v + 20)))
    return img


def vignette(img, strength=0.45):
    mask = Image.new("L", (W // 8, H // 8), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((-W // 16, -H // 16, W // 8 + W // 16, H // 8 + H // 16), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(20)).resize(img.size)
    dark = Image.new("RGB", img.size, (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), mask)


def aurore():
    img = gradient((6, 10, 24), (10, 26, 38))
    img = stars(img, 1, 700)
    img = ribbons(img, [(30, 210, 150), (40, 160, 220), (120, 90, 230)], seed=2, count=6, amp=150, base_y=0.42)
    return vignette(img)


def crepuscule():
    img = gradient((28, 20, 64), (250, 130, 90))
    img = glow(img, W * 0.62, H * 0.62, 260, (255, 200, 120), 0.9)
    img = dunes(img, [(70, 40, 90), (18, 12, 30)], seed=3)
    return vignette(img, 0.3)


def ocean():
    img = gradient((4, 20, 40), (0, 70, 110))
    img = ribbons(img, [(0, 180, 200), (20, 120, 220), (0, 220, 180)], seed=4, count=7, amp=90, thick=60,
                  blur=40, base_y=0.6)
    img = glow(img, W * 0.2, H * 0.15, 420, (40, 120, 200), 0.6)
    return vignette(img)


def nebuleuse():
    img = gradient((8, 6, 20), (16, 8, 30))
    rnd = random.Random(5)
    for _ in range(14):
        img = glow(img, rnd.uniform(0.2, 0.8) * W, rnd.uniform(0.2, 0.8) * H, rnd.uniform(160, 420),
                   rnd.choice([(170, 60, 200), (220, 70, 120), (60, 90, 220), (40, 170, 200)]), rnd.uniform(0.3, 0.7))
    img = stars(img, 6, 900)
    return vignette(img, 0.5)


def graphite():
    img = gradient((34, 37, 43), (10, 11, 14))
    img = glow(img, W * 0.7, H * 0.25, 380, (70, 80, 96), 0.7)
    img = dunes(img, [(48, 52, 60), (14, 15, 18)], seed=7, layers=5)
    img = ribbons(img, [(110, 120, 140)], seed=11, count=2, amp=120, thick=6, blur=3, base_y=0.38)
    return vignette(img, 0.35)


def aube():
    img = gradient((255, 222, 205), (205, 225, 250))
    img = glow(img, W * 0.32, H * 0.42, 300, (255, 245, 225), 0.8)
    img = dunes(img, [(236, 190, 200), (150, 160, 215)], seed=8, layers=6)
    return img


def foret():
    img = gradient((14, 36, 30), (30, 70, 52))
    img = glow(img, W * 0.75, H * 0.2, 360, (180, 230, 160), 0.45)
    img = dunes(img, [(36, 82, 60), (8, 22, 18)], seed=9, layers=7)
    return vignette(img, 0.35)


def braise():
    img = gradient((20, 6, 6), (40, 10, 8))
    img = ribbons(img, [(230, 80, 40), (250, 150, 50), (190, 40, 60)], seed=10, count=6, amp=200, thick=70,
                  blur=50, base_y=0.55)
    return vignette(img, 0.5)


WALLPAPERS = {"Aurore boréale": aurore, "Crépuscule": crepuscule, "Océan": ocean, "Nébuleuse": nebuleuse,
              "Graphite": graphite, "Aube pastel": aube, "Forêt": foret, "Braises": braise}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in WALLPAPERS.items():
        img = grain(fn().convert("RGB"), 4)
        img.save(OUT / f"{name}.jpg", quality=88, optimize=True, progressive=True)
        print("fond créé :", name)

# -*- coding: utf-8 -*-
"""Fond d'écran vivant : teinte selon l'heure, ambiance selon l'état de la machine, jauges dessinées dessus.
À partir du fond d'écran choisi (jamais modifié), on compose une nouvelle image appliquée au bureau."""
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core import CONFIG_DIR

MAX_W = 2880
OUT = CONFIG_DIR / "dynamic"

SLOTS = (  # (heure de début, nom, teinte RGB, force, luminosité)
    (5, "matin", (255, 214, 150), 0.14, 1.02),
    (11, "journée", (255, 255, 255), 0.0, 1.0),
    (17, "soir", (255, 130, 55), 0.24, 0.92),
    (21, "nuit", (18, 28, 90), 0.38, 0.55),
)


def time_slot(now=None):
    h = (now or datetime.now()).hour
    name = SLOTS[-1][1]
    for start, n, *_ in SLOTS:
        if h >= start:
            name = n
    if h < SLOTS[0][0]:
        name = "nuit"
    return name


def state_of(cfg, last, battery, ping):
    """Ambiance courante selon les seuils d'alerte : 'cpu', 'ram', 'battery', 'offline' ou ''."""
    if ping is None:
        return "offline"
    if battery is not None and not battery.power_plugged and battery.percent <= cfg["alert_bat"]:
        return "battery"
    if last.get("cpu", 0) >= cfg["alert_cpu"]:
        return "cpu"
    if last.get("ram", 0) >= cfg["alert_ram"]:
        return "ram"
    return ""


def _font(size):
    for p in ("/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/segoeui.ttf"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _tint(img, rgb, strength):
    if strength <= 0:
        return img
    return Image.blend(img, Image.new("RGB", img.size, rgb), strength)


def _vignette(img, rgb, strength):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle((w * 0.12, h * 0.12, w * 0.88, h * 0.88), fill=255)
    mask = ImageEnhance.Brightness(mask.filter(ImageFilter.GaussianBlur(w * 0.12))).enhance(1.0)
    inv = Image.eval(mask, lambda v: 255 - v).point(lambda v: int(v * strength))
    return Image.composite(Image.new("RGB", (w, h), rgb), img, inv)


def _rings(img, values, accent):
    """Trois jauges (CPU, RAM, disque) en bas à gauche, dessinées en haute définition."""
    w, h = img.size
    r, thick = int(h * 0.055), max(6, int(h * 0.011))
    gap = int(r * 0.9)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f_big, f_small = _font(int(r * 0.62)), _font(int(r * 0.30))
    x0, y = int(w * 0.04) + r, int(h * 0.97) - r - int(h * 0.04)
    for i, (label, pct) in enumerate(values):
        cx = x0 + i * (2 * r + gap)
        box = (cx - r, y - r, cx + r, y + r)
        d.ellipse((box[0] - thick, box[1] - thick, box[2] + thick, box[3] + thick), fill=(0, 0, 0, 90))
        d.arc(box, 0, 360, fill=(255, 255, 255, 70), width=thick)
        color = (255, 69, 58, 255) if pct >= 90 else accent + (255,)
        d.arc(box, -90, -90 + 360 * min(100, pct) / 100, fill=color, width=thick)
        d.text((cx, y - r * 0.08), f"{pct:.0f}", font=f_big, fill=(255, 255, 255, 255), anchor="mm")
        d.text((cx, y + r * 0.52), label, font=f_small, fill=(255, 255, 255, 200), anchor="mm")
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def compose(base_path, size=None, slot=None, state="", stats=None, accent=(10, 132, 255)):
    """Retourne l'image composée. slot/state/stats à None ou vides : effet désactivé."""
    img = Image.open(base_path).convert("RGB")
    if size:  # remplit l'écran sans déformer (recadrage centré)
        tw, th = size
        k = max(tw / img.width, th / img.height)
        img = img.resize((int(img.width * k) + 1, int(img.height * k) + 1), Image.LANCZOS)
        l, t = (img.width - tw) // 2, (img.height - th) // 2
        img = img.crop((l, t, l + tw, t + th))
    if img.width > MAX_W:
        img = img.resize((MAX_W, int(img.height * MAX_W / img.width)), Image.LANCZOS)
    if slot:
        _, _, rgb, strength, bright = next(s for s in SLOTS if s[1] == slot)
        img = _tint(ImageEnhance.Brightness(img).enhance(bright), rgb, strength)
    if state == "offline":
        img = ImageEnhance.Color(ImageEnhance.Brightness(img).enhance(0.85)).enhance(0.15)
    elif state == "battery":
        img = ImageEnhance.Brightness(img).enhance(0.55)
        img = _vignette(img, (255, 159, 10), 0.35)
    elif state in ("cpu", "ram"):
        img = _vignette(img, (255, 45, 45), 0.55)
    if stats:
        img = _rings(img, stats, accent)
    return img


def render_to_file(**kw):
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("dyn-*.jpg"):
        old.unlink(missing_ok=True)
    path = OUT / f"dyn-{int(datetime.now().timestamp())}.jpg"
    compose(**kw).save(path, quality=92)
    return str(path)

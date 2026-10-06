# -*- coding: utf-8 -*-
"""Collection de fonds d'écran : images fournies avec l'application + images ajoutées par l'utilisateur."""

import ctypes
import hashlib
import random
import shutil
import sys
import time
from pathlib import Path

from core import CONFIG_DIR, IS_MAC, IS_WIN

if IS_WIN:
    import winreg

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
USER_DIR = CONFIG_DIR / "wallpapers"          # images ajoutées par l'utilisateur
APPLIED_DIR = CONFIG_DIR / "applied"          # copie de l'image appliquée (survit aux mises à jour)
THUMB_DIR = CONFIG_DIR / "thumbs"

# Disposition : (WallpaperStyle, TileWallpaper) dans HKCU\Control Panel\Desktop
FITS = {"fill": ("10", "0"), "fit": ("6", "0"), "stretch": ("2", "0"), "center": ("0", "0"),
        "tile": ("0", "1"), "span": ("22", "0")}
FIT_LABELS = {"fill": "Remplir", "fit": "Ajuster", "stretch": "Étirer", "center": "Centrer",
              "tile": "Mosaïque", "span": "Étendre (plusieurs écrans)"}


def bundled_dir():
    """Dossier des fonds d'écran livrés avec l'application (exe ou code source)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent / "assets"))
    return base / "wallpapers"


def list_wallpapers():
    """[(nom affiché, chemin, "app" | "user")] triés par nom."""
    out = []
    for folder, kind in ((bundled_dir(), "app"), (USER_DIR, "user")):
        if folder.is_dir():
            for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
                if p.suffix.lower() in IMAGE_EXT:
                    out.append((p.stem, str(p), kind))
    return out


def add_images(paths):
    USER_DIR.mkdir(parents=True, exist_ok=True)
    added = []
    for src in paths:
        src = Path(src)
        if src.suffix.lower() not in IMAGE_EXT:
            continue
        dst = USER_DIR / src.name
        n = 2
        while dst.exists():
            dst = USER_DIR / f"{src.stem} ({n}){src.suffix}"
            n += 1
        shutil.copy2(src, dst)
        added.append(str(dst))
    return added


def remove_image(path):
    p = Path(path)
    if p.parent == USER_DIR:  # on ne supprime jamais les images livrées avec l'application
        p.unlink(missing_ok=True)


def thumbnail(path, w, h):
    """Miniature (PIL.Image) recadrée au format w×h, mise en cache sur disque."""
    from PIL import Image, ImageOps
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(path)
    try:
        digest = hashlib.md5(f"{p}|{p.stat().st_mtime}".encode("utf-8")).hexdigest()[:16]
    except OSError:
        return None
    key = f"{digest}_{w}x{h}.png"
    cached = THUMB_DIR / key
    if cached.exists():
        return Image.open(cached)
    try:
        img = ImageOps.fit(Image.open(p).convert("RGB"), (w, h), Image.LANCZOS)
    except OSError:
        return None
    img.save(cached)
    return img


def _osascript(script):
    import subprocess
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    if res.returncode != 0:
        raise OSError(res.stderr.strip() or "osascript a échoué")
    return res.stdout.strip()


def current_wallpaper():
    if IS_MAC:
        try:
            return _osascript('tell application "System Events" to get picture of desktop 1') or None
        except (OSError, Exception):  # noqa: BLE001
            return None
    if not IS_WIN:
        return None
    buf = ctypes.create_unicode_buffer(520)
    ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0)  # SPI_GETDESKWALLPAPER
    return buf.value or None


def set_wallpaper(path, fit="fill"):
    """Applique l'image comme fond d'écran du bureau. Retourne le chemin réellement utilisé."""
    if not (IS_WIN or IS_MAC):
        raise OSError("Fonds d'écran : Windows et macOS uniquement")
    APPLIED_DIR.mkdir(parents=True, exist_ok=True)
    # copie dans le dossier de l'application : l'image reste valable même si l'original disparaît.
    # Sur Mac, un nom différent à chaque fois : sinon le Finder garde l'ancienne image en cache.
    stem = f"fond-{int(time.time())}" if IS_MAC else "fond-actuel"
    dst = APPLIED_DIR / (stem + Path(path).suffix.lower())
    for old in APPLIED_DIR.glob("fond-*"):
        if old != dst:
            old.unlink(missing_ok=True)
    if Path(path).resolve() != dst.resolve():
        shutil.copy2(path, dst)
    if IS_MAC:  # tous les bureaux / écrans (macOS peut demander l'autorisation la 1re fois)
        esc = str(dst).replace("\\", "\\\\").replace('"', '\\"')
        _osascript(f'tell application "System Events" to tell every desktop to set picture to "{esc}"')
        return str(dst)
    style, tile = FITS.get(fit, FITS["fill"])
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, style)
        winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, tile)
    # SPI_SETDESKWALLPAPER, SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE
    if not ctypes.windll.user32.SystemParametersInfoW(0x0014, 0, str(dst), 0x01 | 0x02):
        raise OSError("Windows a refusé de changer le fond d'écran")
    return str(dst)


def next_slideshow(cfg):
    """Prochaine image du diaporama (dans l'ordre ou au hasard)."""
    items = [p for _, p, _ in list_wallpapers()]
    if cfg.get("slideshow_only"):
        items = [p for p in items if Path(p).stem in cfg["slideshow_only"]] or items
    if not items:
        return None
    last = cfg.get("wallpaper_last")
    if cfg.get("slideshow_shuffle") and len(items) > 1:
        return random.choice([p for p in items if p != last])
    try:
        return items[(items.index(last) + 1) % len(items)]
    except ValueError:
        return items[0]

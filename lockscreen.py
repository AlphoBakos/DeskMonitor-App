# -*- coding: utf-8 -*-
"""
Écran de verrouillage personnalisé.

Windows ne laisse pas modifier son horloge de l'écran de verrouillage. DeskMonitor :
  - applique l'image de votre choix (API Windows « LockScreen ») ;
  - y incruste la date et/ou un message, avec police, couleur et position au choix
    (l'image est régénérée chaque jour pour que la date reste juste) ;
  - règle le format de l'heure de Windows (24 h / 12 h), utilisé par l'horloge de l'écran de verrouillage ;
  - peut masquer les astuces et publicités de Windows sur l'écran de verrouillage.
"""

import ctypes
import os
import subprocess
from datetime import datetime
from pathlib import Path

from core import CONFIG_DIR, IS_WIN, format_date

if IS_WIN:
    import winreg

OUT_DIR = CONFIG_DIR / "lockscreen"
POSITIONS = {"bottom_left": "En bas à gauche", "bottom_center": "En bas au centre",
             "bottom_right": "En bas à droite", "center": "Au centre",
             "top_left": "En haut à gauche", "top_right": "En haut à droite"}
CDM_KEY = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
INTL_KEY = r"Control Panel\International"


# --------------------------------------------------------------------------- #
#  Composition de l'image
# --------------------------------------------------------------------------- #
def _font_files():
    """{nom de police en minuscules: fichier} d'après le registre Windows."""
    fonts = {}
    if not IS_WIN:
        return fonts
    windir_fonts = Path(os.getenv("WINDIR", r"C:\Windows")) / "Fonts"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                name = name.replace(" (TrueType)", "").replace(" (OpenType)", "").strip().lower()
                path = Path(value)
                fonts[name] = str(path if path.is_absolute() else windir_fonts / path)
    return fonts


def load_font(family, size, bold=False):
    from PIL import ImageFont
    fonts = _font_files()
    fam = (family or "").lower()
    wanted = [f"{fam} bold", fam] if bold else [fam, f"{fam} regular"]
    for w in wanted:
        if w in fonts:
            try:
                return ImageFont.truetype(fonts[w], size)
            except OSError:
                pass
    for name, path in fonts.items():  # collections : « Cambria & Cambria Math »…
        if name.startswith(fam + " &") or name.startswith(fam + " ("):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    for fallback in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fallback, size)
        except OSError:
            pass
    return ImageFont.load_default()


def screen_size():
    if IS_WIN:
        w, h = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        if w >= 800 and h >= 600:
            return w, h
    return 1920, 1080


def overlay_lines(cfg, now=None):
    now = now or datetime.now()
    lines = []
    if cfg["lock_show_date"]:
        lines.append(("date", format_date(now, {"date_format": cfg["lock_date_format"],
                                               "date_case": cfg["lock_date_case"]})))
    for t in (cfg["lock_text"] or "").splitlines():
        if t.strip():
            lines.append(("text", t.strip()))
    return lines


def compose(cfg, base_path, size=None, now=None):
    """Image finale de l'écran de verrouillage (PIL.Image)."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    W, H = size or screen_size()
    img = ImageOps.fit(Image.open(base_path).convert("RGB"), (W, H), Image.LANCZOS)
    k = H / 1080
    if cfg["lock_blur"]:
        img = img.filter(ImageFilter.GaussianBlur(cfg["lock_blur"] * k))
    if cfg["lock_dim"]:
        img = ImageEnhance.Brightness(img).enhance(max(0.1, 1 - cfg["lock_dim"] / 100))

    lines = overlay_lines(cfg, now)
    if not lines:
        return img
    big = load_font(cfg["lock_font"], max(12, int(cfg["lock_size"] * k)), cfg["lock_bold"])
    small = load_font(cfg["lock_font"], max(10, int(cfg["lock_size"] * 0.5 * k)), False)
    draw = ImageDraw.Draw(img)
    blocks = []
    for kind, txt in lines:
        font = big if kind == "date" else small
        box = draw.textbbox((0, 0), txt, font=font)
        blocks.append((txt, font, box[2] - box[0], box[3] - box[1], box))
    gap = int(12 * k)
    total_h = sum(b[3] for b in blocks) + gap * (len(blocks) - 1)
    max_w = max(b[2] for b in blocks)
    margin_x, margin_y = int(W * 0.05), int(H * 0.08)
    pos = cfg["lock_pos"]
    y = {"top": margin_y, "center": (H - total_h) // 2}.get(pos.split("_")[0], H - margin_y - total_h)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shadow)
    for txt, font, w, h, box in blocks:
        if pos.endswith("left"):
            x = margin_x
        elif pos.endswith("right"):
            x = W - margin_x - w
        else:
            x = (W - w) // 2
        xy = (x - box[0], y - box[1])
        dl.text(xy, txt, font=font, fill=cfg["lock_color"])
        if cfg["lock_shadow"]:
            ds.text((xy[0] + 2 * k, xy[1] + 3 * k), txt, font=font, fill=(0, 0, 0, 170))
        y += h + gap
    base = img.convert("RGBA")
    if cfg["lock_shadow"]:
        base = Image.alpha_composite(base, shadow.filter(ImageFilter.GaussianBlur(6 * k)))
    return Image.alpha_composite(base, layer).convert("RGB")


# --------------------------------------------------------------------------- #
#  Application à Windows
# --------------------------------------------------------------------------- #
_PS_SET_LOCK = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
$asOp = ($m | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAct = ($m | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.System.UserProfile.LockScreen, Windows.System.UserProfile, ContentType = WindowsRuntime]
$t = $asOp.MakeGenericMethod([Windows.Storage.StorageFile]).Invoke($null, @([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:DM_LOCK_PATH)))
$t.Wait(-1) | Out-Null
$a = $asAct.Invoke($null, @([Windows.System.UserProfile.LockScreen]::SetImageFileAsync($t.Result)))
$a.Wait(-1) | Out-Null
'OK'
"""


def apply_image(img):
    """Enregistre l'image et l'applique à l'écran de verrouillage. Retourne son chemin."""
    if not IS_WIN:
        raise OSError("Écran de verrouillage : Windows uniquement")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # nouveau nom à chaque fois : Windows met les images en cache selon leur chemin
    path = OUT_DIR / f"verrouillage-{datetime.now():%Y%m%d-%H%M%S}.jpg"
    img.save(path, quality=93)
    for old in OUT_DIR.glob("verrouillage-*.jpg"):
        if old != path:
            old.unlink(missing_ok=True)
    env = dict(os.environ, DM_LOCK_PATH=str(path))
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SET_LOCK],
                         capture_output=True, text=True, env=env, timeout=60,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    if "OK" not in res.stdout:
        raise OSError((res.stderr or res.stdout or "échec inconnu").strip().splitlines()[-1])
    # l'image choisie ne doit pas être remplacée par « Windows à la une »
    _set_dword(CDM_KEY, "RotatingLockScreenEnabled", 0)
    return str(path)


def _set_dword(key, name, value):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))


def _get(key, name, default=None):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def tips_enabled():
    return IS_WIN and _get(CDM_KEY, "RotatingLockScreenOverlayEnabled", 1) != 0


def set_tips(enabled):
    """Astuces, informations et publicités de Windows sur l'écran de verrouillage."""
    for name in ("RotatingLockScreenOverlayEnabled", "SubscribedContent-338387Enabled"):
        _set_dword(CDM_KEY, name, 1 if enabled else 0)


def clock_24h():
    return not IS_WIN or "H" in (_get(INTL_KEY, "sShortTime", "HH:mm") or "HH:mm")


def set_clock_24h(h24):
    """Format de l'heure de Windows (écran de verrouillage, barre des tâches…)."""
    values = {"sShortTime": "HH:mm" if h24 else "h:mm tt", "sTimeFormat": "HH:mm:ss" if h24 else "h:mm:ss tt",
              "iTime": "1" if h24 else "0"}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTL_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for name, val in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    # prévient Windows du changement (WM_SETTINGCHANGE « intl »)
    res = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "intl", 0x0002, 1000, ctypes.byref(res))

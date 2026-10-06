# -*- coding: utf-8 -*-
"""Profils de réglages (Travail, Jeu, Minimal…) et thème assorti au fond d'écran."""

import colorsys
import ctypes
import json
import os
import re
import sys
from pathlib import Path

from core import CONFIG_DIR, DEFAULTS, IS_WIN, SHOW_ITEMS, blend

PROFILE_DIR = CONFIG_DIR / "profiles"

# réglages propres à la machine / au classement : jamais remplacés par un profil
NOT_IN_PROFILE = {"org_assign", "org_order", "org_hidden", "org_custom", "org_icons_hidden_by_app",
                  "update_repo", "update_auto", "update_skip", "profile", "widgets_hidden",
                  "wallpaper_last", "lock_last_date", "quick_note", "card_pos", "calendar_ics",
                  "autostart_done", "ctx_on", "ctx_battery_profile", "ctx_night_profile", "ctx_night_from",
                  "ctx_night_to", "ctx_base", "user_name",
                  "assistant_name", "onboarded", "wake_aliases"}

# profils proposés par défaut : appliqués PAR-DESSUS les réglages actuels
PRESETS = {
    "Travail": {
        "mac_theme": "light", "accent_mode": "custom", "accent_color": "#2F6FED", "layout": "cards",
        "org_enabled": True, "alerts": True, "card_desktop": True,
        "cards": ["clock", "calendar", "system", "storage", "network", "weather"],
        "org_cat_state": {"Jeux": "hide", "Multimédia": "hide"},
    },
    "Jeu": {
        "mac_theme": "dark", "accent_mode": "custom", "accent_color": "#00FFC8", "layout": "cards",
        "org_enabled": True, "alerts": True, "alert_gputemp_on": True, "card_desktop": False,
        "org_cat_state": {"Bureautique": "hide", "Développement": "hide", "Système": "hide",
                          "Utilitaires": "hide", "Fichiers": "hide"},
    },
    "Minimal": {
        "layout": "minimal", "accent_mode": "system", "org_enabled": False,
    },
}
PRESET_VERSION = 2   # profils d'exemple réécrits quand leur contenu change


def _safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "Profil"


class ProfileManager:
    def __init__(self):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        for name, data in PRESETS.items():  # 1er lancement : profils d'exemple
            path = PROFILE_DIR / f"{name}.json"
            try:   # ancien profil d'exemple (couleurs réglées une à une) : remplacé
                old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            except (OSError, ValueError):
                old = None
            if old is None or (old.get("_preset") and old.get("_preset_v", 1) < PRESET_VERSION):
                path.write_text(json.dumps({"_preset": True, "_preset_v": PRESET_VERSION, **data}, indent=2, ensure_ascii=False),
                                encoding="utf-8")

    def names(self):
        return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))

    def load(self, name):
        try:
            return json.loads((PROFILE_DIR / f"{_safe_name(name)}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, name, cfg):
        data = {k: v for k, v in cfg.items() if k not in NOT_IN_PROFILE}
        path = PROFILE_DIR / f"{_safe_name(name)}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path.stem

    def delete(self, name):
        try:
            (PROFILE_DIR / f"{_safe_name(name)}.json").unlink()
        except OSError:
            pass

    @staticmethod
    def merge_into(cfg, data):
        """Applique un profil (complet ou partiel) sur la configuration."""
        for k, v in data.items():
            if k.startswith("_") or k in NOT_IN_PROFILE or k not in DEFAULTS:
                continue
            if isinstance(v, dict) and isinstance(cfg.get(k), dict) and k in ("show",):
                cfg[k].update(v)
            else:
                cfg[k] = json.loads(json.dumps(v))

    @staticmethod
    def export(cfg, path):
        Path(path).write_text(json.dumps({"_deskmonitor_export": 1, **cfg}, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    @staticmethod
    def import_file(cfg, path):
        """Remplace tous les réglages par ceux d'un fichier exporté (y compris le classement)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not any(k in DEFAULTS for k in data):
            raise ValueError("Ce fichier ne contient pas de réglages DeskMonitor.")
        for k, v in data.items():
            if k in DEFAULTS and k not in ("org_icons_hidden_by_app",):
                if k == "show" and isinstance(v, dict):
                    cfg["show"].update({s: bool(b) for s, b in v.items() if s in SHOW_ITEMS})
                else:
                    cfg[k] = v


# --------------------------------------------------------------------------- #
#  Thème assorti au fond d'écran
# --------------------------------------------------------------------------- #
def wallpaper_path():
    if sys.platform == "darwin":
        from wallpapers import current_wallpaper
        p = current_wallpaper()
        return p if p and os.path.isfile(p) else None
    if not IS_WIN:
        return None
    buf = ctypes.create_unicode_buffer(520)
    if ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0) and os.path.isfile(buf.value):
        return buf.value  # SPI_GETDESKWALLPAPER
    cached = Path(os.getenv("APPDATA", "")) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
    return str(cached) if cached.is_file() else None


def wallpaper_signature():
    p = wallpaper_path()
    try:
        return f"{p}|{os.path.getmtime(p)}" if p else None
    except OSError:
        return None


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def theme_from_wallpaper(path=None):
    """Calcule un thème (fond sombre teinté + couleur d'accent vive) à partir du fond d'écran."""
    from PIL import Image
    path = path or wallpaper_path()
    if not path:
        raise OSError("Fond d'écran introuvable")
    img = Image.open(path).convert("RGB")
    img.thumbnail((160, 160))
    pal = img.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    palette = pal.getpalette()[:30]
    counts = sorted(pal.getcolors(), reverse=True)  # [(nb pixels, index)]
    colors = []
    for n, idx in counts:
        r, g, b = (palette[idx * 3 + i] / 255 for i in range(3))
        colors.append((n, colorsys.rgb_to_hsv(r, g, b)))
    total = sum(n for n, _ in colors) or 1

    # fond : teinte de la couleur dominante, très sombre et peu saturée
    h0, s0, _ = colors[0][1]
    bg = colorsys.hsv_to_rgb(h0, min(0.45, s0 * 0.7), 0.11)
    # accent : couleur la plus vive et présente (saturation × luminosité × fréquence)
    best = max(colors, key=lambda c: (c[1][1] ** 1.2) * (c[1][2] ** 0.8) * ((c[0] / total) ** 0.25))
    h, s, v = best[1]
    if s < 0.15:  # fond d'écran presque gris : accent bleu par défaut
        h, s = 0.55, 0.6
    accent = colorsys.hsv_to_rgb(h, max(0.55, min(0.9, s)), max(0.85, v))
    text = colorsys.hsv_to_rgb(h0, 0.06, 0.94)
    warn = "#FFC107" if (h < 0.06 or h > 0.94) else "#FF5C5C"  # accent rouge : alerte en jaune
    bg_hex, acc_hex, text_hex = _hex(bg), _hex(accent), _hex(text)
    return {"bg_color": bg_hex, "text_color": text_hex, "accent_color": acc_hex,
            "clock_color": text_hex, "date_color": acc_hex, "warn_color": warn,
            "bar_bg": blend(bg_hex, text_hex, 0.12)}

# -*- coding: utf-8 -*-
"""Constantes, configuration et utilitaires partagés par tous les modules de DeskMonitor."""

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
if IS_WIN:
    import winreg

APP_NAME = "DeskMonitor"
APP_VERSION = "1.9.0"
HIST_LEN = 60  # nombre de mesures conservées pour les graphiques
if IS_WIN:
    CONFIG_DIR = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
elif IS_MAC:
    CONFIG_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
else:
    CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"

# Polices par défaut selon le système
UI_FONT = "Segoe UI" if IS_WIN else "Helvetica Neue" if IS_MAC else "Helvetica"
LIGHT_FONT = "Segoe UI Light" if IS_WIN else UI_FONT
# cartes et paramètres : chiffres d'instrument (DIN) et texte humaniste
NUM_FONT = "Bahnschrift" if IS_WIN else "DIN Alternate" if IS_MAC else "DejaVu Sans"
TEXT_FONT = "Segoe UI" if IS_WIN else "Avenir Next" if IS_MAC else "Helvetica"

# Clic droit : bouton 3 sous Windows/Linux ; bouton 2 ou Ctrl+clic sur Mac
RIGHT_CLICK = ("<Button-2>", "<Control-Button-1>") if IS_MAC else ("<Button-3>",)


def bind_right_click(widget, func):
    for ev in RIGHT_CLICK:
        widget.bind(ev, func)


def open_path(path):
    """Ouvre un fichier, un dossier, une application ou une adresse web avec le programme par défaut."""
    path = str(path)
    if IS_WIN:
        os.startfile(path)
    elif IS_MAC:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_in_folder(path):
    """Affiche le fichier dans l'Explorateur / le Finder."""
    if IS_WIN:
        subprocess.Popen(["explorer.exe", "/select,", str(path)])
    elif IS_MAC:
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])

JOURS_COURTS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.",
               "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

THEMES = {
    "Nuit":   {"bg_color": "#12161F", "text_color": "#E8ECF3", "accent_color": "#4FC3F7",
               "clock_color": "#E8ECF3", "date_color": "#4FC3F7",
               "warn_color": "#FF5C5C", "bar_bg": "#262D3B"},
    "Clair":  {"bg_color": "#F5F6F8", "text_color": "#1D2330", "accent_color": "#2F6FED",
               "clock_color": "#1D2330", "date_color": "#2F6FED",
               "warn_color": "#D93636", "bar_bg": "#DDE1E8"},
    "Néon":   {"bg_color": "#0B0B12", "text_color": "#E0FFF9", "accent_color": "#00FFC8",
               "clock_color": "#E0FFF9", "date_color": "#00FFC8",
               "warn_color": "#FF2E88", "bar_bg": "#1C1C2B"},
    "Sunset": {"bg_color": "#1E1321", "text_color": "#FFE9DC", "accent_color": "#FF9F43",
               "clock_color": "#FFE9DC", "date_color": "#FF9F43",
               "warn_color": "#FF4757", "bar_bg": "#3A2638"},
    "Forêt":  {"bg_color": "#101A14", "text_color": "#E3F2E6", "accent_color": "#66D38E",
               "clock_color": "#E3F2E6", "date_color": "#66D38E",
               "warn_color": "#FF6B6B", "bar_bg": "#213328"},
}

# formats de date : clé -> fonction(datetime) ; le 1er espace sépare le jour du reste
DATE_FORMATS = {
    "long": lambda d: f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}",
    "long_noyear": lambda d: f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}",
    "medium": lambda d: f"{d.day} {MOIS[d.month - 1]} {d.year}",
    "short": lambda d: f"{JOURS_COURTS[d.weekday()]} {d.day} {MOIS_COURTS[d.month - 1]} {d.year}",
    "short_noyear": lambda d: f"{JOURS_COURTS[d.weekday()]} {d.day} {MOIS_COURTS[d.month - 1]}",
    "numeric_day": lambda d: f"{JOURS[d.weekday()]} {d:%d/%m/%Y}",
    "numeric": lambda d: f"{d:%d/%m/%Y}",
    "iso": lambda d: f"{d:%Y-%m-%d}",
}
WITH_WEEKDAY = {"long", "long_noyear", "short", "short_noyear", "numeric_day"}
DATE_CASES = {"normal": "Normale", "upper": "MAJUSCULES", "lower": "minuscules", "title": "Chaque Mot"}
ALIGNS = {"left": "Gauche", "center": "Centré", "right": "Droite"}


def format_date(d, cfg):
    key = cfg.get("date_format", "long")
    txt = DATE_FORMATS.get(key, DATE_FORMATS["long"])(d)
    case = cfg.get("date_case", "normal")
    if case == "upper":
        txt = txt.upper()
    elif case == "lower":
        txt = txt.lower()
    elif case == "title":
        txt = " ".join(w[:1].upper() + w[1:] for w in txt.split(" "))
    else:
        txt = txt[:1].upper() + txt[1:]
    if cfg.get("date_two_lines") and key in WITH_WEEKDAY:
        txt = txt.replace(" ", "\n", 1)
    if cfg.get("date_week"):
        sem = "SEMAINE" if case == "upper" else "semaine" if case == "lower" else "Semaine"
        txt += f" · {sem} {d.isocalendar()[1]}"
    return txt


def version_tuple(v):
    """'v1.2.10' -> (1, 2, 10) pour comparer des versions."""
    parts = []
    for p in str(v).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts + [0] * (3 - len(parts)))


def apply_corners(win, rounded):
    """Coins arrondis natifs de Windows 11 (lissés) ; région arrondie en repli sous Windows 10."""
    if not IS_WIN:
        return
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        pref = ctypes.c_int(2 if rounded else 1)  # DWMWCP_ROUND / DWMWCP_DONOTROUND
        ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(pref), 4) == 0
        if not ok:  # Windows 10 : région (bords non lissés)
            rgn = None
            if rounded:
                w, h = win.winfo_width() or win.winfo_reqwidth(), win.winfo_height() or win.winfo_reqheight()
                r = int(16 * win.winfo_fpixels("1i") / 96)
                rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
            user32.SetWindowRgn(ctypes.c_void_p(hwnd), rgn, True)
    except (OSError, AttributeError):
        pass


def _hwnd(win):
    u = ctypes.windll.user32
    u.GetParent.restype = ctypes.c_void_p
    u.GetParent.argtypes = [ctypes.c_void_p]
    return u.GetParent(win.winfo_id()) or win.winfo_id()


def win_blur(win, enable=True, tint="#151A20", opacity=0.8):
    """Windows 10/11 : verre dépoli « acrylique » derrière la fenêtre, teinté de la couleur `tint`.
    Il n'apparaît que sous les zones TRANSPARENTES de la fenêtre (couleur -transparentcolor) : le fond de la
    carte doit donc être transparent, le texte et les jauges restant opaques par-dessus."""
    if not IS_WIN:
        return False
    a = max(0x30, min(0xF2, int(opacity * 255)))
    r, g, b = (int(tint[i:i + 2], 16) for i in (1, 3, 5))
    color = (a << 24) | (b << 16) | (g << 8) | r   # ABGR

    class ACCENT(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class WCAD(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]
    try:
        win.update_idletasks()
        accent = ACCENT(4 if enable else 0, 2, color, 0)   # 4 = ACCENT_ENABLE_ACRYLICBLURBEHIND, 0 = désactivé
        data = WCAD(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))  # 19 = WCA_ACCENT_POLICY
        f = ctypes.windll.user32.SetWindowCompositionAttribute
        f.argtypes = [ctypes.c_void_p, ctypes.POINTER(WCAD)]
        return bool(f(ctypes.c_void_p(_hwnd(win)), ctypes.byref(data)))
    except (OSError, AttributeError):
        return False


def no_activate(win):
    """Cliquer sur le widget ne l'« active » pas : Windows ne fait donc plus remonter
    tous les widgets de l'application devant les autres fenêtres (effet de clignotement)."""
    if not IS_WIN:
        return
    try:
        win.update_idletasks()
        u = ctypes.windll.user32
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = _hwnd(win)
        ex = u.GetWindowLongPtrW(hwnd, -20)
        if not ex & 0x08000000:  # WS_EX_NOACTIVATE
            u.SetWindowLongPtrW(hwnd, -20, ex | 0x08000000)
    except (OSError, AttributeError):
        pass


def bring_to_front(win):
    """À utiliser avant un menu contextuel : Windows exige que la fenêtre soit au premier plan."""
    if IS_WIN:
        try:
            ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(_hwnd(win)))
        except (OSError, AttributeError):
            pass


def log_exception(context="", exc_info=None):
    """Ajoute l'erreur en cours au journal erreurs.log (limité à ~200 Ko)."""
    import traceback
    from datetime import datetime
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_FILE = CONFIG_DIR / "erreurs.log"
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 200_000:
            LOG_FILE.write_text(LOG_FILE.read_text(encoding="utf-8", errors="replace")[-100_000:], encoding="utf-8")
        text = "".join(traceback.format_exception(*(exc_info or sys.exc_info())))
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] v{APP_VERSION} {context}\n{text}")
    except Exception:  # noqa: BLE001
        pass


def ensure_visible(win):
    """Garde-fou : si Windows considère la fenêtre comme cachée alors que Tk la croit affichée
    (après une veille, un démarrage, un changement d'écran…), on la réaffiche et on la redessine.
    Retourne True si une réparation a été nécessaire."""
    if not IS_WIN:
        return False
    try:
        if not win.winfo_exists() or win.state() == "withdrawn":
            return False
        u = ctypes.windll.user32
        u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        hwnd = _hwnd(win)
        if u.IsWindowVisible(hwnd):
            return False
        u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        u.RedrawWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        u.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0400)  # tout redessiner
        return True
    except Exception:  # noqa: BLE001
        return False


def cfg_signature(cfg, keys=(), prefixes=()):
    """Empreinte d'une partie des réglages : on ne reconstruit un widget que si elle change."""
    items = [(k, cfg.get(k)) for k in keys]
    if prefixes:
        items += [(k, v) for k, v in sorted(cfg.items()) if k.startswith(tuple(prefixes))]
    return json.dumps(items, sort_keys=True, default=str)


# réglages qui changent l'aspect de TOUS les widgets
STYLE_KEYS = ("bg_color", "text_color", "accent_color", "warn_color", "bar_bg", "opacity", "rounded", "border",
              "topmost", "font_family", "text_size", "mac_theme", "card_blur", "card_radius", "card_text_scale")


def hide_from_taskbar(win):
    """Retire la fenêtre de la barre des tâches et d'Alt+Tab (style « fenêtre outil »)."""
    if not IS_WIN:
        return
    try:
        win.update_idletasks()
        u = ctypes.windll.user32
        u.GetParent.restype = ctypes.c_void_p
        u.GetParent.argtypes = [ctypes.c_void_p]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        ex = u.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
        new = (ex | 0x80) & ~0x40000         # + WS_EX_TOOLWINDOW, - WS_EX_APPWINDOW
        if new != ex:
            u.SetWindowLongPtrW(hwnd, -20, new)
            return True  # la fenêtre doit être masquée puis réaffichée pour que la barre se mette à jour
    except (OSError, AttributeError):
        pass
    return False


def make_icon_image(size=256, accent="#4FC3F7", bg="#12161F"):
    """Icône de l'application (carré arrondi + mini graphique), dessinée avec Pillow."""
    from PIL import Image, ImageDraw
    s = size * 4  # sur-échantillonnage pour des bords lisses
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=bg)
    d.rounded_rectangle((int(s * .04),) * 2 + (int(s * .96),) * 2, radius=int(s * 0.19),
                        outline=accent, width=max(4, int(s * 0.03)))
    base, w = int(s * 0.76), int(s * 0.13)
    for i, hgt in enumerate((0.26, 0.44, 0.34, 0.54)):
        x = int(s * 0.19) + i * int(s * 0.165)
        d.rounded_rectangle((x, base - int(s * hgt), x + w, base), radius=int(w * 0.35),
                            fill=accent if i == 3 else blend(accent, bg, 0.35))
    return img.resize((size, size), Image.LANCZOS)


def blend(c1, c2, t):
    """Mélange deux couleurs #RRGGBB (t=0 → c1, t=1 → c2)."""
    try:
        a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, TypeError):
        return c1
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def font_spec(family, size, bold=False, italic=False):
    return (family, int(size), *(["bold"] if bold else []), *(["italic"] if italic else []))


SHOW_ITEMS = {
    "clock": "Heure", "date": "Date", "cpu": "Processeur (CPU)", "ram": "Mémoire (RAM)",
    "gpu": "Carte graphique (GPU)", "disks": "Disques", "net": "Réseau (débit)",
    "ping": "Ping (latence internet)", "ip_local": "IP locale", "ip_public": "IP publique",
    "battery": "Batterie", "uptime": "Temps d'activité", "buttons": "Boutons d'action",
}
HIDDEN_BY_DEFAULT = {"ip_local", "ip_public"} | ({"gpu"} if IS_MAC else set())  # GPU : Windows seulement

DETACHABLE = {"clock": "Heure", "date": "Date"}

DEFAULTS = {
    "clock_font": LIGHT_FONT,
    "font_family": UI_FONT,
    "clock_size": 40,
    "clock_bold": False,
    "clock_italic": False,
    "clock_align": "left",
    "date_font": UI_FONT,
    "date_size": 13,
    "date_bold": False,
    "date_italic": False,
    "date_align": "left",
    "date_format": "long",
    "date_case": "normal",
    "date_week": False,
    "date_two_lines": False,
    "text_size": 10,
    **THEMES["Nuit"],
    "opacity": 90,
    "transparent_bg": False,
    "width": 300,
    "show_seconds": True,
    "clock_24h": True,
    "show": {k: k not in HIDDEN_BY_DEFAULT for k in SHOW_ITEMS},
    "graphs": True,
    "ping_host": "1.1.1.1",
    "refresh_ms": 1000,
    "warn_threshold": 85,
    "topmost": False,
    "locked": False,
    "clean_browsers": True,
    "clean_recycle": False,
    "detach_clock": False,
    "detach_date": False,
    "transparent_clock": False,
    "transparent_date": False,
    # alertes
    "alerts": True,
    "alert_sound": True,
    "alert_cooldown": 10,
    "alert_cpu_on": True, "alert_cpu": 90, "alert_cpu_secs": 30,
    "alert_ram_on": True, "alert_ram": 90,
    "alert_disk_on": True, "alert_disk_gb": 10,
    "alert_bat_on": True, "alert_bat": 20,
    "alert_gputemp_on": True, "alert_gputemp": 85,
    "alert_offline_on": True,
    # bureau organisé
    "org_enabled": False,
    "org_source": "apps",      # "apps" : toutes les applications ; "desktop" : le bureau seulement
    "org_max_rows": 2,         # lignes visibles par panneau (défilement au-delà, 0 = illimité)
    "org_columns": 4,
    "org_icon": 40,
    "org_hide_icons": True,
    "org_system": True,
    "org_assign": {},
    "org_order": {},
    "org_hidden": [],
    "org_custom": [],
    "org_collapsed": ["Système"],
    "org_cat_state": {},       # {panneau: "hide" (masqué) | "remove" (supprimé, apps -> Autres)}
    "org_icons_hidden_by_app": False,
    "org_cat_style": {},       # {panneau: {"accent": "#RRGGBB", "opacity": 90}}
    "org_labels": True,        # noms sous les icônes
    "org_double_click": False, # ouvrir avec un double-clic plutôt qu'un clic
    # apparence générale
    "rounded": True,           # coins arrondis (Windows 11)
    "border": False,           # liseré de couleur d'accent autour des widgets
    "padding": 16,             # marge intérieure du widget de monitoring
    "bar_height": 5,
    "graph_height": 26,
    "graph_fill": True,
    "buttons_style": "both",   # "both" (icône + texte), "icon", "text"
    "clock_blink": False,      # « : » clignotant
    "theme_auto_wallpaper": False,
    "widgets_hidden": False,
    # fonds d'écran
    "wallpaper_fit": "fill",
    "wallpaper_last": "",
    "wallpaper_lock_too": False,   # appliquer aussi l'image choisie à l'écran de verrouillage
    "slideshow": False,
    "slideshow_minutes": 30,
    "slideshow_shuffle": True,
    # écran de verrouillage
    "lock_enabled": False,         # DeskMonitor gère l'image de l'écran de verrouillage
    "lock_image": "",              # "" = même image que le fond d'écran
    "lock_show_date": True,
    "lock_date_format": "long",
    "lock_date_case": "normal",
    "lock_text": "",
    "lock_font": LIGHT_FONT,
    "lock_bold": False,
    "lock_size": 56,
    "lock_color": "#FFFFFF",
    "lock_pos": "bottom_left",
    "lock_dim": 20,
    "lock_blur": 0,
    "lock_shadow": True,
    "lock_last_date": "",
    # macOS : cartes façon widgets Apple
    "layout": "cards",           # cards | strip | minimal | classic (cartes aussi par défaut sous Windows)
    "cards": ["clock", "system", "storage", "battery", "network"],
    "cards_cols": 2,             # colonnes de cartes ; les suivantes s'empilent en dessous
    "cards_layout_v": 2,
    "cards_corner": "tl",
    "card_pos": {},
    "card_compact": True,        # remplit les cases vides en rapprochant les petites cartes
    "card_text_scale": 100,      # taille du texte des cartes, en %
    "calendar_ics": "",          # lien ICS (Google Agenda, Outlook.com…) pour la carte Agenda
    "autostart_done": False,     # démarrage automatique proposé au 1er lancement (Mac)
    # assistant
    "onboarded": False,          # écran d'accueil déjà passé
    "user_name": "",
    "assistant_name": "Jarvis",
    "listen_hotkey": "cmd+alt+j" if IS_MAC else "ctrl+alt+j",
    "wake_on": False,
    "migrated": 0,               # dernière migration des réglages appliquée (voir DeskWidget._migrate)
    "wake_aliases": [],          # façons dont la reconnaissance écrit le nom (apprises avec votre voix)            # activation par la voix (dire le nom de l'assistant)
    "wake_battery_off": True,    # coupée sur batterie
    "wake_night_off": False,     # coupée pendant les heures de silence (non par défaut : les heures de
                                 # silence empêchent l'assistant de PARLER de lui-même, pas de vous écouter)
    # voix
    "voice_on": True,
    "voice_recap": True,         # récapitulatif parlé au lancement
    "voice_alerts": True,        # annonce quand une valeur passe dans le rouge
    "voice_lang": "fr",          # langue des annonces : fr | en
    "voice_name": "",            # vide : meilleure voix disponible dans la langue choisie
    "voice_rate": 185,           # mots par minute
    "voice_quiet": True,         # silence la nuit
    "voice_quiet_from": 22,
    "voice_quiet_to": 7,
    # profils automatiques
    "ctx_on": False,
    "ctx_battery_profile": "",   # profil appliqué quand le portable est sur batterie
    "ctx_night_profile": "",     # profil appliqué la nuit
    "ctx_night_from": 21,
    "ctx_night_to": 7,
    "ctx_base": "",              # profil à restaurer quand la règle ne s'applique plus
    "card_free": False,          # placement libre ; sinon les cartes restent alignées sur la grille
    "card_blur": True,           # flou natif (vibrancy)
    "card_radius": 22,
    "card_all_spaces": True,     # visible sur tous les bureaux
    "card_desktop": False,       # derrière les fenêtres, au niveau du bureau
    "card_menubar": True,        # CPU / RAM / réseau dans la barre des menus
    "card_hotkey": "cmd+alt+d" if IS_MAC else "ctrl+alt+d",  # afficher / masquer les widgets
    "card_system_accent": True,  # couleur d'accentuation de macOS
    "mac_theme": "auto",         # auto | dark | light : thème de TOUS les widgets
    "accent_mode": "system",
    "animations": True,          # apparitions, survols, glissements et compteurs animés     # system (couleur du système) | custom (accent_color) | wallpaper (fond d'écran)
    "weather_city": "",          # vide = d'après l'adresse IP
    "quick_note": "",
    "native_alerts": True,       # notifications du centre de notifications macOS
    # fond d'écran vivant
    "wp_dyn_time": False,        # teinte selon l'heure
    "wp_dyn_state": False,       # ambiance selon l'état (CPU, batterie, hors ligne)
    "wp_dyn_stats": False,       # jauges dessinées sur le fond
    "wp_dyn_applied": False,     # une image retouchée par le fond vivant est au bureau
    # profils et mises à jour
    "profile": "",
    "update_repo": "AlphoBakos/DeskMonitor-App",       # dépôt GitHub « utilisateur/projet » publiant les versions
    "update_auto": True,
    "update_skip": "",
    "x": None,
    "y": None,
    "positions": {},
}


# --------------------------------------------------------------------------- #
#  Utilitaires
# --------------------------------------------------------------------------- #
def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        show = data.pop("show", {})
        # anciennes versions : l'heure suivait la couleur du texte, la date l'accent
        data.setdefault("clock_color", data.get("text_color", cfg["text_color"]))
        data.setdefault("date_color", data.get("accent_color", cfg["accent_color"]))
        data.setdefault("date_font", data.get("font_family", cfg["font_family"]))
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        if data.get("cards_layout_v", 1) < 2:  # v1 : bandeau / grille horizontale → colonnes empilées
            cfg["cards_cols"], cfg["cards_layout_v"], cfg["card_pos"] = 2, 2, {}
            if cfg["layout"] == "strip":
                cfg["layout"] = "cards"
        cfg["show"].update({k: bool(v) for k, v in show.items() if k in SHOW_ITEMS})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def fmt_bytes(n):
    n = float(n)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024 or unit == "To":
            txt = f"{n:.0f}" if unit in ("o", "Ko") else f"{n:.1f}"
            return f"{txt.replace('.', ',')} {unit}"
        n /= 1024


def fmt_duration(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} j {h} h {m:02d} min"
    return f"{h} h {m:02d} min"


def no_window_flags():
    return subprocess.CREATE_NO_WINDOW if IS_WIN else 0


def run_cmd(args):
    res = subprocess.run(args, capture_output=True, creationflags=no_window_flags())
    enc = "oem" if IS_WIN else "utf-8"
    return res.returncode, res.stdout.decode(enc, errors="replace")


def is_admin():
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def launch_command():
    """(exécutable, arguments) permettant de relancer l'application."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    script = Path(__file__).resolve().with_name("desk_monitor.py")
    return str(pyw if pyw.exists() else exe), f'"{script}"'


# ----- Version Microsoft Store (paquet MSIX) ------------------------------- #
_PACKAGED = None


def is_packaged():
    """Vrai si l'application tourne en version Microsoft Store (paquet MSIX). Le Store gère alors les mises à
    jour, et le lancement au démarrage passe par la « tâche de démarrage » déclarée dans le paquet."""
    global _PACKAGED
    if _PACKAGED is None:
        _PACKAGED = False
        if IS_WIN:
            try:
                n = ctypes.c_uint32(0)
                # 15700 = APPMODEL_ERROR_NO_PACKAGE : application classique (installateur .exe)
                _PACKAGED = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None) != 15700
            except (AttributeError, OSError):
                _PACKAGED = False
    return _PACKAGED


STARTUP_TASK_ID = "DeskMonitorStartup"   # identique à AppxManifest.xml


def _wait(op):
    """Attend une opération asynchrone de Windows (winsdk) depuis du code ordinaire."""
    import asyncio

    async def run():
        return await op
    return asyncio.run(run())


def _startup_task():
    from winsdk.windows.applicationmodel import StartupTask
    return _wait(StartupTask.get_async(STARTUP_TASK_ID))


# ----- Démarrage automatique ------------------------------------------------ #
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MAC_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.deskmonitor.app.plist"


def is_autostart():
    if IS_MAC:
        return MAC_AGENT.exists()
    if not IS_WIN:
        return False
    if is_packaged():
        try:
            from winsdk.windows.applicationmodel import StartupTaskState
            return _startup_task().state in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)
        except Exception:  # noqa: BLE001
            return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    if IS_MAC:  # LaunchAgent : lancé à l'ouverture de session
        import plistlib
        if enabled:
            exe, args = launch_command()
            prog = [exe] + ([args.strip('"')] if args else [])
            MAC_AGENT.parent.mkdir(parents=True, exist_ok=True)
            with open(MAC_AGENT, "wb") as f:
                plistlib.dump({"Label": "com.deskmonitor.app", "ProgramArguments": prog,
                               "RunAtLoad": True, "ProcessType": "Interactive"}, f)
        else:
            MAC_AGENT.unlink(missing_ok=True)
        return
    if not IS_WIN:
        return
    if is_packaged():   # version Store : tâche de démarrage du paquet (le registre n'est pas utilisable)
        task = _startup_task()
        if enabled:
            state = _wait(task.request_enable_async())
            from winsdk.windows.applicationmodel import StartupTaskState
            if state == StartupTaskState.DISABLED_BY_USER:
                raise OSError("Le lancement au démarrage a été désactivé dans le Gestionnaire des tâches "
                              "(onglet Démarrage) : réactivez-le là-bas.")
        else:
            task.disable()
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            exe, args = launch_command()
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{exe}" {args}'.strip())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass

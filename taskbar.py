# -*- coding: utf-8 -*-
"""Barre des tâches de Windows : position de la zone de notification (pour y poser les mesures) et couleur de la
barre par l'option officielle « Afficher la couleur d'accentuation sur la barre des tâches »."""
import colorsys
import ctypes
import winreg
from ctypes import wintypes

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
DWM = r"Software\Microsoft\Windows\DWM"
ACCENT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
# valeurs modifiées pour colorer la barre : sauvegardées avant, remises à l'identique ensuite
COLOR_KEYS = [(PERSONALIZE, "ColorPrevalence"), (DWM, "AccentColor"),
              (ACCENT, "AccentColorMenu"), (ACCENT, "StartColorMenu")]

_u = ctypes.windll.user32
_u.FindWindowW.restype = _u.FindWindowExW.restype = ctypes.c_void_p
_u.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
_u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
_u.GetForegroundWindow.restype = ctypes.c_void_p
_u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_u.GetDC.restype = ctypes.c_void_p
_u.GetDC.argtypes = [ctypes.c_void_p]
_u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g = ctypes.windll.gdi32
_g.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_g.GetPixel.restype = wintypes.DWORD


def _rect(hwnd):
    r = wintypes.RECT()
    if not hwnd or not _u.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def geometry():
    """Barre principale : (gauche, haut, droite, bas), début de la zone de notification, fin des icônes
    d'applications. None si elle est introuvable ou pas en bas de l'écran."""
    tb = _u.FindWindowW("Shell_TrayWnd", None)
    bar = _rect(tb)
    tray = _rect(_u.FindWindowExW(tb, None, "TrayNotifyWnd", None))
    if not bar or not tray or bar[2] - bar[0] < bar[3] - bar[1]:   # barre verticale (rare) : pas géré
        return None
    apps = _rect(_u.FindWindowExW(tb, None, "ReBarWindow32", None))
    return {"bar": bar, "tray_left": tray[0], "apps_right": apps[2] if apps else bar[0]}


def foreground_class():
    h = _u.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(128)
    if h:
        _u.GetClassNameW(h, buf, 128)
    return buf.value


def pixel(x, y):
    """Couleur de l'écran en (x, y), en #rrggbb."""
    dc = _u.GetDC(None)
    try:
        c = _g.GetPixel(dc, x, y)
    finally:
        _u.ReleaseDC(None, dc)
    if c == 0xFFFFFFFF:   # hors écran
        return None
    return f"#{c & 0xFF:02x}{(c >> 8) & 0xFF:02x}{(c >> 16) & 0xFF:02x}"


# ----- couleur de la barre --------------------------------------------------------------------------------
def _get(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None


def _put(path, name, val):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        if val is None:
            try:
                winreg.DeleteValue(k, name)
            except OSError:
                pass
        else:
            winreg.SetValueEx(k, name, 0, val[1], val[0])


def light_mode():
    """Mode clair de Windows : la barre n'y prend pas la couleur d'accentuation (limite de Windows)."""
    v = _get(PERSONALIZE, "SystemUsesLightTheme")
    return bool(v and v[0])


def _broadcast():
    res = wintypes.DWORD()
    for s in ("ImmersiveColorSet", "WindowsThemeElement"):
        _u.SendMessageTimeoutW(0xFFFF, 0x1A, 0, s, 2, 1000, ctypes.byref(res))   # WM_SETTINGCHANGE


class _PREF(ctypes.Structure):
    _fields_ = [("crStartColor", wintypes.DWORD), ("crAccentColor", wintypes.DWORD)]


def _pref_funcs():
    """Fonctions de uxtheme utilisées par les Paramètres de Windows pour changer la couleur d'accentuation
    (écrire le registre seul ne suffit pas : Windows garde l'ancienne couleur en mémoire)."""
    ux = ctypes.WinDLL("uxtheme")
    get, put = ux[120], ux[122]   # GetUserColorPreference, SetUserColorPreference
    get.argtypes = put.argtypes = [ctypes.POINTER(_PREF), wintypes.BOOL]
    return get, put


def save_state():
    """Valeurs actuelles, à garder (format JSON) pour les remettre ensuite."""
    state = {f"{p}|{n}": (list(v) if v else None) for p, n in COLOR_KEYS for v in [_get(p, n)]}
    pref = _PREF()
    if _pref_funcs()[0](ctypes.byref(pref), False) == 0:
        state["pref"] = [pref.crStartColor, pref.crAccentColor]
    return state


def restore(saved):
    saved = dict(saved or {})
    pref = saved.pop("pref", None)
    if pref:
        _pref_funcs()[1](ctypes.byref(_PREF(*pref)), True)
    for key, v in saved.items():
        path, name = key.split("|")
        _put(path, name, tuple(v) if v else None)
    _broadcast()


def apply_color(hex_color):
    """Colore la barre (et le menu Démarrer) avec cette couleur."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    get, put = _pref_funcs()
    pref = _PREF()
    get(ctypes.byref(pref), False)
    pref.crAccentColor = 0xFF000000 | (b << 16) | (g << 8) | r
    put(ctypes.byref(pref), True)
    if (_get(PERSONALIZE, "ColorPrevalence") or (0,))[0] != 1:
        _put(PERSONALIZE, "ColorPrevalence", (1, winreg.REG_DWORD))
    _broadcast()


def image_color(path):
    """Couleur dominante et vive d'une image (pour une barre assortie au fond d'écran), ou None."""
    from PIL import Image
    with Image.open(path) as im:
        px = list(im.convert("RGB").resize((48, 27)).getdata())
    scored = sorted(px, key=lambda p: -(colorsys.rgb_to_hsv(*[c / 255 for c in p])[1] *
                                        colorsys.rgb_to_hsv(*[c / 255 for c in p])[2]))
    top = scored[:max(1, len(scored) // 6)]
    r, g, b = (sum(p[i] for p in top) / len(top) / 255 for i in range(3))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.12:   # image sans vraie couleur (noir, gris) : la barre reste normale
        return None
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.45), min(max(v, 0.55), 0.85))
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def distance(a, b):
    return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5))


def busy_columns(x0, x1, top, bottom, bg):
    """Colonnes de l'écran (de x0 à x1) où la barre affiche quelque chose (icône, point « ouvert »…) : la
    position des icônes donnée par Windows 11 est fausse, on regarde donc l'image de la barre elle-même."""
    from PIL import ImageGrab
    if x1 - x0 < 2:
        return []
    img = ImageGrab.grab((x0, top, x1, bottom), all_screens=True).convert("RGB")
    w, h = img.size
    px = img.load()
    ref = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5))
    ys = range(int(h * 0.2), int(h * 0.85), 3)
    return [x0 + x for x in range(w)
            if any(sum(abs(a - b) for a, b in zip(px[x, y], ref)) > 60 for y in ys)]

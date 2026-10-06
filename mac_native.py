# -*- coding: utf-8 -*-
"""Intégration native macOS (PyObjC) : flou « vibrancy », barre des menus, raccourci global, thème système.
Tout est facultatif : si PyObjC manque ou échoue, l'application garde son apparence classique."""
import ctypes
import subprocess
import sys

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

try:
    if not IS_MAC:
        raise ImportError
    import objc
    from AppKit import (NSApp, NSAppearance, NSColor, NSColorSpace, NSMenu, NSMenuItem, NSObject,
                        NSProcessInfo, NSStatusBar, NSUserDefaults, NSViewHeightSizable, NSViewWidthSizable,
                        NSVisualEffectBlendingModeBehindWindow, NSVisualEffectMaterialHUDWindow,
                        NSVisualEffectMaterialUnderWindowBackground, NSVisualEffectStateActive,
                        NSVisualEffectView, NSWindowBelow)
    AVAILABLE = True
except Exception:  # noqa: BLE001
    AVAILABLE = False

_NS_CACHE = {}


def nswindow(tkwin, title):
    """Retrouve la fenêtre native d'une fenêtre Tk (repérée par son titre, qui doit être unique)."""
    if not AVAILABLE:
        return None
    try:
        tkwin.title(title)
        tkwin.update_idletasks()
        for w in NSApp().windows():
            if str(w.title()) == title:
                return w
    except Exception:  # noqa: BLE001
        pass
    return None


def style_card(tkwin, title, radius=22, dark=True, all_spaces=True, desktop_level=False):
    """Fond translucide flouté, coins arrondis et ombre, comme les widgets macOS.
    Retourne True si le style natif a été appliqué."""
    w = nswindow(tkwin, title)
    if w is None:
        return False
    try:
        tkwin.tk.call("::tk::unsupported::MacWindowStyle", "style", tkwin, "plain", "none")
        tkwin.attributes("-transparent", True)
        tkwin.configure(bg="systemTransparent")
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(True)
        cv = w.contentView()
        frame = cv.superview()  # Tk dessine DANS la vue de contenu : le flou doit être derrière elle, pas dessus
        ve = _NS_CACHE.get(title)
        if ve is None or ve.superview() is None:
            ve = NSVisualEffectView.alloc().initWithFrame_(frame.bounds())
            ve.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            ve.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            ve.setState_(NSVisualEffectStateActive)
            ve.setWantsLayer_(True)
            frame.addSubview_positioned_relativeTo_(ve, NSWindowBelow, cv)
            _NS_CACHE[title] = ve
        ve.setMaterial_(NSVisualEffectMaterialHUDWindow if dark else NSVisualEffectMaterialUnderWindowBackground)
        ve.layer().setCornerRadius_(radius)
        ve.layer().setMasksToBounds_(True)
        name = "NSAppearanceNameVibrantDark" if dark else "NSAppearanceNameVibrantLight"
        w.setAppearance_(NSAppearance.appearanceNamed_(name))
        if all_spaces:
            # canJoinAllSpaces | stationary | ignoresCycle : visible sur tous les bureaux
            w.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 6))
        if desktop_level:
            w.setLevel_(-2147483623 + 1)  # juste au-dessus du fond d'écran (kCGDesktopWindowLevel + 1)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
#  Apparence du système
# ---------------------------------------------------------------------------
def system_is_dark():
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return True
    if not AVAILABLE:
        return True
    try:
        return str(NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")) == "Dark"
    except Exception:  # noqa: BLE001
        return True


def system_accent():
    """Couleur d'accentuation choisie dans Réglages Système / Paramètres Windows, en « #RRGGBB »."""
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
                v = winreg.QueryValueEx(k, "AccentColor")[0]  # format ABGR
            return "#%02X%02X%02X" % (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
        except OSError:
            return None
    if not AVAILABLE:
        return None
    try:
        c = NSColor.controlAccentColor().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
        return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in (c.redComponent(), c.greenComponent(),
                                                                       c.blueComponent()))
    except Exception:  # noqa: BLE001
        return None


def thermal_state():
    """0 nominal, 1 modéré, 2 élevé, 3 critique."""
    if not AVAILABLE:
        return 0
    try:
        return int(NSProcessInfo.processInfo().thermalState())
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
#  Presse-papiers
# ---------------------------------------------------------------------------
def clipboard_state():
    """(compteur de changements, texte) du presse-papiers, sans lancer de processus."""
    if not AVAILABLE:
        return 0, None
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        return int(pb.changeCount()), pb.stringForType_(NSPasteboardTypeString)
    except Exception:  # noqa: BLE001
        return 0, None


# ---------------------------------------------------------------------------
#  Barre des menus
# ---------------------------------------------------------------------------
if AVAILABLE:
    class _MenuTarget(NSObject):
        def initWithCallbacks_(self, callbacks):
            self = objc.super(_MenuTarget, self).init()
            self.callbacks = callbacks
            return self

        @objc.typedSelector(b"v@:@")
        def fire_(self, sender):
            fn = self.callbacks.get(int(sender.tag()))
            if fn:
                fn()


class MenuBarItem:
    """Texte en direct dans la barre des menus (CPU, RAM, réseau…) avec un petit menu."""

    def __init__(self, entries):
        """entries : liste de (libellé, fonction) ou None pour un séparateur."""
        self.ok = False
        if not AVAILABLE:
            return
        try:
            self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)  # variable
            self.callbacks = {}
            self.target = _MenuTarget.alloc().initWithCallbacks_(self.callbacks)
            menu = NSMenu.alloc().init()
            for i, e in enumerate(entries):
                if e is None:
                    menu.addItem_(NSMenuItem.separatorItem())
                    continue
                label, fn = e
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, "fire:", "")
                mi.setTag_(i)
                mi.setTarget_(self.target)
                self.callbacks[i] = fn
                menu.addItem_(mi)
            self.item.setMenu_(menu)
            self.ok = True
        except Exception:  # noqa: BLE001
            self.ok = False

    def set_text(self, text):
        if self.ok:
            try:
                self.item.button().setTitle_(text)
            except Exception:  # noqa: BLE001
                pass

    def remove(self):
        if self.ok:
            try:
                NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
            except Exception:  # noqa: BLE001
                pass
            self.ok = False


# ---------------------------------------------------------------------------
#  Raccourci clavier global (API Carbon : aucune autorisation requise)
# ---------------------------------------------------------------------------
KEYCODES = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
            "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37,
            "j": 38, "k": 40, "n": 45, "m": 46}
MODS = {"cmd": 0x0100, "shift": 0x0200, "alt": 0x0800, "ctrl": 0x1000}

# plusieurs raccourcis (« emplacements » 1, 2…), un seul gestionnaire Carbon installé une fois pour toutes
_HK = {"carbon": None, "handler": None, "refs": {}, "callbacks": {}, "types": None}
_WIN_HK = {}   # emplacement → identifiant du thread Windows


def _carbon():
    if _HK["carbon"] is None:
        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class HotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        proto = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        carbon.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                             ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]

        def handler(_call, event, _data):
            hk = HotKeyID()
            # kEventParamDirectObject ('----'), typeEventHotKeyID ('hkid')
            carbon.GetEventParameter(event, 0x2D2D2D2D, 0x686B6964, None, ctypes.sizeof(hk), None, ctypes.byref(hk))
            fn = _HK["callbacks"].get(hk.id)
            if fn:
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
            return 0

        cb = proto(handler)   # gardé en vie tant que l'application tourne
        spec_ev = EventTypeSpec(0x6B657962, 5)  # 'keyb', kEventHotKeyPressed
        carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, proto, ctypes.c_uint32,
                                               ctypes.POINTER(EventTypeSpec), ctypes.c_void_p, ctypes.c_void_p]
        carbon.InstallEventHandler(carbon.GetApplicationEventTarget(), cb, 1, ctypes.byref(spec_ev), None, None)
        carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, HotKeyID, ctypes.c_void_p,
                                               ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        _HK.update(carbon=carbon, handler=cb, types=HotKeyID)
    return _HK["carbon"]


def _register_hotkey_win(spec, callback, slot):
    """Windows : RegisterHotKey dans un thread dédié avec sa boucle de messages."""
    import threading
    from ctypes import wintypes
    parts = [p.strip().lower() for p in spec.split("+")]
    mods = {"alt": 0x1, "ctrl": 0x2, "cmd": 0x2, "shift": 0x4, "win": 0x8}
    try:
        flags = sum(mods[p] for p in parts[:-1]) | 0x4000  # MOD_NOREPEAT
        key = ord(parts[-1].upper()) if len(parts[-1]) == 1 else None
    except KeyError:
        return False
    if key is None:
        return False
    ok, state = threading.Event(), {"ok": False}

    def loop():
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        _WIN_HK[slot] = k.GetCurrentThreadId()
        state["ok"] = bool(u.RegisterHotKey(None, slot, flags, key))
        ok.set()
        if not state["ok"]:
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                try:
                    callback()
                except Exception:  # noqa: BLE001
                    pass
        u.UnregisterHotKey(None, slot)

    threading.Thread(target=loop, daemon=True).start()
    ok.wait(3)
    return state["ok"]


def register_hotkey(spec, callback, slot=1):
    """spec : « cmd+alt+d ». slot : emplacement (1 = afficher/masquer, 2 = assistant…).
    Retourne True si le raccourci est actif. callback est appelé dans le thread principal (Mac)."""
    unregister_hotkey(slot)
    if not spec:
        return False
    if IS_WIN:
        try:
            return _register_hotkey_win(spec, callback, slot)
        except Exception:  # noqa: BLE001
            return False
    if not IS_MAC:
        return False
    try:
        parts = [p.strip().lower() for p in spec.split("+")]
        key = KEYCODES[parts[-1]]
        mods = sum(MODS[p] for p in parts[:-1])
        carbon = _carbon()
        ref = ctypes.c_void_p()
        err = carbon.RegisterEventHotKey(key, mods, _HK["types"](0x444D4F4E, slot),
                                         carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if err != 0:
            return False
        _HK["refs"][slot], _HK["callbacks"][slot] = ref, callback
        return True
    except Exception:  # noqa: BLE001
        return False


def unregister_hotkey(slot=None):
    """Retire un raccourci (ou tous si slot est None)."""
    slots = [slot] if slot is not None else list(set(_HK["refs"]) | set(_WIN_HK))
    for sl in slots:
        tid = _WIN_HK.pop(sl, None)
        if IS_WIN and tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT
            except Exception:  # noqa: BLE001
                pass
        ref = _HK["refs"].pop(sl, None)
        _HK["callbacks"].pop(sl, None)
        if ref is not None and _HK["carbon"] is not None:
            try:
                _HK["carbon"].UnregisterEventHotKey(ref)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
#  Notifications natives
# ---------------------------------------------------------------------------
def notify(title, message, sound=True):
    if not IS_MAC:
        return
    esc = lambda s: str(s).replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if sound:
        script += ' sound name "Funk"'
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass

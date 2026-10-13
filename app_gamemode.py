# -*- coding: utf-8 -*-
"""Mode jeu : quand un jeu, une vidéo ou une présentation occupe tout l'écran principal, les widgets se cachent et
l'écoute vocale se met en pause ; tout revient tout seul à la sortie du plein écran (Windows)."""
import ctypes
import os
from ctypes import wintypes

from core import IS_WIN, log_exception

# fenêtres du système qui couvrent l'écran sans être un « plein écran » (bureau, barre des tâches, menu Démarrer…)
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
                 "ApplicationFrameWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland"}


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def fullscreen_app():
    """Nom de la classe de la fenêtre qui occupe tout l'écran principal, ou None."""
    if not IS_WIN:
        return None
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.MonitorFromWindow.restype = u.MonitorFromPoint.restype = ctypes.c_void_p
    u.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    # jeu en plein écran exclusif (Direct3D) : Windows le signale lui-même
    state = ctypes.c_int()
    if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value == 3:
        return "Direct3D"
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    u.IsZoomed.argtypes = [ctypes.c_void_p]
    if u.IsZoomed(hwnd):   # fenêtre simplement agrandie (pas un plein écran), même si la barre des tâches est masquée
        return None
    cls = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(hwnd, cls, 128)
    if cls.value in SHELL_CLASSES:
        return None
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():   # une fenêtre de DeskMonitor (paramètres…)
        return None
    mon = u.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
    primary = u.MonitorFromPoint(wintypes.POINT(0, 0), 1)   # MONITOR_DEFAULTTOPRIMARY
    if not mon or mon != primary:   # plein écran sur un autre écran : les widgets (écran principal) restent
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    r = wintypes.RECT()
    if not u.GetMonitorInfoW(mon, ctypes.byref(mi)) or not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    m = mi.rcMonitor
    covers = r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    return cls.value if covers else None


class GameModeMixin:
    game_active = False

    def _game_loop(self):
        """Toutes les 1,5 s : entrée / sortie du plein écran."""
        try:
            want = bool(self.cfg.get("game_mode", True) and fullscreen_app())
            if want and not self.game_active:
                self.game_active = True
                self._game_hide()
                if getattr(self, "wake", None) is not None and self.wake.running:
                    self.wake.stop()            # l'écoute reprend toute seule à la sortie (_wake_loop)
                self._alog("mode jeu : widgets masqués, écoute en pause")
            elif want:
                self._game_hide()               # une fenêtre recréée entre-temps (changement de thème…)
            elif self.game_active:
                self.game_active = False
                if not self.cfg["widgets_hidden"]:   # l'utilisateur les avait masqués lui-même : ils le restent
                    self._game_show()
        except Exception:  # noqa: BLE001
            log_exception("mode jeu")
        self.root.after(1500, self._game_loop)

    def _game_hide(self):
        import tkinter as tk
        for w in self.all_windows():
            try:
                if w.winfo_ismapped():
                    w.withdraw()
            except tk.TclError:
                pass

    def _game_show(self):
        import tkinter as tk
        for i, w in enumerate(self.all_windows()):
            try:
                if w is self.root and self.main_hidden:
                    continue
                w.deiconify()
                self.anim.appear(w, i * 22, rise=10, duration_ms=420)
            except tk.TclError:
                pass

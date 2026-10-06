"""Moteur d'animation de DeskMonitor.

Une seule boucle à ~60 images/s, qui ne tourne que tant qu'une animation est en cours (zéro coût au repos).
Courbes d'accélération inspirées de celles de Windows 11 et de macOS : départ franc, arrivée tout en douceur,
léger rebond pour les objets qu'on « pose » (cartes lâchées à la souris).
"""
import time
import tkinter as tk

from core import blend


# --------------------------------------------------------------------------- #
#  Courbes
# --------------------------------------------------------------------------- #
def linear(t):
    return t


def ease_out(t):          # décélération (cubique) : mouvements courants
    return 1 - (1 - t) ** 3


def ease_out_quint(t):    # décélération plus marquée : grands déplacements
    return 1 - (1 - t) ** 5


def ease_in_out(t):       # accélère puis freine : fondus, tiroirs
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_in(t):
    return t ** 3


def back(t, s=1.25):      # dépasse un peu puis revient : effet « posé », ressort amorti
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    """Couleur intermédiaire (t = 0 → c1, t = 1 → c2)."""
    return blend(c1, c2, max(0.0, min(1.0, t)))


# --------------------------------------------------------------------------- #
#  Moteur
# --------------------------------------------------------------------------- #
class Animator:
    FRAME_MS = 15

    def __init__(self, root, enabled=lambda: True):
        self.root = root
        self.enabled = enabled
        self._tw = {}      # clé → [début, durée, étape, courbe, fin, jeton]
        self._job = None

    @property
    def on(self):
        try:
            return bool(self.enabled())
        except Exception:  # noqa: BLE001
            return True

    def play(self, key, duration_ms, step, ease=ease_out, done=None, delay_ms=0):
        """Lance step(p) avec p de 0 à 1 (après la courbe) pendant duration_ms. Une animation de même clé
        est remplacée (elle repart de là où elle en est, puisque chaque étape lit l'état courant)."""
        if not self.on or duration_ms <= 0:
            self._safe(step, 1.0)
            if done:
                self._safe(done)
            self._tw.pop(key, None)
            return
        token = object()
        self._tw[key] = [time.perf_counter() + delay_ms / 1000, duration_ms / 1000, step, ease, done, token]
        if self._job is None:
            self._job = self.root.after(self.FRAME_MS, self._frame)

    def cancel(self, key):
        self._tw.pop(key, None)

    def running(self, key):
        return key in self._tw

    @staticmethod
    def _safe(fn, *a):
        try:
            fn(*a)
            return True
        except tk.TclError:   # fenêtre détruite pendant l'animation
            return False
        except Exception:  # noqa: BLE001
            return False

    def _frame(self):
        self._job = None
        now = time.perf_counter()
        for key, tw in list(self._tw.items()):
            start, dur, step, ease, done, token = tw
            if now < start:
                continue
            t = min(1.0, (now - start) / dur)
            ok = self._safe(step, ease(t))
            if not ok or t >= 1.0:
                if self._tw.get(key) is tw:   # l'étape a pu relancer une animation de même clé
                    del self._tw[key]
                if ok and done:
                    self._safe(done)
        if self._tw:
            self._job = self.root.after(self.FRAME_MS, self._frame)

    # ----- fenêtres --------------------------------------------------------------
    @staticmethod
    def pos(win):
        """Position où la fenêtre se trouve, ou celle où elle est en train d'aller."""
        tgt = getattr(win, "_glide_to", None)
        return tgt if tgt is not None else (win.winfo_x(), win.winfo_y())

    def glide(self, win, x, y, duration_ms=420, ease=ease_out_quint, done=None):
        """Déplace une fenêtre en douceur jusqu'à (x, y)."""
        x, y = int(x), int(y)
        try:
            visible = win.winfo_ismapped() and win.winfo_viewable()
            x0, y0 = win.winfo_x(), win.winfo_y()
        except tk.TclError:
            return
        if not self.on or not visible or (abs(x - x0) + abs(y - y0)) < 3:
            win._glide_to = None
            self.cancel(("glide", str(win)))
            win.geometry(f"+{x}+{y}")
            if done:
                done()
            return
        win._glide_to = (x, y)

        def step(p):
            win.geometry(f"+{round(lerp(x0, x, p))}+{round(lerp(y0, y, p))}")

        def end():
            win._glide_to = None
            if done:
                done()
        self.play(("glide", str(win)), duration_ms, step, ease, end)

    def fade(self, win, to, duration_ms=220, ease=ease_in_out, done=None, delay_ms=0):
        try:
            a0 = float(win.attributes("-alpha"))
        except tk.TclError:
            return
        self.play(("fade", str(win)), duration_ms, lambda p: win.attributes("-alpha", lerp(a0, to, p)),
                  ease, done, delay_ms)

    def appear(self, win, delay_ms=0, rise=16, duration_ms=520):
        """Entrée en scène : la fenêtre monte de quelques pixels en apparaissant (cascade avec delay_ms)."""
        if not self.on:
            return
        try:
            win.update_idletasks()
            target = float(getattr(win, "_base_alpha", None) or win.attributes("-alpha"))
            x, y = win.winfo_x(), win.winfo_y()
        except tk.TclError:
            return
        win.attributes("-alpha", 0.0)
        win.geometry(f"+{x}+{y + rise}")
        win._glide_to = (x, y)

        def step(p):
            win.geometry(f"+{x}+{round(y + rise * (1 - p))}")

        def end():
            win._glide_to = None
        # opacité et position séparées : un déplacement lancé entre-temps n'interrompt pas le fondu
        self.play(("fade", str(win)), int(duration_ms * 0.6), lambda p: win.attributes("-alpha", target * p),
                  ease_out, None, delay_ms)
        self.play(("glide", str(win)), duration_ms, step, ease_out_quint, end, delay_ms)

    # ----- couleurs ---------------------------------------------------------------
    def color(self, key, c0, c1, apply, duration_ms=160, ease=ease_out):
        """Transition de couleur : apply(couleur) à chaque image."""
        self.play(key, duration_ms, lambda p: apply(mix(c0, c1, p)), ease)

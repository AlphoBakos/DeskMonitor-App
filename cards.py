# -*- coding: utf-8 -*-
"""Cartes façon widgets macOS : fenêtres arrondies, translucides et floutées, avec jauges animées.
Cartes : horloge, système, stockage, réseau, batterie, musique, agenda, météo, processus, notes, presse-papiers."""
import os
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import psutil

import anim
import macdata
import mac_native
from core import log_exception, IS_MAC, IS_WIN, no_activate, win_blur, apply_corners, NUM_FONT, TEXT_FONT, UI_FONT, LIGHT_FONT, bind_right_click, blend, fmt_bytes, format_date, save_config

UNIT, GAP = 158, 14

# id : (libellé, largeur en unités, hauteur en unités)
CARD_TYPES = {
    "clock": ("Heure et date", 2, 1),
    "system": ("Processeur et mémoire", 1, 1),
    "storage": ("Stockage", 1, 1),
    "network": ("Réseau et ping", 2, 1),
    "battery": ("Batterie", 1, 1),
    "music": ("Musique", 2, 1),
    "calendar": ("Agenda et rappels", 2, 1),
    "weather": ("Météo", 2, 1),
    "processes": ("Processus gourmands", 2, 2),
    "notes": ("Note rapide", 2, 1),
    "clipboard": ("Presse-papiers", 2, 1),
}
MAC_ONLY = set()                   # (la musique dépend de « winsdk » sous Windows, voir card_ids)
KEY = "#010203"                    # couleur rendue transparente sous Windows (coins arrondis)
KEY_LIGHT = "#F2F4F7"              # idem en thème clair avec le verre acrylique : le lissage du texte se fond
                                   # dans une couleur claire (avec KEY, un liseré sombre entourait les lettres)


def card_ids():
    """Cartes disponibles sur ce système (la musique existe aussi sous Windows si « winsdk » est installé)."""
    return [k for k in CARD_TYPES if k != "music" or IS_MAC or macdata.WIN_MEDIA]


DEFAULT_CARDS = ["clock", "system", "storage", "battery", "network"]
LAYOUTS = {"cards": "Cartes empilées (colonnes)", "minimal": "Minimal (heure seulement)",
           "classic": "Colonne classique"}
CORNERS = {"tl": "Haut à gauche", "tr": "Haut à droite", "bl": "Bas à gauche", "br": "Bas à droite"}


def _trunc(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


class Ring:
    """Jauge graduée : 48 traits disposés en cadran, allumés jusqu'à la valeur. Les traits allumés forment une
    traînée (plus sombres au départ, éclatants à la tête), comme l'aiguille lumineuse d'un instrument."""
    N = 48

    def __init__(self, canvas, cx, cy, r, length, color, track, stroke=2.4):
        import math
        self.c, self.value, self.target, self.color, self.track = canvas, 0.0, 0.0, color, track
        self.ticks, self.lit, self.fills = [], None, {}
        for i in range(self.N):
            a = math.radians(90 - i * 360 / self.N)
            r0 = r - length / 2 - (1.5 if i % 12 == 0 else 0)   # repères aux quarts, un peu plus longs
            r1 = r + length / 2 + (1.5 if i % 12 == 0 else 0)
            self.ticks.append(canvas.create_line(cx + r0 * math.cos(a), cy - r0 * math.sin(a),
                                                 cx + r1 * math.cos(a), cy - r1 * math.sin(a),
                                                 fill=track, width=stroke, capstyle="round"))

    def set(self, pct, color=None):
        self.target = max(0.0, min(100.0, pct))
        if color and color != self.color:
            self.color, self.lit = color, None   # force le recoloriage

    def step(self):
        d = self.target - self.value
        if abs(d) >= 0.05:
            self.value += d * 0.16   # ressort amorti (30 images/s)
        exact = self.value / 100 * self.N
        n = int(exact)
        frac = round((exact - n) * 4) / 4   # le trait suivant s'allume progressivement (4 nuances)
        if (n, frac) == self.lit:
            return
        self.lit = (n, frac)
        head = blend(self.color, "#FFFFFF", 0.4)
        dim = blend(self.color, self.track, 0.45)
        for i, t in enumerate(self.ticks):
            if i < n:
                col = head if i == n - 1 else blend(dim, self.color, min(1.0, (i + 1) / max(1, n) * 1.6))
            elif i == n and frac:
                col = blend(self.track, self.color, frac)
            else:
                col = self.track
            if self.fills.get(t) != col:   # seulement les traits qui changent : moins de redessin
                self.fills[t] = col
                self.c.itemconfigure(t, fill=col)


class Card:
    kind = ""

    def __init__(self, mgr, kind):
        self.m, self.kind = mgr, kind
        self.app = mgr.app
        _, self.w, self.h = CARD_TYPES[kind]
        if mgr.layout == "minimal":
            self.w = 3
        # dessin en pixels « logiques » (px, py) ; la fenêtre réelle (wpx, wpy) suit la mise à l'échelle de l'écran
        self.px, self.py = self.w * UNIT + (self.w - 1) * GAP, self.h * UNIT + (self.h - 1) * GAP
        self.wpx = self.w * mgr.unit + (self.w - 1) * mgr.gap
        self.wpy = self.h * mgr.unit + (self.h - 1) * mgr.gap
        self.k, self.kx, self.ky = mgr.k, self.wpx / self.px, self.wpy / self.py
        self.win = tk.Toplevel(mgr.app.root)
        self.win.overrideredirect(True)
        self.title = f"DeskMonitor carte {kind}"
        self.win.title(self.title)
        self.win.geometry(f"{self.wpx}x{self.wpy}+0+0")
        self.win.attributes("-topmost", bool(mgr.cfg["topmost"]))
        self.native = False
        # Windows + flou : fond de carte transparent (« KEY »), sous lequel Windows dessine un verre acrylique
        self.win_blur = IS_WIN and bool(mgr.cfg["card_blur"])
        self.key = KEY_LIGHT if self.win_blur and not mgr.dark else KEY
        self.cv = tk.Canvas(self.win, width=self.wpx, height=self.wpy, highlightthickness=0, bd=0,
                            bg=self.key if IS_WIN else mgr.fallback_bg)
        self.cv.pack(fill="both", expand=True)
        self.rings = []
        self._drag, self._moved = None, False
        self._nums = {}          # valeurs affichées par les compteurs animés
        self._hover = 0.0        # 0 = repos, 1 = survolée
        self.buttons = []
        self._chip_specs, self._chips, self._chip_p = [], [], 0.0
        self._backdrop()

    def _backdrop(self):
        """Fond arrondi dessiné dans la carte : lisible même quand le flou natif n'apparaît pas."""
        r, w, h = min(int(self.m.cfg["card_radius"]), self.px // 2), self.px - 1, self.py - 1
        if self.win_blur:   # même arrondi que celui dessiné par Windows 11 (8 px)
            r = 8
        pts = []
        for cx, cy, a0 in ((w - r, r, -90), (w - r, h - r, 0), (r, h - r, 90), (r, r, 180)):
            import math
            for i in range(0, 91, 10):
                a = math.radians(a0 + i)
                pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        # Windows + flou : l'intérieur reste transparent pour laisser voir le verre acrylique
        self.bd = self.cv.create_polygon(*pts, fill=self.key if self.win_blur else self.m.bg, outline=self.m.edge,
                                         width=1)
        # reflet : un filet clair sur le bord supérieur, comme une plaque de verre
        self.gloss = self.cv.create_line(r, 1.5, w - r, 1.5, fill=self._gloss(0))

    def _gloss(self, h):
        m = self.m
        return blend(m.bg, "#FFFFFF", (0.14 + 0.22 * h) if m.dark else (0.6 + 0.3 * h))

    # ----- style natif ------------------------------------------------------
    def style(self):
        m = self.m
        self.win.update_idletasks()
        if IS_MAC and m.cfg["card_blur"]:
            self.native = mac_native.style_card(self.win, self.title, m.cfg["card_radius"], m.dark,
                                                all_spaces=m.cfg["card_all_spaces"],
                                                desktop_level=m.cfg["card_desktop"])
        if self.native:
            self.cv.configure(bg="systemTransparent")
        elif self.win_blur:  # Windows : verre acrylique teinté sous le fond transparent, coins arrondis natifs
            self.win.configure(bg=self.key)
            self.win.attributes("-transparentcolor", self.key)
            apply_corners(self.win, True)
            no_activate(self.win)
            # Windows ignore l'effet demandé avant l'affichage de la fenêtre : on l'applique une fois visible.
            # L'opacité réglée devient celle de la teinte ; la fenêtre elle-même reste opaque (texte net).
            op = max(0.3, min(1.0, m.cfg["opacity"] / 100))
            self.win.after(150, lambda: self.win.winfo_exists() and win_blur(self.win, True, m.bg, op))
            self.win.attributes("-alpha", 1.0)
            self.win._base_alpha = 1.0
            self.win.attributes("-topmost", bool(m.cfg["topmost"]))
            return
        elif IS_WIN:  # coins arrondis : tout ce qui est de la couleur « KEY » devient transparent
            self.win.configure(bg=KEY)
            self.win.attributes("-transparentcolor", KEY)
            no_activate(self.win)
        else:
            self.win.configure(bg=m.fallback_bg)
        self.win.attributes("-alpha", max(0.3, min(1.0, m.cfg["opacity"] / 100)))
        self.win._base_alpha = max(0.3, min(1.0, m.cfg["opacity"] / 100))
        self.win.attributes("-topmost", bool(m.cfg["topmost"]))

    def finish(self):
        """Lie le glisser-déposer, le survol et le menu contextuel ; appelé une fois la carte dessinée."""
        for w in (self.cv,):
            w.bind("<ButtonPress-1>", self._press)
            w.bind("<B1-Motion>", self._move)
            w.bind("<ButtonRelease-1>", self._release)
            w.bind("<Enter>", lambda e=None: (self._set_hover(1.0), self._show_chips(True)))
            w.bind("<Leave>", lambda e=None: self._drag is None and (self._set_hover(0.0), self._show_chips(False)))
            bind_right_click(w, self.app.show_menu)

    # survol : le contour s'éclaire de la couleur d'accent et le reflet du verre s'intensifie
    def _paint_hover(self, h, pressed=False):
        m = self.m
        edge = anim.mix(m.edge, m.accent, (0.55 if not pressed else 0.9) * h)
        self.cv.itemconfigure(self.bd, outline=edge, width=1 + (h > 0.5 and pressed))
        self.cv.itemconfigure(self.gloss, fill=self._gloss(h))

    def _set_hover(self, to, pressed=False, ms=180):
        h0 = self._hover

        def step(p):
            self._hover = anim.lerp(h0, to, p)
            self._paint_hover(self._hover, pressed)
        self.app.anim.play(("hover", self.title), ms, step, anim.ease_out)

    def _press(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())
        self._moved = False
        self._set_hover(1.0, pressed=True, ms=90)

    def _move(self, e):
        if self._drag and not self.m.cfg["locked"]:
            if not self._moved:   # la carte se « soulève » : un peu transparente, au-dessus des autres
                self._moved = True
                self.win.lift()
                self.app.anim.fade(self.win, getattr(self.win, "_base_alpha", 1.0) * 0.82, 140)
                self.cv.configure(cursor="fleur")
            self.app.anim.cancel(("glide", str(self.win)))
            self.win._glide_to = None
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")
            if not self.m.cfg["card_free"]:
                self.m.preview_drop(self.kind)   # les autres cartes s'écartent en direct

    def _release(self, _e):
        moved = self._drag and self._moved and not self.m.cfg["locked"]
        self._drag = None
        self._set_hover(1.0, ms=200)
        if moved:
            self.cv.configure(cursor="")
            self.app.anim.fade(self.win, getattr(self.win, "_base_alpha", 1.0), 220)
            if self.m.cfg["card_free"]:
                self.m.cfg["card_pos"][self.kind] = list(self.m.settle(self.kind))
                save_config(self.m.cfg)
            else:
                self.m.reorder(self.kind)

    def button(self, item, command, color=None):
        """Texte cliquable : s'éclaire au survol, s'enfonce au clic."""
        base = color or self.m.fg

        def paint(col):
            self.cv.itemconfigure(item, fill=col)

        def enter(_e=None):
            self.cv.configure(cursor="hand2")
            cur = self.cv.itemcget(item, "fill") or base
            self.app.anim.color(("btn", str(self.cv), item), cur, self.m.accent, paint, 140)

        def leave(_e=None):
            self.cv.configure(cursor="")
            cur = self.cv.itemcget(item, "fill") or base
            self.app.anim.color(("btn", str(self.cv), item), cur, base, paint, 220)

        def click(_e=None):
            self.app.anim.color(("btn", str(self.cv), item), "#FFFFFF", self.m.accent, paint, 260)
            command()
            return "break"
        self.cv.tag_bind(item, "<Enter>", enter)
        self.cv.tag_bind(item, "<Leave>", leave)
        self.cv.tag_bind(item, "<ButtonPress-1>", click)
        self.cv.tag_bind(item, "<ButtonRelease-1>", lambda e=None: "break")
        self.buttons.append(item)

    # ----- boutons d'action (apparaissent au survol, en haut à droite) ---------------------------------
    def chip(self, label, command):
        """Déclare un bouton d'action. command(fin) lance l'action ; fin(texte) affiche le résultat sur le bouton."""
        self._chip_specs.append((label, command))

    @staticmethod
    def _pill(x0, y0, x1, y1):
        r = (y1 - y0) / 2
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
                x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]

    def _make_chips(self):
        """Créés au premier survol, en pixels réels (après la mise à l'échelle de l'écran)."""
        x = self.px * self.kx - 12 * self.kx
        y = 13 * self.ky
        for label, command in reversed(self._chip_specs):
            t = self.text(x - 8 * self.kx, y, label, 10, True, self.m.accent, anchor="ne", state="hidden")
            pill = self.cv.create_polygon(0, 0, 0, 0, smooth=True, fill=self.m.bg, outline="", state="hidden")
            self.cv.tag_lower(pill, t)
            chip = {"text": t, "pill": pill, "label": label, "cmd": command, "x": x, "busy": False, "hot": 0.0}
            self._fit_chip(chip)
            for item in (t, pill):
                self.cv.tag_bind(item, "<Enter>", lambda e=None, c=chip: self._chip_hot(c, True))
                self.cv.tag_bind(item, "<Leave>", lambda e=None, c=chip: self._chip_hot(c, False))
                self.cv.tag_bind(item, "<ButtonPress-1>", lambda e=None, c=chip: self._chip_click(c))
            self._chips.append(chip)
            bb = self.cv.bbox(pill)
            x = (bb[0] if bb else x) - 6 * self.kx

    def _fit_chip(self, chip):
        bb = self.cv.bbox(chip["text"])
        if bb:
            px, py = 8 * self.kx, 3 * self.ky
            self.cv.coords(chip["pill"], *self._pill(bb[0] - px, bb[1] - py, bb[2] + px, bb[3] + py))

    def _paint_chips(self):
        m, p = self.m, self._chip_p
        for c in self._chips:
            base = anim.mix(m.bg, m.accent, 0.20 + 0.18 * c["hot"])
            self.cv.itemconfigure(c["pill"], fill=anim.mix(m.bg, base, p), state="normal" if p > 0.02 else "hidden")
            col = m.good if c.get("ok") else blend(m.accent, m.fg, 0.25)
            self.cv.itemconfigure(c["text"], fill=anim.mix(m.bg, col, p), state="normal" if p > 0.02 else "hidden")
        # l'information de l'en-tête (à droite) s'efface derrière les boutons
        if getattr(self, "hdr_r", None) and self._chips:
            self.cv.itemconfigure(self.hdr_r, state="hidden" if p > 0.02 else "normal")

    def _show_chips(self, on):
        if not self._chip_specs:
            return
        if on and not self._chips:
            self._make_chips()
        if not on and any(c["busy"] for c in self._chips):
            return   # une action est en cours : son bouton reste visible
        p0 = self._chip_p

        def step(t):
            self._chip_p = anim.lerp(p0, 1.0 if on else 0.0, t)
            self._paint_chips()
        self.app.anim.play(("chips", self.title), 160 if on else 240, step, anim.ease_out)

    def _chip_hot(self, chip, on):
        chip["hot"] = 1.0 if on else 0.0
        self.cv.configure(cursor="hand2" if on else "")
        self._paint_chips()

    def _chip_click(self, chip):
        if chip["busy"]:
            return "break"
        if getattr(self.app, "_busy", False):
            self._chip_result(chip, "occupé…", False)
            return "break"
        chip["busy"] = True
        self.cv.itemconfigure(chip["text"], text="…")
        self._fit_chip(chip)

        def finished(msg):
            import re
            chip["busy"] = False
            amount = re.search(r"(\d[\d,. ]*\s?[KMGT]?o)\b", str(msg))
            self._chip_result(chip, ("✓ " + amount.group(1)) if amount else "✓ fait", True)
        try:
            chip["cmd"](finished)
        except Exception:  # noqa: BLE001
            chip["busy"] = False
            self._chip_result(chip, "échec", False)
        return "break"

    def _chip_result(self, chip, text, ok):
        """Le bouton affiche le résultat (« ✓ 1,2 Go ») quelques secondes, puis reprend son libellé."""
        if not self.cv.winfo_exists():
            return
        chip["ok"] = ok
        self.cv.itemconfigure(chip["text"], text=text)
        self._fit_chip(chip)
        self._chip_p = max(self._chip_p, 1.0)
        self._paint_chips()

        def back():
            if self.cv.winfo_exists():
                chip["ok"] = False
                self.cv.itemconfigure(chip["text"], text=chip["label"])
                self._fit_chip(chip)
                self._paint_chips()
                x, y = self.cv.winfo_pointerxy()
                inside = self.win.winfo_rootx() <= x < self.win.winfo_rootx() + self.win.winfo_width() and \
                    self.win.winfo_rooty() <= y < self.win.winfo_rooty() + self.win.winfo_height()
                if not inside:
                    self._show_chips(False)
        self.cv.after(3500, back)

    def clickable(self, items, command):
        """Zone cliquable (ex. la jauge du processeur) : curseur main au survol."""
        for it in items:
            self.cv.tag_bind(it, "<Enter>", lambda e=None: self.cv.configure(cursor="hand2"))
            self.cv.tag_bind(it, "<Leave>", lambda e=None: self.cv.configure(cursor=""))
            self.cv.tag_bind(it, "<ButtonRelease-1>", lambda e=None: (not self._moved) and command())

    def count(self, item, key, value, fmt, ms=650):
        """Compteur animé : le nombre défile jusqu'à sa nouvelle valeur."""
        v0 = self._nums.get(key)
        self._nums[key] = value
        if v0 is None or abs(value - v0) < 0.5:
            self.set(item, text=fmt(value))
            return
        self.app.anim.play(("num", self.title, key), ms, lambda p: self.set(item, text=fmt(anim.lerp(v0, value, p))),
                           anim.ease_out)

    def swap_text(self, item, text, rise=5):
        """Changement de texte en fondu : l'ancien s'efface, le nouveau apparaît en remontant légèrement."""
        pend = self.__dict__.setdefault("_swaps", {})
        if pend.get(item, self.cv.itemcget(item, "text")) == text:
            return
        if not self.app.anim.on or not self.cv.itemcget(item, "text"):
            self.set(item, text=text)
            pend.pop(item, None)
            return
        if item in pend:   # changement déjà en cours : on remplace simplement le texte visé
            pend[item] = text
            return
        pend[item] = text
        col = self.cv.itemcget(item, "fill")
        bg = self.m.bg
        x, y = self.cv.coords(item)[:2]
        dy = rise * self.ky

        def fade_out(p):
            self.cv.itemconfigure(item, fill=anim.mix(col, bg, p))
            self.cv.coords(item, x, y - dy * p)

        def swap():
            self.cv.itemconfigure(item, text=pend.get(item, text))

            def fade_in(p):
                self.cv.itemconfigure(item, fill=anim.mix(bg, col, p))
                self.cv.coords(item, x, y + dy * (1 - p))
            self.app.anim.play(("swap", self.title, item), 260, fade_in, anim.ease_out,
                               lambda: pend.pop(item, None))
        self.app.anim.play(("swap", self.title, item), 140, fade_out, anim.ease_in, swap)

    # ----- aides de dessin ---------------------------------------------------
    def text(self, x, y, s="", size=12, bold=False, color=None, anchor="nw", num=False, light=False, **kw):
        """Texte de la carte : num=True pour les chiffres d'instrument (DIN), sinon texte courant."""
        size = size * self.m.cfg["card_text_scale"] / 100
        size = -max(1, round(size * self.k)) if IS_WIN else max(1, round(size))   # Windows : pixels, comme le dessin
        font = (NUM_FONT if num else TEXT_FONT, size, "bold" if bold else "normal")
        return self.cv.create_text(x, y, text=s, fill=color or self.m.fg, font=font, anchor=anchor, **kw)

    def header(self, label, right=""):
        """Libellé discret en haut de la carte (et une information à droite, facultative)."""
        self.hdr = self.text(16, 13, label, 11, True, self.m.sub)
        self.hdr_r = self.text(self.px - 16, 13, right, 11, False, self.m.sub, anchor="ne")

    def ring(self, cx, cy, r, length=9, color=None):
        rg = Ring(self.cv, cx, cy, r, length, color or self.m.accent, self.m.track,
                  stroke=max(1.5, 2.4 * (self.kx if IS_WIN else 1)))
        self.rings.append(rg)
        return rg

    def num_unit(self, num_item, unit_item, value, unit):
        """Nombre en grand, son unité en petit juste après (alignée sur le bas des chiffres)."""
        self.set(num_item, text=value)
        bb = self.cv.bbox(num_item)
        if bb:
            self.cv.coords(unit_item, bb[2] + 3 * self.kx, bb[3] - 6 * self.ky)
        self.set(unit_item, text=unit)

    def set(self, item, **kw):
        self.cv.itemconfigure(item, **kw)

    def fill(self, item, color):
        """Change la couleur d'un élément seulement si elle est différente (évite de redessiner la carte)."""
        cache = self.__dict__.setdefault("_fills", {})
        if cache.get(item) != color:
            cache[item] = color
            self.cv.itemconfigure(item, fill=color)

    def rescale(self):
        """Adapte le dessin à la mise à l'échelle de l'écran (Windows, DPI > 100 %)."""
        if abs(self.kx - 1) < 0.005 and abs(self.ky - 1) < 0.005:
            return
        self.cv.scale("all", 0, 0, self.kx, self.ky)
        for i in self.cv.find_all():
            if self.cv.type(i) == "text":
                w = int(float(self.cv.itemcget(i, "width") or 0))
                if w:
                    self.cv.itemconfigure(i, width=int(w * self.kx))

    def tick(self):
        for r in self.rings:
            r.step()
        self.frame()

    def frame(self):
        """Animation continue propre à la carte (30 images/s)."""

    def build(self):
        pass

    def update(self, d):
        pass

    def destroy(self):
        mac_native._NS_CACHE.pop(self.title, None)
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def _split(txt):
    """« 462,3 Ko » → (« 462,3 », « Ko »)."""
    parts = txt.split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (txt, "")


class ClockCard(Card):
    def build(self):
        big = self.w >= 3
        self.t = self.text(14, 6, "", 92 if big else 66, False, num=True)
        self.dt = self.text(18, self.py - 46, "", 15, False)
        # trotteuse : 60 graduations sous l'heure
        x0, x1, y = 18, self.px - 18, self.py - 16
        self.sec = []
        for i in range(60):
            x = x0 + (x1 - x0) * i / 59
            h = 9 if i % 5 == 0 else 5
            self.sec.append(self.cv.create_line(x, y - h, x, y, fill=self.m.track, width=2, capstyle="round"))
        self._lit = -1
        self._sx0, self._sx1, self._sy = x0, x1, y
        # point lumineux qui glisse sans à-coups sur la réglette, comme une trotteuse continue
        self.dot = self.cv.create_oval(0, 0, 0, 0, fill=blend(self.m.accent, "#FFFFFF", 0.35), outline="")

    def update(self, d):
        c, now = self.m.cfg, datetime.now()
        fmt = "%H:%M" if c["clock_24h"] else "%I:%M"
        self.swap_text(self.t, now.strftime(fmt) + ("" if c["clock_24h"] else (" am" if now.hour < 12 else " pm")))
        self.swap_text(self.dt, format_date(now, c), rise=3)
        self._light(now.second)

    def _light(self, s):
        if s == self._lit:
            return
        dim = blend(self.m.accent, self.m.track, 0.5)
        for i, t in enumerate(self.sec):
            # traînée : les secondes passées s'estompent vers le début de la minute
            col = blend(dim, self.m.accent, i / max(1, s)) if i < s else self.m.track
            self.fill(t, col)
        self._lit = s

    def frame(self):
        now = time.time()
        sec = now % 60
        self._light(int(sec))
        x = round((self._sx0 + (self._sx1 - self._sx0) * sec / 59.999) * self.kx)
        if x == getattr(self, "_dot_x", None):   # redessiné seulement quand le point avance d'un pixel
            return
        self._dot_x = x
        y = (self._sy - 4) * self.ky
        r = 3.2 * self.kx
        self.cv.coords(self.dot, x - r, y - r, x + r, y + r)


class SystemCard(Card):
    def build(self):
        self.header("Système")
        cx, cy = self.px / 2, 72
        self.cpu = self.ring(cx, cy, 40, 8)
        self.lbl = self.text(cx, cy - 4, "", 20, False, anchor="center", num=True)
        cpu_lbl = self.text(cx, cy + 15, "CPU ›", 9, False, self.m.sub, anchor="center", num=True)
        # la jauge ouvre la liste des programmes qui utilisent le processeur (on peut les fermer)
        self.clickable([*self.cpu.ticks, self.lbl, cpu_lbl], self.app.open_processes)
        if IS_WIN:   # libération de la mémoire : Windows uniquement (pas d'équivalent sûr sur macOS)
            self.chip("Libérer la RAM", lambda fin: self.app.action_ram(fin))
        # réglette mémoire : mêmes graduations, à plat
        y, x0, x1 = self.py - 17, 46, self.px - 46
        self.text(16, y + 5, "RAM", 10, False, self.m.sub, anchor="sw", num=True)
        self.ram_val = self.text(self.px - 16, y + 5, "", 10, False, self.m.accent2, anchor="se", num=True)
        self.rule = [self.cv.create_line(x0 + (x1 - x0) * i / 19, y - 3, x0 + (x1 - x0) * i / 19, y + 3,
                                         fill=self.m.track, width=2, capstyle="round") for i in range(20)]
        self._ram_lit, self._ram_col = None, None

    def update(self, d):
        thr = self.m.cfg["warn_threshold"]
        self.cpu.set(d["cpu"], self.m.warn if d["cpu"] >= thr else self.m.accent)
        self.count(self.lbl, "cpu", d["cpu"], lambda v: f"{v:.0f}%")
        col = self.m.warn if d["ram"] >= thr else self.m.accent2
        self.set(self.ram_val, fill=col)
        self.count(self.ram_val, "ram", d["ram"], lambda v: f"{v:.0f}%")
        self._ram_target, self._ram_col_t = d["ram"], col

    def frame(self):
        tgt = getattr(self, "_ram_target", None)
        if tgt is None:
            return
        cur = getattr(self, "_ram_v", 0.0)
        cur += (tgt - cur) * 0.16
        self._ram_v = cur
        exact = cur / 100 * len(self.rule)
        n, frac = int(exact), round((exact - int(exact)) * 4) / 4
        col = self._ram_col_t
        if (n, frac, col) != (self._ram_lit, self._ram_col):
            for i, t in enumerate(self.rule):
                c = col if i < n else blend(self.m.track, col, frac) if i == n else self.m.track
                self.fill(t, c)
            self._ram_lit, self._ram_col = (n, frac), col


class StorageCard(Card):
    def build(self):
        self.header("Stockage")
        self.chip("Nettoyer", lambda fin: self.app.action_clean(fin))
        self.ring_ = self.ring(self.px / 2, 80, 46, 9)
        self.lbl = self.text(self.px / 2, 80, "", 22, False, anchor="center", num=True)
        self.leg = self.text(self.px / 2, self.py - 12, "", 11, False, self.m.sub, anchor="s")

    def update(self, d):
        u = d["disk"]
        if not u:
            return
        self.ring_.set(u.percent, self.m.warn if u.percent >= self.m.cfg["warn_threshold"] else self.m.accent)
        self.count(self.lbl, "disk", u.percent, lambda v: f"{v:.0f}%")
        self.set(self.leg, text=f"{fmt_bytes(u.free)} libres")


class NetworkCard(Card):
    def build(self):
        self.header("Réseau")
        if IS_WIN:   # sur macOS, vider le cache DNS demande les droits administrateur
            self.chip("Vider le DNS", lambda fin: self.app.action_dns(fin))
        self.down = self.text(16, 32, "", 34, False, num=True)
        self.down_u = self.text(0, 0, "", 13, False, self.m.sub, anchor="sw", num=True)
        self.up = self.text(self.px - 16, 44, "", 13, False, self.m.sub, anchor="ne", num=True)
        self.gx0, self.gy0, self.gw, self.gh = 16, 92, self.px - 32, self.py - 92 - 14
        self.cv.create_line(16, self.gy0 + self.gh, self.px - 16, self.gy0 + self.gh, fill=self.m.track)
        self.fill = self.cv.create_polygon(0, 0, 0, 0, fill=blend(self.m.bg, self.m.accent, 0.22), outline="")
        self.line = self.cv.create_line(0, 0, 0, 0, fill=self.m.accent, width=2, smooth=True)

    def update(self, d):
        v, u = _split(fmt_bytes(d["down"]))
        self.num_unit(self.down, self.down_u, "↓ " + v, u + "/s")
        self.set(self.up, text="↑ " + fmt_rate(d["up"]))
        p = d["ping"]
        self.set(self.hdr_r, text="hors ligne" if p is None else ("" if p == "…" else f"ping {p:.0f} ms"),
                 fill=self.m.warn if (p is None or (p != "…" and p >= 150)) else self.m.sub)
        data = list(d["hist_down"])[-61:]
        if len(data) < 3:
            return
        if data != getattr(self, "_data", None):
            self._data, self._t0 = data, time.time()
        self._top_t = max(max(data), 10 * 1024) * 1.1
        self.frame()

    def frame(self):
        """La courbe glisse vers la gauche entre deux mesures et l'échelle s'adapte en douceur."""
        data = getattr(self, "_data", None)
        if not data:
            return
        self._top = getattr(self, "_top", self._top_t)
        if abs(self._top_t - self._top) > self._top_t * 0.004:
            self._top += (self._top_t - self._top) * 0.12
        else:
            self._top = self._top_t
        period = max(0.25, self.m.cfg["refresh_ms"] / 1000)
        shift = min(1.0, (time.time() - self._t0) / period) if self.app.anim.on else 1.0
        n = len(data) - 1                  # n intervalles visibles
        step = self.gw / (n - 1)
        # pas de redessin tant que la courbe n'a pas glissé d'un pixel (ni changé d'échelle)
        q = (id(data), round(shift * step * self.kx), round(self._top))
        if q == getattr(self, "_drawn", None):
            return
        self._drawn = q
        pts = []
        for i, val in enumerate(data):
            x = self.gx0 + (i - shift) * step
            y = self.gy0 + self.gh * (1 - min(1.0, val / self._top))
            pts.append((x, y))
        x_end = self.gx0 + self.gw
        if pts[0][0] < self.gx0:           # points coupés proprement aux bords du graphique
            (xa, ya), (xb, yb) = pts[0], pts[1]
            pts[0] = (self.gx0, ya + (yb - ya) * (self.gx0 - xa) / (xb - xa))
        if pts[-1][0] > x_end:
            (xa, ya), (xb, yb) = pts[-2], pts[-1]
            pts[-1] = (x_end, ya + (yb - ya) * (x_end - xa) / (xb - xa))
        flat = [v for x, y in pts for v in (x * self.kx, y * self.ky)]
        self.cv.coords(self.line, *flat)
        base = (self.gy0 + self.gh) * self.ky
        self.cv.coords(self.fill, pts[0][0] * self.kx, base, *flat, pts[-1][0] * self.kx, base)


class BatteryCard(Card):
    def build(self):
        self.header("Batterie")
        self.ring_ = self.ring(self.px / 2, 72, 38, 8)
        self.lbl = self.text(self.px / 2, 72, "", 20, False, anchor="center", num=True)
        self.l1 = self.text(self.px / 2, self.py - 28, "", 10, False, self.m.sub, anchor="s")
        self.l2 = self.text(self.px / 2, self.py - 11, "", 10, False, self.m.sub, anchor="s", num=True)

    def update(self, d):
        b = d["battery"]
        if b is None:
            self.set(self.lbl, text="—")
            self.set(self.l1, text="Pas de batterie")
            return
        x = d["bat_extra"]
        low = (not b.power_plugged) and b.percent <= self.m.cfg["alert_bat"]
        self.ring_.set(b.percent, self.m.warn if low else (self.m.good if b.power_plugged else self.m.accent))
        self.count(self.lbl, "bat", b.percent, lambda v: f"{v:.0f}%")
        self.set(self.hdr_r, text="secteur" if b.power_plugged else "")
        bits = []
        if "health" in x:
            bits.append(f"santé {x['health']:.0f} %")
        if "cycles" in x:
            bits.append(f"{x['cycles']} cycles")
        self.set(self.l1, text=", ".join(bits) or ("Sur secteur" if b.power_plugged else "Sur batterie"))
        bits = []
        if "watts" in x and abs(x["watts"]) >= 0.1:
            bits.append(f"{x['watts']:+.1f} W".replace(".", ","))
        if "temp" in x:
            bits.append(f"{x['temp']:.0f} °C")
        if d["thermal"]:
            bits.append(("tiède", "chaud", "très chaud")[min(2, d["thermal"] - 1)])
        self.set(self.l2, text="   ".join(bits))


class MusicCard(Card):
    def build(self):
        self.header("Musique")
        self.title_ = self.text(16, 38, "Rien en lecture", 17, True, width=self.px - 32)
        self.artist = self.text(16, 66, "", 13, False, self.m.sub, width=self.px - 32)
        y = self.py - 28
        for i, (sym, cmd) in enumerate((("⏮", "previous track"), ("⏯", "playpause"), ("⏭", "next track"))):
            t = self.text(28 + i * 46, y, sym, 20, False, anchor="center")
            self.button(t, lambda c=cmd: self._cmd(c))
        # petit égaliseur décoratif : immobile en pause
        self.eq = [self.cv.create_line(self.px - 70 + i * 9, y + 9, self.px - 70 + i * 9, y + 9,
                                       fill=self.m.accent, width=4, capstyle="round") for i in range(6)]
        self.app_, self._phase = None, 0

    def _cmd(self, cmd):
        if self.app_:
            threading.Thread(target=macdata.player_command, args=(self.app_, cmd), daemon=True).start()

    def update(self, d):
        n = d["music"]
        self.app_ = n["app"] if n else None
        self.set(self.hdr_r, text=(_trunc(n["app"].replace(".exe", ""), 18) + ("" if n["playing"] else ", en pause"))
                 if n else "")
        self.set(self.title_, text=_trunc(n["title"], 30) if n else "Rien en lecture")
        self.set(self.artist, text=_trunc(n["artist"], 40) if n else "Lancez un morceau, il s'affichera ici")
        self._playing = bool(n and n["playing"])

    def frame(self):
        import math
        import random
        playing = getattr(self, "_playing", False)
        hs = getattr(self, "_eq_h", [2.0] * len(self.eq))
        tg = getattr(self, "_eq_t", [2.0] * len(self.eq))
        self._phase += 1
        if playing and self._phase % 4 == 0:   # nouvelles cibles ~8 fois par seconde, comme un vrai vumètre
            tg = [3 + 9 * abs(math.sin(self._phase * 0.21 + i * 1.7)) * random.uniform(0.55, 1.0)
                  for i in range(len(self.eq))]
        elif not playing:
            tg = [2.0] * len(self.eq)
        hs = [h + (t - h) * (0.45 if t > h else 0.18) for h, t in zip(hs, tg)]   # monte vite, retombe lentement
        if hs == getattr(self, "_eq_h", None):
            return
        self._eq_h, self._eq_t = hs, tg
        y = self.py - 28 + 9
        for i, (bar, h) in enumerate(zip(self.eq, hs)):
            x = self.px - 70 + i * 9
            self.cv.coords(bar, x * self.kx, (y - h) * self.ky, x * self.kx, y * self.ky)


class CalendarCard(Card):
    def build(self):
        self.header("Agenda")
        self.times = [self.text(16, 40 + i * 30, "", 14, False, self.m.accent, num=True) for i in range(3)]
        self.titles = [self.text(82, 40 + i * 30, "", 13, i == 0, width=self.px - 98) for i in range(3)]

    def update(self, d):
        ev, rem = d["events"], d["reminders"]
        self.set(self.hdr_r, text="" if not rem else f"{rem[0]} rappel{'s' if rem[0] > 1 else ''}",
                 fill=self.m.accent)
        rows = []
        if ev is None and self.m.cfg["calendar_ics"].strip():
            rows = [("", "Lien ICS illisible"), ("", "Vérifiez l'adresse dans les réglages")]
        elif ev is None and not IS_MAC:
            rows = [("", "Ajoutez le lien ICS de votre agenda"), ("", "dans Réglages, Cartes et fond vivant")]
        elif ev is None:
            rows = [("", "Autorisez l'accès au calendrier"), ("", "Réglages Système, Confidentialité")]
        elif not ev:
            rows = [("", "Rien de prévu aujourd'hui ni demain")]
        else:
            today = datetime.now().date()
            for title, start, allday in ev[:3]:
                when = "jour" if allday else start.strftime("%H:%M")
                if start.date() != today:
                    when = "dem." if (start.date() - today).days == 1 else start.strftime("%d/%m")
                rows.append((when, _trunc(title, 30)))
        for i in range(3):
            when, title = rows[i] if i < len(rows) else ("", "")
            self.set(self.times[i], text=when)
            self.cv.coords(self.titles[i], (82 if when else 16) * self.kx, (40 + i * 30) * self.ky)
            self.set(self.titles[i], text=title)


class WeatherCard(Card):
    def build(self):
        self.header("Météo")
        self.temp = self.text(14, 30, "", 52, False, num=True)
        self.icon = self.text(0, 0, "", 26, anchor="w")
        self.lbl = self.text(16, self.py - 34, "", 12, True)
        self.rng = self.text(16, self.py - 15, "", 11, False, self.m.sub, num=True)
        self.hrs = []
        for i in range(4):
            x = self.px - 30 - (3 - i) * 46
            self.hrs.append((self.text(x, 40, "", 10, False, self.m.sub, anchor="n", num=True),
                             self.text(x, 62, "", 15, anchor="n"),
                             self.text(x, 92, "", 13, False, anchor="n", num=True)))

    def update(self, d):
        w = d["weather"]
        if not w:
            self.set(self.lbl, text="Météo indisponible")
            self.set(self.rng, text="Vérifiez la connexion internet")
            return
        self.set(self.hdr, text=w["city"] or "Météo")
        self.set(self.temp, text=f"{w['temp']:.0f}°")
        bb = self.cv.bbox(self.temp)
        if bb:
            self.cv.coords(self.icon, bb[2] + 4 * self.kx, (bb[1] + bb[3]) / 2)
        self.set(self.icon, text=w["icon"])
        self.set(self.lbl, text=w["label"])
        self.set(self.rng, text=f"{w['tmin']:.0f}°  /  {w['tmax']:.0f}°")
        for i, (h_, ic, t) in enumerate(self.hrs):
            h = w["hours"][i] if i < len(w["hours"]) else None
            self.set(h_, text=f"{h[0]:02d}h" if h else "")
            self.set(ic, text=h[2] if h else "")
            self.set(t, text=f"{h[1]:.0f}°" if h else "")


class ProcessCard(Card):
    def build(self):
        self.header("Processus", "processeur")
        self.chip("Tout voir", lambda fin: (self.app.open_processes(), fin("")))
        n = 5 if self.h >= 2 else 2
        self.n, step = n, (self.py - 52) / n
        self.names, self.vals, self.bars, self.xs = [], [], [], []
        bar_w = self.px - 32 - 30
        for i in range(n):
            y = 44 + i * step
            self.names.append(self.text(16, y, "", 13, False, width=self.px - 140))
            self.vals.append(self.text(self.px - 46, y, "", 13, False, anchor="ne", num=True))
            self.cv.create_line(16, y + 24, 16 + bar_w, y + 24, fill=self.m.track, width=3, capstyle="round")
            self.bars.append(self.cv.create_line(16, y + 24, 16, y + 24, fill=self.m.accent, width=3, capstyle="round"))
            x = self.text(self.px - 18, y, "", 13, False, self.m.sub, anchor="ne")
            self.button(x, lambda k=i: self._quit(k), self.m.sub)
            self.xs.append(x)
        self._ys, self._bw = [44 + i * step + 24 for i in range(n)], bar_w
        self.rows = []

    def _quit(self, i):
        if i < len(self.rows):
            _, _, pid, name = self.rows[i]
            if messagebox.askyesno("Quitter le processus", f"Fermer « {name} » ?", parent=self.win):
                macdata.quit_process(pid)

    def update(self, d):
        self.rows = d["procs"] or []
        top = max([r[0] for r in self.rows] + [1.0])
        for i in range(self.n):
            r = self.rows[i] if i < len(self.rows) else None
            self.set(self.names[i], text=_trunc(r[3], 20) if r else "")
            self.set(self.vals[i], text=f"{r[0]:.0f}%" if r else "")
            self.set(self.xs[i], text="✕" if r else "")
            self._bar_t = getattr(self, "_bar_t", [0.0] * self.n)
            self._bar_t[i] = self._bw * (r[0] / top if r else 0)
            self.cv.itemconfigure(self.bars[i], state="normal" if r else "hidden")

    def frame(self):
        tg = getattr(self, "_bar_t", None)
        if not tg:
            return
        cur = getattr(self, "_bar_v", [0.0] * self.n)
        new = [c + (t - c) * 0.2 for c, t in zip(cur, tg)]
        if all(abs(a - b) < 0.05 for a, b in zip(new, cur)):
            return
        self._bar_v = new
        for i, w in enumerate(new):
            y = self._ys[i]
            self.cv.coords(self.bars[i], 16 * self.kx, y * self.ky, (16 + max(w, 0.5)) * self.kx, y * self.ky)


class NotesCard(Card):
    def build(self):
        self.header("Note", "double-clic pour écrire")
        self.body = self.text(16, 38, "", 15, False, width=self.px - 32)
        self.cv.bind("<Double-Button-1>", lambda e: self.edit())

    def edit(self):
        w = tk.Toplevel(self.app.root)
        w.title("Note rapide")
        w.geometry("380x240")
        t = tk.Text(w, wrap="word", font=(TEXT_FONT, 14), padx=12, pady=12, relief="flat",
                    bg=self.m.bg, fg=self.m.fg, insertbackground=self.m.accent, highlightthickness=0)
        t.pack(fill="both", expand=True)
        t.insert("1.0", self.m.cfg["quick_note"])
        t.focus_set()

        def close():
            self.m.cfg["quick_note"] = t.get("1.0", "end").strip()
            save_config(self.m.cfg)
            w.destroy()
        w.protocol("WM_DELETE_WINDOW", close)

    def update(self, d):
        note = self.m.cfg["quick_note"]
        self.set(self.body, text=_trunc(note, 120) if note else "Une idée, un numéro, une tâche : notez-la ici.",
                 fill=self.m.fg if note else self.m.sub)


class ClipboardCard(Card):
    def build(self):
        self.header("Presse-papiers", "clic pour recopier")
        self.rows = []
        for i in range(3):
            y = 38 + i * 36
            if i:
                self.cv.create_line(16, y - 8, self.px - 16, y - 8, fill=self.m.track)
            r = self.text(16, y, "", 13, False, width=self.px - 32)
            self.button(r, lambda k=i: self._copy(k))
            self.rows.append(r)
        self.items = []

    def _copy(self, i):
        if i < len(self.items):
            if not IS_MAC:
                self.app.root.clipboard_clear()
                self.app.root.clipboard_append(self.items[i])
                self.app.root.update()
                return
            try:
                subprocess.run(["pbcopy"], input=self.items[i].encode("utf-8"), timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass

    def update(self, d):
        self.items = list(d["clips"])
        for i, r in enumerate(self.rows):
            self.set(r, text=_trunc(self.items[i], 40) if i < len(self.items) else
                     ("Copiez du texte, il apparaîtra ici" if i == 0 else ""),
                     fill=self.m.fg if i < len(self.items) else self.m.sub)


CARD_CLASSES = {"clock": ClockCard, "system": SystemCard, "storage": StorageCard, "network": NetworkCard,
                "battery": BatteryCard, "music": MusicCard, "calendar": CalendarCard, "weather": WeatherCard,
                "processes": ProcessCard, "notes": NotesCard, "clipboard": ClipboardCard}


def fmt_rate(b):
    return fmt_bytes(b) + "/s"


class CardManager:
    def __init__(self, app):
        self.app, self.cfg = app, app.cfg
        self.cards = {}
        self.sig = None
        self.k = max(1.0, app.root.winfo_fpixels("1i") / 96.0) if IS_WIN else 1.0
        self.unit, self.gap = round(UNIT * self.k), round(GAP * self.k)
        self.layout = "classic"
        self.slow = {"bat_extra": {}, "thermal": 0, "music": None, "events": None, "reminders": None,
                     "weather": None, "procs": [], "clips": []}
        self.menubar = None
        self._clip_count = -1
        self._procs = macdata.ProcSampler()
        self._thread = None
        self.theme_colors()

    # ----- thème -------------------------------------------------------------
    @property
    def active(self):
        return self.cfg["layout"] != "classic"

    def theme_colors(self):
        c = self.cfg
        mode = c["mac_theme"]
        self.dark = mac_native.system_is_dark() if mode == "auto" else mode == "dark"
        accent = (mac_native.system_accent() if c["card_system_accent"] else None) or c["accent_color"]
        self.accent = accent
        if self.dark:   # ardoise, encre, graphite
            self.bg, self.fg, self.sub, self.track = "#15181D", "#EEF1F5", "#9AA3B0", "#2C333D"
            self.edge = "#272D36"
            self.accent2, self.good, self.warn = "#5AD1C4", "#4CD787", "#FF5D4F"
        else:           # papier froid
            self.bg, self.fg, self.sub, self.track = "#F5F7FA", "#14171C", "#5C6573", "#D7DCE3"
            self.edge = "#DDE2E9"
            self.accent2, self.good, self.warn = "#14897D", "#1E8E4E", "#D93A2F"
        self.fallback_bg = self.bg

    # ----- construction ---------------------------------------------------------
    def windows(self):
        return [card.win for card in self.cards.values()]

    def _area(self):
        """Zone utilisable (x0, y0, x1, y1) et marges (haut, bas, côté) : barre des menus et Dock / barre des tâches."""
        if IS_WIN:
            x0, y0, x1, y1 = self.app._work_area()
            m = round(14 * self.k)
            return x0, y0, x1, y1, m, m, m
        x0, y0, x1, y1 = self.app._screen_bounds()
        return x0, y0, x1, y1, 44, 96, 24

    def _wanted(self):
        c = self.cfg
        if c["layout"] == "minimal":
            return ["clock"]
        ids = [k for k in c["cards"] if k in card_ids()]
        if "battery" in ids and psutil.sensors_battery() is None:
            ids.remove("battery")
        return ids

    def build(self, force=False):
        c = self.cfg
        if not self.active:
            self._teardown()
            return
        self.theme_colors()
        ids = self._wanted()
        sig = self._signature(ids)
        if not force and sig == self.sig:
            return
        self.sig = sig
        self.layout = c["layout"]
        for card in self.cards.values():
            card.destroy()
        self.cards = {}
        for k in ids:
            try:
                card = CARD_CLASSES[k](self, k)
                self.cards[k] = card
                card.build()
                card.rescale()
                card.style()
                card.finish()
            except Exception:  # noqa: BLE001  une carte défaillante ne doit pas empêcher les autres
                log_exception(f"carte {k}")
        self._place()
        self._setup_menubar()
        self._setup_hotkey()
        self._ensure_thread()
        if c["widgets_hidden"]:
            for w in self.windows():
                w.withdraw()
        elif not getattr(self, "_entered", False):
            self._entered = True
            self.cascade()
        self.update()

    def cascade(self, delay_ms=120):
        """Les cartes entrent en scène l'une après l'autre, de la plus proche du coin à la plus éloignée."""
        corner_left, corner_top = self.cfg["cards_corner"][1] == "l", self.cfg["cards_corner"][0] == "t"

        def dist(card):
            x, y = self.app.anim.pos(card.win)
            return (x if corner_left else -x) + (y if corner_top else -y)
        for i, card in enumerate(sorted(self.cards.values(), key=dist)):
            self.app.anim.appear(card.win, delay_ms + i * 55)

    def _signature(self, ids):
        c = self.cfg
        return (c["layout"], tuple(ids), c["cards_cols"], c["cards_corner"], self.dark, self.accent, c["card_blur"],
                c["card_radius"], c["card_all_spaces"], c["card_desktop"], c["topmost"], c["opacity"],
                c["card_menubar"], c["card_hotkey"], c["show_seconds"], c["clock_24h"], c["warn_color"],
                c["card_free"], c["card_compact"], c["card_text_scale"], c["calendar_ics"])

    def _teardown(self):
        if self.cards:
            for card in self.cards.values():
                card.destroy()
            self.cards = {}
        self.sig = None
        if self.menubar:
            self.menubar.remove()
            self.menubar = None
        mac_native.unregister_hotkey(1)

    def _place(self, animate=False, ease=None, skip=None):
        final = self._layout(list(self.cards))
        for k, (x, y) in final.items():
            if k == skip:
                continue
            if animate:
                self.app.anim.glide(self.cards[k].win, x, y, 460, ease or anim.ease_out_quint)
            else:
                self.cards[k].win.geometry(f"+{int(x)}+{int(y)}")
        return final

    def _layout(self, ids):
        """Positions (x, y) de chaque carte pour l'ordre donné, sans rien déplacer."""
        c = self.cfg
        saved_order = self.cards
        self.cards = {k: saved_order[k] for k in ids}
        x0, y0, x1, y1, top, bottom, side = self._area()
        max_cols = max(2, (x1 - x0 - 2 * side + self.gap) // (self.unit + self.gap))
        max_rows = max(1, (y1 - y0 - top - bottom + self.gap) // (self.unit + self.gap))
        cols = min(max(2, int(c["cards_cols"])), max_cols)
        occupied, placed, rows, overflow = set(), {}, 0, False

        def find(card, w, ncols, nrows):
            for r in range(0, nrows - card.h + 1):
                for col in range(ncols - w + 1):
                    if all((col + dx, r + dy) not in occupied for dx in range(w) for dy in range(card.h)):
                        return col, r
            return None

        order = self._dense(list(self.cards)) if c["card_compact"] else list(self.cards)
        for k in order:
            card = self.cards[k]
            w = min(card.w, max_cols)
            # 1) dans les colonnes voulues, 2) dans une nouvelle bande à droite, 3) en dépassant en bas
            spot = None
            for ncols in range(cols, max_cols + 1, cols):  # colonnes voulues, puis une nouvelle bande à droite…
                spot = find(card, w, ncols, max_rows)
                if spot:
                    break
            if spot is None:
                overflow, r = True, max_rows
                while (spot := find(card, w, max_cols, r + card.h)) is None:
                    r += 1
            col, r = spot
            for dx in range(w):
                for dy in range(card.h):
                    occupied.add((col + dx, r + dy))
            placed[k] = (col, r)
            rows = max(rows, r + card.h)
        self.overflow = overflow   # écran trop petit pour toutes les cartes (lu par l'autotest)
        if overflow:
            self.app.set_status("Écran trop petit pour toutes les cartes : retirez-en ou réduisez la grille")
        used_cols = max((col + min(self.cards[k].w, max_cols) for k, (col, _) in placed.items()), default=1)
        total_w = used_cols * self.unit + (used_cols - 1) * self.gap
        total_h = rows * self.unit + (rows - 1) * self.gap
        ox = x0 + side if c["cards_corner"][1] == "l" else x1 - total_w - side
        oy = y0 + top if c["cards_corner"][0] == "t" else max(y0 + top, y1 - total_h - bottom)
        # positions enregistrées d'abord ; celles qui en recouvrent une autre sont oubliées (la carte reprend sa case)
        accepted, final = {}, {}
        for k in self.cards:
            pos = c["card_pos"].get(k) if c["card_free"] else None
            if pos is None:
                continue
            if not self.app._valid_pos(pos) or self._hits(self._rect(k, *pos), accepted.values()):
                c["card_pos"].pop(k, None)
                continue
            accepted[k], final[k] = self._rect(k, *pos), tuple(pos)
        for k, (col, r) in placed.items():
            if k in final:
                continue
            x, y = ox + col * (self.unit + self.gap), oy + r * (self.unit + self.gap)
            if self._hits(self._rect(k, x, y), accepted.values()):
                x, y = self._nearest_free(k, x, y, list(accepted.values()))
            accepted[k], final[k] = self._rect(k, x, y), (x, y)
        self.cards = saved_order
        self._slots = dict(accepted)
        return final

    def _dense(self, ids):
        """Ordre de placement qui évite les cases vides : les petites cartes se retrouvent par paires."""
        small = [k for k in ids if self.cards[k].w == 1 and self.cards[k].h == 1]
        out, used = [], set()
        for k in ids:
            if k in used:
                continue
            out.append(k)
            used.add(k)
            if k in small:
                partner = next((s for s in small if s not in used), None)
                if partner:
                    out.append(partner)
                    used.add(partner)
        return out

    # ----- anti-chevauchement -------------------------------------------------------
    def _rect(self, k, x, y):
        card = self.cards[k]
        return (x, y, x + card.wpx, y + card.wpy)

    @staticmethod
    def _hits(rect, others, margin=6):
        return any(rect[0] < o[2] + margin and o[0] < rect[2] + margin and
                   rect[1] < o[3] + margin and o[1] < rect[3] + margin for o in others)

    def _nearest_free(self, k, x, y, others):
        """Position libre (sans toucher une autre carte, dans l'écran) la plus proche de (x, y)."""
        card = self.cards[k]
        x0, y0, x1, y1, top, bottom, side = self._area()
        cands = [(x, y)]
        for o in others:  # contre chaque voisine : à droite, à gauche, dessous, dessus
            cands += [(o[2] + self.gap, y), (o[0] - self.gap - card.wpx, y), (x, o[3] + self.gap), (x, o[1] - self.gap - card.wpy)]
        step = self.unit + self.gap
        cands += [(gx, gy) for gy in range(y0 + top, max(y0 + top + 1, y1 - bottom - card.wpy), step)
                  for gx in range(x0 + side, max(x0 + side + 1, x1 - side - card.wpx), step)]
        best = None
        for cx, cy in cands:
            if not (x0 <= cx and cx + card.wpx <= x1 and y0 <= cy and cy + card.wpy <= y1):
                continue
            if self._hits((cx, cy, cx + card.wpx, cy + card.wpy), others):
                continue
            d = (cx - x) ** 2 + (cy - y) ** 2
            if best is None or d < best[0]:
                best = (d, cx, cy)
        return (best[1], best[2]) if best else (x, y)

    def _drop_order(self, k):
        """Ordre des cartes si la carte k était lâchée là où elle est."""
        card = self.cards[k]
        cx, cy = card.win.winfo_x() + card.wpx / 2, card.win.winfo_y() + card.wpy / 2
        own = getattr(self, "_slots", {}).get(k)
        if own and own[0] <= cx <= own[2] and own[1] <= cy <= own[3]:
            return list(self.cards)   # au-dessus de sa propre place (éventuellement libérée par l'aperçu)
        best = None
        for o, r in getattr(self, "_slots", {}).items():
            if o == k:
                continue
            d = (cx - (r[0] + r[2]) / 2) ** 2 + (cy - (r[1] + r[3]) / 2) ** 2
            inside = r[0] <= cx <= r[2] and r[1] <= cy <= r[3]
            if inside or (best is None or d < best[0]) and d < (self.unit * 0.9) ** 2:
                best = (-1 if inside else d, o)
                if inside:
                    break
        ids = list(self.cards)
        if best:
            before = ids.index(k) < ids.index(best[1])
            ids.remove(k)
            ids.insert(ids.index(best[1]) + (1 if before else 0), k)
        return ids

    def preview_drop(self, k):
        """Pendant le glisser : les autres cartes glissent pour laisser la place où la carte serait posée."""
        now = time.time()
        if now - getattr(self, "_preview_t", 0) < 0.08:
            return
        self._preview_t = now
        ids = self._drop_order(k)
        if ids == list(self.cards):
            return
        self.cards = {i: self.cards[i] for i in ids}
        self.cfg["cards"] = ids + [x for x in self.cfg["cards"] if x not in ids]
        self.sig = self._signature(ids)
        self._place(animate=True, skip=k)

    def reorder(self, k):
        """Mode aligné : la carte lâchée prend la place de celle qui est sous elle ; les autres se réorganisent."""
        card = self.cards[k]
        cx, cy = card.win.winfo_x() + card.wpx / 2, card.win.winfo_y() + card.wpy / 2
        best = None
        own = getattr(self, "_slots", {}).get(k)
        on_own = own and own[0] <= cx <= own[2] and own[1] <= cy <= own[3]
        for o, r in ({} if on_own else getattr(self, "_slots", {})).items():
            if o == k:
                continue
            d = (cx - (r[0] + r[2]) / 2) ** 2 + (cy - (r[1] + r[3]) / 2) ** 2
            inside = r[0] <= cx <= r[2] and r[1] <= cy <= r[3]
            if inside or (best is None or d < best[0]) and d < (self.unit * 0.9) ** 2:
                best = (-1 if inside else d, o)
                if inside:
                    break
        ids = list(self.cards)
        if best:
            ids.remove(k)
            ids.insert(ids.index(best[1]) + (1 if self.cards and list(self.cards).index(k) < list(self.cards).index(best[1]) else 0), k)
            self.cards = {i: self.cards[i] for i in ids}
            self.cfg["cards"] = ids + [x for x in self.cfg["cards"] if x not in ids]
            self.sig = self._signature(ids)
        final = self._place(animate=True, skip=k)
        if k in final:   # la carte lâchée se pose dans sa case avec un petit rebond
            self.app.anim.glide(card.win, *final[k], 380, anim.back)
        save_config(self.cfg)

    def settle(self, k):
        """Après un déplacement à la souris : la carte se cale sur la place libre la plus proche."""
        card = self.cards[k]
        others = [self._rect(o, c.win.winfo_x(), c.win.winfo_y()) for o, c in self.cards.items() if o != k]
        x, y = card.win.winfo_x(), card.win.winfo_y()
        if self._hits(self._rect(k, x, y), others):
            x, y = self._nearest_free(k, x, y, others)
            self.app.anim.glide(card.win, x, y, 380, anim.back)
        return int(x), int(y)

    def reset_positions(self):
        self.cfg["card_pos"] = {}
        self._place(animate=True)
        save_config(self.cfg)

    # ----- barre des menus & raccourci -------------------------------------------
    def _setup_menubar(self):
        if self.menubar:
            self.menubar.remove()
            self.menubar = None
        if IS_MAC and self.cfg["card_menubar"]:
            a = self.app
            self.menubar = mac_native.MenuBarItem([
                ("Afficher / masquer les widgets", lambda: a.call_soon(a.toggle_widgets)),
                ("Paramètres…", lambda: a.call_soon(a.open_settings)),
                ("Processus…", lambda: a.call_soon(a.open_processes)),
                ("Lire le récapitulatif", lambda: a.call_soon(lambda: a.speak_recap(force=True))),
                ("Parler à l'assistant", lambda: a.call_soon(a.listen)),
                None,
                ("Quitter DeskMonitor", lambda: a.call_soon(a.quit)),
            ])

    def _setup_hotkey(self):
        if IS_MAC or IS_WIN:
            spec = self.cfg["card_hotkey"]
            mac_native.register_hotkey(spec, lambda: self.app.call_soon(self.app.toggle_widgets)) if spec else \
                mac_native.unregister_hotkey(1)

    # ----- données lentes (thread) -------------------------------------------------
    def _ensure_thread(self):
        """Un thread par source de données : l'attente d'une autorisation (agenda) ne bloque pas les autres."""
        if getattr(self, "_threads", None):
            return
        c = self.cfg

        def set_battery():
            self.slow["bat_extra"] = macdata.battery_details()
            self.slow["thermal"] = mac_native.thermal_state()

        def set_events():
            url = c["calendar_ics"].strip()
            self.slow["events"] = macdata.ics_events(url) if url else (macdata.next_events() if IS_MAC else None)
            self.slow["reminders"] = macdata.reminders_open() if IS_MAC else None

        jobs = (("battery", 20, set_battery),
                ("music", 3, lambda: self.slow.__setitem__("music", macdata.now_playing())),
                ("calendar", 120, set_events),
                ("weather", 900, lambda: self.slow.__setitem__(
                    "weather", macdata.weather(c["weather_city"]) or self.slow["weather"])),
                ("processes", 2.5, lambda: self.slow.__setitem__("procs", self._procs.top(5))))

        def worker(card, every, job):
            while True:
                if card in self.cards:
                    try:
                        job()
                    except Exception:  # noqa: BLE001
                        log_exception(f"données {card}")
                    time.sleep(every)
                else:
                    time.sleep(1)

        self._threads = [threading.Thread(target=worker, args=j, daemon=True) for j in jobs]
        for t in self._threads:
            t.start()

    # ----- mise à jour --------------------------------------------------------------
    def update(self):
        if not self.cards and not self.menubar:
            return
        a = self.app
        if not a.last:
            return
        self._poll_clipboard()
        try:
            disk = psutil.disk_usage("/System/Volumes/Data" if IS_MAC else
                                     (os.getenv("SystemDrive", "C:") + "\\") if IS_WIN else "/")
        except OSError:
            disk = None
        d = {"cpu": a.last["cpu"], "ram": a.last["ram"], "down": a.last["down"], "up": a.last["up"],
             "hist_down": a.hist["net_down"], "ping": a.sensors.get("ping", "…"), "disk": disk,
             "battery": a._battery(), **self.slow}
        for card in self.cards.values():
            try:
                card.update(d)
            except Exception:  # noqa: BLE001
                pass
        if self.menubar:
            self.menubar.set_text(f"CPU {d['cpu']:.0f}% · RAM {d['ram']:.0f}% · ↓{fmt_rate(d['down'])}")

    def _poll_clipboard(self):
        if "clipboard" not in self.cards:
            return
        if IS_WIN:  # pas de compteur de changements : on compare le texte
            try:
                txt = self.app.root.clipboard_get()
            except tk.TclError:
                return
            n = hash(txt)
        else:
            n, txt = mac_native.clipboard_state()
        if n != self._clip_count:
            self._clip_count = n
            if txt and txt.strip():
                clips = [t for t in self.slow["clips"] if t != txt]
                self.slow["clips"] = ([txt] + clips)[:3]

    def animate(self):
        for card in self.cards.values():
            card.tick()

    def follow_system(self):
        """Appelé régulièrement : réagit au passage du clair au sombre ou à un nouvel accent."""
        if self.active and (self.cfg["mac_theme"] == "auto" or self.cfg["card_system_accent"]):
            self.build()

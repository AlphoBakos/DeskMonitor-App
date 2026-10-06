# -*- coding: utf-8 -*-
"""
Fenêtre de paramètres moderne : barre latérale, sections en cartes, interrupteurs,
recherche instantanée. Chaque réglage s'applique en direct.

Les pages sont décrites de façon déclarative (listes de lignes) : c'est ce qui permet
la recherche et l'ajout facile de nouvelles options.
"""

import os
import subprocess
import sys
from datetime import datetime

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

import lockscreen
import profiles as prof
import wallpapers
from core import (IS_MAC, ALIGNS, APP_NAME, APP_VERSION, CONFIG_DIR, DATE_CASES, DATE_FORMATS, DEFAULTS, IS_WIN,
                  UI_FONT, NUM_FONT, TEXT_FONT, ensure_visible, open_path,
                  SHOW_ITEMS, blend, format_date, is_admin, is_autostart, make_icon_image,
                  set_autostart)

# palette de la fenêtre (indépendante du thème des widgets pour rester toujours lisible)
# ardoise / panneau / encre / graphite : la même famille de tons que les cartes
UI = {"bg": "#101317", "side": "#0B0D11", "card": "#171B21", "card2": "#212731", "field": "#0D1014",
      "line": "#242A33", "text": "#EEF1F5", "muted": "#8C95A3", "hover": "#1A1F26", "off": "#2F3641"}
FONT = TEXT_FONT


_FONTS = []


def font_list(widget):
    """Polices installées (lister les polices peut prendre plusieurs secondes : fait une seule fois,
    en avance, par preload_fonts au démarrage de l'application)."""
    if not _FONTS:
        _FONTS.extend(sorted({f for f in tkfont.families(widget) if not f.startswith("@")}, key=str.lower))
    return _FONTS


def setup_styles(root, accent):
    """Style sombre des widgets ttk de toute l'application (paramètres, processus…)."""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=UI["bg"], foreground=UI["text"], fieldbackground=UI["field"],
                 bordercolor=UI["line"], lightcolor=UI["line"], darkcolor=UI["line"], troughcolor=UI["field"],
                 focuscolor=accent, selectbackground=accent, selectforeground="#FFFFFF",
                 insertcolor=UI["text"], arrowcolor=UI["muted"], font=(FONT, 10))
    st.configure("TCombobox", padding=(8, 4), arrowsize=14)
    st.map("TCombobox", fieldbackground=[("readonly", UI["field"])], foreground=[("readonly", UI["text"])],
           selectbackground=[("readonly", UI["field"])], selectforeground=[("readonly", UI["text"])],
           background=[("active", UI["hover"])], arrowcolor=[("active", accent)],
           bordercolor=[("focus", accent)])
    st.configure("TSpinbox", padding=(8, 4), arrowsize=12)
    st.map("TSpinbox", bordercolor=[("focus", accent)], arrowcolor=[("active", accent)])
    st.configure("TEntry", padding=(8, 5))
    st.map("TEntry", bordercolor=[("focus", accent)])
    st.configure("Horizontal.TScale", background=accent, troughcolor=UI["off"], bordercolor=UI["card"],
                 lightcolor=accent, darkcolor=accent, sliderthickness=16)
    st.configure("Treeview", background=UI["card"], fieldbackground=UI["card"], foreground=UI["text"],
                 rowheight=26, bordercolor=UI["line"])
    st.configure("Treeview.Heading", background=UI["card2"], foreground=UI["muted"], relief="flat",
                 bordercolor=UI["line"])
    st.map("Treeview", background=[("selected", accent)], foreground=[("selected", "#FFFFFF")])
    st.map("Treeview.Heading", background=[("active", UI["hover"])])
    st.configure("TButton", background=UI["card2"], foreground=UI["text"], padding=(12, 5), relief="flat",
                 borderwidth=0)
    st.map("TButton", background=[("active", UI["hover"])])
    st.configure("TCheckbutton", background=UI["bg"], foreground=UI["text"], indicatorbackground=UI["field"])
    st.map("TCheckbutton", background=[("active", UI["bg"])], indicatorbackground=[("selected", accent)])
    st.configure("Vertical.TScrollbar", background=UI["card2"], troughcolor=UI["bg"], bordercolor=UI["bg"],
                 arrowcolor=UI["muted"], lightcolor=UI["card2"], darkcolor=UI["card2"])
    st.configure("TLabel", background=UI["bg"], foreground=UI["text"])
    st.configure("TFrame", background=UI["bg"])
    for opt, val in (("background", UI["field"]), ("foreground", UI["text"]),
                     ("selectBackground", accent), ("selectForeground", "#FFFFFF"), ("font", (FONT, 10))):
        root.option_add(f"*TCombobox*Listbox.{opt}", val)


def dark_titlebar(win):
    """Barre de titre sombre (Windows 10 20H1+ / 11)."""
    if not IS_WIN:
        return
    try:
        import ctypes
        win.update_idletasks()
        u = ctypes.windll.user32
        u.GetParent.restype = ctypes.c_void_p
        u.GetParent.argtypes = [ctypes.c_void_p]
        hwnd = u.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20, ctypes.byref(val), 4)
    except (OSError, AttributeError):
        pass


# --------------------------------------------------------------------------- #
#  Petits composants
# --------------------------------------------------------------------------- #
class Toggle(tk.Canvas):
    """Interrupteur façon Windows 11."""
    W, H = 42, 22

    def __init__(self, parent, value, command, accent, bg):
        super().__init__(parent, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.value, self.command, self.accent = bool(value), command, accent
        self.bind("<Button-1>", self._click)
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h, r = self.W, self.H, self.H / 2
        fill = self.accent if self.value else UI["off"]
        self.create_oval(0, 0, h, h, fill=fill, outline=fill)
        self.create_oval(w - h, 0, w, h, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        x = w - h + 3 if self.value else 3
        self.create_oval(x, 3, x + h - 6, h - 3, fill="#FFFFFF", outline="#FFFFFF")

    def _click(self, _e=None):
        self.value = not self.value
        self._draw()
        self.command(self.value)


class FlatButton(tk.Label):
    def __init__(self, parent, text, command, accent, primary=False, danger=False, small=False):
        self.normal = accent if primary else ("#5A2A30" if danger else UI["card2"])
        self.over = blend(self.normal, "#FFFFFF", 0.12)
        fg = "#FFFFFF" if (primary or danger) else UI["text"]
        super().__init__(parent, text=text, bg=self.normal, fg=fg, cursor="hand2",
                         font=(FONT, 9 if small else 10, "bold" if primary else "normal"),
                         padx=10 if small else 14, pady=3 if small else 6)
        self.bind("<Enter>", lambda e: self.configure(bg=self.over))
        self.bind("<Leave>", lambda e: self.configure(bg=self.normal))
        self.bind("<Button-1>", lambda e: command())


class Swatch(tk.Frame):
    """Pastille de couleur + code hexadécimal ; clic = choisir une couleur."""

    def __init__(self, parent, color, command, bg, show_hex=True, default_label=None):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.command = command
        self.chip = tk.Frame(self, bg=color or UI["off"], width=26, height=20, highlightthickness=1,
                             highlightbackground=UI["line"])
        self.chip.pack(side="left")
        self.lbl = None
        if show_hex:
            self.lbl = tk.Label(self, text=(color or default_label or "").upper(), bg=bg, fg=UI["muted"],
                                font=("Consolas", 9), width=8, anchor="w")
            self.lbl.pack(side="left", padx=(8, 0))
        for w in (self, self.chip, *(x for x in [self.lbl] if x)):
            w.bind("<Button-1>", self._pick)

    def _pick(self, _e=None):
        _, hexa = colorchooser.askcolor(color=self.chip.cget("bg"), parent=self.winfo_toplevel(),
                                        title="Choisir une couleur")
        if hexa:
            self.set(hexa.upper())
            self.command(hexa.upper())

    def set(self, color):
        self.chip.configure(bg=color)
        if self.lbl:
            self.lbl.configure(text=color.upper())


# --------------------------------------------------------------------------- #
#  Description déclarative des lignes
# --------------------------------------------------------------------------- #
def T(key, label, desc="", **kw):
    return dict(type="toggle", key=key, label=label, desc=desc, **kw)


def C(key, label, options, desc="", **kw):
    return dict(type="choice", key=key, label=label, desc=desc, options=options, **kw)


def N(key, label, lo, hi, step=1, unit="", desc="", **kw):
    return dict(type="num", key=key, label=label, desc=desc, lo=lo, hi=hi, step=step, unit=unit, **kw)


def SL(key, label, lo, hi, unit="", desc="", **kw):
    return dict(type="slider", key=key, label=label, desc=desc, lo=lo, hi=hi, unit=unit, **kw)


def COL(key, label, desc="", **kw):
    return dict(type="color", key=key, label=label, desc=desc, **kw)


def F(key, label, desc="", **kw):
    return dict(type="font", key=key, label=label, desc=desc, **kw)


def TXT(key, label, desc="", placeholder="", **kw):
    return dict(type="text", key=key, label=label, desc=desc, placeholder=placeholder, **kw)


def B(label, desc, text, command, primary=False, danger=False, **kw):
    return dict(type="button", label=label, desc=desc, text=text, command=command, primary=primary,
                danger=danger, **kw)


def TN(on_key, key, label, lo, hi, step, unit, desc="", **kw):
    """Interrupteur + valeur (seuils d'alerte)."""
    return dict(type="toggle_num", on_key=on_key, key=key, label=label, desc=desc, lo=lo, hi=hi, step=step,
                unit=unit, **kw)


def X(builder, label=""):
    """Contenu personnalisé sur toute la largeur de la carte."""
    return dict(type="custom", builder=builder, label=label, desc="")


# --------------------------------------------------------------------------- #
#  Fenêtre
# --------------------------------------------------------------------------- #
class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.page = "appearance"
        self._fonts = None
        w = self.win = tk.Toplevel(app.root)
        w.title(f"{APP_NAME} — Paramètres")
        w.configure(bg=UI["bg"])
        w.attributes("-topmost", True)  # toujours au-dessus des widgets et panneaux
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        W, H = min(int(1000 * self.scale), sw - 80), min(int(700 * self.scale), sh - 100)
        w.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        w.minsize(int(760 * self.scale), int(480 * self.scale))
        self._icon = tk.PhotoImage(master=w)
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(make_icon_image(64, self.accent, self.cfg["bg_color"]), master=w)
            w.iconphoto(False, self._icon)
        except Exception:  # noqa: BLE001
            pass
        setup_styles(app.root, self.accent)
        dark_titlebar(w)

        self.side = tk.Frame(w, bg=UI["side"], width=int(230 * self.scale))
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        right = tk.Frame(w, bg=UI["bg"])
        right.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(right, bg=UI["bg"], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(right, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=UI["bg"])
        self._win_id = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win_id, width=e.width))
        w.bind("<MouseWheel>", self._wheel)

        self._build_sidebar()
        self.show(self.page)
        w.bind("<Map>", lambda e: e.widget is w and w.after(80, self._sync_canvas))

    # ----- utilitaires ----------------------------------------------------------
    @property
    def scale(self):
        # macOS compte 72 points par pouce : 72/96 réduisait toute la fenêtre (nom de l'app tronqué)
        return 1.0 if IS_MAC else self.app.root.winfo_fpixels("1i") / 96.0

    @property
    def accent(self):
        return self.cfg["accent_color"]   # palette commune à tous les widgets (voir _sync_palette)

    def _sync_canvas(self):
        """Recale la zone de contenu sur la taille réelle de la fenêtre (au cas où Windows
        n'aurait pas envoyé l'événement de redimensionnement, ex. au premier affichage)."""
        try:
            if not self.win.winfo_exists():
                return
            self.win.update_idletasks()
            w = self.canvas.winfo_width()
            if w > 1:
                self.canvas.itemconfigure(self._win_id, width=w)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            ensure_visible(self.win)
        except tk.TclError:
            pass

    def _wheel(self, e):
        # les listes déroulantes gèrent leur propre molette
        if isinstance(e.widget, str) or e.widget.winfo_class() in ("TCombobox", "Listbox", "TSpinbox"):
            return
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def fonts(self):
        return font_list(self.win)

    def get(self, key):
        if "." in key:
            a, b = key.split(".", 1)
            return self.cfg[a][b]
        return self.cfg[key]

    def set(self, key, value):
        if "." in key:
            a, b = key.split(".", 1)
            self.cfg[a][b] = value
        else:
            self.cfg[key] = value
        if key == "accent_mode" and value == "wallpaper":   # couleur du fond d'écran calculée tout de suite
            try:
                self.cfg["accent_color"] = prof.theme_from_wallpaper()["accent_color"]
            except Exception:  # noqa: BLE001
                pass
        self.app.schedule_rebuild()
        if key in self.RELAYOUT_KEYS:   # options qui font apparaître / disparaître d'autres réglages
            self.win.after(250, self.refresh)
        if key.startswith("lock_") and getattr(self, "_preview_lbl", None) is not None:
            if getattr(self, "_preview_after", None):
                self.win.after_cancel(self._preview_after)
            self._preview_after = self.win.after(350, self._update_preview)  # aperçu en direct

    # ----- barre latérale -------------------------------------------------------
    PAGES = [
        ("appearance", "◐", "Apparence", "Un seul style pour tous les widgets : cartes, applications, horloge"),
        ("widgets", "▥", "Widgets", "Ce que les widgets affichent et comment ils mesurent"),
        ("clock", "◷", "Heure et date", "Format de l'heure et de la date"),
        ("desktop", "▦", "Applications", "Vos applications rangées en panneaux sur le bureau"),
        ("wallpapers", "◩", "Fond d'écran", "Collection, diaporama et fond d'écran vivant"),
        ("lock", "◫", "Écran de verrouillage", "Image, date et message de l'écran de verrouillage"),
        ("assistant", "◌", "Assistant", "Votre prénom, la voix et les commandes vocales"),
        ("alerts", "◉", "Alertes", "Notifications quand la machine souffre"),
        ("profiles", "◍", "Profils", "Changer toute l'apparence en un clic"),
        ("general", "◎", "Général", "Démarrage, raccourci, nettoyage et mises à jour"),
        ("about", "○", "À propos", ""),
    ]
    RELAYOUT_KEYS = ("layout", "accent_mode", "mac_theme", "card_blur", "org_enabled")

    def pages(self):
        """Pages disponibles sur ce système (l'écran de verrouillage n'est personnalisable que sous Windows)."""
        return [p for p in self.PAGES if IS_WIN or p[0] != "lock"]

    def _build_sidebar(self):
        s = self.side
        for ch in s.winfo_children():
            ch.destroy()
        head = tk.Frame(s, bg=UI["side"], padx=18, pady=18)
        head.pack(fill="x")
        tk.Label(head, image=self._icon, bg=UI["side"]).pack(side="left")
        box = tk.Frame(head, bg=UI["side"])
        box.pack(side="left", padx=10)
        tk.Label(box, text=APP_NAME, bg=UI["side"], fg=UI["text"], font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(box, text=f"version {APP_VERSION}", bg=UI["side"], fg=UI["muted"],
                 font=(NUM_FONT, 10)).pack(anchor="w")

        # recherche
        sf = tk.Frame(s, bg=UI["field"], highlightthickness=1, highlightbackground=UI["line"],
                      highlightcolor=self.accent)
        sf.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(sf, text="⌕", bg=UI["field"], fg=UI["muted"], font=(FONT, 20)).pack(side="left", padx=(10, 4))
        self.search_var = tk.StringVar(s)
        ent = tk.Entry(sf, textvariable=self.search_var, bg=UI["field"], fg=UI["text"], relief="flat",
                       insertbackground=self.accent, font=(FONT, 11), highlightthickness=0, bd=0)
        ent.pack(side="left", fill="x", expand=True, ipady=6)
        ph = tk.Label(sf, text="Rechercher un réglage", bg=UI["field"], fg=UI["muted"], font=(FONT, 11))
        ph.place(x=34, rely=0.5, anchor="w")
        ph.bind("<Button-1>", lambda e: ent.focus_set())
        self.search_var.trace_add("write", lambda *_: (ph.place_forget() if self.search_var.get()
                                                       else ph.place(x=34, rely=0.5, anchor="w"),
                                                       self._on_search()))

        self.nav = {}
        for key, emo, title, _ in self.pages():
            row = tk.Frame(s, bg=UI["side"], cursor="hand2")
            row.pack(fill="x", padx=8, pady=1)
            bar = tk.Frame(row, bg=UI["side"], width=3)
            bar.pack(side="left", fill="y", pady=6)
            ico = tk.Label(row, text="", bg=UI["side"], width=1)   # navigation purement typographique
            ico.pack(side="left", padx=(6, 4), pady=9)
            lbl = tk.Label(row, text=title, bg=UI["side"], fg=UI["muted"], font=(FONT, 12), anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            parts = (row, ico, lbl)
            for p in parts:
                p.bind("<Button-1>", lambda e, k=key: (self.search_var.set(""), self.show(k)))
                p.bind("<Enter>", lambda e, k=key, ps=parts: self._nav_hover(k, ps, True))
                p.bind("<Leave>", lambda e, k=key, ps=parts: self._nav_hover(k, ps, False))
            self.nav[key] = (row, bar, ico, lbl)

        foot = tk.Frame(s, bg=UI["side"], padx=14, pady=14)
        foot.pack(side="bottom", fill="x")
        FlatButton(foot, "Fermer", self.win.destroy, self.accent).pack(fill="x")

    def _nav_hover(self, key, parts, on):
        if key == self.page and not self.search_var.get():
            return
        for p in parts:
            p.configure(bg=UI["hover"] if on else UI["side"])

    def _select_nav(self, key):
        for k, (row, bar, ico, lbl) in self.nav.items():
            sel = k == key
            bg = UI["card2"] if sel else UI["side"]
            for p in (row, ico, lbl):
                p.configure(bg=bg)
            bar.configure(bg=self.accent if sel else bg)
            ico.configure(fg=self.accent if sel else UI["muted"])
            lbl.configure(font=(FONT, 12, "bold" if sel else "normal"), fg=UI["text"] if sel else UI["muted"])

    # ----- rendu ----------------------------------------------------------------
    def show(self, key):
        self.page = key
        self._select_nav(key)
        _, emo, title, sub = next(p for p in self.PAGES if p[0] == key)
        self._render(title, sub, getattr(self, f"p_{key}")())

    def refresh(self):
        """Redessine la page (après un changement de thème, un profil…)."""
        setup_styles(self.app.root, self.accent)
        self._build_sidebar()
        if self.search_var.get():
            self._on_search()
        else:
            self.show(self.page)

    def _on_search(self):
        q = self.search_var.get().strip().lower()
        if not q:
            self.show(self.page)
            return
        self._select_nav(None)
        cards = []
        for key, emo, title, _ in self.pages():
            for card_title, rows in getattr(self, f"p_{key}")():
                hits = [r for r in rows if r["type"] != "custom" and
                        (q in r["label"].lower() or q in r.get("desc", "").lower())]
                if hits:
                    cards.append((f"{emo}  {title}  ›  {card_title}", hits))
        sub = f"{sum(len(r) for _, r in cards)} réglage(s) trouvé(s)" if cards else "Aucun réglage ne correspond."
        self._render(f"Recherche : « {self.search_var.get().strip()} »", sub, cards)

    def _render(self, title, subtitle, cards):
        for ch in self.content.winfo_children():
            ch.destroy()
        self._preview_lbl = None
        self._thumbs = []
        self.canvas.yview_moveto(0)
        pad = int(28 * self.scale)
        head = tk.Frame(self.content, bg=UI["bg"], padx=pad, pady=int(22 * self.scale))
        head.pack(fill="x")
        tk.Label(head, text=title, bg=UI["bg"], fg=UI["text"], font=(FONT, 24, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(head, text=subtitle, bg=UI["bg"], fg=UI["muted"], font=(FONT, 12)).pack(anchor="w", pady=(2, 0))
        self.win.after(60, self._sync_canvas)
        for card_title, rows in cards:
            rows = [r for r in rows if r.get("cond", True)]
            if not rows:
                continue
            card = tk.Frame(self.content, bg=UI["card"], padx=int(18 * self.scale), pady=int(14 * self.scale))
            card.pack(fill="x", padx=pad, pady=(0, int(14 * self.scale)))
            if card_title:
                tk.Label(card, text=card_title, bg=UI["card"], fg=self.accent,
                         font=(FONT, 12, "bold")).pack(anchor="w", pady=(0, 4))
            for i, r in enumerate(rows):
                if i:
                    tk.Frame(card, bg=UI["line"], height=1).pack(fill="x")
                self._row(card, r)
        tk.Frame(self.content, bg=UI["bg"], height=int(20 * self.scale)).pack()

    def _row(self, card, r):
        bg = UI["card"]
        if r["type"] == "custom":
            holder = tk.Frame(card, bg=bg)
            holder.pack(fill="x", pady=6)
            r["builder"](holder)
            return
        row = tk.Frame(card, bg=bg)
        row.pack(fill="x", pady=int(8 * self.scale))
        txt = tk.Frame(row, bg=bg)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=r["label"], bg=bg, fg=UI["text"], font=(FONT, 12), anchor="w",
                 justify="left").pack(anchor="w")
        if r.get("desc"):
            tk.Label(txt, text=r["desc"], bg=bg, fg=UI["muted"], font=(FONT, 11), anchor="w", justify="left",
                     wraplength=int(430 * self.scale)).pack(anchor="w")
        ctl = tk.Frame(row, bg=bg)
        ctl.pack(side="right", padx=(12, 0))
        getattr(self, f"_ctl_{r['type']}")(ctl, r)

    # ----- contrôles ------------------------------------------------------------
    def _ctl_toggle(self, parent, r):
        getter = r.get("get") or (lambda: bool(self.get(r["key"])))
        setter = r.get("set") or (lambda v: self.set(r["key"], v))
        Toggle(parent, getter(), setter, self.accent, UI["card"]).pack()

    def _ctl_choice(self, parent, r):
        opts = r["options"]
        keys = list(opts)
        cb = ttk.Combobox(parent, values=list(opts.values()), state="readonly", width=r.get("width", 24))
        cur = self.get(r["key"])
        cb.current(keys.index(cur) if cur in keys else 0)
        cb.bind("<<ComboboxSelected>>", lambda e: self.set(r["key"], keys[cb.current()]))
        cb.pack()

    def _spin(self, parent, key, lo, hi, step, unit):
        var = tk.StringVar(parent, str(self.get(key)))

        def changed(*_):
            try:
                v = int(float(var.get()))
            except ValueError:
                return
            if lo <= v <= hi:
                self.set(key, v)

        var.trace_add("write", changed)
        ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=7).pack(side="left")
        if unit:
            tk.Label(parent, text=unit, bg=UI["card"], fg=UI["muted"], font=(FONT, 9), width=4,
                     anchor="w").pack(side="left", padx=(6, 0))

    def _ctl_num(self, parent, r):
        self._spin(parent, r["key"], r["lo"], r["hi"], r["step"], r["unit"])

    def _ctl_toggle_num(self, parent, r):
        self._spin(parent, r["key"], r["lo"], r["hi"], r["step"], r["unit"])
        Toggle(parent, self.get(r["on_key"]), lambda v: self.set(r["on_key"], v), self.accent,
               UI["card"]).pack(side="left", padx=(12, 0))

    def _ctl_slider(self, parent, r):
        val = tk.Label(parent, text=f"{self.get(r['key'])} {r['unit']}", bg=UI["card"], fg=UI["muted"],
                       font=(FONT, 9), width=6, anchor="e")

        def moved(v):
            v = int(float(v))
            val.configure(text=f"{v} {r['unit']}")
            if v != self.get(r["key"]):
                self.set(r["key"], v)

        sc = ttk.Scale(parent, from_=r["lo"], to=r["hi"], orient="horizontal", length=int(200 * self.scale),
                       command=moved)
        sc.set(self.get(r["key"]))
        sc.pack(side="left")
        val.pack(side="left", padx=(8, 0))

    def _ctl_color(self, parent, r):
        Swatch(parent, self.get(r["key"]), lambda c: self.set(r["key"], c), UI["card"]).pack()

    def _ctl_font(self, parent, r):
        var = tk.StringVar(parent, self.get(r["key"]))
        cb = ttk.Combobox(parent, values=self.fonts(), textvariable=var, width=24)
        cb.bind("<<ComboboxSelected>>", lambda e: self.set(r["key"], var.get()))
        cb.bind("<Return>", lambda e: self.set(r["key"], var.get()))
        cb.bind("<FocusOut>", lambda e: var.get() != self.get(r["key"]) and self.set(r["key"], var.get()))
        cb.pack()

    def _ctl_text(self, parent, r):
        var = tk.StringVar(parent, self.get(r["key"]))
        var.trace_add("write", lambda *_: self.set(r["key"], var.get().strip()))
        e = ttk.Entry(parent, textvariable=var, width=r.get("width", 26))
        e.pack()

    def _ctl_button(self, parent, r):
        FlatButton(parent, r["text"], r["command"], self.accent, primary=r.get("primary"),
                   danger=r.get("danger")).pack()

    # ======================================================================== #
    #  Pages
    # ======================================================================== #
    @property
    def layout(self):
        return self.cfg["layout"]

    def _note(self, text):
        """Petit texte explicatif sur toute la largeur d'une carte."""
        def build(parent):
            tk.Label(parent, text=text, bg=UI["card"], fg=UI["muted"], font=(FONT, 11), justify="left",
                     anchor="w", wraplength=int(620 * self.scale)).pack(anchor="w")
        return X(build)

    def p_appearance(self):
        import cards
        c = self.cfg
        on_cards = self.layout == "cards"
        glass = (IS_WIN or IS_MAC) and bool(c["card_blur"])
        return [
            ("Style", [
                C("layout", "Disposition des widgets", cards.LAYOUTS,
                  "Cartes en colonnes, heure seule, ou ancienne colonne de monitoring"),
                C("mac_theme", "Thème", {"auto": "Automatique (suit Windows)" if IS_WIN else
                                         "Automatique (suit le système)", "dark": "Sombre", "light": "Clair"},
                  "Cartes, panneaux d'applications, horloge et notifications prennent tous ces couleurs"),
                C("accent_mode", "Couleur d'accent", {"system": "Celle du système",
                                                      "custom": "Personnalisée",
                                                      "wallpaper": "Tirée du fond d'écran"},
                  "Jauges, graphiques, icônes des panneaux, date"),
                COL("accent_color", "Couleur personnalisée", cond=c["accent_mode"] == "custom"),
            ]),
            ("Rendu", [
                T("card_blur", "Effet verre", "Arrière-plan flouté façon verre dépoli" +
                  (", comme les widgets de macOS" if IS_MAC else ", comme Windows 11"), cond=IS_WIN or IS_MAC),
                SL("opacity", "Teinte du verre" if glass else "Opacité", 20, 100, "%",
                   "Plus bas = plus transparent"),
                SL("card_radius", "Arrondi des coins", 6, 36, "px"),
                SL("card_text_scale", "Taille du texte", 80, 160, "%", "Agrandit ou réduit tous les textes"),
                T("animations", "Animations", "Entrée en cascade, survols lumineux, cartes qui s'écartent quand on "
                  "en déplace une, compteurs et courbes fluides, panneaux qui se plient en douceur"),
                T("transparent_bg", "Fond de la colonne transparent", "Seul le texte reste visible",
                  cond=IS_WIN and self.layout == "classic"),
            ]),
            ("Sur le bureau", [
                T("card_desktop", "Sous les fenêtres, au niveau du bureau",
                  "Les widgets ne passent plus devant vos applications", cond=IS_WIN or IS_MAC),
                T("topmost", "Toujours au premier plan", "Les widgets restent devant vos fenêtres",
                  cond=not c["card_desktop"]),
                T("card_all_spaces", "Visible sur tous les bureaux (Spaces)", cond=IS_MAC),
                C("cards_corner", "Coin de l'écran", cards.CORNERS, cond=self.layout != "classic"),
                N("cards_cols", "Largeur de la grille", 2, 8, 1, "cases",
                  "2 = deux cases de large, les cartes suivantes s'empilent en dessous", cond=on_cards),
                T("card_compact", "Combler les cases vides", "Rapproche les petites cartes", cond=on_cards),
                T("card_free", "Placement libre", "Désactivé : les cartes restent alignées sur la grille",
                  cond=self.layout != "classic"),
                T("locked", "Verrouiller les positions", "Empêche de déplacer les widgets par erreur"),
                B("Tout ranger", "Cartes dans leur coin, panneaux d'applications alignés à côté, sans chevauchement",
                  "Ranger tout le bureau", lambda: self.app.tidy_desktop(), primary=True),
            ]),
        ]

    def p_widgets(self):
        import cards
        from core import save_config  # noqa: F401
        cfg = self.cfg
        lay = self.layout

        def card_toggle(k):
            def get():
                return k in cfg["cards"]

            def setter(v):
                ids = [x for x in cfg["cards"] if x != k]
                if v:
                    ids = [x for x in cards.card_ids() if x in ids or x == k]
                cfg["cards"] = ids
                self.app.schedule_rebuild()
            return T(None, cards.CARD_TYPES[k][0], get=get, set=setter)

        shown = [T(f"show.{k}", v) for k, v in SHOW_ITEMS.items() if k not in ("clock", "date")]
        out = []
        if lay == "minimal":
            out.append(("Disposition minimale", [self._note(
                "Seule l'heure est affichée. Choisissez « Cartes empilées » dans Apparence pour ajouter "
                "le monitoring, la météo, l'agenda ou la musique.")]))
        if lay == "cards":
            out += [
                ("Cartes affichées", [card_toggle(k) for k in cards.card_ids()]),
                ("Contenu des cartes", [
                    TXT("weather_city", "Ville de la météo", "Vide : position approximative d'après votre adresse IP",
                        placeholder="Paris"),
                    TXT("calendar_ics", "Lien de l'agenda (ICS)",
                        "Adresse privée .ics de Google Agenda, Outlook.com, iCloud…" +
                        (" Indispensable sous Windows" if IS_WIN else ""),
                        placeholder="https://calendar.google.com/…/basic.ics"),
                ]),
            ]
        if lay == "classic":
            out += [
                ("Éléments affichés", shown),
                ("Colonne", [
                    F("font_family", "Police du texte"),
                    N("width", "Largeur", 180, 700, 10, "px"),
                    N("padding", "Marge intérieure", 4, 40, 2, "px"),
                    C("buttons_style", "Boutons d'action", {"both": "Icône et texte", "icon": "Icône seule",
                                                            "text": "Texte seul"}),
                    T("graphs", "Graphiques d'historique", "Courbe des 60 dernières mesures"),
                    T("graph_fill", "Remplir sous la courbe"),
                    N("graph_height", "Hauteur des graphiques", 12, 80, 2, "px"),
                    N("bar_height", "Épaisseur des barres", 2, 16, 1, "px"),
                ]),
            ]
        out.append(("Mesures", [
            N("warn_threshold", "Seuil du rouge", 50, 100, 5, "%",
              "Au-delà, jauges et barres passent dans la couleur d'alerte"),
            N("refresh_ms", "Fréquence de rafraîchissement", 250, 10000, 250, "ms"),
            TXT("ping_host", "Serveur testé par le ping", "Ex. : 1.1.1.1, 8.8.8.8, google.com"),
        ]))
        return out

    def p_clock(self):
        now = datetime.now()
        formats = {k: format_date(now, {"date_format": k}) for k in DATE_FORMATS}
        classic = self.layout == "classic"
        return [
            ("Heure", [
                T("clock_24h", "Format 24 heures", "Sinon : 02:30 PM"),
                T("show_seconds", "Afficher les secondes"),
                T("clock_blink", "Deux-points clignotants", "Le « : » clignote chaque seconde", cond=classic),
            ]),
            ("Date", [
                C("date_format", "Format", formats, width=28),
                C("date_case", "Majuscules", DATE_CASES),
                T("date_two_lines", "Jour de la semaine sur une ligne à part"),
                T("date_week", "Numéro de semaine", "Ajoute « · Semaine 40 »"),
            ]),
            ("Police de la colonne classique", [
                F("clock_font", "Police de l'heure"),
                N("clock_size", "Taille de l'heure", 10, 160, 2, "pt"),
                C("clock_align", "Alignement de l'heure", ALIGNS),
                T("clock_bold", "Heure en gras"),
                F("date_font", "Police de la date"),
                N("date_size", "Taille de la date", 7, 72, 1, "pt"),
                C("date_align", "Alignement de la date", ALIGNS),
                T("date_bold", "Date en gras"),
            ] if classic else []),
            ("Widgets séparés", [
                T("detach_clock", "Heure dans son propre widget", "À placer où vous voulez sur le bureau"),
                T("transparent_clock", "Fond transparent pour l'heure", cond=IS_WIN),
                T("detach_date", "Date dans son propre widget"),
                T("transparent_date", "Fond transparent pour la date", cond=IS_WIN),
            ] if classic else []),
        ]

    def p_desktop(self):
        org = self.app.organizer
        return [
            ("Général", [
                T("org_enabled", "Panneaux d'applications sur le bureau",
                  "Vos applications rangées dans des panneaux thématiques. Aucun fichier n'est déplacé."),
                C("org_source", "Applications affichées", {"apps": "Toutes celles de l'ordinateur",
                                                           "desktop": "Seulement celles du bureau"}),
                T("org_hide_icons", "Masquer les icônes Windows du bureau", "Réaffichées à la fermeture",
                  cond=IS_WIN),
                T("org_system", "Ajouter Ce PC, Corbeille et Téléchargements", cond=IS_WIN),
                T("org_labels", "Noms sous les icônes"),
                T("org_double_click", "Ouvrir avec un double-clic", "Évite les ouvertures accidentelles"),
            ]),
            ("Disposition", [
                N("org_columns", "Icônes par ligne", 1, 12),
                N("org_max_rows", "Lignes visibles par panneau", 0, 20, 1, "",
                  "Au-delà, la molette fait défiler le panneau (0 = tout afficher)"),
                C("org_icon", "Taille des icônes", {32: "Petites", 40: "Moyennes", 48: "Grandes",
                                                    64: "Très grandes"}),
                B("Rangement", "Répartit les panneaux à côté des cartes, sans chevauchement", "Ranger tout le bureau",
                  lambda: self.app.tidy_desktop()),
                B("Liste des applications", "Relit les applications installées", "Actualiser", org.refresh_all),
                B("Raccourcis masqués", f"{len(self.cfg['org_hidden'])} raccourci(s) masqué(s)",
                  "Tout réafficher", lambda: (org.unhide_all(), self.refresh())),
            ]),
            ("Panneaux", [X(self._panels_table)]),
        ]

    def p_wallpapers(self):
        return [
            ("Collection", [X(self._wallpaper_gallery)]),
            ("Options", [
                C("wallpaper_fit", "Disposition de l'image", wallpapers.FIT_LABELS),
                T("wallpaper_lock_too", "Utiliser aussi pour l'écran de verrouillage",
                  "Avec la date et le message choisis dans « Écran de verrouillage »"),
            ]),
            ("Diaporama", [
                T("slideshow", "Changer de fond d'écran automatiquement"),
                N("slideshow_minutes", "Toutes les", 1, 1440, 5, "min"),
                T("slideshow_shuffle", "Ordre aléatoire"),
                B("Image suivante", "Passe tout de suite à l'image suivante", "Suivante",
                  lambda: (lambda p: p and self.app.apply_wallpaper(p))(wallpapers.next_slideshow(self.cfg))),
            ]),
            ("Fond d'écran vivant", [
                T("wp_dyn_time", "Teinte selon l'heure", "Matin chaud, soir orangé, nuit sombre"),
                T("wp_dyn_state", "Ambiance selon l'état de l'ordinateur",
                  "Rouge si CPU ou RAM saturés, sombre si batterie faible, terne hors ligne"),
                T("wp_dyn_stats", "Jauges CPU / RAM / disque sur le fond", "Mises à jour au plus toutes les 3 minutes"),
                self._note("Couleur des widgets assortie au fond d'écran : Apparence › Couleur d'accent."),
            ]),
        ]

    def p_lock(self):
        now = datetime.now()
        formats = {k: format_date(now, {"date_format": k}) for k in DATE_FORMATS}
        return [
            ("Aperçu", [X(self._lock_preview)]),
            ("Image", [X(self._lock_image_picker)]),
            ("Date et message", [
                T("lock_show_date", "Afficher la date", "Remise à jour automatiquement chaque jour"),
                C("lock_date_format", "Format de la date", formats, width=28),
                C("lock_date_case", "Majuscules", DATE_CASES),
                TXT("lock_text", "Message personnel", "Ex. : votre nom, une citation… (laisser vide pour aucun)",
                    width=30),
                F("lock_font", "Police"),
                N("lock_size", "Taille", 16, 160, 4, "pt"),
                COL("lock_color", "Couleur du texte"),
                C("lock_pos", "Position", lockscreen.POSITIONS),
                T("lock_bold", "Gras"),
                T("lock_shadow", "Ombre portée", "Améliore la lisibilité sur les images claires"),
            ]),
            ("Effets", [
                SL("lock_dim", "Assombrir l'image", 0, 80, "%"),
                SL("lock_blur", "Flou", 0, 30, "px"),
            ]),
            ("Windows", [
                T("lock_enabled", "Gérer l'écran de verrouillage avec DeskMonitor",
                  "Garde la date à jour chaque jour"),
                T(None, "Horloge en 24 heures", "Réglage de Windows : s'applique aussi à la barre des tâches",
                  cond=IS_WIN, get=lockscreen.clock_24h, set=lambda v: lockscreen.set_clock_24h(v)),
                T(None, "Astuces et publicités de Windows", "Textes « Le saviez-vous ? », suggestions…",
                  cond=IS_WIN, get=lockscreen.tips_enabled, set=lambda v: lockscreen.set_tips(v)),
            ]),
        ]

    def p_assistant(self):
        import voice as voicemod
        voices = {"": "Automatique (meilleure voix de la langue)",
                  voicemod.SYSTEM: "Voix du système (Siri si choisie dans macOS)" if IS_MAC else "Voix par défaut de Windows",
                  **{n: f"{lbl}, français" for n, lbl in voicemod.voices("fr").items()},
                  **{n: f"{lbl}, anglais" for n, lbl in voicemod.voices("en").items()}}
        return [
            ("Vous et votre assistant", [
                TXT("user_name", "Votre prénom", "L'assistant vous appelle par ce prénom", placeholder="Alpho"),
                TXT("assistant_name", "Nom de l'assistant", "Le nom qu'il se donne en se présentant", placeholder="Jarvis"),
                C("voice_lang", "Langue de l'assistant", {"fr": "Français", "en": "Anglais"},
                  "Récapitulatif, alertes et réponses sont dits dans cette langue"),
            ]),
            ("Ce qu'il sait faire", [self._note(
                "Ouvrir une application : « ouvre Chrome », « lance Excel ».\n"
                "Ouvrir un dossier ou un fichier : « ouvre le dossier téléchargements », « ouvre le fichier rapport ».\n"
                "Chercher sur internet : « cherche recette de crêpes », « recherche le match du PSG sur YouTube ».\n"
                "Entretien : « libère la mémoire », « nettoie le cache », « vide le cache DNS », « optimise le PC ».\n"
                "Et toujours : le point, la batterie, la météo, l'agenda, l'heure, la musique, ranger le bureau.\n"
                "Avec l'activation par la voix, dites son nom d'abord : « Bakos, ouvre Chrome ».")]),
            ("Commandes vocales", [
                TXT("listen_hotkey", "Raccourci pour parler", "Appuyez, puis parlez : « le point », « ma batterie », "
                    "« la météo », « mes rendez-vous », « qui ralentit l'ordinateur », « pause »…",
                    placeholder="cmd+alt+j"),
                T("wake_on", "Activation par la voix",
                  "Dites son nom, puis votre question (« [nom], quelle heure est-il ? »). Le micro reste actif, "
                  "tout est traité sur l'ordinateur, hors ligne", cond=IS_MAC or IS_WIN),
                B("Apprendre son nom", "Dites son nom 3 fois : il le reconnaîtra mieux avec votre voix",
                  "Apprendre", lambda: self.app.learn_name(), cond=IS_MAC or IS_WIN),
                T("wake_battery_off", "Couper l'écoute sur batterie", cond=IS_MAC or IS_WIN),
                T("wake_night_off", "Couper l'écoute pendant les heures de silence", cond=IS_MAC or IS_WIN),
                B("Essayer", "L'assistant écoute une phrase et vous répond", "Parler maintenant",
                  lambda: self.app.listen(), primary=True),
                B("Présentation", "L'assistant se présente et fait le point", "Écouter la présentation",
                  lambda: self.app.introduce()),
            ]),
            ("Voix", [
                T("voice_on", "Annonces vocales", "DeskMonitor vous parle : récapitulatif et valeurs dans le rouge"),
                T("voice_recap", "Récapitulatif au lancement", "Heure, machine, batterie, météo, agenda"),
                T("voice_alerts", "Annoncer ce qui passe dans le rouge",
                  "Processeur, mémoire, disque, batterie faible, connexion perdue"),
                C("voice_name", "Voix", voices, "Les voix neuronales (Vivienne, Denise, Henri…) ont une intonation "
                  "humaine ; sans internet, la meilleure voix installée prend le relais automatiquement",
                  width=34),
                SL("voice_rate", "Débit", 130, 260, "mots/min"),
                T("voice_quiet", "Silence la nuit"),
                N("voice_quiet_from", "Silence à partir de", 0, 23, 1, "h"),
                N("voice_quiet_to", "Jusqu'à", 0, 23, 1, "h"),
                B("Écouter", "Le récapitulatif tel qu'il serait annoncé maintenant", "Lire le récapitulatif",
                  lambda: self.app.speak_recap(force=True), primary=True),
            ]),
        ]

    def p_alerts(self):
        return [
            ("Général", [
                T("alerts", "Activer les alertes", "Notification en bas à droite de l'écran"),
                T("native_alerts", "Notifications du centre de notifications macOS" if IS_MAC else
                  "Notifications de Windows", "Au lieu de la bulle de DeskMonitor", cond=IS_MAC or IS_WIN),
                T("alert_sound", "Jouer un son"),
                N("alert_cooldown", "Délai entre deux alertes identiques", 1, 240, 1, "min"),
                B("Aperçu", "Affiche une notification d'exemple", "Tester une alerte",
                  lambda: self.app.notify("Exemple d'alerte",
                                          "Voici à quoi ressemblent les notifications de DeskMonitor.")),
            ]),
            ("Seuils", [
                TN("alert_cpu_on", "alert_cpu", "Processeur au-dessus de", 30, 100, 5, "%"),
                N("alert_cpu_secs", "… pendant au moins", 5, 600, 5, "s"),
                TN("alert_ram_on", "alert_ram", "Mémoire (RAM) au-dessus de", 30, 100, 5, "%"),
                TN("alert_disk_on", "alert_disk_gb", "Espace libre du disque système sous", 1, 500, 1, "Go"),
                TN("alert_bat_on", "alert_bat", "Batterie débranchée sous", 5, 90, 5, "%"),
                TN("alert_gputemp_on", "alert_gputemp", "Température du GPU au-dessus de", 50, 110, 5, "°C",
                   "Lisible uniquement sur les cartes NVIDIA"),
                T("alert_offline_on", "Perte de la connexion internet"),
            ]),
        ]

    def p_profiles(self):
        return [
            ("Mes profils", [X(self._profiles_list)]),
            ("Profils automatiques", [
                T("ctx_on", "Changer de profil automatiquement", "Un profil sur batterie, un autre la nuit"),
                C("ctx_battery_profile", "Quand le portable est sur batterie",
                  {"": "Aucun", **{n: n for n in self.app.profiles.names()}}),
                C("ctx_night_profile", "La nuit", {"": "Aucun", **{n: n for n in self.app.profiles.names()}}),
                N("ctx_night_from", "La nuit commence à", 0, 23, 1, "h"),
                N("ctx_night_to", "La nuit se termine à", 0, 23, 1, "h"),
            ]),
            ("Enregistrer", [
                B("Nouveau profil", "Enregistre l'apparence actuelle (thème, widgets, panneaux, positions)",
                  "Enregistrer sous…", self._profile_save_as, primary=True),
            ]),
            ("Transférer vers un autre PC", [
                B("Exporter", "Tous vos réglages dans un fichier (.json)", "Exporter…", self._export),
                B("Importer", "Remplace vos réglages par ceux d'un fichier exporté", "Importer…", self._import),
            ]),
        ]

    def p_general(self):
        admin = is_admin()
        return [
            ("Comportement", [
                T(None, "Lancer au démarrage de Windows" if IS_WIN else "Lancer à l'ouverture de session", cond=IS_WIN or IS_MAC,
                  get=is_autostart, set=lambda v: set_autostart(v)),
                T(None, "Afficher les widgets", "Aussi accessible depuis l'icône de la zone de notification",
                  get=lambda: not self.cfg["widgets_hidden"], set=lambda v: self.app.set_widgets_hidden(not v)),
                TXT("card_hotkey", "Raccourci pour afficher / masquer les widgets",
                    "Exemple : ctrl+alt+d (ctrl, alt, shift + une lettre" + ("; cmd = ⌘)" if IS_MAC else ")"),
                    placeholder="ctrl+alt+d"),
                T("card_menubar", "CPU, RAM et réseau dans la barre des menus" if IS_MAC else
                  "CPU, RAM et réseau dans l'infobulle de l'icône (à côté de l'horloge)", cond=IS_MAC or IS_WIN),
            ]),
            ("Nettoyage", [
                T("clean_browsers", "Inclure les caches des navigateurs", "Chrome, Edge, Firefox, Brave…"),
                T("clean_recycle", "Vider aussi la corbeille"),
                B("Mode administrateur", "Actif ✔" if admin else "Inactif : certains fichiers système sont ignorés",
                  "Relancer en admin", self.app.relaunch_admin, cond=IS_WIN and not admin),
            ]),
            ("Mises à jour", [
                TXT("update_repo", "Dépôt GitHub", "Où sont publiées les nouvelles versions (utilisateur/projet)",
                    width=28),
                T("update_auto", "Vérifier automatiquement", "Au démarrage puis une fois par jour"),
                B("Version installée", f"DeskMonitor {APP_VERSION}", "Vérifier maintenant",
                  lambda: self.app.check_updates(True), primary=True),
            ]),
            ("Réglages", [
                B("Dossier de configuration", str(CONFIG_DIR), "Ouvrir", self._open_config),
                B("Réinitialiser", "Rétablit les réglages par défaut (positions et classement conservés)",
                  "Réinitialiser…", self._reset, danger=True),
            ]),
        ]

    def p_about(self):
        return [("", [X(self._about)])]

    # ======================================================================== #
    #  Contenus personnalisés
    # ======================================================================== #
    # ----- galeries d'images ------------------------------------------------------
    def _image_grid(self, parent, tiles, selected):
        """Grille de miniatures. tiles = [(libellé, chemin | None, clic, suppression | None)]."""
        from PIL import ImageTk
        bg = UI["card"]
        tw, th = int(170 * self.scale), int(96 * self.scale)
        avail = self.canvas.winfo_width() - int(2 * 28 * self.scale) - int(2 * 18 * self.scale)
        cols = max(2, avail // (tw + 14)) if avail > 0 else 3
        grid = tk.Frame(parent, bg=bg)
        grid.pack(fill="x")
        for i, (label, path, on_click, on_remove) in enumerate(tiles):
            sel = path is not None and selected is not None and os.path.normcase(path) == os.path.normcase(selected)
            cell = tk.Frame(grid, bg=self.accent if sel else UI["line"], padx=2, pady=2, cursor="hand2")
            cell.grid(row=i // cols, column=i % cols, padx=5, pady=5, sticky="n")
            inner = tk.Frame(cell, bg=UI["card2"])
            inner.pack()
            img = wallpapers.thumbnail(path, tw, th) if path else None
            if img is not None:
                photo = ImageTk.PhotoImage(img, master=self.win)
                self._thumbs.append(photo)
                pic = tk.Label(inner, image=photo, bg=UI["card2"], bd=0)
            else:  # tuile d'action (« Ajouter… », « Même image… ») : même taille qu'une miniature
                pic = tk.Frame(inner, bg=UI["card2"], width=tw, height=th)
                pic.pack_propagate(False)
                tk.Label(pic, text=label.split("\n")[0], bg=UI["card2"], fg=UI["text"],
                         font=(FONT, 18)).place(relx=0.5, rely=0.5, anchor="center")
            pic.pack()
            # légende de largeur fixe (en pixels) : toutes les tuiles sont identiques
            capf = tk.Frame(inner, bg=UI["card2"], width=tw, height=int(24 * self.scale))
            capf.pack_propagate(False)
            capf.pack()
            cap = tk.Label(capf, text=(label if path else label.split("\n")[-1]) + ("  ✔" if sel else ""),
                           bg=UI["card2"], fg=self.accent if sel else UI["text"], font=(FONT, 9), anchor="w",
                           padx=6)
            cap.pack(fill="both", expand=True)
            for w in (cell, inner, pic, capf, cap, *pic.winfo_children()):
                w.bind("<Button-1>", lambda e, f=on_click: f())
            if on_remove:
                x = tk.Label(inner, text="✕", bg=UI["card2"], fg=UI["muted"],
                             font=(FONT, 9), cursor="hand2")
                x.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-4)
                x.bind("<Button-1>", lambda e, f=on_remove: f())

    def _wallpaper_gallery(self, parent):
        self._thumbs = []
        current = self.cfg.get("wallpaper_last") or wallpapers.current_wallpaper()
        tiles = []
        for name, path, kind in wallpapers.list_wallpapers():
            tiles.append((name, path, lambda p=path: self.app.apply_wallpaper(p),
                          (lambda p=path: self._remove_wallpaper(p)) if kind == "user" else None))
        tiles.append(("➕\nAjouter des images…", None, self._add_wallpapers, None))
        tk.Label(parent, text="Cliquez sur une image pour l'appliquer au bureau.", bg=UI["card"], fg=UI["muted"],
                 font=(FONT, 9)).pack(anchor="w", pady=(0, 6))
        self._image_grid(parent, tiles, current)

    def _add_wallpapers(self):
        paths = filedialog.askopenfilenames(parent=self.win, title="Ajouter des fonds d'écran",
                                            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp")])
        if paths:
            wallpapers.add_images(paths)
            self.refresh()

    def _remove_wallpaper(self, path):
        if messagebox.askyesno(APP_NAME, f"Retirer « {os.path.splitext(os.path.basename(path))[0]} » "
                                         "de la collection ?", parent=self.win):
            wallpapers.remove_image(path)
            self.refresh()

    def _lock_image_picker(self, parent):
        self._thumbs = getattr(self, "_thumbs", [])
        sel = self.cfg["lock_image"]
        tiles = [("🖥\nMême image que le fond d'écran", None, lambda: self._set_lock_image(""), None)]
        for name, path, _ in wallpapers.list_wallpapers():
            tiles.append((name, path, lambda p=path: self._set_lock_image(p), None))
        tiles.append(("📂\nAutre image…", None, self._pick_lock_file, None))
        if sel and not any(os.path.normcase(sel) == os.path.normcase(p) for _, p, _ in wallpapers.list_wallpapers()):
            tiles.insert(1, (os.path.splitext(os.path.basename(sel))[0], sel, lambda: None, None))
        if not sel:
            tk.Label(parent, text="✔ Utilise actuellement la même image que le fond d'écran", bg=UI["card"],
                     fg=self.accent, font=(FONT, 9)).pack(anchor="w", pady=(0, 6))
        self._image_grid(parent, tiles, sel or None)

    def _set_lock_image(self, path):
        self.cfg["lock_image"] = path
        self.app.save()
        self.refresh()

    def _pick_lock_file(self):
        path = filedialog.askopenfilename(parent=self.win, title="Image de l'écran de verrouillage",
                                          filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp")])
        if path:
            self._set_lock_image(wallpapers.add_images([path])[0])  # copiée dans la collection

    def _lock_preview(self, parent):
        bg = UI["card"]
        box = tk.Frame(parent, bg=bg)
        box.pack(fill="x")
        self._preview_lbl = tk.Label(box, bg=UI["field"], text="Préparation de l'aperçu…", fg=UI["muted"])
        self._preview_lbl.pack(side="left")
        side = tk.Frame(box, bg=bg)
        side.pack(side="left", fill="y", padx=(18, 0))
        tk.Label(side, text="L'horloge de Windows reste affichée\nau-dessus : sa police et sa position\n"
                            "ne peuvent pas être modifiées.", bg=bg, fg=UI["muted"], font=(FONT, 9),
                 justify="left").pack(anchor="w")
        FlatButton(side, "Appliquer à l'écran de verrouillage", lambda: self.app.update_lockscreen(True),
                   self.accent, primary=True).pack(anchor="w", pady=(12, 6))
        tk.Label(side, text="Astuce : Windows + L pour voir le résultat.", bg=bg, fg=UI["muted"],
                 font=(FONT, 8)).pack(anchor="w")
        self.win.after(50, self._update_preview)

    def _update_preview(self):
        self._preview_after = None
        lbl = getattr(self, "_preview_lbl", None)
        if lbl is None or not lbl.winfo_exists():
            return
        base = self.app.lock_base_image()
        if not base:
            lbl.configure(text="Aucune image disponible")
            return
        try:
            from PIL import ImageTk
            w = int(360 * self.scale)
            img = lockscreen.compose(self.cfg, base, size=(960, 540)).resize((w, int(w * 9 / 16)))
            self._preview_img = ImageTk.PhotoImage(img, master=self.win)
            lbl.configure(image=self._preview_img, text="")
        except Exception as ex:  # noqa: BLE001
            lbl.configure(text=f"Aperçu impossible : {ex}")

    def _panels_table(self, parent):
        org = self.app.organizer
        c = self.cfg
        bg = UI["card"]
        tk.Label(parent, text="Masqué : caché avec ses applications · Supprimé : ses applications vont dans "
                              "« Autres » · Couleur et opacité propres à chaque panneau",
                 bg=bg, fg=UI["muted"], font=(FONT, 9), wraplength=int(620 * self.scale),
                 justify="left").pack(anchor="w", pady=(0, 8))
        table = tk.Frame(parent, bg=bg)
        table.pack(fill="x")
        for col, title in enumerate(("Panneau", "État", "Couleur", "Opacité", "")):
            tk.Label(table, text=title, bg=bg, fg=UI["muted"], font=(FONT, 9)).grid(
                row=0, column=col, sticky="w", padx=(0, 14), pady=(0, 4))
        states = {"show": "Affiché", "hide": "Masqué", "remove": "Supprimé"}
        for r, (cat, emo) in enumerate(org.categories(), start=1):
            style = c["org_cat_style"].get(cat, {})
            tk.Label(table, text=f"{emo}  {cat}", bg=bg, fg=UI["text"], font=(FONT, 10)).grid(
                row=r, column=0, sticky="w", padx=(0, 14), pady=3)
            choices = ["show", "hide"] if cat == "Autres" else list(states)
            cb = ttk.Combobox(table, values=[states[k] for k in choices], state="readonly", width=10)
            cb.current(choices.index(org.cat_state(cat)) if org.cat_state(cat) in choices else 0)
            cb.bind("<<ComboboxSelected>>", lambda e, k=cat, w=cb, ch=choices: org.set_cat_state(k, ch[w.current()]))
            cb.grid(row=r, column=1, sticky="w", padx=(0, 14), pady=3)
            Swatch(table, style.get("accent", c["accent_color"]),
                   lambda col, k=cat: self._cat_style(k, "accent", col), bg).grid(
                row=r, column=2, sticky="w", padx=(0, 14))
            var = tk.StringVar(table, str(style.get("opacity", c["opacity"])))
            var.trace_add("write", lambda *_, k=cat, v=var: v.get().isdigit() and 20 <= int(v.get()) <= 100
                          and self._cat_style(k, "opacity", int(v.get())))
            ttk.Spinbox(table, from_=20, to=100, increment=5, textvariable=var, width=5).grid(
                row=r, column=3, sticky="w", padx=(0, 14))
            if style:
                FlatButton(table, "↺ Par défaut", lambda k=cat: self._cat_style(k, None, None, refresh=True),
                           self.accent, small=True).grid(row=r, column=4, sticky="w")
        FlatButton(parent, "Tout rétablir", lambda: (org.restore_all_panels(), self.refresh()),
                   self.accent).pack(anchor="w", pady=(10, 0))

    def _cat_style(self, cat, key, value, refresh=False):
        styles = self.cfg["org_cat_style"]
        if key is None:
            styles.pop(cat, None)
        else:
            styles.setdefault(cat, {})[key] = value
        self.app.schedule_rebuild()
        if refresh:
            self.win.after(150, self.refresh)

    def _profiles_list(self, parent):
        bg = UI["card"]
        pm = self.app.profiles
        names = pm.names()
        if not names:
            tk.Label(parent, text="Aucun profil pour l'instant.", bg=bg, fg=UI["muted"]).pack(anchor="w")
        for name in names:
            row = tk.Frame(parent, bg=UI["card2"], padx=12, pady=8)
            row.pack(fill="x", pady=3)
            active = self.cfg.get("profile") == name
            tk.Label(row, text=("●  " if active else "") + name, bg=UI["card2"],
                     fg=self.accent if active else UI["text"], font=(FONT, 10, "bold")).pack(side="left")
            if (pm.load(name) or {}).get("_preset"):
                tk.Label(row, text="modèle", bg=UI["card2"], fg=UI["muted"], font=(FONT, 8)).pack(side="left", padx=8)
            FlatButton(row, "Supprimer", lambda n=name: self._profile_delete(n), self.accent,
                       small=True).pack(side="right", padx=(6, 0))
            FlatButton(row, "Mettre à jour", lambda n=name: self._profile_update(n), self.accent,
                       small=True).pack(side="right", padx=(6, 0))
            FlatButton(row, "Appliquer", lambda n=name: (self.app.apply_profile(n), self.win.after(200, self.refresh)),
                       self.accent, primary=True, small=True).pack(side="right")

    def _profile_save_as(self):
        name = simpledialog.askstring("Nouveau profil", "Nom du profil :", parent=self.win)
        if name and name.strip():
            self.cfg["profile"] = self.app.profiles.save(name.strip(), self.cfg)
            self.app.save()
            self.refresh()

    def _profile_update(self, name):
        if messagebox.askyesno(APP_NAME, f"Remplacer le profil « {name} » par les réglages actuels ?",
                               parent=self.win):
            self.app.profiles.save(name, self.cfg)
            self.cfg["profile"] = name
            self.app.save()
            self.refresh()

    def _profile_delete(self, name):
        if messagebox.askyesno(APP_NAME, f"Supprimer le profil « {name} » ?", parent=self.win):
            self.app.profiles.delete(name)
            if self.cfg.get("profile") == name:
                self.cfg["profile"] = ""
            self.refresh()

    def _export(self):
        path = filedialog.asksaveasfilename(parent=self.win, title="Exporter les réglages",
                                            defaultextension=".json", initialfile="DeskMonitor-reglages.json",
                                            filetypes=[("Réglages DeskMonitor", "*.json")])
        if path:
            prof.ProfileManager.export(self.cfg, path)
            messagebox.showinfo(APP_NAME, f"Réglages exportés :\n{path}", parent=self.win)

    def _import(self):
        path = filedialog.askopenfilename(parent=self.win, title="Importer des réglages",
                                          filetypes=[("Réglages DeskMonitor", "*.json")])
        if not path:
            return
        try:
            self.app.import_settings(path)
        except (OSError, ValueError) as ex:
            messagebox.showerror(APP_NAME, f"Import impossible :\n{ex}", parent=self.win)
            return
        self.win.after(200, self.refresh)

    def _about(self, parent):
        bg = UI["card"]
        box = tk.Frame(parent, bg=bg)
        box.pack(fill="x", pady=10)
        try:
            from PIL import ImageTk
            self._big_icon = ImageTk.PhotoImage(make_icon_image(96, self.accent, self.cfg["bg_color"]), master=self.win)
            tk.Label(box, image=self._big_icon, bg=bg).pack(side="left", padx=(0, 18))
        except Exception:  # noqa: BLE001
            pass
        txt = tk.Frame(box, bg=bg)
        txt.pack(side="left", anchor="n")
        tk.Label(txt, text=APP_NAME, bg=bg, fg=UI["text"], font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(txt, text=f"Version {APP_VERSION}", bg=bg, fg=UI["muted"], font=(FONT, 10)).pack(anchor="w")
        tk.Label(txt, text="Heure, date, monitoring, alertes et bureau organisé,\nle tout personnalisable.",
                 bg=bg, fg=UI["text"], font=(FONT, 10), justify="left").pack(anchor="w", pady=(10, 0))
        repo = self.cfg.get("update_repo")
        if repo:
            link = tk.Label(txt, text=f"github.com/{repo}", bg=bg, fg=self.accent, cursor="hand2",
                            font=(FONT, 10, "underline"))
            link.pack(anchor="w", pady=(8, 0))
            link.bind("<Button-1>", lambda e: open_path(f"https://github.com/{repo}"))

    def _open_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        open_path(CONFIG_DIR)

    def _reset(self):
        if not messagebox.askyesno(APP_NAME, "Rétablir tous les réglages par défaut ?\n"
                                             "(positions et classement des applications conservés)",
                                   parent=self.win):
            return
        import json
        keep = {k: v for k, v in self.cfg.items()
                if k in ("x", "y", "positions", "update_repo", "profile")
                or (k.startswith("org_") and k != "org_enabled")}
        self.cfg.clear()
        self.cfg.update(json.loads(json.dumps(DEFAULTS)))
        self.cfg.update(keep)
        self.app.schedule_rebuild()
        self.win.after(200, self.refresh)

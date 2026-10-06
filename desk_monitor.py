#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeskMonitor — widget de bureau : heure, date, performances de la machine
et optimisation en un clic (cache, RAM, CPU, DNS, corbeille).

Clic gauche maintenu : déplacer le widget
Clic droit           : menu (paramètres, actions, quitter...)
"""
import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

try:
    import psutil
except ImportError:  # pragma: no cover
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror("DeskMonitor", "Le module 'psutil' est requis.\n\npip install psutil")
    sys.exit(1)

import sensors
import actions
from organizer import DesktopOrganizer, set_desktop_icons
from profiles import ProfileManager
from settings_ui import UI, SettingsWindow, font_list, setup_styles
from tray import TrayIcon
import voice as voicemod
import assistant
import wallpapers
from anim import Animator
from cards import CardManager
from app_voice import VoiceMixin
from app_assistant import AssistantMixin
from app_wallpaper import WallpaperMixin
from app_updates import UpdateMixin
from app_alerts import AlertsMixin
from app_actions import ActionsMixin
from process_window import ProcessWindow

from core import (
    IS_WIN,
    APP_NAME,
    APP_VERSION,
    HIST_LEN,
    CONFIG_DIR,
    format_date,
    blend,
    font_spec,
    DETACHABLE,
    DEFAULTS,
    load_config,
    save_config,
    fmt_bytes,
    fmt_duration,
    no_window_flags,
    is_admin,
    launch_command,
    is_autostart,
    set_autostart,
    apply_corners,
    bring_to_front,
    cfg_signature,
    no_activate,
    ensure_visible,
    log_exception,
    bind_right_click,
    IS_MAC,
    STYLE_KEYS,
    hide_from_taskbar,
)
if IS_WIN:
    from ctypes import wintypes


# --------------------------------------------------------------------------- #
#  Widget principal
# --------------------------------------------------------------------------- #
class DeskWidget(VoiceMixin, AssistantMixin, WallpaperMixin, UpdateMixin, AlertsMixin, ActionsMixin):
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.anim = Animator(root, lambda: self.cfg.get("animations", True))
        self.rows = {}
        self._jobs = queue.Queue()
        self._busy = False
        self._status_after = None
        self._rebuild_after = None
        self._drag = (None, 0, 0)
        self.panels = {}
        self.panel_lbl = {}     # libellés heure / date des widgets séparés
        self.main_lbl = {}      # libellés heure / date dans le widget principal
        self._sigs = {}         # empreintes des réglages : on ne redessine que ce qui a changé
        self.main_hidden = False
        self._net_prev = (psutil.net_io_counters(), time.time())
        self.settings_win = None
        self.proc_win = None
        self.hist = defaultdict(lambda: deque(maxlen=HIST_LEN))
        self.last = {}          # dernières mesures (toujours relevées, même si masquées)
        self.sensors = {}       # rempli par le thread des capteurs (GPU, ping, IP)
        self.toasts = []
        self._alert_last = {}
        self._cpu_high_since = None
        self._ui_calls = queue.Queue()  # appels venant d'autres threads (icône de notification…)
        self._wall_sig = None
        self.profiles = ProfileManager()

        root.title(APP_NAME)
        root.overrideredirect(True)
        psutil.cpu_percent(None)
        setup_styles(root, self.cfg["accent_color"])

        self._ctx_active = None
        self.voice = voicemod.Voice()
        self.listener = assistant.Listener()
        self.wake = assistant.WakeListener(
            get_name=lambda: self.cfg["assistant_name"].strip() or "Jarvis",
            get_lang=lambda: self.cfg["voice_lang"],
            on_wake=lambda cmd: self.call_soon(self._on_wake, cmd),
            is_speaking=self.voice.speaking,
            get_aliases=lambda: assistant.clean_aliases(self.cfg["wake_aliases"], self.cfg["assistant_name"]),
            get_vocab=self.assistant_vocab,
            log=self._alog)
        self.listener.vocab = self.assistant_vocab
        self.files = actions.FileIndex()      # fichiers et dossiers que l'assistant sait ouvrir
        root.after(15000, self._files_loop)
        self._listen_spec = None
        self.voice_ready = False          # activé par main() : jamais de voix pendant l'autotest
        self._red, self._red_last = {}, {}
        self._dyn_sig, self._dyn_core, self._dyn_busy, self._dyn_time = None, None, False, 0.0
        self.organizer = DesktopOrganizer(self)
        self.cards = CardManager(self)
        self.build()
        self._place_initial()
        # l'application vit dans la zone de notification : aucun bouton dans la barre des tâches
        if hide_from_taskbar(root) and not self.main_hidden:
            root.withdraw()
            root.deiconify()
        if self.cfg["widgets_hidden"]:
            self.set_widgets_hidden(True)
        self._clock_loop()
        self._stats_loop()
        self._poll_jobs()
        self.root.after(3000, self._alert_loop)
        self.root.after(2000, self._wallpaper_loop)
        self.root.after(1000, self._signal_loop)
        self.root.after(500, self._cards_loop)
        self.root.after(20000, self._context_loop)
        self.root.after(4000, self._voice_watch)
        self.root.after(1500, self._setup_listen_hotkey)
        self.root.after(5000, self._wake_loop)
        self.root.after(60000, self._dynamic_wallpaper_loop)
        threading.Thread(target=self._sensor_loop, daemon=True).start()
        self.tray = TrayIcon(self)
        self.tray.start()
        if IS_MAC:
            self._setup_mac()
        self.root.after(20000, self._update_loop)
        self._slide_time = time.time()
        self.root.after(15000, self._wallpaper_timers)
        self._last_health, self._last_bounds = time.time(), self._screen_bounds()
        self.root.after(3000, self._health_loop)
        for delay in (15, 45, 90):  # au démarrage de Windows, le bureau n'est pas toujours prêt tout de suite
            self.root.after(delay * 1000, self._recover)
        # liste des polices chargée en avance : les paramètres s'ouvrent ensuite instantanément
        self.root.after(6000, lambda: font_list(self.root))

    def _setup_mac(self):
        """macOS : pas d'icône de notification → Dock, ⌘, et barre des menus."""
        root = self.root

        def reopen(*_):  # clic sur l'icône du Dock
            if self.cfg["widgets_hidden"]:
                self.set_widgets_hidden(False)
            self.open_settings()

        root.createcommand("::tk::mac::ReopenApplication", reopen)
        root.createcommand("::tk::mac::ShowPreferences", self.open_settings)  # ⌘ ,
        root.createcommand("::tk::mac::Quit", self.quit)
        bar = tk.Menu(root)
        wm = tk.Menu(bar, tearoff=0)
        wm.add_command(label="Paramètres…", accelerator="⌘,", command=self.open_settings)
        wm.add_command(label="Afficher / masquer les widgets", command=self.toggle_widgets)
        wm.add_separator()
        wm.add_command(label="Parler à l'assistant", command=self.listen)
        wm.add_command(label="Lire le récapitulatif", command=lambda: self.speak_recap(force=True))
        wm.add_command(label="Faire taire la voix", command=self.voice.stop)
        wm.add_separator()
        wm.add_command(label="Tout optimiser", command=self.action_boost)
        wm.add_command(label="Nettoyer le cache", command=self.action_clean)
        wm.add_command(label="Processus…", command=self.open_processes)
        wm.add_separator()
        wm.add_command(label="Replacer les widgets", command=self.reset_position)
        corners = tk.Menu(wm, tearoff=0)
        for label, key in (("Haut à gauche", "tl"), ("Haut à droite", "tr"),
                           ("Bas à gauche", "bl"), ("Bas à droite", "br")):
            corners.add_command(label=label, command=lambda k=key: self.place_corner(k))
        wm.add_cascade(label="Placer dans un coin", menu=corners)
        bar.add_cascade(label="Widgets", menu=wm)
        root.configure(menu=bar)

    def save(self):
        save_config(self.cfg)

    def call_soon(self, fn, *args):
        """Exécute fn(*args) dans le thread de l'interface (appelable depuis n'importe quel thread)."""
        self._ui_calls.put((fn, args))

    # ----- Construction de l'interface -------------------------------------
    def _style_window(self, win, transparent):
        c = self.cfg
        border = c["border"] and not transparent
        win.configure(bg=c["bg_color"], highlightthickness=1 if border else 0,
                      highlightbackground=c["accent_color"], highlightcolor=c["accent_color"])
        win.attributes("-alpha", max(0.2, min(1.0, c["opacity"] / 100)))
        win.attributes("-topmost", bool(c["topmost"]))
        if IS_WIN:
            win.attributes("-transparentcolor", c["bg_color"] if transparent else "")
        apply_corners(win, c["rounded"] and not transparent)
        no_activate(win)

    def _make_clock(self, parent):
        c = self.cfg
        anchor = {"left": "w", "center": "center", "right": "e"}[c["clock_align"]]
        return tk.Label(parent, bg=c["bg_color"], fg=c["clock_color"], anchor=anchor, justify=c["clock_align"],
                        font=font_spec(c["clock_font"], c["clock_size"], c["clock_bold"], c["clock_italic"]))

    def _make_date(self, parent):
        c = self.cfg
        anchor = {"left": "w", "center": "center", "right": "e"}[c["date_align"]]
        return tk.Label(parent, bg=c["bg_color"], fg=c["date_color"], anchor=anchor, justify=c["date_align"],
                        font=font_spec(c["date_font"], c["date_size"], c["date_bold"], c["date_italic"]))

    def _detached(self):
        c = self.cfg
        if self.cards.active:
            return []
        return [k for k in DETACHABLE if c["show"][k] and c[f"detach_{k}"]]

    def _label(self, key):
        """Libellé actuel de l'heure / de la date (widget séparé ou widget principal)."""
        lbl = self.panel_lbl.get(key) if key in self.panels else self.main_lbl.get(key)
        return lbl if lbl is not None and lbl.winfo_exists() else None

    def _build_panels(self, force=False):
        """Crée / met à jour les widgets séparés (heure, date) — seulement s'ils ont changé."""
        c = self.cfg
        detached = self._detached()
        for k in list(self.panels):
            if k not in detached:
                self.panels.pop(k).destroy()
                self._sigs.pop(k, None)
        for k in detached:
            win = self.panels.get(k)
            new = win is None or not win.winfo_exists()
            sig = cfg_signature(c, STYLE_KEYS + (f"transparent_{k}",), (f"{k}_",))
            if not (new or force or self._sigs.get(k) != sig):
                continue
            self._sigs[k] = sig
            if new:
                win = tk.Toplevel(self.root)
                win.overrideredirect(True)
                win.title(f"{APP_NAME} — {DETACHABLE[k]}")
                self.panels[k] = win
            for ch in win.winfo_children():
                ch.destroy()
            self._style_window(win, c[f"transparent_{k}"])
            fr = tk.Frame(win, bg=c["bg_color"], padx=12, pady=6)
            fr.pack(fill="both", expand=True)
            self.panel_lbl[k] = (self._make_clock if k == "clock" else self._make_date)(fr)
            self.panel_lbl[k].pack(fill="x")
            self._bind_recursive(win)
            if new:
                self._place_panel(k)

    def _sync_palette(self):
        """Une seule apparence pour tous les widgets : le thème (auto / sombre / clair) et la couleur d'accent
        donnent la palette des cartes, reprise par le widget classique, les panneaux d'applications, les widgets
        séparés et les notifications. Plus de couleurs réglées séparément pour chacun."""
        c, cm = self.cfg, self.cards
        mode = c.get("accent_mode", "system")
        c["card_system_accent"] = mode == "system"
        c["theme_auto_wallpaper"] = mode == "wallpaper"
        cm.theme_colors()
        accent = cm.accent if mode == "system" else c["accent_color"]
        c.update(bg_color=cm.bg, text_color=cm.fg, bar_bg=cm.track, warn_color=cm.warn,
                 clock_color=cm.fg, date_color=accent, accent_color=accent,
                 rounded=int(c["card_radius"]) >= 4, border=False,
                 text_size=max(8, round(10 * int(c["card_text_scale"]) / 100)))

    def build(self, force=False):
        """Met à jour l'affichage. Seules les parties dont les réglages ont changé sont redessinées."""
        c = self.cfg
        self._sync_palette()
        self._build_panels(force)
        detached = self._detached()
        in_main = [k for k in ("clock", "date") if c["show"][k] and k not in detached]
        sig = cfg_signature(c, STYLE_KEYS + (
            "show", "detach_clock", "detach_date", "transparent_bg", "width", "padding", "bar_height",
            "graph_height", "graphs", "buttons_style"), tuple(f"{k}_" for k in in_main))
        if force or sig != self._sigs.get("main") or not self.root.winfo_children():
            self._sigs["main"] = sig
            self._build_main(detached)
        self.update_clock()
        self.update_stats()
        self.organizer.build()
        self.cards.build(force)

    def _build_main(self, detached):
        c = self.cfg
        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.rows = {}
        self.main_lbl = {}
        bg, fg = c["bg_color"], c["text_color"]
        self._style_window(self.root, c["transparent_bg"])

        pad = int(c["padding"])
        inner = int(c["width"]) - 2 * pad
        bar_h = int(c["bar_height"])
        fam, ts = c["font_family"], int(c["text_size"])
        f_text = (fam, ts)
        f_bold = (fam, ts, "bold")
        f_small = (fam, max(7, ts - 1))

        frame = tk.Frame(self.root, bg=bg, padx=pad, pady=max(6, pad * 3 // 4))
        frame.pack(fill="both", expand=True)
        self.frame = frame
        show = c["show"]

        clock_in_main = show["clock"] and "clock" not in detached
        date_in_main = show["date"] and "date" not in detached
        if clock_in_main:
            self.main_lbl["clock"] = self._make_clock(frame)
            self.main_lbl["clock"].pack(fill="x")
        if date_in_main:
            self.main_lbl["date"] = self._make_date(frame)
            self.main_lbl["date"].pack(fill="x")

        # (clé, libellé, type d'indicateur : "bar", "graph" ou None)
        graph = "graph" if c["graphs"] else "bar"
        metrics = []
        if show["cpu"]:
            metrics.append(("cpu", "CPU", graph))
        if show["ram"]:
            metrics.append(("ram", "RAM", graph))
        if show["gpu"]:
            metrics.append(("gpu", "GPU", graph))
        if show["disks"]:
            for part in self._disk_partitions():
                name = part.mountpoint.rstrip("\\") if IS_WIN else part.mountpoint
                metrics.append((f"disk:{part.mountpoint}", f"Disque {name}", "bar"))
        if show["net"]:
            metrics.append(("net", "Réseau", "graph" if c["graphs"] else None))
        if show["ping"]:
            metrics.append(("ping", "Ping", "graph" if c["graphs"] else None))
        if show["ip_local"]:
            metrics.append(("ip_local", "IP locale", None))
        if show["ip_public"]:
            metrics.append(("ip_public", "IP publique", None))
        if show["battery"] and self._battery() is not None:
            metrics.append(("battery", "Batterie", "bar"))
        if show["uptime"]:
            metrics.append(("uptime", "Allumé depuis", None))

        if metrics and (clock_in_main or date_in_main):
            tk.Frame(frame, bg=c["bar_bg"], height=1).pack(fill="x", pady=(10, 6))

        for key, label, kind in metrics:
            row = tk.Frame(frame, bg=bg)
            row.pack(fill="x", pady=(4, 0))
            tk.Label(row, text=label, bg=bg, fg=fg, font=f_bold, anchor="w").pack(side="left")
            val = tk.Label(row, text="…", bg=bg, fg=fg, font=f_text, anchor="e")
            val.pack(side="right")
            canvas = rect = None
            if kind == "bar":
                canvas = tk.Canvas(frame, width=inner, height=bar_h, bg=c["bar_bg"],
                                   highlightthickness=0, bd=0)
                canvas.pack(fill="x", pady=(3, 2))
                rect = canvas.create_rectangle(0, 0, 0, bar_h, width=0, fill=c["accent_color"])
            elif kind == "graph":
                canvas = tk.Canvas(frame, width=inner, height=int(int(c["graph_height"]) * self._scale()),
                                   bg=blend(bg, c["bar_bg"], 0.5), highlightthickness=0, bd=0)
                canvas.pack(fill="x", pady=(3, 2))
            self.rows[key] = (val, canvas, rect)

        self.btn_frame = None
        if show["buttons"]:
            bf = tk.Frame(frame, bg=bg)
            bf.pack(fill="x", pady=(12, 0))
            buttons = [
                ("🧹", "Cache", self.action_clean),
                ("🧠", "RAM", self.action_ram),
                ("⚙", "CPU", self.open_processes),
                ("⚡", "Tout", self.action_boost),
            ]
            style = c["buttons_style"]
            for i, (ico, label, cmd) in enumerate(buttons):
                txt = ico if style == "icon" else label if style == "text" else f"{ico} {label}"
                b = tk.Label(bf, text=txt, bg=c["bar_bg"], fg=fg, font=f_small,
                             padx=4, pady=5, cursor="hand2")
                b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
                bf.columnconfigure(i, weight=1, uniform="btn")
                b._is_button = True
                b.bind("<Button-1>", lambda e, f=cmd: f())
                b.bind("<Enter>", lambda e, w=b: w.configure(bg=c["accent_color"], fg=c["bg_color"]))
                b.bind("<Leave>", lambda e, w=b: w.configure(bg=c["bar_bg"], fg=fg))
            self.btn_frame = bf

        self.status_lbl = tk.Label(frame, text="", bg=bg, fg=c["accent_color"], font=f_small,
                                   anchor="w", justify="left", wraplength=inner)
        self.status_lbl.pack(fill="x", pady=(6, 0))
        main_empty = not (metrics or show["buttons"] or clock_in_main or date_in_main)
        if main_empty and not detached:
            self.status_lbl.configure(text="Clic droit → Paramètres")

        # largeur minimale imposée par une bande invisible
        tk.Frame(frame, bg=bg, width=inner, height=0).pack()

        # widget principal vide (tout est séparé) : on le masque
        self.main_hidden = (main_empty and bool(detached)) or self.cards.active
        if self.main_hidden:
            self.root.withdraw()
        elif self.root.state() == "withdrawn":
            self.root.deiconify()

        self._bind_recursive(self.root)

    def _scale(self):
        return self.root.winfo_fpixels("1i") / 96.0

    def _bind_recursive(self, widget):
        for w in widget.winfo_children():
            if isinstance(w, tk.Toplevel):
                continue
            if not getattr(w, "_is_button", False):
                w.bind("<ButtonPress-1>", self._start_drag)
                w.bind("<B1-Motion>", self._do_drag)
                w.bind("<ButtonRelease-1>", self._end_drag)
            bind_right_click(w, self.show_menu)
            self._bind_recursive(w)
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            bind_right_click(widget, self.show_menu)

    def schedule_rebuild(self):
        if self._rebuild_after:
            self.root.after_cancel(self._rebuild_after)
        self._rebuild_after = self.root.after(120, self._do_rebuild)

    def _do_rebuild(self):
        self._rebuild_after = None
        self.build()
        if self.cfg["widgets_hidden"]:
            self.set_widgets_hidden(True)
        save_config(self.cfg)
        setup_styles(self.root, self.cfg["accent_color"])
        if hasattr(self, "tray"):
            self.tray.refresh()

    # ----- Visibilité, profils, import -----------------------------------------
    def all_windows(self):
        return [self.root, *self.panels.values(), *self.organizer.windows(), *self.cards.windows()]

    def set_widgets_hidden(self, hidden):
        """Masque / réaffiche tous les widgets et panneaux (l'icône de notification reste)."""
        self.cfg["widgets_hidden"] = bool(hidden)
        a = self.anim
        for i, w in enumerate(self.all_windows()):
            try:
                if hidden:
                    if a.on and w.winfo_ismapped():   # fondu, puis la fenêtre disparaît
                        base = getattr(w, "_base_alpha", None) or float(w.attributes("-alpha"))
                        w._base_alpha = base
                        a.fade(w, 0.0, 180, done=lambda w=w, b=base: (w.withdraw(), w.attributes("-alpha", b)))
                    else:
                        w.withdraw()
                elif not (w is self.root and self.main_hidden):
                    w.deiconify()
                    a.appear(w, i * 22, rise=10, duration_ms=420)
            except tk.TclError:
                pass
        self.save()
        if hasattr(self, "tray"):
            self.tray.refresh()

    def toggle_widgets(self):
        self.set_widgets_hidden(not self.cfg["widgets_hidden"])

    def _reposition_all(self):
        self._place_initial()
        for k in self.panels:
            self._place_panel(k)
        for cat, win in self.organizer.fences.items():
            pos = self.cfg["positions"].get(f"fence:{cat}")
            if self._valid_pos(pos):
                win.geometry(f"+{int(pos[0])}+{int(pos[1])}")

    def _after_bulk_change(self, message):
        self.build()
        self.save()
        self._reposition_all()
        setup_styles(self.root, self.cfg["accent_color"])
        self.tray.refresh()
        self.set_status(message)

    def apply_profile(self, name):
        data = self.profiles.load(name)
        if data is None:
            return
        ProfileManager.merge_into(self.cfg, data)
        self.cfg["profile"] = name
        self._after_bulk_change(f"Profil « {name} » appliqué")
        if self.settings_win and self.settings_win.win.winfo_exists():
            self.settings_win.refresh()

    def import_settings(self, path):
        ProfileManager.import_file(self.cfg, path)
        self._after_bulk_change("Réglages importés")

    # ----- Boucles de fond : fond d'écran, seconde instance, mises à jour ----------
    def _signal_loop(self):
        """Relancer DeskMonitor alors qu'il tourne déjà ouvre simplement ses paramètres."""
        try:
            if SIGNAL_FILE.exists():
                SIGNAL_FILE.unlink()
                if self.cfg["widgets_hidden"]:
                    self.set_widgets_hidden(False)
                self.open_settings()
        except OSError:
            pass
        self.root.after(1000, self._signal_loop)

    def _context_loop(self):
        """Profils automatiques : un profil sur batterie, un autre la nuit ; retour au profil de base ensuite."""
        c = self.cfg
        try:
            if c["ctx_on"]:
                b = self._battery()
                on_batt = b is not None and not b.power_plugged
                h, f, t = datetime.now().hour, int(c["ctx_night_from"]), int(c["ctx_night_to"])
                night = (h >= f or h < t) if f > t else f <= h < t
                names = self.profiles.names()
                want = (c["ctx_battery_profile"] if on_batt else "") or (c["ctx_night_profile"] if night else "")
                if want and want in names:
                    if self._ctx_active != want:
                        if not self._ctx_active:
                            c["ctx_base"] = c["profile"]
                        self._ctx_active = want
                        self.apply_profile(want)
                elif self._ctx_active:
                    self._ctx_active, base = None, c["ctx_base"]
                    if base and base in names:
                        self.apply_profile(base)
            else:
                self._ctx_active = None
        except Exception:  # noqa: BLE001
            log_exception("profils automatiques")
        self.root.after(60000, self._context_loop)

    def _cards_loop(self):
        """Animation des jauges (20 images/s) et suivi du thème clair/sombre de macOS."""
        try:
            self.cards.animate()
            self._cards_n = getattr(self, "_cards_n", 0) + 1
            if self._cards_n % 100 == 0:
                self.cards.follow_system()
        except Exception:  # noqa: BLE001
            pass
        self.root.after(33, self._cards_loop)

    # ----- Position / déplacement -------------------------------------------
    def _screen_bounds(self):
        """(x0, y0, x1, y1) de l'ensemble des écrans (multi-écrans sous Windows)."""
        if IS_WIN:
            try:
                gsm = ctypes.windll.user32.GetSystemMetrics
                x0, y0 = gsm(76), gsm(77)  # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN
                return x0, y0, x0 + gsm(78), y0 + gsm(79)
            except OSError:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _valid_pos(self, pos):
        if not pos or pos[0] is None or pos[1] is None:
            return False
        x0, y0, x1, y1 = self._screen_bounds()
        return x0 - 20 <= pos[0] < x1 - 40 and y0 - 20 <= pos[1] < y1 - 40

    def _place_initial(self):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_reqwidth()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if not self._valid_pos((x, y)):
            x, y = sw - w - 40, 40
        self.root.geometry(f"+{int(x)}+{int(y)}")

    def _place_panel(self, key):
        win = self.panels[key]
        win.update_idletasks()
        pos = self.cfg["positions"].get(key)
        if not self._valid_pos(pos):
            # par défaut en haut à gauche : l'heure, puis la date en dessous
            y = 40
            if key == "date" and "clock" in self.panels:
                y += self.panels["clock"].winfo_reqheight() + 10
            pos = (40, y)
        win.geometry(f"+{int(pos[0])}+{int(pos[1])}")

    def place_corner(self, corner):
        """Colle le widget principal dans un coin (« tl », « tr », « bl », « br »), en laissant la barre des menus et le Dock."""
        if self.cards.active:
            self.cfg["cards_corner"], self.cfg["card_pos"] = corner, {}
            self.cards.build(force=True)
            save_config(self.cfg)
            return
        self.root.update_idletasks()
        x0, y0, x1, y1 = self._screen_bounds()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        top, bottom, side = (40, 90, 20) if IS_MAC else (20, 60, 20)
        x = x0 + side if corner[1] == "l" else x1 - w - side
        y = y0 + top if corner[0] == "t" else max(y0 + top, y1 - h - bottom)
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self.cfg["x"], self.cfg["y"] = int(x), int(y)
        save_config(self.cfg)

    def reset_position(self):
        self.cfg["x"] = self.cfg["y"] = None
        self.cfg["positions"] = {}
        self._place_initial()
        for k in ("clock", "date"):
            if k in self.panels:
                self._place_panel(k)
        self.cards.reset_positions()
        self.root.update_idletasks()
        self.organizer.auto_layout()
        save_config(self.cfg)

    def tidy_desktop(self, announce=True):
        """Range tout le bureau : cartes alignées dans leur coin, panneaux d'applications en colonnes à côté,
        sans aucun chevauchement. Les autres réglages ne changent pas."""
        if self.cards.active:
            self.cards.reset_positions()
        else:
            self._place_initial()
            for k in ("clock", "date"):
                if k in self.panels:
                    self.cfg["positions"].pop(k, None)
                    self._place_panel(k)
        self.root.update_idletasks()
        self.organizer.auto_layout()
        save_config(self.cfg)
        if announce:
            self.set_status(self._tr("Bureau rangé", "Desktop tidied"))

    def _alog(self, msg):
        """Journal de l'assistant (assistant.log) : ce qu'il entend et ce qu'il comprend, pour le diagnostic."""
        try:
            path = CONFIG_DIR / "assistant.log"
            if path.exists() and path.stat().st_size > 100_000:
                path.write_text(path.read_text(encoding="utf-8", errors="replace")[-50_000:], encoding="utf-8")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        except OSError:
            pass

    def _migrate(self):
        """Mise à jour des réglages d'une version précédente (une seule fois)."""
        c = self.cfg
        if c.get("migrated", 0) < 1:   # 1.5.1
            c["wake_night_off"] = False   # l'écoute du nom était coupée de 22 h à 7 h : déroutant
            c["wake_aliases"] = assistant.clean_aliases(c["wake_aliases"], c["assistant_name"])
            c["migrated"] = 1
            save_config(c)
            self.root.after(5000, lambda: self.tidy_desktop(announce=False))   # nouveau style : bureau rangé
        if c.get("migrated", 0) < 2:   # 1.6 : une seule apparence pour tous les widgets
            c["accent_mode"] = ("wallpaper" if c.get("theme_auto_wallpaper") else
                                "system" if c.get("card_system_accent") else "custom")
            c["migrated"] = 2
            save_config(c)
        if c.get("migrated", 0) < 3:   # 1.8 : voix neuronale, fond d'écran d'origine rétabli
            if voicemod.neural_ok() and not str(c.get("voice_name", "")).startswith(voicemod.NEURAL_PREFIX):
                c["voice_name"] = ""   # automatique : la voix neuronale la plus naturelle
            if not (c["wp_dyn_time"] or c["wp_dyn_state"] or c["wp_dyn_stats"]):
                c["wp_dyn_applied"] = True   # une image retouchée peut être restée : la boucle remet l'originale
            c["migrated"] = 3
            save_config(c)
        for key in ("wallpaper_last", "lock_image"):   # à chaque démarrage : une image disparue de l'application
            p = c.get(key)                               # (fonds livrés changés) est retrouvée dans la collection
            if p and not os.path.isfile(p):
                mine = wallpapers.USER_DIR / Path(p).name
                if mine.is_file():
                    c[key] = str(mine)
                    save_config(c)
        if c.get("migrated", 0) < 4:   # 1.8.1 : mises à jour depuis le dépôt public
            if c.get("update_repo", "") in ("", "AlphoBakos/DeskMonitor"):
                c["update_repo"] = DEFAULTS["update_repo"]
            c["migrated"] = 4
            save_config(c)

    def _start_drag(self, e):
        win = e.widget.winfo_toplevel()
        self._drag = (win, e.x_root - win.winfo_x(), e.y_root - win.winfo_y())
        self._drag_from = (e.x_root, e.y_root)

    def _do_drag(self, e):
        win, dx, dy = self._drag
        if self.cfg["locked"] or win is None:
            return
        fx, fy = getattr(self, "_drag_from", (e.x_root, e.y_root))
        if not getattr(win, "_lifted", False) and win is not self.root and abs(e.x_root - fx) + abs(e.y_root - fy) > 4:
            win._lifted = True
            win.lift()
            self.anim.fade(win, (getattr(win, "_base_alpha", None) or 1.0) * 0.84, 130)
        self.anim.cancel(("glide", str(win)))
        win._glide_to = None
        win.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _end_drag(self, _e):
        win = self._drag[0]
        self._drag = (None, 0, 0)
        if win is not None and getattr(win, "_lifted", False):
            win._lifted = False
            self.anim.fade(win, getattr(win, "_base_alpha", None) or 1.0, 220)
        if self.cfg["locked"] or win is None:
            return
        if win is self.root:
            self.cfg["x"], self.cfg["y"] = win.winfo_x(), win.winfo_y()
        else:
            key = getattr(win, "_pos_key", None)  # panneaux du bureau organisé
            for k, p in self.panels.items():
                if p is win:
                    key = k
            if key:
                self.cfg["positions"][key] = [win.winfo_x(), win.winfo_y()]
        save_config(self.cfg)

    def _keep_on_desktop(self):
        """Garde les widgets sous les autres fenêtres (effet « widget de bureau »)."""
        if not IS_WIN or self.cfg["topmost"]:
            return
        user32 = ctypes.windll.user32
        user32.GetParent.restype = user32.GetWindow.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        me = os.getpid()

        def above_foreign_window(hwnd):
            """Vrai si une fenêtre visible d'une AUTRE application se trouve sous ce widget."""
            h = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
            for _ in range(400):
                if not h:
                    return False
                if user32.IsWindowVisible(h):
                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    if pid.value != me:
                        cls = ctypes.create_unicode_buffer(32)
                        user32.GetClassNameW(ctypes.c_void_p(h), cls, 32)
                        if cls.value not in ("Progman", "WorkerW"):
                            return True
                h = user32.GetWindow(h, 2)
            return False

        cards_below = self.cards.windows() if self.cfg.get("card_desktop") else []
        for win in [self.root, *self.panels.values(), *self.organizer.windows(), *cards_below]:
            try:
                hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
                # on ne touche à l'ordre des fenêtres que si c'est nécessaire (évite tout redessin)
                if above_foreign_window(hwnd):
                    # HWND_BOTTOM, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                    user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            except Exception:
                pass

    # ----- Mesures ------------------------------------------------------------
    @staticmethod
    def _disk_partitions():
        parts = []
        for p in psutil.disk_partitions(all=False):
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            if not IS_WIN and p.mountpoint.startswith(("/snap", "/boot", "/var/snap")):
                continue
            # macOS : les volumes système APFS (/System/Volumes/…, Recovery) partagent le même espace
            if IS_MAC and p.mountpoint.startswith(("/System/Volumes", "/Volumes/Recovery", "/private")):
                continue
            parts.append(p)
        return parts

    @staticmethod
    def _battery():
        try:
            return psutil.sensors_battery()
        except Exception:
            return None

    def _set_row(self, key, text, percent=None, warn=None, series=None, maxv=100.0):
        """Met à jour une ligne. `series` = [(valeurs, couleur, remplir?)] pour les graphiques."""
        row = self.rows.get(key)
        if not row:
            return
        c = self.cfg
        val, canvas, rect = row
        if warn is None and percent is not None:
            warn = percent >= c["warn_threshold"]
            if key == "battery":
                warn = percent <= 100 - c["warn_threshold"]
        color = c["warn_color"] if warn else c["accent_color"]
        val.configure(text=text, fg=c["warn_color"] if warn else c["text_color"])
        if canvas is None:
            return
        w = canvas.winfo_width()
        if w <= 1:
            w = int(canvas["width"])
        if rect is not None:  # barre
            if percent is not None:
                canvas.coords(rect, 0, 0, w * max(0, min(100, percent)) / 100, int(canvas["height"]))
                canvas.itemconfigure(rect, fill=color)
            return
        if series is None:
            series = [(self.hist[key], color, True)]
        self._draw_graph(canvas, w, series, maxv)

    def _draw_graph(self, canvas, w, series, maxv):
        canvas.delete("all")
        h = int(canvas["height"])
        bg = canvas["bg"]
        step = w / (HIST_LEN - 1)
        maxv = max(maxv, 1e-6)
        for vals, color, fill in series:
            vals = list(vals)
            if len(vals) < 2:
                continue
            x0 = (HIST_LEN - len(vals)) * step
            pts = []
            for i, v in enumerate(vals):
                pts += [x0 + i * step, h - 1 - (min(max(v, 0), maxv) / maxv) * (h - 4)]
            if fill and self.cfg["graph_fill"]:
                canvas.create_polygon(x0, h, *pts, pts[-2], h, fill=blend(bg, color, 0.3), outline="")
            canvas.create_line(*pts, fill=color, width=max(1, round(1.5 * self._scale())))

    def sample(self):
        """Relève les mesures de base (pour l'historique et les alertes), qu'elles soient affichées ou non."""
        now = time.time()
        cpu = psutil.cpu_percent(None)
        vm = psutil.virtual_memory()
        now_c = psutil.net_io_counters()
        prev_c, prev_t = self._net_prev
        dt = max(0.001, now - prev_t)
        down = max(0, now_c.bytes_recv - prev_c.bytes_recv) / dt
        up = max(0, now_c.bytes_sent - prev_c.bytes_sent) / dt
        self._net_prev = (now_c, now)
        self.last.update(cpu=cpu, ram=vm.percent, vm=vm, down=down, up=up)
        self.hist["cpu"].append(cpu)
        self.hist["ram"].append(vm.percent)
        self.hist["net_down"].append(down)
        self.hist["net_up"].append(up)
        gpu = self.sensors.get("gpu")
        if gpu and gpu.get("util") is not None:
            self.hist["gpu"].append(gpu["util"])
        ping = self.sensors.get("ping", "…")
        if ping != "…":
            self.hist["ping"].append(ping if ping is not None else 0)

    def update_clock(self):
        now = datetime.now()
        clock, date = self._label("clock"), self._label("date")
        if clock is not None:
            fmt = "%H:%M" if self.cfg["clock_24h"] else "%I:%M"
            if self.cfg["show_seconds"]:
                fmt += ":%S"
            txt = now.strftime(fmt)
            if not self.cfg["clock_24h"]:
                txt += " AM" if now.hour < 12 else " PM"
            if self.cfg["clock_blink"] and now.second % 2:
                txt = txt.replace(":", " ")
            if clock.cget("text") != txt:  # pas de redessin inutile
                clock.configure(text=txt)
        if date is not None:
            txt = format_date(now, self.cfg)
            if date.cget("text") != txt:
                date.configure(text=txt)

    def update_stats(self):
        """Affiche les dernières mesures (ne relève rien : voir sample())."""
        c = self.cfg
        if not self.last:
            self.sample()
        self.cards.update()
        if "cpu" in self.rows:
            cpu = self.last["cpu"]
            self._set_row("cpu", f"{cpu:.0f} %", cpu)
        if "ram" in self.rows:
            vm = self.last["vm"]
            used = (vm.total - vm.available) / 1024 ** 3
            total = vm.total / 1024 ** 3
            txt = f"{vm.percent:.0f} % · {used:.1f} / {total:.1f} Go".replace(".", ",")
            self._set_row("ram", txt, vm.percent)
        if "gpu" in self.rows:
            g = self.sensors.get("gpu")
            if g is None:
                self._set_row("gpu", "…" if "gpu" not in self.sensors else "non disponible", 0)
            else:
                parts = [f"{g['util']:.0f} %"]
                if g.get("mem_used") is not None:
                    mem = fmt_bytes(g["mem_used"])
                    if g.get("mem_total"):
                        mem = f"{mem.split()[0]} / {fmt_bytes(g['mem_total'])}"
                    parts.append(mem)
                hot = False
                if g.get("temp") is not None:
                    parts.append(f"{g['temp']:.0f} °C")
                    hot = g["temp"] >= c["alert_gputemp"]
                self._set_row("gpu", " · ".join(parts), g["util"],
                              warn=hot or g["util"] >= c["warn_threshold"])
        for key in self.rows:
            if key.startswith("disk:"):
                try:
                    u = psutil.disk_usage(key[5:])
                    self._set_row(key, f"{u.percent:.0f} % · {fmt_bytes(u.free)} libres", u.percent)
                except OSError:
                    pass
        if "net" in self.rows:
            down, up = self.last["down"], self.last["up"]
            peak = max([50 * 1024, *self.hist["net_down"], *self.hist["net_up"]]) * 1.15
            self._set_row("net", f"↓ {fmt_bytes(down)}/s   ↑ {fmt_bytes(up)}/s", warn=False,
                          series=[(self.hist["net_down"], c["accent_color"], True),
                                  (self.hist["net_up"], blend(c["text_color"], c["bg_color"], 0.35), False)],
                          maxv=peak)
        if "ping" in self.rows:
            ms = self.sensors.get("ping", "…")
            if ms == "…":
                self._set_row("ping", "…", warn=False)
            elif ms is None:
                self._set_row("ping", "hors ligne", warn=True)
            else:
                slow = ms >= 150
                self._set_row("ping", f"{ms:.0f} ms", warn=slow,
                              maxv=max([100.0, *self.hist["ping"]]) * 1.15)
        if "ip_local" in self.rows:
            self._set_row("ip_local", self.sensors.get("ip_local") or "…", warn=False)
        if "ip_public" in self.rows:
            self._set_row("ip_public", self.sensors.get("ip_public") or "…", warn=False)
        if "battery" in self.rows:
            b = self._battery()
            if b is not None:
                state = "secteur" if b.power_plugged else fmt_duration(b.secsleft) \
                    if b.secsleft not in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED) \
                    and b.secsleft > 0 else "sur batterie"
                self._set_row("battery", f"{b.percent:.0f} % · {state}", b.percent)
        if "uptime" in self.rows:
            self._set_row("uptime", fmt_duration(time.time() - psutil.boot_time()))

    def _clock_loop(self):
        try:
            self.update_clock()
            if int(time.time()) % 2 == 0:
                self._keep_on_desktop()
        except tk.TclError:
            pass
        self.root.after(1000 - int(time.time() * 1000) % 1000 + 5, self._clock_loop)

    # ----- Robustesse : démarrage de Windows, veille, changement d'écran ------------
    def _health_loop(self):
        """Toutes les 3 s : répare les widgets que Windows aurait cachés et détecte la sortie de veille."""
        now = time.time()
        resumed = now - self._last_health > 20       # la boucle s'est arrêtée : l'ordinateur était en veille
        bounds = self._screen_bounds()
        screen_changed = bounds != self._last_bounds  # écran branché / débranché, résolution…
        self._last_health, self._last_bounds = now, bounds
        try:
            if not self.cfg["widgets_hidden"]:
                for w in self.all_windows():
                    if not (w is self.root and self.main_hidden):
                        ensure_visible(w)
            if self.settings_win and self.settings_win.win.winfo_exists():
                ensure_visible(self.settings_win.win)
            if resumed or screen_changed:
                self._recover()
        except Exception:  # noqa: BLE001
            log_exception("contrôle des widgets")
        self.root.after(3000, self._health_loop)

    def _on_screen(self, win):
        x0, y0, x1, y1 = self._screen_bounds()
        x, y = win.winfo_x(), win.winfo_y()
        w, h = max(40, win.winfo_width()), max(40, win.winfo_height())
        return x + w > x0 + 20 and x < x1 - 20 and y + h > y0 + 10 and y < y1 - 20

    def _recover(self):
        """Remet tout d'aplomb : après le démarrage de Windows ou une sortie de veille."""
        try:
            self.organizer.apply_icon_visibility()   # le bureau Windows n'était peut-être pas prêt
            self.organizer.retry_failed_icons()      # icônes non chargées au démarrage
            self.organizer.avoid_cards()             # panneaux restés sous une carte : vers une place libre
            if not self._on_screen(self.root):
                self._place_initial()
            for k, win in self.panels.items():
                if not self._on_screen(win):
                    win.geometry("+40+40") if k == "clock" else win.geometry("+40+160")
            misplaced = [cat for cat, win in self.organizer.fences.items() if not self._on_screen(win)]
            if misplaced:
                self.organizer.auto_layout(only=misplaced)
            if not self.cfg["widgets_hidden"]:
                for w in self.all_windows():
                    if not (w is self.root and self.main_hidden):
                        ensure_visible(w)
                        w.attributes("-alpha", w.attributes("-alpha"))  # rafraîchit la transparence
            self._keep_on_desktop()
        except Exception:  # noqa: BLE001
            log_exception("remise en ordre des widgets")

    def _stats_loop(self):
        try:
            self.sample()
            self.update_stats()
            self._tray_tooltip()
        except Exception:
            pass
        self.root.after(max(250, int(self.cfg["refresh_ms"])), self._stats_loop)

    def _tray_tooltip(self):
        """Windows : équivalent de la barre des menus du Mac, dans l'infobulle de l'icône de notification."""
        if not IS_WIN or not hasattr(self, "tray") or time.time() - getattr(self, "_tip_time", 0) < 2:
            return
        self._tip_time = time.time()
        last = self.last
        if self.cfg.get("card_menubar") and last:
            self.tray.set_tooltip(f"{APP_NAME} — CPU {last['cpu']:.0f} % · RAM {last['ram']:.0f} %\n"
                                  f"↓ {fmt_bytes(last['down'])}/s · ↑ {fmt_bytes(last['up'])}/s")
        else:
            self.tray.set_tooltip(f"{APP_NAME} {APP_VERSION}")

    def _sensor_loop(self):
        """Thread : GPU, ping et IP (opérations lentes ou réseau, hors de l'interface)."""
        gpu = None
        last_ping = last_local = last_public = 0.0
        while True:
            c, show, now = self.cfg, self.cfg["show"], time.time()
            try:
                if show["gpu"] or (c["alerts"] and c["alert_gputemp_on"]):
                    if gpu is None:
                        gpu = sensors.GpuMonitor()
                    self.sensors["gpu"] = gpu.sample() if gpu.available else None
                if (show["ping"] or (c["alerts"] and c["alert_offline_on"])) and now - last_ping >= 3:
                    last_ping = now
                    ms = sensors.tcp_ping(c["ping_host"].strip() or "1.1.1.1")
                    self.sensors["ping"] = ms
                    self.sensors["ping_fails"] = 0 if ms is not None else self.sensors.get("ping_fails", 0) + 1
                if show["ip_local"] and now - last_local >= 30:
                    last_local = now
                    self.sensors["ip_local"] = sensors.local_ip() or "non connecté"
                if show["ip_public"] and (now - last_public >= 600 or
                                          (not self.sensors.get("ip_public") and now - last_public >= 60)):
                    last_public = now
                    self.sensors["ip_public"] = sensors.public_ip()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.5)

    # ----- Tâches en arrière-plan -------------------------------------------
    def run_bg(self, func, busy_msg, done=None):
        if self._busy:
            self.set_status("Une opération est déjà en cours…")
            return
        self._busy = True
        self.set_status(busy_msg, sticky=True)

        def worker():
            try:
                self._jobs.put((done or self.set_status, func(), None))
            except Exception as ex:  # noqa: BLE001
                self._jobs.put((None, None, ex))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_jobs(self):
        try:
            while True:
                done, res, err = self._jobs.get_nowait()
                self._busy = False
                if err is not None:
                    self.set_status(f"Erreur : {err}")
                elif done:
                    done(res)
        except queue.Empty:
            pass
        try:
            while True:
                fn, args = self._ui_calls.get_nowait()
                try:
                    fn(*args)
                except Exception as ex:  # noqa: BLE001
                    self.set_status(f"Erreur : {ex}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_jobs)

    def set_status(self, text, sticky=False):
        if self._status_after:
            self.root.after_cancel(self._status_after)
            self._status_after = None
        if self.main_hidden:
            if not sticky:
                self._toast(text)
            return
        try:
            self.status_lbl.configure(text=text)
        except tk.TclError:
            return
        if not sticky:
            self._status_after = self.root.after(8000, lambda: self.status_lbl.configure(text=""))

    def _toast(self, text, ms=4500):
        """Petite bulle d'information qui disparaît seule (le widget principal est caché : pas de boîte modale)."""
        c = self.cfg
        try:
            if getattr(self, "_toast_win", None) is not None and self._toast_win.winfo_exists():
                self._toast_win.destroy()
            t = self._toast_win = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            t.configure(bg=c["accent_color"])
            body = tk.Frame(t, bg=c["bg_color"], padx=14, pady=9)
            body.pack(padx=1, pady=1)
            tk.Label(body, text=text, bg=c["bg_color"], fg=c["text_color"], font=(c["font_family"], int(c["text_size"])),
                     justify="left", wraplength=int(340 * self._scale())).pack()
            t.update_idletasks()
            x0, y0, x1, y1 = self._work_area() if IS_WIN else self._screen_bounds()
            t.geometry(f"+{x1 - t.winfo_reqwidth() - 20}+{y0 + (44 if IS_MAC else 20)}")
            t.after(ms, lambda: t.winfo_exists() and t.destroy())
        except tk.TclError:
            pass

    def open_processes(self):
        if self.proc_win and self.proc_win.win.winfo_exists():
            self.proc_win.win.deiconify()
            self.proc_win.win.lift()
            return
        self.proc_win = ProcessWindow(self)

    def open_settings(self, page=None):
        if not (self.settings_win and self.settings_win.win.winfo_exists()):
            self.settings_win = SettingsWindow(self)
        w = self.settings_win.win
        w.deiconify()
        w.lift()
        w.focus_force()
        if page:
            self.settings_win.show(page)

    def toggle(self, key):
        self.cfg[key] = not self.cfg[key]
        self.schedule_rebuild()

    def toggle_autostart(self):
        try:
            set_autostart(not is_autostart())
            self.set_status("Démarrage automatique " + ("activé" if is_autostart() else "désactivé"))
        except OSError as ex:
            self.set_status(f"Erreur : {ex}")

    def relaunch_admin(self):
        if not IS_WIN:
            return
        exe, args = launch_command()
        save_config(self.cfg)
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f"{args} --restart".strip(), None, 1)
        if r > 32:
            self.quit()

    def show_menu(self, e):
        c = self.cfg
        opts = dict(tearoff=0, bg=UI["card"], fg=UI["text"], activebackground=c["accent_color"],
                    activeforeground="#FFFFFF", bd=0, relief="flat")
        m = tk.Menu(self.root, **opts)
        m.add_command(label="⚙  Paramètres…", command=self.open_settings)
        m.add_separator()
        m.add_command(label="⚡  Tout optimiser", command=self.action_boost)
        am = tk.Menu(m, **opts)
        am.add_command(label="🧹  Nettoyer le cache", command=self.action_clean)
        am.add_command(label="🧠  Libérer la RAM", command=self.action_ram)
        am.add_command(label="🌐  Vider le cache DNS", command=self.action_dns)
        am.add_command(label="🗑  Vider la corbeille…", command=self.action_recycle)
        am.add_separator()
        am.add_command(label="📊  Processus / CPU…", command=self.open_processes)
        if IS_WIN:
            am.add_command(label="🖥  Gestionnaire des tâches",
                           command=lambda: subprocess.Popen(["taskmgr"], creationflags=no_window_flags()))
            am.add_separator()
            am.add_command(label="🔋  Hautes performances", command=lambda: self.action_power(True))
            am.add_command(label="🔋  Utilisation normale", command=lambda: self.action_power(False))
        m.add_cascade(label="🛠  Actions", menu=am)
        names = self.profiles.names()
        if names:
            pr = tk.Menu(m, **opts)
            for n in names:
                pr.add_radiobutton(label=n, command=lambda k=n: self.apply_profile(k),
                                   variable=tk.StringVar(pr, c.get("profile", "")), value=n)
            m.add_cascade(label="👤  Profils", menu=pr)
        m.add_separator()
        dm = tk.Menu(m, **opts)
        dm.add_checkbutton(label="Heure dans un widget séparé", command=lambda: self.toggle("detach_clock"),
                           variable=tk.BooleanVar(dm, c["detach_clock"]))
        dm.add_checkbutton(label="Date dans un widget séparé", command=lambda: self.toggle("detach_date"),
                           variable=tk.BooleanVar(dm, c["detach_date"]))
        dm.add_checkbutton(label="Bureau organisé", command=lambda: self.toggle("org_enabled"),
                           variable=tk.BooleanVar(dm, c["org_enabled"]))
        if c["org_enabled"]:
            dm.add_command(label="Ranger les panneaux automatiquement", command=self.organizer.auto_layout)
        dm.add_command(label="Ranger tout le bureau", command=self.tidy_desktop)
        dm.add_separator()
        dm.add_checkbutton(label="Toujours au premier plan", command=lambda: self.toggle("topmost"),
                           variable=tk.BooleanVar(dm, c["topmost"]))
        dm.add_checkbutton(label="Verrouiller les positions", command=lambda: self.toggle("locked"),
                           variable=tk.BooleanVar(dm, c["locked"]))
        dm.add_command(label="Replacer les widgets", command=self.reset_position)
        m.add_cascade(label="🗔  Disposition", menu=dm)
        m.add_command(label="🙈  Masquer les widgets", command=lambda: self.set_widgets_hidden(True))
        if IS_WIN and not is_admin():
            m.add_command(label="🛡  Relancer en administrateur", command=self.relaunch_admin)
        m.add_separator()
        m.add_command(label="Quitter", command=self.quit)
        bring_to_front(self.root)  # sinon le menu ne se ferme pas en cliquant ailleurs
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def quit(self):
        self.tray.stop()
        self.organizer.shutdown()
        save_config(self.cfg)
        self.root.destroy()


# --------------------------------------------------------------------------- #
#  Démarrage
# --------------------------------------------------------------------------- #
_MUTEX = None
SIGNAL_FILE = CONFIG_DIR / "open-settings.signal"


def single_instance():
    """Empêche de lancer deux widgets en même temps."""
    global _MUTEX
    if not IS_WIN:  # macOS / Linux : verrou exclusif sur un fichier
        import fcntl
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _MUTEX = open(CONFIG_DIR / "instance.lock", "w")
        for _ in range(30 if "--restart" in sys.argv else 1):
            try:
                fcntl.flock(_MUTEX, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                time.sleep(0.2)
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    tries = 30 if "--restart" in sys.argv else 1
    for _ in range(tries):
        h = k32.CreateMutexW(None, False, "Local\\DeskMonitor_SingleInstance")
        if h and ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            _MUTEX = h
            return True
        if h:
            k32.CloseHandle(h)
        time.sleep(0.2)
    return False


def main():
    if IS_WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    if "--show-icons" in sys.argv:  # utilisé par le désinstalleur
        set_desktop_icons(True)
        return
    if "--selftest" in sys.argv:  # vérification automatique de l'application compilée (GitHub Actions)
        from selftest import selftest
        sys.exit(selftest(DeskWidget))
    if "--speech-test" in sys.argv or "--mic-test" in sys.argv:   # tests de la reconnaissance vocale
        from selftest import speech_test
        sys.exit(speech_test())
    if "--wake-test" in sys.argv:   # --wake-test SORTIE NOM [secondes] : journal de l'écoute continue
        from selftest import wake_test
        sys.exit(wake_test())
    if not single_instance():
        # déjà lancé (raccourci du menu Démarrer, par ex.) : on demande à l'instance d'ouvrir ses paramètres
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SIGNAL_FILE.write_text("1", encoding="utf-8")
        except OSError:
            pass
        return
    # toute erreur (y compris dans l'interface) est consignée dans erreurs.log
    sys.excepthook = lambda *exc: log_exception("erreur non gérée", exc)
    threading.excepthook = lambda a: log_exception(f"thread {a.thread.name if a.thread else ''}",
                                                   (a.exc_type, a.exc_value, a.exc_traceback))
    root = tk.Tk()
    root.report_callback_exception = lambda *exc: log_exception("interface", exc)
    app = DeskWidget(root)
    if IS_MAC and getattr(sys, "frozen", False) and not app.cfg["autostart_done"]:
        try:  # 1er lancement de l'application installée : démarrage automatique à l'ouverture de session
            set_autostart(True)
        except OSError:
            pass
        app.cfg["autostart_done"] = True
        app.save()
    app._migrate()
    app.voice_ready = True
    root.after(8000, app.prefetch_voice)
    if not app.cfg["onboarded"]:   # premier lancement : prénom, langue, nom de l'assistant
        import onboarding
        root.after(1200, lambda: onboarding.Onboarding(app, on_done=app.introduce))
    elif app.cfg["voice_recap"]:
        root.after(12000, app.speak_recap)   # laisse le temps à la météo et à l'agenda d'arriver
    root.mainloop()


if __name__ == "__main__":
    main()

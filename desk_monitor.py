#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeskMonitor — widget de bureau : heure, date, performances de la machine
et optimisation en un clic (cache, RAM, CPU, DNS, corbeille).

Clic gauche maintenu : déplacer le widget
Clic droit           : menu (paramètres, actions, quitter...)
"""

import ctypes
import glob
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from tkinter import font as tkfont

try:
    import psutil
except ImportError:  # pragma: no cover
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror("DeskMonitor", "Le module 'psutil' est requis.\n\npip install psutil")
    sys.exit(1)

import sensors
import actions
from organizer import DesktopOrganizer, collect_items, set_desktop_icons
from profiles import ProfileManager, theme_from_wallpaper, wallpaper_signature
from settings_ui import UI, SettingsWindow, dark_titlebar, font_list, setup_styles
from tray import TrayIcon
import lockscreen
import mac_native
import macdata
import updater
import voice as voicemod
import assistant
import wallpaper_dynamic
import wallpapers
from anim import Animator
from anim import ease_in as anim_ease_in
from cards import CardManager

from core import (
    IS_WIN,
    TEXT_FONT,
    APP_NAME,
    APP_VERSION,
    HIST_LEN,
    CONFIG_DIR,
    CONFIG_FILE,
    JOURS_COURTS,
    MOIS_COURTS,
    JOURS,
    MOIS,
    THEMES,
    DATE_FORMATS,
    WITH_WEEKDAY,
    DATE_CASES,
    ALIGNS,
    format_date,
    blend,
    font_spec,
    SHOW_ITEMS,
    HIDDEN_BY_DEFAULT,
    DETACHABLE,
    DEFAULTS,
    load_config,
    save_config,
    fmt_bytes,
    fmt_duration,
    no_window_flags,
    run_cmd,
    is_admin,
    launch_command,
    RUN_KEY,
    is_autostart,
    set_autostart,
    apply_corners,
    bring_to_front,
    cfg_signature,
    no_activate,
    ensure_visible,
    log_exception,
    bind_right_click,
    open_path,
    IS_MAC,
    STYLE_KEYS,
    hide_from_taskbar,
)
if IS_WIN:
    from ctypes import wintypes
    import winsound


# --------------------------------------------------------------------------- #
#  Optimisation
# --------------------------------------------------------------------------- #
class Optimizer:
    @staticmethod
    def _excluded():
        ex = set()
        meipass = getattr(sys, "_MEIPASS", None)  # dossier temporaire de l'exe
        if meipass:
            ex.add(os.path.normcase(os.path.abspath(meipass)))
        return ex

    @classmethod
    def _clean_dir(cls, path, excluded):
        """Supprime le contenu de `path` (pas le dossier lui-même).
        Retourne (octets libérés, éléments ignorés)."""
        freed = skipped = 0
        try:
            entries = list(os.scandir(path))
        except OSError:
            return 0, 0
        for e in entries:
            try:
                if os.path.normcase(os.path.abspath(e.path)) in excluded:
                    continue
                # ne jamais suivre de liens/jonctions
                if e.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(e.path)):
                    continue
                if e.is_dir(follow_symlinks=False):
                    f, s = cls._clean_dir(e.path, excluded)
                    freed += f
                    skipped += s
                    try:
                        os.rmdir(e.path)
                    except OSError:
                        pass
                else:
                    size = e.stat(follow_symlinks=False).st_size
                    try:
                        os.remove(e.path)
                    except PermissionError:
                        os.chmod(e.path, stat.S_IWRITE)
                        os.remove(e.path)
                    freed += size
            except OSError:
                skipped += 1
        return freed, skipped

    @staticmethod
    def cache_targets(browsers=True):
        home = Path.home()
        targets = [tempfile.gettempdir()]
        if IS_WIN:
            local = os.getenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
            windir = os.getenv("WINDIR", r"C:\Windows")
            targets += [
                os.path.join(windir, "Temp"),
                os.path.join(local, "Microsoft", "Windows", "INetCache"),
                os.path.join(local, "CrashDumps"),
                os.path.join(local, "D3DSCache"),
            ]
            if browsers:
                for base in (r"Google\Chrome", r"Microsoft\Edge", r"BraveSoftware\Brave-Browser",
                             r"Vivaldi", r"Chromium"):
                    for sub in ("Cache", "Code Cache", "GPUCache"):
                        targets += glob.glob(os.path.join(local, base, "User Data", "*", sub))
                targets += glob.glob(os.path.join(local, "Mozilla", "Firefox", "Profiles", "*", "cache2"))
                targets += glob.glob(os.path.join(os.getenv("APPDATA", ""), "Opera Software", "*", "Cache"))
        elif sys.platform == "darwin":
            targets.append(str(home / "Library" / "Caches"))
        else:
            targets.append(str(home / ".cache" / "thumbnails"))
            if browsers:
                for b in ("mozilla", "google-chrome", "chromium", "BraveSoftware"):
                    targets.append(str(home / ".cache" / b))
        seen, result = set(), []
        for t in targets:
            key = os.path.normcase(os.path.abspath(t))
            if key not in seen and os.path.isdir(t):
                seen.add(key)
                result.append(t)
        return result

    @classmethod
    def clean_cache(cls, browsers=True, recycle=False):
        excluded = cls._excluded()
        freed = skipped = 0
        for t in cls.cache_targets(browsers):
            f, s = cls._clean_dir(t, excluded)
            freed += f
            skipped += s
        msg = f"Cache nettoyé : {fmt_bytes(freed)} libérés"
        if recycle:
            msg += " · " + cls.empty_recycle_bin()
        if skipped:
            msg += f" ({skipped} fichiers en cours d'utilisation ignorés)"
        return msg

    @staticmethod
    def empty_recycle_bin():
        if IS_MAC:  # le Finder vide la corbeille (macOS peut demander l'autorisation la 1re fois)
            code, _ = run_cmd(["osascript", "-e", 'tell application "Finder" to empty trash'])
            return "Corbeille vidée" if code == 0 else "Impossible de vider la corbeille"
        if not IS_WIN:
            return "Corbeille : Windows uniquement"

        class SHQUERYRBINFO(ctypes.Structure):
            if ctypes.sizeof(ctypes.c_void_p) == 4:
                _pack_ = 1
            _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        shell32 = ctypes.windll.shell32
        shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if info.i64NumItems == 0:
            return "Corbeille déjà vide"
        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        shell32.SHEmptyRecycleBinW(None, None, 0x07)
        return f"Corbeille vidée ({fmt_bytes(info.i64Size)})"

    @staticmethod
    def free_ram():
        if not IS_WIN:
            return "Libération de la RAM : disponible sous Windows uniquement"
        before = psutil.virtual_memory().available
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        access = 0x1000 | 0x0100  # QUERY_LIMITED_INFORMATION | SET_QUOTA
        count = 0
        own = os.getpid()
        for pid in psutil.pids():
            if pid in (0, 4, own):
                continue
            h = k32.OpenProcess(access, False, pid)
            if h:
                if psapi.EmptyWorkingSet(h):
                    count += 1
                k32.CloseHandle(h)
        time.sleep(1.0)
        gained = max(0, psutil.virtual_memory().available - before)
        msg = f"RAM optimisée : {fmt_bytes(gained)} récupérés sur {count} processus"
        if not is_admin():
            msg += " (lancez en admin pour plus d'effet)"
        return msg

    @staticmethod
    def flush_dns():
        if IS_WIN:
            code, _ = run_cmd(["ipconfig", "/flushdns"])
            return "Cache DNS vidé" if code == 0 else "Échec du vidage DNS"
        return "Vidage DNS : Windows uniquement"

    @staticmethod
    def current_power_plan():
        if not IS_WIN:
            return "?"
        code, out = run_cmd(["powercfg", "/getactivescheme"])
        if code == 0 and "(" in out:
            return out[out.rfind("(") + 1:out.rfind(")")]
        return "?"

    @staticmethod
    def set_power_plan(high_perf):
        if not IS_WIN:
            return "Plans d'alimentation : Windows uniquement"
        scheme = "SCHEME_MIN" if high_perf else "SCHEME_BALANCED"
        code, _ = run_cmd(["powercfg", "/setactive", scheme])
        if code != 0:
            return "Ce plan d'alimentation n'est pas disponible sur cette machine"
        return f"Plan d'alimentation : {Optimizer.current_power_plan()}"

    @classmethod
    def boost_all(cls, browsers, recycle):
        parts = [cls.clean_cache(browsers, recycle), cls.free_ram(), cls.flush_dns()]
        return "\n".join(parts)


# --------------------------------------------------------------------------- #
#  Widget principal
# --------------------------------------------------------------------------- #
class DeskWidget:
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
    def _wallpaper_loop(self):
        """Thème assorti au fond d'écran : réappliqué dès que le fond d'écran change."""
        try:
            if self.cfg["theme_auto_wallpaper"]:
                sig = wallpaper_signature()
                if sig and sig != self._wall_sig:
                    self._wall_sig = sig
                    self.cfg["accent_color"] = theme_from_wallpaper()["accent_color"]
                    self._do_rebuild()
                    if self.settings_win and self.settings_win.win.winfo_exists():
                        self.settings_win.refresh()
            else:
                self._wall_sig = None
        except Exception:  # noqa: BLE001
            pass
        self.root.after(10000, self._wallpaper_loop)

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

    # ----- Fonds d'écran et écran de verrouillage ------------------------------
    def _in_background(self, func, done=None, error_title=None):
        """Exécute func() dans un thread ; done(résultat) ou l'erreur reviennent dans l'interface."""
        def worker():
            try:
                res = func()
                if done:
                    self.call_soon(done, res)
            except Exception as ex:  # noqa: BLE001
                if error_title:
                    self.call_soon(self.notify, error_title, str(ex))

        threading.Thread(target=worker, daemon=True).start()

    def apply_wallpaper(self, path, quiet=False):
        c = self.cfg

        def work():
            used = wallpapers.set_wallpaper(path, c["wallpaper_fit"])
            if c["wallpaper_lock_too"] or (c["lock_enabled"] and not c["lock_image"]):
                self._make_lockscreen(base=used)
            return used

        def done(_used):
            c["wallpaper_last"] = path
            self._slide_time = time.time()
            self.save()
            if not quiet:
                self.set_status(f"Fond d'écran : {Path(path).stem}")
            if self.settings_win and self.settings_win.win.winfo_exists() and \
                    self.settings_win.page in ("wallpapers", "lock"):
                self.settings_win.refresh()

        self._in_background(work, done, None if quiet else "Fond d'écran")

    def lock_base_image(self):
        c = self.cfg
        for p in (c["lock_image"], c["wallpaper_last"], wallpapers.current_wallpaper()):
            if p and os.path.isfile(p):
                return p
        items = wallpapers.list_wallpapers()
        return items[0][1] if items else None

    def _make_lockscreen(self, base=None):
        """(thread) compose et applique l'image de l'écran de verrouillage."""
        base = base if (base and not self.cfg["lock_image"]) else self.lock_base_image()
        if not base:
            raise OSError("Aucune image disponible pour l'écran de verrouillage.")
        lockscreen.apply_image(lockscreen.compose(self.cfg, base))
        self.cfg["lock_last_date"] = datetime.now().strftime("%Y-%m-%d")

    def update_lockscreen(self, manual=False):
        def done(_):
            self.save()
            if manual:
                self.notify("Écran de verrouillage", "Votre écran de verrouillage a été mis à jour.\n"
                                                     "Appuyez sur Windows + L pour le voir.")

        if manual:
            self.cfg["lock_enabled"] = True
        self._in_background(self._make_lockscreen, done, "Écran de verrouillage" if manual else None)

    # ----- Voix ---------------------------------------------------------------------
    def _voice_allowed(self):
        c = self.cfg
        if not (self.voice_ready and c["voice_on"]):
            return False
        if c["voice_quiet"]:
            h, f, t = datetime.now().hour, int(c["voice_quiet_from"]), int(c["voice_quiet_to"])
            if ((h >= f or h < t) if f > t else f <= h < t):
                return False
        return True

    def speak(self, text, urgent=False, force=False):
        c = self.cfg
        if not (force or self._voice_allowed()):
            return
        lang = c["voice_lang"]
        if not hasattr(self, "_voice_cache"):
            self._voice_cache = {}
        if lang not in self._voice_cache:   # voix installées et meilleure voix, par langue (calculé une fois)
            self._voice_cache[lang] = (voicemod.voices(lang), voicemod.default_voice(lang))
        installed, best = self._voice_cache[lang]
        name = c["voice_name"]
        if name != voicemod.SYSTEM and name not in installed:
            name = best   # aucune voix choisie, ou voix d'une autre langue
        self.voice.say(text, name, c["voice_rate"], urgent)

    def prefetch_voice(self):
        """Réponses courtes préparées à l'avance (voix neuronale) : « Oui Alpho ? » part sans attendre."""
        c, t = self.cfg, self._tr
        name = c["user_name"].strip()
        best = voicemod.default_voice(c["voice_lang"])
        voice = c["voice_name"] if str(c["voice_name"]).startswith(voicemod.NEURAL_PREFIX) else best
        voicemod.prefetch([t(f"Oui {name} ?" if name else "Oui ?", f"Yes {name}?" if name else "Yes?"),
                           t("Je vous écoute.", "I'm listening."), t("Dites-moi.", "Go ahead."),
                           t(f"Oui, {name}, que puis-je faire ?" if name else "Que puis-je faire ?",
                             "What can I do for you?"),
                           t("Je n'ai rien entendu.", "I didn't catch that."), t("C'est fait.", "Done."),
                           t("Je libère la mémoire.", "Freeing up memory."), t("Je range le bureau.", "Tidying up the desktop.")],
                          voice, c["voice_rate"])

    def _tr(self, fr, en):
        return en if self.cfg["voice_lang"] == "en" else fr

    def _pct(self, v):
        return self._tr(f"{v:.0f} %", f"{v:.0f} percent")

    def _disk(self):
        try:
            return psutil.disk_usage("/System/Volumes/Data" if IS_MAC else
                                     (os.getenv("SystemDrive", "C:") + "\\") if IS_WIN else "/")
        except OSError:
            return None

    def recap_text(self):
        """Récapitulatif parlé : heure, machine, batterie, météo, agenda, ce qui est dans le rouge."""
        t, now = self._tr, datetime.now()
        if not self.last:
            self.sample()
        if now.hour < 5 or now.hour >= 18:
            hello = t("Bonsoir", "Good evening")
        else:
            hello = t("Bonjour", "Good morning" if now.hour < 12 else "Good afternoon")
        if c_name := self.cfg["user_name"].strip():
            hello += " " + c_name
        parts = [hello + ". " + t(f"Il est {self._heure(now.hour, now.minute)}.",
                                  f"It's {now.strftime('%-I:%M %p') if not IS_WIN else now.strftime('%I:%M %p')}.")]
        parts.append(t(f"Le processeur est à {self._pct(self.last['cpu'])}, la mémoire à {self._pct(self.last['ram'])}.",
                       f"The processor is at {self._pct(self.last['cpu'])}, memory at {self._pct(self.last['ram'])}."))
        d = self._disk()
        if d:
            parts.append(t(f"Il reste {d.free / 1e9:.0f} gigaoctets sur le disque.",
                           f"{d.free / 1e9:.0f} gigabytes left on the disk."))
        b = self._battery()
        if b is not None:
            if b.power_plugged:
                parts.append(t(f"Batterie à {self._pct(b.percent)}, sur secteur.",
                               f"Battery at {self._pct(b.percent)}, plugged in."))
            else:
                left = b.secsleft if b.secsleft and b.secsleft > 0 else None
                hm = (left // 3600, left % 3600 // 60) if left else None
                parts.append(t(f"Batterie à {self._pct(b.percent)}" +
                               (f", environ {hm[0]} heures {hm[1]} minutes d'autonomie." if hm else "."),
                               f"Battery at {self._pct(b.percent)}" +
                               (f", about {hm[0]} hours {hm[1]} minutes left." if hm else ".")))
        slow = self.cards.slow if hasattr(self, "cards") else {}
        w = slow.get("weather")
        if w:
            label = t(w["label"].lower(), macdata.WEATHER_EN.get(w.get("code"), ""))
            city = w.get("city")
            parts.append(t(f"{('À ' + city + ', ') if city else 'Dehors, '}{w['temp']:.0f} degrés, {label}.",
                           f"{('In ' + city + ', ') if city else 'Outside, '}{w['temp']:.0f} degrees, {label}."))
        ev = slow.get("events")
        if ev:
            today = [e for e in ev if e[1].date() == now.date()]
            if today:
                title, start, allday = today[0]
                n = len(today)
                at_fr = "." if allday else f", à {self._heure(start.hour, start.minute)}."
                at_en = "." if allday else f", at {start.strftime('%I:%M %p').lstrip('0')}."
                parts.append(t(f"Vous avez {n} rendez-vous aujourd'hui. Le prochain : {title}{at_fr}",
                               f"You have {n} appointment{'s' if n > 1 else ''} today. Next: {title}{at_en}"))
        rem = slow.get("reminders")
        if rem and rem[0]:
            n = rem[0]
            parts.append(t(f"{n} rappel{'s' if n > 1 else ''} à faire.", f"{n} reminder{'s' if n > 1 else ''} to do."))
        reds = self._red_messages()
        parts.append(" ".join(m for _, m in reds) if reds else t("Tout est au vert.", "Everything looks good."))
        return " ".join(parts)

    def speak_recap(self, force=False):
        self.speak(self.recap_text(), urgent=True, force=force)

    def _red_messages(self):
        """[(clé, phrase)] des valeurs actuellement dans le rouge."""
        c, t, out = self.cfg, self._tr, []
        thr = c["warn_threshold"]
        if not self.last:
            return out
        if self.last["cpu"] >= thr:
            p = self._pct(self.last["cpu"])
            out.append(("cpu", t(f"Attention, le processeur est à {p}.", f"Heads up, the processor is at {p}.")))
        if self.last["ram"] >= thr:
            p = self._pct(self.last["ram"])
            out.append(("ram", t(f"Attention, la mémoire est utilisée à {p}.", f"Heads up, memory is {p} full.")))
        d = self._disk()
        if d and d.percent >= thr:
            p = self._pct(d.percent)
            out.append(("disk", t(f"Attention, le disque est plein à {p}.", f"Heads up, the disk is {p} full.")))
        b = self._battery()
        if b is not None and not b.power_plugged and b.percent <= c["alert_bat"]:
            p = self._pct(b.percent)
            out.append(("bat", t(f"Batterie faible, {p}. Branchez le chargeur.",
                                 f"Battery low, {p}. Plug in the charger.")))
        if self.sensors.get("ping_fails", 0) >= 3:
            out.append(("offline", t("La connexion internet est coupée.", "The internet connection is down.")))
        return out

    def _voice_watch(self):
        """Annonce une valeur qui passe dans le rouge (une fois, puis au plus toutes les 10 minutes).
        Le processeur doit y rester 15 s : un pic d'une seconde ne mérite pas d'être annoncé."""
        try:
            if self.cfg["voice_alerts"] and self.last:
                now = time.time()
                reds = dict(self._red_messages())
                if "cpu" in reds:
                    self._cpu_red_since = getattr(self, "_cpu_red_since", None) or now
                    if now - self._cpu_red_since < 15:
                        reds.pop("cpu")
                else:
                    self._cpu_red_since = None
                name = self.cfg["user_name"].strip()
                for key, msg in reds.items():
                    if not self._red.get(key) and now - self._red_last.get(key, 0) >= 600:
                        self._red_last[key] = now
                        self.speak(f"{name}, {msg[0].lower()}{msg[1:]}" if name else msg, urgent=True)
                if self._red.get("offline") and "offline" not in reds:
                    self.speak(self._tr("La connexion internet est rétablie.", "The internet connection is back."))
                self._red = {k: True for k in reds}
        except Exception:  # noqa: BLE001
            log_exception("voix")
        self.root.after(2000, self._voice_watch)

    # ----- Assistant ---------------------------------------------------------------
    def _setup_listen_hotkey(self):
        spec = self.cfg["listen_hotkey"].strip()
        if spec != self._listen_spec:
            self._listen_spec = spec
            mac_native.register_hotkey(spec, lambda: self.call_soon(self.listen), slot=2) if spec else \
                mac_native.unregister_hotkey(2)
        self.root.after(3000, self._setup_listen_hotkey)   # suit les changements faits dans les paramètres

    def hotkey_words(self, spec=None):
        """« cmd+alt+j » → « Commande Option J » (pour le dire à voix haute)."""
        spec = spec or self.cfg["listen_hotkey"]
        fr = {"cmd": "Commande", "alt": "Option" if IS_MAC else "Alt", "ctrl": "Contrôle", "shift": "Majuscule"}
        en = {"cmd": "Command", "alt": "Option" if IS_MAC else "Alt", "ctrl": "Control", "shift": "Shift"}
        names = en if self.cfg["voice_lang"] == "en" else fr
        return " ".join(names.get(p, p.upper()) for p in spec.lower().split("+"))

    def introduce(self):
        c, t = self.cfg, self._tr
        name, asst = c["user_name"].strip(), c["assistant_name"].strip() or "Jarvis"
        keys = self.hotkey_words()
        hi_fr, hi_en = (f"Enchanté, {name}." if name else "Enchanté."), (f"Nice to meet you, {name}." if name
                                                                         else "Nice to meet you.")
        self.speak(t(f"{hi_fr} Je suis {asst}. Je veille sur votre ordinateur et je vous préviens si "
                     f"quelque chose ne va pas. Pour me parler, appuyez sur {keys}.",
                     f"{hi_en} I'm {asst}. I'll keep an eye on this computer and let you know if "
                     f"anything goes wrong. To talk to me, press {keys}."), force=True)
        self.root.after(1500, lambda: self.speak_recap(force=True))

    def _wake_should_run(self):
        c = self.cfg
        if not (self.voice_ready and c["wake_on"] and (IS_MAC or IS_WIN)):
            return False
        b = self._battery()
        if c["wake_battery_off"] and b is not None and not b.power_plugged:
            return False
        if c["wake_night_off"] and c["voice_quiet"]:
            h, f, t = datetime.now().hour, int(c["voice_quiet_from"]), int(c["voice_quiet_to"])
            if (h >= f or h < t) if f > t else f <= h < t:
                return False
        return True

    def _wake_loop(self):
        """Démarre / arrête l'écoute continue selon les réglages, la batterie et l'heure."""
        try:
            want = self._wake_should_run()
            if want and not self.wake.running:
                self.wake.start()
            elif not want and self.wake.running:
                self.wake.stop()
        except Exception:  # noqa: BLE001
            log_exception("activation vocale")
        self.root.after(5000, self._wake_loop)

    def learn_name(self, rounds=3):
        """Apprend comment la reconnaissance écrit le nom de l'assistant avec votre voix (3 essais)."""
        c, t = self.cfg, self._tr
        asst = c["assistant_name"].strip() or "Jarvis"
        was_running = self.wake.running
        self.wake.stop()
        found = []

        def step(i):
            if i >= rounds:
                learned = [a for a in dict.fromkeys(found) if a]
                c["wake_aliases"] = list(dict.fromkeys(c["wake_aliases"] + learned))[-6:]
                self.save()
                msg = t(f"Merci. Je reconnaîtrai mon nom, même prononcé « {', '.join(learned)} ».",
                        f"Thanks. I'll recognize my name, even when it sounds like \"{', '.join(learned)}\".") \
                    if learned else t("Merci. Je vous entends bien dire mon nom.", "Thanks. I can hear my name clearly.")
                self.speak(msg, force=True)
                if was_running:
                    self.root.after(4000, self.wake.start)
                return
            self.speak(t(f"Dites mon nom après le signal : {asst}." if i == 0 else "Encore une fois.",
                         f"Say my name after the tone: {asst}." if i == 0 else "Once more."), force=True)

            def wait_voice():
                if self.voice.speaking():
                    self.root.after(150, wait_voice)
                    return

                def heard(text, err):
                    if text:
                        found.append(assistant.learn_alias(text, asst))
                        self.call_soon(self._toast, f"« {text} »")
                    self.call_soon(step, i + 1)
                self.listener.listen(c["voice_lang"], heard, max_secs=6, on_ready=assistant.chime, free_only=True)
            self.root.after(300, wait_voice)

        step(0)

    def _files_loop(self):
        self.files.refresh()
        self.root.after(600000, self._files_loop)

    def assistant_vocab(self):
        """Noms proposés au moteur de reconnaissance : applications installées et dossiers (Windows)."""
        if not IS_WIN:
            return None
        apps = sorted({a[0] for a in (self.organizer.apps or [])}) + list(actions.ALIASES)
        places = ["téléchargements", "documents", "bureau", "images", "photos", "musique", "vidéos", "corbeille",
                  "ce PC", "paramètres", "OneDrive", "dossier personnel"] + self.files.spoken_names(60)
        return {"apps": apps, "places": places}

    @staticmethod
    def _heure(h, m):
        """L'heure comme on la dit : « minuit vingt », « une heure », « midi et quart », « 15 heures 40 »."""
        word = {0: "minuit", 12: "midi"}.get(h) or ("une heure" if h == 1 else f"{h} heures")
        if not m:
            return word
        if m == 15:
            return word + " et quart"
        if m == 30:
            return word + " et demie"
        return f"{word} {m}"

    def _pick(self, *options):
        """Une formulation au hasard : l'assistant ne répète pas toujours la même phrase."""
        import random
        return random.choice(options)

    def _do_action(self, act, run=True):
        """Ouvre une application, un dossier, un fichier ou lance une recherche. Retourne la réponse parlée."""
        t = self._tr
        kind, target, extra = act
        if kind == "search":
            site = "" if extra == "google" else f" {t('sur', 'on')} {extra.title()}"
            if run:
                actions.open_target(actions.search_url(target, extra))
            return self._pick(t(f"Voici ce que j'ai trouvé pour {target}{site}.", f"Here's what I found for {target}{site}."),
                              t(f"Je lance la recherche : {target}{site}.", f"Searching for {target}{site}."),
                              t(f"C'est parti, je cherche {target}{site}.", f"On it, looking up {target}{site}."))
        q = actions.norm(target)
        if q in ("tes parametres", "les parametres de deskmonitor", "deskmonitor", "tes reglages"):
            if run:
                self.open_settings()
            return t("J'ouvre mes paramètres.", "Opening my settings.")
        found, label = None, target
        folders = actions.known_folders()
        if extra in ("folder", "any"):
            if q in actions.SPECIAL:
                found, label = actions.SPECIAL[q], actions.SPECIAL_LABELS.get(q, target)
            elif q in folders:
                found, label = folders[q], t("le dossier ", "the ") + target[:1].upper() + target[1:] + \
                    ("" if self.cfg["voice_lang"] != "en" else " folder")
        if found is None and extra == "any":
            items = collect_items("apps", True, self.organizer.apps)
            app = actions.find_app(target, items)
            if app is not None:
                if run:
                    self.organizer.launch(app)
                return self._pick(t(f"J'ouvre {app['name']}.", f"Opening {app['name']}."),
                                  t(f"Je lance {app['name']}.", f"Launching {app['name']}."),
                                  t(f"C'est parti pour {app['name']}.", f"Here comes {app['name']}."))
            if q in actions.WEBSITES:
                found, label = actions.WEBSITES[q], actions.SITE_LABELS.get(q, target.title())
        if found is None:
            self.files.refresh()
            hit = self.files.find(target, extra)
            if hit:
                found = hit[0]
                label = (t("le dossier ", "the folder ") + Path(hit[0]).name if hit[1]
                         else t("le fichier ", "the file ") + Path(hit[0]).stem)
        if found is None:
            what = {"folder": t("le dossier", "the folder"), "file": t("le fichier", "the file")}.get(extra, "")
            return t(f"Je ne trouve pas {what} {target} sur l'ordinateur. Dites « cherche {target} » pour une "
                     f"recherche sur internet.".replace("  ", " "),
                     f"I can't find {what} {target} on this computer. Say \"search {target}\" to look it up online."
                     .replace("  ", " "))
        if run:
            try:
                actions.open_target(found)
            except OSError as ex:
                return t(f"Je n'arrive pas à ouvrir {label} : {ex}", f"I can't open {label}: {ex}")
        return self._pick(t(f"J'ouvre {label}.", f"Opening {label}."), t(f"Voilà, j'ouvre {label}.", f"There you go, opening {label}."),
                          t(f"Tout de suite : {label}.", f"Right away: {label}."))

    def _on_wake(self, command):
        name = self.cfg["user_name"].strip()
        if not command:   # seulement le nom : on attend la question
            assistant.chime()
            self._toast(self._tr("Je vous écoute…", "I'm listening…"), ms=8000)
            t = self._tr
            self.speak(self._pick(t(f"Oui {name} ?" if name else "Oui ?", f"Yes {name}?" if name else "Yes?"),
                                  t("Je vous écoute.", "I'm listening."), t("Dites-moi.", "Go ahead."),
                                  t(f"Oui, {name}, que puis-je faire ?" if name else "Que puis-je faire ?",
                                    "What can I do for you?")),
                       urgent=True, force=True)
            self.wake.arm()
            return
        self._on_heard(command, None)

    def listen(self):
        """Écoute une phrase, puis répond."""
        if self.wake.running:   # l'écoute continue tourne déjà : la prochaine phrase est une commande
            self.voice.stop()
            assistant.chime()
            self._toast(self._tr("Je vous écoute…", "I'm listening…"), ms=8000)
            self.wake.arm()
            return
        if self.listener.busy:
            return
        c = self.cfg
        self.voice.stop()
        asst = c["assistant_name"].strip() or "Jarvis"

        def ready():   # (thread) le moteur est prêt : signal sonore et bulle « j'écoute »
            assistant.chime()
            self.call_soon(self._toast, self._tr(f"{asst} vous écoute…", f"{asst} is listening…"), 8000)

        # Mac et Windows : le signal sonore n'est donné qu'une fois le micro prêt
        self.listener.listen(c["voice_lang"], lambda text, err: self.call_soon(self._on_heard, text, err),
                             on_ready=ready)

    def _on_heard(self, text, err):
        self._alog(f"entendu : « {text} » → {assistant.parse(text) if text else err}")
        if err or not text:
            self._toast(err or "…")
            self.speak(self._tr("Je n'ai rien entendu.", "I didn't catch that."), force=True)
            return
        self._toast(f"« {text} »")
        reply = self.answer(text)
        if reply:
            self.speak(reply, urgent=True, force=True)

    def answer(self, text, act=True):
        """Réponse de l'assistant à une phrase. act=False : ne déclenche aucune action (autotest)."""
        c, t = self.cfg, self._tr
        name = c["user_name"].strip()
        intent = assistant.parse(text)
        if not self.last:
            self.sample()
        slow = self.cards.slow
        if intent == "stop":
            if act:
                self.voice.stop()
            return ""
        todo = actions.parse(text)   # ouvrir une application / un dossier / un fichier, chercher sur internet
        if todo:
            return self._do_action(todo, run=act)
        words = actions.norm(text).split()
        if ({"libere", "liberer", "vide", "vider", "free", "clear"} & set(words)) and ({"memoire", "ram", "memory"} & set(words)):
            if act:
                self.action_ram()
            return t("Je libère la mémoire.", "Freeing up memory.")
        if "dns" in words:
            if act:
                self.action_dns()
            return t("Je vide le cache DNS.", "Flushing the DNS cache.")
        if intent == "tidy":
            if act:
                self.tidy_desktop()
            return self._pick(t("Je range le bureau.", "Tidying up the desktop."),
                              t("Et voilà, tout est bien rangé.", "There, everything's tidy."))
        if intent in ("hide", "show"):
            if act:
                self.set_widgets_hidden(intent == "hide")
            return self._pick(t("C'est fait.", "Done."), t("Voilà.", "There you go."), t("Tout de suite.", "Right away."))
        if intent == "clean":
            if act:
                self.action_clean()
            return self._pick(t("Je nettoie le cache, je vous dis combien j'ai libéré.", "Clearing the cache."),
                              t("Je fais le ménage dans les fichiers temporaires.", "Cleaning up temporary files."))
        if intent == "boost":
            if act:
                self.action_boost()
            return t("J'optimise le système : cache, mémoire et réseau.", "Optimizing the system: cache, memory and network.")
        if intent.startswith("music_"):
            playing = slow.get("music") or (macdata.now_playing() if act else None)
            if not playing:
                return t("Aucune musique en cours.", "Nothing is playing.")
            cmd = {"music_next": "next track", "music_prev": "previous track"}.get(intent, "playpause")
            if act:
                threading.Thread(target=macdata.player_command, args=(playing["app"], cmd), daemon=True).start()
            return ""
        if intent == "processes":
            procs = slow.get("procs") or []
            if not procs:
                return t("Rien ne ralentit l'ordinateur en ce moment.", "Nothing is slowing the computer down.")
            top = procs[0]
            nxt = f", {t('suivi de', 'followed by')} {procs[1][3]}" if len(procs) > 1 else ""
            return t(f"{top[3]} utilise le plus le processeur, {self._pct(top[0])}{nxt}.",
                     f"{top[3]} is using the most processor, {self._pct(top[0])}{nxt}.")
        if intent == "battery":
            b = self._battery()
            if b is None:
                return t("Cet ordinateur n'a pas de batterie.", "This computer has no battery.")
            state = t("en charge", "charging") if b.power_plugged else t("sur batterie", "on battery")
            return t(f"Batterie à {self._pct(b.percent)}, {state}.", f"Battery at {self._pct(b.percent)}, {state}.")
        if intent == "cpu":
            return t(f"Le processeur est à {self._pct(self.last['cpu'])}.",
                     f"The processor is at {self._pct(self.last['cpu'])}.")
        if intent == "ram":
            return t(f"La mémoire est utilisée à {self._pct(self.last['ram'])}.",
                     f"Memory is {self._pct(self.last['ram'])} used.")
        if intent == "disk":
            d = self._disk()
            return t(f"Il reste {d.free / 1e9:.0f} gigaoctets sur le disque.",
                     f"{d.free / 1e9:.0f} gigabytes left on the disk.") if d else ""
        if intent == "network":
            p = self.sensors.get("ping", "…")
            if p is None:
                return t("Pas de connexion internet.", "There's no internet connection.")
            if p == "…":
                return t("Je vérifie la connexion.", "Checking the connection.")
            return t(f"La connexion fonctionne, {p:.0f} millisecondes de latence.",
                     f"The connection is up, {p:.0f} milliseconds of latency.")
        if intent == "weather":
            w = slow.get("weather")
            if not w:
                return t("Je n'ai pas encore la météo. Activez la carte Météo.",
                         "I don't have the weather yet. Turn on the weather card.")
            label = t(w["label"].lower(), macdata.WEATHER_EN.get(w.get("code"), ""))
            return t(f"{w['temp']:.0f} degrés, {label}. Entre {w['tmin']:.0f} et {w['tmax']:.0f} aujourd'hui.",
                     f"{w['temp']:.0f} degrees, {label}. Between {w['tmin']:.0f} and {w['tmax']:.0f} today.")
        if intent == "agenda":
            ev = slow.get("events")
            if ev is None:
                return t("Je n'ai pas accès à votre agenda. Activez la carte Agenda.",
                         "I can't see your calendar. Turn on the calendar card.")
            if not ev:
                return t("Rien de prévu aujourd'hui ni demain.", "Nothing planned today or tomorrow.")
            title, start, allday = ev[0]
            when = t("aujourd'hui", "today") if start.date() == datetime.now().date() else t("demain", "tomorrow")
            at = "" if allday else t(f" à {self._heure(start.hour, start.minute)}",
                                     f" at {start.strftime('%I:%M %p').lstrip('0')}")
            return t(f"Prochain rendez-vous {when}{at} : {title}.", f"Next appointment {when}{at}: {title}.")
        if intent == "time":
            now = datetime.now()
            return t(f"Il est {self._heure(now.hour, now.minute)}.",
                     f"It's {now.strftime('%I:%M %p').lstrip('0')}.")
        if intent == "date":
            return t(f"Nous sommes le {format_date(datetime.now(), {**c, 'date_format': 'long'})}.",
                     f"Today is {datetime.now().strftime('%A, %B %d')}.")
        if intent == "recap":
            return self.recap_text()
        if intent == "hello":
            return t(f"Bonjour {name}. Que puis-je faire pour vous ?", f"Hello {name}. What can I do for you?")
        if intent == "thanks":
            return t(f"Avec plaisir, {name}.", f"My pleasure, {name}.")
        heard = text.strip(" .…")
        if not heard:   # Windows : la phrase après le nom ne fait pas partie des commandes connues
            return t("Je n'ai pas compris. Dites par exemple : ouvre Chrome, cherche la météo à Paris, ouvre le dossier "
                     "téléchargements, ma batterie, ou range le bureau.",
                     "I didn't catch that. Try: open Chrome, search the weather in Paris, open downloads, my battery, "
                     "or tidy the desktop.")
        return t(f"Je n'ai pas compris « {heard} ». Essayez : le point, la batterie, la météo ou mon agenda.",
                 f"I didn't understand \"{heard}\". Try: status, battery, weather or my schedule.")

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

    def _dynamic_wallpaper_loop(self):
        """Recompose le fond d'écran quand l'heure, l'état ou les mesures changent (au plus une fois par minute)."""
        c = self.cfg
        try:
            active = c["wp_dyn_time"] or c["wp_dyn_state"] or c["wp_dyn_stats"]
            if not active and c.get("wp_dyn_applied") and not self._dyn_busy:
                # effets coupés : on remet le fond d'écran d'origine (sinon les jauges restaient figées dessus)
                c["wp_dyn_applied"] = False
                self._dyn_sig = None
                base = c["wallpaper_last"]
                if base and os.path.isfile(base):
                    self.apply_wallpaper(base, quiet=True)
            if active and self.last and not self._dyn_busy:
                slot = wallpaper_dynamic.time_slot() if c["wp_dyn_time"] else None
                state = wallpaper_dynamic.state_of(c, self.last, self._battery(),
                                                   self.sensors.get("ping", "…")) if c["wp_dyn_state"] else ""
                disk = psutil.disk_usage("/System/Volumes/Data" if IS_MAC else "/").percent
                stats = [("CPU", round(self.last["cpu"], -1)), ("RAM", round(self.last["ram"], -1)),
                         ("DISQUE", round(disk))] if c["wp_dyn_stats"] else None
                sig = (slot, state, tuple(stats) if stats else None, c["wallpaper_last"], c["accent_color"])
                core = (sig[0], sig[1], sig[3], sig[4])
                recent = time.time() - self._dyn_time < 180   # jauges seules : au plus toutes les 3 minutes
                if sig != self._dyn_sig and not (recent and core == self._dyn_core):
                    self._dyn_sig, self._dyn_core, self._dyn_busy, self._dyn_time = sig, core, True, time.time()
                    base = next((p for p in (c["wallpaper_last"], wallpapers.current_wallpaper())
                                 if p and os.path.isfile(p) and "dynamic" not in Path(p).parts
                                 and not Path(p).name.startswith("dyn-")), None)
                    ratio = 2 if IS_MAC else 1  # Mac : écrans Retina
                    size = (self.root.winfo_screenwidth() * ratio, self.root.winfo_screenheight() * ratio)
                    acc = tuple(int(c["accent_color"][i:i + 2], 16) for i in (1, 3, 5))

                    def work():
                        path = wallpaper_dynamic.render_to_file(base_path=base, size=size, slot=slot, state=state,
                                                                stats=stats, accent=acc)
                        wallpapers.set_wallpaper(path, c["wallpaper_fit"])
                        c["wp_dyn_applied"] = True

                    def done(_r=None):
                        self._dyn_busy = False

                    def failed():
                        self._dyn_busy, self._dyn_sig = False, None

                    if base:
                        def run():
                            try:
                                work()
                            finally:
                                self.call_soon(done)
                        threading.Thread(target=run, daemon=True).start()
                    else:
                        failed()
        except Exception:  # noqa: BLE001
            self._dyn_busy = False
        self.root.after(60000, self._dynamic_wallpaper_loop)

    def _wallpaper_timers(self):
        """Diaporama de fonds d'écran + date de l'écran de verrouillage remise à jour chaque jour."""
        c = self.cfg
        try:
            if c["slideshow"] and time.time() - self._slide_time >= max(1, c["slideshow_minutes"]) * 60:
                nxt = wallpapers.next_slideshow(c)
                if nxt:
                    self.apply_wallpaper(nxt, quiet=True)
                self._slide_time = time.time()
            if c["lock_enabled"] and c["lock_show_date"] and \
                    c["lock_last_date"] != datetime.now().strftime("%Y-%m-%d"):
                self.cfg["lock_last_date"] = datetime.now().strftime("%Y-%m-%d")  # une tentative par jour
                self.update_lockscreen()
        except Exception:  # noqa: BLE001
            pass
        self.root.after(30000, self._wallpaper_timers)

    def _update_loop(self):
        c = self.cfg
        if c["update_auto"] and c["update_repo"]:
            self.check_updates(False)
        self.root.after(24 * 3600 * 1000, self._update_loop)

    def check_updates(self, manual=False):
        repo = self.cfg["update_repo"].strip()
        if not repo:
            if manual:
                messagebox.showinfo(APP_NAME, "Indiquez d'abord le dépôt GitHub où sont publiées les versions\n"
                                              "(Paramètres → Général → Mises à jour).")
                self.open_settings("general")
            return

        def worker():
            try:
                self.call_soon(self._on_update_checked, updater.check(repo), None, manual)
            except Exception as ex:  # noqa: BLE001
                self.call_soon(self._on_update_checked, None, ex, manual)

        if manual:
            self.set_status("Recherche de mise à jour…", sticky=True)
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_checked(self, info, err, manual):
        if manual:
            self.set_status("")
        if err is not None:
            if manual:
                messagebox.showerror(APP_NAME, f"Impossible de vérifier les mises à jour :\n{err}")
            return
        if info is None:
            if manual:
                messagebox.showinfo(APP_NAME, f"Vous avez déjà la dernière version ({APP_VERSION}).")
            return
        if not manual and self.cfg["update_skip"] == info["version"]:
            return
        if not manual:  # vérification automatique : simple notification cliquable
            self.notify("Mise à jour disponible", f"DeskMonitor {info['version']} est disponible.\n"
                                                  "Cliquez pour l'installer.", lambda: self._ask_update(info))
            return
        self._ask_update(info)

    def _ask_update(self, info):
        notes = info["notes"][:600] + ("…" if len(info["notes"]) > 600 else "")
        ans = messagebox.askyesnocancel(
            APP_NAME, f"DeskMonitor {info['version']} est disponible (vous avez la {APP_VERSION}).\n\n"
                      f"{notes}\n\nInstaller maintenant ?\n\n(Non = plus tard · Annuler = ignorer cette version)")
        if ans is None:
            self.cfg["update_skip"] = info["version"]
            self.save()
        elif ans:
            self.set_status("Téléchargement de la mise à jour…", sticky=True)

            def worker():
                try:
                    path = updater.download(info["url"])
                    self.call_soon(self._install_update, path)
                except Exception as ex:  # noqa: BLE001
                    self.call_soon(messagebox.showerror, APP_NAME, f"Téléchargement impossible :\n{ex}")

            threading.Thread(target=worker, daemon=True).start()

    def _install_update(self, path):
        updater.run_installer(path)
        self.quit()

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

    # ----- Alertes --------------------------------------------------------------
    def _alert_loop(self):
        try:
            self.check_alerts()
        except Exception:  # noqa: BLE001
            pass
        self.root.after(2000, self._alert_loop)

    def check_alerts(self):
        c = self.cfg
        if not c["alerts"] or not self.last:
            return
        now = time.time()

        def fire(key, title, msg, action=None):
            if now - self._alert_last.get(key, 0) >= c["alert_cooldown"] * 60:
                self._alert_last[key] = now
                self.notify(title, msg, action)

        if c["alert_cpu_on"]:
            if self.last["cpu"] >= c["alert_cpu"]:
                self._cpu_high_since = self._cpu_high_since or now
                if now - self._cpu_high_since >= c["alert_cpu_secs"]:
                    fire("cpu", "Processeur surchargé",
                         f"Le CPU est à {self.last['cpu']:.0f} % depuis plus de {c['alert_cpu_secs']} s.\n"
                         "Cliquez pour voir les programmes gourmands.", self.open_processes)
            else:
                self._cpu_high_since = None
        if c["alert_ram_on"] and self.last["ram"] >= c["alert_ram"]:
            fire("ram", "Mémoire presque pleine",
                 f"La RAM est utilisée à {self.last['ram']:.0f} %.\nCliquez pour libérer la mémoire.",
                 self.action_ram)
        if c["alert_disk_on"]:
            drive = (os.getenv("SystemDrive", "C:") + "\\") if IS_WIN else "/"
            free = shutil.disk_usage(drive).free
            if free < c["alert_disk_gb"] * 1024 ** 3:
                fire("disk", "Espace disque faible",
                     f"Il reste {fmt_bytes(free)} sur {drive}\nCliquez pour nettoyer le cache.", self.action_clean)
        if c["alert_bat_on"]:
            b = self._battery()
            if b is not None and not b.power_plugged and b.percent <= c["alert_bat"]:
                fire("bat", "Batterie faible", f"Batterie à {b.percent:.0f} %. Branchez le chargeur.")
        if c["alert_gputemp_on"]:
            g = self.sensors.get("gpu")
            if g and g.get("temp") is not None and g["temp"] >= c["alert_gputemp"]:
                fire("gputemp", "Carte graphique très chaude",
                     f"Le GPU est à {g['temp']:.0f} °C.")
        if c["alert_offline_on"] and self.sensors.get("ping_fails", 0) >= 3:
            fire("offline", "Connexion internet perdue",
                 f"{c['ping_host']} ne répond plus depuis quelques secondes.")

    def _work_area(self):
        return self.organizer._work_area()

    def notify(self, title, msg, action=None):
        """Petite notification en bas à droite de l'écran, aux couleurs du thème."""
        c = self.cfg
        if IS_MAC and c["native_alerts"]:
            mac_native.notify(title, msg, c["alert_sound"])
            return
        if IS_WIN and c["native_alerts"] and action is None and self.tray.icon is not None:
            self.tray.notify(title, msg)   # notification Windows (centre de notifications)
            return
        if c["alert_sound"] and IS_WIN:
            try:
                winsound.MessageBeep(0x30)  # MB_ICONWARNING
            except RuntimeError:
                pass
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.attributes("-alpha", 0.97)
        t._base_alpha, t._new = 0.97, True
        t.configure(bg=c["warn_color"])
        body = tk.Frame(t, bg=c["bg_color"], padx=14, pady=10, cursor="hand2")
        body.pack(fill="both", expand=True, padx=(5, 0))
        fam, ts = TEXT_FONT, int(c["text_size"])
        head = tk.Frame(body, bg=c["bg_color"])
        head.pack(fill="x")
        tk.Label(head, text=f"⚠  {title}", bg=c["bg_color"], fg=c["warn_color"],
                 font=(fam, ts + 1, "bold")).pack(side="left")
        close = tk.Label(head, text="✕", bg=c["bg_color"], fg=c["text_color"], font=(fam, ts), cursor="hand2")
        close.pack(side="right", padx=(12, 0))
        tk.Label(body, text=msg, bg=c["bg_color"], fg=c["text_color"], font=(fam, ts), justify="left",
                 wraplength=int(300 * self._scale())).pack(anchor="w", pady=(4, 0))

        def dismiss(_e=None, run=False):
            if t in self.toasts:
                self.toasts.remove(t)
            if run and action:
                action()
            if not t.winfo_exists():
                return

            def gone():
                if t.winfo_exists():
                    t.destroy()
                self._stack_toasts()
            if self.anim.on:   # elle repart vers le bord en s'effaçant, les autres se resserrent
                x, y = t.winfo_x(), t.winfo_y()
                self.anim.play(("toast-out", str(t)), 240, lambda p: (
                    t.attributes("-alpha", 0.97 * (1 - p)), t.geometry(f"+{round(x + 40 * p)}+{y}")),
                    anim_ease_in, gone)
            else:
                gone()

        for w in (body, head, *body.winfo_children(), *head.winfo_children()):
            w.bind("<Button-1>", lambda e: dismiss(run=True))
        close.bind("<Button-1>", lambda e: dismiss())
        apply_corners(t, c["rounded"])
        no_activate(t)
        self.toasts.append(t)
        self._stack_toasts()
        t.after(12000, dismiss)

    def _stack_toasts(self):
        left, top, right, bottom = self._work_area()
        gap = int(10 * self._scale())
        y = bottom - gap
        for t in reversed(self.toasts):
            if not t.winfo_exists():
                continue
            t.update_idletasks()
            w, h = t.winfo_reqwidth(), t.winfo_reqheight()
            y -= h
            x = right - w - gap
            if getattr(t, "_new", False) and self.anim.on:   # arrivée : glisse depuis le bord de l'écran
                t._new = False
                t.geometry(f"+{x + 60}+{y}")
                t.attributes("-alpha", 0.0)
                self.anim.fade(t, 0.97, 260)
                self.anim.glide(t, x, y, 420) if t.winfo_ismapped() else t.after(
                    10, lambda t=t, x=x, y=y: self.anim.glide(t, x, y, 420))
            else:
                t._new = False
                self.anim.glide(t, x, y, 320)
            y -= gap

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

    # ----- Actions ------------------------------------------------------------
    def _done_and(self, then=None):
        """Fin d'une action d'entretien : bulle d'information, puis then(résultat) (ex. retour sur une carte)."""
        def done(res):
            self.set_status(res)
            self._toast(str(res).split("\n")[0], 5000)
            if then:
                then(res)
        return done

    def action_clean(self, then=None):
        c = self.cfg
        self.run_bg(lambda: Optimizer.clean_cache(c["clean_browsers"], c["clean_recycle"]),
                    "Nettoyage du cache en cours…", self._done_and(then))

    def action_ram(self, then=None):
        self.run_bg(Optimizer.free_ram, "Libération de la mémoire…", self._done_and(then))

    def action_dns(self, then=None):
        self.run_bg(Optimizer.flush_dns, "Vidage du cache DNS…", self._done_and(then))

    def action_recycle(self):
        if messagebox.askyesno(APP_NAME, "Vider définitivement la corbeille ?", parent=self.root):
            self.run_bg(Optimizer.empty_recycle_bin, "Vidage de la corbeille…")

    def action_boost(self):
        c = self.cfg
        self.run_bg(lambda: Optimizer.boost_all(c["clean_browsers"], c["clean_recycle"]),
                    "Optimisation complète en cours…")

    def action_power(self, high):
        self.run_bg(lambda: Optimizer.set_power_plan(high), "Changement du plan d'alimentation…")

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
#  Fenêtre des processus (CPU)
# --------------------------------------------------------------------------- #
class ProcessWindow:
    COLS = (("name", "Processus", 220), ("pid", "PID", 70), ("cpu", "CPU %", 80), ("mem", "Mémoire", 100))

    def __init__(self, app):
        self.app = app
        self.sort_key, self.sort_rev = "cpu", True
        self.data = []
        w = self.win = tk.Toplevel(app.root)
        w.title(f"{APP_NAME} — Processus")
        sc = app._scale()
        w.geometry(f"{int(600 * sc)}x{int(540 * sc)}")
        w.minsize(460, 300)
        w.configure(bg=UI["bg"])
        w.attributes("-topmost", True)
        dark_titlebar(w)

        top = ttk.Frame(w, padding=8)
        top.pack(fill="x")
        self.plan_lbl = ttk.Label(top, text="Plan d'alimentation : …")
        self.plan_lbl.pack(side="left")
        if IS_WIN:
            ttk.Button(top, text="Équilibré", command=lambda: self.power(False)).pack(side="right")
            ttk.Button(top, text="⚡ Hautes perf.", command=lambda: self.power(True)).pack(side="right", padx=4)

        tf = ttk.Frame(w, padding=(8, 0))
        tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, columns=[c[0] for c in self.COLS], show="headings", selectmode="extended")
        for key, title, width in self.COLS:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor="w" if key == "name" else "e", stretch=key == "name")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bot = ttk.Frame(w, padding=8)
        bot.pack(fill="x")
        ttk.Button(bot, text="🔄 Actualiser", command=self.refresh).pack(side="left")
        self.auto = tk.BooleanVar(w, True)
        ttk.Checkbutton(bot, text="Auto (3 s)", variable=self.auto).pack(side="left", padx=8)
        ttk.Button(bot, text="❌ Terminer", command=self.kill).pack(side="right")
        ttk.Button(bot, text="⬇ Réduire la priorité", command=self.lower_priority).pack(side="right", padx=4)
        self.info = ttk.Label(w, text="", padding=(8, 0, 8, 8))
        self.info.pack(fill="x")

        self._loading = False
        self.q = queue.Queue()
        self.refresh()
        self._poll()
        self._auto_loop()

    def _collect(self):
        procs = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                p.cpu_percent(None)
                procs.append(p)
            except psutil.Error:
                pass
        time.sleep(0.8)
        ncpu = psutil.cpu_count() or 1
        rows = []
        for p in procs:
            try:
                if p.pid == 0:
                    continue
                rows.append((p.info["name"] or "?", p.pid, p.cpu_percent(None) / ncpu, p.memory_info().rss))
            except psutil.Error:
                pass
        return rows, Optimizer.current_power_plan()

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        if not self.data:
            self.info.configure(text="Chargement des processus…")

        def worker():
            try:
                res = self._collect()
            except Exception:  # noqa: BLE001
                res = ([], "?")
            self.q.put(res)

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        if not self.win.winfo_exists():
            return
        try:
            self._on_data(self.q.get_nowait())
        except queue.Empty:
            pass
        self.win.after(100, self._poll)

    def _on_data(self, res):
        self._loading = False
        self.data, plan = res
        self.plan_lbl.configure(text=f"Plan d'alimentation : {plan}")
        self._render()

    def _render(self):
        idx = {"name": 0, "pid": 1, "cpu": 2, "mem": 3}[self.sort_key]
        key = (lambda r: r[0].lower()) if idx == 0 else (lambda r: r[idx])
        rows = sorted(self.data, key=key, reverse=self.sort_rev)
        selected = {self.tree.set(i, "pid") for i in self.tree.selection()}
        self.tree.delete(*self.tree.get_children())
        for name, pid, cpu, mem in rows:
            iid = self.tree.insert("", "end", values=(name, pid, f"{cpu:.1f}".replace(".", ","), fmt_bytes(mem)))
            if str(pid) in selected:
                self.tree.selection_add(iid)
        total = psutil.cpu_percent(None)
        self.info.configure(text=f"{len(rows)} processus · CPU total {total:.0f} %")

    def sort_by(self, key):
        self.sort_rev = not self.sort_rev if self.sort_key == key else key != "name"
        self.sort_key = key
        self._render()

    def _auto_loop(self):
        if not self.win.winfo_exists():
            return
        if self.auto.get():
            self.refresh()
        self.win.after(3000, self._auto_loop)

    def _selected(self):
        return [(self.tree.set(i, "name"), int(self.tree.set(i, "pid"))) for i in self.tree.selection()]

    def kill(self):
        sel = self._selected()
        if not sel:
            return
        names = ", ".join(n for n, _ in sel[:5]) + ("…" if len(sel) > 5 else "")
        if not messagebox.askyesno(APP_NAME, f"Terminer : {names} ?\nLes données non enregistrées seront perdues.",
                                   parent=self.win):
            return
        errors = []
        for name, pid in sel:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error as ex:
                errors.append(f"{name} : {type(ex).__name__}")
        if errors:
            messagebox.showwarning(APP_NAME, "Impossible de terminer :\n" + "\n".join(errors) +
                                   "\n\n(Essayez de relancer en administrateur)", parent=self.win)
        self.win.after(500, self.refresh)

    def lower_priority(self):
        errors = []
        for name, pid in self._selected():
            try:
                p = psutil.Process(pid)
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if IS_WIN else 10)
            except psutil.Error as ex:
                errors.append(f"{name} : {type(ex).__name__}")
        if errors:
            messagebox.showwarning(APP_NAME, "Échec pour :\n" + "\n".join(errors), parent=self.win)
        else:
            self.info.configure(text="Priorité réduite ✔")

    def power(self, high):
        msg = Optimizer.set_power_plan(high)
        self.plan_lbl.configure(text=msg)


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


def selftest():
    """Démarre l'application, parcourt les paramètres et le bureau organisé, puis quitte.
    Code de retour 0 si aucune erreur. Le rapport est écrit dans CONFIG_DIR/selftest.txt."""
    import tempfile
    import traceback
    import core
    tmp = Path(tempfile.mkdtemp(prefix="deskmonitor-selftest-"))  # jamais la vraie configuration
    core.CONFIG_DIR, core.CONFIG_FILE = tmp, tmp / "config.json"
    report, errors = [], []
    root = tk.Tk()
    root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))
    app = DeskWidget(root)
    c = app.cfg
    c["animations"] = False   # positions vérifiées tout de suite : pas de glissement en cours

    def step(label, fn):
        try:
            res = fn()
            report.append(f"OK   {label}" + (f" : {res}" if res is not None else ""))
        except Exception:  # noqa: BLE001
            errors.append(f"{label}\n{traceback.format_exc()}")
            report.append(f"ÉCHEC {label}")

    def run():
        step("système", lambda: f"{sys.platform} / {APP_VERSION}")
        step("widget principal", lambda: f"{len(app.rows)} indicateurs")
        step("fonds d'écran intégrés", lambda: len(wallpapers.list_wallpapers()))
        step("applications installées", lambda: len(app.organizer.apps or
                                                     __import__("organizer").list_installed_apps()))

        def org():
            c.update(org_enabled=True, org_source="apps", org_hide_icons=False)
            app.organizer.apps = __import__("organizer").list_installed_apps()
            app.build()
            icons = sum(1 for k in app.organizer.icons.cache)
            return f"{len(app.organizer.fences)} panneaux, {icons} icônes chargées"
        step("bureau organisé", org)
        def cards_test():
            import cards as cardsmod
            out = []
            c["cards"] = [k for k in cardsmod.CARD_TYPES if k != "calendar"]  # l'agenda demande une autorisation
            for layout in ("cards", "minimal", "cards"):
                c["layout"] = layout
                app.build(force=True)
                app.root.update()
                app.sample()
                app.cards.update()
                app.cards.animate()
                out.append(f"{layout}={len(app.cards.cards)}")
            native = sum(1 for k in app.cards.cards.values() if k.native)
            return f"{', '.join(out)} ; flou natif : {native}"
        def overlap_test():
            c["layout"] = "cards"
            c["cards"] = ["clock", "system", "storage", "battery", "network", "music", "weather", "processes"]
            c["card_free"] = True
            c["card_pos"] = {"system": [100, 100], "network": [120, 110], "storage": [100, 100], "clock": [90, 95]}
            app.build(force=True)
            app.root.update()
            cm = app.cards
            rects = [cm._rect(k, cd.win.winfo_x(), cd.win.winfo_y()) for k, cd in cm.cards.items()]
            bad = sum(1 for i, r in enumerate(rects) if cm._hits(r, rects[:i] + rects[i + 1:], margin=0))
            cm.cards["system"].win.geometry(f"+{cm.cards['clock'].win.winfo_x()}+{cm.cards['clock'].win.winfo_y()}")
            cm.settle("system")
            rects = [cm._rect(k, cd.win.winfo_x(), cd.win.winfo_y()) for k, cd in cm.cards.items()]
            bad2 = sum(1 for i, r in enumerate(rects) if cm._hits(r, rects[:i] + rects[i + 1:], margin=0))
            c["card_pos"], c["card_free"] = {}, False
            if bad or bad2:
                raise RuntimeError(f"cartes superposées : {bad} au lancement, {bad2} après déplacement")
            return f"{len(rects)} cartes, aucune superposition"
        def strip_test():
            c["layout"], c["cards_cols"] = "cards", 2
            c["cards"] = list(__import__("cards").CARD_TYPES)
            c["card_pos"] = {}
            app.build(force=True)
            app.root.update()
            sw, sh = app.root.winfo_screenwidth(), app.root.winfo_screenheight()
            off = [k for k, cd in app.cards.cards.items()
                   if cd.win.winfo_x() + cd.px > sw or cd.win.winfo_y() + cd.py > sh]
            # cartes réellement disponibles : Musique optionnelle (Windows), Batterie absente sans batterie (Mac de bureau,
            # machine virtuelle…)
            available = [k for k in c["cards"] if k in __import__("cards").card_ids()
                         and not (k == "battery" and psutil.sensors_battery() is None)]
            missing = [k for k in available if k not in app.cards.cards]
            if off and not missing and getattr(app.cards, "overflow", False):
                # écran trop petit (machine virtuelle, runner GitHub…) : l'app le signale, c'est le comportement voulu
                return f"écran {sw}×{sh} trop petit : {len(off)} carte(s) dépassent, signalé à l'utilisateur"
            if off or missing:
                raise RuntimeError(f"cartes hors écran : {off} ; manquantes : {missing}")
            return f"{len(app.cards.cards)} cartes toutes visibles en colonnes"
        step("toutes les cartes à l'écran", strip_test)
        def align_test():
            c["layout"], c["card_free"] = "cards", False
            c["cards"] = ["clock", "system", "storage", "battery", "network", "music"]
            c["card_pos"] = {"clock": [9, 44], "system": [358, 42], "network": [7, 216]}  # anciennes positions
            app.build(force=True)
            app.root.update()
            cm = app.cards
            xs = {k: cd.win.winfo_x() for k, cd in cm.cards.items()}
            ys = {k: cd.win.winfo_y() for k, cd in cm.cards.items()}
            # pas de la grille tel que l'application le calcule (zoom de l'écran compris sous Windows)
            ox, oy, step_ = min(xs.values()), min(ys.values()), cm.unit + cm.gap
            off = [k for k in xs if (xs[k] - ox) % step_ or (ys[k] - oy) % step_]
            if off:
                raise RuntimeError(f"grille non alignée : {xs} {ys}")
            c["cards"] = ["clock", "system", "storage", "battery", "network"]  # cartes par défaut : 2 colonnes
            app.build(force=True)
            app.root.update()
            cols = {cd.win.winfo_x() for cd in cm.cards.values()}
            if len(cols) != 2:
                raise RuntimeError(f"colonnes attendues : 2, obtenues : {sorted(cols)}")
            c["cards"] = ["clock", "system", "storage", "battery", "network", "music"]
            app.build(force=True)
            app.root.update()
            xs = {k: cd.win.winfo_x() for k, cd in cm.cards.items()}
            ys = {k: cd.win.winfo_y() for k, cd in cm.cards.items()}
            before = list(cm.cards)
            cm.cards["storage"].win.geometry(f"+{xs['clock'] + 10}+{ys['clock'] + 10}")  # glissé sur l'horloge
            app.root.update()
            cm.reorder("storage")
            app.root.update()
            after = list(cm.cards)
            rects = [cm._rect(k, cd.win.winfo_x(), cd.win.winfo_y()) for k, cd in cm.cards.items()]
            bad = sum(1 for i, r in enumerate(rects) if cm._hits(r, rects[:i] + rects[i + 1:], margin=0))
            if after == before or bad or c["cards"][:len(after)] != after:
                raise RuntimeError(f"réorganisation : {before} -> {after}, superpositions {bad}")
            return f"{' > '.join(after)}"
        step("alignement et glisser-déposer", align_test)
        def extras_test():
            import cards as cardsmod
            c.update(layout="cards", cards=["clock", "system", "battery", "network", "storage", "weather"],
                     card_free=False, card_compact=True, card_text_scale=130)
            app.build(force=True)
            app.root.update()
            cm = app.cards
            order = cm._dense(list(cm.cards))
            smalls = [k for k in order if cm.cards[k].w == 1]
            if order[order.index(smalls[0]) + 1] != smalls[1]:
                raise RuntimeError(f"petites cartes non appariées : {order}")
            sizes = {cm.cards["system"].cv.itemcget(i, "font") for i in cm.cards["system"].cv.find_all()
                     if cm.cards["system"].cv.type(i) == "text"}
            c["card_text_scale"] = 100
            # profils automatiques : règle « nuit » forcée sur tout le jour
            app.profiles.save("Test nuit", c)
            c.update(ctx_on=True, ctx_night_profile="Test nuit", ctx_night_from=0, ctx_night_to=24, profile="")
            app._ctx_active = None
            app.root.after_cancel = app.root.after_cancel
            before = app._ctx_active
            app._context_loop()
            applied = app._ctx_active
            c["ctx_on"] = False
            app.profiles.delete("Test nuit")
            if applied != "Test nuit":
                raise RuntimeError(f"profil automatique non appliqué ({before} -> {applied})")
            return f"ordre {order} ; textes {len(sizes)} polices ; profil auto OK"
        step("compactage, taille du texte, profils auto", extras_test)
        step("anti-chevauchement", overlap_test)
        step("récapitulatif vocal (texte)", lambda: app.recap_text()[:90] + "…")

        def assistant_test():
            c.update(user_name="Alpho", assistant_name="Nova")
            phrases = ["Quelle heure est-il", "Où en est ma batterie", "Fais-moi le point", "Quel temps fait-il",
                       "Mes rendez-vous", "Qui ralentit mon Mac", "Bonjour", "Merci", "blabla", "Combien de mémoire"]
            empty = [p for p in phrases if not app.answer(p, act=False)]
            import onboarding
            ob = onboarding.Onboarding(app, on_done=lambda: None)
            ob.name_var.set("Alpho")
            ob._set_lang("en")
            ob.finish()
            ok = c["onboarded"] and c["voice_lang"] == "en" and c["user_name"] == "Alpho"
            c.update(voice_lang="fr", onboarded=False)
            if empty or not ok:
                raise RuntimeError(f"réponses vides : {empty} ; accueil OK : {ok}")
            return f"{len(phrases)} phrases comprises ; accueil OK"
        step("assistant", assistant_test)

        def actions_test():
            cases = {"ouvre le dossier téléchargements": "Téléchargements", "cherche recette de crêpes": "crêpes",
                     "ouvre la corbeille": "corbeille", "libère la mémoire": "mémoire"}
            bad = {q: r for q, r in ((q, app.answer(q, act=False)) for q in cases) if cases[q].lower() not in r.lower()}
            if bad:
                raise AssertionError(f"réponses inattendues : {bad}")
            return f"{len(cases)} actions comprises"
        step("actions de l'assistant", actions_test)

        def neural_test():
            if not voicemod.neural_ok():
                return "module absent (voix hors ligne utilisée)"
            try:
                path = voicemod._neural_file("Bonjour.", "fr-FR-VivienneMultilingualNeural", 185)
            except BaseException as ex:  # noqa: BLE001  hors ligne : la voix installée prend le relais
                return f"injoignable ({type(ex).__name__}) : voix hors ligne utilisée"
            return f"Vivienne, {os.path.getsize(path)} octets"
        step("voix neuronale", neural_test)

        def wake_match_test():
            cases = {"Pablo, quelle heure est-il": (True, "quelle heure est-il"), "Dis Pablo la météo": (True, "la météo"),
                     "Tableau où en est ma batterie": (True, "où en est ma batterie"), "Pablo": (True, ""),
                     "Le tableau est beau": (False, ""), "On mange quoi ce soir": (False, "")}
            bad = {k: assistant.match_name(k, "Pablo", ["tableau"]) for k, v in cases.items()
                   if assistant.match_name(k, "Pablo", ["tableau"]) != v}
            if bad or app.wake.running:
                raise RuntimeError(f"activation vocale : {bad}, écoute active pendant l'autotest : {app.wake.running}")
            return f"{len(cases)} phrases correctement triées"
        step("activation par la voix (nom)", wake_match_test)
        step("voix françaises", lambda: len(voicemod.french_voices()))
        step("cartes macOS", cards_test)
        step("données Mac", lambda: {"batterie": macdata.battery_details(), "thermique": mac_native.thermal_state(),
                                      "accent": mac_native.system_accent(), "sombre": mac_native.system_is_dark(),
                                      "processus": len(macdata.ProcSampler().top(3))})
        step("fond d'écran vivant", lambda: wallpaper_dynamic.compose(
            base_path=wallpapers.list_wallpapers()[0][1], size=(800, 500), slot="soir", state="cpu",
            stats=[("CPU", 90), ("RAM", 50), ("DISQUE", 20)]).size)
        step("barre des menus / raccourci", lambda: (app.cards.menubar.ok if app.cards.menubar else None,
                                                    mac_native.register_hotkey("cmd+alt+d", lambda: None)))
        step("ouverture des paramètres", lambda: app.open_settings())
        for key, *_ in app.settings_win.pages():
            step(f"page « {key} »", lambda k=key: (app.settings_win.show(k), app.root.update(),
                                                   len(app.settings_win.content.winfo_children()))[2])
        if IS_WIN:   # fonctions adaptées à Windows (voix naturelles, reconnaissance hors ligne)
            def win_voice():
                import asyncio
                import voice as vm
                names = vm.voices(c["voice_lang"])
                wav = asyncio.run(vm._onecore_wav("Test", vm.default_voice(c["voice_lang"]), 185))                     if vm._onecore() else b""
                return f"{len(names)} voix, par défaut {vm.default_voice(c['voice_lang'])}, synthèse {len(wav)} octets"
            step("voix Windows (naturelles)", win_voice)

            def win_recognition():
                """Phrases dites par la voix de synthèse, reconnues par le moteur de Windows (sans micro)."""
                import asyncio
                import voice as vm
                if not vm._onecore():
                    return "voix OneCore absentes : test sauté"
                rec = subprocess.run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; "
                                      "[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | "
                                      "ForEach-Object { $_.Culture.Name }"], capture_output=True, timeout=60,
                                     creationflags=no_window_flags()).stdout.decode("utf-8", "ignore").split()
                if not any(r.startswith("fr") for r in rec):
                    return f"moteur de reconnaissance français absent ({', '.join(rec) or 'aucun'}) : test sauté"
                fr_voice = vm.offline_voice("fr")   # voix installée (la voix neuronale ne sert pas à fabriquer le WAV)
                results = []
                for phrase, want in (("Quelle heure est-il", "time"), ("Jarvis, ma batterie", "wake")):
                    path = str(tmp / "phrase.wav")
                    Path(path).write_bytes(asyncio.run(vm._onecore_wav(phrase, fr_voice, 185)))
                    full = app.wake._win_script("fr", "Jarvis", ())
                    script = full[:full.index("$parent =")].replace(
                        "$r.SetInputToDefaultAudioDevice();", f"$r.SetInputToWaveFile({assistant._ps_quote(path)});") +                         "$res = $r.Recognize(); if ($res) { [Console]::Out.WriteLine($res.Grammar.Name + \"`t\" + $res.Text) }"
                    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                                         timeout=60, creationflags=no_window_flags()).stdout.decode("utf-8", "ignore")
                    grammar, _, text = out.strip().partition("	")
                    ok = (grammar == "wake") if want == "wake" else assistant.parse(text) == want
                    if not ok:
                        raise RuntimeError(f"« {phrase} » compris « {text} » ({grammar})")
                    results.append(text)
                return " / ".join(results)
            step("reconnaissance vocale Windows", win_recognition)
        step("thème du fond d'écran", lambda: bool(theme_from_wallpaper(
            wallpapers.list_wallpapers()[0][1])))
        root.after(500, finish)

    def finish():
        text = "\n".join(report) + ("\n\nERREURS :\n" + "\n".join(errors) if errors else "\n\nAucune erreur.")
        out = os.environ.get("DM_SELFTEST_OUT") or str(tmp / "selftest.txt")
        Path(out).write_text(text, encoding="utf-8")
        try:
            print(text, flush=True)
        except (OSError, AttributeError):  # application fenêtrée sans console
            pass
        app.organizer.shutdown()
        app.tray.stop()
        root.destroy()

    root.after(2500, run)
    root.mainloop()
    return 1 if errors else 0


def wake_test():
    args = sys.argv[sys.argv.index("--wake-test") + 1:]
    out, name = Path(args[0]), args[1]
    secs = int(args[2]) if len(args) > 2 else 45   # --wake-test SORTIE NOM [secondes] [variante1,variante2]
    root = tk.Tk()
    root.withdraw()
    lines = []

    def log(msg):
        lines.append(f"{time.strftime('%H:%M:%S')} {msg}")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    aliases = args[3].split(",") if len(args) > 3 else []
    w = assistant.WakeListener(get_name=lambda: name, get_lang=lambda: "fr", get_aliases=lambda: aliases,
                               on_wake=lambda cmd: log(f"RÉVEIL → commande : « {cmd} »"),
                               is_speaking=lambda: False, log=log)
    w.start()
    root.after(secs * 1000, lambda: (w.stop(), root.after(800, root.destroy)))
    root.mainloop()
    return 0


def speech_test():
    """--speech-test FICHIER SORTIE [fr|en] : transcrit un fichier audio.
    --mic-test SORTIE [fr|en] : écoute le micro quelques secondes. Le résultat est écrit dans SORTIE."""
    args = sys.argv[sys.argv.index("--speech-test" if "--speech-test" in sys.argv else "--mic-test") + 1:]
    mic = "--mic-test" in sys.argv
    out = Path(args[0] if mic else args[1])
    lang = (args[1] if mic else args[2]) if len(args) > (1 if mic else 2) else "fr"
    root = tk.Tk()
    root.withdraw()
    res = {}

    def done(text, err):
        res.update(text=text, err=err)

    if mic:
        listener = assistant.Listener()
        listener.record = []

        def ready():
            assistant.chime()
            Path(str(out) + ".ready").write_text("1")   # pour les tests automatiques : on peut parler
        root.after(500, lambda: listener.listen(lang, done, max_secs=12, on_ready=ready))
    else:
        assistant.transcribe_file(args[0], lang, done)

    def poll():
        if res:
            dbg = getattr(listener, "last_debug", {}) if mic else {}
            if mic and listener.record:
                import array
                import wave
                with wave.open(str(out) + ".wav", "wb") as w:   # le son capté, pour analyse
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(dbg.get("rate", 48000))
                    w.writeframes(array.array("h", (max(-32767, min(32767, int(v * 32767)))
                                                    for v in listener.record)).tobytes())
            extra = {k: dbg.get(k) for k in ("buffers", "format", "peak", "gen", "calls", "errors")} if dbg else {}
            out.write_text(f"texte : {res['text']}\nerreur : {res['err']}\ndiagnostic : {extra}\n", encoding="utf-8")
            root.destroy()
        else:
            root.after(100, poll)

    root.after(100, poll)
    root.after(90000, root.destroy)
    root.mainloop()
    return 0 if res.get("text") else 1


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
        sys.exit(selftest())
    if "--speech-test" in sys.argv or "--mic-test" in sys.argv:   # tests de la reconnaissance vocale
        sys.exit(speech_test())
    if "--wake-test" in sys.argv:   # --wake-test SORTIE NOM [secondes] : journal de l'écoute continue
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

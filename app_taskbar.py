# -*- coding: utf-8 -*-
"""Barre des tâches (Windows) : mesures à gauche de la zone de notification et barre colorée (couleur du fond
d'écran, des widgets ou au choix). La couleur passe par l'option officielle de Windows et est remise comme avant
dès qu'on choisit « Normale » ou qu'on ferme DeskMonitor."""
import ctypes
import os
import tkinter as tk
from tkinter import font as tkfont

from app_gamemode import fullscreen_app
from core import UI_FONT, _hwnd, fmt_bytes, is_packaged, log_exception, save_config

# fenêtres ouvertes depuis la barre (menu Démarrer, recherche, volets…) : les mesures ne passent pas devant
FLYOUTS = {"Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "ControlCenterWindow",
           "TopLevelWindowForOverflowXamlIsland", "NotifyIconOverflowWindow", "Shell_InputSwitchTopLevelWindow"}


class TaskbarMixin:
    tb_meter = None

    def _taskbar_loop(self):
        """Toutes les 200 ms : place les mesures sur la barre ; toutes les 3 s : couleur de la barre."""
        self._tb_n = getattr(self, "_tb_n", 0) + 1
        try:
            self._meter_tick()
            if self._tb_n % 15 == 1:
                self._color_tick()
        except Exception:  # noqa: BLE001
            log_exception("barre des tâches")
        self.root.after(200, self._taskbar_loop)

    # ----- mesures -------------------------------------------------------------------------------------
    def _meter_rows(self, mode):
        last = self.last or {}
        cpu = f"{last['cpu']:.0f} %" if "cpu" in last else "–"
        ram = f"{last['ram']:.0f} %" if "ram" in last else "–"
        down = f"{fmt_bytes(last['down'])}/s" if "down" in last else "–"
        up = f"{fmt_bytes(last['up'])}/s" if "up" in last else "–"
        hot = {cpu: last.get("cpu", 0) >= 90, ram: last.get("ram", 0) >= 90}
        rows = {"cpu_ram": [[("CPU", cpu)], [("RAM", ram)]],
                "net": [[("↓", down)], [("↑", up)]],
                "all": [[("CPU", cpu), ("↓", down)], [("RAM", ram), ("↑", up)]]}[mode]
        return rows, hot

    def _meter_build(self, mode, light):
        m = self.tb_meter
        if m and m["mode"] == mode and m["light"] == light and m["win"].winfo_exists():
            return m
        if m:
            m["win"].destroy()
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        key = "#202020"
        cv = tk.Canvas(win, bg=key, highlightthickness=0, bd=0, cursor="hand2")
        cv.pack(fill="both", expand=True)
        win.attributes("-transparentcolor", key)
        font, bold = (UI_FONT, 8), (UI_FONT, 8, "bold")
        sample_val = {"cpu_ram": ["100 %"], "net": [f"{fmt_bytes(999.9 * 1024 ** 2)}/s"],
                      "all": ["100 %", f"{fmt_bytes(999.9 * 1024 ** 2)}/s"]}[mode]
        f_lab, f_val = tkfont.Font(font=font), tkfont.Font(font=bold)
        cols, x = [], 0
        for s in sample_val:   # largeur fixe : rien ne bouge quand les chiffres changent
            lw = max(f_lab.measure(t) for t in ("CPU", "RAM", "↓", "↑")) + 5
            vw = f_val.measure(s)
            cols.append((x, x + lw + vw))
            x += lw + vw + 12
        fg, dim = ("#1b1b1b", "#5c5c5c") if light else ("#ffffff", "#b4b4b4")
        items = []
        for r in range(2):
            row = []
            for x0, x1 in cols:
                row.append((cv.create_text(x0, 0, anchor="w", font=font, fill=dim),
                            cv.create_text(x1, 0, anchor="e", font=bold, fill=fg)))
            items.append(row)
        menu = tk.Menu(win, tearoff=0)
        menu.add_command(label="Processus en cours", command=self.open_processes)
        menu.add_command(label="Paramètres de la barre des tâches", command=lambda: self.open_settings("general"))
        menu.add_separator()
        menu.add_command(label="Masquer les mesures", command=self._meter_off)
        cv.bind("<Button-1>", lambda e: self.open_processes())
        cv.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        self.tb_meter = m = {"win": win, "cv": cv, "items": items, "mode": mode, "light": light, "key": key,
                             "w": int(x - 12) + 4, "fg": fg, "hot": "#ff6b6b", "geo": None, "shown": False,
                             "hwnd": None, "font_h": f_val.metrics("linespace")}
        return m

    def _meter_off(self):
        self.cfg["taskbar_meter"] = "off"
        save_config(self.cfg)

    def _meter_hide(self):
        m = self.tb_meter
        if m and m["shown"]:
            m["win"].withdraw()
            m["shown"] = False

    def _meter_tick(self):
        mode = self.cfg.get("taskbar_meter", "off")
        if mode not in ("cpu_ram", "net", "all") or self.game_active:
            return self._meter_hide()
        import taskbar
        geo = taskbar.geometry()
        if not geo or geo["bar"][1] >= self.root.winfo_screenheight() - 3 or fullscreen_app():
            return self._meter_hide()   # barre masquée automatiquement, ou plein écran
        if mode != "all":
            self._tb_small = False
        elif getattr(self, "_tb_small", False):
            mode = "cpu_ram"   # pas assez de place pour tout : processeur et mémoire seulement
        m = self._meter_build(mode, taskbar.light_mode())
        win, cv = m["win"], m["cv"]
        left, top, right, bottom = geo["bar"]
        h, w = bottom - top, m["w"]
        if self._tb_n % 5 == 0 or not m["shown"]:
            # couleur réelle de la barre près de l'horloge : contours du texte nets, sans halo
            bg = taskbar.pixel(geo["tray_left"] - 3, top + h // 2)
            if bg and bg != m["key"]:
                cv.configure(bg=bg)
                win.attributes("-transparentcolor", bg)
                m["key"] = bg
        x = self._meter_spot(m, geo, w, h)
        if x is None:
            if mode == "all" and not m["shown"]:
                self._tb_small = True
            return self._meter_hide()
        if self._tb_n % 5 == 0 or not m["shown"]:
            rows, hot = self._meter_rows(mode)
            lh = m["font_h"]
            for r, row in enumerate(m["items"]):
                y = h // 2 + (r - 0.5) * (lh + 1)
                for c, (lab, val) in enumerate(row):
                    t_lab, t_val = rows[r][c]
                    cv.itemconfigure(lab, text=t_lab)
                    cv.itemconfigure(val, text=t_val, fill=m["hot"] if hot.get(t_val) else m["fg"])
                    cv.coords(lab, cv.coords(lab)[0], y)
                    cv.coords(val, cv.coords(val)[0], y)
        geo_s = f"{m['w']}x{h}+{x}+{top}"
        moved = geo_s != m["geo"]
        if moved:
            win.geometry(geo_s)
            m["geo"] = geo_s
        if not m["shown"]:
            win.deiconify()
            m["shown"] = True
            m["hwnd"] = _hwnd(win)
            moved = True
        fg = taskbar.foreground_class()
        if moved or fg == "Shell_TrayWnd" or (self._tb_n % 5 == 0 and fg not in FLYOUTS):
            # repasse au-dessus de la barre (qui remonte quand on clique dessus), sans prendre le focus
            ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(m["hwnd"]), ctypes.c_void_p(-1), 0, 0, 0, 0,
                                              0x0001 | 0x0002 | 0x0010)

    def _meter_spot(self, m, geo, w, h):
        """Place libre sur la barre : à gauche de la zone de notification, sinon tout à gauche de la barre."""
        import taskbar
        left, top = geo["bar"][0], geo["bar"][1]
        bottom, tray = geo["bar"][3], geo["tray_left"]
        spots = {"right": tray - w - 8, "left": left + 8}
        if m["shown"]:
            # déjà affichées : on vérifie seulement que des icônes n'arrivent pas juste à côté
            if self._tb_n % 5:
                return spots.get(m["side"])
            x = spots[m["side"]]
            near = (x - 10, x) if m["side"] == "right" else (x + w, x + w + 10)
            if taskbar.busy_columns(*near, top, bottom, m["key"]):
                m["side"] = None
                return None
            return x
        if self._tb_n % 10 and m.get("side") is None and m.get("scanned"):
            return None   # pas de place : nouvel essai toutes les 2 s
        m["scanned"] = True
        busy = taskbar.busy_columns(left, tray, top, bottom, m["key"])
        if not busy or busy[-1] < spots["right"] - 6:
            m["side"] = "right"
        elif busy[0] > spots["left"] + w + 6:
            m["side"] = "left"
        else:
            m["side"] = None
        return spots.get(m["side"])

    # ----- couleur de la barre -------------------------------------------------------------------------
    def _wall_color(self):
        import taskbar
        import wallpapers
        path = wallpapers.current_wallpaper()
        if not path or not os.path.isfile(path):
            return None
        sig = (path, os.path.getmtime(path))
        if getattr(self, "_tb_wall", (None, None))[0] != sig:
            self._tb_wall = (sig, taskbar.image_color(path))
        return self._tb_wall[1]

    def _color_tick(self):
        import taskbar
        c = self.cfg
        mode = c.get("taskbar_color", "off")
        want = None
        if mode != "off" and not is_packaged() and not taskbar.light_mode():
            want = (self._wall_color() if mode == "wallpaper" else
                    c["accent_color"] if mode == "accent" else mode if mode.startswith("#") else None)
        applied = c.get("taskbar_applied") or ""
        if want:
            if not c.get("taskbar_saved"):
                c["taskbar_saved"] = taskbar.save_state()
            # couleur du fond d'écran : seulement si elle change vraiment (fond vivant redessiné souvent)
            if not applied or taskbar.distance(applied, want) > (40 if mode == "wallpaper" else 0):
                taskbar.apply_color(want)
                c["taskbar_applied"] = want
                save_config(c)
        elif c.get("taskbar_saved"):
            self.restore_taskbar()

    def restore_taskbar(self):
        """Remet la barre des tâches exactement comme avant DeskMonitor."""
        c = self.cfg
        if c.get("taskbar_saved"):
            import taskbar
            taskbar.restore(c["taskbar_saved"])
            c["taskbar_saved"], c["taskbar_applied"] = None, ""
            save_config(c)

# -*- coding: utf-8 -*-
"""Alertes (seuils dépassés) et notifications à l'écran."""
import os
import shutil
import time

import tkinter as tk


import mac_native
from anim import ease_in as anim_ease_in

from i18n import tr
from core import (
    IS_WIN,
    TEXT_FONT,
    fmt_bytes,
    apply_corners,
    no_activate,
    IS_MAC,
)
if IS_WIN:
    import winsound


class AlertsMixin:
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
        title, msg = tr(title), tr(msg)   # aussi pour les notifications de Windows et de macOS
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

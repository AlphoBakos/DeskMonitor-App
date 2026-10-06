# -*- coding: utf-8 -*-
"""Fenêtre des processus : les programmes qui utilisent le plus le processeur."""
import queue
import threading
import time

import tkinter as tk
from tkinter import messagebox, ttk

import psutil

from settings_ui import UI, dark_titlebar
from optimizer import Optimizer

from core import (
    IS_WIN,
    APP_NAME,
    fmt_bytes,
)


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

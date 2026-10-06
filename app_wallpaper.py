# -*- coding: utf-8 -*-
"""Fonds d'écran, écran de verrouillage, fond assorti et fond d'écran vivant."""
import os
import threading
import time
from datetime import datetime
from pathlib import Path


import psutil

from profiles import theme_from_wallpaper, wallpaper_signature
import lockscreen
import wallpaper_dynamic
import wallpapers

from core import (
    IS_MAC,
)


class WallpaperMixin:
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

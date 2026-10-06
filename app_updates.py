# -*- coding: utf-8 -*-
"""Mises à jour : vérification sur GitHub, téléchargement et installation."""
import threading

from tkinter import messagebox


import updater

from core import (
    is_packaged,
    open_path,
    APP_NAME,
    APP_VERSION,
)


class UpdateMixin:
    def _update_loop(self):
        c = self.cfg
        if c["update_auto"] and c["update_repo"]:
            self.check_updates(False)
        self.root.after(24 * 3600 * 1000, self._update_loop)

    def check_updates(self, manual=False):
        if is_packaged():   # version Microsoft Store : les mises à jour passent par le Store
            if manual:
                open_path("ms-windows-store://downloadsandupdates")
            return
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

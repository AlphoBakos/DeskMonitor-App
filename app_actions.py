# -*- coding: utf-8 -*-
"""Actions d'entretien (cache, RAM, DNS, corbeille, alimentation) et retours des utilisateurs (GitHub)."""
from pathlib import Path

from tkinter import messagebox


from core import (
    APP_NAME,
    APP_VERSION,
    CONFIG_DIR,
    DEFAULTS,
)
from optimizer import Optimizer


class ActionsMixin:
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

    # ----- retours des utilisateurs --------------------------------------------
    def _issue_url(self, template, **fields):
        from urllib.parse import urlencode
        repo = self.cfg.get("update_repo") or DEFAULTS["update_repo"]
        return f"https://github.com/{repo}/issues/new?" + urlencode({"template": template, **fields})

    def report_problem(self):
        """Ouvre le formulaire « Signaler un problème » de GitHub, pré-rempli (version, système, dernières
        erreurs). Rien n'est envoyé : la personne relit puis valide elle-même dans son navigateur."""
        import platform
        import webbrowser
        log = ""
        try:
            lines = (CONFIG_DIR / "erreurs.log").read_text(encoding="utf-8", errors="replace").splitlines()
            log = "\n".join(lines[-40:])[-2500:]
        except OSError:
            pass
        home = str(Path.home())
        log = log.replace(home, "~").replace(home.replace("\\", "/"), "~")   # pas de nom d'utilisateur
        system = f"{platform.system()} {platform.release()} ({platform.machine()})"
        webbrowser.open(self._issue_url("probleme.yml", version=APP_VERSION,
                                        journal=f"Système : {system}\n\n{log or '(aucune erreur enregistrée)'}"))

    def suggest_idea(self):
        import webbrowser
        webbrowser.open(self._issue_url("idee.yml"))

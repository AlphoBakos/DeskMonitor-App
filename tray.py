# -*- coding: utf-8 -*-
"""
Icône de DeskMonitor dans la zone de notification (icônes cachées, à côté de l'horloge).

pystray tourne dans son propre thread : chaque clic est transmis à l'interface Tk
via app.call_soon(), qui l'exécute dans le thread principal.
"""

from core import APP_NAME, APP_VERSION, make_icon_image

import sys

# Sur macOS, pystray et Tk exigent tous deux le thread principal : on s'appuie
# à la place sur le Dock, ⌘, et la barre des menus (voir DeskWidget._setup_mac).
try:
    if sys.platform == "darwin":
        raise ImportError
    import pystray
    HAS_TRAY = True
except ImportError:  # pragma: no cover
    HAS_TRAY = False


class TrayIcon:
    def __init__(self, app):
        self.app = app
        self.icon = None
        if not HAS_TRAY:
            return
        self.icon = pystray.Icon(APP_NAME, self._image(), f"{APP_NAME} {APP_VERSION}", menu=self._menu())

    def _image(self):
        c = self.app.cfg
        return make_icon_image(64, c["accent_color"], c["bg_color"])

    def _do(self, fn, *args):
        """Crée un callback pystray qui exécute fn dans le thread Tk."""
        return lambda icon=None, item=None: self.app.call_soon(fn, *args)

    def _menu(self):
        app = self.app
        M, S = pystray.Menu, pystray.Menu.SEPARATOR
        from i18n import tr

        def I(text, *args, **kw):   # libellés recalculés à chaque ouverture : suivent la langue de l'interface
            if callable(text):
                return pystray.MenuItem(lambda item, f=text: tr(f(item)), *args, **kw)
            return pystray.MenuItem(lambda item, t=text: tr(t), *args, **kw)

        def profiles():
            names = app.profiles.names()
            if not names:
                return (I("Aucun profil enregistré", None, enabled=False),)
            return tuple(I(n, self._do(app.apply_profile, n),
                           checked=lambda item, n=n: app.cfg.get("profile") == n, radio=True) for n in names)

        return M(
            I("⚙  Paramètres", self._do(app.open_settings), default=True),
            I(lambda item: "Afficher les widgets" if app.cfg["widgets_hidden"] else "Masquer les widgets",
              self._do(app.toggle_widgets)),
            S,
            I("Actions rapides", M(
                I("🧹  Nettoyer le cache", self._do(app.action_clean)),
                I("🧠  Libérer la RAM", self._do(app.action_ram)),
                I("⚡  Tout optimiser", self._do(app.action_boost)),
                I("🌐  Vider le cache DNS", self._do(app.action_dns)),
                I("📊  Processus / CPU…", self._do(app.open_processes)),
            )),
            I("Profils", M(profiles)),
            I("Ranger tout le bureau", self._do(app.tidy_desktop)),
            I("Bureau organisé", self._do(app.toggle, "org_enabled"),
              checked=lambda item: bool(app.cfg["org_enabled"])),
            I("Toujours au premier plan", self._do(app.toggle, "topmost"),
              checked=lambda item: bool(app.cfg["topmost"])),
            S,
            I("Rechercher une mise à jour", self._do(app.check_updates, True)),
            I("Quitter", self._do(app.quit)),
        )

    def start(self):
        if self.icon is not None:
            self.icon.run_detached()

    def refresh(self):
        """Met à jour l'image (couleurs du thème) et les coches du menu."""
        if self.icon is None:
            return
        try:
            self.icon.icon = self._image()
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def set_tooltip(self, text):
        """Texte de l'infobulle de l'icône (Windows : 127 caractères au plus)."""
        if self.icon is not None:
            try:
                self.icon.title = text[:127]
            except Exception:  # noqa: BLE001
                pass

    def notify(self, title, msg):
        if self.icon is not None:
            try:
                self.icon.notify(msg, title)
            except Exception:  # noqa: BLE001
                pass

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass

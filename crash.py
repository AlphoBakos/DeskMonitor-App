# -*- coding: utf-8 -*-
"""Rapports de plantage : DeskMonitor note ses plantages sur l'ordinateur et, au lancement suivant, propose
d'envoyer un rapport. Rien ne part sans l'accord de la personne (elle relit le formulaire avant de l'envoyer)."""
import faulthandler
import traceback
from datetime import datetime

import core

_native = None


def _dir():
    return core.CONFIG_DIR   # lu à chaque fois : l'autotest le remplace par un dossier temporaire


def record(text, context):
    """Ajoute un plantage à plantage.txt (lu puis effacé au lancement suivant)."""
    try:
        _dir().mkdir(parents=True, exist_ok=True)
        with open(_dir() / "plantage.txt", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] v{core.APP_VERSION} {context}\n{text.strip()}\n\n")
    except OSError:
        pass


def record_exc(exc_info, context="erreur non gérée"):
    record("".join(traceback.format_exception(*exc_info)), context)


def install():
    """À l'ouverture. Si la séance précédente ne s'est pas fermée normalement ET qu'une erreur fatale
    (Python ou Tk) a été écrite, c'est un plantage. Un arrêt du PC sans erreur n'en est pas un."""
    global _native
    d = _dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        running, native = d / "seance-en-cours", d / "plantage-natif.log"
        if running.exists() and native.exists():
            text = native.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                record(text[-3000:], "arrêt brutal")
        running.write_text("1", encoding="utf-8")
        _native = open(native, "w", encoding="utf-8")
        faulthandler.enable(_native)
    except OSError:
        pass


def closed_normally():
    """À la fermeture normale de l'application."""
    global _native
    try:
        faulthandler.disable()
        if _native:
            _native.close()
            _native = None
        (_dir() / "seance-en-cours").unlink(missing_ok=True)
    except OSError:
        pass


def pending():
    """Texte des plantages pas encore proposés, ou chaîne vide."""
    try:
        return (_dir() / "plantage.txt").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def clear():
    try:
        (_dir() / "plantage.txt").unlink(missing_ok=True)
    except OSError:
        pass

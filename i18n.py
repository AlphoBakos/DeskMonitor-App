# -*- coding: utf-8 -*-
"""Langue de l'interface. Le code est écrit en français ; en anglais, chaque texte affiché passe par tr(), qui
cherche sa traduction dans i18n_en.json (texte français exact → texte anglais).

install() branche tr() sur les widgets Tk (libellés, boutons, menus, boîtes de dialogue, titres de fenêtres) :
la plupart des textes sont traduits sans toucher au reste du code. Les textes qui contiennent une valeur
(« 3 raccourcis masqués ») utilisent un modèle : tr("{n} raccourci(s) masqué(s)").format(n=3).

Collecte des textes non traduits : DM_I18N_COLLECT=fichier.json (écrit à la fermeture du programme)."""
import atexit
import json
import os
import sys
from pathlib import Path

_lang = "fr"
_en = {}
_missing = set()
_COLLECT = os.environ.get("DM_I18N_COLLECT")


def _data_file():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))   # application construite : _MEIPASS
    return base / "i18n_en.json"


_patterns = []    # modèles « … {} … » : textes qui contiennent une valeur
_cache = {}


def _load():
    global _en, _patterns
    import re
    try:
        _en = json.loads(_data_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _en = {}
    _patterns = []
    for fr, en in _en.items():
        if "{}" in fr:
            rx = "^" + re.escape(fr).replace(r"\{\}", "(.+?)") + "$"
            _patterns.append((re.compile(rx, re.S), en))
    _cache.clear()


def _from_pattern(text):
    """« Le CPU est à 96 % … » → modèle « Le CPU est à {} % … » → traduction avec les mêmes valeurs."""
    if text in _cache:
        return _cache[text]
    out = None
    for rx, en in _patterns:
        m = rx.match(text)
        if m:
            out = en.format(*m.groups())
            break
    if len(_cache) > 2000:
        _cache.clear()
    _cache[text] = out
    return out


def set_lang(lang):
    global _lang
    _lang = "en" if lang == "en" else "fr"
    if _lang == "en" and not _en:
        _load()


def lang():
    return _lang


def tr(text):
    """Texte dans la langue de l'interface (inchangé en français, ou si aucune traduction n'existe)."""
    if _lang == "fr" or not isinstance(text, str) or not text.strip():
        return text
    out = _en.get(text)
    if out is None and _patterns:
        out = _from_pattern(text)
    if out is None:
        if _COLLECT and any(ch.isalpha() for ch in text):
            _missing.add(text)
        return text
    return out


def _save_missing():
    if _COLLECT and _missing:
        try:
            old = json.loads(Path(_COLLECT).read_text(encoding="utf-8")) if Path(_COLLECT).exists() else []
        except (OSError, ValueError):
            old = []
        Path(_COLLECT).write_text(json.dumps(sorted(set(old) | _missing), ensure_ascii=False, indent=1),
                                  encoding="utf-8")


atexit.register(_save_missing)


# --------------------------------------------------------------------------- #
#  Points d'accroche Tk
# --------------------------------------------------------------------------- #
_installed = False


def _tr_kw(kw, keys=("text", "label")):
    for k in keys:
        if k in kw:
            kw[k] = tr(kw[k])
    return kw


def install():
    """Traduit automatiquement les textes des widgets Tk (une seule fois)."""
    global _installed
    if _installed:
        return
    _installed = True
    import tkinter as tk
    from tkinter import messagebox, ttk

    def patch_widget(cls, with_cnf):
        init, conf = cls.__init__, cls.configure

        if with_cnf:   # widgets Tk classiques : __init__(master, cnf={}, **kw)
            def __init__(self, master=None, cnf=None, **kw):
                init(self, master, _tr_kw(dict(cnf)) if cnf else {}, **_tr_kw(kw))
        else:          # widgets ttk : __init__(master, **kw)
            def __init__(self, master=None, **kw):
                init(self, master, **_tr_kw(kw))

        def configure(self, cnf=None, **kw):
            if isinstance(cnf, dict):
                cnf = _tr_kw(dict(cnf))
            return conf(self, cnf, **_tr_kw(kw))
        cls.__init__, cls.configure, cls.config = __init__, configure, configure

    for cls in (tk.Label, tk.Button, tk.Checkbutton, tk.Radiobutton, tk.LabelFrame, tk.Message):
        patch_widget(cls, True)
    for cls in (ttk.Label, ttk.Button, ttk.Checkbutton, ttk.Radiobutton, ttk.LabelFrame):
        patch_widget(cls, False)

    for name in ("add_command", "add_cascade", "add_checkbutton", "add_radiobutton"):
        orig = getattr(tk.Menu, name)

        def add(self, cnf=None, _orig=orig, **kw):
            if isinstance(cnf, dict):
                cnf = _tr_kw(dict(cnf))
            return _orig(self, cnf, **_tr_kw(kw))
        setattr(tk.Menu, name, add)
    entry_conf = tk.Menu.entryconfigure

    def entryconfigure(self, index, cnf=None, **kw):
        return entry_conf(self, index, cnf, **_tr_kw(kw))
    tk.Menu.entryconfigure = tk.Menu.entryconfig = entryconfigure

    wm_title = tk.Wm.wm_title

    def title(self, string=None):
        return wm_title(self, tr(string) if string is not None else None)
    tk.Wm.wm_title = tk.Wm.title = title

    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion",
                 "askretrycancel", "askyesnocancel"):
        orig = getattr(messagebox, name)

        def box(title=None, message=None, _orig=orig, **options):
            return _orig(tr(title), tr(message), **options)
        setattr(messagebox, name, box)

# -*- coding: utf-8 -*-
"""Premier lancement : prénom, langue et nom de l'assistant. Modifiables ensuite dans Paramètres > Assistant."""
import sys
import tkinter as tk

from core import APP_NAME, IS_MAC, NUM_FONT, TEXT_FONT, save_config
from settings_ui import UI, FlatButton, dark_titlebar

TEXTS = {
    "fr": {"title": "Faisons connaissance", "sub": "Votre assistant veille sur l'ordinateur et vous parle.",
           "name": "Votre prénom", "lang": "Langue de l'assistant", "assistant": "Nom de votre assistant",
           "hint": "Vous pourrez tout changer plus tard dans Paramètres, Assistant.", "go": "Commencer",
           "missing": "Indiquez votre prénom pour que l'assistant puisse vous appeler."},
    "en": {"title": "Let's get acquainted", "sub": "Your assistant watches over this computer and talks to you.",
           "name": "Your first name", "lang": "Assistant language", "assistant": "Your assistant's name",
           "hint": "You can change all of this later in Settings, Assistant.", "go": "Get started",
           "missing": "Enter your first name so the assistant knows what to call you."},
}


class Onboarding:
    def __init__(self, app, on_done):
        self.app, self.cfg, self.on_done = app, app.cfg, on_done
        self.lang = self.cfg.get("voice_lang", "fr")
        accent = app.cards.accent if app.cards.active else self.cfg["accent_color"]
        self.accent = accent
        w = self.win = tk.Toplevel(app.root)
        w.title(APP_NAME)
        w.configure(bg=UI["bg"])
        w.resizable(False, False)
        w.attributes("-topmost", True)
        dark_titlebar(w)
        # Windows : le texte grandit avec le zoom de l'écran (125 %, 150 %…) ; la fenêtre suit
        self.k = 1.0 if sys.platform == "darwin" else max(1.0, w.winfo_fpixels("1i") / 96.0)
        w.protocol("WM_DELETE_WINDOW", self.skip)
        self.name_var = tk.StringVar(w, self.cfg.get("user_name", ""))
        self.asst_var = tk.StringVar(w, self.cfg.get("assistant_name", "Jarvis"))
        self.build()
        w.after(200, lambda: self.name_entry.focus_force())

    def t(self, key):
        return TEXTS[self.lang][key]

    def build(self):
        for ch in self.win.winfo_children():
            ch.destroy()
        body = tk.Frame(self.win, bg=UI["bg"], padx=44, pady=36)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=self.t("title"), bg=UI["bg"], fg=UI["text"], font=(TEXT_FONT, 26, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(body, text=self.t("sub"), bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 13), anchor="w",
                 justify="left", wraplength=int(430 * self.k)).pack(fill="x", pady=(4, 26))

        self.name_entry = self._field(body, self.t("name"), self.name_var)

        tk.Label(body, text=self.t("lang"), bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 12),
                 anchor="w").pack(fill="x", pady=(18, 6))
        pills = tk.Frame(body, bg=UI["bg"])
        pills.pack(fill="x")
        for code, label in (("fr", "Français"), ("en", "English")):
            sel = code == self.lang
            p = tk.Label(pills, text=label, cursor="hand2", padx=18, pady=8, font=(TEXT_FONT, 13, "bold" if sel else
                                                                                    "normal"),
                         bg=self.accent if sel else UI["card2"], fg="#FFFFFF" if sel else UI["text"])
            p.pack(side="left", padx=(0, 8))
            p.bind("<Button-1>", lambda e, c=code: self._set_lang(c))

        self._field(body, self.t("assistant"), self.asst_var, top=18)

        tk.Label(body, text=self.t("hint"), bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 11), anchor="w",
                 justify="left", wraplength=int(430 * self.k)).pack(fill="x", pady=(22, 0))
        self.err = tk.Label(body, text="", bg=UI["bg"], fg="#FF5D4F", font=(TEXT_FONT, 11), anchor="w")
        self.err.pack(fill="x", pady=(6, 0))
        btn = FlatButton(body, self.t("go"), self.finish, self.accent, primary=True)
        btn.configure(font=(TEXT_FONT, 14, "bold"), pady=10)
        btn.pack(fill="x", pady=(14, 0))
        self.win.bind("<Return>", lambda e: self.finish())
        # taille d'après le contenu réel : le bouton n'est jamais coupé, quel que soit le zoom de l'écran
        w = self.win
        w.update_idletasks()
        W, H = int(520 * self.k), w.winfo_reqheight()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2)}")

    def _field(self, parent, label, var, top=0):
        tk.Label(parent, text=label, bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 12), anchor="w").pack(
            fill="x", pady=(top, 6))
        box = tk.Frame(parent, bg=UI["field"], highlightthickness=1, highlightbackground=UI["line"],
                       highlightcolor=self.accent)
        box.pack(fill="x")
        e = tk.Entry(box, textvariable=var, bg=UI["field"], fg=UI["text"], insertbackground=self.accent,
                     relief="flat", highlightthickness=0, bd=0, font=(TEXT_FONT, 16))
        e.pack(fill="x", padx=12, ipady=8)
        return e

    def _set_lang(self, code):
        self.lang = code
        self.build()

    def skip(self):
        """Fenêtre fermée sans valider : on ne redemande pas, tout reste modifiable dans les paramètres."""
        self.cfg.update(onboarded=True, voice_lang=self.lang)
        save_config(self.cfg)
        self.win.destroy()

    def finish(self):
        name = " ".join(self.name_var.get().split()).strip()
        if not name:
            self.err.configure(text=self.t("missing"))
            self.name_entry.focus_set()
            return
        self.cfg.update(user_name=name[:40], voice_lang=self.lang,
                        assistant_name=(" ".join(self.asst_var.get().split()) or "Jarvis")[:30], onboarded=True)
        save_config(self.cfg)
        self.win.destroy()
        self.on_done()

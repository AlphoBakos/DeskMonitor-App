# -*- coding: utf-8 -*-
"""Premier lancement : un court parcours en 5 écrans (connaissance, style, bureau, assistant, gestes utiles).
Tout reste modifiable ensuite dans les paramètres. Les choix de style s'appliquent en direct sur le bureau."""
import sys
import tkinter as tk

from core import APP_NAME, IS_MAC, IS_WIN, TEXT_FONT, is_autostart, save_config, set_autostart
from settings_ui import UI, FlatButton, Toggle, dark_titlebar

ACCENTS = ["#6E8BFF", "#2FB5A5", "#E0567A", "#F2A33A", "#9B6CFF"]

TEXTS = {
    "fr": {
        "next": "Continuer", "back": "Retour", "go": "C'est parti", "skip": "Passer",
        "step": "Étape {} sur {}",
        "t1": "Bienvenue dans DeskMonitor", "s1": "Quelques réglages rapides, et votre bureau est prêt.",
        "name": "Votre prénom", "lang": "Langue", "missing": "Indiquez votre prénom pour que l'assistant puisse vous appeler.",
        "t2": "Votre style", "s2": "Les widgets changent en direct derrière cette fenêtre.",
        "theme": "Thème", "auto": "Automatique", "dark": "Sombre", "light": "Clair",
        "accent": "Couleur", "system": "Celle de Windows" if IS_WIN else "Celle du système",
        "layout": "Disposition", "cards": "Cartes", "minimal": "Heure seule", "classic": "Colonne",
        "t3": "Votre bureau", "s3": "DeskMonitor peut aussi ranger vos applications.",
        "org": "Ranger mes applications dans des panneaux",
        "org_d": "Internet, Bureautique, Jeux… Aucun fichier n'est déplacé.",
        "auto_start": "Lancer DeskMonitor à l'ouverture de session",
        "auto_start_d": "Vos widgets sont là dès que l'ordinateur démarre.",
        "t4": "Votre assistant", "s4": "Il vous répond, ouvre vos applications et cherche pour vous.",
        "asst": "Nom de l'assistant", "voice": "Annonces vocales",
        "voice_d": "Récapitulatif au démarrage, alerte si la machine souffre.",
        "wake": "Activation par la voix",
        "wake_d": "Dites son nom pour lui parler. Le micro reste à l'écoute, hors ligne. Désactivé par défaut.",
        "examples": "Essayez : « {a}, ouvre Chrome » · « cherche une recette » · « fais le point » · « range le bureau »",
        "t5": "Bon à savoir", "s5": "Quatre gestes pour tout maîtriser.",
        "tips": [("Clic droit", "sur un widget : le menu et les paramètres."),
                 ("Survol", "d'une carte : des actions rapides (nettoyer, libérer la RAM…)."),
                 ("Glisser", "une carte pour la déplacer : les autres s'écartent."),
                 ("{hide}", "affiche ou masque tous les widgets ; {talk} pour parler à l'assistant.")],
    },
    "en": {
        "next": "Continue", "back": "Back", "go": "Let's go", "skip": "Skip",
        "step": "Step {} of {}",
        "t1": "Welcome to DeskMonitor", "s1": "A few quick settings and your desktop is ready.",
        "name": "Your first name", "lang": "Language", "missing": "Enter your first name so the assistant knows what to call you.",
        "t2": "Your style", "s2": "The widgets update live behind this window.",
        "theme": "Theme", "auto": "Automatic", "dark": "Dark", "light": "Light",
        "accent": "Color", "system": "Windows accent" if IS_WIN else "System accent",
        "layout": "Layout", "cards": "Cards", "minimal": "Clock only", "classic": "Column",
        "t3": "Your desktop", "s3": "DeskMonitor can also tidy up your apps.",
        "org": "Group my apps into panels",
        "org_d": "Internet, Office, Games… No file is moved.",
        "auto_start": "Start DeskMonitor when I sign in",
        "auto_start_d": "Your widgets are there as soon as the computer starts.",
        "t4": "Your assistant", "s4": "It answers you, opens your apps and searches for you.",
        "asst": "Assistant's name", "voice": "Spoken announcements",
        "voice_d": "A summary at startup, a warning when the computer struggles.",
        "wake": "Voice activation",
        "wake_d": "Say its name to talk to it. The microphone keeps listening, offline. Off by default.",
        "examples": "Try: \"{a}, open Chrome\" · \"search for a recipe\" · \"give me a summary\" · \"tidy the desktop\"",
        "t5": "Good to know", "s5": "Four gestures to master everything.",
        "tips": [("Right-click", "a widget: menu and settings."),
                 ("Hover", "a card: quick actions (clean up, free memory…)."),
                 ("Drag", "a card to move it: the others make room."),
                 ("{hide}", "shows or hides all widgets; {talk} to talk to the assistant.")],
    },
}
STEPS = 5


class Onboarding:
    def __init__(self, app, on_done):
        self.app, self.cfg, self.on_done = app, app.cfg, on_done
        self.lang = self.cfg.get("voice_lang", "fr")
        self.step = 1
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
        # choix proposés (appliqués à la fin pour le bureau, en direct pour le style)
        self.org = True
        self.autostart = is_autostart()
        self.build()

    # ----- outils -------------------------------------------------------------
    @property
    def accent(self):
        # la couleur choisie ; sinon le bleu de DeskMonitor (l'accent de Windows peut être gris : boutons ternes)
        return self.cfg["accent_color"] if self.cfg["accent_mode"] == "custom" else ACCENTS[0]

    def t(self, key):
        return TEXTS[self.lang][key]

    def _title(self, body, title, sub):
        tk.Label(body, text=self.t("step").format(self.step, STEPS), bg=UI["bg"], fg=self.accent,
                 font=(TEXT_FONT, 11, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, text=title, bg=UI["bg"], fg=UI["text"], font=(TEXT_FONT, 24, "bold"), anchor="w").pack(
            fill="x", pady=(4, 0))
        tk.Label(body, text=sub, bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 13), anchor="w", justify="left",
                 wraplength=int(470 * self.k)).pack(fill="x", pady=(4, 22))

    def _label(self, parent, text, top=0):
        tk.Label(parent, text=text, bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 12), anchor="w").pack(
            fill="x", pady=(top, 6))

    def _pills(self, parent, options, current, on_pick, swatch=False):
        row = tk.Frame(parent, bg=UI["bg"])
        row.pack(fill="x")
        for value, label in options:
            sel = value == current
            if swatch:   # pastille de couleur
                p = tk.Label(row, text="✓" if sel else " ", width=3, cursor="hand2", pady=6,
                             font=(TEXT_FONT, 12, "bold"), bg=value, fg="#FFFFFF")
            else:
                p = tk.Label(row, text=label, cursor="hand2", padx=16, pady=7,
                             font=(TEXT_FONT, 12, "bold" if sel else "normal"),
                             bg=self.accent if sel else UI["card2"], fg="#FFFFFF" if sel else UI["text"])
            p.pack(side="left", padx=(0, 8))
            p.bind("<Button-1>", lambda e, v=value: on_pick(v))
        return row

    def _field(self, parent, label, var, top=0):
        self._label(parent, label, top)
        box = tk.Frame(parent, bg=UI["field"], highlightthickness=1, highlightbackground=UI["line"],
                       highlightcolor=self.accent)
        box.pack(fill="x")
        e = tk.Entry(box, textvariable=var, bg=UI["field"], fg=UI["text"], insertbackground=self.accent,
                     relief="flat", highlightthickness=0, bd=0, font=(TEXT_FONT, 16))
        e.pack(fill="x", padx=12, ipady=8)
        return e

    def _switch(self, parent, title, desc, value, command, top=14):
        row = tk.Frame(parent, bg=UI["card"], padx=16, pady=12)
        row.pack(fill="x", pady=(top, 0))
        txt = tk.Frame(row, bg=UI["card"])
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=title, bg=UI["card"], fg=UI["text"], font=(TEXT_FONT, 13, "bold"), anchor="w").pack(fill="x")
        tk.Label(txt, text=desc, bg=UI["card"], fg=UI["muted"], font=(TEXT_FONT, 11), anchor="w", justify="left",
                 wraplength=int(360 * self.k)).pack(fill="x")
        Toggle(row, value, command, self.accent, UI["card"]).pack(side="right", padx=(12, 0))

    def _live(self, **changes):
        """Applique un choix de style tout de suite : on voit les widgets changer derrière la fenêtre."""
        self.cfg.update(**changes)
        self.app.schedule_rebuild()
        self.win.after(250, self.build)

    # ----- écrans --------------------------------------------------------------
    def build(self):
        for ch in self.win.winfo_children():
            ch.destroy()
        body = tk.Frame(self.win, bg=UI["bg"], padx=44, pady=32)
        body.pack(fill="both", expand=True)
        getattr(self, f"_step{self.step}")(body)
        self.err = tk.Label(body, text="", bg=UI["bg"], fg="#FF5D4F", font=(TEXT_FONT, 11), anchor="w")
        self.err.pack(fill="x", pady=(10, 0))
        self._nav(body)
        w = self.win
        w.update_idletasks()   # taille d'après le contenu réel, quel que soit le zoom de l'écran
        W, H = int(560 * self.k), w.winfo_reqheight()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2)}")

    def _nav(self, body):
        nav = tk.Frame(body, bg=UI["bg"])
        nav.pack(fill="x", pady=(8, 0))
        dots = tk.Frame(nav, bg=UI["bg"])
        dots.pack(side="left")
        for i in range(1, STEPS + 1):   # progression
            tk.Frame(dots, bg=self.accent if i <= self.step else UI["off"], width=int((22 if i == self.step else 8)
                                                                                    * self.k),
                     height=int(8 * self.k)).pack(side="left", padx=3)
        last = self.step == STEPS
        btn = FlatButton(nav, self.t("go") if last else self.t("next"), self.finish if last else self.next,
                         self.accent, primary=True)
        btn.configure(font=(TEXT_FONT, 13, "bold"), pady=8, padx=22)
        btn.pack(side="right")
        if self.step > 1:
            FlatButton(nav, self.t("back"), self.back, self.accent).pack(side="right", padx=(0, 8))
        else:
            FlatButton(nav, self.t("skip"), self.skip, self.accent).pack(side="right", padx=(0, 8))
        self.win.bind("<Return>", lambda e: (self.finish() if last else self.next()))

    def _step1(self, body):
        self._title(body, self.t("t1"), self.t("s1"))
        self.name_entry = self._field(body, self.t("name"), self.name_var)
        self.win.after(150, lambda: self.name_entry.winfo_exists() and self.name_entry.focus_force())
        self._label(body, self.t("lang"), top=18)
        self._pills(body, [("fr", "Français"), ("en", "English")], self.lang, self._set_lang)

    def _step2(self, body):
        self._title(body, self.t("t2"), self.t("s2"))
        c = self.cfg
        self._label(body, self.t("theme"))
        self._pills(body, [("auto", self.t("auto")), ("dark", self.t("dark")), ("light", self.t("light"))],
                    c["mac_theme"], lambda v: self._live(mac_theme=v))
        self._label(body, self.t("accent"), top=16)
        row = self._pills(body, [(a, "") for a in ACCENTS], c["accent_color"] if c["accent_mode"] == "custom" else None,
                          lambda v: self._live(accent_mode="custom", accent_color=v), swatch=True)
        sys_sel = c["accent_mode"] == "system"
        p = tk.Label(row, text=self.t("system"), cursor="hand2", padx=12, pady=7, font=(TEXT_FONT, 11, "bold" if sys_sel
                                                                                          else "normal"),
                     bg=self.accent if sys_sel else UI["card2"], fg="#FFFFFF" if sys_sel else UI["text"])
        p.pack(side="left")
        p.bind("<Button-1>", lambda e: self._live(accent_mode="system"))
        self._label(body, self.t("layout"), top=16)
        self._pills(body, [("cards", self.t("cards")), ("minimal", self.t("minimal")), ("classic", self.t("classic"))],
                    c["layout"], lambda v: self._live(layout=v))

    def _step3(self, body):
        self._title(body, self.t("t3"), self.t("s3"))
        self._switch(body, self.t("org"), self.t("org_d"), self.org, lambda v: setattr(self, "org", v), top=0)
        if IS_WIN or IS_MAC:
            self._switch(body, self.t("auto_start"), self.t("auto_start_d"), self.autostart,
                         lambda v: setattr(self, "autostart", v))

    def _step4(self, body):
        self._title(body, self.t("t4"), self.t("s4"))
        self._field(body, self.t("asst"), self.asst_var)
        c = self.cfg
        self._switch(body, self.t("voice"), self.t("voice_d"), c["voice_on"], lambda v: c.update(voice_on=v))
        if IS_WIN or IS_MAC:
            self._switch(body, self.t("wake"), self.t("wake_d"), c["wake_on"], lambda v: c.update(wake_on=v), top=8)
        asst = " ".join(self.asst_var.get().split()) or "Jarvis"
        tk.Label(body, text=self.t("examples").format(a=asst), bg=UI["bg"], fg=UI["muted"], font=(TEXT_FONT, 11),
                 anchor="w", justify="left", wraplength=int(470 * self.k)).pack(fill="x", pady=(14, 0))

    def _step5(self, body):
        self._title(body, self.t("t5"), self.t("s5"))
        def keys(spec):   # « ctrl+alt+d » → « Ctrl + Alt + D »
            return " + ".join(p.capitalize() for p in spec.split("+")) if spec else ""
        hide, talk = keys(self.cfg["card_hotkey"]), keys(self.cfg["listen_hotkey"])
        for head, text in self.t("tips"):
            row = tk.Frame(body, bg=UI["card"], padx=16, pady=10)
            row.pack(fill="x", pady=(0, 8))
            tk.Label(row, text=head.format(hide=hide, talk=talk), bg=UI["card"], fg=self.accent,
                     font=(TEXT_FONT, 12, "bold"), anchor="w", width=14).pack(side="left")
            tk.Label(row, text=text.format(hide=hide, talk=talk), bg=UI["card"], fg=UI["text"], font=(TEXT_FONT, 12),
                     anchor="w", justify="left", wraplength=int(300 * self.k)).pack(side="left", fill="x", expand=True)

    # ----- navigation --------------------------------------------------------------
    def _set_lang(self, code):
        self.lang = code
        self.cfg["voice_lang"] = code
        self.build()

    def _check_name(self):
        if not " ".join(self.name_var.get().split()):
            self.err.configure(text=self.t("missing"))
            self.name_entry.focus_set()
            return False
        return True

    def next(self):
        if self.step == 1 and not self._check_name():
            return
        self.step = min(STEPS, self.step + 1)
        self.build()

    def back(self):
        self.step = max(1, self.step - 1)
        self.build()

    def skip(self):
        """Fenêtre fermée sans aller au bout : on ne redemande pas, tout reste modifiable dans les paramètres."""
        self.cfg.update(onboarded=True, voice_lang=self.lang)
        save_config(self.cfg)
        self.win.destroy()

    def finish(self):
        c = self.cfg
        name = " ".join(self.name_var.get().split()).strip()
        c.update(user_name=name[:40], voice_lang=self.lang, onboarded=True, org_enabled=self.org,
                 assistant_name=(" ".join(self.asst_var.get().split()) or "Jarvis")[:30])
        try:
            if self.autostart != is_autostart():
                set_autostart(self.autostart)
        except OSError as ex:
            self.app.set_status(str(ex))
        save_config(c)
        self.win.destroy()
        self.app.build(force=True)
        self.app.root.after(1500, lambda: self.app.tidy_desktop(announce=False))   # tout bien rangé, sans chevauchement
        self.on_done()

# -*- coding: utf-8 -*-
"""Assistant vocal : écoute (raccourci, activation par le nom), compréhension et réponses, actions demandées."""
import threading
from datetime import datetime
from pathlib import Path


import actions
from organizer import collect_items
import mac_native
import macdata
import assistant

from core import (
    IS_WIN,
    format_date,
    log_exception,
    IS_MAC,
)


class AssistantMixin:
    # ----- Assistant ---------------------------------------------------------------
    def _setup_listen_hotkey(self):
        spec = self.cfg["listen_hotkey"].strip()
        if spec != self._listen_spec:
            self._listen_spec = spec
            mac_native.register_hotkey(spec, lambda: self.call_soon(self.listen), slot=2) if spec else \
                mac_native.unregister_hotkey(2)
        self.root.after(3000, self._setup_listen_hotkey)   # suit les changements faits dans les paramètres

    def hotkey_words(self, spec=None):
        """« cmd+alt+j » → « Commande Option J » (pour le dire à voix haute)."""
        spec = spec or self.cfg["listen_hotkey"]
        fr = {"cmd": "Commande", "alt": "Option" if IS_MAC else "Alt", "ctrl": "Contrôle", "shift": "Majuscule"}
        en = {"cmd": "Command", "alt": "Option" if IS_MAC else "Alt", "ctrl": "Control", "shift": "Shift"}
        names = en if self.cfg["voice_lang"] == "en" else fr
        return " ".join(names.get(p, p.upper()) for p in spec.lower().split("+"))

    def introduce(self):
        c, t = self.cfg, self._tr
        name, asst = c["user_name"].strip(), c["assistant_name"].strip() or "Jarvis"
        keys = self.hotkey_words()
        hi_fr, hi_en = (f"Enchanté, {name}." if name else "Enchanté."), (f"Nice to meet you, {name}." if name
                                                                         else "Nice to meet you.")
        self.speak(t(f"{hi_fr} Je suis {asst}. Je veille sur votre ordinateur et je vous préviens si "
                     f"quelque chose ne va pas. Pour me parler, appuyez sur {keys}.",
                     f"{hi_en} I'm {asst}. I'll keep an eye on this computer and let you know if "
                     f"anything goes wrong. To talk to me, press {keys}."), force=True)
        self.root.after(1500, lambda: self.speak_recap(force=True))

    def _wake_should_run(self):
        c = self.cfg
        if not (self.voice_ready and c["wake_on"] and (IS_MAC or IS_WIN)):
            return False
        b = self._battery()
        if c["wake_battery_off"] and b is not None and not b.power_plugged:
            return False
        if c["wake_night_off"] and c["voice_quiet"]:
            h, f, t = datetime.now().hour, int(c["voice_quiet_from"]), int(c["voice_quiet_to"])
            if (h >= f or h < t) if f > t else f <= h < t:
                return False
        return True

    def _wake_loop(self):
        """Démarre / arrête l'écoute continue selon les réglages, la batterie et l'heure."""
        try:
            want = self._wake_should_run()
            if want and not self.wake.running:
                self.wake.start()
            elif not want and self.wake.running:
                self.wake.stop()
        except Exception:  # noqa: BLE001
            log_exception("activation vocale")
        self.root.after(5000, self._wake_loop)

    def learn_name(self, rounds=3):
        """Apprend comment la reconnaissance écrit le nom de l'assistant avec votre voix (3 essais)."""
        c, t = self.cfg, self._tr
        asst = c["assistant_name"].strip() or "Jarvis"
        was_running = self.wake.running
        self.wake.stop()
        found = []

        def step(i):
            if i >= rounds:
                learned = [a for a in dict.fromkeys(found) if a]
                c["wake_aliases"] = list(dict.fromkeys(c["wake_aliases"] + learned))[-6:]
                self.save()
                msg = t(f"Merci. Je reconnaîtrai mon nom, même prononcé « {', '.join(learned)} ».",
                        f"Thanks. I'll recognize my name, even when it sounds like \"{', '.join(learned)}\".") \
                    if learned else t("Merci. Je vous entends bien dire mon nom.", "Thanks. I can hear my name clearly.")
                self.speak(msg, force=True)
                if was_running:
                    self.root.after(4000, self.wake.start)
                return
            self.speak(t(f"Dites mon nom après le signal : {asst}." if i == 0 else "Encore une fois.",
                         f"Say my name after the tone: {asst}." if i == 0 else "Once more."), force=True)

            def wait_voice():
                if self.voice.speaking():
                    self.root.after(150, wait_voice)
                    return

                def heard(text, err):
                    if text:
                        found.append(assistant.learn_alias(text, asst))
                        self.call_soon(self._toast, f"« {text} »")
                    self.call_soon(step, i + 1)
                self.listener.listen(c["voice_lang"], heard, max_secs=6, on_ready=assistant.chime, free_only=True)
            self.root.after(300, wait_voice)

        step(0)

    def _files_loop(self):
        self.files.refresh()
        self.root.after(600000, self._files_loop)

    def assistant_vocab(self):
        """Noms proposés au moteur de reconnaissance : applications installées et dossiers (Windows)."""
        if not IS_WIN:
            return None
        apps = sorted({a[0] for a in (self.organizer.apps or [])}) + list(actions.ALIASES)
        places = ["téléchargements", "documents", "bureau", "images", "photos", "musique", "vidéos", "corbeille",
                  "ce PC", "paramètres", "OneDrive", "dossier personnel"] + self.files.spoken_names(60)
        return {"apps": apps, "places": places}

    @staticmethod
    def _heure(h, m):
        """L'heure comme on la dit : « minuit vingt », « une heure », « midi et quart », « 15 heures 40 »."""
        word = {0: "minuit", 12: "midi"}.get(h) or ("une heure" if h == 1 else f"{h} heures")
        if not m:
            return word
        if m == 15:
            return word + " et quart"
        if m == 30:
            return word + " et demie"
        return f"{word} {m}"

    def _pick(self, *options):
        """Une formulation au hasard : l'assistant ne répète pas toujours la même phrase."""
        import random
        return random.choice(options)

    def _do_action(self, act, run=True):
        """Ouvre une application, un dossier, un fichier ou lance une recherche. Retourne la réponse parlée."""
        t = self._tr
        kind, target, extra = act
        if kind == "search":
            site = "" if extra == "google" else f" {t('sur', 'on')} {extra.title()}"
            if run:
                actions.open_target(actions.search_url(target, extra))
            return self._pick(t(f"Voici ce que j'ai trouvé pour {target}{site}.", f"Here's what I found for {target}{site}."),
                              t(f"Je lance la recherche : {target}{site}.", f"Searching for {target}{site}."),
                              t(f"C'est parti, je cherche {target}{site}.", f"On it, looking up {target}{site}."))
        q = actions.norm(target)
        if q in ("tes parametres", "les parametres de deskmonitor", "deskmonitor", "tes reglages"):
            if run:
                self.open_settings()
            return t("J'ouvre mes paramètres.", "Opening my settings.")
        found, label = None, target
        folders = actions.known_folders()
        if extra in ("folder", "any"):
            if q in actions.SPECIAL:
                found, label = actions.SPECIAL[q], actions.SPECIAL_LABELS.get(q, target)
            elif q in folders:
                found, label = folders[q], t("le dossier ", "the ") + target[:1].upper() + target[1:] + \
                    ("" if self.cfg["voice_lang"] != "en" else " folder")
        if found is None and extra == "any":
            items = collect_items("apps", True, self.organizer.apps)
            app = actions.find_app(target, items)
            if app is not None:
                if run:
                    self.organizer.launch(app)
                return self._pick(t(f"J'ouvre {app['name']}.", f"Opening {app['name']}."),
                                  t(f"Je lance {app['name']}.", f"Launching {app['name']}."),
                                  t(f"C'est parti pour {app['name']}.", f"Here comes {app['name']}."))
            if q in actions.WEBSITES:
                found, label = actions.WEBSITES[q], actions.SITE_LABELS.get(q, target.title())
        if found is None:
            self.files.refresh()
            hit = self.files.find(target, extra)
            if hit:
                found = hit[0]
                label = (t("le dossier ", "the folder ") + Path(hit[0]).name if hit[1]
                         else t("le fichier ", "the file ") + Path(hit[0]).stem)
        if found is None:
            what = {"folder": t("le dossier", "the folder"), "file": t("le fichier", "the file")}.get(extra, "")
            return t(f"Je ne trouve pas {what} {target} sur l'ordinateur. Dites « cherche {target} » pour une "
                     f"recherche sur internet.".replace("  ", " "),
                     f"I can't find {what} {target} on this computer. Say \"search {target}\" to look it up online."
                     .replace("  ", " "))
        if run:
            try:
                actions.open_target(found)
            except OSError as ex:
                return t(f"Je n'arrive pas à ouvrir {label} : {ex}", f"I can't open {label}: {ex}")
        return self._pick(t(f"J'ouvre {label}.", f"Opening {label}."), t(f"Voilà, j'ouvre {label}.", f"There you go, opening {label}."),
                          t(f"Tout de suite : {label}.", f"Right away: {label}."))

    def _on_wake(self, command):
        name = self.cfg["user_name"].strip()
        if not command:   # seulement le nom : on attend la question
            assistant.chime()
            self._toast(self._tr("Je vous écoute…", "I'm listening…"), ms=8000)
            t = self._tr
            self.speak(self._pick(t(f"Oui {name} ?" if name else "Oui ?", f"Yes {name}?" if name else "Yes?"),
                                  t("Je vous écoute.", "I'm listening."), t("Dites-moi.", "Go ahead."),
                                  t(f"Oui, {name}, que puis-je faire ?" if name else "Que puis-je faire ?",
                                    "What can I do for you?")),
                       urgent=True, force=True)
            self.wake.arm()
            return
        self._on_heard(command, None)

    def listen(self):
        """Écoute une phrase, puis répond."""
        if self.wake.running:   # l'écoute continue tourne déjà : la prochaine phrase est une commande
            self.voice.stop()
            assistant.chime()
            self._toast(self._tr("Je vous écoute…", "I'm listening…"), ms=8000)
            self.wake.arm()
            return
        if self.listener.busy:
            return
        c = self.cfg
        self.voice.stop()
        asst = c["assistant_name"].strip() or "Jarvis"

        def ready():   # (thread) le moteur est prêt : signal sonore et bulle « j'écoute »
            assistant.chime()
            self.call_soon(self._toast, self._tr(f"{asst} vous écoute…", f"{asst} is listening…"), 8000)

        # Mac et Windows : le signal sonore n'est donné qu'une fois le micro prêt
        self.listener.listen(c["voice_lang"], lambda text, err: self.call_soon(self._on_heard, text, err),
                             on_ready=ready)

    def _on_heard(self, text, err):
        self._alog(f"entendu : « {text} » → {assistant.parse(text) if text else err}")
        if err or not text:
            self._toast(err or "…")
            self.speak(self._tr("Je n'ai rien entendu.", "I didn't catch that."), force=True)
            return
        self._toast(f"« {text} »")
        reply = self.answer(text)
        if reply:
            self.speak(reply, urgent=True, force=True)

    def answer(self, text, act=True):
        """Réponse de l'assistant à une phrase. act=False : ne déclenche aucune action (autotest)."""
        c, t = self.cfg, self._tr
        name = c["user_name"].strip()
        intent = assistant.parse(text)
        if not self.last:
            self.sample()
        slow = self.cards.slow
        if intent == "stop":
            if act:
                self.voice.stop()
            return ""
        todo = actions.parse(text)   # ouvrir une application / un dossier / un fichier, chercher sur internet
        if todo:
            return self._do_action(todo, run=act)
        words = actions.norm(text).split()
        if ({"libere", "liberer", "vide", "vider", "free", "clear"} & set(words)) and ({"memoire", "ram", "memory"} & set(words)):
            if not IS_WIN:
                return t("Sur Mac, la mémoire est gérée par macOS : je ne peux pas la libérer moi-même.",
                         "On a Mac, macOS manages memory itself: I can't free it for you.")
            if act:
                self.action_ram()
            return t("Je libère la mémoire.", "Freeing up memory.")
        if "dns" in words:
            if not IS_WIN:
                return t("Sur Mac, vider le cache DNS demande les droits administrateur : je ne peux pas le faire.",
                         "On a Mac, flushing the DNS cache needs administrator rights: I can't do it.")
            if act:
                self.action_dns()
            return t("Je vide le cache DNS.", "Flushing the DNS cache.")
        if intent == "tidy":
            if act:
                self.tidy_desktop()
            return self._pick(t("Je range le bureau.", "Tidying up the desktop."),
                              t("Et voilà, tout est bien rangé.", "There, everything's tidy."))
        if intent in ("hide", "show"):
            if act:
                self.set_widgets_hidden(intent == "hide")
            return self._pick(t("C'est fait.", "Done."), t("Voilà.", "There you go."), t("Tout de suite.", "Right away."))
        if intent == "clean":
            if act:
                self.action_clean()
            return self._pick(t("Je nettoie le cache, je vous dis combien j'ai libéré.", "Clearing the cache."),
                              t("Je fais le ménage dans les fichiers temporaires.", "Cleaning up temporary files."))
        if intent == "boost":
            if act:
                self.action_boost()
            return t("J'optimise le système : cache, mémoire et réseau.", "Optimizing the system: cache, memory and network.")
        if intent.startswith("music_"):
            playing = slow.get("music") or (macdata.now_playing() if act else None)
            if not playing:
                return t("Aucune musique en cours.", "Nothing is playing.")
            cmd = {"music_next": "next track", "music_prev": "previous track"}.get(intent, "playpause")
            if act:
                threading.Thread(target=macdata.player_command, args=(playing["app"], cmd), daemon=True).start()
            return ""
        if intent == "processes":
            procs = slow.get("procs") or []
            if not procs:
                return t("Rien ne ralentit l'ordinateur en ce moment.", "Nothing is slowing the computer down.")
            top = procs[0]
            nxt = f", {t('suivi de', 'followed by')} {procs[1][3]}" if len(procs) > 1 else ""
            return t(f"{top[3]} utilise le plus le processeur, {self._pct(top[0])}{nxt}.",
                     f"{top[3]} is using the most processor, {self._pct(top[0])}{nxt}.")
        if intent == "battery":
            b = self._battery()
            if b is None:
                return t("Cet ordinateur n'a pas de batterie.", "This computer has no battery.")
            state = t("en charge", "charging") if b.power_plugged else t("sur batterie", "on battery")
            return t(f"Batterie à {self._pct(b.percent)}, {state}.", f"Battery at {self._pct(b.percent)}, {state}.")
        if intent == "cpu":
            return t(f"Le processeur est à {self._pct(self.last['cpu'])}.",
                     f"The processor is at {self._pct(self.last['cpu'])}.")
        if intent == "ram":
            return t(f"La mémoire est utilisée à {self._pct(self.last['ram'])}.",
                     f"Memory is {self._pct(self.last['ram'])} used.")
        if intent == "disk":
            d = self._disk()
            return t(f"Il reste {d.free / 1e9:.0f} gigaoctets sur le disque.",
                     f"{d.free / 1e9:.0f} gigabytes left on the disk.") if d else ""
        if intent == "network":
            p = self.sensors.get("ping", "…")
            if p is None:
                return t("Pas de connexion internet.", "There's no internet connection.")
            if p == "…":
                return t("Je vérifie la connexion.", "Checking the connection.")
            return t(f"La connexion fonctionne, {p:.0f} millisecondes de latence.",
                     f"The connection is up, {p:.0f} milliseconds of latency.")
        if intent == "weather":
            w = slow.get("weather")
            if not w:
                return t("Je n'ai pas encore la météo. Activez la carte Météo.",
                         "I don't have the weather yet. Turn on the weather card.")
            label = t(w["label"].lower(), macdata.WEATHER_EN.get(w.get("code"), ""))
            return t(f"{w['temp']:.0f} degrés, {label}. Entre {w['tmin']:.0f} et {w['tmax']:.0f} aujourd'hui.",
                     f"{w['temp']:.0f} degrees, {label}. Between {w['tmin']:.0f} and {w['tmax']:.0f} today.")
        if intent == "agenda":
            ev = slow.get("events")
            if ev is None:
                return t("Je n'ai pas accès à votre agenda. Activez la carte Agenda.",
                         "I can't see your calendar. Turn on the calendar card.")
            if not ev:
                return t("Rien de prévu aujourd'hui ni demain.", "Nothing planned today or tomorrow.")
            title, start, allday = ev[0]
            when = t("aujourd'hui", "today") if start.date() == datetime.now().date() else t("demain", "tomorrow")
            at = "" if allday else t(f" à {self._heure(start.hour, start.minute)}",
                                     f" at {start.strftime('%I:%M %p').lstrip('0')}")
            return t(f"Prochain rendez-vous {when}{at} : {title}.", f"Next appointment {when}{at}: {title}.")
        if intent == "time":
            now = datetime.now()
            return t(f"Il est {self._heure(now.hour, now.minute)}.",
                     f"It's {now.strftime('%I:%M %p').lstrip('0')}.")
        if intent == "date":
            return t(f"Nous sommes le {format_date(datetime.now(), {**c, 'date_format': 'long'})}.",
                     f"Today is {datetime.now().strftime('%A, %B %d')}.")
        if intent == "recap":
            return self.recap_text()
        if intent == "hello":
            return t(f"Bonjour {name}. Que puis-je faire pour vous ?", f"Hello {name}. What can I do for you?")
        if intent == "thanks":
            return t(f"Avec plaisir, {name}.", f"My pleasure, {name}.")
        heard = text.strip(" .…")
        if not heard:   # Windows : la phrase après le nom ne fait pas partie des commandes connues
            return t("Je n'ai pas compris. Dites par exemple : ouvre Chrome, cherche la météo à Paris, ouvre le dossier "
                     "téléchargements, ma batterie, ou range le bureau.",
                     "I didn't catch that. Try: open Chrome, search the weather in Paris, open downloads, my battery, "
                     "or tidy the desktop.")
        return t(f"Je n'ai pas compris « {heard} ». Essayez : le point, la batterie, la météo ou mon agenda.",
                 f"I didn't understand \"{heard}\". Try: status, battery, weather or my schedule.")

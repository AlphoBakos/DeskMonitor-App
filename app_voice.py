# -*- coding: utf-8 -*-
"""Voix de l'assistant : synthèse, récapitulatif parlé, annonces de ce qui passe dans le rouge."""
import os
import time
from datetime import datetime


import psutil

import macdata
import voice as voicemod

from core import (
    IS_WIN,
    log_exception,
    IS_MAC,
)


class VoiceMixin:
    # ----- Voix ---------------------------------------------------------------------
    def _voice_allowed(self):
        c = self.cfg
        if not (self.voice_ready and c["voice_on"]):
            return False
        if c["voice_quiet"]:
            h, f, t = datetime.now().hour, int(c["voice_quiet_from"]), int(c["voice_quiet_to"])
            if ((h >= f or h < t) if f > t else f <= h < t):
                return False
        return True

    def speak(self, text, urgent=False, force=False):
        c = self.cfg
        if not (force or self._voice_allowed()):
            return
        lang = c["voice_lang"]
        if not hasattr(self, "_voice_cache"):
            self._voice_cache = {}
        if lang not in self._voice_cache:   # voix installées et meilleure voix, par langue (calculé une fois)
            self._voice_cache[lang] = (voicemod.voices(lang), voicemod.default_voice(lang))
        installed, best = self._voice_cache[lang]
        name = c["voice_name"]
        if name != voicemod.SYSTEM and name not in installed:
            name = best   # aucune voix choisie, ou voix d'une autre langue
        self.voice.say(text, name, c["voice_rate"], urgent)

    def prefetch_voice(self):
        """Réponses courtes préparées à l'avance (voix neuronale) : « Oui Alpho ? » part sans attendre."""
        c, t = self.cfg, self._tr
        name = c["user_name"].strip()
        best = voicemod.default_voice(c["voice_lang"])
        voice = c["voice_name"] if str(c["voice_name"]).startswith(voicemod.NEURAL_PREFIX) else best
        voicemod.prefetch([t(f"Oui {name} ?" if name else "Oui ?", f"Yes {name}?" if name else "Yes?"),
                           t("Je vous écoute.", "I'm listening."), t("Dites-moi.", "Go ahead."),
                           t(f"Oui, {name}, que puis-je faire ?" if name else "Que puis-je faire ?",
                             "What can I do for you?"),
                           t("Je n'ai rien entendu.", "I didn't catch that."), t("C'est fait.", "Done."),
                           t("Je libère la mémoire.", "Freeing up memory."), t("Je range le bureau.", "Tidying up the desktop.")],
                          voice, c["voice_rate"])

    def _tr(self, fr, en):
        return en if self.cfg["voice_lang"] == "en" else fr

    def _pct(self, v):
        return self._tr(f"{v:.0f} %", f"{v:.0f} percent")

    def _disk(self):
        try:
            return psutil.disk_usage("/System/Volumes/Data" if IS_MAC else
                                     (os.getenv("SystemDrive", "C:") + "\\") if IS_WIN else "/")
        except OSError:
            return None

    def recap_text(self):
        """Récapitulatif parlé : heure, machine, batterie, météo, agenda, ce qui est dans le rouge."""
        t, now = self._tr, datetime.now()
        if not self.last:
            self.sample()
        if now.hour < 5 or now.hour >= 18:
            hello = t("Bonsoir", "Good evening")
        else:
            hello = t("Bonjour", "Good morning" if now.hour < 12 else "Good afternoon")
        if c_name := self.cfg["user_name"].strip():
            hello += " " + c_name
        parts = [hello + ". " + t(f"Il est {self._heure(now.hour, now.minute)}.",
                                  f"It's {now.strftime('%-I:%M %p') if not IS_WIN else now.strftime('%I:%M %p')}.")]
        parts.append(t(f"Le processeur est à {self._pct(self.last['cpu'])}, la mémoire à {self._pct(self.last['ram'])}.",
                       f"The processor is at {self._pct(self.last['cpu'])}, memory at {self._pct(self.last['ram'])}."))
        d = self._disk()
        if d:
            parts.append(t(f"Il reste {d.free / 1e9:.0f} gigaoctets sur le disque.",
                           f"{d.free / 1e9:.0f} gigabytes left on the disk."))
        b = self._battery()
        if b is not None:
            if b.power_plugged:
                parts.append(t(f"Batterie à {self._pct(b.percent)}, sur secteur.",
                               f"Battery at {self._pct(b.percent)}, plugged in."))
            else:
                left = b.secsleft if b.secsleft and b.secsleft > 0 else None
                hm = (left // 3600, left % 3600 // 60) if left else None
                parts.append(t(f"Batterie à {self._pct(b.percent)}" +
                               (f", environ {hm[0]} heures {hm[1]} minutes d'autonomie." if hm else "."),
                               f"Battery at {self._pct(b.percent)}" +
                               (f", about {hm[0]} hours {hm[1]} minutes left." if hm else ".")))
        slow = self.cards.slow if hasattr(self, "cards") else {}
        w = slow.get("weather")
        if w:
            label = t(w["label"].lower(), macdata.WEATHER_EN.get(w.get("code"), ""))
            city = w.get("city")
            parts.append(t(f"{('À ' + city + ', ') if city else 'Dehors, '}{w['temp']:.0f} degrés, {label}.",
                           f"{('In ' + city + ', ') if city else 'Outside, '}{w['temp']:.0f} degrees, {label}."))
        ev = slow.get("events")
        if ev:
            today = [e for e in ev if e[1].date() == now.date()]
            if today:
                title, start, allday = today[0]
                n = len(today)
                at_fr = "." if allday else f", à {self._heure(start.hour, start.minute)}."
                at_en = "." if allday else f", at {start.strftime('%I:%M %p').lstrip('0')}."
                parts.append(t(f"Vous avez {n} rendez-vous aujourd'hui. Le prochain : {title}{at_fr}",
                               f"You have {n} appointment{'s' if n > 1 else ''} today. Next: {title}{at_en}"))
        rem = slow.get("reminders")
        if rem and rem[0]:
            n = rem[0]
            parts.append(t(f"{n} rappel{'s' if n > 1 else ''} à faire.", f"{n} reminder{'s' if n > 1 else ''} to do."))
        reds = self._red_messages()
        parts.append(" ".join(m for _, m in reds) if reds else t("Tout est au vert.", "Everything looks good."))
        return " ".join(parts)

    def speak_recap(self, force=False):
        self.speak(self.recap_text(), urgent=True, force=force)

    def _red_messages(self):
        """[(clé, phrase)] des valeurs actuellement dans le rouge."""
        c, t, out = self.cfg, self._tr, []
        thr = c["warn_threshold"]
        if not self.last:
            return out
        if self.last["cpu"] >= thr:
            p = self._pct(self.last["cpu"])
            out.append(("cpu", t(f"Attention, le processeur est à {p}.", f"Heads up, the processor is at {p}.")))
        if self.last["ram"] >= thr:
            p = self._pct(self.last["ram"])
            out.append(("ram", t(f"Attention, la mémoire est utilisée à {p}.", f"Heads up, memory is {p} full.")))
        d = self._disk()
        if d and d.percent >= thr:
            p = self._pct(d.percent)
            out.append(("disk", t(f"Attention, le disque est plein à {p}.", f"Heads up, the disk is {p} full.")))
        b = self._battery()
        if b is not None and not b.power_plugged and b.percent <= c["alert_bat"]:
            p = self._pct(b.percent)
            out.append(("bat", t(f"Batterie faible, {p}. Branchez le chargeur.",
                                 f"Battery low, {p}. Plug in the charger.")))
        if self.sensors.get("ping_fails", 0) >= 3:
            out.append(("offline", t("La connexion internet est coupée.", "The internet connection is down.")))
        return out

    def _voice_watch(self):
        """Annonce une valeur qui passe dans le rouge (une fois, puis au plus toutes les 10 minutes).
        Le processeur doit y rester 15 s : un pic d'une seconde ne mérite pas d'être annoncé."""
        try:
            if self.cfg["voice_alerts"] and self.last:
                now = time.time()
                reds = dict(self._red_messages())
                if "cpu" in reds:
                    self._cpu_red_since = getattr(self, "_cpu_red_since", None) or now
                    if now - self._cpu_red_since < 15:
                        reds.pop("cpu")
                else:
                    self._cpu_red_since = None
                name = self.cfg["user_name"].strip()
                for key, msg in reds.items():
                    if not self._red.get(key) and now - self._red_last.get(key, 0) >= 600:
                        self._red_last[key] = now
                        self.speak(f"{name}, {msg[0].lower()}{msg[1:]}" if name else msg, urgent=True)
                if self._red.get("offline") and "offline" not in reds:
                    self.speak(self._tr("La connexion internet est rétablie.", "The internet connection is back."))
                self._red = {k: True for k in reds}
        except Exception:  # noqa: BLE001
            log_exception("voix")
        self.root.after(2000, self._voice_watch)

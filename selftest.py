# -*- coding: utf-8 -*-
"""Autotests de DeskMonitor (--selftest, --wake-test, --speech-test)."""
import os
import subprocess
import sys
import time
from pathlib import Path

import tkinter as tk

import psutil

from profiles import theme_from_wallpaper
import mac_native
import macdata
import voice as voicemod
import assistant
import wallpaper_dynamic
import wallpapers

from core import (
    IS_WIN,
    APP_VERSION,
    no_window_flags,
)


def selftest(DeskWidget):
    """Démarre l'application, parcourt les paramètres et le bureau organisé, puis quitte.
    Code de retour 0 si aucune erreur. Le rapport est écrit dans CONFIG_DIR/selftest.txt."""
    import tempfile
    import traceback
    import core
    tmp = Path(tempfile.mkdtemp(prefix="deskmonitor-selftest-"))  # jamais la vraie configuration
    core.CONFIG_DIR, core.CONFIG_FILE = tmp, tmp / "config.json"
    report, errors = [], []
    root = tk.Tk()
    root.report_callback_exception = lambda *e: errors.append("".join(traceback.format_exception(*e)))
    app = DeskWidget(root)
    c = app.cfg
    c["animations"] = False   # positions vérifiées tout de suite : pas de glissement en cours

    def step(label, fn):
        try:
            res = fn()
            report.append(f"OK   {label}" + (f" : {res}" if res is not None else ""))
        except Exception:  # noqa: BLE001
            errors.append(f"{label}\n{traceback.format_exc()}")
            report.append(f"ÉCHEC {label}")

    def run():
        step("système", lambda: f"{sys.platform} / {APP_VERSION}")
        step("widget principal", lambda: f"{len(app.rows)} indicateurs")
        step("fonds d'écran intégrés", lambda: len(wallpapers.list_wallpapers()))
        step("applications installées", lambda: len(app.organizer.apps or
                                                     __import__("organizer").list_installed_apps()))

        def org():
            c.update(org_enabled=True, org_source="apps", org_hide_icons=False)
            app.organizer.apps = __import__("organizer").list_installed_apps()
            app.build()
            icons = sum(1 for k in app.organizer.icons.cache)
            return f"{len(app.organizer.fences)} panneaux, {icons} icônes chargées"
        step("bureau organisé", org)
        def cards_test():
            import cards as cardsmod
            out = []
            c["cards"] = [k for k in cardsmod.CARD_TYPES if k != "calendar"]  # l'agenda demande une autorisation
            for layout in ("cards", "minimal", "cards"):
                c["layout"] = layout
                app.build(force=True)
                app.root.update()
                app.sample()
                app.cards.update()
                app.cards.animate()
                out.append(f"{layout}={len(app.cards.cards)}")
            native = sum(1 for k in app.cards.cards.values() if k.native)
            return f"{', '.join(out)} ; flou natif : {native}"
        def overlap_test():
            c["layout"] = "cards"
            c["cards"] = ["clock", "system", "storage", "battery", "network", "music", "weather", "processes"]
            c["card_free"] = True
            c["card_pos"] = {"system": [100, 100], "network": [120, 110], "storage": [100, 100], "clock": [90, 95]}
            app.build(force=True)
            app.root.update()
            cm = app.cards
            rects = [cm._rect(k, cd.win.winfo_x(), cd.win.winfo_y()) for k, cd in cm.cards.items()]
            bad = sum(1 for i, r in enumerate(rects) if cm._hits(r, rects[:i] + rects[i + 1:], margin=0))
            cm.cards["system"].win.geometry(f"+{cm.cards['clock'].win.winfo_x()}+{cm.cards['clock'].win.winfo_y()}")
            cm.settle("system")
            rects = [cm._rect(k, cd.win.winfo_x(), cd.win.winfo_y()) for k, cd in cm.cards.items()]
            bad2 = sum(1 for i, r in enumerate(rects) if cm._hits(r, rects[:i] + rects[i + 1:], margin=0))
            c["card_pos"], c["card_free"] = {}, False
            if bad or bad2:
                raise RuntimeError(f"cartes superposées : {bad} au lancement, {bad2} après déplacement")
            return f"{len(rects)} cartes, aucune superposition"
        def strip_test():
            c["layout"], c["cards_cols"] = "cards", 2
            c["cards"] = list(__import__("cards").CARD_TYPES)
            c["card_pos"] = {}
            app.build(force=True)
            app.root.update()
            sw, sh = app.root.winfo_screenwidth(), app.root.winfo_screenheight()
            off = [k for k, cd in app.cards.cards.items()
                   if cd.win.winfo_x() + cd.px > sw or cd.win.winfo_y() + cd.py > sh]
            # cartes réellement disponibles : Musique optionnelle (Windows), Batterie absente sans batterie (Mac de bureau,
            # machine virtuelle…)
            available = [k for k in c["cards"] if k in __import__("cards").card_ids()
                         and not (k == "battery" and psutil.sensors_battery() is None)]
            missing = [k for k in available if k not in app.cards.cards]
            if off and not missing and getattr(app.cards, "overflow", False):
                # écran trop petit (machine virtuelle, runner GitHub…) : l'app le signale, c'est le comportement voulu
                return f"écran {sw}×{sh} trop petit : {len(off)} carte(s) dépassent, signalé à l'utilisateur"
            if off or missing:
                raise RuntimeError(f"cartes hors écran : {off} ; manquantes : {missing}")
            return f"{len(app.cards.cards)} cartes toutes visibles en colonnes"
        step("toutes les cartes à l'écran", strip_test)
        def align_test():
            c["layout"], c["card_free"] = "cards", False
            c["cards"] = ["clock", "system", "storage", "battery", "network", "music"]
            c["card_pos"] = {"clock": [9, 44], "system": [358, 42], "network": [7, 216]}  # anciennes positions
            app.build(force=True)
            app.root.update()
            cm = app.cards
            xs = {k: cd.win.winfo_x() for k, cd in cm.cards.items()}
            ys = {k: cd.win.winfo_y() for k, cd in cm.cards.items()}
            # pas de la grille tel que l'application le calcule (zoom de l'écran compris sous Windows)
            ox, oy, step_ = min(xs.values()), min(ys.values()), cm.unit + cm.gap
            off = [k for k in xs if (xs[k] - ox) % step_ or (ys[k] - oy) % step_]
            if off:
                raise RuntimeError(f"grille non alignée : {xs} {ys}")
            c["cards"] = ["clock", "system", "storage", "battery", "network"]  # cartes par défaut : 2 colonnes
            app.build(force=True)
            app.root.update()
            cols = {cd.win.winfo_x() for cd in cm.cards.values()}
            if len(cols) != 2:
                raise RuntimeError(f"colonnes attendues : 2, obtenues : {sorted(cols)}")
            c["cards"] = ["clock", "system", "storage", "battery", "network", "music"]
            app.build(force=True)
            app.root.update()
            xs = {k: cd.win.winfo_x() for k, cd in cm.cards.items()}
            ys = {k: cd.win.winfo_y() for k, cd in cm.cards.items()}
            before = list(cm.cards)
            cm.cards["storage"].win.geometry(f"+{xs['clock'] + 10}+{ys['clock'] + 10}")  # glissé sur l'horloge
            app.root.update()
            cm.reorder("storage")
            app.root.update()
            after = list(cm.cards)
            rects = [cm._rect(k, cd.win.winfo_x(), cd.win.winfo_y()) for k, cd in cm.cards.items()]
            bad = sum(1 for i, r in enumerate(rects) if cm._hits(r, rects[:i] + rects[i + 1:], margin=0))
            if after == before or bad or c["cards"][:len(after)] != after:
                raise RuntimeError(f"réorganisation : {before} -> {after}, superpositions {bad}")
            return f"{' > '.join(after)}"
        step("alignement et glisser-déposer", align_test)
        def extras_test():
            import cards as cardsmod
            c.update(layout="cards", cards=["clock", "system", "battery", "network", "storage", "weather"],
                     card_free=False, card_compact=True, card_text_scale=130)
            app.build(force=True)
            app.root.update()
            cm = app.cards
            order = cm._dense(list(cm.cards))
            smalls = [k for k in order if cm.cards[k].w == 1]
            if order[order.index(smalls[0]) + 1] != smalls[1]:
                raise RuntimeError(f"petites cartes non appariées : {order}")
            sizes = {cm.cards["system"].cv.itemcget(i, "font") for i in cm.cards["system"].cv.find_all()
                     if cm.cards["system"].cv.type(i) == "text"}
            c["card_text_scale"] = 100
            # profils automatiques : règle « nuit » forcée sur tout le jour
            app.profiles.save("Test nuit", c)
            c.update(ctx_on=True, ctx_night_profile="Test nuit", ctx_night_from=0, ctx_night_to=24, profile="")
            app._ctx_active = None
            app.root.after_cancel = app.root.after_cancel
            before = app._ctx_active
            app._context_loop()
            applied = app._ctx_active
            c["ctx_on"] = False
            app.profiles.delete("Test nuit")
            if applied != "Test nuit":
                raise RuntimeError(f"profil automatique non appliqué ({before} -> {applied})")
            return f"ordre {order} ; textes {len(sizes)} polices ; profil auto OK"
        step("compactage, taille du texte, profils auto", extras_test)
        step("anti-chevauchement", overlap_test)
        step("récapitulatif vocal (texte)", lambda: app.recap_text()[:90] + "…")

        def assistant_test():
            c.update(user_name="Alpho", assistant_name="Nova")
            phrases = ["Quelle heure est-il", "Où en est ma batterie", "Fais-moi le point", "Quel temps fait-il",
                       "Mes rendez-vous", "Qui ralentit mon Mac", "Bonjour", "Merci", "blabla", "Combien de mémoire"]
            empty = [p for p in phrases if not app.answer(p, act=False)]
            import onboarding
            ob = onboarding.Onboarding(app, on_done=lambda: None)
            ob.name_var.set("Alpho")
            ob._set_lang("en")
            ob.finish()
            ok = c["onboarded"] and c["voice_lang"] == "en" and c["user_name"] == "Alpho"
            c.update(voice_lang="fr", onboarded=False)
            if empty or not ok:
                raise RuntimeError(f"réponses vides : {empty} ; accueil OK : {ok}")
            return f"{len(phrases)} phrases comprises ; accueil OK"
        step("assistant", assistant_test)

        def actions_test():
            cases = {"ouvre le dossier téléchargements": "Téléchargements", "cherche recette de crêpes": "crêpes",
                     "ouvre la corbeille": "corbeille", "libère la mémoire": "mémoire"}
            bad = {q: r for q, r in ((q, app.answer(q, act=False)) for q in cases) if cases[q].lower() not in r.lower()}
            if bad:
                raise AssertionError(f"réponses inattendues : {bad}")
            return f"{len(cases)} actions comprises"
        step("actions de l'assistant", actions_test)

        def neural_test():
            if not voicemod.neural_ok():
                return "module absent (voix hors ligne utilisée)"
            try:
                path = voicemod._neural_file("Bonjour.", "fr-FR-VivienneMultilingualNeural", 185)
            except BaseException as ex:  # noqa: BLE001  hors ligne : la voix installée prend le relais
                return f"injoignable ({type(ex).__name__}) : voix hors ligne utilisée"
            return f"Vivienne, {os.path.getsize(path)} octets"
        step("voix neuronale", neural_test)

        def wake_match_test():
            cases = {"Pablo, quelle heure est-il": (True, "quelle heure est-il"), "Dis Pablo la météo": (True, "la météo"),
                     "Tableau où en est ma batterie": (True, "où en est ma batterie"), "Pablo": (True, ""),
                     "Le tableau est beau": (False, ""), "On mange quoi ce soir": (False, "")}
            bad = {k: assistant.match_name(k, "Pablo", ["tableau"]) for k, v in cases.items()
                   if assistant.match_name(k, "Pablo", ["tableau"]) != v}
            if bad or app.wake.running:
                raise RuntimeError(f"activation vocale : {bad}, écoute active pendant l'autotest : {app.wake.running}")
            return f"{len(cases)} phrases correctement triées"
        step("activation par la voix (nom)", wake_match_test)
        step("voix françaises", lambda: len(voicemod.french_voices()))
        step("cartes macOS", cards_test)
        step("données Mac", lambda: {"batterie": macdata.battery_details(), "thermique": mac_native.thermal_state(),
                                      "accent": mac_native.system_accent(), "sombre": mac_native.system_is_dark(),
                                      "processus": len(macdata.ProcSampler().top(3))})
        step("fond d'écran vivant", lambda: wallpaper_dynamic.compose(
            base_path=wallpapers.list_wallpapers()[0][1], size=(800, 500), slot="soir", state="cpu",
            stats=[("CPU", 90), ("RAM", 50), ("DISQUE", 20)]).size)
        step("barre des menus / raccourci", lambda: (app.cards.menubar.ok if app.cards.menubar else None,
                                                    mac_native.register_hotkey("cmd+alt+d", lambda: None)))
        step("ouverture des paramètres", lambda: app.open_settings())
        for key, *_ in app.settings_win.pages():
            step(f"page « {key} »", lambda k=key: (app.settings_win.show(k), app.root.update(),
                                                   len(app.settings_win.content.winfo_children()))[2])
        if IS_WIN:   # fonctions adaptées à Windows (voix naturelles, reconnaissance hors ligne)
            def win_voice():
                import asyncio
                import voice as vm
                names = vm.voices(c["voice_lang"])
                wav = asyncio.run(vm._onecore_wav("Test", vm.default_voice(c["voice_lang"]), 185))                     if vm._onecore() else b""
                return f"{len(names)} voix, par défaut {vm.default_voice(c['voice_lang'])}, synthèse {len(wav)} octets"
            step("voix Windows (naturelles)", win_voice)

            def win_recognition():
                """Phrases dites par la voix de synthèse, reconnues par le moteur de Windows (sans micro)."""
                import asyncio
                import voice as vm
                if not vm._onecore():
                    return "voix OneCore absentes : test sauté"
                rec = subprocess.run(["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; "
                                      "[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | "
                                      "ForEach-Object { $_.Culture.Name }"], capture_output=True, timeout=60,
                                     creationflags=no_window_flags()).stdout.decode("utf-8", "ignore").split()
                if not any(r.startswith("fr") for r in rec):
                    return f"moteur de reconnaissance français absent ({', '.join(rec) or 'aucun'}) : test sauté"
                fr_voice = vm.offline_voice("fr")   # voix installée (la voix neuronale ne sert pas à fabriquer le WAV)
                results = []
                for phrase, want in (("Quelle heure est-il", "time"), ("Jarvis, ma batterie", "wake")):
                    path = str(tmp / "phrase.wav")
                    Path(path).write_bytes(asyncio.run(vm._onecore_wav(phrase, fr_voice, 185)))
                    full = app.wake._win_script("fr", "Jarvis", ())
                    script = full[:full.index("$parent =")].replace(
                        "$r.SetInputToDefaultAudioDevice();", f"$r.SetInputToWaveFile({assistant._ps_quote(path)});") +                         "$res = $r.Recognize(); if ($res) { [Console]::Out.WriteLine($res.Grammar.Name + \"`t\" + $res.Text) }"
                    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                                         timeout=60, creationflags=no_window_flags()).stdout.decode("utf-8", "ignore")
                    grammar, _, text = out.strip().partition("	")
                    ok = (grammar == "wake") if want == "wake" else assistant.parse(text) == want
                    if not ok:
                        raise RuntimeError(f"« {phrase} » compris « {text} » ({grammar})")
                    results.append(text)
                return " / ".join(results)
            step("reconnaissance vocale Windows", win_recognition)
        step("thème du fond d'écran", lambda: bool(theme_from_wallpaper(
            wallpapers.list_wallpapers()[0][1])))

        def store_test():
            """Version Microsoft Store : tâche de démarrage du paquet (activée puis remise comme avant)."""
            if not core.is_packaged():
                return "version classique (test sauté)"
            before = core.is_autostart()
            core.set_autostart(True)
            on = core.is_autostart()
            core.set_autostart(before)
            if not on or core.is_autostart() != before:
                raise RuntimeError(f"tâche de démarrage : activée={on}, remise={core.is_autostart()} (attendu {before})")
            return "paquet MSIX, tâche de démarrage OK"
        step("version Microsoft Store", store_test)

        def english_test():
            """Interface en anglais : dictionnaire présent (aussi dans l'application construite), modèles, dates."""
            import i18n
            from datetime import datetime
            before = i18n.lang()
            i18n.set_lang("en")
            try:
                checks = {"Apparence": "Appearance", "Le GPU est à 91 °C.": "The GPU is at 91 °C.",
                          core.format_date(datetime(2026, 10, 6), {"date_format": "long"}): "Tuesday, October 6, 2026"}
                bad = {k: v for k, v in checks.items() if i18n.tr(k) != v}
                if bad:
                    raise RuntimeError(f"traductions inattendues : {bad}")
                return f"{len(i18n._en)} textes traduits"
            finally:
                i18n.set_lang(before)
        step("interface en anglais", english_test)
        root.after(500, finish)

    def finish():
        text = "\n".join(report) + ("\n\nERREURS :\n" + "\n".join(errors) if errors else "\n\nAucune erreur.")
        out = os.environ.get("DM_SELFTEST_OUT") or str(tmp / "selftest.txt")
        Path(out).write_text(text, encoding="utf-8")
        try:
            print(text, flush=True)
        except (OSError, AttributeError):  # application fenêtrée sans console
            pass
        app.organizer.shutdown()
        app.tray.stop()
        root.destroy()

    root.after(2500, run)
    root.mainloop()
    return 1 if errors else 0


def wake_test():
    args = sys.argv[sys.argv.index("--wake-test") + 1:]
    out, name = Path(args[0]), args[1]
    secs = int(args[2]) if len(args) > 2 else 45   # --wake-test SORTIE NOM [secondes] [variante1,variante2]
    root = tk.Tk()
    root.withdraw()
    lines = []

    def log(msg):
        lines.append(f"{time.strftime('%H:%M:%S')} {msg}")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    aliases = args[3].split(",") if len(args) > 3 else []
    w = assistant.WakeListener(get_name=lambda: name, get_lang=lambda: "fr", get_aliases=lambda: aliases,
                               on_wake=lambda cmd: log(f"RÉVEIL → commande : « {cmd} »"),
                               is_speaking=lambda: False, log=log)
    w.start()
    root.after(secs * 1000, lambda: (w.stop(), root.after(800, root.destroy)))
    root.mainloop()
    return 0


def speech_test():
    """--speech-test FICHIER SORTIE [fr|en] : transcrit un fichier audio.
    --mic-test SORTIE [fr|en] : écoute le micro quelques secondes. Le résultat est écrit dans SORTIE."""
    args = sys.argv[sys.argv.index("--speech-test" if "--speech-test" in sys.argv else "--mic-test") + 1:]
    mic = "--mic-test" in sys.argv
    out = Path(args[0] if mic else args[1])
    lang = (args[1] if mic else args[2]) if len(args) > (1 if mic else 2) else "fr"
    root = tk.Tk()
    root.withdraw()
    res = {}

    def done(text, err):
        res.update(text=text, err=err)

    if mic:
        listener = assistant.Listener()
        listener.record = []

        def ready():
            assistant.chime()
            Path(str(out) + ".ready").write_text("1")   # pour les tests automatiques : on peut parler
        root.after(500, lambda: listener.listen(lang, done, max_secs=12, on_ready=ready))
    else:
        assistant.transcribe_file(args[0], lang, done)

    def poll():
        if res:
            dbg = getattr(listener, "last_debug", {}) if mic else {}
            if mic and listener.record:
                import array
                import wave
                with wave.open(str(out) + ".wav", "wb") as w:   # le son capté, pour analyse
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(dbg.get("rate", 48000))
                    w.writeframes(array.array("h", (max(-32767, min(32767, int(v * 32767)))
                                                    for v in listener.record)).tobytes())
            extra = {k: dbg.get(k) for k in ("buffers", "format", "peak", "gen", "calls", "errors")} if dbg else {}
            out.write_text(f"texte : {res['text']}\nerreur : {res['err']}\ndiagnostic : {extra}\n", encoding="utf-8")
            root.destroy()
        else:
            root.after(100, poll)

    root.after(100, poll)
    root.after(90000, root.destroy)
    root.mainloop()
    return 0 if res.get("text") else 1

# -*- coding: utf-8 -*-
"""Assistant vocal : écoute une phrase (reconnaissance du système), la comprend, et dit quoi faire.
macOS : framework Speech (hors ligne si possible). Windows : System.Speech (PowerShell)."""
import os
import subprocess
import sys
import threading
import time
import unicodedata

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


def _norm(text):
    t = unicodedata.normalize("NFD", text.lower())
    return " " + "".join(ch for ch in t if unicodedata.category(ch) != "Mn") + " "


# (intention, mots-clés) : le premier qui correspond gagne, d'où l'ordre
INTENTS = [
    ("hide", ["masque", "cache les widgets", "cache les cartes", "hide"]),
    ("show", ["affiche les", "montre les", "show the widgets", "show widgets"]),
    ("tidy", [" range ", " range-", " organise ", " tidy", " organize", " arrange "]),
    ("clean", ["nettoie", "vide le cache", "clean", "clear the cache"]),
    ("boost", ["optimise", "accelere", "boost", "speed up"]),
    ("music_next", ["suivant", "chanson suivante", "next song", "next track", "skip"]),
    ("music_prev", ["precedent", "previous"]),
    ("music_pause", ["pause", "arrete la musique", "coupe la musique", "stop the music"]),
    ("music_play", ["joue", "reprends", "relance la musique", "play", "resume"]),
    ("stop", ["tais-toi", "tais toi", "silence", " chut", "arrete de parler", "shut up", "be quiet", " stop "]),
    ("processes", ["qui consomme", "ralentit", "gourmand", "processus", "slowing", "what's using", "processes"]),
    ("battery", ["batterie", "battery"]),
    ("cpu", ["processeur", " cpu", "processor"]),
    ("ram", ["memoire", " ram", "memory"]),
    ("disk", ["disque", "stockage", "espace libre", "disk", "storage"]),
    ("network", ["internet", "connexion", "reseau", "ping", "network", "connection"]),
    ("weather", ["meteo", "quel temps", "temperature", "weather"]),
    ("agenda", ["agenda", "rendez-vous", "rendez vous", "reunion", "calendrier", "programme", "calendar",
                "meeting", "schedule", "appointment"]),
    ("time", ["quelle heure", "l'heure", "what time", "the time"]),
    ("date", ["quel jour", "la date", "what day", "the date"]),
    ("recap", ["recap", "resume", "le point", "bilan", "situation", "status", "summary", "briefing", "update me"]),
    ("hello", ["bonjour", "salut", "coucou", "hello", " hi ", "hey"]),
    ("thanks", ["merci", "thank"]),
]


# Phrases complètes proposées au moteur de Windows (en plus de la dictée libre) : il reconnaît bien mieux
# une phrase attendue qu'une phrase quelconque. Plusieurs formulations par demande, comme on parle vraiment.
COMMAND_PHRASES = {
    "fr": [
        # widgets et bureau
        "masque les widgets", "cache les widgets", "cache les cartes", "affiche les widgets", "montre les widgets",
        "montre les cartes", "range le bureau", "range les widgets", "organise le bureau", "organise les widgets",
        # entretien
        "nettoie le cache", "vide le cache", "nettoie l'ordinateur", "fais le ménage", "optimise le système",
        "optimise l'ordinateur", "accélère l'ordinateur", "accélère le PC",
        "libère la mémoire", "libère la RAM", "vide la mémoire", "vide la RAM", "vide le cache DNS",
        # musique
        "chanson suivante", "musique suivante", "passe à la suivante", "suivant", "chanson précédente", "précédent",
        "pause", "mets en pause", "mets la musique en pause", "arrête la musique", "coupe la musique",
        "joue la musique", "lance la musique", "reprends la musique", "remets la musique",
        # silence
        "tais-toi", "silence", "chut", "arrête de parler", "stop",
        # état de la machine
        "qui ralentit l'ordinateur", "qu'est-ce qui ralentit l'ordinateur", "qui consomme le plus",
        "quels programmes consomment", "les processus",
        "ma batterie", "la batterie", "état de la batterie", "combien de batterie", "il me reste combien de batterie",
        "le processeur", "utilisation du processeur", "combien de processeur",
        "la mémoire", "combien de mémoire", "utilisation de la mémoire", "la RAM",
        "l'espace disque", "le stockage", "combien d'espace libre", "il me reste combien de place",
        "la connexion internet", "est-ce que j'ai internet", "le réseau", "le ping",
        # météo, agenda, heure
        "la météo", "quel temps fait-il", "quel temps fait-il aujourd'hui", "il fait quel temps", "la température",
        "quelle est la météo", "va-t-il pleuvoir",
        "mes rendez-vous", "mon agenda", "mon programme", "qu'est-ce que j'ai aujourd'hui", "mes réunions",
        "quelle heure est-il", "il est quelle heure", "l'heure", "quel jour sommes-nous", "on est quel jour",
        "la date", "quelle est la date",
        # bilan
        "le point", "fais le point", "fais-moi le point", "un récapitulatif", "fais un bilan", "résumé",
        "comment va l'ordinateur", "comment va le PC", "tout va bien",
        # politesse
        "bonjour", "salut", "coucou", "bonsoir", "merci", "merci beaucoup",
    ],
    "en": [
        "hide the widgets", "show the widgets", "tidy the desktop", "organize the widgets",
        "clean the cache", "clear the cache", "clean up the computer", "speed up", "speed up the computer", "boost",
        "free up memory", "free the RAM", "clear the memory",
        "next song", "next track", "skip", "previous song", "pause", "pause the music", "stop the music",
        "play the music", "play music", "resume", "be quiet", "stop", "shut up",
        "what's slowing the computer", "what's using the processor", "processes",
        "my battery", "battery status", "how much battery", "the processor", "processor usage", "memory",
        "memory usage", "disk space", "storage", "how much space is left", "internet connection", "network",
        "the weather", "what's the weather", "is it going to rain", "temperature",
        "my calendar", "my meetings", "my schedule", "what do I have today",
        "what time is it", "what day is it", "the date",
        "give me a summary", "status update", "how's the computer", "summary",
        "hello", "hi", "good evening", "thank you", "thanks",
    ],
}

# Mots trop courants pour servir de variante du nom de l'assistant : appris par erreur, ils réveilleraient
# l'assistant à chaque phrase (« on », « et », « demain »…)
STOPWORDS = set("""
a à au aux avec ce ces cet cette dans de des du elle elles en est et eux il ils je la le les leur lui ma mais me
mes moi mon ne ni nos notre nous on ou où par pas pour qu que qui sa se ses si son sur ta te tes toi ton tu un une
vos votre vous y oui non alors bon bien très tout tous toute toutes comme fait faire dit dire va vais aller avoir
être été demain hier aujourd'hui maintenant ici là voilà ça cela quoi quand comment pourquoi euh ben hein ok okay
the a an and or of to in on at is it i you he she we they my your this that what yes no so well hey hi
""".split())


def valid_alias(alias, name=""):
    """Une variante du nom n'est retenue que si elle est assez longue et n'est pas un mot courant."""
    words = _tokens(alias)
    if not words or len("".join(words)) < 4:
        return False
    if all(w in STOPWORDS for w in words):
        return False
    return " ".join(words) != " ".join(_tokens(name))


def phonetic_variants(name):
    """Orthographes que le moteur de Windows prononce comme le nom : « Bakos » → « Bacos », « Bacosse »…
    Le nom lui-même vient toujours en premier."""
    n = name.strip()
    if not n:
        return []
    out = [n]
    low = n.lower()
    import re
    k2c = re.sub(r"k(?=[aou])", "c", low)   # même son seulement devant a, o, u (« Kevin » ≠ « Cevin »)
    c2k = re.sub(r"c(?=[aou])", "k", low)
    cands = {k2c, c2k, low.replace("ph", "f"), low.replace("y", "i")}
    if low.endswith("s"):
        cands |= {low + "se", k2c + "se", c2k + "se"}
    elif low[-1] not in "aeiouy":
        cands.add(low + "e")
    for c in sorted(cands):
        if c != low:
            out.append(c.capitalize())
    return out[:7]


def clean_aliases(aliases, name=""):
    return [a for a in dict.fromkeys(aliases or []) if valid_alias(a, name)]


def command_phrases(lang):
    return COMMAND_PHRASES.get(lang, COMMAND_PHRASES["fr"])


def _ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def win_recognizer_script(lang, extra_phrases=(), dictation=True):
    """Début de script PowerShell : moteur System.Speech dans la langue voulue (repli : celui installé),
    dictée libre + phrases attendues, entrée = micro par défaut. Variable : $r."""
    culture = "fr-FR" if lang == "fr" else "en-US"
    s = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
         "Add-Type -AssemblyName System.Speech;"
         f"$ci = [System.Globalization.CultureInfo]'{culture}';"
         "$inst = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | "
         "Where-Object { $_.Culture.Name -eq $ci.Name } | Select-Object -First 1;"
         "if ($inst) { $r = New-Object System.Speech.Recognition.SpeechRecognitionEngine($inst) } "
         "else { $r = New-Object System.Speech.Recognition.SpeechRecognitionEngine };"
         "$culture = $r.RecognizerInfo.Culture;")
    if dictation:
        s += ("$d = New-Object System.Speech.Recognition.DictationGrammar; $d.Name = 'free';"
              "$r.LoadGrammar($d);")
    if extra_phrases:
        s += ("$ch = New-Object System.Speech.Recognition.Choices;"
              + "".join(f"$ch.Add({_ps_quote(p)});" for p in extra_phrases)
              + "$gb = New-Object System.Speech.Recognition.GrammarBuilder; $gb.Culture = $culture; $gb.Append($ch);"
              "$g = New-Object System.Speech.Recognition.Grammar($gb); $g.Name = 'commands'; $r.LoadGrammar($g);")
    s += ("$r.SetInputToDefaultAudioDevice();"
          "$r.InitialSilenceTimeout = [TimeSpan]::FromSeconds(6);"
          "$r.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.9);")
    return s


ACT_VERBS = {
    "fr": {"open": ["ouvre", "lance", "démarre", "ouvre-moi", "lance-moi", "peux-tu ouvrir", "peux-tu lancer",
                    "tu peux ouvrir", "tu peux lancer", "ouvrir", "lancer"],
           "search": ["cherche", "recherche", "cherche-moi", "fais une recherche sur", "cherche sur internet",
                      "recherche sur internet", "cherche sur Google", "google"],
           "folder": ["le dossier", "mes", "mon", "le", "la", "les"],
           "file": ["le fichier", "le document"]},
    "en": {"open": ["open", "launch", "start", "can you open", "please open"],
           "search": ["search for", "search", "look up", "google"],
           "folder": ["the folder", "my", "the"], "file": ["the file", "the document"]},
}


def _clean_name(name):
    """Nom d'application utilisable dans une grammaire (sans symboles ni parenthèses)."""
    import re
    n = re.sub(r"\(.*?\)", " ", str(name))
    n = re.sub(r"[^\w' -]+", " ", n)
    return " ".join(n.split())[:40]


def act_grammar_ps(lang, vocab, sfx=""):
    """Script PowerShell qui définit $acts{sfx} : ouvrir une application / un dossier connu, ouvrir un fichier ou
    faire une recherche (dictée libre pour le nom du fichier et la recherche). sfx : suffixe des variables, pour
    construire plusieurs copies indépendantes (un même bloc ne peut pas servir à deux grammaires)."""
    if not vocab:
        return ""
    v = ACT_VERBS.get(lang, ACT_VERBS["fr"])
    apps = [n for n in dict.fromkeys(_clean_name(a) for a in vocab.get("apps", ())) if len(n) >= 2][:300]
    places = [n for n in dict.fromkeys(_clean_name(a) for a in vocab.get("places", ())) if len(n) >= 2][:150]

    def choices(var, items):
        return (f"${var}{sfx} = New-Object System.Speech.Recognition.Choices;"
                + "".join(f"${var}{sfx}.Add({_ps_quote(i)});" for i in items))
    s = (choices("ov", v["open"]) + choices("sv", v["search"]) + choices("fv", v["file"])
         + choices("dv", v["folder"]) + "$acts{sfx} = New-Object System.Speech.Recognition.Choices;")
    if apps:
        s += (choices("ap", apps) + "$g1{sfx} = New-Object System.Speech.Recognition.GrammarBuilder; $g1{sfx}.Culture = $culture;"
              "$g1{sfx}.Append($ov{sfx}); $g1{sfx}.Append($ap{sfx}); $acts{sfx}.Add($g1{sfx});")
    if places:
        s += (choices("pl", places) + "$g2{sfx} = New-Object System.Speech.Recognition.GrammarBuilder; $g2{sfx}.Culture = $culture;"
              "$g2{sfx}.Append($ov{sfx}); $g2{sfx}.Append($dv{sfx}, 0, 1); $g2{sfx}.Append($pl{sfx}); $acts{sfx}.Add($g2{sfx});")
    s += ("$g3{sfx} = New-Object System.Speech.Recognition.GrammarBuilder; $g3{sfx}.Culture = $culture;"
          "$g3{sfx}.Append($sv{sfx}); $g3{sfx}.AppendDictation(); $acts{sfx}.Add($g3{sfx});"
          "$g4{sfx} = New-Object System.Speech.Recognition.GrammarBuilder; $g4{sfx}.Culture = $culture;"
          "$g4{sfx}.Append($ov{sfx}); $g4{sfx}.Append($fv{sfx}); $g4{sfx}.AppendDictation(); $acts{sfx}.Add($g4{sfx});")
    return s.replace("{sfx}", sfx)


def run_ps(script):
    """Lance un script PowerShell écrit dans un fichier (pas de limite de longueur de la ligne de commande ;
    UTF-8 avec BOM pour que Windows PowerShell lise bien les accents). Retourne le Popen."""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"deskmonitor-ecoute-{os.getpid()}-{threading.get_ident()}.ps1")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(script)
    return subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000)


def _parse_exact(t):
    for intent, words in INTENTS:
        if any(w in t for w in words):
            return intent
    return "unknown"


def parse(text):
    """Intention reconnue dans la phrase, ou « unknown ». Si aucun mot-clé ne correspond (mot mal transcrit :
    « ma baterie », « quel tant fait-il »), on cherche la phrase connue la plus proche."""
    t = _norm(text)
    intent = _parse_exact(t)
    if intent != "unknown" or len(t.strip()) < 3:
        return intent
    import difflib
    known = {_norm(p).strip(): p for lang in COMMAND_PHRASES for p in COMMAND_PHRASES[lang]}
    close = difflib.get_close_matches(t.strip(), list(known), n=1, cutoff=0.72)
    return _parse_exact(_norm(known[close[0]])) if close else "unknown"


# ---------------------------------------------------------------------------
#  Écoute
# ---------------------------------------------------------------------------
class Listener:
    """listen(lang, done) : écoute une phrase et appelle done(texte, erreur) (depuis un autre thread)."""

    def __init__(self):
        self.busy = False
        self.record = None   # liste d'échantillons si on veut enregistrer (tests)

    WARMUP = 1.2   # le moteur hors ligne perd le son de la 1re seconde : on ne donne le signal qu'après

    vocab = None   # {"apps": [...], "places": [...]} : noms proposés au moteur (Windows)

    def listen(self, lang, done, max_secs=8, on_ready=None, free_only=False):
        """on_ready() : appelé quand on peut parler (c'est là qu'on joue le « tink »).
        free_only : dictée libre seule (Windows), pour apprendre le nom sans le confondre avec une commande."""
        if self.busy:
            return
        self.busy = True
        self.on_ready = on_ready

        def finish(text, err):
            self.busy = False
            done(text, err)

        if IS_MAC:
            self._listen_mac(lang, finish, max_secs)
        elif IS_WIN:
            threading.Thread(target=self._listen_win, args=(lang, finish, max_secs, free_only), daemon=True).start()
        else:
            finish(None, "Reconnaissance vocale non disponible sur ce système")

    # ----- macOS -----------------------------------------------------------------------
    def _listen_mac(self, lang, finish, max_secs):
        try:
            import AVFoundation
            import Speech
            from Foundation import NSLocale
        except ImportError:
            finish(None, "Module de reconnaissance vocale absent")
            return
        state = {"text": "", "last": time.time(), "final": False, "err": None, "buffers": 0, "errors": []}
        self.last_debug = state

        def start():
            loc = NSLocale.localeWithLocaleIdentifier_("fr-FR" if lang == "fr" else "en-US")
            rec = Speech.SFSpeechRecognizer.alloc().initWithLocale_(loc)
            if rec is None or not rec.isAvailable():
                finish(None, "La reconnaissance vocale n'est pas disponible")
                return
            on_device = bool(rec.supportsOnDeviceRecognition())

            def new_task():
                """(Re)lance une reconnaissance sur le même flux micro : macOS abandonne après ~3 s de silence."""
                gen = state["gen"] = state.get("gen", 0) + 1
                req = Speech.SFSpeechAudioBufferRecognitionRequest.alloc().init()
                # hors ligne, les résultats partiels sur un flux micro ne remontent jamais (testé) :
                # on demande seulement le résultat final, la fin de phrase est détectée au niveau sonore
                req.setShouldReportPartialResults_(False)
                if on_device:
                    req.setRequiresOnDeviceRecognition_(True)   # rien ne quitte le Mac

                def handler(result, error):
                    state["calls"] = state.get("calls", 0) + 1
                    if gen != state["gen"]:
                        return   # ancienne tentative
                    if result is not None:
                        txt = str(result.bestTranscription().formattedString())
                        if txt != state["text"]:
                            state["text"], state["last"] = txt, time.time()
                        if result.isFinal():
                            state["final"] = True
                    if error is not None:
                        state["errors"].append(str(error.localizedDescription()))
                        if not state["text"]:
                            state["err"] = str(error.localizedDescription())

                state["req"] = req
                state["task"] = rec.recognitionTaskWithRequest_resultHandler_(req, handler)

            engine = AVFoundation.AVAudioEngine.alloc().init()
            node = engine.inputNode()
            fmt = node.outputFormatForBus_(0)
            state["format"] = f"{fmt.sampleRate():.0f} Hz, {fmt.channelCount()} canal(aux)"
            state["rate"] = int(fmt.sampleRate())
            state["peak"] = 0.0

            state["levels"], state["voice_last"] = [], None

            def tap(buf, when):
                state["buffers"] += 1
                try:   # niveau du micro : crête sur un échantillon sur 16
                    ch, n = buf.floatChannelData()[0], int(buf.frameLength())
                    if self.record is not None:   # tests : garde le son capté
                        self.record.extend(ch[i] for i in range(n))
                    level = max(abs(ch[i]) for i in range(0, n, 16))
                    state["peak"] = max(state["peak"], level)
                    lv = state["levels"]
                    lv.append(level)
                    floor = sorted(lv[:8])[len(lv[:8]) // 2] if lv else 0   # bruit de fond (début de l'écoute)
                    if len(lv) > 3 and level > max(0.03, floor * 3):
                        state["voice_last"] = time.time()
                        state["voiced"] = state.get("voiced", 0) + 1
                except Exception:  # noqa: BLE001
                    pass
                state["req"].appendAudioPCMBuffer_(buf)

            new_task()
            node.installTapOnBus_bufferSize_format_block_(0, 1024, fmt, tap)
            engine.prepare()
            ok, err = engine.startAndReturnError_(None)
            if not ok:
                node.removeTapOnBus_(0)
                finish(None, "Micro indisponible")
                return

            def watch():
                time.sleep(self.WARMUP)
                state["levels"], state["voice_last"] = [], None   # le bruit pendant le démarrage ne compte pas
                if self.on_ready:
                    try:
                        self.on_ready()
                    except Exception:  # noqa: BLE001
                        pass
                    time.sleep(0.5)   # le « tink » est capté par le micro : il ne doit pas compter comme de la voix
                    state["voice_last"], state["voiced"] = None, 0
                t0 = time.time()
                while True:
                    time.sleep(0.1)
                    v = state["voice_last"]
                    # au moins 0,3 s de voix, puis 1,3 s de silence
                    done_talking = v is not None and state.get("voiced", 0) >= 3 and time.time() - v > 1.3
                    if done_talking or time.time() - t0 > max_secs or state["final"]:
                        break
                try:
                    state["req"].endAudio()   # demande le résultat final
                except Exception:  # noqa: BLE001
                    pass
                t1 = time.time()
                while not state["final"] and not state["err"] and time.time() - t1 < 6:
                    time.sleep(0.1)
                try:
                    engine.stop()
                    node.removeTapOnBus_(0)
                    state["task"].finish()
                except Exception:  # noqa: BLE001
                    pass
                finish(state["text"] or None, None if state["text"] else (state["err"] or "Je n'ai rien entendu"))

            threading.Thread(target=watch, daemon=True).start()

        def authorized(status):
            if status != 3:   # SFSpeechRecognizerAuthorizationStatusAuthorized
                finish(None, "Autorisez la reconnaissance vocale dans Réglages Système > Confidentialité")
                return
            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVFoundation.AVMediaTypeAudio,
                lambda granted: start() if granted else finish(None, "Autorisez le micro dans Réglages Système"))

        Speech.SFSpeechRecognizer.requestAuthorization_(authorized)

    # ----- Windows -----------------------------------------------------------------------
    def _listen_win(self, lang, finish, max_secs, free_only=False):
        """System.Speech hors ligne : dictée libre + liste des commandes connues (bien plus fiable que la
        dictée seule). Le script écrit READY quand le micro écoute, puis la phrase reconnue."""
        acts = "" if free_only else act_grammar_ps(lang, self.vocab() if callable(self.vocab) else self.vocab)
        script = win_recognizer_script(lang, extra_phrases=() if free_only else command_phrases(lang)) + acts + (
            ("$ag = New-Object System.Speech.Recognition.Grammar((New-Object System.Speech.Recognition.GrammarBuilder"
             "($acts))); $ag.Name = 'act'; $r.LoadGrammar($ag);" if acts else "") +
            "[Console]::Out.WriteLine('READY'); [Console]::Out.Flush();"
            f"$res = $r.Recognize([TimeSpan]::FromSeconds({int(max_secs)}));"
            "if ($res) { [Console]::Out.WriteLine('TEXT ' + $res.Text) }")
        try:
            p = run_ps(script)
            text, t0 = None, time.time()
            for raw in p.stdout:
                line = raw.decode("utf-8", "ignore").strip()
                if line == "READY" and self.on_ready:
                    try:
                        self.on_ready()   # le micro écoute : signal sonore et bulle « j'écoute »
                    except Exception:  # noqa: BLE001
                        pass
                elif line.startswith("TEXT "):
                    text = line[5:].strip()
                if time.time() - t0 > max_secs + 20:
                    break
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            finish(text or None, None if text else "Je n'ai rien entendu")
        except (OSError, subprocess.SubprocessError) as ex:
            finish(None, str(ex))


def transcribe_file(path, lang, done, timeout=30):
    """(macOS, tests) transcrit un fichier audio ; done(texte, erreur) appelé depuis un autre thread."""
    try:
        import Speech
        from Foundation import NSLocale, NSURL
    except ImportError as ex:
        done(None, f"import : {ex}")
        return
    state = {"text": None, "done": False, "err": None}

    def authorized(status):
        if status != 3:
            done(None, f"autorisation refusée (statut {status})")
            return
        rec = Speech.SFSpeechRecognizer.alloc().initWithLocale_(
            NSLocale.localeWithLocaleIdentifier_("fr-FR" if lang == "fr" else "en-US"))
        req = Speech.SFSpeechURLRecognitionRequest.alloc().initWithURL_(NSURL.fileURLWithPath_(path))
        on_device = bool(rec.supportsOnDeviceRecognition())
        if on_device:
            req.setRequiresOnDeviceRecognition_(True)

        def handler(result, error):
            if result is not None:
                state["text"] = str(result.bestTranscription().formattedString())
                if result.isFinal():
                    state["done"] = True
            if error is not None:
                state["err"], state["done"] = str(error.localizedDescription()), True

        state["task"] = rec.recognitionTaskWithRequest_resultHandler_(req, handler)

        def wait():
            t0 = time.time()
            while not state["done"] and time.time() - t0 < timeout:
                time.sleep(0.1)
            done(state["text"], None if state["text"] else (state["err"] or "délai dépassé"))
        threading.Thread(target=wait, daemon=True).start()

    Speech.SFSpeechRecognizer.requestAuthorization_(authorized)


def learn_alias(heard, name):
    """Ce que le moteur a écrit quand on a dit le nom : la variante à retenir (ou None si c'est déjà le nom)."""
    import difflib
    words, target = _tokens(heard), _tokens(name)
    if not words:
        return None
    guess = " ".join(words[:max(1, len(target))])
    if difflib.SequenceMatcher(None, guess, " ".join(target)).ratio() >= 0.75:
        return None
    return guess if valid_alias(guess, name) else None   # « on », « et », « demain »… : jamais retenus


def chime():
    """Petit son qui signale que l'assistant écoute."""
    try:
        if IS_MAC:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
        elif IS_WIN:
            import winsound
            winsound.MessageBeep(0x40)
    except (OSError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
#  Activation par la voix (macOS) : écoute continue, réagit au nom de l'assistant
# ---------------------------------------------------------------------------
def _tokens(text):
    import re
    return re.findall(r"[a-z0-9']+", _norm(text))


def match_name(text, name, aliases=()):
    """Si la phrase commence par le nom (ou « dis / hey / ok… » + le nom) : (True, suite de la phrase). Tolère les
    petites erreurs de transcription (« Pablo » → « Pablos », « Pablot »…)."""
    import difflib
    words, target = _tokens(text), _tokens(name)
    if not words or not target:
        return False, ""
    n = len(target)
    starts = [0] + ([1] if words[0] in ("dis", "hey", "he", "ok", "eh", "salut", "bonjour", "hello", "hi", "yo")
                    else [])
    known = {" ".join(_tokens(a)) for a in aliases if a}
    for i in starts:
        chunk = " ".join(words[i:i + n])
        alias = next((a for a in known if " ".join(words[i:i + len(a.split())]) == a), None)
        if alias:   # variante apprise (« tableau » pour « Pablo »…)
            raw = text.split()
            return True, " ".join(raw[i + len(alias.split()):]).lstrip(",.;:!? ")
        if difflib.SequenceMatcher(None, chunk, " ".join(target)).ratio() >= 0.75:
            # suite de la phrase d'origine, après le nom
            raw = text.split()
            rest = " ".join(raw[i + n:]).lstrip(",.;:!? ")
            return True, rest
    return False, ""


class WakeListener:
    """Écoute en continu ; découpe le son en phrases (niveau sonore) ; transcrit chaque phrase hors ligne ;
    appelle on_wake(commande) quand la phrase commence par le nom (commande vide si seul le nom est dit :
    la phrase suivante devient la commande)."""

    ROTATE = 40   # secondes sans parole avant de renouveler la requête (limite d'environ 1 minute)

    def __init__(self, get_name, get_lang, on_wake, is_speaking, log=None, get_aliases=lambda: (),
                 get_vocab=lambda: None):
        self.get_name, self.get_lang, self.on_wake, self.is_speaking = get_name, get_lang, on_wake, is_speaking
        self.get_aliases, self.get_vocab = get_aliases, get_vocab
        self.log = log or (lambda *_: None)
        self.running = False
        self.armed_until = 0.0
        self._st = None

    def arm(self, secs=8):
        """La prochaine phrase sera une commande, sans avoir à redire le nom (raccourci clavier, « Pablo » seul)."""
        self.armed_until = time.time() + secs

    def start(self):
        if self.running or not (IS_MAC or IS_WIN):
            return
        self.running = True
        if IS_WIN:
            threading.Thread(target=self._run_win, daemon=True).start()
            return
        try:
            import Speech
            from Foundation import NSLocale
        except ImportError:
            self.running = False
            return

        def authorized(status):
            if status != 3:
                self.running = False
                self.log("refus de la reconnaissance vocale")
                return
            import AVFoundation
            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVFoundation.AVMediaTypeAudio, lambda ok: self._run(Speech, NSLocale) if ok else self._denied())

        Speech.SFSpeechRecognizer.requestAuthorization_(authorized)

    def _denied(self):
        self.running = False
        self.log("refus du micro")

    def stop(self):
        self.running = False
        p = getattr(self, "_proc", None)
        if p is not None and p.poll() is None:
            try:
                p.kill()   # Windows : coupe l'écoute (et le micro) tout de suite
            except OSError:
                pass

    # ----- Windows : écoute continue avec System.Speech ---------------------------------------
    def _win_script(self, lang, name, aliases, vocab=None):
        """Écoute continue Windows. Pendant la veille, PAS de dictée libre : face à un nom absent du dictionnaire
        (« Bakos »), elle l'emporte toujours avec un mot approchant (« Bécasse »). Grammaires :
          - « wake » : [dis|hey|ok] + nom (ou variante phonétique) + [commande connue] ;
          - « commands » : les commandes connues seules (après le nom, ou après le raccourci) ;
          - « other » : attrape-tout qui absorbe les conversations ordinaires sans les transformer en mots.
        Écrit « grammaire<TAB>confiance<TAB>texte » par phrase. S'arrête si DeskMonitor n'existe plus."""
        names = [n for n in dict.fromkeys(phonetic_variants(name) + clean_aliases(aliases, name)) if n.strip()]
        prefixes = ["dis", "hey", "ok", "salut"] if lang == "fr" else ["hey", "ok", "hi"]
        return win_recognizer_script(lang, extra_phrases=command_phrases(lang), dictation=False) + (
            "$pre = New-Object System.Speech.Recognition.Choices;"
            + "".join(f"$pre.Add({_ps_quote(p)});" for p in prefixes)
            + "$nm = New-Object System.Speech.Recognition.Choices;"
            + "".join(f"$nm.Add({_ps_quote(n)});" for n in names)
            + "$cmd = New-Object System.Speech.Recognition.Choices;"
            + "".join(f"$cmd.Add({_ps_quote(p)});" for p in command_phrases(lang))
            + "$wb = New-Object System.Speech.Recognition.GrammarBuilder; $wb.Culture = $culture;"
            "$wb.Append($pre, 0, 1); $wb.Append($nm); $wb.Append($cmd, 0, 1);"
            "$wg = New-Object System.Speech.Recognition.Grammar($wb); $wg.Name = 'wake'; $r.LoadGrammar($wg);"
            + (act_grammar_ps(lang, vocab, "W") + act_grammar_ps(lang, vocab, "A") +
               # nom + action (« Bakos, ouvre Excel ») ; action seule quand l'assistant attend la question
               "$pre2 = New-Object System.Speech.Recognition.Choices;"
               + "".join(f"$pre2.Add({_ps_quote(p)});" for p in prefixes)
               + "$nm2 = New-Object System.Speech.Recognition.Choices;"
               + "".join(f"$nm2.Add({_ps_quote(n)});" for n in names)
               + "$wa = New-Object System.Speech.Recognition.GrammarBuilder; $wa.Culture = $culture;"
               "$wa.Append($pre2, 0, 1); $wa.Append($nm2); $wa.Append($actsW);"
               "$wag = New-Object System.Speech.Recognition.Grammar($wa); $wag.Name = 'wakeact'; $r.LoadGrammar($wag);"
               "$ag = New-Object System.Speech.Recognition.Grammar((New-Object System.Speech.Recognition.GrammarBuilder"
               "($actsA))); $ag.Name = 'act'; $r.LoadGrammar($ag);" if vocab else "") +
            "$ob = New-Object System.Speech.Recognition.GrammarBuilder; $ob.Culture = $culture; $ob.AppendWildcard();"
            "$og = New-Object System.Speech.Recognition.Grammar($ob); $og.Name = 'other'; $r.LoadGrammar($og);"
            f"$parent = {os.getpid()};"
            "[Console]::Out.WriteLine('READY'); [Console]::Out.Flush();"
            "while ($true) {"
            "  if (-not (Get-Process -Id $parent -ErrorAction SilentlyContinue)) { exit };"
            "  $res = $r.Recognize([TimeSpan]::FromSeconds(20));"
            "  if ($res) { [Console]::Out.WriteLine($res.Grammar.Name + \"`t\" + "
            "[math]::Round($res.Confidence, 2) + \"`t\" + $res.Text); [Console]::Out.Flush() }"
            "  else { [Console]::Out.WriteLine('TICK'); [Console]::Out.Flush() }"   # signe de vie (silence)
            "}")

    def _run_win(self):
        while self.running:
            lang, name, aliases = self.get_lang(), self.get_name(), tuple(self.get_aliases())
            vocab = self.get_vocab()
            key = (lang, name, aliases, self._vocab_key(vocab))
            try:
                self._proc = run_ps(self._win_script(lang, name, aliases, vocab))
            except OSError as ex:
                self.log(f"écoute impossible : {ex}")
                self.running = False
                return
            self.log("écoute démarrée (Windows)")
            for raw in self._proc.stdout:
                if not self.running:
                    break
                line = raw.decode("utf-8", "ignore").rstrip("\r\n")
                if line.count("\t") >= 2:
                    grammar, conf, text = line.split("\t", 2)
                    try:
                        self._heard_win(text, grammar, float(conf.replace(",", ".")))
                    except Exception:  # noqa: BLE001
                        pass
                # le nom, ses variantes, la langue ou les applications ont changé : nouvelle grammaire
                if (self.get_lang(), self.get_name(), tuple(self.get_aliases()),
                        self._vocab_key(self.get_vocab())) != key:
                    break
            if self._proc.poll() is None:
                self._proc.kill()
            if self.running:
                time.sleep(1)   # relance (réglages changés, ou processus arrêté)
        self.log("écoute arrêtée")

    @staticmethod
    def _vocab_key(vocab):
        return None if not vocab else (tuple(vocab.get("apps", ())), tuple(vocab.get("places", ())))

    def _heard_win(self, text, grammar, conf):
        text = text.strip()
        if not text:
            return
        if self.is_speaking():
            self.log(f"ignoré (l'assistant parle) : {text}")
            return
        armed = time.time() < self.armed_until
        if grammar == "other":   # conversation ordinaire, absorbée par l'attrape-tout
            if armed:            # on attendait une question, mais ce n'est pas une commande connue
                self.armed_until = 0
                self.log("commande non reconnue (hors des phrases connues)")
                self.on_wake("…")
            return
        if grammar in ("commands", "act"):
            if armed and conf >= 0.3:
                self.armed_until = 0
                self.log(f"commande : {text} ({conf:.2f})")
                self.on_wake(text)
            else:
                self.log(f"commande sans le nom, ignorée : {text} ({conf:.2f})")
            return
        # grammaire « wake » : le nom, suivi ou non d'une commande
        ok, rest = match_name(text, self.get_name(), phonetic_variants(self.get_name())[1:] + list(self.get_aliases()))
        if not ok:   # le nom reconnu est une variante phonétique : on retire simplement le préfixe et le nom
            words = text.split()
            words = words[1:] if words and words[0].lower() in ("dis", "hey", "ok", "salut", "hi") else words
            rest = " ".join(words[1:])
        seuil = 0.25 if not rest else 0.4 if grammar == "wakeact" else 0.45   # le nom seul : confiance faible
        self.log(f"entendu : {text} ({grammar}, {conf:.2f}) → {'nom reconnu' if conf >= seuil else 'trop incertain'}")
        if conf < seuil:
            return
        self.armed_until = 0
        if not rest:
            self.arm()
        self.on_wake(rest)

    def _run(self, Speech, NSLocale):
        import AVFoundation
        st = self._st = {"gen": 0, "voice_last": None, "voiced": 0, "levels": [], "seg_start": None}
        lang = self.get_lang()
        rec = Speech.SFSpeechRecognizer.alloc().initWithLocale_(
            NSLocale.localeWithLocaleIdentifier_("fr-FR" if lang == "fr" else "en-US"))
        on_device = bool(rec.supportsOnDeviceRecognition())

        # le moteur ne traite qu'une requête à la fois : la suivante n'est ouverte qu'après le résultat
        st["req"], st["task"], st["req_start"], st["waiting"] = None, None, time.time(), False

        def new_request():
            st["gen"] += 1
            gen = st["gen"]
            req = Speech.SFSpeechAudioBufferRecognitionRequest.alloc().init()
            req.setShouldReportPartialResults_(False)
            if on_device:
                req.setRequiresOnDeviceRecognition_(True)
            name = self.get_name()
            req.setContextualStrings_([name, f"Dis {name}", f"Hey {name}"])   # le nom n'est pas dans le dictionnaire
            box = {"done": False}

            def handler(result, error):
                if box["done"]:
                    return
                if result is not None and result.isFinal():
                    box["done"] = True
                    st["waiting"] = False
                    self._heard(str(result.bestTranscription().formattedString()))
                elif error is not None:
                    box["done"] = True
                    st["waiting"] = False
                    if box.get("ended"):
                        self.log(f"requête {gen} : {error.localizedDescription()}")

            st["box"] = box
            st["task"] = rec.recognitionTaskWithRequest_resultHandler_(req, handler)
            st["req"], st["req_start"] = req, time.time()

        def end_request():
            """Fin de phrase : demande le résultat final ; plus de son envoyé jusqu'à la réponse."""
            req = st["req"]
            st["req"], st["waiting"], st["wait_start"] = None, True, time.time()
            st["box"]["ended"] = True
            try:
                req.endAudio()
            except Exception:  # noqa: BLE001
                st["waiting"] = False

        def cancel_request():
            st["box"]["done"] = True
            st["req"] = None
            try:
                st["task"].cancel()
            except Exception:  # noqa: BLE001
                pass

        engine = AVFoundation.AVAudioEngine.alloc().init()
        node = engine.inputNode()
        fmt = node.outputFormatForBus_(0)

        def tap(buf, when):
            try:
                ch, n = buf.floatChannelData()[0], int(buf.frameLength())
                level = max(abs(ch[i]) for i in range(0, n, 16))
                lv = st["levels"]
                lv.append(level)
                if len(lv) > 50:
                    del lv[0]
                floor = sorted(lv)[len(lv) // 4] if lv else 0   # bruit de fond (quart le plus calme)
                if level > max(0.03, floor * 3):
                    st["voice_last"] = time.time()
                    st["voiced"] += 1
                    st["seg_start"] = st["seg_start"] or time.time()
            except Exception:  # noqa: BLE001
                pass
            req = st["req"]
            if req is not None:
                try:
                    req.appendAudioPCMBuffer_(buf)
                except Exception:  # noqa: BLE001
                    pass

        new_request()
        node.installTapOnBus_bufferSize_format_block_(0, 1024, fmt, tap)
        engine.prepare()
        ok, _err = engine.startAndReturnError_(None)
        if not ok:
            node.removeTapOnBus_(0)
            self.running = False
            self.log("micro indisponible")
            return
        self.log("écoute démarrée")

        def watch():
            while self.running:
                time.sleep(0.05)
                now = time.time()
                if st["waiting"]:   # résultat en cours de calcul
                    if now - st["wait_start"] > 6:
                        st["waiting"] = False
                    continue
                if st["req"] is None:   # résultat reçu : requête suivante
                    st["voice_last"], st["voiced"], st["seg_start"] = None, 0, None
                    new_request()
                    continue
                v = st["voice_last"]
                if v is not None and st["voiced"] >= 3 and now - v > 0.9:   # fin d'une phrase
                    self.log(f"phrase découpée ({st['voiced']} blocs voisés, {now - (st['seg_start'] or now):.1f} s)")
                    end_request()
                elif v is not None and st["voiced"] < 3 and now - v > 0.9:   # bruit bref : oublié
                    st["voice_last"], st["voiced"], st["seg_start"] = None, 0, None
                elif st["seg_start"] and now - st["seg_start"] > 15:   # parole sans fin (télé, musique)
                    cancel_request()
                elif v is None and now - st["req_start"] > self.ROTATE:   # long silence : requête neuve
                    cancel_request()
            try:
                engine.stop()
                node.removeTapOnBus_(0)
                if st["req"] is not None:
                    cancel_request()
            except Exception:  # noqa: BLE001
                pass
            self.log("écoute arrêtée")

        threading.Thread(target=watch, daemon=True).start()

    def _heard(self, text):
        text = text.strip()
        if not text:
            return
        if self.is_speaking():   # l'assistant s'entend lui-même parler : on ignore
            self.log(f"ignoré (l'assistant parle) : {text}")
            return
        if time.time() < self.armed_until:
            self.armed_until = 0
            self.log(f"commande : {text}")
            self.on_wake(text)
            return
        ok, rest = match_name(text, self.get_name(), self.get_aliases())
        self.log(f"entendu : {text} → {'nom reconnu' if ok else 'ignoré'}")
        if ok:
            if not rest:
                self.arm()
            self.on_wake(rest)

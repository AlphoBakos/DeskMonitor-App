# -*- coding: utf-8 -*-
"""Synthèse vocale.
- Voix neuronales de Microsoft (Vivienne, Denise, Henri… : intonation humaine), quand internet est disponible ;
- sinon, hors ligne : `say` sur macOS ; sous Windows, voix « OneCore » (Julie, Paul, Hortense…) via winsdk,
  ou System.Speech (SAPI) en dernier recours.
Une phrase à la fois, dans un thread."""
import asyncio
import queue
import time
import subprocess
import sys
import threading

from i18n import tr

IS_MAC = sys.platform == "darwin"
SYSTEM = "__system__"   # voix choisie dans les réglages du système (sur Mac : peut être une voix Siri)
IS_WIN = sys.platform == "win32"

_WIN_SCRIPT = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.Rate = {rate};"
    "if ('{voice}') {{ try {{ $s.SelectVoice('{voice}') }} catch {{}} }}"
    "else {{ $fr = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'fr*' }} | "
    "Select-Object -First 1; if ($fr) {{ $s.SelectVoice($fr.VoiceInfo.Name) }} }};"
    "$s.Speak([Console]::In.ReadToEnd())"
)


# voix « gadget » de macOS : à écarter des annonces
NOVELTY = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Wobble", "Fred", "Good News",
           "Jester", "Junior", "Organ", "Superstar", "Ralph", "Trinoids", "Whisper", "Zarvox", "Grandma", "Grandpa"}
REGIONS = {"fr_FR": "France", "fr_CA": "Canada", "fr_BE": "Belgique", "fr_CH": "Suisse", "en_US": "US",
           "en_GB": "Royaume-Uni", "en_AU": "Australie", "en_IE": "Irlande", "en_IN": "Inde", "en_ZA": "Afrique du Sud"}
PREFERRED = {"fr": ("Thomas", "Audrey", "Aurélie", "Jacques", "Flo", "Amélie",
                    "Microsoft Julie", "Microsoft Paul", "Microsoft Hortense"),
             "en": ("Ava", "Zoe", "Samantha", "Allison", "Daniel", "Karen", "Moira", "Flo",
                    "Microsoft Aria", "Microsoft Jenny", "Microsoft Guy", "Microsoft Zira", "Microsoft David")}


# ----- voix neuronales (en ligne) -------------------------------------------------------------------
NEURAL_PREFIX = "neural:"
NEURAL = {
    "fr": [("fr-FR-VivienneMultilingualNeural", "Vivienne"), ("fr-FR-DeniseNeural", "Denise"),
           ("fr-FR-HenriNeural", "Henri"), ("fr-FR-RemyMultilingualNeural", "Rémy"), ("fr-FR-EloiseNeural", "Éloïse"),
           ("fr-CA-SylvieNeural", "Sylvie (Canada)"), ("fr-CA-AntoineNeural", "Antoine (Canada)"),
           ("fr-BE-CharlineNeural", "Charline (Belgique)"), ("fr-CH-ArianeNeural", "Ariane (Suisse)")],
    "en": [("en-US-AvaMultilingualNeural", "Ava"), ("en-US-AndrewMultilingualNeural", "Andrew"),
           ("en-US-EmmaMultilingualNeural", "Emma"), ("en-US-BrianMultilingualNeural", "Brian"),
           ("en-GB-SoniaNeural", "Sonia (UK)"), ("en-GB-RyanNeural", "Ryan (UK)")],
}


def neural_ok():
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _neural_file(text, voice, rate):
    """Phrase → fichier MP3 (mis en cache : les réponses fréquentes partent instantanément)."""
    import hashlib
    import os
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "deskmonitor-voix")
    os.makedirs(folder, exist_ok=True)
    pct = max(-50, min(100, round((rate / 185 - 1) * 100)))
    path = os.path.join(folder, hashlib.sha1(f"{voice}|{pct}|{text}".encode("utf-8")).hexdigest()[:20] + ".mp3")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    import edge_tts

    async def run():
        await edge_tts.Communicate(text, voice, rate=f"{pct:+d}%").save(path + ".part")
    try:
        asyncio.run(asyncio.wait_for(run(), timeout=8))
        os.replace(path + ".part", path)
    except BaseException:
        try:
            os.remove(path + ".part")
        except OSError:
            pass
        raise
    files = sorted((os.path.join(folder, f) for f in os.listdir(folder)), key=os.path.getmtime)
    for old in files[:-120]:   # cache limité
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def _log_error(what):
    """Trace de l'erreur dans le dossier temporaire (deskmonitor-voix/erreurs.log), pour le diagnostic."""
    import os
    import tempfile
    import traceback
    try:
        folder = os.path.join(tempfile.gettempdir(), "deskmonitor-voix")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "erreurs.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + f"  {what}\n" + traceback.format_exc() + "\n")
    except OSError:
        pass


def prefetch(texts, voice, rate):
    """Prépare en arrière-plan les réponses courtes et fréquentes : elles partent ensuite sans délai."""
    if not voice.startswith(NEURAL_PREFIX) or not neural_ok():
        return

    def run():
        for t in texts:
            try:
                _neural_file(t, voice[len(NEURAL_PREFIX):], rate)
            except BaseException:  # noqa: BLE001
                _log_error("préparation des réponses")
                return
    threading.Thread(target=run, daemon=True).start()


def _mci(cmd):
    import ctypes
    buf = ctypes.create_unicode_buffer(128)
    err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 128, None)
    return err, buf.value


# ----- Windows : voix « OneCore » (plus naturelles, sans lancer PowerShell) ----------------------
def _onecore():
    """Module de synthèse de Windows (winsdk), ou None s'il n'est pas installé."""
    if not IS_WIN:
        return None
    try:
        from winsdk.windows.media.speechsynthesis import SpeechSynthesizer
        return SpeechSynthesizer
    except Exception:  # noqa: BLE001
        return None


def _onecore_voices():
    """{nom: langue} des voix OneCore installées (« Microsoft Julie » : « fr-FR »)."""
    synth = _onecore()
    try:
        return {v.display_name: v.language for v in synth.all_voices} if synth else {}
    except Exception:  # noqa: BLE001
        return {}


async def _onecore_wav(text, voice, rate):
    """Phrase → fichier WAV en mémoire (voix OneCore)."""
    from winsdk.windows.storage.streams import DataReader
    synth_cls = _onecore()
    s = synth_cls()
    v = next((v for v in synth_cls.all_voices if v.display_name == voice), None)
    if v is not None:
        s.voice = v
    try:
        s.options.speaking_rate = max(0.5, min(3.0, rate / 185))  # 185 mots/min ≈ vitesse normale
    except Exception:  # noqa: BLE001  (Windows 10 ancien : pas de réglage de vitesse)
        pass
    stream = await s.synthesize_text_to_stream_async(text)
    reader = DataReader(stream.get_input_stream_at(0))
    await reader.load_async(stream.size)
    buf = bytearray(stream.size)
    reader.read_bytes(buf)
    return bytes(buf)


def _wav_seconds(data):
    import io
    import wave
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return 0.0


def voices(lang="fr"):
    """{nom: libellé} des voix installées pour une langue (« fr » ou « en »)."""
    out = {}
    if neural_ok():   # voix neuronales d'abord : les plus naturelles
        for vid, label in NEURAL.get(lang, ()):
            out[NEURAL_PREFIX + vid] = f"{label} ({tr('neuronale, très naturelle, en ligne')})"
    try:
        if IS_MAC:
            import re
            txt = subprocess.run(["say", "-v", "?"], capture_output=True, timeout=5).stdout.decode("utf-8", "ignore")
            for line in txt.splitlines():
                m = re.match(r"^(.*?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
                if not m or not m.group(2).startswith(lang + "_"):
                    continue
                name, loc = m.group(1).strip(), m.group(2)
                short = name.split(" (")[0]
                if short in NOVELTY:
                    continue
                quality = " premium" if "Premium" in name else " améliorée" if "Enhanced" in name else ""
                out[name] = f"{short}{quality} ({REGIONS.get(loc, loc)})"
        elif IS_WIN:
            for name, culture in _onecore_voices().items():   # voix naturelles d'abord
                if culture.lower().startswith(lang):
                    out[name] = f"{name.replace('Microsoft ', '')} ({tr('naturelle')})"
            txt = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                 ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Culture.Name + '|' + $_.VoiceInfo.Name }"],
                capture_output=True, timeout=15, creationflags=0x08000000).stdout.decode("utf-8", "ignore")
            for line in txt.splitlines():
                culture, _, name = line.strip().partition("|")
                # « Microsoft Hortense Desktop » existe aussi en OneCore : on ne garde que la version naturelle
                if culture.startswith(lang) and name and name.replace(" Desktop", "") not in out:
                    out[name] = name.replace(" Desktop", "") + f" ({tr('classique')})"
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def offline_voice(lang="fr"):
    """Meilleure voix hors ligne (secours quand la voix neuronale ne répond pas)."""
    v = {n: lbl for n, lbl in voices(lang).items() if not n.startswith(NEURAL_PREFIX)}
    for pref in PREFERRED.get(lang, ()):
        for n in v:
            if n.split(" (")[0] == pref:
                return n
    natural = [n for n in v if "naturelle" in v[n]]
    return natural[0] if natural else next(iter(v), "")


def french_voices():
    return voices("fr")


def default_voice(lang="fr"):
    """Meilleure voix installée : Premium, puis améliorée, puis les voix habituelles de la langue."""
    v = voices(lang)
    neural = [n for n in v if n.startswith(NEURAL_PREFIX)]
    if neural:
        return neural[0]
    home = "France" if lang == "fr" else "US"
    for tag in ("Premium", "Enhanced", "amélioré"):
        best = [n for n in v if tag.lower() in n.lower()]
        if best:
            return sorted(best, key=lambda n: home not in v[n])[0]
    for pref in PREFERRED.get(lang, ()):
        for n in sorted(v, key=lambda n: home not in v[n]):
            if n.split(" (")[0] == pref:
                return n
    natural = [n for n in v if "naturelle" in v[n]]   # Windows : une voix OneCore plutôt que SAPI
    return natural[0] if natural else next(iter(v), "")


class Voice:
    def __init__(self):
        self._q = queue.Queue()
        self._proc = None
        threading.Thread(target=self._worker, daemon=True).start()

    def say(self, text, voice="", rate=185, urgent=False):
        """Ajoute une phrase à dire. urgent=True : coupe ce qui est en cours et passe devant."""
        if not text or not (IS_MAC or IS_WIN):
            return
        if urgent:
            self.stop()
        self._q.put((text, voice, rate))

    def speaking(self):
        """Vrai pendant qu'une phrase est dite (et un court instant après, l'écho de la pièce)."""
        p = self._proc
        if (p is not None and p.poll() is None) or not self._q.empty() or time.time() < self._play_until:
            self._quiet_since = None
            return True
        return time.time() - (getattr(self, "_ended", 0) or 0) < 1.0

    _play_until = 0.0   # Windows (voix OneCore) : fin prévue de la lecture en cours
    _neural_down = 0.0  # voix neuronale injoignable : on passe hors ligne jusqu'à cette heure

    def stop(self):
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass
        if IS_WIN and time.time() < self._play_until:
            import winsound
            winsound.PlaySound(None, 0)   # coupe la lecture en cours
            self._play_until = 0.0

    def _speak_onecore(self, text, voice, rate):
        """Windows : voix naturelle. Retourne False si elle est indisponible (on passe alors par SAPI)."""
        if not _onecore():
            return False
        names = _onecore_voices()
        if voice and voice != SYSTEM and voice not in names:
            return False   # voix SAPI « classique » (ex. Zira) : pas disponible en OneCore
        import os
        import tempfile
        import winsound
        data = asyncio.run(_onecore_wav(text, "" if voice == SYSTEM else voice, rate))
        # winsound ne joue pas un son en mémoire de façon asynchrone : on passe par un fichier temporaire
        path = os.path.join(tempfile.gettempdir(), "deskmonitor-voix.wav")
        with open(path, "wb") as f:
            f.write(data)
        self._play_until = time.time() + _wav_seconds(data) + 0.1
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        while time.time() < self._play_until:   # stop() remet _play_until à 0
            time.sleep(0.05)
        return True

    def _speak_neural(self, text, voice, rate):
        """Voix neuronale : synthèse en ligne (cache), lecture MP3. False si indisponible."""
        if time.time() < self._neural_down or not neural_ok():
            return False
        try:
            path = _neural_file(text, voice[len(NEURAL_PREFIX):], rate)
        except BaseException:  # noqa: BLE001  hors ligne, service indisponible…
            self._neural_down = time.time() + 300
            _log_error("synthèse neuronale")
            return False
        if IS_MAC:
            self._proc = subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._proc.wait()
            return True
        _mci("close dmvoix")
        err = _mci(f'open "{path}" type mpegvideo alias dmvoix')[0]
        if err:
            try:
                raise OSError(f"MCI open : erreur {err}")
            except OSError:
                _log_error("lecture MP3")
            return False
        err, length = _mci("status dmvoix length")
        secs = int(length) / 1000 if not err and length.isdigit() else 10
        _mci("play dmvoix")
        self._play_until = time.time() + secs + 0.15
        while time.time() < self._play_until:   # stop() remet _play_until à 0
            time.sleep(0.04)
        _mci("stop dmvoix")
        _mci("close dmvoix")
        return True

    def _worker(self):
        while True:
            text, voice, rate = self._q.get()
            try:
                if voice.startswith(NEURAL_PREFIX):
                    if self._speak_neural(text, voice, rate):
                        continue
                    lang = voice[len(NEURAL_PREFIX):][:2]   # hors ligne : meilleure voix installée
                    fb = self.__dict__.setdefault("_fallback", {})
                    voice = fb.get(lang) or offline_voice(lang)
                    fb[lang] = voice
                if IS_WIN and self._speak_onecore(text, voice, rate):
                    continue
                if IS_MAC:
                    cmd = ["say", "-r", str(int(rate)), "-f", "-"]
                    if voice and voice != SYSTEM:
                        cmd[1:1] = ["-v", voice]
                    self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL)
                else:
                    # SAPI : vitesse de -10 à 10 ; 185 mots/min ≈ 0
                    r = max(-10, min(10, round((rate - 185) / 15)))
                    script = _WIN_SCRIPT.format(rate=r, voice="" if voice == SYSTEM else voice.replace("'", ""))
                    self._proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                                                  stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL, creationflags=0x08000000)
                self._proc.communicate(text.encode("utf-8"), timeout=120)
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
            finally:
                self._proc = None
                self._ended = time.time()

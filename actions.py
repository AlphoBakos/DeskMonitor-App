# -*- coding: utf-8 -*-
"""Actions de l'assistant : lancer une application, ouvrir un dossier ou un fichier, faire une recherche sur
internet. Les noms dits à voix haute sont rapprochés des vrais noms (« excel » → « Microsoft Excel »,
« téléchargement » → dossier Téléchargements, « rapport de stage » → Rapport_stage_final.docx…)."""
import difflib
import os
import re
import sys
import threading
import time
import unicodedata
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def norm(text):
    t = unicodedata.normalize("NFD", str(text).lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", t))


def _tokens_orig(text):
    return re.findall(r"[^\W_]+", str(text).lower())


# --------------------------------------------------------------------------- #
#  Comprendre la demande
# --------------------------------------------------------------------------- #
OPEN_VERBS = ["ouvre moi", "ouvre", "ouvrir", "lance moi", "lance", "lancer", "demarre", "demarrer", "execute",
              "affiche moi", "va sur", "va dans", "open", "launch", "start", "run", "go to"]
SEARCH_VERBS = ["fais une recherche sur", "fais une recherche", "recherche sur internet", "cherche sur internet",
                "recherche sur google", "cherche sur google", "recherche", "cherche moi", "cherche", "trouve moi",
                "google", "search the web for", "search for", "search", "look up", "google"]
FOLDER_WORDS = ["le dossier", "dossier", "le repertoire", "repertoire", "the folder", "folder", "mes", "mon", "ma"]
FILE_WORDS = ["le fichier", "fichier", "le document", "document", "the file", "file"]
FILLER = ["s il te plait", "s il vous plait", "stp", "svp", "please", "pour moi", "maintenant", "vite"]

SITES = {   # « cherche … sur youtube »
    "youtube": "https://www.youtube.com/results?search_query={}",
    "wikipedia": "https://fr.wikipedia.org/w/index.php?search={}",
    "google maps": "https://www.google.com/maps/search/{}", "maps": "https://www.google.com/maps/search/{}",
    "amazon": "https://www.amazon.fr/s?k={}", "github": "https://github.com/search?q={}",
    "google images": "https://www.google.com/search?tbm=isch&q={}", "images": "https://www.google.com/search?tbm=isch&q={}",
    "google": "https://www.google.com/search?q={}",
}
WEBSITES = {"youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
            "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
            "netflix": "https://www.netflix.com", "github": "https://github.com", "chatgpt": "https://chatgpt.com",
            "wikipedia": "https://fr.wikipedia.org", "linkedin": "https://www.linkedin.com",
            "twitter": "https://x.com", "whatsapp": "https://web.whatsapp.com", "google maps": "https://maps.google.com"}


def _strip(rest, words):
    for w in sorted(words, key=len, reverse=True):
        if rest == w or rest.startswith(w + " "):
            return rest[len(w):].strip(), True
    return rest, False


def _original(text, q):
    """Même suite de mots que q, mais avec les accents de la phrase d'origine (« crêpes » et non « crepes »)."""
    orig = re.findall(r"[^\W_]+", str(text).lower())
    plain = [norm(w) for w in orig]
    qw = q.split()
    for i in range(len(plain) - len(qw) + 1):
        if plain[i:i + len(qw)] == qw:
            return " ".join(orig[i:i + len(qw)])
    return q


def parse(text):
    """(« open », cible, genre) / (« search », requête, site) / None. genre : « folder », « file » ou « any »."""
    t = " " + norm(text) + " "
    for f in FILLER:
        t = t.replace(" " + f + " ", " ")
    t = t.strip()
    # « est-ce que tu peux ouvrir… », « peux-tu lancer… »
    t = re.sub(r"^(est ce que )?(tu peux|peux tu|pourrais tu|tu pourrais|je veux|je voudrais|j aimerais|"
               r"can you|could you|please|i want to|i d like to)\s+", "", t)
    for v in sorted(SEARCH_VERBS, key=len, reverse=True):
        if t.startswith(v + " "):
            q = t[len(v):].strip()
            site = "google"
            m = re.search(r"\s+(sur|dans|on)\s+(youtube|wikipedia|google maps|maps|amazon|github|google images|"
                          r"images|google)$", q)
            if m:
                site, q = m.group(2), q[:m.start()].strip()
            q = re.sub(r"^(des |du |de la |de l |de |d |les |la |le |l |un |une |a propos de |sur |for |about )",
                       "", q).strip()
            return ("search", _original(text, q), site) if q else None
    for v in sorted(OPEN_VERBS, key=len, reverse=True):
        if t.startswith(v + " "):
            rest = t[len(v):].strip()
            if rest in ("la musique", "music", "the music"):
                return None   # « lance la musique » : commande de lecture
            if rest in SPECIAL or rest in ALIASES:
                return "open", _original(text, rest), "any"
            rest, is_file = _strip(rest, FILE_WORDS)
            rest, is_folder = _strip(rest, FOLDER_WORDS)
            rest = re.sub(r"^(l |le |la |les |the |un |une |application |l application |app |logiciel |"
                          r"le logiciel |programme |le programme |site |le site )", "", rest).strip()
            rest = re.sub(r"^(application |app |logiciel |programme |site )", "", rest).strip()
            if not rest:
                return None
            return "open", _original(text, rest), "file" if is_file else "folder" if is_folder else "any"
    return None


# --------------------------------------------------------------------------- #
#  Dossiers et fichiers
# --------------------------------------------------------------------------- #
def known_folders():
    """{nom parlé: chemin} des dossiers habituels."""
    home = Path.home()
    out = {}

    def add(path, *names):
        p = Path(path)
        if p.is_dir():
            for n in names:
                out[n] = str(p)

    shell = {}
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                for key, val in (("Desktop", "Desktop"), ("Personal", "Documents"), ("My Pictures", "Pictures"),
                                 ("My Music", "Music"), ("My Video", "Videos"),
                                 ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")):
                    try:
                        shell[val] = os.path.expandvars(winreg.QueryValueEx(k, key)[0])
                    except OSError:
                        pass
        except OSError:
            pass
    add(shell.get("Downloads", home / "Downloads"), "telechargements", "telechargement", "downloads", "download")
    add(shell.get("Documents", home / "Documents"), "documents", "document", "mes documents")
    add(shell.get("Desktop", home / "Desktop"), "bureau", "desktop")
    add(shell.get("Pictures", home / "Pictures"), "images", "photos", "image", "pictures")
    add(shell.get("Music", home / "Music"), "musique", "musiques", "music")
    add(shell.get("Videos", home / "Videos"), "videos", "video", "films")
    add(home, "dossier personnel", "mon dossier", "home", "utilisateur")
    if os.getenv("OneDrive"):
        add(os.getenv("OneDrive"), "onedrive", "one drive")
    return out


SPECIAL = {   # emplacements du système
    "ce pc": "shell:MyComputerFolder", "poste de travail": "shell:MyComputerFolder", "this pc": "shell:MyComputerFolder",
    "corbeille": "shell:RecycleBinFolder", "recycle bin": "shell:RecycleBinFolder",
    "parametres": "ms-settings:", "settings": "ms-settings:", "reglages": "ms-settings:",
    "panneau de configuration": "shell:ControlPanelFolder", "control panel": "shell:ControlPanelFolder",
    # l'Explorateur s'ouvre par Windows lui-même : ne dépend pas de la liste des applications
    "explorateur de fichiers": "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}", "explorateur": "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}", "explorateur windows": "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}",
    "l explorateur": "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}", "mes fichiers": "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}", "file explorer": "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}",
}


SPECIAL_LABELS = {"explorateur de fichiers": "l'Explorateur de fichiers", "explorateur": "l'Explorateur de fichiers",
                  "explorateur windows": "l'Explorateur de fichiers", "l explorateur": "l'Explorateur de fichiers",
                  "mes fichiers": "l'Explorateur de fichiers", "file explorer": "File Explorer", "ce pc": "Ce PC", "poste de travail": "Ce PC", "this pc": "This PC", "corbeille": "la corbeille",
                  "recycle bin": "the recycle bin", "parametres": "les paramètres de Windows",
                  "settings": "Windows settings", "reglages": "les réglages de Windows",
                  "panneau de configuration": "le panneau de configuration", "control panel": "the control panel"}
SITE_LABELS = {"youtube": "YouTube", "gmail": "Gmail", "google": "Google", "facebook": "Facebook",
               "instagram": "Instagram", "netflix": "Netflix", "github": "GitHub", "chatgpt": "ChatGPT",
               "wikipedia": "Wikipédia", "linkedin": "LinkedIn", "twitter": "X", "whatsapp": "WhatsApp",
               "google maps": "Google Maps"}


class FileIndex:
    """Index des fichiers et dossiers de l'utilisateur (bureau, documents, téléchargements…), reconstruit en
    arrière-plan toutes les 10 minutes. Recherche par nom approché."""
    SKIP = {"node_modules", ".git", "__pycache__", "appdata", ".venv", "venv", "site-packages", "build", "dist",
            "$recycle.bin", ".cache", ".idea", ".vscode"}
    MAX = 40000

    def __init__(self):
        self.items = []     # (nom normalisé, chemin, est un dossier)
        self.stamp = 0.0
        self._busy = False

    def refresh(self, force=False):
        if self._busy or (not force and time.time() - self.stamp < 600):
            return
        self._busy = True
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        items, seen = [], set()
        roots = list(dict.fromkeys(known_folders().values()))
        try:
            for root in roots:
                base_depth = root.rstrip("\\/").count(os.sep)
                for dirpath, dirnames, filenames in os.walk(root):
                    depth = dirpath.count(os.sep) - base_depth
                    dirnames[:] = [d for d in dirnames if d.lower() not in self.SKIP and not d.startswith(".")]
                    if depth >= 4:
                        dirnames[:] = []
                    for d in dirnames:
                        p = os.path.join(dirpath, d)
                        if p not in seen:
                            seen.add(p)
                            items.append((norm(d), p, True))
                    for f in filenames:
                        if f.startswith((".", "~$")) or f.lower().endswith((".tmp", ".ini", ".lnk.bak")):
                            continue
                        p = os.path.join(dirpath, f)
                        if p not in seen:
                            seen.add(p)
                            items.append((norm(os.path.splitext(f)[0]), p, False))
                    if len(items) > self.MAX:
                        break
            self.items, self.stamp = items, time.time()
        finally:
            self._busy = False

    def find(self, query, kind="any"):
        q = norm(query)
        if not q or not self.items:
            return None
        qw = set(q.split())
        best = None
        for name, path, is_dir in self.items:
            if kind == "folder" and not is_dir or kind == "file" and is_dir:
                continue
            if name == q:
                score = 3.0
            elif qw and qw <= set(name.split()):
                score = 2.0 + len(qw) / max(1, len(name.split()))
            elif q in name:
                score = 1.6
            else:
                r = difflib.SequenceMatcher(None, q, name).ratio()
                if r < 0.72:
                    continue
                score = r
            score += 0.05 if is_dir and kind != "file" else 0
            try:
                score += min(0.2, max(0.0, (os.path.getmtime(path) - time.time() + 90 * 86400) / (90 * 86400) * 0.2))
            except OSError:
                continue
            if best is None or score > best[0]:
                best = (score, path, is_dir)
        return best[1:] if best else None

    def spoken_names(self, limit=150):
        """Noms de dossiers proches de la racine, proposés au moteur de reconnaissance."""
        out = []
        for name, path, is_dir in self.items:
            if is_dir and 2 <= len(name) <= 30 and len(name.split()) <= 4:
                out.append(name)
            if len(out) >= limit:
                break
        return out


# --------------------------------------------------------------------------- #
#  Applications
# --------------------------------------------------------------------------- #
ALIASES = {   # façons courantes de dire le nom d'une application
    "word": "microsoft word", "excel": "microsoft excel", "powerpoint": "microsoft powerpoint",
    "outlook": "microsoft outlook", "teams": "microsoft teams", "edge": "microsoft edge", "chrome": "google chrome",
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "le navigateur": "google chrome", "navigateur": "google chrome", "la calculatrice": "calculatrice",
    "calculette": "calculatrice", "explorateur": "explorateur de fichiers", "l explorateur": "explorateur de fichiers",
    "l explorateur de fichiers": "explorateur de fichiers", "explorateur windows": "explorateur de fichiers",
    "mes fichiers": "explorateur de fichiers", "file explorer": "explorateur de fichiers",
    "bloc note": "bloc notes", "notepad": "bloc notes", "terminal": "terminal", "invite de commande": "invite de commandes",
    "gestionnaire des taches": "gestionnaire des taches", "spotify": "spotify", "discord": "discord",
}


def find_app(query, apps):
    """Application la plus proche de ce qui a été dit, parmi apps = [{"name", "path", …}], ou None."""
    q = norm(query)
    if not q or not apps:
        return None
    queries = list(dict.fromkeys([q, norm(ALIASES.get(q, q))]))   # ce qui a été dit d'abord, puis l'alias
    names = [(norm(a["name"]), a) for a in apps]

    def shortest(hits):
        return min(hits, key=lambda h: h[0])[1] if hits else None

    stages = (
        lambda q: shortest([(len(n), a) for n, a in names if n == q]),
        # tous les mots dits sont dans le nom (« excel » ⊂ « microsoft excel »), le nom le plus court gagne
        lambda q: shortest([(len(n), a) for n, a in names if all(w in n.split() for w in q.split())]),
        lambda q: shortest([(len(n), a) for n, a in names if n.startswith(q) or (" " + q) in (" " + n)]),
        # mots collés ou séparés (« chat gpt » / « ChatGPT Classic », « fire fox » / « Firefox »)
        lambda q: shortest([(len(n), a) for n, a in names if n.replace(" ", "").startswith(q.replace(" ", ""))]),
    )
    for stage in stages:
        for qq in queries:
            hit = stage(qq)
            if hit is not None:
                return hit
    # dernier recours : orthographe approchée, seulement pour ce qui a été dit (pas l'alias) et très proche
    best = difflib.get_close_matches(q, [n for n, _ in names], n=1, cutoff=0.82)
    return next(a for n, a in names if n == best[0]) if best else None


def open_target(target):
    if target.startswith(("shell:", "ms-settings:")):
        if IS_WIN:
            import subprocess
            subprocess.Popen(["explorer.exe", target])
        return
    if target.startswith("http"):
        webbrowser.open(target)
        return
    if IS_WIN:
        os.startfile(target)  # noqa: S606
    else:
        import subprocess
        subprocess.Popen(["open", target])


def search_url(query, site="google"):
    return SITES.get(site, SITES["google"]).format(quote_plus(query))

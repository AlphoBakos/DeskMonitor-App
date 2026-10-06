# -*- coding: utf-8 -*-
"""
Bureau organisé : range automatiquement les raccourcis et dossiers du bureau
dans des panneaux thématiques (Jeux, Internet, Bureautique...).

- clic sur une icône          : ouvrir
- glisser une icône            : la déplacer vers un autre panneau / la réordonner
- clic sur le titre            : replier / déplier le panneau
- glisser le titre             : déplacer le panneau
- clic droit                   : options (déplacer, masquer, nouvelle catégorie...)

Aucun fichier n'est déplacé ni modifié : seul l'affichage est réorganisé.
"""

import ctypes
import json
import os
import re
import threading
import time
import struct
import subprocess
import sys
from pathlib import Path

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes

import anim
from core import (CONFIG_DIR, IS_MAC, STYLE_KEYS, TEXT_FONT, apply_corners, bind_right_click, blend as blend_hex,
                  bring_to_front, cfg_signature, no_activate, open_path, reveal_in_folder, win_blur)

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:  # les icônes seront remplacées par des emojis
    HAS_PIL = False

# (nom, emoji, mots-clés recherchés au début d'un mot du nom ou de la cible)
CATEGORIES = [
    ("Jeux", "🎮", [
        "steam", "epic games", "rockstar", "fivem", "riot", "valorant", "league of legends", "ubisoft",
        "uplay", "battle.net", "blizzard", "minecraft", "roblox", "gog", "xbox", "ea app", "origin",
        "fortnite", "gta", "grand theft", "call of duty", "counter-strike", "cs2", "overwatch", "genshin",
        "solitaire", "efootball", "game bar", "échecs", "chess",
        "playnite", "heroic", "bluestacks", "emulat", "retroarch", "jeu", "game", "steamapps",
        "steam://", "com.epicgames", "euro truck", "fifa", "fc 2", "rocket league", "apex"]),
    ("Internet", "🌐", [
        "chrome", "google chrome", "firefox", "edge", "brave", "opera", "vivaldi", "tor browser",
        "discord", "telegram", "whatsapp", "signal", "teams", "zoom", "skype", "slack", "messenger",
        "thunderbird", "filezilla", "qbittorrent", "utorrent", "linkedin", "safari", "mail", "messages", "facetime", "http://", "https://"]),
    ("Bureautique", "📝", [
        "word", "excel", "powerpoint", "onenote", "outlook", "access", "publisher", "acrobat",
        "adobe reader", "pdf", "libreoffice", "openoffice", "onlyoffice", "wps", "notion", "evernote",
        "obsidian", "office", "calculat", "to do", "calendrier", "courrier", "pages", "numbers", "keynote",
        "notes", "rappels", "reminders", "aperçu", "preview", "textedit"]),
    ("Développement", "💻", [
        "visual studio", "vs code", "vscode", "code", "cursor", "postman", "docker", "git", "github",
        "python", "pycharm", "intellij", "webstorm", "android studio", "node", "sublime", "notepad++",
        "terminal", "powershell", "putty", "winscp", "vmware", "virtualbox", "hyper-v", "wsl", "ubuntu",
        "claude", "xampp", "wamp", "mysql", "dbeaver", "figma", "unity", "unreal", "godot", "jetbrains",
        "mongodb", "packet tracer", "cisco", "wireshark", "gns3", "arduino", "eclipse", "netbeans",
        "chatgpt", "copilot", "ollama", "lm studio", "psql", "postgresql", "sql shell", "idle",
        "visual studio installer", "pgadmin", "xcode", "iterm"]),
    ("Multimédia", "🎬", [
        "vlc", "spotify", "itunes", "deezer", "obs studio", "obs64", "photoshop", "lightroom", "premiere",
        "after effects", "illustrator", "audacity", "gimp", "capcut", "davinci", "blender", "kdenlive",
        "handbrake", "netflix", "prime video", "disney", "youtube", "media player", "musique", "music",
        "photo", "video", "vidéo", "paint", "krita", "inkscape", "canva", "quran", "iptv", "kodi",
        "plex", "stremio", "molotov", "twitch", "shazam", "podcast", "radio", "films", "multimédia",
        "caméra", "enregistreur vocal", "clipchamp", "apple music", "musique", "imovie", "garageband",
        "final cut", "logic pro", "quicktime", "podcasts", "photo booth"]),
    ("Utilitaires", "🛠", [
        "winrar", "7-zip", "7zip", "ccleaner", "driver booster", "partition", "aomei", "minitool",
        "malwarebytes", "avast", "avg", "kaspersky", "norton", "bitdefender", "cpu-z", "gpu-z",
        "hwmonitor", "crystaldisk", "anydesk", "teamviewer", "rufus", "everything", "powertoys", "revo",
        "iobit", "deskmonitor", "vpn", "nordvpn", "keepass", "bitwarden",
        "megasync", "mega", "dropbox", "onedrive", "google drive", "icloud", "sharex", "greenshot",
        "lightshot", "logitech", "razer", "corsair", "msi afterburner", "msi center", "armoury", "nvidia", "amd software",
        "hp ", "translucenttb", "mobile connecté", "phone link", "wincmd", "windows commander",
        "total commander", "power automate"]),
    ("Système", "⚙", [
        "panneau de configuration", "control panel", "paramètres", "settings", "ce pc", "corbeille",
        "recycle", "explorateur de fichiers", "file explorer", "invite de commandes", "exécuter",
        "gestionnaire", "gestion de", "services", "éditeur du registre", "regedit", "observateur",
        "planificateur", "moniteur de ressources", "analyseur de performances", "informations système",
        "configuration du système", "défragmenter", "nettoyage de disque", "diagnostic", "narrateur",
        "loupe", "clavier visuel", "sous-titres", "accès vocal", "table des caractères", "pare-feu",
        "sécurité windows", "sauvegarde windows", "lecteur de récupération", "odbc", "iscsi",
        "stratégie", "outils windows", "bureau à distance", "assistance rapide", "enregistreur d’actions",
        "enregistreur d'actions", "microsoft store", "outil capture", "horloge", "bloc-notes",
        "pense-bête", "windows powershell", "app store", "finder", "moniteur d'activité", "activity monitor",
        "utilitaire de disque", "disk utility", "réglages système", "system settings", "préférences système"]),
]
FOLDERS, FILES, OTHERS = "Dossiers", "Fichiers", "Autres"
SPECIAL = [(FOLDERS, "📁"), (FILES, "📄"), (OTHERS, "✨")]
CUSTOM_EMOJI = "📌"
APP_EXT = {".lnk", ".url", ".exe", ".appref-ms", ".bat", ".cmd", ".app"}
IGNORED = {"desktop.ini", "thumbs.db"}

SYSTEM_ITEMS = [  # éléments système proposés dans « Dossiers »
    ("::{20D04FE0-3AEA-1069-A2D8-08002B30309D}", "Ce PC"),
    ("::{645FF040-5081-101B-9F08-00AA002F954E}", "Corbeille"),
]

_RULES = [(name, [re.compile(r"(?<![a-z0-9])" + re.escape(k)) for k in kws]) for name, _, kws in CATEGORIES]


# --------------------------------------------------------------------------- #
#  Lecture du bureau
# --------------------------------------------------------------------------- #
def desktop_dirs():
    dirs = []
    if IS_WIN:
        buf = ctypes.create_unicode_buffer(260)
        for csidl in (0x10, 0x19):  # bureau utilisateur, bureau public
            if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
                dirs.append(buf.value)
    else:
        dirs.append(str(Path.home() / "Desktop"))
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


def parse_lnk(path):
    """(cible, cible_est_un_dossier) d'un raccourci .lnk, sans COM."""
    try:
        with open(path, "rb") as f:
            data = f.read(65536)
        if len(data) < 76 or data[:4] != b"\x4c\x00\x00\x00":
            return "", False
        flags, attrs = struct.unpack_from("<II", data, 0x14)
        is_dir = bool(attrs & 0x10)
        pos = 76
        if flags & 0x01:  # HasLinkTargetIDList
            pos += 2 + struct.unpack_from("<H", data, pos)[0]
        target = ""
        if flags & 0x02:  # HasLinkInfo
            li = pos
            _, hsize, liflags, _, lbp = struct.unpack_from("<IIIII", data, li)
            if liflags & 0x01:
                if hsize >= 0x24:
                    start = li + struct.unpack_from("<I", data, li + 0x1C)[0]
                    end = start
                    while end + 1 < len(data) and data[end:end + 2] != b"\x00\x00":
                        end += 2
                    target = data[start:end].decode("utf-16-le", "replace")
                else:
                    end = data.find(b"\x00", li + lbp)
                    target = data[li + lbp:end].decode("mbcs" if IS_WIN else "latin-1", "replace")
        return target, is_dir
    except (OSError, struct.error, LookupError):
        return "", False


def parse_url(path):
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.upper().startswith("URL="):
                return line[4:].strip()
    except OSError:
        pass
    return ""


def classify(item):
    if item["is_dir"]:
        return FOLDERS
    text = f"{item['name']} {item['target']}".lower()
    for name, patterns in _RULES:
        if any(p.search(text) for p in patterns):
            return name
    return OTHERS if item["ext"] in APP_EXT else FILES


def scan_desktop(with_system=True):
    items, seen = [], set()
    for d in desktop_dirs():
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.name.lower() in IGNORED or e.name.startswith((".", "~$")):
                continue
            try:
                if IS_WIN and e.stat().st_file_attributes & 0x2:  # caché
                    continue
            except (OSError, AttributeError):
                pass
            p = Path(e.path)
            ext = p.suffix.lower()
            is_dir = e.is_dir() and ext != ".app"  # sur Mac, une application .app est un dossier
            target = ""
            if ext == ".lnk":
                target, is_dir = parse_lnk(e.path)
            elif ext == ".url":
                target = parse_url(e.path)
            name = p.stem if ext in APP_EXT else p.name
            key = (name.lower(), target.lower())
            if key in seen:  # même raccourci sur le bureau personnel et le bureau public
                continue
            seen.add(key)
            items.append({"path": e.path, "name": name, "target": target, "is_dir": is_dir, "ext": ext})
    if with_system and IS_WIN:
        for path, name in SYSTEM_ITEMS:
            items.append({"path": path, "name": name, "target": "", "is_dir": True, "ext": ""})
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            items.append({"path": str(downloads), "name": "Téléchargements", "target": "",
                          "is_dir": True, "ext": ""})
    return items


# --------------------------------------------------------------------------- #
#  Toutes les applications de l'ordinateur (menu Démarrer + Microsoft Store)
# --------------------------------------------------------------------------- #
_JUNK_NAME = re.compile(
    r"uninstall|désinstall|desinstall|\bhelp\b|aide de|obtenir de l'aide|manual|manuel|documentation"
    r"|\bdocs?\b|readme|lisez-moi|release notes|notes de version|nouveautés|what's new|website|site web"
    r"|support center|samples for|tools for|reload configuration|reset preferences|installation notes"
    r"|application verifier|app cert kit|debuggable|télémétrie|préférences linguistiques"
    r"|install additional tools|software development kit|command prompt for vs|native tools"
    r"|cross tools|prise en main|centre de commentaires|private browsing|\(x86\)|qt linguist"
    r"|spreadsheet compare|stack builder|faq|licen[cs]e|changelog|fxdk|development kit",
    re.IGNORECASE)
_JUNK_EXT = (".chm", ".txt", ".htm", ".html", ".url", ".hlp", ".pdf", ".md", ".rtf", ".ini", ".log")


def _norm(name):
    """Nom simplifié pour repérer les doublons (« MongoDB Compass » = « MongoDBCompass »)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _is_junk(name, appid):
    a = appid.lower()
    if ";" in a or a.startswith(("http:", "https:", "file:", "mailto:")) or a.endswith(_JUNK_EXT):
        return True
    if a.startswith("{") and not os.path.splitext(a)[1]:  # dossier, pas une application
        return True
    return bool(_JUNK_NAME.search(name))


def _start_apps_powershell():
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
           "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                         capture_output=True, timeout=60,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    data = json.loads(out.decode("utf-8", "replace") or "[]")
    if isinstance(data, dict):
        data = [data]
    return [(d.get("Name") or "", d.get("AppID") or "") for d in data]


def _start_apps_folders():
    """Solution de repli : raccourcis .lnk des dossiers du menu Démarrer."""
    res = []
    roots = [os.path.join(os.getenv("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
             os.path.join(os.getenv("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]
    for r in roots:
        for dirpath, _, files in os.walk(r):
            for f in files:
                if f.lower().endswith(".lnk"):
                    res.append((f[:-4], os.path.join(dirpath, f)))
    return res


def _mac_apps():
    """Applications macOS : /Applications, ~/Applications, applications système (+ un sous-dossier)."""
    res = []
    for root in ("/Applications", str(Path.home() / "Applications"), "/System/Applications"):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if entry.endswith(".app"):
                res.append((entry[:-4], full))
            elif os.path.isdir(full) and not entry.startswith("."):  # ex. « Utilitaires »
                for sub in sorted(os.listdir(full)):
                    if sub.endswith(".app"):
                        res.append((sub[:-4], os.path.join(full, sub)))
    return res


def list_installed_apps():
    """[(nom, AppID)] filtrée et sans doublons. Lent (1-2 s) : à appeler hors de l'interface."""
    if IS_MAC:
        seen, apps = set(), []
        for name, path in _mac_apps():
            if _norm(name) not in seen and not _JUNK_NAME.search(name):
                seen.add(_norm(name))
                apps.append((name, path))
        return apps
    if not IS_WIN:
        return []
    try:
        raw = _start_apps_powershell()
    except Exception:  # noqa: BLE001
        raw = []
    if not raw:
        raw = _start_apps_folders()
    seen, apps = set(), []
    for name, appid in sorted(raw, key=lambda x: x[0].lower()):
        key = _norm(name)
        if not name or not appid or key in seen or _is_junk(name, appid):
            continue
        seen.add(key)
        apps.append((name.strip(), appid))
    return apps


def app_item(name, appid):
    if appid.startswith("::") or os.path.isabs(appid) and os.path.exists(appid):
        path = appid  # élément système ou chemin direct (.lnk du menu Démarrer)
    else:
        path = "shell:AppsFolder\\" + appid
    return {"path": path, "name": name, "target": appid, "is_dir": appid.startswith("::"),
            "ext": ".lnk", "app": True}


def collect_items(source, with_system, apps):
    """Éléments à afficher selon la source choisie."""
    desktop = scan_desktop(with_system)
    if source != "apps" or not apps:
        return desktop
    items = [app_item(n, a) for n, a in apps]
    names = {_norm(it["name"]) for it in items}
    for it in desktop:
        # on garde les dossiers / fichiers du bureau et les raccourcis absents du menu Démarrer
        if _norm(it["name"]) not in names:
            items.append(it)
    return items


# --------------------------------------------------------------------------- #
#  Icônes Windows -> images Tk
# --------------------------------------------------------------------------- #
class IconLoader:
    SHGFI_SYSICONINDEX, SHGFI_PIDL = 0x4000, 0x8

    def __init__(self):
        self.cache = {}
        self.failed = set()  # icônes non chargées (à retenter)
        self.lists = {}
        if not (IS_WIN and HAS_PIL):
            return

        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [("hIcon", wintypes.HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                        ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                        ("hbmMask", wintypes.HANDLE), ("hbmColor", wintypes.HANDLE)]

        class BITMAP(ctypes.Structure):
            _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                        ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD),
                        ("bmBitsPixel", wintypes.WORD), ("bmBits", ctypes.c_void_p)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
                        ("bmiColors", wintypes.DWORD * 4)]

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        self.SHFILEINFOW, self.ICONINFO, self.BITMAP, self.BITMAPINFO = SHFILEINFOW, ICONINFO, BITMAP, BITMAPINFO
        self.shell32, self.user32, self.gdi32, self.ole32 = (ctypes.windll.shell32, ctypes.windll.user32,
                                                             ctypes.windll.gdi32, ctypes.windll.ole32)
        H = wintypes.HANDLE
        self.shell32.SHGetFileInfoW.restype = ctypes.c_size_t
        self.shell32.SHGetFileInfoW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                                wintypes.UINT, wintypes.UINT]
        self.shell32.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                                    ctypes.POINTER(ctypes.c_void_p), wintypes.ULONG,
                                                    ctypes.c_void_p]
        self.shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        self.user32.GetIconInfo.argtypes = [H, ctypes.c_void_p]
        self.user32.GetDC.restype = H
        self.user32.GetDC.argtypes = [H]
        self.user32.ReleaseDC.argtypes = [H, H]
        self.user32.DestroyIcon.argtypes = [H]
        self.gdi32.GetObjectW.argtypes = [H, ctypes.c_int, ctypes.c_void_p]
        self.gdi32.GetDIBits.argtypes = [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                         ctypes.c_void_p, wintypes.UINT]
        self.gdi32.DeleteObject.argtypes = [H]
        self.ole32.CoInitialize(None)
        self.iid = GUID()
        self.ole32.CLSIDFromString("{46EB5926-582E-4017-9FDF-E8998DAA0950}", ctypes.byref(self.iid))
        self.get_icon_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
                                                 ctypes.c_uint, ctypes.POINTER(H))

    def _sys_index(self, path):
        info = self.SHFILEINFOW()
        if path.startswith(("::", "shell:")):
            pidl = ctypes.c_void_p()
            if self.shell32.SHParseDisplayName(path, None, ctypes.byref(pidl), 0, None) != 0:
                return None
            self.shell32.SHGetFileInfoW(pidl, 0, ctypes.byref(info), ctypes.sizeof(info),
                                        self.SHGFI_SYSICONINDEX | self.SHGFI_PIDL)
            self.ole32.CoTaskMemFree(pidl)
        else:
            if not self.shell32.SHGetFileInfoW(ctypes.c_wchar_p(path), 0, ctypes.byref(info),
                                               ctypes.sizeof(info), self.SHGFI_SYSICONINDEX):
                return None
        return info.iIcon

    def _image_list(self, shil):
        if shil not in self.lists:
            ptr = ctypes.c_void_p()
            ok = self.shell32.SHGetImageList(shil, ctypes.byref(self.iid), ctypes.byref(ptr)) == 0
            self.lists[shil] = ptr if ok and ptr.value else None
        return self.lists[shil]

    def _dib(self, hdc, hbm, w, h):
        bmi = self.BITMAPINFO()
        bmi.biSize, bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = 40, w, -h, 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        self.gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bmi), 0)
        return buf.raw

    def _icon(self, shil, index):
        il = self._image_list(shil)
        if il is None:
            return None
        vtbl = ctypes.cast(il.value, ctypes.POINTER(ctypes.c_void_p))[0]
        get_icon = self.get_icon_proto(ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[10])
        hicon = wintypes.HANDLE()
        if get_icon(il.value, index, 0x1, ctypes.byref(hicon)) != 0 or not hicon.value:  # ILD_TRANSPARENT
            return None
        try:
            ii = self.ICONINFO()
            if not self.user32.GetIconInfo(hicon, ctypes.byref(ii)):
                return None
            try:
                if not ii.hbmColor:
                    return None
                bm = self.BITMAP()
                self.gdi32.GetObjectW(ii.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm))
                w, h = bm.bmWidth, bm.bmHeight
                hdc = self.user32.GetDC(None)
                try:
                    img = Image.frombuffer("RGBA", (w, h), self._dib(hdc, ii.hbmColor, w, h), "raw", "BGRA", 0, 1)
                    if img.getextrema()[3][1] == 0:  # icône sans alpha : on applique le masque
                        mask = Image.frombuffer("RGBA", (w, h), self._dib(hdc, ii.hbmMask, w, h),
                                                "raw", "BGRA", 0, 1).convert("L")
                        img = img.copy()
                        img.putalpha(mask.point(lambda v: 0 if v > 128 else 255))
                finally:
                    self.user32.ReleaseDC(None, hdc)
                return img.copy()
            finally:
                if ii.hbmColor:
                    self.gdi32.DeleteObject(ii.hbmColor)
                if ii.hbmMask:
                    self.gdi32.DeleteObject(ii.hbmMask)
        finally:
            self.user32.DestroyIcon(hicon)

    @staticmethod
    def _mac_icon(path):
        """Icône d'une application macOS (fichier .icns du paquet .app)."""
        import plistlib
        res = Path(path) / "Contents" / "Resources"
        try:
            with open(Path(path) / "Contents" / "Info.plist", "rb") as f:
                name = plistlib.load(f).get("CFBundleIconFile", "")
        except (OSError, ValueError):
            name = ""
        candidates = [res / (name if name.endswith(".icns") else name + ".icns")] if name else []
        candidates += sorted(res.glob("*.icns")) if res.is_dir() else []
        for c in candidates:
            try:
                return Image.open(c).convert("RGBA")  # Pillow charge la plus grande taille disponible
            except (OSError, ValueError):
                continue
        return None

    def get(self, path, px):
        """PhotoImage de px×px pour le fichier / dossier / élément système, ou None."""
        if IS_MAC and HAS_PIL and str(path).endswith(".app"):
            key = (path, px)
            if key not in self.cache:
                img = self._mac_icon(path)
                if img is None:
                    return None
                self.cache[key] = ImageTk.PhotoImage(img.resize((px, px), Image.LANCZOS))
            return self.cache[key]
        if not (IS_WIN and HAS_PIL):
            return None
        key = (path, px)
        if key in self.cache:
            return self.cache[key]
        photo = None
        try:
            idx = self._sys_index(path)
            if idx is not None:
                shil = 0 if px <= 32 else 2 if px <= 48 else 4  # LARGE / EXTRALARGE / JUMBO
                img = self._icon(shil, idx)
                if shil == 4 and img is not None:
                    box = img.getbbox()  # icône sans version 256 px : petite image dans un coin
                    if box and box[2] - box[0] <= 48 and box[3] - box[1] <= 48:
                        img = self._icon(2, idx)
                if img is not None:
                    box = img.getbbox()  # petite icône collée dans un coin : on la recadre
                    if box and box[0] <= 2 and box[1] <= 2 and max(box[2], box[3]) <= img.width * 0.6:
                        side = max(box[2], box[3])
                        img = img.crop((0, 0, side, side))
                    if img.size != (px, px):
                        img = img.resize((px, px), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
        except (OSError, ValueError):
            photo = None
        if photo is not None:  # un échec (bureau Windows pas encore prêt au démarrage) sera retenté
            self.cache[key] = photo
        else:
            self.failed.add(key)
        return photo


# --------------------------------------------------------------------------- #
#  Icônes Windows du bureau (afficher / masquer)
# --------------------------------------------------------------------------- #
def _desktop_defview():
    if not IS_WIN:
        return None
    u = ctypes.windll.user32
    u.FindWindowW.restype = u.FindWindowExW.restype = ctypes.c_void_p
    u.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR]
    progman = u.FindWindowW("Progman", None)
    dv = u.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else None
    w = None
    while not dv:
        w = u.FindWindowExW(None, w, "WorkerW", None)
        if not w:
            break
        dv = u.FindWindowExW(w, None, "SHELLDLL_DefView", None)
    return dv


def desktop_icons_visible():
    dv = _desktop_defview()
    if not dv:
        return True
    u = ctypes.windll.user32
    lv = u.FindWindowExW(dv, None, "SysListView32", None)
    u.IsWindowVisible.argtypes = [ctypes.c_void_p]
    return bool(u.IsWindowVisible(lv)) if lv else True


def set_desktop_icons(visible):
    """Équivaut au clic droit sur le bureau > Affichage > Afficher les icônes du bureau."""
    dv = _desktop_defview()
    if dv and desktop_icons_visible() != visible:
        u = ctypes.windll.user32
        u.SendMessageW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW(dv, 0x0111, 0x7402, 0)  # WM_COMMAND, bascule d'affichage des icônes


def _blend(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


# --------------------------------------------------------------------------- #
#  Panneaux
# --------------------------------------------------------------------------- #
class DesktopOrganizer:
    POLL_MS = 5000

    def __init__(self, app):
        self.app = app
        self.fences = {}
        self.icons = IconLoader()
        self._sig = None
        self._tdrag = None
        self._ghost = None
        self._hdrag = None
        self._last_click = None
        self._scroll = {}          # position de défilement de chaque panneau
        self._fence_sigs = {}      # empreinte de chaque panneau (redessin seulement si elle change)
        self._icon_missing = set() # panneaux avec des icônes manquantes (retentées plus tard)
        self.apps = self._load_apps_cache()
        self._apps_new = None      # rempli par le thread de mise à jour
        self._apps_loading = False
        self._apps_time = 0.0
        self.app.root.after(self.POLL_MS, self._poll)

    # ----- liste des applications installées ----------------------------------
    APPS_CACHE = CONFIG_DIR / "apps_cache.json"
    APPS_REFRESH_S = 600

    def _load_apps_cache(self):
        try:
            return [tuple(x) for x in json.loads(self.APPS_CACHE.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def retry_failed_icons(self):
        """Redessine les panneaux dont des icônes n'avaient pas pu être chargées (ex. au démarrage)."""
        if not self._icon_missing or not self.cfg["org_enabled"]:
            return
        cats, self._icon_missing = self._icon_missing, set()
        self.icons.failed.clear()
        for cat in cats:
            self._fence_sigs.pop(cat, None)
        self.build()

    def refresh_all(self):
        self.build(force=True)
        if self.cfg["org_source"] == "apps":
            self.refresh_apps()  # le panneau se mettra à jour dès que la liste sera prête

    def refresh_apps(self):
        """Relit la liste des applications en arrière-plan (Get-StartApps prend 1-2 s)."""
        if self._apps_loading or not IS_WIN:
            return
        self._apps_loading = True
        self._apps_time = time.time()

        def worker():
            try:
                apps = list_installed_apps()
                if apps:
                    try:
                        self.APPS_CACHE.parent.mkdir(parents=True, exist_ok=True)
                        self.APPS_CACHE.write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        pass
                    self._apps_new = apps
            finally:
                self._apps_loading = False

        threading.Thread(target=worker, daemon=True).start()

    @property
    def cfg(self):
        return self.app.cfg

    def windows(self):
        return [w for w in self.fences.values() if w.winfo_exists()]

    # ----- données ------------------------------------------------------------
    def categories(self):
        cats = [(n, e) for n, e, _ in CATEGORIES] + SPECIAL[:2]
        cats += [(n, CUSTOM_EMOJI) for n in self.cfg["org_custom"]]
        return cats + SPECIAL[2:]

    def emoji(self, cat):
        return dict(self.categories()).get(cat, CUSTOM_EMOJI)

    # ----- panneaux masqués / supprimés ------------------------------------------
    # org_cat_state = {catégorie: "hide" | "remove"} ; absent = affiché
    def cat_state(self, cat):
        return self.cfg["org_cat_state"].get(cat, "show")

    def active_categories(self):
        """Catégories vers lesquelles on peut encore classer une application."""
        return [(n, e) for n, e in self.categories() if self.cat_state(n) == "show"]

    def set_cat_state(self, cat, state):
        states = self.cfg["org_cat_state"]
        if state == "show":
            states.pop(cat, None)
        else:
            states[cat] = state
        self.app.save()
        self.build()

    def hide_panel(self, cat):
        self.set_cat_state(cat, "hide")

    def remove_panel(self, cat):
        if messagebox.askyesno(
                "Supprimer le panneau",
                f"Supprimer le panneau « {cat} » ?\n\nSes applications seront déplacées dans « {OTHERS} ».\n"
                "Vous pourrez le rétablir depuis le clic droit ou Paramètres → Bureau.",
                parent=self.app.root):
            self.set_cat_state(cat, "remove")

    def set_panel_style(self, cat, key, value):
        styles = self.cfg["org_cat_style"]
        if key is None:
            styles.pop(cat, None)
        else:
            styles.setdefault(cat, {})[key] = value
        self.app.save()
        self.build()

    def pick_panel_color(self, cat):
        from tkinter import colorchooser
        cur = self.cfg["org_cat_style"].get(cat, {}).get("accent", self.cfg["accent_color"])
        _, hexa = colorchooser.askcolor(color=cur, parent=self.app.root, title=f"Couleur du panneau « {cat} »")
        if hexa:
            self.set_panel_style(cat, "accent", hexa.upper())

    def restore_all_panels(self):
        self.cfg["org_cat_state"] = {}
        self.app.save()
        self.build()

    def _signature(self):
        sig = []
        for d in desktop_dirs():
            try:
                sig += sorted(os.listdir(d))
            except OSError:
                pass
        return tuple(sig)

    def grouped(self):
        c = self.cfg
        valid = {n for n, _ in self.categories()}
        hidden = set(c["org_hidden"])
        groups = {}
        for it in collect_items(c["org_source"], c["org_system"], self.apps):
            if it["path"] in hidden:
                continue
            cat = c["org_assign"].get(it["path"])
            if cat not in valid:
                cat = classify(it)
            if self.cat_state(cat) == "remove":  # panneau supprimé : ses applications vont dans Autres
                cat = OTHERS
            groups.setdefault(cat, []).append(it)
        for cat, items in groups.items():
            order = c["org_order"].get(cat, [])
            rank = {p: i for i, p in enumerate(order)}
            items.sort(key=lambda it: (rank.get(it["path"], len(order)), it["name"].lower()))
        return [(n, groups[n]) for n, _ in self.categories()
                if groups.get(n) and self.cat_state(n) == "show"]

    # ----- construction ------------------------------------------------------
    def _fence_signature(self, cat, items):
        """Empreinte d'un panneau : il n'est redessiné que si elle change."""
        c = self.cfg
        return (cfg_signature(c, STYLE_KEYS + ("org_icon", "org_columns", "org_max_rows", "org_labels")),
                json.dumps(c["org_cat_style"].get(cat), sort_keys=True), cat in c["org_collapsed"],
                tuple((it["path"], it["name"]) for it in items))

    def build(self, force=False):
        c = self.cfg
        self.apply_icon_visibility()
        if not c["org_enabled"]:
            for w in self.fences.values():
                w.destroy()
            self.fences = {}
            self._fence_sigs = {}
            return
        if c["org_source"] == "apps" and not self.apps:
            self.refresh_apps()  # 1er lancement : le bureau s'affiche en attendant la liste
        self._sig = self._signature()
        groups = self.grouped()
        names = {n for n, _ in groups}
        for n in list(self.fences):
            if n not in names:
                self.fences.pop(n).destroy()
                self._fence_sigs.pop(n, None)
        new = []
        for cat, items in groups:
            win = self.fences.get(cat)
            created = win is None or not win.winfo_exists()
            if created:
                win = tk.Toplevel(self.app.root)
                win.overrideredirect(True)
                win.title(f"Bureau — {cat}")
                win._pos_key = f"fence:{cat}"
                self.fences[cat] = win
                new.append(cat)
            sig = self._fence_signature(cat, items)
            if created or force or self._fence_sigs.get(cat) != sig:  # les autres panneaux ne bougent pas
                self._fence_sigs[cat] = sig
                self._fill(win, cat, items)
        for cat in new:
            pos = c["positions"].get(f"fence:{cat}")
            if self.app._valid_pos(pos):
                self.fences[cat].geometry(f"+{int(pos[0])}+{int(pos[1])}")
        if new:
            self.auto_layout(only=[cat for cat in new if not self.app._valid_pos(
                c["positions"].get(f"fence:{cat}"))])
            if not getattr(self, "_entered", False) and not c["widgets_hidden"]:
                self._entered = True   # après les cartes, les panneaux arrivent un à un
                for i, cat in enumerate(sorted(new, key=lambda k: self.app.anim.pos(self.fences[k]))):
                    self.app.anim.appear(self.fences[cat], 380 + i * 70)

    def _scale(self):
        return self.app.root.winfo_fpixels("1i") / 96.0

    def _fill(self, win, cat, items):
        """Panneau au même style que les cartes : palette du thème, verre acrylique (Windows), coins arrondis."""
        c = self.cfg
        for ch in win.winfo_children():
            ch.destroy()
        style = c["org_cat_style"].get(cat, {})  # couleur / opacité propres au panneau
        cm = self.app.cards
        cm.theme_colors()
        fg, sub, track = cm.fg, cm.sub, cm.track
        acc = style.get("accent") or c["accent_color"]
        opacity = max(0.2, min(1.0, style.get("opacity", c["opacity"]) / 100))
        # Windows + flou : fond transparent (couleur clé) sous lequel Windows dessine un verre acrylique teinté
        glass = IS_WIN and bool(c.get("card_blur"))
        if glass:
            from cards import KEY, KEY_LIGHT
            bg = KEY if cm.dark else KEY_LIGHT
            hover = blend_hex(cm.bg, fg, 0.10)
        else:
            bg = cm.bg
            hover = blend_hex(cm.bg, fg, 0.08)
        win.configure(bg=bg)
        win.attributes("-topmost", bool(c["topmost"]))
        if glass:
            win.attributes("-transparentcolor", bg)
            win.attributes("-alpha", 1.0)
        else:
            win.attributes("-alpha", opacity)
        win._base_alpha = 1.0 if glass else opacity

        def finish_style():
            if not win.winfo_exists():
                return
            apply_corners(win, int(c["card_radius"]) >= 4)
            no_activate(win)
            if glass:
                win_blur(win, True, cm.bg, opacity)
        win.after(150, finish_style)   # le verre ne s'applique qu'une fois la fenêtre affichée

        scale = self._scale()
        px = int(int(c["org_icon"]) * scale)
        tile_w = max(px + int(24 * scale), int(84 * scale))
        fam = TEXT_FONT
        ts = max(8, round(10 * int(c["card_text_scale"]) / 100))
        f_tile = tkfont.Font(family=fam, size=max(7, ts - 1))
        collapsed = cat in c["org_collapsed"]

        outer = tk.Frame(win, bg=bg)
        outer.pack(fill="both", expand=True)
        outer._fence_cat = cat

        head = tk.Frame(outer, bg=bg, padx=14, pady=9)
        head.pack(fill="x")
        head._fence_cat = cat
        # en-tête façon cartes : titre sobre, emoji teinté de l'accent, compteur discret
        emo = tk.Label(head, text=self.emoji(cat), bg=bg, fg=acc, font=(fam, ts + 1))
        emo.pack(side="left")
        title = tk.Label(head, text=cat, bg=bg, fg=fg, font=(fam, ts + 1, "bold"))
        title.pack(side="left", padx=(6, 0))
        arrow = tk.Label(head, text="▸" if collapsed else "▾", bg=bg, fg=sub, font=(fam, ts))
        arrow.pack(side="right")
        count = tk.Label(head, text=str(len(items)), bg=bg, fg=sub, font=(fam, max(7, ts - 1)))
        count.pack(side="right", padx=(0, 8))
        for w in (head, emo, title, arrow, count):
            w.bind("<ButtonPress-1>", lambda e: self._head_press(e))
            w.bind("<B1-Motion>", self.app._do_drag)
            w.bind("<ButtonRelease-1>", lambda e, k=cat: self._head_release(e, k))
            bind_right_click(w, lambda e, k=cat: self._fence_menu(e, k))

        if collapsed:
            return
        tk.Frame(outer, bg=track, height=1).pack(fill="x", padx=14)   # filet discret, comme les cartes
        cols = max(1, int(c["org_columns"]))
        n_rows = -(-len(items) // cols)
        max_rows = int(c["org_max_rows"])
        scrolling = 0 < max_rows < n_rows
        canvas = None
        if scrolling:
            # panneau défilant : grille dans un Canvas + petit indicateur de position
            wrap = tk.Frame(outer, bg=bg)
            wrap.pack(fill="both", expand=True)
            wrap._fence_cat = cat
            canvas = tk.Canvas(wrap, bg=bg, highlightthickness=0, bd=0)
            canvas._fence_cat = cat
            track = tk.Frame(wrap, bg=bg, width=max(3, int(3 * scale)))
            track.pack(side="right", fill="y", padx=(0, 3), pady=6)
            thumb = tk.Frame(track, bg=acc)
            body = tk.Frame(canvas, bg=bg, padx=8, pady=8)
            canvas.create_window(0, 0, window=body, anchor="nw")
        else:
            body = tk.Frame(outer, bg=bg, padx=8, pady=8)
            body.pack(fill="both", expand=True)
        body._fence_cat = cat
        for w in ([body, canvas] if canvas else [body]):
            w.bind("<ButtonPress-1>", self.app._start_drag)
            w.bind("<B1-Motion>", self.app._do_drag)
            w.bind("<ButtonRelease-1>", self.app._end_drag)
            bind_right_click(w, lambda e, k=cat: self._fence_menu(e, k))

        for i, it in enumerate(items):
            # pas d'option width sur la tuile : un simple configure(bg=…) au survol
            # ferait alors redemander à Tk une hauteur nulle et masquerait son contenu
            tile = tk.Frame(body, bg=bg, padx=3, pady=5, cursor="hand2")
            tile.grid(row=i // cols, column=i % cols, sticky="n", padx=1, pady=1)
            tile._tile_path = it["path"]
            tile._fence_cat = cat
            img = self.icons.get(it["path"], px)
            if img is None:
                self._icon_missing.add(cat)
            if img is not None:
                # taille fixe : l'icône peut rétrécir à l'appui sans faire bouger la tuile
                ico = tk.Label(tile, image=img, bg=bg, width=px + 4, height=px + 4)
                ico.image = img
            else:
                emoji = "📁" if it["is_dir"] else "🔗" if it["ext"] in APP_EXT else "📄"
                ico = tk.Label(tile, text=emoji, bg=bg, fg=fg, font=(fam, max(12, int(px / scale * 0.55))))
            ico.pack(pady=(2, 0))
            if c["org_labels"]:
                # hauteur fixe de 2 lignes : toutes les tuiles ont la même taille
                tk.Label(tile, text=self._two_lines(it["name"], f_tile, tile_w - 6), bg=bg, fg=fg,
                         font=f_tile, justify="center", width=0, height=2, anchor="n").pack()
            # largeur fixe des tuiles : une bande invisible
            tk.Frame(tile, width=(tile_w if c["org_labels"] else px + int(16 * scale)) - 4,
                     height=0, bg=bg).pack()
            parts = (tile, *tile.winfo_children())
            tile._fx = self._tile_fx(tile, parts, ico, img, it["path"], px, bg, cm.bg, hover, acc)
            for w in parts:
                w._tile_path = it["path"]
                w.bind("<Enter>", lambda e, t=tile: t._fx["hover"](1.0))
                w.bind("<Leave>", lambda e, t=tile: t._fx["hover"](0.0))
                w.bind("<ButtonPress-1>", lambda e, item=it, k=cat: self._tile_press(e, item, k))
                w.bind("<B1-Motion>", self._tile_motion)
                w.bind("<ButtonRelease-1>", self._tile_release)
                bind_right_click(w, lambda e, item=it, k=cat: self._tile_menu(e, item, k))

        if scrolling:
            self._setup_scroll(cat, canvas, body, track, thumb, n_rows, max_rows)

    def _tile_fx(self, tile, parts, ico, img, path, px, bg, vis_bg, hover, acc):
        """Effets d'une tuile : fond qui s'allume en fondu et icône qui se soulève au survol, icône qui
        s'enfonce à l'appui, halo de la couleur d'accent au lancement."""
        a = self.app.anim
        key = ("tile", str(tile))
        state = {"h": 0.0, "glow": 0.0}

        def paint():
            h, g = state["h"], state["glow"]
            if h <= 0.01 and g <= 0.01:
                col = bg   # repos : fond transparent (verre) ou couleur du panneau
            else:
                col = anim.mix(anim.mix(vis_bg, hover, h), acc, 0.5 * g)
            for x in parts:
                if x.winfo_exists():
                    x.configure(bg=col)
            lift = h > 0.5 and g <= 0.01
            if ico.winfo_exists():
                ico.pack_configure(pady=(0, 2) if lift else (2, 0))

        def hover_to(to):
            h0 = state["h"]

            def step(p):
                state["h"] = anim.lerp(h0, to, p)
                paint()
            a.play(key, 150 if to > h0 else 260, step, anim.ease_out)

        small = {}

        def press():
            if img is None or not ico.winfo_exists():
                return
            if "img" not in small:
                small["img"] = self.icons.get(path, int(px * 0.84)) or img
            ico.configure(image=small["img"])

        def release():
            if img is not None and ico.winfo_exists():
                ico.configure(image=img)

        def glow():
            def step(p):
                state["glow"] = 1 - p
                paint()
            a.play(("glow", str(tile)), 700, step, anim.ease_out)
        return {"hover": hover_to, "press": press, "release": release, "glow": glow}

    def _setup_scroll(self, cat, canvas, body, track, thumb, n_rows, max_rows):
        body.update_idletasks()
        w, h = body.winfo_reqwidth(), body.winfo_reqheight()
        row_h = (h - 12) / n_rows  # pady=6 en haut et en bas
        visible = int(max_rows * row_h + 12)
        # pas d'incrément imposé : le défilement peut s'arrêter entre deux lignes pendant l'animation
        canvas.configure(width=w, height=visible, scrollregion=(0, 0, w, h), yscrollincrement=1)
        canvas.pack(side="left", fill="both", expand=True)
        target = {}

        def update_thumb():
            first, last = canvas.yview()
            thumb.place(x=0, relwidth=1, rely=first, relheight=max(0.08, last - first))
            self._scroll[cat] = first

        def on_wheel(e):
            top = canvas.canvasy(0)
            goal = target.get("y", top) + (-1 if e.delta > 0 else 1) * row_h
            goal = max(0.0, min(h - visible, round(goal / row_h) * row_h))
            target["y"] = goal

            def step(p):
                canvas.yview_moveto(anim.lerp(top, goal, p) / h)
                update_thumb()
            self.app.anim.play(("scroll", cat), 280, step, anim.ease_out, lambda: target.pop("y", None))
            return "break"

        def bind_all(widget):
            widget.bind("<MouseWheel>", on_wheel, add="+")
            for ch in widget.winfo_children():
                bind_all(ch)

        for wdg in (canvas, track, thumb):
            wdg.bind("<MouseWheel>", on_wheel)
        bind_all(body)
        canvas.yview_moveto(self._scroll.get(cat, 0))
        update_thumb()

    @staticmethod
    def _two_lines(text, fnt, width):
        """Coupe le nom sur 2 lignes max, avec « … » si nécessaire."""
        words, lines, cur = text.split(), [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            if fnt.measure(test) <= width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) > 2:
            lines = [lines[0], " ".join(lines[1:])]
        out = []
        for ln in lines[:2]:
            if fnt.measure(ln) > width:
                while ln and fnt.measure(ln + "…") > width:
                    ln = ln[:-1]
                ln += "…"
            out.append(ln)
        return "\n".join(out)

    # ----- disposition ---------------------------------------------------------
    def _work_area(self):
        if IS_WIN:
            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
                return r.left, r.top, r.right, r.bottom
        return 0, 0, self.app.root.winfo_screenwidth(), self.app.root.winfo_screenheight()

    def avoid_cards(self):
        """Déplace vers une place libre les panneaux qui se trouvent sous une carte (les autres ne bougent pas)."""
        cards = getattr(self.app, "cards", None)
        if not (self.fences and cards is not None and cards.active):
            return []

        def rect(w):
            w.update_idletasks()
            x, y = self.app.anim.pos(w)
            return (x, y, x + w.winfo_width(), y + w.winfo_height())

        def hit(a, b, m=8):
            return a[0] < b[2] + m and b[0] < a[2] + m and a[1] < b[3] + m and b[1] < a[3] + m

        card_rects = [rect(w) for w in cards.windows() if w.winfo_exists()]
        moved = []
        for cat, win in self.fences.items():
            r = rect(win)
            if not any(hit(r, c) for c in card_rects):
                continue
            busy = card_rects + [rect(w) for k, w in self.fences.items() if k != cat]
            left, top, right, bottom = self._work_area()
            w, h, step = r[2] - r[0], r[3] - r[1], int(20 * self._scale())
            spot = next(((x, y) for x in range(left + step, right - w, step) for y in range(top + step, bottom - h, step)
                         if not any(hit((x, y, x + w, y + h), b) for b in busy)), None)
            if spot:
                self.app.anim.glide(win, *spot)
                self.cfg["positions"][f"fence:{cat}"] = list(spot)
                moved.append(cat)
        if moved:
            self.app.save()
        return moved

    def auto_layout(self, only=None):
        """Range les panneaux en colonnes, à gauche de l'écran, sous l'heure/la date séparées."""
        if not self.fences:
            return
        left, top, right, bottom = self._work_area()
        gap = int(14 * self._scale())
        y0 = top + gap
        for win in self.app.panels.values():
            win.update_idletasks()
            if win.winfo_x() < left + (right - left) / 2 and win.winfo_y() < top + (bottom - top) / 3:
                y0 = max(y0, win.winfo_y() + win.winfo_height() + gap)
        # on laisse libre la zone du widget de monitoring s'il est sur la moitié droite
        root = self.app.root
        if not self.app.main_hidden and root.winfo_x() > left + (right - left) / 2:
            right = root.winfo_x() - gap
        # idem pour les cartes (style « cartes ») : les panneaux se rangent à côté, jamais dessous
        cards = getattr(self.app, "cards", None)
        card_wins = [w for w in (cards.windows() if cards is not None and cards.active else []) if w.winfo_exists()]
        if card_wins:
            for w in card_wins:
                w.update_idletasks()
            pos = self.app.anim.pos   # position d'arrivée des cartes qui sont en train de glisser
            cx0 = min(pos(w)[0] for w in card_wins)
            cx1 = max(pos(w)[0] + w.winfo_width() for w in card_wins)
            if (cx0 + cx1) / 2 < left + (right - left) / 2:
                left = max(left, cx1 + gap)    # cartes à gauche : panneaux à leur droite
            else:
                right = min(right, cx0 - gap)  # cartes à droite : panneaux à leur gauche
        fences = [(cat, self.fences[cat]) for cat, _ in self.categories() if cat in self.fences]
        for _, win in fences:
            win.update_idletasks()
        col_w = max(win.winfo_reqwidth() for _, win in fences)
        n_cols = max(1, (right - left - gap) // (col_w + gap))
        heights = [y0] * n_cols
        # « maçonnerie » : chaque panneau va dans la colonne la moins remplie
        for cat, win in fences:
            i = heights.index(min(heights))
            x, y = left + gap + i * (col_w + gap), heights[i]
            if only is None or cat in only:
                self.app.anim.glide(win, x, y, 520 + 40 * i)
                self.cfg["positions"][f"fence:{cat}"] = [x, y]
            heights[i] = y + win.winfo_reqheight() + gap
        self.app.save()

    # ----- interactions : titre --------------------------------------------------
    def _head_press(self, e):
        self._hdrag = (e.x_root, e.y_root)
        self.app._start_drag(e)

    def _head_release(self, e, cat):
        moved = self._hdrag and (abs(e.x_root - self._hdrag[0]) + abs(e.y_root - self._hdrag[1]) > 4)
        self._hdrag = None
        if moved:
            self.app._end_drag(e)
        else:
            self.app._drag = (None, 0, 0)
            self.toggle_collapse(cat)

    def toggle_collapse(self, cat):
        lst = self.cfg["org_collapsed"]
        collapsing = cat not in lst
        if collapsing:
            lst.append(cat)
        else:
            lst.remove(cat)
        self.app.save()
        win = self.fences.get(cat)
        if not (win is not None and win.winfo_exists() and win.winfo_ismapped() and self.app.anim.on):
            self.build()
            return
        win.update_idletasks()
        x, y = win.winfo_x(), win.winfo_y()
        w, h0 = win.winfo_width(), win.winfo_height()

        def release_size():   # le panneau reprend sa taille naturelle
            if win.winfo_exists():
                win.geometry("")
                win.geometry(f"+{x}+{y}")

        if collapsing:   # le contenu se range sous l'en-tête, puis le panneau est redessiné plié
            try:
                h1 = win.winfo_children()[0].winfo_children()[0].winfo_reqheight()
            except (IndexError, tk.TclError):
                self.build()
                return

            def done():
                self.build()
                release_size()
            self.app.anim.play(("drawer", cat), 260, lambda p: win.geometry(
                f"{w}x{round(anim.lerp(h0, h1, p))}+{x}+{y}"), anim.ease_in_out, done)
        else:            # redessiné déplié, puis il s'ouvre comme un tiroir
            self.build()
            win.update_idletasks()
            w1, h1 = win.winfo_reqwidth(), win.winfo_reqheight()
            win.geometry(f"{w1}x{h0}+{x}+{y}")
            self.app.anim.play(("drawer", cat), 320, lambda p: win.geometry(
                f"{w1}x{round(anim.lerp(h0, h1, p))}+{x}+{y}"), anim.ease_out_quint, release_size)

    # ----- interactions : icônes -------------------------------------------------
    @staticmethod
    def _tile_of(widget):
        return widget if hasattr(widget, "_fx") else getattr(widget, "master", None)

    def _tile_press(self, e, item, cat):
        self._tdrag = {"item": item, "cat": cat, "x": e.x_root, "y": e.y_root, "moved": False,
                       "widget": e.widget}
        tile = self._tile_of(e.widget)
        if tile is not None and hasattr(tile, "_fx"):
            tile._fx["press"]()

    def _tile_motion(self, e):
        d = self._tdrag
        if not d:
            return
        if not d["moved"] and abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 8:
            d["moved"] = True
            self._make_ghost(d["item"])
        if self._ghost is not None:
            self._ghost.geometry(f"+{e.x_root + 14}+{e.y_root + 10}")

    def _make_ghost(self, item):
        c = self.cfg
        g = self._ghost = tk.Toplevel(self.app.root)
        g.overrideredirect(True)
        g.attributes("-topmost", True)
        g.attributes("-alpha", 0.85)
        fr = tk.Frame(g, bg=c["accent_color"], padx=8, pady=4)
        fr.pack()
        img = self.icons.get(item["path"], int(24 * self._scale()))
        if img is not None:
            tk.Label(fr, image=img, bg=c["accent_color"]).pack(side="left", padx=(0, 6))
        tk.Label(fr, text=item["name"], bg=c["accent_color"], fg=c["bg_color"],
                 font=(c["font_family"], int(c["text_size"]), "bold")).pack(side="left")

    def _tile_release(self, e):
        d, self._tdrag = self._tdrag, None
        tile = self._tile_of(d["widget"]) if d else None
        if tile is not None and hasattr(tile, "_fx") and tile.winfo_exists():
            tile._fx["release"]()
        if self._ghost is not None:
            self._ghost.destroy()
            self._ghost = None
        if not d:
            return
        if not d["moved"]:
            if self.cfg["org_double_click"]:
                last = self._last_click
                self._last_click = (d["item"]["path"], time.time())
                if not (last and last[0] == d["item"]["path"] and time.time() - last[1] < 0.45):
                    return  # 1er clic : on attend le second
                self._last_click = None
            self.launch(d["item"], d["widget"])
            return
        w = self.app.root.winfo_containing(e.x_root, e.y_root)
        cat = before = None
        while w is not None:
            if before is None and getattr(w, "_tile_path", None):
                before = w._tile_path
            if getattr(w, "_fence_cat", None):
                cat = w._fence_cat
                break
            w = w.master
        if cat is not None and before != d["item"]["path"]:
            self.move_item(d["item"]["path"], cat, before)

    def launch(self, item, widget=None):
        p = item["path"]
        try:
            if p.startswith("::"):
                subprocess.Popen(["explorer.exe", "shell:" + p])
            elif p.startswith("shell:"):  # application du menu Démarrer / du Store
                subprocess.Popen(["explorer.exe", p])
            else:
                open_path(p)
        except OSError as ex:
            messagebox.showerror("Bureau organisé", f"Impossible d'ouvrir « {item['name']} » :\n{ex}")
            return
        if widget is not None:  # halo de la couleur d'accent qui s'estompe : l'application démarre
            tile = self._tile_of(widget)
            if tile is not None and hasattr(tile, "_fx"):
                tile._fx["glow"]()

    def move_item(self, path, cat, before=None):
        c = self.cfg
        current = {n: [it["path"] for it in items] for n, items in self.grouped()}
        for n, lst in c["org_order"].items():
            if path in lst:
                lst.remove(path)
        order = c["org_order"].setdefault(cat, [p for p in current.get(cat, []) if p != path])
        for p in current.get(cat, []):  # garde l'ordre affiché actuel
            if p not in order and p != path:
                order.append(p)
        if before in order:
            order.insert(order.index(before), path)
        else:
            order.append(path)
        c["org_assign"][path] = cat
        self.app.save()
        self.build()

    # ----- menus -----------------------------------------------------------------
    def _common_menu(self, m):
        n_hidden = len(self.cfg["org_hidden"])
        m.add_separator()
        m.add_command(label="Ranger les panneaux automatiquement", command=self.auto_layout)
        if n_hidden:
            m.add_command(label=f"Réafficher les raccourcis masqués ({n_hidden})", command=self.unhide_all)
        off = [(n, e) for n, e in self.categories() if self.cat_state(n) != "show"]
        if off:
            sub = tk.Menu(m, tearoff=0)
            for n, e in off:
                what = "masqué" if self.cat_state(n) == "hide" else "supprimé"
                sub.add_command(label=f"{e}  {n}  ({what})", command=lambda k=n: self.set_cat_state(k, "show"))
            sub.add_separator()
            sub.add_command(label="Tout rétablir", command=self.restore_all_panels)
            m.add_cascade(label=f"Rétablir un panneau ({len(off)})", menu=sub)
        m.add_command(label="Actualiser", command=self.refresh_all)
        m.add_command(label="⚙  Paramètres…", command=self.app.open_settings)

    def _popup(self, m, e):
        bring_to_front(e.widget.winfo_toplevel())  # sinon le menu ne se ferme pas en cliquant ailleurs
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _tile_menu(self, e, item, cat):
        m = tk.Menu(self.app.root, tearoff=0)
        m.add_command(label="Ouvrir", command=lambda: self.launch(item))
        if not item["path"].startswith(("::", "shell:")):
            m.add_command(label="Ouvrir l'emplacement",
                          command=lambda: reveal_in_folder(item["path"]))
        mv = tk.Menu(m, tearoff=0)
        for n, emo in self.active_categories():
            if n != cat:
                mv.add_command(label=f"{emo}  {n}", command=lambda k=n: self.move_item(item["path"], k))
        mv.add_separator()
        mv.add_command(label="➕  Nouvelle catégorie…", command=lambda: self.new_category(item["path"]))
        m.add_cascade(label="Déplacer vers", menu=mv)
        if item["path"] in self.cfg["org_assign"]:
            m.add_command(label="Classement automatique", command=lambda: self.reset_item(item["path"]))
        m.add_command(label="Masquer ce raccourci", command=lambda: self.hide(item["path"]))
        self._common_menu(m)
        self._popup(m, e)

    def _fence_menu(self, e, cat):
        m = tk.Menu(self.app.root, tearoff=0)
        collapsed = cat in self.cfg["org_collapsed"]
        m.add_command(label="Déplier" if collapsed else "Replier", command=lambda: self.toggle_collapse(cat))
        m.add_command(label="➕  Nouvelle catégorie…", command=lambda: self.new_category(None))
        m.add_separator()
        m.add_command(label="🎨  Couleur du panneau…", command=lambda: self.pick_panel_color(cat))
        op = tk.Menu(m, tearoff=0)
        current = self.cfg["org_cat_style"].get(cat, {}).get("opacity")
        for v in (100, 90, 80, 70, 60, 50, 40):
            op.add_radiobutton(label=f"{v} %", value=v, variable=tk.IntVar(op, current or 0),
                               command=lambda x=v: self.set_panel_style(cat, "opacity", x))
        m.add_cascade(label="◐  Opacité du panneau", menu=op)
        if cat in self.cfg["org_cat_style"]:
            m.add_command(label="↺  Style par défaut", command=lambda: self.set_panel_style(cat, None, None))
        m.add_separator()
        m.add_command(label="👁  Masquer ce panneau", command=lambda: self.hide_panel(cat))
        if cat in self.cfg["org_custom"]:
            m.add_command(label="🗑  Supprimer cette catégorie", command=lambda: self.delete_category(cat))
        elif cat != OTHERS:
            m.add_command(label=f"🗑  Supprimer ce panneau (applications → {OTHERS})",
                          command=lambda: self.remove_panel(cat))
        self._common_menu(m)
        self._popup(m, e)

    def new_category(self, path):
        name = simpledialog.askstring("Nouvelle catégorie", "Nom de la catégorie :", parent=self.app.root)
        name = (name or "").strip()
        if not name:
            return
        if name not in {n for n, _ in self.categories()}:
            self.cfg["org_custom"].append(name)
        self.cfg["org_cat_state"].pop(name, None)  # nom d'un panneau masqué : on le rétablit
        if path:
            self.move_item(path, name)
        else:
            self.app.save()
            self.build()

    def delete_category(self, cat):
        c = self.cfg
        if cat in c["org_custom"]:
            c["org_custom"].remove(cat)
        c["org_cat_state"].pop(cat, None)
        c["org_assign"] = {p: k for p, k in c["org_assign"].items() if k != cat}
        c["org_order"].pop(cat, None)
        c["positions"].pop(f"fence:{cat}", None)
        self.app.save()
        self.build()

    def reset_item(self, path):
        self.cfg["org_assign"].pop(path, None)
        self.app.save()
        self.build()

    def hide(self, path):
        self.cfg["org_hidden"].append(path)
        self.app.save()
        self.build()

    def unhide_all(self):
        self.cfg["org_hidden"] = []
        self.app.save()
        self.build()

    # ----- divers ------------------------------------------------------------------
    def apply_icon_visibility(self):
        """Masque les icônes Windows quand les panneaux sont actifs (option), sinon les restaure."""
        if not IS_WIN:
            return
        c = self.cfg
        want_hidden = c["org_enabled"] and c["org_hide_icons"]
        try:
            if want_hidden:
                set_desktop_icons(False)
                if not c["org_icons_hidden_by_app"]:
                    c["org_icons_hidden_by_app"] = True
                    self.app.save()
            elif c["org_icons_hidden_by_app"]:
                set_desktop_icons(True)
                c["org_icons_hidden_by_app"] = False
                self.app.save()
        except OSError:
            pass

    def shutdown(self):
        """À la fermeture : on rend ses icônes au bureau Windows."""
        if IS_WIN and self.cfg["org_icons_hidden_by_app"]:
            try:
                set_desktop_icons(True)
            except OSError:
                pass
            self.cfg["org_icons_hidden_by_app"] = False

    def _poll(self):
        """Toutes les 5 s : nouvelle liste d'applications ou bureau modifié -> on redessine."""
        c = self.cfg
        try:
            if c["org_enabled"] and self._tdrag is None:
                changed = self._signature() != self._sig
                if self._apps_new is not None:
                    changed = changed or self._apps_new != self.apps
                    self.apps, self._apps_new = self._apps_new, None
                if changed:
                    self.build()
                if (c["org_source"] == "apps"
                        and time.time() - self._apps_time >= self.APPS_REFRESH_S):
                    self.refresh_apps()  # nouvelles applications installées / désinstallées
        except tk.TclError:
            return
        self.app.root.after(self.POLL_MS, self._poll)

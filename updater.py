# -*- coding: utf-8 -*-
"""
Mises à jour automatiques via les « Releases » d'un dépôt GitHub.

Chaque version publiée doit porter un tag du type « v1.2.0 » et contenir
l'installateur « DeskMonitor-Setup-1.2.0.exe » en pièce jointe (voir publier_version.bat).
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from core import APP_NAME, APP_VERSION, version_tuple

API = "https://api.github.com/repos/{repo}/releases/latest"


def check(repo, timeout=10):
    """Retourne {"version", "url", "notes", "page"} si une version plus récente existe, sinon None."""
    repo = (repo or "").strip().strip("/")
    if repo.count("/") != 1:
        raise ValueError("Indiquez le dépôt sous la forme « utilisateur/projet ».")
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            raise ValueError(f"Aucune version publiée sur « {repo} » (ou dépôt introuvable / privé).") from None
        raise
    tag = data.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(APP_VERSION):
        return None
    assets = data.get("assets", [])
    if sys.platform == "darwin":  # Mac : .dmg adapté au processeur (Apple Silicon / Intel)
        arch = "arm64" if platform.machine() == "arm64" else "intel"
        dmgs = [a for a in assets if a.get("name", "").lower().endswith(".dmg")]
        asset = next((a for a in dmgs if arch in a["name"].lower()), dmgs[0] if dmgs else None)
        kind = "….dmg"
    else:
        asset = next((a for a in assets
                      if a.get("name", "").lower().endswith(".exe") and "setup" in a["name"].lower()), None)
        kind = "…Setup….exe"
    if asset is None:
        raise ValueError(f"La version {tag} ne contient pas d'installateur ({kind}).")
    return {"version": tag.lstrip("vV"), "url": asset["browser_download_url"],
            "notes": (data.get("body") or "").strip(), "page": data.get("html_url", "")}


def download(url, progress=None):
    """Télécharge l'installateur dans le dossier temporaire et renvoie son chemin."""
    dest = os.path.join(tempfile.gettempdir(), os.path.basename(url.split("?")[0]) or "DeskMonitor-Setup.exe")
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    return dest


def run_installer(path):
    """Windows : installation silencieuse (l'installateur relance DeskMonitor).
    Mac : ouvre l'image disque ; il suffit de glisser DeskMonitor dans Applications."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], close_fds=True)

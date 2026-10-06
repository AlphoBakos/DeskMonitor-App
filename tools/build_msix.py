# -*- coding: utf-8 -*-
"""Paquet Microsoft Store (MSIX) de DeskMonitor.

Prérequis : build.bat lancé (application construite dans build\\dist\\DeskMonitor) et le Windows SDK (makeappx).
Usage :
    python tools/build_msix.py            → Installateur\\DeskMonitor-<version>.msix (à envoyer dans Partner Center)
    python tools/build_msix.py --layout   → seulement le dossier build\\msix (essai local en mode développeur :
                                             Add-AppxPackage -Register build\\msix\\AppxManifest.xml)
Le Store signe lui-même le paquet : aucun certificat n'est nécessaire pour le publier."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "build" / "dist" / "DeskMonitor"
LAYOUT = ROOT / "build" / "msix"
MSIX_DIR = ROOT / "installer" / "msix"


def app_version():
    text = (ROOT / "core.py").read_text(encoding="utf-8")
    v = re.search(r'APP_VERSION = "([\d.]+)"', text).group(1)
    parts = (v.split(".") + ["0", "0", "0"])[:3]
    return ".".join(parts) + ".0"   # le Store exige 4 nombres, le dernier à 0


def makeappx():
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    found = sorted(kits.glob("10.*/x64/makeappx.exe"), key=lambda p: [int(x) for x in p.parent.parent.name.split(".")])
    if not found:
        sys.exit("makeappx.exe introuvable : installez le Windows SDK (winget install Microsoft.WindowsSDK.10.0.26100)")
    return found[-1]


def logos(dest):
    """Icônes demandées par Windows et le Store, tirées de assets/DeskMonitor.png."""
    src = Image.open(ROOT / "assets" / "DeskMonitor.png").convert("RGBA")
    dest.mkdir(parents=True, exist_ok=True)

    def square(size, name, margin=0.0):
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        inner = round(size * (1 - 2 * margin))
        icon = src.resize((inner, inner), Image.LANCZOS)
        canvas.paste(icon, ((size - inner) // 2, (size - inner) // 2), icon)
        canvas.save(dest / name)

    square(50, "StoreLogo.png")
    square(44, "Square44x44Logo.png")
    square(44, "Square44x44Logo.targetsize-44_altform-unplated.png")
    square(150, "Square150x150Logo.png", margin=0.18)
    wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
    icon = src.resize((96, 96), Image.LANCZOS)
    wide.paste(icon, ((310 - 96) // 2, (150 - 96) // 2), icon)
    wide.save(dest / "Wide310x150Logo.png")


def main():
    if not (DIST / "DeskMonitor.exe").exists():
        sys.exit("build\\dist\\DeskMonitor introuvable : lancez d'abord build.bat")
    ident = json.loads((MSIX_DIR / "identity.json").read_text(encoding="utf-8"))
    version = app_version()
    if LAYOUT.exists():
        shutil.rmtree(LAYOUT)
    shutil.copytree(DIST, LAYOUT)
    logos(LAYOUT / "Assets")
    manifest = (MSIX_DIR / "AppxManifest.xml").read_text(encoding="utf-8")
    manifest = (manifest.replace("{NAME}", ident["name"]).replace("{PUBLISHER}", ident["publisher"])
                .replace("{PUBLISHER_DISPLAY}", ident["publisher_display"]).replace("{VERSION}", version))
    (LAYOUT / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    print(f"dossier du paquet prêt : {LAYOUT} (version {version})")
    if "--layout" in sys.argv:
        return
    out = ROOT / "Installateur" / f"DeskMonitor-{version.rsplit('.', 1)[0]}.msix"
    out.parent.mkdir(exist_ok=True)
    subprocess.run([str(makeappx()), "pack", "/o", "/d", str(LAYOUT), "/p", str(out)], check=True,
                   stdout=subprocess.DEVNULL)
    print(f"paquet créé : {out} ({out.stat().st_size // 1_000_000} Mo)")


if __name__ == "__main__":
    main()

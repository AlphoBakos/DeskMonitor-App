# -*- coding: utf-8 -*-
"""Génère assets/DeskMonitor.ico (utilisé par l'exe et l'installateur)."""
from pathlib import Path

from core import make_icon_image

out = Path(__file__).resolve().parent / "assets"
out.mkdir(exist_ok=True)
img = make_icon_image(256)
img.save(out / "DeskMonitor.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out / "DeskMonitor.png")
# icône macOS (.icns) : générée depuis la version 1024 px pour rester nette sur écran Retina
make_icon_image(1024).save(out / "DeskMonitor.icns")
print("Icônes générées :", out / "DeskMonitor.ico", "+ .icns")

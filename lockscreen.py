# -*- coding: utf-8 -*-
"""Écran de verrouillage de Windows : DeskMonitor ne le gère plus (2.4.0). Ce module sert seulement à remettre
une dernière fois l'image choisie, sans la date qu'elle portait."""
import os
import subprocess
from datetime import datetime

from core import CONFIG_DIR, IS_WIN

if IS_WIN:
    import winreg

OUT_DIR = CONFIG_DIR / "lockscreen"
CDM_KEY = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"


_PS_SET_LOCK = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
$asOp = ($m | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAct = ($m | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.System.UserProfile.LockScreen, Windows.System.UserProfile, ContentType = WindowsRuntime]
$t = $asOp.MakeGenericMethod([Windows.Storage.StorageFile]).Invoke($null, @([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:DM_LOCK_PATH)))
$t.Wait(-1) | Out-Null
$a = $asAct.Invoke($null, @([Windows.System.UserProfile.LockScreen]::SetImageFileAsync($t.Result)))
$a.Wait(-1) | Out-Null
'OK'
"""


def apply_image(img):
    """Enregistre l'image et l'applique à l'écran de verrouillage. Retourne son chemin."""
    if not IS_WIN:
        raise OSError("Écran de verrouillage : Windows uniquement")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # nouveau nom à chaque fois : Windows met les images en cache selon leur chemin
    path = OUT_DIR / f"verrouillage-{datetime.now():%Y%m%d-%H%M%S}.jpg"
    img.save(path, quality=93)
    for old in OUT_DIR.glob("verrouillage-*.jpg"):
        if old != path:
            old.unlink(missing_ok=True)
    env = dict(os.environ, DM_LOCK_PATH=str(path))
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SET_LOCK],
                         capture_output=True, text=True, env=env, timeout=60,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    if "OK" not in res.stdout:
        raise OSError((res.stderr or res.stdout or "échec inconnu").strip().splitlines()[-1])
    # l'image choisie ne doit pas être remplacée par « Windows à la une »
    _set_dword(CDM_KEY, "RotatingLockScreenEnabled", 0)
    return str(path)


def _set_dword(key, name, value):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))



def apply_plain(path):
    """(thread) Applique l'image telle quelle ; les erreurs sont ignorées (rien d'autre à faire)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            apply_image(im.convert("RGB"))
    except Exception:  # noqa: BLE001
        pass

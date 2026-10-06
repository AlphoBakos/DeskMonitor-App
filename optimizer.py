# -*- coding: utf-8 -*-
"""Optimisation : nettoyage du cache, de la corbeille, de la mémoire, du DNS ; plans d'alimentation."""
import ctypes
import glob
import os
import stat
import sys
import tempfile
import time
from pathlib import Path


import psutil


from core import (
    IS_WIN,
    fmt_bytes,
    run_cmd,
    is_admin,
    IS_MAC,
)
if IS_WIN:
    from ctypes import wintypes


# --------------------------------------------------------------------------- #
#  Optimisation
# --------------------------------------------------------------------------- #
class Optimizer:
    @staticmethod
    def _excluded():
        ex = set()
        meipass = getattr(sys, "_MEIPASS", None)  # dossier temporaire de l'exe
        if meipass:
            ex.add(os.path.normcase(os.path.abspath(meipass)))
        return ex

    @classmethod
    def _clean_dir(cls, path, excluded):
        """Supprime le contenu de `path` (pas le dossier lui-même).
        Retourne (octets libérés, éléments ignorés)."""
        freed = skipped = 0
        try:
            entries = list(os.scandir(path))
        except OSError:
            return 0, 0
        for e in entries:
            try:
                if os.path.normcase(os.path.abspath(e.path)) in excluded:
                    continue
                # ne jamais suivre de liens/jonctions
                if e.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(e.path)):
                    continue
                if e.is_dir(follow_symlinks=False):
                    f, s = cls._clean_dir(e.path, excluded)
                    freed += f
                    skipped += s
                    try:
                        os.rmdir(e.path)
                    except OSError:
                        pass
                else:
                    size = e.stat(follow_symlinks=False).st_size
                    try:
                        os.remove(e.path)
                    except PermissionError:
                        os.chmod(e.path, stat.S_IWRITE)
                        os.remove(e.path)
                    freed += size
            except OSError:
                skipped += 1
        return freed, skipped

    @staticmethod
    def cache_targets(browsers=True):
        home = Path.home()
        targets = [tempfile.gettempdir()]
        if IS_WIN:
            local = os.getenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
            windir = os.getenv("WINDIR", r"C:\Windows")
            targets += [
                os.path.join(windir, "Temp"),
                os.path.join(local, "Microsoft", "Windows", "INetCache"),
                os.path.join(local, "CrashDumps"),
                os.path.join(local, "D3DSCache"),
            ]
            if browsers:
                for base in (r"Google\Chrome", r"Microsoft\Edge", r"BraveSoftware\Brave-Browser",
                             r"Vivaldi", r"Chromium"):
                    for sub in ("Cache", "Code Cache", "GPUCache"):
                        targets += glob.glob(os.path.join(local, base, "User Data", "*", sub))
                targets += glob.glob(os.path.join(local, "Mozilla", "Firefox", "Profiles", "*", "cache2"))
                targets += glob.glob(os.path.join(os.getenv("APPDATA", ""), "Opera Software", "*", "Cache"))
        elif sys.platform == "darwin":
            targets.append(str(home / "Library" / "Caches"))
        else:
            targets.append(str(home / ".cache" / "thumbnails"))
            if browsers:
                for b in ("mozilla", "google-chrome", "chromium", "BraveSoftware"):
                    targets.append(str(home / ".cache" / b))
        seen, result = set(), []
        for t in targets:
            key = os.path.normcase(os.path.abspath(t))
            if key not in seen and os.path.isdir(t):
                seen.add(key)
                result.append(t)
        return result

    @classmethod
    def clean_cache(cls, browsers=True, recycle=False):
        excluded = cls._excluded()
        freed = skipped = 0
        for t in cls.cache_targets(browsers):
            f, s = cls._clean_dir(t, excluded)
            freed += f
            skipped += s
        msg = f"Cache nettoyé : {fmt_bytes(freed)} libérés"
        if recycle:
            msg += " · " + cls.empty_recycle_bin()
        if skipped:
            msg += f" ({skipped} fichiers en cours d'utilisation ignorés)"
        return msg

    @staticmethod
    def empty_recycle_bin():
        if IS_MAC:  # le Finder vide la corbeille (macOS peut demander l'autorisation la 1re fois)
            code, _ = run_cmd(["osascript", "-e", 'tell application "Finder" to empty trash'])
            return "Corbeille vidée" if code == 0 else "Impossible de vider la corbeille"
        if not IS_WIN:
            return "Corbeille : Windows uniquement"

        class SHQUERYRBINFO(ctypes.Structure):
            if ctypes.sizeof(ctypes.c_void_p) == 4:
                _pack_ = 1
            _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        shell32 = ctypes.windll.shell32
        shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if info.i64NumItems == 0:
            return "Corbeille déjà vide"
        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        shell32.SHEmptyRecycleBinW(None, None, 0x07)
        return f"Corbeille vidée ({fmt_bytes(info.i64Size)})"

    @staticmethod
    def free_ram():
        if not IS_WIN:
            return "Libération de la RAM : disponible sous Windows uniquement"
        before = psutil.virtual_memory().available
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        access = 0x1000 | 0x0100  # QUERY_LIMITED_INFORMATION | SET_QUOTA
        count = 0
        own = os.getpid()
        for pid in psutil.pids():
            if pid in (0, 4, own):
                continue
            h = k32.OpenProcess(access, False, pid)
            if h:
                if psapi.EmptyWorkingSet(h):
                    count += 1
                k32.CloseHandle(h)
        time.sleep(1.0)
        gained = max(0, psutil.virtual_memory().available - before)
        msg = f"RAM optimisée : {fmt_bytes(gained)} récupérés sur {count} processus"
        if not is_admin():
            msg += " (lancez en admin pour plus d'effet)"
        return msg

    @staticmethod
    def flush_dns():
        if IS_WIN:
            code, _ = run_cmd(["ipconfig", "/flushdns"])
            return "Cache DNS vidé" if code == 0 else "Échec du vidage DNS"
        return "Vidage DNS : Windows uniquement"

    @staticmethod
    def current_power_plan():
        if not IS_WIN:
            return "?"
        code, out = run_cmd(["powercfg", "/getactivescheme"])
        if code == 0 and "(" in out:
            return out[out.rfind("(") + 1:out.rfind(")")]
        return "?"

    @staticmethod
    def set_power_plan(high_perf):
        if not IS_WIN:
            return "Plans d'alimentation : Windows uniquement"
        scheme = "SCHEME_MIN" if high_perf else "SCHEME_BALANCED"
        code, _ = run_cmd(["powercfg", "/setactive", scheme])
        if code != 0:
            return "Ce plan d'alimentation n'est pas disponible sur cette machine"
        return f"Plan d'alimentation : {Optimizer.current_power_plan()}"

    @classmethod
    def boost_all(cls, browsers, recycle):
        parts = [cls.clean_cache(browsers, recycle), cls.free_ram(), cls.flush_dns()]
        return "\n".join(parts)

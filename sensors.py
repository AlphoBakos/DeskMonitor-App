# -*- coding: utf-8 -*-
"""Capteurs complémentaires : carte graphique (GPU), adresses IP et ping."""

import ctypes
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes
    import winreg


# --------------------------------------------------------------------------- #
#  Réseau
# --------------------------------------------------------------------------- #
def local_ip():
    """IP locale de l'interface utilisée pour sortir sur internet (aucun paquet envoyé)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def public_ip():
    for url in ("https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                ip = r.read(64).decode("ascii", "ignore").strip()
            if 6 < len(ip) < 46:
                return ip
        except Exception:  # noqa: BLE001
            continue
    return None


def tcp_ping(host, port=443, timeout=2.0):
    """Latence (ms) d'une connexion TCP vers host:port, ou None si injoignable.
    Ne nécessite pas de droits administrateur, contrairement à un ping ICMP."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return None
    return (time.perf_counter() - start) * 1000


# --------------------------------------------------------------------------- #
#  Carte graphique
# --------------------------------------------------------------------------- #
def _gpu_registry_info():
    """(nom, mémoire dédiée en octets) de la carte graphique la mieux dotée."""
    best = (None, 0)
    if not IS_WIN:
        return best
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return best
    with root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, sub) as k:
                    name = winreg.QueryValueEx(k, "DriverDesc")[0]
                    try:
                        mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                    except OSError:
                        mem = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                    if isinstance(mem, bytes):
                        mem = int.from_bytes(mem, "little")
                    if best[0] is None or mem > best[1]:
                        best = (name, int(mem))
            except OSError:
                continue
    return best


class _Pdh:
    """Compteurs de performance Windows « GPU Engine » (toutes marques de GPU)."""
    PDH_FMT_DOUBLE = 0x00000200
    PDH_MORE_DATA = 0x800007D2

    class _Value(ctypes.Structure):
        _fields_ = [("CStatus", ctypes.c_uint32), ("doubleValue", ctypes.c_double)]

    class _Item(ctypes.Structure):
        pass

    _Item._fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _Value)]

    def __init__(self):
        pdh = self.pdh = ctypes.WinDLL("pdh")
        for fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData",
                   "PdhGetFormattedCounterArrayW"):
            getattr(pdh, fn).restype = ctypes.c_uint32
        pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_size_t,
                                              ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                     ctypes.POINTER(wintypes.DWORD),
                                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.query = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
            raise OSError("PdhOpenQuery")
        self.util = self._add(r"\GPU Engine(*engtype_3D)\Utilization Percentage")
        self.mem = self._add(r"\GPU Adapter Memory(*)\Dedicated Usage")
        if self.util is None:
            raise OSError("Compteurs GPU indisponibles")
        pdh.PdhCollectQueryData(self.query)

    def _add(self, path):
        c = ctypes.c_void_p()
        ok = self.pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(c)) == 0
        return c if ok else None

    def _values(self, counter):
        if counter is None:
            return []
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        r = self.pdh.PdhGetFormattedCounterArrayW(counter, self.PDH_FMT_DOUBLE, ctypes.byref(size),
                                                  ctypes.byref(count), None)
        if r != self.PDH_MORE_DATA or not size.value:
            return []
        buf = (ctypes.c_byte * size.value)()
        if self.pdh.PdhGetFormattedCounterArrayW(counter, self.PDH_FMT_DOUBLE, ctypes.byref(size),
                                                 ctypes.byref(count), buf) != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(self._Item))
        return [(items[i].szName or "", items[i].FmtValue.doubleValue) for i in range(count.value)
                if items[i].FmtValue.CStatus in (0, 1)]

    def sample(self):
        self.pdh.PdhCollectQueryData(self.query)
        # comme le Gestionnaire des tâches : somme par moteur, puis le moteur le plus chargé
        engines = {}
        for name, val in self._values(self.util):
            try:
                key = name.split("luid_", 1)[1].split("_engtype", 1)[0].replace("_phys", "")
            except IndexError:
                key = name
            engines[key] = engines.get(key, 0.0) + val
        util = min(100.0, max(engines.values(), default=0.0))
        mem = max((v for _, v in self._values(self.mem)), default=None)
        return util, mem


class GpuMonitor:
    def __init__(self):
        self.name, self.mem_total = _gpu_registry_info()
        self.smi = self._find_smi()
        self.pdh = None
        if not self.smi and IS_WIN:
            try:
                self.pdh = _Pdh()
            except OSError:
                self.pdh = None

    @staticmethod
    def _find_smi():
        cand = [shutil.which("nvidia-smi")]
        if IS_WIN:
            cand += [os.path.join(os.getenv("WINDIR", r"C:\Windows"), "System32", "nvidia-smi.exe"),
                     r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"]
        return next((c for c in cand if c and os.path.isfile(c)), None)

    @property
    def available(self):
        return bool(self.smi or self.pdh)

    def sample(self):
        """dict(name, util, mem_used, mem_total, temp) — valeurs None si inconnues."""
        if self.smi:
            try:
                flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
                out = subprocess.run(
                    [self.smi, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, creationflags=flags).stdout
                util, used, total, temp, name = [x.strip() for x in out.splitlines()[0].split(",", 4)]
                return {"name": name, "util": float(util), "mem_used": float(used) * 1024 ** 2,
                        "mem_total": float(total) * 1024 ** 2, "temp": float(temp)}
            except Exception:  # noqa: BLE001
                return None
        if self.pdh:
            try:
                util, mem = self.pdh.sample()
            except OSError:
                return None
            return {"name": self.name, "util": util, "mem_used": mem,
                    "mem_total": self.mem_total or None, "temp": None}
        return None

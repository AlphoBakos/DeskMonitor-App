# -*- coding: utf-8 -*-
"""Sources de données des cartes (batterie détaillée, musique, calendrier, météo, processus).
Chaque fonction est lente ou bloquante : à appeler depuis un thread, jamais depuis l'interface."""
import json
import os
import plistlib
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import psutil

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

try:  # Windows : session multimédia du système (Spotify, navigateur, lecteurs…), via le paquet « winsdk »
    if not IS_WIN:
        raise ImportError
    import asyncio
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _Smtc,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlayStatus)
    WIN_MEDIA = True
except Exception:  # noqa: BLE001
    WIN_MEDIA = False


def _run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "ignore").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _http_json(url, timeout=8):
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "DeskMonitor"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read(200000).decode("utf-8", "ignore"))


# ---------------------------------------------------------------------------
#  Batterie : santé, cycles, température, puissance
# ---------------------------------------------------------------------------
_health_cache = {"t": 0.0, "v": None}


def _health_from_profiler():
    if time.time() - _health_cache["t"] > 900:
        import re
        _health_cache["t"] = time.time()
        m = re.search(r"Maximum Capacity:\s*(\d+)\s*%", _run(["system_profiler", "SPPowerDataType"], 20))
        _health_cache["v"] = float(m.group(1)) if m else None
    return _health_cache["v"]


_win_bat_static = {"t": 0.0, "design": None, "cycles": None}


def _win_battery_details():
    """Windows : santé (capacité actuelle / d'origine), cycles et puissance, sans droits administrateur.
    La capacité d'origine vient du rapport `powercfg /batteryreport` (lent : mis en cache 24 h)."""
    import tempfile
    st = _win_bat_static
    if time.time() - st["t"] > 86400:
        st["t"] = time.time()
        path = os.path.join(tempfile.gettempdir(), "deskmonitor-batterie.xml")
        try:
            subprocess.run(["powercfg", "/batteryreport", "/xml", "/output", path], capture_output=True,
                           timeout=30, creationflags=0x08000000)
            import xml.etree.ElementTree as ET
            root = ET.parse(path).getroot()
            ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
            b = root.find(f".//{ns}Battery")
            if b is not None:
                st["design"] = int(b.findtext(f"{ns}DesignCapacity") or 0) or None
                st["cycles"] = int(b.findtext(f"{ns}CycleCount") or 0) or None
            os.remove(path)
        except Exception:  # noqa: BLE001
            pass
    script = ("$n='root\\wmi';"
              "$f=Get-CimInstance -Namespace $n -ClassName BatteryFullChargedCapacity -EA SilentlyContinue|Select -First 1;"
              "$c=Get-CimInstance -Namespace $n -ClassName BatteryCycleCount -EA SilentlyContinue|Select -First 1;"
              "$s=Get-CimInstance -Namespace $n -ClassName BatteryStatus -EA SilentlyContinue|Select -First 1;"
              "\"$($f.FullChargedCapacity)|$($c.CycleCount)|$($s.ChargeRate)|$($s.DischargeRate)\"")
    out = {}
    try:
        txt = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=15,
                             creationflags=0x08000000).stdout.decode("utf-8", "ignore").strip()
        full, cycles, charge, discharge = (int(v) if v.strip().lstrip("-").isdigit() else 0 for v in txt.split("|"))
    except Exception:  # noqa: BLE001
        return out
    if st["design"] and full:
        out["health"] = min(100.0, full / st["design"] * 100)
    cycles = cycles or st["cycles"]
    if cycles:   # 0 = non fourni par le pilote : on n'affiche rien plutôt qu'un faux « 0 cycle »
        out["cycles"] = cycles
    if 0 < charge < 1_000_000:
        out["watts"] = charge / 1000.0
    elif 0 < discharge < 1_000_000:      # -2147483648 = valeur invalide (en charge)
        out["watts"] = -discharge / 1000.0
    return out


def battery_details():
    """{health %, cycles, temp °C, watts (+ charge / − décharge)} ou {} sans batterie."""
    if IS_WIN:
        try:
            import psutil
            if psutil.sensors_battery() is None:
                return {}
        except Exception:  # noqa: BLE001
            return {}
        return _win_battery_details()
    if not IS_MAC:
        return {}
    try:
        raw = subprocess.run(["ioreg", "-arn", "AppleSmartBattery"], capture_output=True, timeout=6).stdout
        data = plistlib.loads(raw)
        d = data[0] if isinstance(data, list) and data else data
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    design = d.get("DesignCapacity")
    maxcap = d.get("AppleRawMaxCapacity") or d.get("MaxCapacity")
    if design and maxcap and maxcap > 100:
        out["health"] = min(100.0, maxcap / design * 100)
    if "health" not in out:  # Mac récents : la santé n'est exposée que par system_profiler (lent, mise en cache)
        out["health"] = _health_from_profiler()
        if out["health"] is None:
            del out["health"]
    if "CycleCount" in d:
        out["cycles"] = int(d["CycleCount"])
    if d.get("Temperature"):
        out["temp"] = d["Temperature"] / 100.0
    amp = d.get("InstantAmperage", d.get("Amperage"))
    volt = d.get("Voltage")
    if amp is not None and volt:
        if amp >= 2 ** 63:  # entier signé stocké en non signé
            amp -= 2 ** 64
        out["watts"] = amp * volt / 1e6
    return out


# ---------------------------------------------------------------------------
#  Musique (Apple Music / Spotify)
# ---------------------------------------------------------------------------
_PLAYERS = (("Spotify", "Spotify", "com.spotify.client"), ("Music", "Music", "com.apple.Music"))


def _running(proc):
    return subprocess.run(["pgrep", "-x", proc], capture_output=True).returncode == 0


async def _win_session():
    return (await _Smtc.request_async()).get_current_session()


async def _win_now_playing():
    sess = await _win_session()
    if sess is None:
        return None
    props = await sess.try_get_media_properties_async()
    playing = sess.get_playback_info().playback_status == _PlayStatus.PLAYING
    if not (props.title or props.artist):
        return None
    return {"app": sess.source_app_user_model_id or "Windows", "title": props.title or "",
            "artist": props.artist or "", "playing": playing}


async def _win_command(cmd):
    sess = await _win_session()
    if sess is None:
        return
    if cmd == "playpause":
        await sess.try_toggle_play_pause_async()
    elif cmd == "next track":
        await sess.try_skip_next_async()
    elif cmd == "previous track":
        await sess.try_skip_previous_async()


def now_playing():
    """{app, title, artist, playing} du lecteur actif, ou None. Ne lance jamais l'application."""
    if IS_WIN:
        if not WIN_MEDIA:
            return None
        try:
            return asyncio.run(_win_now_playing())
        except Exception:  # noqa: BLE001
            return None
    if not IS_MAC:
        return None
    for app, proc, bundle in _PLAYERS:
        if not _running(proc):
            continue
        script = (f'tell application id "{bundle}"\n'
                  'if player state is stopped then return ""\n'
                  'return (player state as text) & "|" & (name of current track) & "|" & (artist of current track)\n'
                  'end tell')
        out = _run(["osascript", "-e", script])
        if out.count("|") >= 2:
            state, title, artist = out.split("|", 2)
            return {"app": app, "title": title, "artist": artist, "playing": state.strip() == "playing"}
    return None


def player_command(app, cmd):
    """cmd : playpause, next track, previous track."""
    if IS_WIN:
        if WIN_MEDIA:
            try:
                asyncio.run(_win_command(cmd))
            except Exception:  # noqa: BLE001
                pass
        return
    bundle = {a: b for a, _, b in _PLAYERS}.get(app)
    if bundle and IS_MAC:
        _run(["osascript", "-e", f'tell application id "{bundle}" to {cmd}'])


# ---------------------------------------------------------------------------
#  Calendrier et rappels (EventKit)
# ---------------------------------------------------------------------------
_store = {"obj": None, "events_ok": None, "reminders_ok": None}


def _eventkit():
    if _store["obj"] is None:
        from EventKit import EKEventStore
        _store["obj"] = EKEventStore.alloc().init()
    return _store["obj"]


def _request(kind):
    """Demande l'accès (une seule fois) ; attend la réponse de l'utilisateur."""
    key = f"{kind}_ok"
    if _store[key] is not None:
        return _store[key]
    from EventKit import EKEntityTypeEvent, EKEntityTypeReminder
    store = _eventkit()
    done = threading.Event()
    result = {"ok": False}

    def cb(granted, _err):
        result["ok"] = bool(granted)
        done.set()

    if kind == "events" and hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(cb)
    elif kind == "reminders" and hasattr(store, "requestFullAccessToRemindersWithCompletion_"):
        store.requestFullAccessToRemindersWithCompletion_(cb)
    else:
        store.requestAccessToEntityType_completion_(EKEntityTypeEvent if kind == "events" else EKEntityTypeReminder, cb)
    done.wait(60)
    _store[key] = result["ok"]
    return result["ok"]


def next_events(limit=4):
    """[(titre, heure de début, journée entière?)] des 2 prochains jours, ou None si accès refusé."""
    if not IS_MAC:
        return None
    try:
        if not _request("events"):
            return None
        from Foundation import NSDate
        store = _eventkit()
        now = NSDate.date()
        end = NSDate.dateWithTimeIntervalSinceNow_(2 * 86400)
        evs = store.eventsMatchingPredicate_(store.predicateForEventsWithStartDate_endDate_calendars_(now, end, None))
        rows = []
        for e in evs or []:
            start = datetime.fromtimestamp(e.startDate().timeIntervalSince1970())
            endd = datetime.fromtimestamp(e.endDate().timeIntervalSince1970())
            if endd >= datetime.now():
                rows.append((str(e.title()), start, bool(e.isAllDay())))
        rows.sort(key=lambda r: r[1])
        return rows[:limit]
    except Exception:  # noqa: BLE001
        return None


def reminders_open():
    """(nombre de rappels à faire, [titres]) ou None si accès refusé."""
    if not IS_MAC:
        return None
    try:
        if not _request("reminders"):
            return None
        store = _eventkit()
        done = threading.Event()
        box = []

        def cb(rems):
            box.extend(str(r.title()) for r in (rems or []))
            done.set()

        store.fetchRemindersMatchingPredicate_completion_(
            store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(None, None, None), cb)
        done.wait(15)
        return len(box), box[:3]
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
#  Météo (Open-Meteo, sans clé)
# ---------------------------------------------------------------------------
WEATHER_CODES = {
    0: ("☀️", "Dégagé"), 1: ("🌤", "Plutôt dégagé"), 2: ("⛅", "Éclaircies"), 3: ("☁️", "Couvert"),
    45: ("🌫", "Brouillard"), 48: ("🌫", "Brouillard givrant"), 51: ("🌦", "Bruine"), 53: ("🌦", "Bruine"),
    55: ("🌦", "Bruine"), 61: ("🌧", "Pluie"), 63: ("🌧", "Pluie"), 65: ("🌧", "Forte pluie"),
    71: ("🌨", "Neige"), 73: ("🌨", "Neige"), 75: ("🌨", "Forte neige"), 80: ("🌦", "Averses"),
    81: ("🌧", "Averses"), 82: ("⛈", "Fortes averses"), 95: ("⛈", "Orage"), 96: ("⛈", "Orage"), 99: ("⛈", "Orage"),
}
WEATHER_EN = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
              51: "drizzle", 53: "drizzle", 55: "drizzle", 61: "rain", 63: "rain", 65: "heavy rain", 71: "snow",
              73: "snow", 75: "heavy snow", 80: "showers", 81: "showers", 82: "heavy showers", 95: "thunderstorms",
              96: "thunderstorms", 99: "thunderstorms"}
_geo = {}


def _locate(city):
    if city in _geo:
        return _geo[city]
    if city:
        d = _http_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=fr&name="
                       + urllib.parse.quote(city))
        r = (d.get("results") or [None])[0]
        loc = (r["latitude"], r["longitude"], r["name"]) if r else None
    else:  # position approximative d'après l'adresse IP
        d = _http_json("https://ipwho.is/")
        loc = (d["latitude"], d["longitude"], d.get("city", "")) if d.get("success") else None
    if loc:
        _geo[city] = loc
    return loc


def weather(city=""):
    """{city, temp, icon, label, tmin, tmax, hours:[(heure, temp, icône)]} ou None."""
    try:
        loc = _locate(city.strip())
        if not loc:
            return None
        lat, lon, name = loc
        d = _http_json("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&timezone=auto&forecast_days=2"
                       "&current=temperature_2m,weather_code&hourly=temperature_2m,weather_code"
                       "&daily=temperature_2m_max,temperature_2m_min" % (lat, lon))
        code = d["current"]["weather_code"]
        icon, label = WEATHER_CODES.get(code, ("🌡", ""))
        hours = []
        now_h = datetime.now().replace(minute=0, second=0, microsecond=0)
        for t, temp, wc in zip(d["hourly"]["time"], d["hourly"]["temperature_2m"], d["hourly"]["weather_code"]):
            dt = datetime.fromisoformat(t)
            if dt > now_h and dt <= now_h + timedelta(hours=12) and dt.hour % 3 == 0:
                hours.append((dt.hour, temp, WEATHER_CODES.get(wc, ("🌡", ""))[0]))
        return {"city": name, "temp": d["current"]["temperature_2m"], "icon": icon, "label": label, "code": code,
                "tmin": d["daily"]["temperature_2m_min"][0], "tmax": d["daily"]["temperature_2m_max"][0],
                "hours": hours[:4]}
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
#  Processus les plus gourmands
# ---------------------------------------------------------------------------
class ProcSampler:
    def __init__(self):
        self._procs = {}
        self._ncpu = psutil.cpu_count() or 1

    def top(self, n=5):
        rows, seen = [], set()
        for p in psutil.process_iter(["pid", "name"]):
            pid = p.info["pid"]
            # Windows : « System Idle Process » (pid 0) mesure le temps où le processeur ne fait RIEN,
            # et « System » / « Registry » / « Memory Compression » ne se quittent pas
            if IS_WIN and (pid in (0, 4) or (p.info["name"] or "") in ("Registry", "Memory Compression",
                                                                       "Secure System")):
                continue
            seen.add(pid)
            try:
                if pid not in self._procs:
                    self._procs[pid] = p
                    p.cpu_percent(None)  # amorçage : la 1re mesure vaut toujours 0
                    continue
                q = self._procs[pid]
                rows.append((q.cpu_percent(None) / self._ncpu, q.memory_info().rss, pid, p.info["name"] or "?"))
            except (psutil.Error, OSError):
                continue
        for pid in set(self._procs) - seen:
            self._procs.pop(pid, None)
        rows.sort(reverse=True)
        return rows[:n]


def quit_process(pid):
    try:
        if pid == os.getpid():
            return False
        psutil.Process(pid).terminate()
        return True
    except (psutil.Error, OSError):
        return False


# ---------------------------------------------------------------------------
#  Agenda par lien ICS (Google Agenda, Outlook.com, iCloud… : adresse privée au format .ics)
# ---------------------------------------------------------------------------
_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _http_text(url, timeout=12):
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "DeskMonitor"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read(4_000_000).decode("utf-8", "ignore")


def _ics_dt(name, val):
    """(datetime local, journée entière ?) d'une propriété DTSTART / DTEND."""
    if "VALUE=DATE" in name or len(val) == 8:
        return datetime.strptime(val[:8], "%Y%m%d"), True
    dt = datetime.strptime(val.rstrip("Z"), "%Y%m%dT%H%M%S")
    if val.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return dt, False


def _ics_occurrences(start, rule, lo, hi):
    """Début des occurrences d'un événement récurrent (DAILY, WEEKLY, MONTHLY, YEARLY) entre lo et hi."""
    params = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    freq, step = params.get("FREQ"), max(1, int(params.get("INTERVAL", "1") or 1))
    until = None
    if params.get("UNTIL"):
        try:
            until = _ics_dt("", params["UNTIL"][:15] if "T" in params["UNTIL"] else params["UNTIL"])[0]
        except ValueError:
            pass
    byday = params.get("BYDAY", _DAYS[start.weekday()]).split(",")
    monday0 = start.date() - timedelta(days=start.weekday())
    out, day = [], lo.date()
    while day <= hi.date():
        occ = datetime.combine(day, start.time())
        ok = occ >= start and (until is None or occ <= until + timedelta(days=1))
        if ok and freq == "DAILY":
            ok = (day - start.date()).days % step == 0
        elif ok and freq == "WEEKLY":
            ok = ((day - monday0).days // 7) % step == 0 and _DAYS[day.weekday()] in [d[-2:] for d in byday]
        elif ok and freq == "MONTHLY":
            ok = day.day == start.day and ((day.year - start.year) * 12 + day.month - start.month) % step == 0
        elif ok and freq == "YEARLY":
            ok = (day.month, day.day) == (start.month, start.day) and (day.year - start.year) % step == 0
        elif ok:
            ok = False
        if ok:
            out.append(occ)
        day += timedelta(days=1)
    return out


def ics_events(url, limit=4):
    """[(titre, début, journée entière ?)] des 2 prochains jours d'après un lien ICS, ou None en cas d'erreur."""
    try:
        url = url.strip()
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        raw = []
        for line in _http_text(url).splitlines():
            if line[:1] in (" ", "\t") and raw:
                raw[-1] += line[1:]
            else:
                raw.append(line)
        events, cur = [], None
        for line in raw:
            if line == "BEGIN:VEVENT":
                cur = {}
            elif line == "END:VEVENT":
                if cur:
                    events.append(cur)
                cur = None
            elif cur is not None and ":" in line:
                name, _, val = line.partition(":")
                cur.setdefault(name.split(";")[0], (name, val))
        now = datetime.now()
        lo = datetime.combine(now.date(), datetime.min.time())
        hi = now + timedelta(days=2)
        rows = []
        for e in events:
            if "DTSTART" not in e:
                continue
            start, allday = _ics_dt(*e["DTSTART"])
            end = _ics_dt(*e["DTEND"])[0] if "DTEND" in e else start + (timedelta(days=1) if allday else timedelta(hours=1))
            title = e.get("SUMMARY", ("", "(sans titre)"))[1].replace("\\,", ",").replace("\\n", " ")
            starts = _ics_occurrences(start, e["RRULE"][1], lo, hi) if "RRULE" in e else [start]
            for s in starts:
                if s + (end - start) >= now and s <= hi:
                    rows.append((title, s, allday))
        rows.sort(key=lambda r: r[1])
        return rows[:limit]
    except Exception:  # noqa: BLE001
        return None

#!/usr/bin/env python3
"""
Shared helpers for the 3-module thermal-management logging / plotting scripts
(MEP 311s/212s payload-pod project).

The Arduino reports one block per second containing the three module
temperatures (Plant / Power / Control), the controlling max temperature,
battery voltage, heater PWM/duty, and estimated current & power. Everything
serial- and parsing-related lives here so the entry scripts stay small.
"""

import glob
import re
import time
from datetime import datetime
from pathlib import Path

import serial

# CSV columns written for every reading.
FIELDS = ["timestamp", "elapsed_s",
          "temp_plant", "temp_power", "temp_control", "temp_max",
          "battery_V", "heater_pwm", "duty", "current_A", "power_W",
          "fan", "led", "mode"]

# The three module sensors: (csv column, label, colour) — used by every plot.
SENSORS = [
    ("temp_plant",   "Plant (cargo bay)", "tab:red"),
    ("temp_power",   "Power module",      "tab:blue"),
    ("temp_control", "Control module",    "tab:green"),
]

# One regex per serial line we care about.
PATTERNS = {
    "temp_plant":   re.compile(r"Temp Plant\s*=\s*([-\d.]+)"),
    "temp_power":   re.compile(r"Temp Power\s*=\s*([-\d.]+)"),
    "temp_control": re.compile(r"Temp Control\s*=\s*([-\d.]+)"),
    "temp_max":     re.compile(r"Temp Max\s*=\s*([-\d.]+)"),
    "battery_V":    re.compile(r"Battery Voltage\s*=\s*([-\d.]+)"),
    "heater_pwm":   re.compile(r"Heater PWM\s*=\s*(\d+)"),
    "duty":         re.compile(r"Duty\s*=\s*([-\d.]+)"),
    "current_A":    re.compile(r"Current\s*=\s*([-\d.]+)"),
    "power_W":      re.compile(r"Power\s*=\s*([-\d.]+)"),
    "fan":          re.compile(r"Fan\s*=\s*(ON|OFF)"),
    "led":          re.compile(r"LED\s*=\s*(STEADY|FAST|SLOW|OFF)"),
    "mode":         re.compile(r"Mode:\s*(.+)"),
}

SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return float("nan")


def smooth_curve(x, y, points=400, sigma=2.5):
    """
    Return a dense (xs, ys) that draws a SMOOTH TREND through the readings.

    The DHT11 quantizes temperature into coarse steps, so the raw data is a
    staircase. We low-pass it out with a Gaussian filter (strength = `sigma`,
    in samples) and then draw a cubic spline through the de-stepped values.
    sigma <= 0 disables smoothing. Falls back gracefully on too-few points.
    """
    import numpy as np
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if len(x) < 3 or sigma is None or sigma <= 0:
        return x, y

    xu, idx = np.unique(x, return_index=True)
    yu = y[idx]
    if len(xu) < 3:
        return xu, yu

    try:
        from scipy.ndimage import gaussian_filter1d
        s = min(sigma, len(yu) / 3.0)
        ys = gaussian_filter1d(yu, sigma=max(s, 0.5), mode="nearest")
    except Exception:
        ys = yu

    try:
        from scipy.interpolate import make_interp_spline
        k = 3 if len(xu) >= 4 else 2
        xs = np.linspace(xu.min(), xu.max(), max(points, len(xu)))
        return xs, make_interp_spline(xu, ys, k=k)(xs)
    except Exception:
        return xu, ys


def new_session_path(prefix="heat"):
    """Return a fresh, timestamped CSV path inside the sessions folder."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return SESSIONS_DIR / f"{prefix}_{stamp}.csv"


def probe_port(port, baud, seconds=2.0):
    """True if `port` emits any bytes within `seconds` (i.e. the real board)."""
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except (serial.SerialException, OSError):
        return False
    start = time.time()
    try:
        while time.time() - start < seconds:
            try:
                if ser.readline():
                    return True
            except (serial.SerialException, OSError):
                return False
    finally:
        try:
            ser.close()
        except Exception:
            pass
    return False


def list_ports():
    return sorted(glob.glob("/dev/cu.usbmodem*") +
                  glob.glob("/dev/cu.usbserial*") +
                  glob.glob("/dev/cu.wchusbserial*") +
                  glob.glob("/dev/ttyUSB*") +
                  glob.glob("/dev/ttyACM*"))


def autodetect_port(baud):
    """Pick the serial port that is actually sending data (skips dead/hub ports)."""
    candidates = list_ports()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for p in candidates:
        print(f"  probing {p} ...")
        if probe_port(p, baud):
            return p
    return candidates[0]


class SerialReader:
    """
    Resilient serial reader. `readings()` yields one parsed record dict per
    complete Arduino block and NEVER raises on I/O problems — it transparently
    reconnects forever until stop() is called. Junk/partial lines are ignored.
    """

    def __init__(self, port, baud=9600, status_cb=None):
        self.port = port
        self.baud = baud
        self.status_cb = status_cb
        self.on_raw = None          # optional: called with every raw line (debug)
        self.status = "connecting"
        self._stop = False

    def stop(self):
        self._stop = True

    def _set(self, s):
        self.status = s
        if self.status_cb:
            try:
                self.status_cb(s)
            except Exception:
                pass

    def _connect(self):
        while not self._stop:
            try:
                ser = serial.Serial(self.port, self.baud, timeout=2)
                self._set("connected")
                return ser
            except (serial.SerialException, OSError):
                self._set("reconnecting")
                time.sleep(1.0)
        return None

    def readings(self):
        record = {}
        ser = None
        while not self._stop:
            if ser is None:
                ser = self._connect()
                if ser is None:
                    break

            try:
                line = ser.readline()
            except (serial.SerialException, OSError):
                self._set("reconnecting")
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                record = {}
                time.sleep(0.5)
                continue
            except Exception:
                continue

            try:
                raw = line.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not raw:
                continue

            if self.on_raw:
                try:
                    self.on_raw(raw)
                except Exception:
                    pass

            for key, pat in PATTERNS.items():
                m = pat.search(raw)
                if m:
                    record[key] = m.group(1).strip()
                    break

            # "Mode:" ends a normal block; require at least the plant temp.
            if "mode" in record and "temp_plant" in record:
                rec = dict(record)
                record = {}
                yield rec

        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


def make_row(record, start_time, when=None):
    """Turn a parsed record into a full CSV row dict with timestamp + elapsed_s."""
    now = when if when is not None else time.time()
    record = dict(record)
    record["timestamp"] = datetime.now().isoformat(timespec="seconds")
    record["elapsed_s"] = round(now - start_time, 1)
    return {k: record.get(k, "") for k in FIELDS}


def scan_sessions(dirpath=SESSIONS_DIR):
    """Describe every CSV in the sessions folder for the interactive chooser."""
    import pandas as pd
    out = []
    for p in sorted(Path(dirpath).glob("*.csv")):
        info = {"path": p, "name": p.name, "rows": 0,
                "duration": None, "tmin": None, "tmax": None, "start": None}
        try:
            df = pd.read_csv(p)
            info["rows"] = len(df)
            if len(df):
                if "elapsed_s" in df:
                    info["duration"] = float(pd.to_numeric(df["elapsed_s"],
                                                           errors="coerce").max())
                # Use the controlling max temperature for the at-a-glance range.
                col = "temp_max" if "temp_max" in df else "temp_plant"
                if col in df:
                    t = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(t):
                        info["tmin"], info["tmax"] = float(t.min()), float(t.max())
                if "timestamp" in df:
                    info["start"] = str(df["timestamp"].iloc[0])
        except Exception as e:
            info["error"] = str(e)
        out.append(info)
    return out

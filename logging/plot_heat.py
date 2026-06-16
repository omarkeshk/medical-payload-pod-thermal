#!/usr/bin/env python3
"""
Plot module temperatures from saved run CSV(s).

  - One file  -> all three module curves (Plant / Power / Control), smoothed,
                 with the 35 C alert and 40 C limit lines.
  - Several files -> overlay ONE module (default the plant) across the runs,
                 e.g. to compare fan-on vs fan-off or heater-on vs cooling.

With no file given it lists every saved session (readings, duration, max-temp
range, start time) and lets you pick which to open.

Usage:
    python3 plot_heat.py                      # interactive chooser
    python3 plot_heat.py run.csv              # 3 module curves for one run
    python3 plot_heat.py a.csv b.csv          # overlay plant temp of each run
    python3 plot_heat.py a.csv b.csv --module temp_power
    python3 plot_heat.py run.csv --no-smooth -o run.png --no-show
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

import heat_common as hc


def choose_from_sessions():
    sessions = hc.scan_sessions()
    if not sessions:
        sys.exit(f"No session CSVs found in {hc.SESSIONS_DIR}.\nRun the logger first.")

    print(f"\nSaved sessions in {hc.SESSIONS_DIR}:\n")
    print(f"  {'#':>2}  {'file':<32} {'readings':>8} {'duration':>9} {'max °C':>13}  start")
    print("  " + "-" * 78)
    for i, s in enumerate(sessions, 1):
        dur = f"{s['duration']:.0f}s" if s['duration'] is not None else "—"
        trng = f"{s['tmin']:.1f}–{s['tmax']:.1f}" if s['tmin'] is not None else "—"
        start = (s['start'] or "")[:19]
        flag = "  (empty)" if s['rows'] == 0 else ""
        print(f"  {i:>2}  {s['name']:<32} {s['rows']:>8} {dur:>9} {trng:>13}  {start}{flag}")
    print()

    raw = input("Plot which?  number | 1,3 to overlay | 'a' all | Enter = latest : ").strip()
    if raw == "":
        chosen = [sessions[-1]]
    elif raw.lower() in ("a", "all"):
        chosen = sessions
    else:
        idxs = [int(t) - 1 for t in raw.replace(" ", "").split(",")
                if t.isdigit() and 1 <= int(t) <= len(sessions)]
        if not idxs:
            sys.exit("No valid selection.")
        chosen = [sessions[i] for i in idxs]

    chosen = [s for s in chosen if s["rows"] > 0]
    if not chosen:
        sys.exit("Nothing to plot — selected file(s) are empty.")
    return [s["path"] for s in chosen]


def flexible_ylim(ax, ys, margin_frac=0.08):
    yv = [y for y in ys if y == y]
    if not yv:
        return
    y0, y1 = min(yv), max(yv)
    if y1 == y0:
        y0 -= 1.0
        y1 += 1.0
    m = max(0.3, (y1 - y0) * margin_frac)
    ax.set_ylim(y0 - m, max(y1 + m, 41 if y1 > 36 else y1 + m))


def add_threshold_lines(ax):
    ax.axhline(40, color="red", ls="--", lw=1.0, label="40 °C limit")
    ax.axhline(35, color="orange", ls="--", lw=0.9, label="35 °C alert")


def plot_single(path, ax, sigma):
    """Three module curves for one run."""
    df = pd.read_csv(path)
    t = pd.to_numeric(df["elapsed_s"], errors="coerce")
    all_temps = []
    for col, label, color in hc.SENSORS:
        if col not in df:
            continue
        temp = pd.to_numeric(df[col], errors="coerce")
        all_temps += list(temp.dropna())
        if sigma and sigma > 0:
            xs, ys = hc.smooth_curve(t.to_numpy(), temp.to_numpy(), sigma=sigma)
            ax.plot(xs, ys, "-", lw=1.8, color=color, label=label)
            ax.plot(t, temp, ".", ms=3, color=color, alpha=0.22)
        else:
            ax.plot(t, temp, marker=".", ms=3, lw=1.4, color=color, label=label)
    add_threshold_lines(ax)
    flexible_ylim(ax, all_temps)
    ax.set_title(f"Module Temperatures — {Path(path).name}", fontweight="bold")
    return all_temps


def plot_overlay(paths, ax, sigma, module):
    """Overlay one module's temperature across several runs."""
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    label_of = dict((c, l) for c, l, _ in hc.SENSORS)
    all_temps = []
    for i, p in enumerate(paths):
        df = pd.read_csv(p)
        if module not in df or df.empty:
            print(f"(skipping {Path(p).name}: no {module})")
            continue
        t = pd.to_numeric(df["elapsed_s"], errors="coerce")
        temp = pd.to_numeric(df[module], errors="coerce")
        all_temps += list(temp.dropna())
        c = colors[i % len(colors)]
        if sigma and sigma > 0:
            xs, ys = hc.smooth_curve(t.to_numpy(), temp.to_numpy(), sigma=sigma)
            ax.plot(xs, ys, "-", lw=1.8, color=c, label=Path(p).name)
            ax.plot(t, temp, ".", ms=3, color=c, alpha=0.22)
        else:
            ax.plot(t, temp, marker=".", ms=3, lw=1.4, color=c, label=Path(p).name)
    add_threshold_lines(ax)
    flexible_ylim(ax, all_temps)
    ax.set_title(f"{label_of.get(module, module)} temperature — {len(paths)} runs",
                 fontweight="bold")
    return all_temps


def main():
    ap = argparse.ArgumentParser(description="Plot module temperatures from saved run CSV(s).")
    ap.add_argument("csv", nargs="*", help="CSV file(s). Omit for the interactive chooser.")
    ap.add_argument("-o", "--out", default=None, help="Output image path")
    ap.add_argument("--no-show", action="store_true", help="Save without opening a window")
    ap.add_argument("--smooth", type=float, default=2.5,
                    help="Smoothing strength (Gaussian sigma in samples; default 2.5)")
    ap.add_argument("--no-smooth", action="store_true", help="Straight segments through raw points")
    ap.add_argument("--module", default="temp_plant",
                    help="Which sensor to overlay when comparing runs (default temp_plant)")
    args = ap.parse_args()

    if args.csv:
        for c in args.csv:
            if not Path(c).exists():
                sys.exit(f"File not found: {c}")
        paths = args.csv
    else:
        paths = choose_from_sessions()

    sigma = 0 if args.no_smooth else args.smooth
    fig, ax = plt.subplots(figsize=(11, 6))
    if len(paths) == 1:
        plot_single(paths[0], ax, sigma)
        default_out = str(paths[0]).rsplit(".", 1)[0] + ".png"
    else:
        plot_overlay(paths, ax, sigma, args.module)
        default_out = str(hc.SESSIONS_DIR / "overlay.png")

    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()

    out = args.out or default_out
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()

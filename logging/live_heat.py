#!/usr/bin/env python3
"""
Live monitor for the 3-module payload pod — logs every reading to its own
per-run CSV AND plots the three module temperatures (Plant / Power / Control)
in real time, smoothed, with the 35 C alert and 40 C limit lines.

Runs forever until you close the window or press Ctrl-C; survives USB dropouts
and serial noise by reconnecting. Each run writes a new file under
sessions/heat_<date>_<time>.csv  (override with --csv).

Usage:
    python3 live_heat.py
    python3 live_heat.py --port /dev/cu.usbmodem21301
    python3 live_heat.py --window 180
    python3 live_heat.py --duration 600 --no-show
"""

import argparse
import csv
import sys
import threading
import time

import matplotlib.pyplot as plt

import heat_common as hc


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.t = []
        self.series = {col: [] for col, _, _ in hc.SENSORS}
        self.mode = ""
        self.tmax = float("nan")
        self.count = 0
        self.status = "connecting"
        self.running = True


def reader_loop(reader, shared, writer, fh, start):
    def on_status(s):
        with shared.lock:
            shared.status = s
    reader.status_cb = on_status

    try:
        for record in reader.readings():
            if not shared.running:
                break
            row = hc.make_row(record, start)
            try:
                writer.writerow(row)
                fh.flush()
            except Exception:
                pass
            with shared.lock:
                shared.t.append(row["elapsed_s"])
                for col, _, _ in hc.SENSORS:
                    shared.series[col].append(hc.to_float(row[col]))
                shared.tmax = hc.to_float(row["temp_max"])
                shared.mode = row["mode"]
                shared.count += 1
    except Exception as e:
        with shared.lock:
            shared.status = f"reader error: {e}"


def build_figure():
    fig, ax = plt.subplots(figsize=(10, 6))
    lines = {}
    for col, label, color in hc.SENSORS:
        (smooth,) = ax.plot([], [], color=color, lw=1.8, label=label)
        (raw,) = ax.plot([], [], color=color, marker=".", ms=3, ls="none", alpha=0.25)
        lines[col] = (smooth, raw)
    ax.axhline(40, color="red", ls="--", lw=1.0, label="40 °C limit")
    ax.axhline(35, color="orange", ls="--", lw=0.9, label="35 °C alert")
    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig, ax, lines


def flexible_limits(ax, xs, all_ys):
    if not xs:
        return
    x0, x1 = min(xs), max(xs)
    if x1 == x0:
        x1 = x0 + 1
    ax.set_xlim(x0, x1 + max(0.5, (x1 - x0) * 0.03))
    yv = [y for y in all_ys if y == y]
    if yv:
        y0, y1 = min(yv), max(yv)
        if y1 == y0:
            y0 -= 1.0
            y1 += 1.0
        m = max(0.5, (y1 - y0) * 0.08)
        # keep the 40 C limit visible once we get close
        ax.set_ylim(y0 - m, max(y1 + m, 41 if y1 > 36 else y1 + m))


def redraw(fig, ax, lines, shared, window):
    with shared.lock:
        t = list(shared.t)
        series = {c: list(v) for c, v in shared.series.items()}
        mode = shared.mode
        tmax = shared.tmax
        count = shared.count
        status = shared.status

    title = "Payload Pod — Module Temperatures (LIVE)"
    if not t:
        ax.set_title(f"{title}   [{status}…]", fontweight="bold", fontsize=11)
        return

    if window:
        cut = t[-1] - window
        keep = next((i for i, x in enumerate(t) if x >= cut), 0)
        t = t[keep:]
        series = {c: v[keep:] for c, v in series.items()}

    all_ys = []
    for col, _, _ in hc.SENSORS:
        y = series[col]
        all_ys += y
        xs, ys = hc.smooth_curve(t, y)
        lines[col][0].set_data(xs, ys)
        lines[col][1].set_data(t, y)
    flexible_limits(ax, t, all_ys)
    ax.set_title(f"{title}   [{count} readings | max {tmax:.1f}°C | {mode} | {status}]",
                 fontweight="bold", fontsize=11)


def main():
    ap = argparse.ArgumentParser(description="Live log + 3-module temperature plot (runs forever).")
    ap.add_argument("--port", help="Serial port (default: auto-detect the live one)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--csv", default=None, help="Output CSV (default: new sessions/heat_<time>.csv)")
    ap.add_argument("--window", type=float, default=None, help="Show only the last N seconds")
    ap.add_argument("--refresh", type=float, default=1.0, help="Plot refresh seconds (default 1)")
    ap.add_argument("--duration", type=float, default=None, help="Auto-stop after N seconds")
    ap.add_argument("--out", default=None, help="Final PNG path (default: alongside the CSV)")
    ap.add_argument("--no-show", action="store_true", help="Headless: don't open a window")
    args = ap.parse_args()

    port = args.port or hc.autodetect_port(args.baud)
    if not port:
        sys.exit("No serial port found. Plug in the Arduino or pass --port.")

    csv_path = args.csv or str(hc.new_session_path())
    print(f"Live on {port} @ {args.baud} baud -> {csv_path}")
    print("Runs until you close the window or press Ctrl-C.\n")

    fh = open(csv_path, "w", newline="")
    writer = csv.DictWriter(fh, fieldnames=hc.FIELDS)
    writer.writeheader()
    fh.flush()

    shared = Shared()
    reader = hc.SerialReader(port, args.baud)
    start = time.time()
    th = threading.Thread(target=reader_loop, args=(reader, shared, writer, fh, start), daemon=True)
    th.start()

    if not args.no_show:
        plt.ion()
    fig, ax, lines = build_figure()
    if not args.no_show:
        fig.show()

    try:
        while shared.running:
            if args.duration and (time.time() - start) >= args.duration:
                break
            if not args.no_show and not plt.fignum_exists(fig.number):
                break
            try:
                redraw(fig, ax, lines, shared, args.window)
            except Exception as e:
                print(f"(redraw skipped: {e})")
            try:
                plt.pause(args.refresh) if not args.no_show else time.sleep(args.refresh)
            except Exception:
                time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        shared.running = False
        reader.stop()
        th.join(timeout=3)
        try:
            fh.close()
        except Exception:
            pass
        out = args.out or (csv_path.rsplit(".", 1)[0] + ".png")
        try:
            redraw(fig, ax, lines, shared, args.window)
            fig.savefig(out, dpi=150)
            print(f"Saved {out}  ({shared.count} readings -> {csv_path})")
        except Exception as e:
            print(f"(could not save figure: {e})")
        if not args.no_show:
            plt.ioff()


if __name__ == "__main__":
    main()

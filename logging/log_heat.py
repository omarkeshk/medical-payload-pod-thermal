#!/usr/bin/env python3
"""
Log readings from the heat_trail_divider Arduino sketch to a per-run CSV.
No plot — just robust logging. Runs forever until Ctrl-C; reconnects on USB
dropouts and ignores serial noise / partial lines.

Each run writes a new file under  sessions/heat_<date>_<time>.csv  (override
with --csv). Use plot_heat.py afterwards to view any saved run.

Usage:
    python3 log_heat.py                       # auto-detect port, new session file
    python3 log_heat.py --port /dev/cu.usbmodem21301
    python3 log_heat.py --csv myrun.csv --duration 600
"""

import argparse
import csv
import sys
import threading
import time

import heat_common as hc


def main():
    ap = argparse.ArgumentParser(description="Log Arduino heat-control readings to CSV (runs forever).")
    ap.add_argument("--port", help="Serial port (default: auto-detect the live one)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--csv", default=None, help="Output CSV (default: new sessions/heat_<time>.csv)")
    ap.add_argument("--duration", type=float, default=None, help="Auto-stop after N seconds")
    args = ap.parse_args()

    port = args.port or hc.autodetect_port(args.baud)
    if not port:
        sys.exit("No serial port found. Plug in the Arduino or pass --port.")

    csv_path = args.csv or str(hc.new_session_path())
    print(f"Logging {port} @ {args.baud} baud -> {csv_path}")
    print("Runs until you press Ctrl-C.\n")

    reader = hc.SerialReader(port, args.baud, status_cb=lambda s: print(f"[{s}]"))
    start = time.time()
    n = 0

    # Watchdog: stop after --duration even if NO data ever arrives (the reader
    # loop polls _stop on every read timeout, so this ends it promptly).
    if args.duration:
        threading.Timer(args.duration, reader.stop).start()

    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=hc.FIELDS)
        writer.writeheader()
        fh.flush()
        try:
            for record in reader.readings():
                if args.duration and (time.time() - start) >= args.duration:
                    break
                row = hc.make_row(record, start)
                try:
                    writer.writerow(row)
                    fh.flush()
                except Exception as e:
                    print(f"(write error, continuing: {e})")
                    continue
                n += 1
                print(f"[{n:4d}] {row['elapsed_s']:>6}s  "
                      f"Plant={row['temp_plant']:>5}  Pow={row['temp_power']:>5}  "
                      f"Ctrl={row['temp_control']:>5}  Max={row['temp_max']:>5}C  "
                      f"Duty={row['duty']:>5}%  {row['power_W']}W  "
                      f"Batt={row['battery_V']}V  {row['mode']}")
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            reader.stop()

    print(f"\nWrote {n} readings to {csv_path}")


if __name__ == "__main__":
    main()

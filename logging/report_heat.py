#!/usr/bin/env python3
"""
Generate the report deliverables from a logged run (MEP 311s/212s payload pod).

Produces, into a report/ folder next to the CSV:
  1. <run>_temps.png   — 3 module temperature-time curves + 35/40 °C lines,
                          with the lumped-capacitance exponential fit on the
                          plant sensor (gives the transient time constant tau).
  2. <run>_power.png   — heater duty %, battery voltage, and estimated power.
  3. <run>_summary.md  — stats table: start / steady-state / max temp per
     <run>_summary.csv   module, ΔT, ≤40 °C compliance, time constant, mean
                          steady-state power / current / voltage.

These cover the spec's required "temperature-time curves from all three sensors
under steady-state conditions" plus the data for validating against the
analytical (resistor-network / lumped-capacity) predictions.

Usage:
    python3 report_heat.py                 # pick a session interactively
    python3 report_heat.py run.csv
    python3 report_heat.py run.csv --no-show
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import heat_common as hc


# ---------- analysis helpers ----------

def lumped_fit(t, T):
    """Fit T(t) = Tinf - (Tinf - T0) exp(-(t-t0)/tau). Returns dict or None."""
    from scipy.optimize import curve_fit
    t = np.asarray(t, float)
    T = np.asarray(T, float)
    m = ~(np.isnan(t) | np.isnan(T))
    t, T = t[m], T[m]
    if len(t) < 5:
        return None
    t0 = t[0]

    def model(tt, Tinf, tau, T0):
        return Tinf - (Tinf - T0) * np.exp(-(tt - t0) / tau)

    try:
        p0 = [T[-1], max((t[-1] - t0) / 3.0, 1.0), T[0]]
        lo = [T.min() - 25, 0.5, T.min() - 25]
        hi = [T.max() + 35, 1e5, T.max() + 25]
        popt, _ = curve_fit(model, t, T, p0=p0, bounds=(lo, hi), maxfev=20000)
        Tinf, tau, T0 = popt
        tt = np.linspace(t0, t[-1], 300)
        return {"Tinf": Tinf, "tau": tau, "T0": T0, "t": tt, "T": model(tt, *popt)}
    except Exception:
        return None


def steady_mean(t, series, frac=0.25):
    """Mean of `series` over the final `frac` of the run (steady-state estimate)."""
    t = np.asarray(t, float)
    s = pd.to_numeric(pd.Series(series), errors="coerce").to_numpy()
    if len(t) == 0:
        return float("nan")
    cut = t[-1] - frac * (t[-1] - t[0]) if t[-1] > t[0] else t[0]
    v = s[t >= cut]
    v = v[~np.isnan(v)]
    return float(np.mean(v)) if len(v) else float("nan")


# ---------- figures ----------

def fig_temperatures(df, t, out, show):
    fig, ax = plt.subplots(figsize=(11, 6))
    for col, label, color in hc.SENSORS:
        if col not in df:
            continue
        temp = pd.to_numeric(df[col], errors="coerce")
        xs, ys = hc.smooth_curve(t.to_numpy(), temp.to_numpy())
        ax.plot(xs, ys, "-", lw=1.8, color=color, label=label)
        ax.plot(t, temp, ".", ms=3, color=color, alpha=0.22)

    # lumped-capacitance fit on the plant sensor
    fit = lumped_fit(t.to_numpy(), pd.to_numeric(df["temp_plant"], errors="coerce").to_numpy())
    if fit:
        ax.plot(fit["t"], fit["T"], "k--", lw=1.2,
                label=f"Lumped fit: τ={fit['tau']:.0f}s, T∞={fit['Tinf']:.1f}°C")

    ax.axhline(40, color="red", ls="--", lw=1.0, label="40 °C limit")
    ax.axhline(35, color="orange", ls="--", lw=0.9, label="35 °C alert")
    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Module Temperatures vs Time", fontweight="bold")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    if not show:
        plt.close(fig)
    return fit


def fig_power(df, t, out, show):
    fig, ax1 = plt.subplots(figsize=(11, 6))
    duty = pd.to_numeric(df.get("duty"), errors="coerce")
    volt = pd.to_numeric(df.get("battery_V"), errors="coerce")
    power = pd.to_numeric(df.get("power_W"), errors="coerce")

    ax1.plot(t, duty, color="tab:orange", lw=1.4, label="Heater duty (%)")
    ax1.plot(t, power, color="tab:red", lw=1.4, label="Est. power (W)")
    ax1.set_xlabel("Elapsed time (s)")
    ax1.set_ylabel("Duty (%)  /  Power (W)")
    ax1.grid(alpha=0.3)

    ax2 = ax1.twinx()
    ax2.plot(t, volt, color="tab:green", lw=1.4, label="Battery (V)")
    ax2.set_ylabel("Battery (V)", color="tab:green")

    l1, lab1 = ax1.get_legend_handles_labels()
    l2, lab2 = ax2.get_legend_handles_labels()
    ax1.legend(l1 + l2, lab1 + lab2, loc="best", fontsize=8)
    ax1.set_title("Heater Duty, Estimated Power & Battery Voltage", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    if not show:
        plt.close(fig)


# ---------- summary table ----------

def build_summary(df, t, fit):
    rows = []
    for col, label, _ in hc.SENSORS:
        if col not in df:
            continue
        temp = pd.to_numeric(df[col], errors="coerce")
        t0 = float(temp.dropna().iloc[0]) if temp.notna().any() else float("nan")
        steady = steady_mean(t, temp)
        tmax = float(temp.max())
        rows.append({
            "Module": label,
            "T_start (°C)": round(t0, 1),
            "T_steady (°C)": round(steady, 1),
            "T_max (°C)": round(tmax, 1),
            "ΔT (°C)": round(steady - t0, 1),
            "≤40 °C": "PASS" if tmax < 40 else "FAIL",
        })
    summary = pd.DataFrame(rows)

    extras = {
        "duration_s": round(float(t.max()), 1) if len(t) else 0,
        "readings": int(len(df)),
        "plant_tau_s": round(fit["tau"], 1) if fit else None,
        "plant_Tinf_C": round(fit["Tinf"], 1) if fit else None,
        "steady_duty_pct": round(steady_mean(t, df.get("duty")), 1),
        "steady_power_W": round(steady_mean(t, df.get("power_W")), 2),
        "steady_current_A": round(steady_mean(t, df.get("current_A")), 2),
        "battery_min_V": round(float(pd.to_numeric(df.get("battery_V"), errors="coerce").min()), 2),
        "battery_max_V": round(float(pd.to_numeric(df.get("battery_V"), errors="coerce").max()), 2),
        "overall_compliance": "PASS" if (summary["≤40 °C"] == "PASS").all() else "FAIL",
    }
    return summary, extras


def df_to_md(df):
    """Markdown pipe-table without needing the optional `tabulate` package."""
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep] + body)


def write_summary(summary, extras, md_path, csv_path):
    summary.to_csv(csv_path, index=False)
    lines = ["# Experimental Results Summary", "",
             "## Per-module temperatures", "", df_to_md(summary), "",
             "## Run / control metrics", ""]
    for k, v in extras.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append(f"**Overall ≤40 °C compliance: {extras['overall_compliance']}**")
    md_path.write_text("\n".join(lines))
    print(f"Saved {md_path}")
    print(f"Saved {csv_path}")


def choose():
    sessions = [s for s in hc.scan_sessions() if s["rows"] > 0]
    if not sessions:
        sys.exit(f"No non-empty sessions in {hc.SESSIONS_DIR}. Run the logger first.")
    print(f"\nSessions in {hc.SESSIONS_DIR}:\n")
    for i, s in enumerate(sessions, 1):
        dur = f"{s['duration']:.0f}s" if s['duration'] else "—"
        print(f"  {i:>2}  {s['name']:<32} {s['rows']:>5} rows  {dur:>7}")
    raw = input("\nReport which?  number | Enter = latest : ").strip()
    if raw == "":
        return sessions[-1]["path"]
    if raw.isdigit() and 1 <= int(raw) <= len(sessions):
        return sessions[int(raw) - 1]["path"]
    sys.exit("No valid selection.")


def main():
    ap = argparse.ArgumentParser(description="Generate report figures + summary from a run CSV.")
    ap.add_argument("csv", nargs="?", help="Session CSV (omit to pick interactively)")
    ap.add_argument("--outdir", default=None, help="Output folder (default: report/ next to the CSV)")
    ap.add_argument("--no-show", action="store_true", help="Save without opening windows")
    args = ap.parse_args()

    path = Path(args.csv) if args.csv else Path(choose())
    if not path.exists():
        sys.exit(f"File not found: {path}")

    df = pd.read_csv(path)
    if df.empty or "elapsed_s" not in df:
        sys.exit(f"{path} has no usable data.")
    t = pd.to_numeric(df["elapsed_s"], errors="coerce")

    outdir = Path(args.outdir) if args.outdir else (path.parent.parent / "report")
    outdir.mkdir(exist_ok=True)
    stem = path.stem

    fit = fig_temperatures(df, t, outdir / f"{stem}_temps.png", not args.no_show)
    fig_power(df, t, outdir / f"{stem}_power.png", not args.no_show)
    summary, extras = build_summary(df, t, fit)
    write_summary(summary, extras, outdir / f"{stem}_summary.md", outdir / f"{stem}_summary.csv")

    print("\n" + summary.to_string(index=False))
    print(f"\nOverall ≤40 °C compliance: {extras['overall_compliance']}")
    if fit:
        print(f"Plant lumped-capacitance time constant τ ≈ {fit['tau']:.0f} s, "
              f"steady-state T∞ ≈ {fit['Tinf']:.1f} °C")

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()

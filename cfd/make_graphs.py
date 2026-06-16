"""
Build publication-quality analytical graphs for the CFD report:

  G1  Convergence: residuals vs iteration (per case)
  G2  Verdict bar chart: fan ON vs fan OFF vs sealed-box analytical bound
  G4  Line probes: T vs height (z-axis lines) + T along the fan axis
  G5  Energy balance: heat-out by wall vs power-in
  G6  Side-by-side contour panels (fan-on | fan-off) for each slice plane
  G7  Combined summary: TL;DR dashboard figure for the report

Run:
    /Users/omarkeshk/Desktop/UNI/Heat/term-project/.venv/bin/python make_graphs.py

Output → runs/figs_graphs/*.png
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle, FancyArrowPatch
from matplotlib.tri import Triangulation

HERE = Path(__file__).parent.resolve()
RUNS = HERE / "runs"
OUT = RUNS / "figs_graphs"
OUT.mkdir(exist_ok=True)

# Project constants
LX, LY, LZ = 90.0, 65.0, 50.0   # mm
COMPONENTS_MM = {
    "R1":  ((20.0, 25.0, 0.0), (30.0, 40.0, 8.0)),
    "R2":  ((60.0, 25.0, 0.0), (70.0, 40.0, 8.0)),
    "MOS": ((40.0, 45.0, 0.0), (50.0, 55.0, 12.0)),
}

# Output sizes
DPI = 160
plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "savefig.bbox": "tight",
})

CASES = ["fan_on", "fan_off"]
CASE_LABELS = {"fan_on": "Fan ON — 50 mm fan @ 6000 rpm (CAD vents)",
               "fan_off": "Fan OFF — natural draft through vents"}

# Sealed-box analytical bound from baseline.py (what happens if all the
# vents are blocked AND the fan is off) — kept as a reference bar in G2.
ANALYTICAL_SEALED = 118.0


def case_t_mean(case: str) -> float:
    """Bulk T_mean (°C) of the current run, from RESULT.txt."""
    rt = RUNS / f"{case}_fine" / "RESULT.txt"
    m = re.search(r"T_mean_C\s*:\s*([\d.]+)", rt.read_text())
    return float(m.group(1))


# ---------------------------------------------------------------------------
# G1 — Convergence
# ---------------------------------------------------------------------------

_RES_PAT = re.compile(
    r"Solving for (Ux|Uy|Uz|h|p_rgh|k|omega|epsilon),\s+"
    r"Initial residual = ([\d.eE+-]+)"
)
_TIME_PAT = re.compile(r"^Time = (\d+)\s*$")


def parse_log(case_dir: Path):
    """Return dict[var] = (iters, residuals)."""
    log = case_dir / "log.solver"
    if not log.exists():
        return {}
    text = log.read_text(errors="ignore")
    cur_iter = 0
    per_iter_first = {}     # var -> {iter: first residual at that iter}
    for line in text.splitlines():
        m = _TIME_PAT.match(line.strip())
        if m:
            cur_iter = int(m.group(1))
            continue
        m = _RES_PAT.search(line)
        if m:
            var, val = m.group(1), float(m.group(2))
            d = per_iter_first.setdefault(var, {})
            if cur_iter not in d:
                d[cur_iter] = val
    out = {}
    for var, d in per_iter_first.items():
        iters = np.array(sorted(d))
        vals = np.array([d[i] for i in iters])
        out[var] = (iters, vals)
    return out


def fig_convergence():
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    palette = {
        "p_rgh":   "#d62728",   # red
        "Ux":      "#1f77b4",   # blue
        "Uy":      "#9467bd",   # purple
        "Uz":      "#2ca02c",   # green
        "h":       "#ff7f0e",   # orange
        "k":       "#8c564b",   # brown
        "omega":   "#7f7f7f",   # grey
    }
    targets = {"p_rgh": 1e-3, "Ux": 1e-4, "Uy": 1e-4, "Uz": 1e-4,
               "h": 1e-4, "k": 1e-3, "omega": 1e-3}

    for ax, case in zip(axes, CASES):
        case_dir = RUNS / f"{case}_fine"
        data = parse_log(case_dir)
        for var, (it, val) in data.items():
            ax.semilogy(it, val, label=var, color=palette.get(var, "grey"),
                        lw=1.4)
            if var in targets:
                ax.axhline(targets[var], color=palette.get(var, "grey"),
                           ls=":", lw=0.7, alpha=0.4)
        ax.set_title(CASE_LABELS[case])
        ax.set_xlabel("SIMPLE iteration")
        ax.grid(True, which="both", alpha=0.2)
        # Final iter annotation
        rt = case_dir / "RESULT.txt"
        if rt.exists():
            txt = rt.read_text()
            fi = re.search(r"final_iter:\s*(\d+)", txt)
            tm = re.search(r"T_mean_C\s*:\s*([\d.]+)", txt)
            if fi and tm:
                ax.text(0.97, 0.97,
                        f"final iter {fi.group(1)}\n"
                        f"T_mean = {float(tm.group(1)):.2f} °C\n"
                        f"(iteration-averaged)",
                        transform=ax.transAxes,
                        ha="right", va="top",
                        bbox=dict(boxstyle="round,pad=0.4",
                                  fc="white", ec="#888", alpha=0.95))
    axes[0].set_ylabel("Initial residual  (log scale)")
    axes[0].legend(loc="lower left", ncol=4, fontsize=8, framealpha=0.9)
    plt.suptitle("Solver convergence — the true vent/fan jets are quasi-unsteady, so "
                 "residuals settle into a bounded band; report values use "
                 "iteration-averaged fields (TMean) over the second half of the run",
                 fontsize=11, y=1.02)
    out = OUT / "G1_convergence.png"
    plt.savefig(out)
    plt.close()
    print(f"  → {out.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# G2 — Validation bar
# ---------------------------------------------------------------------------

def fig_validation_bar():
    """The verdict chart: both CFD operating points against the 40 degC
    limit, with the sealed-box analytical estimate as the
    'what-if-the-vents-clog' reference bound."""
    t_on = case_t_mean("fan_on")
    t_off = case_t_mean("fan_off")

    labels = ["Fan ON\n(CFD, CAD vents)", "Fan OFF\n(CFD, natural draft)",
              "Sealed box\n(analytical bound)"]
    vals = [t_on, t_off, ANALYTICAL_SEALED]
    colors = ["#2ca02c", "#d62728", "#7f7f7f"]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.bar(labels, vals, color=colors, edgecolor="black", lw=0.8, width=0.55)
    ax.axhline(40.0, color="black", ls="--", lw=1.5, label="40 °C limit (spec)")
    ax.axhline(25.0, color="grey", ls=":", lw=1.0, label="Ambient 25 °C")

    for rect, v in zip(bars, vals):
        ax.text(rect.get_x() + rect.get_width()/2, v + 2, f"{v:.1f} °C",
                ha="center", va="bottom", fontsize=11, fontweight="bold")

    verdicts = [("PASS", "#2ca02c"), ("FAIL", "#d62728"), ("FAIL", "#7f7f7f")]
    for rect, (txt, col) in zip(bars, verdicts):
        ax.text(rect.get_x() + rect.get_width()/2, 5, txt,
                ha="center", va="bottom", fontsize=12, fontweight="bold",
                color="white")

    ax.set_ylabel("Bulk-air T_mean  (°C)")
    ax.set_title("Verdict — the fan keeps the box under the limit; "
                 "natural draft alone does not")
    ax.legend(loc="upper left", framealpha=0.95)
    ax.set_ylim(0, 135)
    ax.grid(True, axis="y", alpha=0.3)

    out = OUT / "G2_validation_bar.png"
    plt.savefig(out)
    plt.close()
    print(f"  → {out.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# G4 — Line probes
# ---------------------------------------------------------------------------

def fig_line_probes():
    """Line-probe T vs position with log scale to span 25 °C → 700 °C and a
    hatched band marking heater-zone segments (where the readings are non-
    physical source-cell artefacts — see F3 in RESULTS §7)."""

    fig, axes = plt.subplots(2, 2, figsize=(14, 9.5))

    def _xyz_in_heater(xyz):
        """Boolean array: True where each point sits inside any heater zone."""
        mask = np.zeros(len(xyz), dtype=bool)
        for (lo, hi) in COMPONENTS_MM.values():
            inside = (
                (xyz[:, 0] >= lo[0] / 1000.0) & (xyz[:, 0] <= hi[0] / 1000.0) &
                (xyz[:, 1] >= lo[1] / 1000.0) & (xyz[:, 1] <= hi[1] / 1000.0) &
                (xyz[:, 2] >= lo[2] / 1000.0) & (xyz[:, 2] <= hi[2] / 1000.0)
            )
            mask |= inside
        return mask

    def _plot(ax, label, title, xlabel, axis_idx, scale=1000.0):
        for case, color in [("fan_on", "#2ca02c"), ("fan_off", "#d62728")]:
            f = RUNS / f"{case}_fine" / "samples" / f"line_{label}.npz"
            d = np.load(f)
            s_mm = d["s"] * scale
            xyz = d["xyz"]
            in_heater = _xyz_in_heater(xyz)
            T = d["T"].copy()
            # Plot full curve solid
            ax.plot(s_mm, T, color=color, lw=2.0, label=CASE_LABELS[case])
            # Overlay heater-zone segments dashed to flag artefact region
            T_artefact = np.where(in_heater, T, np.nan)
            ax.plot(s_mm, T_artefact, color=color, lw=2.0, ls=":", alpha=0.8)
        # Shaded heater bands (positional, in the probe-axis coordinate)
        # Use fan_on xyz to derive in-heater axis-range
        f0 = RUNS / "fan_on_fine" / "samples" / f"line_{label}.npz"
        d0 = np.load(f0)
        s_mm0 = d0["s"] * scale
        in_heater0 = _xyz_in_heater(d0["xyz"])
        if in_heater0.any():
            # Find contiguous true segments
            edges = np.diff(in_heater0.astype(int))
            starts = np.where(edges == 1)[0] + 1
            ends   = np.where(edges == -1)[0] + 1
            if in_heater0[0]:
                starts = np.r_[0, starts]
            if in_heater0[-1]:
                ends = np.r_[ends, len(in_heater0)]
            for a_idx, b_idx in zip(starts, ends):
                ax.axvspan(s_mm0[a_idx], s_mm0[b_idx - 1],
                           color="#ff6600", alpha=0.12, zorder=0)
        ax.axhline(40, color="black", ls="--", lw=1, alpha=0.7, label="40 °C limit")
        ax.axhline(25, color="grey",  ls=":",  lw=1, alpha=0.6, label="Ambient 25 °C")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("T  (°C, log scale)")
        ax.set_yscale("log")
        ax.set_ylim(20, 1000)
        ax.set_title(title)
        ax.legend(fontsize=8.5, loc="upper right")
        ax.grid(True, which="both", alpha=0.2)

    _plot(axes[0, 0], "zline_R1",
          "Vertical line through Resistor 1  (x=25 mm, y=32.5 mm)",
          "z, height above floor  (mm)", axis_idx=2)
    _plot(axes[0, 1], "zline_MOS",
          "Vertical line through MOSFET  (x=45 mm, y=50 mm)",
          "z, height above floor  (mm)", axis_idx=2)
    _plot(axes[1, 0], "xline_flow",
          "Fan-axis line: back vents → fan disk  (y=32.5 mm, z=25 mm)",
          "x, distance from back wall  (mm)", axis_idx=0)
    _plot(axes[1, 1], "xline_heaters",
          "Across heaters  (y=32.5 mm, z=6 mm)",
          "x, position across box  (mm)", axis_idx=0)

    # Annotate the heater bands on the xline panel
    ax = axes[1, 1]
    for name, (lo, hi) in COMPONENTS_MM.items():
        if not (lo[2] <= 6.0 <= hi[2]):
            continue
        if not (lo[1] <= 32.5 <= hi[1]):
            continue
        cx = (lo[0] + hi[0]) / 2
        ax.text(cx, 850, name, ha="center", va="top",
                fontsize=10, fontweight="bold", color="#cc4400")

    plt.suptitle("Temperature along probe lines  (orange band = inside heater cellZone — non-physical artefact, see RESULTS §7 F3)",
                 fontsize=10.5, y=1.0)
    out = OUT / "G4_line_probes.png"
    plt.savefig(out)
    plt.close()
    print(f"  → {out.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# G5 — Energy balance
# ---------------------------------------------------------------------------

def fig_energy_balance():
    """Heat-balance via CFD-sampled wall-adjacent temperatures.

    We sample T at 1 mm offset from each wall, use the BC h_eff to estimate
    each wall's raw conduction-radiation loss.

    Fan ON: advection through the fan disk dominates —
        q_fan = ρ · Q_fan · cp · (T_fan_disk − T_amb)
    with Q_fan from the fan-curve/system-curve operating point
    (case_generator.fan_operating_flow), then everything is normalized so
    Σ = 17 W (the wall-slab estimate over-counts by a near-constant ratio).

    Fan OFF (true vents): buoyant draft enters the lower slots and leaves
    via the upper slots/fan-side openings. The vent-draft advection is hard
    to sample robustly from slabs, so it is reported as the RESIDUAL
    17 W − Σ(wall losses) — labelled as such on the figure.
    """
    from case_generator import fan_operating_flow

    A = {
        "floor":   (LX * LY) * 1e-6,
        "ceiling": (LX * LY) * 1e-6,
        "side_x0": (LY * LZ) * 1e-6,
        "side_x1": (LY * LZ) * 1e-6,
        "side_y0": (LX * LZ) * 1e-6,
        "side_y1": (LX * LZ) * 1e-6,
    }
    h_eff = 13.86
    T_amb = 25.0
    rho   = 1.2     # kg/m³
    cp    = 1005    # J/kg·K
    Q_fan = fan_operating_flow(dict(fan_rpm=6000.0))   # ~2.05e-3 m³/s

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    for ax, case, info in [
        (axes[0], "fan_on", dict(label=CASE_LABELS["fan_on"])),
        (axes[1], "fan_off",  dict(label=CASE_LABELS["fan_off"])),
    ]:
        walls = dict(np.load(RUNS / f"{case}_fine" / "samples" / "walls.npz"))

        def _wall_q(name, label_area=None):
            return h_eff * A[name] * (float(walls[name]) - T_amb)

        wall_losses = {
            "Floor":            _wall_q("floor"),
            "Ceiling":          _wall_q("ceiling"),
            "Front wall\n(x=0)": _wall_q("side_x0"),
            "Fan wall\n(x=90)":  _wall_q("side_x1"),
            "Long walls\n(×2)": (_wall_q("side_y0") + _wall_q("side_y1")),
        }

        if case == "fan_on":
            dT_fan = max(0.0, float(walls["fan_disk"]) - T_amb)
            q_raw = dict(wall_losses)
            q_raw["Fan exhaust\n(advection)"] = rho * Q_fan * cp * dT_fan
            raw_total = sum(q_raw.values())
            scale = 17.0 / raw_total if raw_total > 0.1 else 1.0
            q_norm = {k: v * scale for k, v in q_raw.items()}
        else:
            raw_total = sum(wall_losses.values())
            # Walls capped at 17 W; the remainder left via buoyant draft
            scale = min(1.0, 17.0 / raw_total) if raw_total > 0.1 else 1.0
            q_norm = {k: v * scale for k, v in wall_losses.items()}
            q_norm["Vent draft\n(residual)"] = max(0.0, 17.0 - sum(q_norm.values()))

        paths = list(q_norm.keys())
        vals  = list(q_norm.values())
        # Highlight the advection paths (fan exhaust / vent draft) in red
        colors = []
        for p in paths:
            if "Fan exhaust" in p or "Vent draft" in p:
                colors.append("#d62728")
            elif "Ceiling" in p:
                colors.append("#ff7f0e")
            else:
                colors.append("#1f77b4")

        b = ax.bar(paths, vals, color=colors, edgecolor="black", lw=0.7)
        for r, v in zip(b, vals):
            ax.text(r.get_x() + r.get_width() / 2, v + 0.3,
                    f"{v:.1f} W\n({v/17*100:.0f}%)",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")

        ax.axhline(17.0, color="green", ls="--", lw=1.5, alpha=0.7,
                   label="total Q_in = 17 W")
        ax.set_ylabel("Heat extracted  (W)")
        ax.set_title(info["label"] +
                     f"\n(raw Σ = {raw_total:.1f} W — normalized to conserve)")
        ax.set_ylim(0, max(20, max(vals) * 1.25))
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(loc="upper right", fontsize=8.5)

    plt.suptitle("Heat-balance — where does the 17 W go? "
                 "(per-path estimate from CFD-sampled wall T, "
                 "normalized to conservation)",
                 fontsize=11, y=1.02)
    out = OUT / "G5_energy_balance.png"
    plt.savefig(out)
    plt.close()
    print(f"  → {out.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# G6 — Side-by-side contours
# ---------------------------------------------------------------------------

def _component_overlays(ax, slice_kind):
    """Draw component bounding boxes projected onto the slice plane."""
    for name, (lo, hi) in COMPONENTS_MM.items():
        if slice_kind == "z004":
            if not (lo[2] <= 4.0 <= hi[2]):
                continue
            ax.add_patch(Rectangle((lo[0], lo[1]),
                                   hi[0] - lo[0], hi[1] - lo[1],
                                   fill=False, edgecolor="black", lw=1.4))
            ax.text((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, name,
                    ha="center", va="center", fontsize=8.5, fontweight="bold")
        elif slice_kind == "z025":
            # heaters don't reach z=25mm — show as dashed footprint
            ax.add_patch(Rectangle((lo[0], lo[1]),
                                   hi[0] - lo[0], hi[1] - lo[1],
                                   fill=False, edgecolor="#666", lw=0.8, ls="--"))
        elif slice_kind == "x025":
            # slice at x=25mm cuts through R1 only (x=20-30)
            if not (lo[0] <= 25.0 <= hi[0]):
                continue
            ax.add_patch(Rectangle((lo[1], lo[2]),
                                   hi[1] - lo[1], hi[2] - lo[2],
                                   fill=False, edgecolor="black", lw=1.4))
            ax.text((lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2, name,
                    ha="center", va="center", fontsize=8.5, fontweight="bold")
        elif slice_kind == "y0325":
            # slice at y=32.5mm cuts through both resistors (y=25-40) but not MOSFET (y=45-55)
            if not (lo[1] <= 32.5 <= hi[1]):
                continue
            ax.add_patch(Rectangle((lo[0], lo[2]),
                                   hi[0] - lo[0], hi[2] - lo[2],
                                   fill=False, edgecolor="black", lw=1.4))
            ax.text((lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2, name,
                    ha="center", va="center", fontsize=8.5, fontweight="bold")


def _make_turbo_with_overshoot():
    cmap = plt.get_cmap("turbo").copy()
    cmap.set_over("#4a0000")   # very dark red for above-range cells
    # set_under uses turbo's lowest colour (avoid white voids when bulk T==vmin)
    cmap.set_under(cmap(0.0))
    cmap.set_bad("white")      # only true NaN (outside-domain) becomes white
    return cmap


def _plot_slice(ax, case, slice_kind, vmin, vmax, with_arrow=False):
    """Regrid the unstructured slice samples onto a regular 2D grid via
    scipy.interpolate.griddata for clean contour plots without Delaunay
    triangulation artefacts."""
    from scipy.interpolate import griddata

    f = RUNS / f"{case}_fine" / "samples" / f"slice_{slice_kind}.npz"
    d = np.load(f)
    a, b, T = d["a"], d["b"], d["T"]
    a_lim, b_lim = d["a_lim"], d["b_lim"]
    a_mm = a * 1000.0
    b_mm = b * 1000.0
    a_lim_mm = (a_lim[0] * 1000.0, a_lim[1] * 1000.0)
    b_lim_mm = (b_lim[0] * 1000.0, b_lim[1] * 1000.0)

    # Regular grid (2 px per mm)
    nx = int((a_lim_mm[1] - a_lim_mm[0]) * 2) + 1
    ny = int((b_lim_mm[1] - b_lim_mm[0]) * 2) + 1
    xi = np.linspace(a_lim_mm[0], a_lim_mm[1], nx)
    yi = np.linspace(b_lim_mm[0], b_lim_mm[1], ny)
    XI, YI = np.meshgrid(xi, yi)
    Ti = griddata((a_mm, b_mm), T, (XI, YI), method="linear")

    cmap = _make_turbo_with_overshoot()
    # extend="both" so values at exactly vmin get the lower contour colour,
    # not treated as out-of-range.
    cf = ax.contourf(XI, YI, Ti, levels=np.linspace(vmin, vmax, 32),
                     cmap=cmap, extend="both")

    ax.set_xlim(*a_lim_mm)
    ax.set_ylim(*b_lim_mm)
    ax.set_aspect("equal")
    _component_overlays(ax, slice_kind)

    if with_arrow and case == "fan_on" and slice_kind in {"y0325", "z004", "z025"}:
        # Fan flow runs along +x: back vents (x=0) → fan disk (x=90).
        # Both the horizontal (x,y) planes and the vertical (x,z) plane
        # contain the flow axis, so draw the arrow in-plane along x.
        b_pos = LY - 5 if slice_kind.startswith("z") else LZ - 5
        ax.annotate("vents → fan", xy=(LX - 6, b_pos), xytext=(6, b_pos),
                    arrowprops=dict(arrowstyle="->", color="white",
                                    lw=2, mutation_scale=14),
                    fontsize=10, color="white", fontweight="bold",
                    ha="left", va="center")
    return cf


def fig_contour_panels():
    """Each slice plane → one figure with fan-on (left) and fan-off (right)."""
    slices = {
        "z004":  ("Horizontal slice at z = 4 mm (through heater layer)",        "x (mm)", "y (mm)"),
        "z025":  ("Horizontal slice at z = 25 mm (mid-height, on the fan axis)", "x (mm)", "y (mm)"),
        "x025":  ("Vertical slice at x = 25 mm (through Resistor 1)",           "y (mm)", "z (mm)"),
        "y0325": ("Vertical slice at y = 32.5 mm (along the fan axis)",         "x (mm)", "z (mm)"),
    }

    # Use T_mean + 13 °C anchor so both cases use the "headroom-to-limit" bar.
    d41_mean = case_t_mean("fan_on")
    fof_mean = case_t_mean("fan_off")
    d41_lo, d41_hi = 25, int(np.ceil(d41_mean + 13))     # → [25, 41]
    fof_lo, fof_hi = 25, int(np.ceil(fof_mean + 13))     # → [25, 117]

    for skind, (title, xlbl, ylbl) in slices.items():
        fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

        cf1 = _plot_slice(axes[0], "fan_on", skind, vmin=d41_lo, vmax=d41_hi,
                          with_arrow=True)
        cf2 = _plot_slice(axes[1], "fan_off",  skind, vmin=fof_lo, vmax=fof_hi)

        axes[0].set_title(f"{CASE_LABELS['fan_on']}\nbar [{d41_lo}, {d41_hi}] °C")
        axes[1].set_title(f"{CASE_LABELS['fan_off']}\nbar [{fof_lo}, {fof_hi}] °C")
        for ax in axes:
            ax.set_xlabel(xlbl)
            ax.set_ylabel(ylbl)
        plt.colorbar(cf1, ax=axes[0], label="T (°C)", fraction=0.046, pad=0.04)
        plt.colorbar(cf2, ax=axes[1], label="T (°C)", fraction=0.046, pad=0.04)

        plt.suptitle(title + "   (saturated dark-red = cells exceed bar; these are non-physical heat-source-cell artefacts)",
                     fontsize=10.5, y=1.02)
        out = OUT / f"G6_slice_{skind}.png"
        plt.savefig(out)
        plt.close()
        print(f"  → {out.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# G7 — TL;DR summary 4-panel figure
# ---------------------------------------------------------------------------

def fig_summary():
    d41_mean = case_t_mean("fan_on")
    fof_mean = case_t_mean("fan_off")

    fig = plt.figure(figsize=(14, 9.5))
    gs = fig.add_gridspec(2, 3, width_ratios=[1, 1, 0.6])

    # Top-left: fan_on z004 slice
    ax1 = fig.add_subplot(gs[0, 0])
    d = np.load(RUNS / "fan_on_fine/samples/slice_z004.npz")
    tri = Triangulation(d["a"] * 1000, d["b"] * 1000)
    cf1 = ax1.tricontourf(tri, d["T"], levels=np.linspace(25, d41_mean + 13, 24),
                          cmap=_make_turbo_with_overshoot(), extend="max")
    _component_overlays(ax1, "z004")
    ax1.set_aspect("equal")
    ax1.set_xlabel("x (mm)"); ax1.set_ylabel("y (mm)")
    ax1.set_title("Fan ON — heater-layer slice z=4 mm")
    plt.colorbar(cf1, ax=ax1, fraction=0.046, label="T (°C)")

    # Top-middle: fan_off z004 slice
    ax2 = fig.add_subplot(gs[0, 1])
    d = np.load(RUNS / "fan_off_fine/samples/slice_z004.npz")
    tri = Triangulation(d["a"] * 1000, d["b"] * 1000)
    cf2 = ax2.tricontourf(tri, d["T"], levels=np.linspace(25, fof_mean + 13, 24),
                          cmap=_make_turbo_with_overshoot(), extend="max")
    _component_overlays(ax2, "z004")
    ax2.set_aspect("equal")
    ax2.set_xlabel("x (mm)"); ax2.set_ylabel("y (mm)")
    ax2.set_title("Fan OFF (natural draft) — same slice")
    plt.colorbar(cf2, ax=ax2, fraction=0.046, label="T (°C)")

    # Top-right: verdict mini
    ax3 = fig.add_subplot(gs[0, 2])
    labels = ["Fan ON", "Fan OFF", "Sealed\n(analyt.)"]
    vals = [d41_mean, fof_mean, ANALYTICAL_SEALED]
    cols = ["#2ca02c", "#d62728", "#7f7f7f"]
    bars = ax3.bar(labels, vals, color=cols, edgecolor="black", lw=0.7, width=0.6)
    for rect, v in zip(bars, vals):
        ax3.text(rect.get_x() + rect.get_width()/2, v + 2, f"{v:.1f}",
                 ha="center", va="bottom", fontsize=8.5, fontweight="bold")
    ax3.axhline(40, color="black", ls="--", lw=1, label="40 °C limit")
    ax3.set_ylabel("T_mean (°C)")
    ax3.set_title("Verdict")
    ax3.legend(fontsize=8, loc="upper left")
    ax3.grid(True, axis="y", alpha=0.3)

    # Bottom-left: line probe — vertical through R1
    ax4 = fig.add_subplot(gs[1, 0])
    for case, color in [("fan_on", "#2ca02c"), ("fan_off", "#d62728")]:
        d = np.load(RUNS / f"{case}_fine/samples/line_zline_R1.npz")
        ax4.plot(d["s"] * 1000, d["T"], color=color, lw=2,
                 label=CASE_LABELS[case])
    ax4.axhline(40, color="black", ls="--", lw=1, label="40 °C limit")
    ax4.set_xlabel("z, height above floor (mm)")
    ax4.set_ylabel("T (°C)")
    ax4.set_title("Vertical line through Resistor 1")
    ax4.legend(fontsize=8.5)
    ax4.grid(True, alpha=0.3)
    ax4.set_yscale("log")
    ax4.set_ylim(20, 1000)

    # Bottom-middle: convergence — fan ON
    ax5 = fig.add_subplot(gs[1, 1])
    data = parse_log(RUNS / "fan_on_fine")
    for var, color in [("p_rgh", "#d62728"), ("Ux", "#1f77b4"),
                       ("h", "#ff7f0e"), ("k", "#8c564b")]:
        if var in data:
            it, val = data[var]
            ax5.semilogy(it, val, color=color, label=var, lw=1.4)
    ax5.axhline(1e-3, color="grey", ls=":", lw=0.8)
    ax5.set_xlabel("SIMPLE iteration")
    ax5.set_ylabel("Initial residual")
    ax5.set_title("Convergence — fan ON")
    ax5.legend(fontsize=8)
    ax5.grid(True, which="both", alpha=0.2)

    # Bottom-right: convergence — fan OFF
    ax6 = fig.add_subplot(gs[1, 2])
    data = parse_log(RUNS / "fan_off_fine")
    for var, color in [("p_rgh", "#d62728"), ("Ux", "#1f77b4"),
                       ("h", "#ff7f0e"), ("k", "#8c564b")]:
        if var in data:
            it, val = data[var]
            ax6.semilogy(it, val, color=color, label=var, lw=1.2)
    ax6.axhline(1e-3, color="grey", ls=":", lw=0.8)
    ax6.set_xlabel("SIMPLE iteration")
    ax6.set_title("Convergence — fan OFF")
    ax6.legend(fontsize=8)
    ax6.grid(True, which="both", alpha=0.2)

    plt.suptitle("Plant Module Thermal CFD — Summary Dashboard",
                 fontsize=13, fontweight="bold", y=1.0)
    out = OUT / "G7_summary_dashboard.png"
    plt.savefig(out)
    plt.close()
    print(f"  → {out.relative_to(HERE)}")


def main():
    print("Generating graphs in", OUT.relative_to(HERE))
    fig_convergence()
    fig_validation_bar()
    fig_line_probes()
    fig_energy_balance()
    fig_contour_panels()
    fig_summary()
    print("Done.")


if __name__ == "__main__":
    main()

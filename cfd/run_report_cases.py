"""
Generate + run the two report-quality CFD cases — geometry straight from the CAD:

  1. fan_on_fine   — 50 mm 5 V fan @ 6000 rpm exhausting through the 45 mm
                     opening; air enters through 3x 50x5 mm front slots +
                     3x 40x5 mm side slots (PLA walls, 2.5 mm)
  2. fan_off_fine  — same enclosure, fan stopped (blocked opening), vents
                     open: buoyancy-driven natural draft through the slots

Fine mesh: 110 x 80 x 60 = 528,000 cells.  10-25 min per case on M4 Max (8 cores).

Cases are written under term-project/cfd/atmospheric/runs/<name>/ and KEPT on disk
so ParaView can open them afterwards.

Usage:
    python run_report_cases.py            # both cases
    python run_report_cases.py fan_on     # only fan-on
    python run_report_cases.py fan_off    # only fan-off
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from runner import run_cfd

HERE = Path(__file__).parent.resolve()
RUNS_DIR = HERE / "runs"


# Mesh sized for ~500k cells; one cell ≈ 0.83 mm in every direction
FINE_MESH = dict(mesh_nx=110, mesh_ny=80, mesh_nz=60)

# Everything below comes from the as-built CAD: PLA 3D-printed module,
# 2.5 mm walls, 17 W total dissipation, ambient 25 C, fan at rated 6000 rpm.
# true_vents=True uses the actual CAD openings (45 mm fan disk + 6 intake
# slots) — geometry constants live in case_generator.py
# (FAN_CENTER_M / FAN_RADIUS_M / FRONT_SLOTS_M / SIDE_SLOTS_M).
BASE_PARAMS = dict(
    true_vents        = True,
    wall_thickness_mm = 2.5,
    wall_k            = 0.20,    # PLA (matches WALL_MATERIALS[0] in case_generator)
    wall_material     = 0,       # PLA — used by _wall_emissivity → ε=0.90
    ambient_C         = 25.0,
    heat_total_W      = 17.0,
    fin_count         = 0,
    fin_height_mm     = 0,
    hs_fin_count      = 0,
    hs_fin_height_mm  = 0,
    end_iter          = 4000,
    write_interval    = 4000,    # final snapshot only (keeps disk small)
    n_procs           = 8,
    **FINE_MESH,
)


CASES = {
    # Fan-on: forced convection.
    "fan_on": dict(BASE_PARAMS, fan_rpm=6000.0),
    # Fan-off: natural draft through the open vent slots (fan opening blocked
    # by the stopped blades). Buoyancy-driven SIMPLE struggles unless we
    # tighten pressure/velocity relaxation. Need more iterations too.
    "fan_off":  dict(BASE_PARAMS,
                     fan_rpm=0.0,
                     end_iter=8000,
                     write_interval=8000,
                     tight_relaxation=True),
}


def run_one(name: str) -> dict:
    case_dir = RUNS_DIR / f"{name}_fine"
    print(f"\n=== {name}  →  {case_dir} ===")
    t0 = time.perf_counter()
    metrics = run_cfd(CASES[name], case_dir=case_dir, keep=True, parallel=True)
    dt = time.perf_counter() - t0
    print(f"  T_min  = {metrics['T_min_C']:6.2f} C")
    print(f"  T_mean = {metrics['T_mean_C']:6.2f} C")
    print(f"  T_max  = {metrics['T_max_C']:6.2f} C")
    print(f"  cells  = {metrics['n_cells']:,}")
    print(f"  wall   = {dt/60:.1f} min")
    # Drop a .foam handle so ParaView can open the case by double-click
    (case_dir / "case.foam").touch()
    # Write a small per-case summary
    (case_dir / "RESULT.txt").write_text(
        f"name      : {name}\n"
        f"fan_rpm   : {CASES[name]['fan_rpm']}\n"
        f"cells     : {metrics['n_cells']}\n"
        f"T_min_C   : {metrics['T_min_C']:.3f}\n"
        f"T_mean_C  : {metrics['T_mean_C']:.3f}\n"
        f"T_max_C   : {metrics['T_max_C']:.3f}\n"
        f"final_iter: {metrics['final_time']:.0f}\n"
        f"solve_s   : {metrics['solve_time_s']:.1f}\n"
        f"total_s   : {metrics['total_time_s']:.1f}\n"
    )
    return metrics


def main() -> int:
    RUNS_DIR.mkdir(exist_ok=True)
    requested = sys.argv[1:] or list(CASES.keys())
    bad = [c for c in requested if c not in CASES]
    if bad:
        print(f"Unknown case(s): {bad}; valid = {list(CASES)}")
        return 2

    summary = {}
    for name in requested:
        summary[name] = run_one(name)

    print("\n=== SUMMARY ===")
    print(f"{'case':<14s} {'T_mean':>8s} {'T_max':>8s} {'cells':>10s} {'time':>8s}")
    print("-" * 56)
    for name, m in summary.items():
        print(f"{name:<14s} {m['T_mean_C']:>7.2f}C {m['T_max_C']:>7.2f}C "
              f"{m['n_cells']:>10,d} {m['solve_time_s']/60:>6.1f}min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

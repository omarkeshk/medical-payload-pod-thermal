"""
End-to-end CFD wrapper: design vector -> OpenFOAM case -> T_max.

This is the bridge between the optimization layer (BO) and OpenFOAM. Given
a parameter dict, it:
  1. Generates a complete OpenFOAM case via case_generator.generate_case
  2. Runs blockMesh + decomposePar + buoyantSimpleFoam + reconstructPar
  3. Parses the final temperature field
  4. Returns a metrics dict {T_max, T_mean, T_min, wall_time, n_cells, ...}

All OpenFOAM commands run inside `openfoam2512 -c "..."` so the env is loaded.
Cases are written under /tmp/openfoam_runs/<run_id>/ by default.

Usage:
    from runner import run_cfd
    result = run_cfd(dict(
        wall_thickness_mm=2.5, wall_k=0.20, ambient_C=25.0,
        heat_total_W=17.0, mesh_nx=36, mesh_ny=26, mesh_nz=20,
    ))
    print(result["T_max"], result["wall_time"])
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from case_generator import generate_case


DEFAULT_RUN_ROOT = Path("/tmp/openfoam_runs")


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

def _of_run(case_dir: Path, command: str, log_name: str) -> int:
    """Run an OpenFOAM command inside the case dir, log to log_name."""
    log_path = case_dir / log_name
    full = f"cd {case_dir} && {command} > {log_name} 2>&1"
    return subprocess.call(["openfoam2512", "-c", full])


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

_NONUNIFORM_HEADER = re.compile(r"internalField\s+nonuniform\s+List<scalar>")
_FLOAT_LINE = re.compile(r"^\s*-?\d+(\.\d+)?([eE][+-]?\d+)?\s*$")


def _parse_scalar_field(field_path: Path) -> list[float]:
    """Parse OpenFOAM nonuniform scalar field; return list of cell values."""
    text = field_path.read_text()
    m = _NONUNIFORM_HEADER.search(text)
    if not m:
        # uniform field -- try to extract single value
        u = re.search(r"internalField\s+uniform\s+([-\d.eE+]+)", text)
        if u:
            return [float(u.group(1))]
        raise ValueError(f"Cannot parse scalar field at {field_path}")
    # After header: <count>\n(\nval\nval\n...)\n;
    body = text[m.end():]
    open_paren = body.find("(")
    close_paren = body.find(")", open_paren)
    inside = body[open_paren + 1:close_paren]
    return [float(s) for s in inside.split() if s.strip()]


def _final_time_dir(case_dir: Path) -> Path:
    """Find the highest-numbered time directory in the case."""
    times = []
    for p in case_dir.iterdir():
        if p.is_dir():
            try:
                times.append((float(p.name), p))
            except ValueError:
                continue
    if not times:
        raise RuntimeError(f"No time directories found in {case_dir}")
    return max(times)[1]


def parse_T(case_dir: Path) -> dict:
    """Return min/max/mean T (K and degC) from the final time step.

    Prefers the iteration-averaged TMean (written by the fieldAverage
    function object in true_vents cases) over the instantaneous T — the
    vent/fan jets oscillate, so the averaged field is the robust steady
    estimate.
    """
    final = _final_time_dir(case_dir)
    T_path = final / "TMean"
    if not T_path.exists():
        T_path = final / "T"
    if not T_path.exists():
        raise RuntimeError(f"No T field at {T_path}")
    values = _parse_scalar_field(T_path)
    if not values:
        raise RuntimeError(f"Empty T field at {T_path}")
    T_min, T_max = min(values), max(values)
    T_mean = sum(values) / len(values)
    return {
        "T_min_K":   T_min,
        "T_max_K":   T_max,
        "T_mean_K":  T_mean,
        "T_min_C":   T_min - 273.15,
        "T_max_C":   T_max - 273.15,
        "T_mean_C":  T_mean - 273.15,
        "n_cells":   len(values),
        "final_time": float(final.name),
    }


# ---------------------------------------------------------------------------
# Top-level: run + parse
# ---------------------------------------------------------------------------

def run_cfd(params: dict, case_dir: str | Path | None = None,
            keep: bool = False, parallel: bool = True) -> dict:
    """
    Generate + run + parse one CFD case. Returns metrics dict.

    Parameters
    ----------
    params : dict
        Same keys as case_generator.generate_case.
    case_dir : optional path
        Where to put the case. Defaults to /tmp/openfoam_runs/<uuid>/
    keep : bool
        If True, leave the case on disk after parsing. If False, delete.
    parallel : bool
        If True, run with `mpirun -np N` decomposition (faster).
    """
    if case_dir is None:
        case_dir = DEFAULT_RUN_ROOT / uuid.uuid4().hex[:8]
    case_dir = Path(case_dir).expanduser().resolve()
    if case_dir.exists():
        shutil.rmtree(case_dir)

    t_total = time.perf_counter()

    # 1) Templating
    generate_case(params, case_dir)

    # 2) blockMesh + topoSet (cellZones for component heat sources, plus
    #    boundary faceSets for the fan/vent openings in true_vents mode)
    rc = _of_run(case_dir, "blockMesh", "log.blockMesh")
    if rc != 0:
        raise RuntimeError(f"blockMesh failed (rc={rc}); see {case_dir}/log.blockMesh")
    rc = _of_run(case_dir, "topoSet", "log.topoSet")
    if rc != 0:
        raise RuntimeError(f"topoSet failed (rc={rc}); see {case_dir}/log.topoSet")
    if params.get("true_vents"):
        rc = _of_run(case_dir, "createPatch -overwrite", "log.createPatch")
        if rc != 0:
            raise RuntimeError(
                f"createPatch failed (rc={rc}); see {case_dir}/log.createPatch")

    # Fields are templated into 0.orig; install them as 0/ only now, so
    # their boundary entries match the post-createPatch patch list.
    shutil.copytree(case_dir / "0.orig", case_dir / "0", dirs_exist_ok=True)

    # 3) Solve
    if parallel:
        n = params.get("n_procs", 8)
        rc = _of_run(case_dir, "decomposePar -force", "log.decompose")
        if rc != 0:
            raise RuntimeError(f"decomposePar failed (rc={rc})")
        t_solve = time.perf_counter()
        rc = _of_run(case_dir,
                     f"mpirun -np {n} buoyantSimpleFoam -parallel",
                     "log.solver")
        solve_time = time.perf_counter() - t_solve
        if rc != 0:
            raise RuntimeError(f"solver failed (rc={rc}); see {case_dir}/log.solver")
        rc = _of_run(case_dir, "reconstructPar -latestTime", "log.reconstruct")
        if rc != 0:
            raise RuntimeError(f"reconstructPar failed (rc={rc})")
    else:
        t_solve = time.perf_counter()
        rc = _of_run(case_dir, "buoyantSimpleFoam", "log.solver")
        solve_time = time.perf_counter() - t_solve
        if rc != 0:
            raise RuntimeError(f"solver failed (rc={rc})")

    # 4) Parse
    metrics = parse_T(case_dir)
    metrics["solve_time_s"] = solve_time
    metrics["total_time_s"] = time.perf_counter() - t_total
    metrics["case_dir"] = str(case_dir)

    # 5) Optional cleanup
    if not keep:
        shutil.rmtree(case_dir, ignore_errors=True)
        metrics["case_dir"] = None

    return metrics


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    base = dict(
        wall_thickness_mm=2.5, wall_k=0.20, ambient_C=25.0, heat_total_W=17.0,
        mesh_nx=36, mesh_ny=26, mesh_nz=20,
        end_iter=2000, write_interval=2000, n_procs=8,
    )

    cases = [
        ("Fan only 4000 rpm",                          {**base, "fan_rpm": 4000}),
        ("Fan + 10 fins x 20mm",                       {**base, "fan_rpm": 4000, "fin_count": 10, "fin_height_mm": 20}),
        ("Fan + external HS (R=0.5)",                  {**base, "fan_rpm": 4000, "hs_R_external": 0.5}),
        ("Fan + restricted vent (1000 mm2)",           {**base, "fan_rpm": 4000, "vent_area_mm2": 1000}),
        ("No fan, just external HS R=0.5",             {**base, "fan_rpm": 0,    "hs_R_external": 0.5}),
        ("No fan, big fins 15x25mm",                   {**base, "fan_rpm": 0,    "fin_count": 15, "fin_height_mm": 25}),
    ]

    print(f"{'Case':<35s} {'T_max':>8s} {'T_mean':>8s} {'time':>7s}")
    print("-" * 65)
    for name, p in cases:
        try:
            r = run_cfd(p, parallel=True)
            print(f"{name:<35s} {r['T_max_C']:>7.1f}C {r['T_mean_C']:>7.1f}C "
                  f"{r['solve_time_s']:>6.1f}s")
        except Exception as e:
            print(f"{name:<35s} FAIL: {e}")

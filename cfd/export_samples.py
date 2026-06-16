"""
Sample OpenFOAM field data and export to NPZ for matplotlib plotting.

Run with pvbatch (NOT plain python):
    pvbatch export_samples.py            # both cases
    pvbatch export_samples.py fan_on   # one case

Output per case:
    runs/<case>_fine/samples/slice_z004.npz   - horizontal slice z=4mm
    runs/<case>_fine/samples/slice_z025.npz   - horizontal slice z=25mm (mid, fan axis)
    runs/<case>_fine/samples/slice_x025.npz   - vertical slice x=25mm
    runs/<case>_fine/samples/slice_y0325.npz  - vertical slice y=32.5mm (along fan axis)
    runs/<case>_fine/samples/line_*.npz       - probe lines (see process_case)
    runs/<case>_fine/samples/walls.npz        - wall-adjacent T per wall + fan-disk T

True-vents geometry: flow runs along X (back slots at x=0 + side slots at
y=65 in, 38mm fan disk at x=90 out). Fields: uses the iteration-averaged
TMean/UMean when the run wrote them (fieldAverage), else instantaneous T/U.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from paraview.simple import (  # type: ignore
    OpenFOAMReader, Calculator, Slice, ResampleToImage,
    PlotOverLine, GetAnimationScene,
)
from paraview import servermanager as _sm
import paraview.simple as pvs  # type: ignore


HERE = Path(__file__).parent.resolve()
RUNS_DIR = HERE / "runs"
LX, LY, LZ = 0.090, 0.065, 0.050


def _has_mean_fields(case_dir: Path) -> bool:
    """True if the run's final time directory contains fieldAverage output."""
    times = [d for d in case_dir.iterdir()
             if d.is_dir() and re.fullmatch(r"\d+(\.\d+)?", d.name)]
    if not times:
        return False
    latest = max(times, key=lambda d: float(d.name))
    return (latest / "TMean").exists()


def load_case(case_dir: Path):
    foam = case_dir / "case.foam"
    if not foam.exists():
        foam.touch()
    use_mean = _has_mean_fields(case_dir)
    t_name = "TMean" if use_mean else "T"
    u_name = "UMean" if use_mean else "U"
    reader = OpenFOAMReader(registrationName=case_dir.name, FileName=str(foam))
    reader.MeshRegions = ["internalMesh"]
    reader.CellArrays = ["T", "U", "p"] + (["TMean", "UMean"] if use_mean else [])
    reader.UpdatePipelineInformation()
    times = reader.TimestepValues
    if not times:
        raise RuntimeError(f"No time steps in {case_dir}")
    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.GoToLast()
    reader.UpdatePipeline(time=times[-1])
    calc = Calculator(registrationName="TtoC", Input=reader)
    calc.AttributeType = "Cell Data"
    calc.ResultArrayName = "T_C"
    calc.Function = f"{t_name} - 273.15"
    calc.UpdatePipeline()
    # Scalar |U| so downstream samplers don't care which vector we used
    calc2 = Calculator(registrationName="Umag", Input=calc)
    calc2.AttributeType = "Cell Data"
    calc2.ResultArrayName = "Umag"
    calc2.Function = f"mag({u_name})"
    calc2.UpdatePipeline()
    print(f"  fields: {t_name}/{u_name}" +
          ("  (iteration-averaged)" if use_mean else "  (instantaneous)"))
    return reader, calc2


def fetch_flat(source, array_name, kind="cells"):
    """Return a 1D numpy array of values from a (possibly multi-block) source."""
    data = _sm.Fetch(source)

    def _walk(d):
        if hasattr(d, "GetNumberOfBlocks"):
            for i in range(d.GetNumberOfBlocks()):
                child = d.GetBlock(i)
                if child is not None:
                    yield from _walk(child)
        else:
            field = d.GetCellData() if kind == "cells" else d.GetPointData()
            if field is None:
                return
            arr = field.GetArray(array_name)
            if arr is None:
                return
            n = arr.GetNumberOfTuples()
            comps = arr.GetNumberOfComponents()
            if comps == 1:
                yield np.array([arr.GetValue(j) for j in range(n)])
            else:
                # vector — return magnitude
                out = np.zeros(n)
                for j in range(n):
                    v = arr.GetTuple(comps * 0 + 0)  # not used
                    t = [arr.GetComponent(j, c) for c in range(comps)]
                    out[j] = (sum(c * c for c in t)) ** 0.5
                yield out

    chunks = list(_walk(data))
    return np.concatenate(chunks) if chunks else np.array([])


def cell_centers(source):
    from vtkmodules.vtkFiltersCore import vtkCellCenters
    data = _sm.Fetch(source)

    def _walk(d):
        if hasattr(d, "GetNumberOfBlocks"):
            for i in range(d.GetNumberOfBlocks()):
                child = d.GetBlock(i)
                if child is not None:
                    yield from _walk(child)
        else:
            cc = vtkCellCenters()
            cc.SetInputData(d)
            cc.Update()
            pts = cc.GetOutput().GetPoints()
            if pts is None:
                return
            n = pts.GetNumberOfPoints()
            yield np.array([pts.GetPoint(j) for j in range(n)])

    chunks = list(_walk(data))
    return np.concatenate(chunks) if chunks else np.zeros((0, 3))


def resample_plane(calc, origin, normal, dim_axes, n_a, n_b, samples_dir, label):
    """Sample a plane via Slice filter and export unstructured triangulation
    (cell centers + values). Matplotlib's tricontourf interpolates accurately
    onto a regular grid for plotting."""
    from vtkmodules.vtkFiltersCore import vtkCellCenters
    sl = Slice(registrationName=f"sl_{label}", Input=calc)
    sl.SliceType = "Plane"
    sl.SliceType.Origin = origin
    sl.SliceType.Normal = normal
    sl.UpdatePipeline()

    data = _sm.Fetch(sl)

    def _walk(d):
        if hasattr(d, "GetNumberOfBlocks"):
            for i in range(d.GetNumberOfBlocks()):
                child = d.GetBlock(i)
                if child is not None:
                    yield from _walk(child)
        else:
            yield d

    centers, tvals, umags = [], [], []
    for block in _walk(data):
        if block is None or block.GetNumberOfCells() == 0:
            continue
        cc = vtkCellCenters()
        cc.SetInputData(block)
        cc.Update()
        pts = cc.GetOutput().GetPoints()
        cd = block.GetCellData()
        if pts is None or cd is None:
            continue
        t_arr = cd.GetArray("T_C")
        u_arr = cd.GetArray("Umag")
        n = pts.GetNumberOfPoints()
        centers.append(np.array([pts.GetPoint(j) for j in range(n)]))
        tvals.append(np.array([t_arr.GetValue(j) for j in range(n)]))
        if u_arr is not None:
            umags.append(np.array([u_arr.GetValue(j) for j in range(n)]))
        else:
            umags.append(np.zeros(n))

    xyz = np.concatenate(centers)
    T = np.concatenate(tvals)
    Umag = np.concatenate(umags)

    # Choose 2 in-plane coordinates
    if normal == [0, 0, 1]:
        a, b = xyz[:, 0], xyz[:, 1]   # x, y
        a_lim, b_lim = (0.0, LX), (0.0, LY)
        a_name, b_name = "x", "y"
    elif normal == [1, 0, 0]:
        a, b = xyz[:, 1], xyz[:, 2]   # y, z
        a_lim, b_lim = (0.0, LY), (0.0, LZ)
        a_name, b_name = "y", "z"
    else:  # y normal
        a, b = xyz[:, 0], xyz[:, 2]   # x, z
        a_lim, b_lim = (0.0, LX), (0.0, LZ)
        a_name, b_name = "x", "z"

    out = samples_dir / f"slice_{label}.npz"
    np.savez(out, a=a, b=b, T=T, Umag=Umag,
             a_name=a_name, b_name=b_name,
             a_lim=a_lim, b_lim=b_lim,
             normal=normal, origin=origin)
    print(f"  → {out.relative_to(HERE)}  n={len(T)}  T∈[{T.min():.1f}, {T.max():.1f}]")
    pvs.Delete(sl)


def line_probe(calc, p1, p2, n, samples_dir, label):
    pol = PlotOverLine(registrationName=f"line_{label}", Input=calc)
    pol.Point1 = list(p1)
    pol.Point2 = list(p2)
    pol.Resolution = n - 1
    pol.UpdatePipeline()
    data = _sm.Fetch(pol)
    pd = data.GetPointData()
    t_arr = pd.GetArray("T_C")
    u_arr = pd.GetArray("Umag")
    pts = data.GetPoints()
    nn = t_arr.GetNumberOfTuples()
    xyz = np.array([pts.GetPoint(j) for j in range(nn)])
    T = np.array([t_arr.GetValue(j) for j in range(nn)])
    Umag = (np.array([u_arr.GetValue(j) for j in range(nn)])
            if u_arr is not None else np.zeros(nn))
    s = np.linalg.norm(xyz - xyz[0], axis=1)
    out = samples_dir / f"line_{label}.npz"
    np.savez(out, s=s, xyz=xyz, T=T, Umag=Umag, p1=list(p1), p2=list(p2))
    print(f"  → {out.relative_to(HERE)}  n={nn}  T∈[{T.min():.1f}, {T.max():.1f}]")
    pvs.Delete(pol)


def process_case(case_name: str):
    case_dir = RUNS_DIR / f"{case_name}_fine"
    if not case_dir.exists():
        print(f"SKIP {case_name}: {case_dir} not found")
        return
    samples_dir = case_dir / "samples"
    samples_dir.mkdir(exist_ok=True)
    print(f"\n=== {case_name}  →  {samples_dir.relative_to(HERE)} ===")
    reader, calc = load_case(case_dir)

    # Slice planes (resample to a regular grid for matplotlib contourf)
    resample_plane(calc, origin=[LX/2, LY/2, 0.004], normal=[0, 0, 1],
                   dim_axes="xy", n_a=180, n_b=130,
                   samples_dir=samples_dir, label="z004")
    resample_plane(calc, origin=[LX/2, LY/2, LZ/2], normal=[0, 0, 1],
                   dim_axes="xy", n_a=180, n_b=130,
                   samples_dir=samples_dir, label="z025")
    resample_plane(calc, origin=[0.025, LY/2, LZ/2], normal=[1, 0, 0],
                   dim_axes="yz", n_a=130, n_b=100,
                   samples_dir=samples_dir, label="x025")
    resample_plane(calc, origin=[LX/2, LY/2, LZ/2], normal=[0, 1, 0],
                   dim_axes="xz", n_a=180, n_b=100,
                   samples_dir=samples_dir, label="y0325")

    # Line probes
    # 1) Vertical line at (x=25, y=32.5): scans z through resistor1
    line_probe(calc, (0.025, 0.0325, 0.0), (0.025, 0.0325, LZ),
               n=200, samples_dir=samples_dir, label="zline_R1")
    # 2) Vertical line at (x=45, y=50): MOSFET column
    line_probe(calc, (0.045, 0.050, 0.0), (0.045, 0.050, LZ),
               n=200, samples_dir=samples_dir, label="zline_MOS")
    # 3) Fan-axis line along x at (y=32.5, z=25): back vents → fan disk
    line_probe(calc, (0.0, 0.0325, 0.025), (LX, 0.0325, 0.025),
               n=200, samples_dir=samples_dir, label="xline_flow")
    # 4) Horizontal line along x at (y=32.5, z=6mm): across the resistors
    line_probe(calc, (0.0, 0.0325, 0.006), (LX, 0.0325, 0.006),
               n=200, samples_dir=samples_dir, label="xline_heaters")

    # Bulk stats
    T_all = fetch_flat(calc, "T_C")
    xyz = cell_centers(calc)
    np.savez(samples_dir / "bulk.npz", T=T_all, xyz=xyz)
    print(f"  → bulk.npz  n_cells={len(T_all)}  T_mean={T_all.mean():.2f}  "
          f"T_min={T_all.min():.2f}  T_max={T_all.max():.2f}")

    # Wall patch temperatures — average T_C on each external face
    # Use a thin slab near each wall (1 mm offset) and average T_C there as a
    # proxy for the wall-adjacent gas temperature, which is what the
    # externalWallHeatFluxTemperature BC uses with the prescribed h_eff.
    wall_offset_m = 0.001
    wall_planes = {
        "floor":   ([LX / 2, LY / 2, wall_offset_m],         [0, 0, 1]),
        "ceiling": ([LX / 2, LY / 2, LZ - wall_offset_m],    [0, 0, 1]),
        "side_x0": ([wall_offset_m, LY / 2, LZ / 2],         [1, 0, 0]),
        "side_x1": ([LX - wall_offset_m, LY / 2, LZ / 2],    [1, 0, 0]),
        "side_y0": ([LX / 2, wall_offset_m, LZ / 2],         [0, 1, 0]),
        "side_y1": ([LX / 2, LY - wall_offset_m, LZ / 2],    [0, 1, 0]),
    }
    wall_T = {}
    for wname, (org, nrm) in wall_planes.items():
        sl = Slice(registrationName=f"wall_{wname}", Input=calc)
        sl.SliceType = "Plane"
        sl.SliceType.Origin = org
        sl.SliceType.Normal = nrm
        sl.UpdatePipeline()
        T_arr = fetch_flat(sl, "T_C")
        wall_T[wname] = float(T_arr.mean()) if T_arr.size else float("nan")
        pvs.Delete(sl)

    # Fan-disk exhaust temperature: average T over cells within the 38 mm
    # opening radius on the x = LX-1mm plane — the advected-heat estimate
    # in the energy balance uses this (q = rho*Q_fan*cp*(T_fan - T_amb)).
    from vtkmodules.vtkFiltersCore import vtkCellCenters
    sl = Slice(registrationName="fan_plane", Input=calc)
    sl.SliceType = "Plane"
    sl.SliceType.Origin = [LX - wall_offset_m, LY / 2, LZ / 2]
    sl.SliceType.Normal = [1, 0, 0]
    sl.UpdatePipeline()
    data = _sm.Fetch(sl)

    def _walk_blocks(d):
        if hasattr(d, "GetNumberOfBlocks"):
            for i in range(d.GetNumberOfBlocks()):
                child = d.GetBlock(i)
                if child is not None:
                    yield from _walk_blocks(child)
        else:
            yield d

    fan_vals = []
    for block in _walk_blocks(data):
        if block is None or block.GetNumberOfCells() == 0:
            continue
        cc = vtkCellCenters(); cc.SetInputData(block); cc.Update()
        pts = cc.GetOutput().GetPoints()
        t_arr = block.GetCellData().GetArray("T_C")
        if pts is None or t_arr is None:
            continue
        for j in range(pts.GetNumberOfPoints()):
            _, py, pz = pts.GetPoint(j)
            if ((py - 0.0325) ** 2 + (pz - 0.025) ** 2) ** 0.5 <= 0.019:
                fan_vals.append(t_arr.GetValue(j))
    wall_T["fan_disk"] = float(np.mean(fan_vals)) if fan_vals else float("nan")
    pvs.Delete(sl)

    np.savez(samples_dir / "walls.npz", **wall_T)
    print(f"  → walls.npz  T_wall_adj ≈ " +
          ", ".join(f"{k}={v:.1f}" for k, v in wall_T.items()))


def main():
    targets = sys.argv[1:] or ["fan_on", "fan_off"]
    for name in targets:
        process_case(name)


if __name__ == "__main__":
    main()

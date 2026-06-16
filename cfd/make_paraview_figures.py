"""
Generate report-quality figures for one or both CFD cases using pvbatch.

Usage:
    pvbatch make_paraview_figures.py                  # both cases
    pvbatch make_paraview_figures.py fan_on
    pvbatch make_paraview_figures.py fan_off

Output goes into <case_dir>/figs/  (PNG, 1600x1200 by default).

Figures produced per case:
    01_T_horizontal_midplane.png   slice z = 25 mm, coloured by T (°C)
    02_T_vertical_midplane.png     slice x = 45 mm, coloured by T (°C)
    03_T_vertical_alt.png          slice y = 32.5 mm (perpendicular to fan axis)
    04_U_magnitude_vertical.png    slice x = 45 mm, coloured by |U|
    05_U_vectors_vertical.png      glyph arrows on x = 45 mm slice
    06_streamlines_T.png           streamlines from inlet, coloured by T
    07_iso_T35.png                 isosurface T = 35 °C (yellow) over outline
    08_iso_T30.png                 isosurface T = 30 °C (cyan) over outline
    09_surface_T_walls.png         exterior wall surface coloured by T
    10_components_zoom.png         zoomed view of MOSFET + resistor zones
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# pvbatch import — fails if run with plain python
from paraview.simple import (  # type: ignore
    OpenFOAMReader, Calculator, Slice, Contour, StreamTracer,
    Glyph, Show, Hide, ColorBy, GetActiveViewOrCreate, GetActiveSource,
    GetColorTransferFunction, GetOpacityTransferFunction, GetScalarBar,
    SaveScreenshot, ResetCamera, Render, UpdatePipeline,
    ExtractSurface, FeatureEdges, Outline, ResampleToImage,
    Threshold, Delete, AnnotateTime, GetAnimationScene,
)
import paraview.simple as pvs  # type: ignore


HERE = Path(__file__).parent.resolve()
RUNS_DIR = HERE / "runs"

LX, LY, LZ = 0.090, 0.065, 0.050   # m

# Component zones (from case_generator.write_topoSetDict)
COMPONENTS = {
    "resistor1": ((0.020, 0.025, 0.000), (0.030, 0.040, 0.008)),
    "resistor2": ((0.060, 0.025, 0.000), (0.070, 0.040, 0.008)),
    "mosfet":    ((0.040, 0.045, 0.000), (0.050, 0.055, 0.012)),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_mean_fields(case_dir: Path) -> bool:
    import re as _re
    times = [d for d in case_dir.iterdir()
             if d.is_dir() and _re.fullmatch(r"\d+(\.\d+)?", d.name)]
    if not times:
        return False
    latest = max(times, key=lambda d: float(d.name))
    return (latest / "TMean").exists()


def load_case(case_dir: Path):
    """Open the OpenFOAM case, go to last time step, add T_C calculator.

    Prefers the iteration-averaged TMean/UMean fields when present."""
    foam = case_dir / "case.foam"
    if not foam.exists():
        foam.touch()

    use_mean = _has_mean_fields(case_dir)
    t_name = "TMean" if use_mean else "T"
    reader = OpenFOAMReader(registrationName=case_dir.name, FileName=str(foam))
    reader.MeshRegions = ["internalMesh"]
    reader.CellArrays = (["T", "U", "p", "p_rgh"]
                         + (["TMean", "UMean"] if use_mean else []))
    reader.UpdatePipelineInformation()

    # jump to last timestep
    times = reader.TimestepValues
    if not times:
        raise RuntimeError(f"No time steps in {case_dir}")
    scene = GetAnimationScene()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.GoToLast()
    reader.UpdatePipeline(time=times[-1])

    # T_C = T - 273.15
    calc = Calculator(registrationName="TtoC", Input=reader)
    calc.AttributeType = "Cell Data"
    calc.ResultArrayName = "T_C"
    calc.Function = f"{t_name} - 273.15"
    calc.UpdatePipeline()

    return reader, calc


def setup_view(width: int = 1600, height: int = 1200):
    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [width, height]
    view.OrientationAxesVisibility = 1
    view.Background = [1.0, 1.0, 1.0]   # white background
    view.UseColorPaletteForBackground = 0
    return view


def hide_all():
    src = GetActiveSource()
    for s in pvs.GetSources().values():
        Hide(s, GetActiveViewOrCreate("RenderView"))


def colourbar(view, lookup, title: str):
    bar = GetScalarBar(lookup, view)
    bar.Title = title
    bar.ComponentTitle = ""
    bar.TitleColor = [0, 0, 0]
    bar.LabelColor = [0, 0, 0]
    bar.Orientation = "Horizontal"
    bar.WindowLocation = "Lower Center"
    bar.ScalarBarLength = 0.5


def save(view, out_path: Path):
    out_path.parent.mkdir(exist_ok=True)
    Render(view)
    SaveScreenshot(str(out_path), view, ImageResolution=view.ViewSize,
                   TransparentBackground=0)
    print(f"  → {out_path.relative_to(HERE)}")


def show_outline(source, view):
    o = Outline(Input=source)
    d = Show(o, view)
    d.AmbientColor = [0.2, 0.2, 0.2]
    d.DiffuseColor = [0.2, 0.2, 0.2]
    d.LineWidth = 1.5
    return o, d


def show_component_outlines(view, source):
    """Draw thin boxes where the heater components sit. Returns the box
    proxies so the caller can Delete() them after saving."""
    _FIG_COUNTER[0] += 1
    tag = _FIG_COUNTER[0]
    boxes = []
    for name, (lo, hi) in COMPONENTS.items():
        box = pvs.Box(registrationName=f"box{tag}_{name}")
        box.XLength = hi[0] - lo[0]
        box.YLength = hi[1] - lo[1]
        box.ZLength = hi[2] - lo[2]
        box.Center = [(lo[0] + hi[0]) / 2.0,
                      (lo[1] + hi[1]) / 2.0,
                      (lo[2] + hi[2]) / 2.0]
        d = Show(box, view)
        d.Representation = "Wireframe"
        d.AmbientColor = [0.0, 0.0, 0.0]
        d.DiffuseColor = [0.0, 0.0, 0.0]
        d.LineWidth = 2.0
        boxes.append(box)
    return boxes


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _orient_camera_normal(view, normal, center):
    """Position the camera looking down `normal`, parallel projection, so a
    slice perpendicular to `normal` fills the frame."""
    far = 0.5
    nx, ny, nz = normal
    cx, cy, cz = center
    view.CameraPosition   = [cx + far * nx, cy + far * ny, cz + far * nz]
    view.CameraFocalPoint = [cx, cy, cz]
    if abs(nz) < 0.5:
        view.CameraViewUp = [0, 0, 1]    # Z up for X- or Y-normal slices
    else:
        view.CameraViewUp = [0, 1, 0]    # Y up for top-down (Z-normal) view
    view.CameraParallelProjection = 1
    # ResetCamera preserves direction; it refits parallel scale to data.
    ResetCamera(view)


_FIG_COUNTER = [0]


def fig_slice(view, calc, normal, origin, array, title, out_path,
              vector=False, vmin=None, vmax=None):
    hide_all()
    _FIG_COUNTER[0] += 1
    tag = _FIG_COUNTER[0]
    sl = Slice(registrationName=f"slice{tag}_{array}", Input=calc)
    sl.SliceType = "Plane"
    sl.SliceType.Origin = origin
    sl.SliceType.Normal = normal
    sl.UpdatePipeline()

    d = Show(sl, view)
    if vector:
        ColorBy(d, ("CELLS", array, "Magnitude"))
    else:
        ColorBy(d, ("CELLS", array))
    d.SetScalarBarVisibility(view, True)

    lut = GetColorTransferFunction(array)
    lut.ApplyPreset("Cool to Warm", True)
    if vmin is not None and vmax is not None:
        lut.RescaleTransferFunction(vmin, vmax)
    colourbar(view, lut, title)

    outline_src, outline_disp = show_outline(calc, view)
    boxes = show_component_outlines(view, calc)
    _orient_camera_normal(view, normal, origin)
    save(view, out_path)

    # Clean up so state doesn't accumulate between figures
    Delete(sl)
    Delete(outline_src)
    for b in boxes:
        Delete(b)


def fig_streamlines(view, calc, out_path, vmin=None, vmax=None):
    hide_all()
    # Seed line at the heater layer (z = 6 mm), spanning x. This guarantees
    # streamlines start right above the heat sources for both fan-on (where
    # the fan sweeps these traces toward the outlet) and fan-off (where
    # buoyant plumes lift them upward).
    st = StreamTracer(registrationName="streams", Input=calc, SeedType="Line")
    st.Vectors = ["CELLS", "U"]
    st.SeedType.Point1 = [0.010, LY / 2.0, 0.006]
    st.SeedType.Point2 = [0.080, LY / 2.0, 0.006]
    st.SeedType.Resolution = 80
    st.MaximumStreamlineLength = 0.4
    st.IntegrationDirection = "BOTH"
    st.UpdatePipeline()

    tube = pvs.Tube(registrationName="tubes", Input=st)
    tube.Radius = 0.0005
    tube.UpdatePipeline()

    d = Show(tube, view)
    ColorBy(d, ("POINTS", "T_C"))
    d.SetScalarBarVisibility(view, True)
    lut = GetColorTransferFunction("T_C")
    lut.ApplyPreset("Cool to Warm", True)
    if vmin is not None and vmax is not None:
        lut.RescaleTransferFunction(vmin, vmax)
    colourbar(view, lut, "T (°C)")

    show_outline(calc, view)
    show_component_outlines(view, calc)
    ResetCamera(view)
    cam = view.GetActiveCamera()
    cam.Azimuth(30)
    cam.Elevation(20)
    Render(view)
    save(view, out_path)


def fig_isosurface(view, calc, iso_value, colour_rgb, out_path):
    hide_all()
    iso = Contour(registrationName=f"iso_T{iso_value:.0f}", Input=calc)
    iso.ContourBy = ["CELLS", "T_C"]
    iso.Isosurfaces = [iso_value]
    iso.UpdatePipeline()

    d = Show(iso, view)
    d.Representation = "Surface"
    d.AmbientColor = colour_rgb
    d.DiffuseColor = colour_rgb
    d.Opacity = 0.65

    show_outline(calc, view)
    show_component_outlines(view, calc)
    ResetCamera(view)
    cam = view.GetActiveCamera()
    cam.Azimuth(35)
    cam.Elevation(22)
    Render(view)
    save(view, out_path)


def fig_components_zoom(view, calc, out_path, vmin=None, vmax=None):
    """Slice through components horizontally, zoom on the heater zone."""
    hide_all()
    sl = Slice(registrationName="slice_comp", Input=calc)
    sl.SliceType = "Plane"
    sl.SliceType.Origin = [LX / 2.0, LY / 2.0, 0.004]   # 4 mm above floor
    sl.SliceType.Normal = [0, 0, 1]
    sl.UpdatePipeline()

    d = Show(sl, view)
    ColorBy(d, ("CELLS", "T_C"))
    d.SetScalarBarVisibility(view, True)
    lut = GetColorTransferFunction("T_C")
    lut.ApplyPreset("Black-Body Radiation", True)
    if vmin is not None and vmax is not None:
        lut.RescaleTransferFunction(vmin, vmax)
    colourbar(view, lut, "T (°C) — 4 mm above floor")

    show_component_outlines(view, calc)
    ResetCamera(view)
    # zoom factor
    cam = view.GetActiveCamera()
    cam.Dolly(1.4)
    Render(view)
    save(view, out_path)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def process_case(case_name: str):
    case_dir = RUNS_DIR / f"{case_name}_fine"
    if not case_dir.exists():
        print(f"SKIP {case_name}: {case_dir} not found")
        return

    out_dir = case_dir / "figs"
    out_dir.mkdir(exist_ok=True)
    print(f"\n=== {case_name}  →  {out_dir.relative_to(HERE)} ===")

    reader, calc = load_case(case_dir)
    view = setup_view()

    # Percentile-based colour range so a few hot-source cells don't blow out
    # the bulk variation. OpenFOAM readers return MultiBlockDataSet, so we
    # MergeBlocks first then fetch the resulting unstructured grid.
    import numpy as np
    from paraview import servermanager as _sm
    merged = pvs.MergeBlocks(registrationName="merged_for_stats", Input=calc)
    merged.UpdatePipeline()
    data = _sm.Fetch(merged)

    def _all_cell_data(d, name):
        """Yield numpy array of `name` from every leaf block of d."""
        if hasattr(d, "GetNumberOfBlocks"):
            for i in range(d.GetNumberOfBlocks()):
                child = d.GetBlock(i)
                if child is not None:
                    yield from _all_cell_data(child, name)
        else:
            cd = d.GetCellData()
            if cd is not None:
                arr = cd.GetArray(name)
                if arr is not None:
                    yield np.array(
                        [arr.GetValue(j) for j in range(arr.GetNumberOfValues())]
                    )

    # Spatially mask out the heater cellZones so the colour bar reflects the
    # bulk AIR temperature, not the (non-physical) source-cell overshoot.
    def _all_cells_with_centers(d):
        if hasattr(d, "GetNumberOfBlocks"):
            for i in range(d.GetNumberOfBlocks()):
                child = d.GetBlock(i)
                if child is not None:
                    yield from _all_cells_with_centers(child)
        else:
            from vtkmodules.vtkFiltersCore import vtkCellCenters
            cc = vtkCellCenters()
            cc.SetInputData(d)
            cc.Update()
            centers = cc.GetOutput().GetPoints()
            t_arr = d.GetCellData().GetArray("T_C")
            if t_arr is None or centers is None:
                return
            n = t_arr.GetNumberOfValues()
            xyz = np.array(
                [centers.GetPoint(j) for j in range(n)]
            )
            t_vals = np.array(
                [t_arr.GetValue(j) for j in range(n)]
            )
            yield xyz, t_vals

    pieces = list(_all_cells_with_centers(data))
    if pieces:
        xyz = np.vstack([p[0] for p in pieces])
        tvals = np.concatenate([p[1] for p in pieces])
    else:
        xyz = np.zeros((0, 3))
        tvals = np.array([25.0, 30.0])

    raw_lo, raw_hi = float(tvals.min()), float(tvals.max())
    # Read T_mean from RESULT.txt (computed by run_report_cases.py) — this is
    # the physically meaningful number. Cells inside the heater bounding boxes
    # are non-physical (heat is dumped into AIR, not a solid body), so we set
    # the colour bar to bracket the BULK air temperature around T_mean, and
    # let hot-source cells saturate at the upper bound.
    result_txt = (case_dir / "RESULT.txt").read_text() if (case_dir / "RESULT.txt").exists() else ""
    t_mean = None
    for line in result_txt.splitlines():
        if line.startswith("T_mean_C"):
            t_mean = float(line.split(":")[1].strip())
            break
    if t_mean is None:
        t_mean = float(np.median(tvals))
    # 25 °C (ambient) on the cool side; T_mean + 13 °C (the 40 °C safety
    # limit margin) on the hot side, with a min span of 15 °C.
    t_lo = 25
    t_hi = max(40, int(np.ceil(t_mean + 13)))
    print(f"  T raw (incl heaters):  {raw_lo:.2f} .. {raw_hi:.2f} °C")
    print(f"  T_mean (from RESULT):  {t_mean:.2f} °C")
    print(f"  T colour bar (locked): {t_lo} .. {t_hi} °C")
    Delete(merged)

    def _try(label, fn, *args, **kw):
        try:
            fn(*args, **kw)
        except Exception as exc:
            print(f"  {label} FAILED: {exc!r}")

    # 01 — Horizontal slice through the heater layer (z = 4 mm)
    _try("01_heater_layer", fig_slice, view, calc,
         normal=[0, 0, 1], origin=[LX / 2, LY / 2, 0.004],
         array="T_C", title="T (°C) — z = 4 mm (through heaters)",
         out_path=out_dir / "01_T_heater_layer.png",
         vmin=t_lo, vmax=t_hi)

    # 01b — Horizontal mid-plane (z = LZ/2) — shows fan-mixed bulk
    _try("01b_midplane", fig_slice, view, calc,
         normal=[0, 0, 1], origin=[LX / 2, LY / 2, LZ / 2],
         array="T_C", title="T (°C) — z = 25 mm (mid-height)",
         out_path=out_dir / "01b_T_midheight.png",
         vmin=t_lo, vmax=t_hi)

    # 02 — Vertical slice through resistor1 (x = 25 mm)
    _try("02_vertical_R1", fig_slice, view, calc,
         normal=[1, 0, 0], origin=[0.025, LY / 2, LZ / 2],
         array="T_C", title="T (°C) — x = 25 mm (through resistor 1)",
         out_path=out_dir / "02_T_vertical_through_R1.png",
         vmin=t_lo, vmax=t_hi)

    # 03 — Vertical slice along fan flow direction (y = 32.5 mm cuts both R)
    _try("03_vertical_fanline", fig_slice, view, calc,
         normal=[0, 1, 0], origin=[LX / 2, LY / 2, LZ / 2],
         array="T_C", title="T (°C) — y = 32.5 mm (through resistors)",
         out_path=out_dir / "03_T_vertical_fanline.png",
         vmin=t_lo, vmax=t_hi)

    # 04 — |U| through resistor1 (same plane as fig 02 to show flow)
    _try("04_U_mag_R1", fig_slice, view, calc,
         normal=[1, 0, 0], origin=[0.025, LY / 2, LZ / 2],
         array="U", title="|U| (m/s) — x = 25 mm",
         vector=True,
         out_path=out_dir / "04_U_magnitude_vertical.png")

    # 04b — |U| along fan flow (y mid-plane)
    _try("04b_U_mag_fanline", fig_slice, view, calc,
         normal=[0, 1, 0], origin=[LX / 2, LY / 2, LZ / 2],
         array="U", title="|U| (m/s) — y = 32.5 mm",
         vector=True,
         out_path=out_dir / "04b_U_magnitude_fanline.png")

    # 06 — Streamlines coloured by T
    _try("06_streams", fig_streamlines, view, calc,
         out_path=out_dir / "06_streamlines_T.png",
         vmin=t_lo, vmax=t_hi)

    # 07 / 08 — Isosurfaces (only meaningful if max bulk T exceeds threshold)
    if t_hi >= 36:
        _try("07_iso_T35", fig_isosurface, view, calc,
             iso_value=35.0,
             colour_rgb=[1.0, 0.78, 0.0],
             out_path=out_dir / "07_iso_T35.png")
    if t_hi >= 31:
        _try("08_iso_T30", fig_isosurface, view, calc,
             iso_value=30.0,
             colour_rgb=[0.2, 0.7, 0.9],
             out_path=out_dir / "08_iso_T30.png")

    # 10 — Component-level horizontal slice 4mm above floor
    _try("10_components", fig_components_zoom, view, calc,
         out_path=out_dir / "10_components_zoom.png",
         vmin=t_lo, vmax=t_hi)


def main() -> int:
    targets = sys.argv[1:] or ["fan_on", "fan_off"]
    for name in targets:
        process_case(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

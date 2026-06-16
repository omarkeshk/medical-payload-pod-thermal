"""
Hero-quality 3D ParaView renders for the report.

For each case (design41, fan_off) produces 5 screenshots at 2400x1800,
anti-aliased, white background:
  H1_streamlines_iso.png     — streamlines coloured by T, ISO view
  H2_streamlines_top.png     — streamlines from top-down (xy plane)
  H3_streamlines_side.png    — streamlines side-on (xz plane through fan flow)
  H4_isosurface_cutaway.png  — isosurfaces 30/35/40 °C + cutaway slice
  H5_streams_over_slice.png  — vertical T slice + 3D streamlines combined

Run:
    /Applications/ParaView-6.1.0.app/Contents/bin/pvbatch make_hero_shots.py
    /Applications/ParaView-6.1.0.app/Contents/bin/pvbatch make_hero_shots.py fan_on
    /Applications/ParaView-6.1.0.app/Contents/bin/pvbatch make_hero_shots.py fan_off

Output → runs/<case>_fine/figs_hero/
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from paraview.simple import (  # type: ignore
    OpenFOAMReader, Calculator, Slice, Contour, StreamTracer, Tube,
    Show, Hide, ColorBy, GetActiveViewOrCreate, GetActiveSource,
    GetColorTransferFunction, GetOpacityTransferFunction, GetScalarBar,
    SaveScreenshot, ResetCamera, Render, UpdatePipeline,
    ExtractSurface, Outline, GetAnimationScene, Delete,
    CellDatatoPointData,
)
import paraview.simple as pvs  # type: ignore


HERE = Path(__file__).parent.resolve()
RUNS = HERE / "runs"

LX, LY, LZ = 0.090, 0.065, 0.050

COMPONENTS = {
    "resistor1": ((0.020, 0.025, 0.000), (0.030, 0.040, 0.008)),
    "resistor2": ((0.060, 0.025, 0.000), (0.070, 0.040, 0.008)),
    "mosfet":    ((0.040, 0.045, 0.000), (0.050, 0.055, 0.012)),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_mean_fields(case_dir: Path) -> bool:
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
    GetAnimationScene().GoToLast()
    reader.UpdatePipeline(time=times[-1])
    calc = Calculator(registrationName="TtoC", Input=reader)
    calc.AttributeType = "Cell Data"
    calc.ResultArrayName = "T_C"
    calc.Function = f"{t_name} - 273.15"
    calc.UpdatePipeline()
    # Convert cell data → point data so StreamTracer can interpolate T_C
    # along streamlines (CFD outputs cell-centred values; streamlines are
    # poly-line geometry with point data).
    c2p = CellDatatoPointData(registrationName="cell2point", Input=calc)
    c2p.UpdatePipeline()
    print(f"  fields: {t_name}/{u_name}" +
          ("  (iteration-averaged)" if use_mean else "  (instantaneous)"))
    return reader, c2p, u_name


def reset_view(width=2400, height=1800):
    # Clean slate — destroy any existing source so successive cases don't bleed state
    for s in list(pvs.GetSources().values()):
        pvs.Delete(s)
    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [width, height]
    # ParaView 6 background: force "Single Color" with white
    try:
        view.BackgroundColorMode = "Single Color"
    except Exception:
        pass
    view.Background = [1.0, 1.0, 1.0]
    view.UseColorPaletteForBackground = 0
    view.OrientationAxesVisibility = 1
    return view


def add_box_outline(calc, view):
    o = Outline(Input=calc)
    d = Show(o, view)
    d.AmbientColor = [0.25, 0.25, 0.25]
    d.DiffuseColor = [0.25, 0.25, 0.25]
    d.LineWidth = 2.0
    return o


def add_component_boxes(view, opacity=0.55, color=(0.9, 0.35, 0.25)):
    handles = []
    for name, (lo, hi) in COMPONENTS.items():
        box = pvs.Box(registrationName=f"hero_box_{name}")
        box.XLength = hi[0] - lo[0]
        box.YLength = hi[1] - lo[1]
        box.ZLength = hi[2] - lo[2]
        box.Center = [(lo[0] + hi[0]) / 2.0,
                      (lo[1] + hi[1]) / 2.0,
                      (lo[2] + hi[2]) / 2.0]
        d = Show(box, view)
        d.Representation = "Surface"
        d.AmbientColor = color
        d.DiffuseColor = color
        d.Opacity = opacity
        d.Specular = 0.4
        handles.append(box)
    return handles


def set_camera(view, pos, focal, up):
    view.CameraParallelProjection = 0
    ResetCamera(view)   # fit data into the view, then override the angles
    view.CameraPosition = pos
    view.CameraFocalPoint = focal
    view.CameraViewUp = up
    Render(view)


def colour_streamlines_by_T(tube_disp, view, vmin, vmax):
    ColorBy(tube_disp, ("POINTS", "T_C"))
    lut = GetColorTransferFunction("T_C")
    lut.ApplyPreset("Turbo", True)
    lut.RescaleTransferFunction(vmin, vmax)
    bar = GetScalarBar(lut, view)
    bar.Title = "T (°C)"
    bar.ComponentTitle = ""
    bar.TitleColor = [0, 0, 0]
    bar.LabelColor = [0, 0, 0]
    bar.Orientation = "Horizontal"
    bar.WindowLocation = "Lower Center"
    bar.ScalarBarLength = 0.5
    bar.TitleFontSize = 32
    bar.LabelFontSize = 26
    bar.ScalarBarThickness = 30
    tube_disp.SetScalarBarVisibility(view, True)


def colour_streamlines_by_Umag(tube_disp, view, vmax, u_name="U"):
    """Colour by velocity magnitude — useful when T is uniform (fan-on)."""
    ColorBy(tube_disp, ("POINTS", u_name, "Magnitude"))
    lut = GetColorTransferFunction(u_name)
    lut.ApplyPreset("Turbo", True)
    lut.RescaleTransferFunction(0.0, vmax)
    bar = GetScalarBar(lut, view)
    bar.Title = "|U|  (m/s)"
    bar.ComponentTitle = ""
    bar.TitleColor = [0, 0, 0]
    bar.LabelColor = [0, 0, 0]
    bar.Orientation = "Horizontal"
    bar.WindowLocation = "Lower Center"
    bar.ScalarBarLength = 0.5
    bar.TitleFontSize = 32
    bar.LabelFontSize = 26
    bar.ScalarBarThickness = 30
    tube_disp.SetScalarBarVisibility(view, True)


def save(view, out: Path):
    out.parent.mkdir(exist_ok=True, parents=True)
    Render(view)
    SaveScreenshot(str(out), view, ImageResolution=view.ViewSize,
                   TransparentBackground=0)
    print(f"  → {out.relative_to(HERE)}")


# ---------------------------------------------------------------------------
# Hero shots
# ---------------------------------------------------------------------------

def hero_streamlines(calc, view, vmin, vmax, out_dir: Path, label_prefix: str,
                     seed_mode: str = "sphere",
                     colour_by: str = "T",
                     u_name: str = "U"):
    """Three streamline shots: iso, top, side.

    seed_mode:
        sphere   — 3D point cloud centred on the heater layer (good for
                   buoyancy-driven flow, where streamlines curl upward).
        vents    — point cloud near the back intake slots (x ≈ 0) so the
                   forward-integrated streamlines show the intake jets
                   sweeping across the heaters into the fan disk at x=90.
    """
    add_box_outline(calc, view)
    boxes = add_component_boxes(view)

    if seed_mode == "vents":
        # Seeds over the back-vent wall (x ≈ 0); forward integration carries
        # them across the box to the fan. The side-slot intake (y=65) shows
        # up naturally where those jets join the main stream.
        st = StreamTracer(registrationName="hero_streams", Input=calc,
                          SeedType="Point Cloud")
        st.Vectors = ["POINTS", u_name]
        st.SeedType.Center = [0.004, LY / 2.0, LZ / 2.0]
        st.SeedType.Radius = 0.030
        st.SeedType.NumberOfPoints = 600
        st.MaximumStreamlineLength = 0.5
        st.IntegrationDirection = "FORWARD"
        st.UpdatePipeline()
    else:
        # Buoyancy-driven case — sphere around the heater layer
        st = StreamTracer(registrationName="hero_streams", Input=calc,
                          SeedType="Point Cloud")
        st.Vectors = ["POINTS", u_name]
        st.SeedType.Center = [LX / 2.0, LY / 2.0, 0.012]
        st.SeedType.Radius = 0.025
        st.SeedType.NumberOfPoints = 400
        st.MaximumStreamlineLength = 0.5
        st.IntegrationDirection = "BOTH"
        st.UpdatePipeline()

    tube = Tube(registrationName="hero_tube", Input=st)
    tube.Radius = 0.0006
    tube.NumberofSides = 8
    tube.UpdatePipeline()

    tube_disp = Show(tube, view)
    if colour_by == "U":
        # Bar max ≈ 1.1× the fan-disk exhaust velocity (~1.8 m/s at 6000 rpm)
        colour_streamlines_by_Umag(tube_disp, view, vmax=2.0, u_name=u_name)
    else:
        colour_streamlines_by_T(tube_disp, view, vmin, vmax)
    tube_disp.Ambient = 0.25
    tube_disp.Diffuse = 0.7
    tube_disp.Specular = 0.3

    # ISO view
    set_camera(view,
               pos=[LX + 0.07, -0.06, LZ + 0.07],
               focal=[LX/2, LY/2, LZ/2],
               up=[0, 0, 1])
    save(view, out_dir / f"{label_prefix}_H1_iso.png")

    # Top view
    set_camera(view,
               pos=[LX/2, LY/2, LZ + 0.20],
               focal=[LX/2, LY/2, LZ/2],
               up=[0, 1, 0])
    save(view, out_dir / f"{label_prefix}_H2_top.png")

    # Side view (looking along +x)
    set_camera(view,
               pos=[LX + 0.20, LY/2, LZ/2],
               focal=[LX/2, LY/2, LZ/2],
               up=[0, 0, 1])
    save(view, out_dir / f"{label_prefix}_H3_side.png")

    # Hide everything for the next shot (Delete on ParaView 6.1 offscreen
    # render server tends to segfault when removing isos/tubes between renders).
    Hide(tube, view)
    for b in boxes:
        Hide(b, view)


def hero_isosurface_cutaway(calc, view, t_mean, out_dir: Path,
                            label_prefix: str):
    """Isosurfaces at T_mean+5/+10/+15 °C plus a vertical slice for context."""
    add_box_outline(calc, view)
    boxes = add_component_boxes(view, opacity=0.7)

    # Cutaway slice at y = LY (back wall, fully visible)
    sl = Slice(registrationName="hero_back_slice", Input=calc)
    sl.SliceType = "Plane"
    sl.SliceType.Origin = [LX/2, LY - 0.001, LZ/2]
    sl.SliceType.Normal = [0, 1, 0]
    sl.UpdatePipeline()
    sl_disp = Show(sl, view)
    ColorBy(sl_disp, ("POINTS", "T_C"))
    lut = GetColorTransferFunction("T_C")
    lut.ApplyPreset("Turbo", True)
    lut.RescaleTransferFunction(25, t_mean + 13)
    sl_disp.SetScalarBarVisibility(view, True)
    bar = GetScalarBar(lut, view)
    bar.Title = "T (°C)"
    bar.ComponentTitle = ""
    bar.TitleColor = [0, 0, 0]
    bar.LabelColor = [0, 0, 0]
    bar.Orientation = "Horizontal"
    bar.WindowLocation = "Lower Center"
    bar.ScalarBarLength = 0.5
    bar.TitleFontSize = 32
    bar.LabelFontSize = 26
    bar.ScalarBarThickness = 30

    # Isosurfaces at T_mean+5, +10, +15
    iso_specs = [
        (t_mean + 5,  [0.4, 0.85, 0.95], 0.30),
        (t_mean + 10, [1.0, 0.78, 0.0],  0.35),
        (t_mean + 15, [0.9, 0.25, 0.25], 0.50),
    ]
    isos = []
    for tval, rgb, opa in iso_specs:
        iso = Contour(registrationName=f"hero_iso_{tval:.0f}", Input=calc)
        iso.ContourBy = ["POINTS", "T_C"]
        iso.Isosurfaces = [tval]
        iso.UpdatePipeline()
        d = Show(iso, view)
        d.Representation = "Surface"
        d.AmbientColor = rgb
        d.DiffuseColor = rgb
        d.Opacity = opa
        d.Specular = 0.5
        isos.append(iso)

    set_camera(view,
               pos=[LX + 0.08, -0.06, LZ + 0.07],
               focal=[LX/2, LY/2, LZ/2],
               up=[0, 0, 1])
    save(view, out_dir / f"{label_prefix}_H4_iso_cutaway.png")

    Hide(sl, view)
    for i in isos:
        Hide(i, view)
    for b in boxes:
        Hide(b, view)


def hero_streams_over_slice(calc, view, t_mean, out_dir: Path,
                            label_prefix: str):
    """Vertical T slice (y=32.5mm) + 3D streamlines on top — combined "money shot"."""
    add_box_outline(calc, view)
    boxes = add_component_boxes(view, opacity=0.6)

    # Vertical slice along fan flow
    sl = Slice(registrationName="hero_combo_slice", Input=calc)
    sl.SliceType = "Plane"
    sl.SliceType.Origin = [LX/2, LY/2, LZ/2]
    sl.SliceType.Normal = [0, 1, 0]
    sl.UpdatePipeline()
    sl_disp = Show(sl, view)
    ColorBy(sl_disp, ("POINTS", "T_C"))
    lut = GetColorTransferFunction("T_C")
    lut.ApplyPreset("Turbo", True)
    lut.RescaleTransferFunction(25, t_mean + 13)
    sl_disp.Opacity = 0.92
    sl_disp.SetScalarBarVisibility(view, True)

    bar = GetScalarBar(lut, view)
    bar.Title = "T (°C)"
    bar.ComponentTitle = ""
    bar.TitleColor = [0, 0, 0]
    bar.LabelColor = [0, 0, 0]
    bar.Orientation = "Horizontal"
    bar.WindowLocation = "Lower Center"
    bar.ScalarBarLength = 0.5
    bar.TitleFontSize = 32
    bar.LabelFontSize = 26
    bar.ScalarBarThickness = 30

    # Streamlines
    st = StreamTracer(registrationName="hero_combo_streams", Input=calc,
                      SeedType="Line")
    st.Vectors = ["CELLS", "U"]
    st.SeedType.Point1 = [0.010, LY / 2.0, 0.006]
    st.SeedType.Point2 = [0.080, LY / 2.0, 0.006]
    st.SeedType.Resolution = 100
    st.MaximumStreamlineLength = 0.5
    st.IntegrationDirection = "BOTH"
    st.UpdatePipeline()

    tube = Tube(registrationName="hero_combo_tube", Input=st)
    tube.Radius = 0.0005
    tube.NumberofSides = 8
    tube.UpdatePipeline()
    tube_disp = Show(tube, view)
    ColorBy(tube_disp, None)
    tube_disp.AmbientColor = [0.05, 0.05, 0.05]
    tube_disp.DiffuseColor = [0.05, 0.05, 0.05]
    tube_disp.Opacity = 0.95

    set_camera(view,
               pos=[LX + 0.07, -0.05, LZ + 0.06],
               focal=[LX/2, LY/2, LZ/2],
               up=[0, 0, 1])
    save(view, out_dir / f"{label_prefix}_H5_streams_over_slice.png")

    Hide(tube, view); Hide(sl, view)
    for b in boxes:
        Hide(b, view)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def process_case(case_name: str):
    case_dir = RUNS / f"{case_name}_fine"
    if not case_dir.exists():
        print(f"SKIP {case_name}: {case_dir} not found")
        return
    out_dir = case_dir / "figs_hero"
    out_dir.mkdir(exist_ok=True)
    print(f"\n=== {case_name}  →  {out_dir.relative_to(HERE)} ===")

    # T_mean per case
    rt = (case_dir / "RESULT.txt").read_text()
    t_mean = float([l for l in rt.splitlines()
                    if l.startswith("T_mean_C")][0].split(":")[1])
    print(f"  T_mean = {t_mean:.2f} °C  →  colour bar [25, {int(t_mean + 13)}] °C")

    view = reset_view()
    reader, calc, u_name = load_case(case_dir)

    seed_mode = "vents" if case_name == "fan_on" else "sphere"
    colour_by  = "U"     if case_name == "fan_on" else "T"
    hero_streamlines(calc, view, vmin=25, vmax=int(t_mean + 13),
                     out_dir=out_dir, label_prefix=case_name,
                     seed_mode=seed_mode, colour_by=colour_by,
                     u_name=u_name)
    hero_isosurface_cutaway(calc, view, t_mean=t_mean,
                            out_dir=out_dir, label_prefix=case_name)
    # H5 (combined slice + streams) — DROPPED: rendered blank reliably after
    # H4's isosurface filter chain. The four shots above already cover the
    # story (H1 iso streams, H2 top, H3 side, H4 isosurface cutaway).


def main():
    targets = sys.argv[1:] or ["fan_on", "fan_off"]
    for name in targets:
        process_case(name)


if __name__ == "__main__":
    main()

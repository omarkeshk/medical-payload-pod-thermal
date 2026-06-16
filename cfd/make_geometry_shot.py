"""
Geometry-explicit 3D render: transparent enclosure walls with the actual
fan hole and vent slots cut out, fan coloured red, vents blue, heat-source
components orange. Shows the design geometry (not the flow).

Run:
    /Applications/ParaView-6.1.0.app/Contents/bin/pvbatch make_geometry_shot.py
Output -> runs/figs_graphs/geometry_*.png
"""
from __future__ import annotations
from pathlib import Path
import paraview.simple as pvs
from paraview.simple import (
    OpenFOAMReader, Show, Render, ResetCamera, SaveScreenshot,
    GetActiveViewOrCreate, Outline, Box,
)

HERE = Path(__file__).parent.resolve()
RUNS = HERE / "runs"
LX, LY, LZ = 0.090, 0.065, 0.050

WALLS = ["group/wall"]
FAN = ["patch/fan"]
VENTS = ["patch/ventFront", "patch/ventSide"]

COMPONENTS = {
    "resistor1": ((0.020, 0.025, 0.000), (0.030, 0.040, 0.008)),
    "resistor2": ((0.060, 0.025, 0.000), (0.070, 0.040, 0.008)),
    "mosfet":    ((0.040, 0.045, 0.000), (0.050, 0.055, 0.012)),
}

case_dir = RUNS / "fan_on_fine"
foam = case_dir / "case.foam"
if not foam.exists():
    foam.touch()


def load(name, regions):
    r = OpenFOAMReader(registrationName=name, FileName=str(foam))
    r.UpdatePipelineInformation()
    try:
        print(f"  available regions: {list(r.MeshRegions.Available)}")
    except Exception as e:
        print(f"  (could not list regions: {e})")
    r.MeshRegions = regions
    r.CellArrays = []
    r.UpdatePipeline()
    return r


view = GetActiveViewOrCreate("RenderView")
view.ViewSize = [2400, 1800]
try:
    view.BackgroundColorMode = "Single Color"
except Exception:
    pass
view.Background = [1.0, 1.0, 1.0]
view.UseColorPaletteForBackground = 0
view.OrientationAxesVisibility = 1


def surf(src, rgb, opacity):
    d = Show(src, view)
    d.Representation = "Surface"
    d.AmbientColor = rgb
    d.DiffuseColor = rgb
    d.Opacity = opacity
    d.Specular = 0.2
    return d


walls = load("walls", WALLS)
surf(walls, [0.62, 0.62, 0.62], 0.16)

fan = load("fan", FAN)
surf(fan, [0.86, 0.16, 0.16], 1.0)

vents = load("vents", VENTS)
surf(vents, [0.13, 0.45, 0.90], 1.0)

for nm, (lo, hi) in COMPONENTS.items():
    b = Box(registrationName="geo_" + nm)
    b.XLength = hi[0] - lo[0]
    b.YLength = hi[1] - lo[1]
    b.ZLength = hi[2] - lo[2]
    b.Center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
    surf(b, [1.0, 0.6, 0.1], 1.0)

o = Outline(Input=walls)
do = Show(o, view)
do.AmbientColor = [0.2, 0.2, 0.2]
do.DiffuseColor = [0.2, 0.2, 0.2]
do.LineWidth = 2.0

out = RUNS / "figs_graphs"
out.mkdir(exist_ok=True)


def shot(pos, fname):
    view.CameraParallelProjection = 0
    ResetCamera(view)
    view.CameraPosition = pos
    view.CameraFocalPoint = [LX / 2, LY / 2, LZ / 2]
    view.CameraViewUp = [0, 0, 1]
    Render(view)
    SaveScreenshot(str(out / fname), view, ImageResolution=[2400, 1800])
    print(f"  -> figs_graphs/{fname}")


# Angle 1: fan side (x=90, right) + front vents visible through transparency
shot([LX + 0.11, -0.085, LZ + 0.08], "geometry_fan_side.png")
# Angle 2: vent side (x=0 front + y=65 side) facing the camera
shot([-0.07, LY + 0.12, LZ + 0.085], "geometry_vent_side.png")
print("done")

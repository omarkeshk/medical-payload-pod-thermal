"""
CalculiX (ccx) steady-state conduction + radiation FEA of the space radiator.

Models the high-emissivity radiator panel sized in the analytical study
(~0.036 m^2 aluminium plate): 17 W is conducted in at the central heat-pipe
footprint, and the space-facing top surface radiates to deep space
(sink 2.7 K, emissivity 0.9). Solves the nonlinear (T^4) steady heat transfer
and reports the temperature field.

Generates the .inp deck, runs ccx_2.23, parses the .dat, and plots the field.
"""
import subprocess, re, os
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

JOB = "radiator"
WORK = "/tmp/fea_space"
os.makedirs(WORK, exist_ok=True)

# --- geometry / mesh ---
LX, LY, TZ = 0.190, 0.190, 0.003      # plate 0.19 x 0.19 m (=0.0361 m^2), 3 mm Al
NX, NY, NZ = 24, 24, 1
Q_TOTAL = 17.0                         # W conducted in
K_AL = 200.0                           # W/mK aluminium
EMIS = 0.9
T_SINK = 2.7                           # K, deep space
PATCH = 0.040                          # central 40 mm heat-pipe footprint

nx1, ny1, nz1 = NX+1, NY+1, NZ+1
def nid(ix, iy, iz): return iz*nx1*ny1 + iy*nx1 + ix + 1

nodes = []
for iz in range(nz1):
    for iy in range(ny1):
        for ix in range(nx1):
            nodes.append((nid(ix,iy,iz), ix*LX/NX, iy*LY/NY, iz*TZ/NZ))

elems = []
eid = 0
for iz in range(NZ):
    for iy in range(NY):
        for ix in range(NX):
            eid += 1
            n = [nid(ix,iy,iz), nid(ix+1,iy,iz), nid(ix+1,iy+1,iz), nid(ix,iy+1,iz),
                 nid(ix,iy,iz+1), nid(ix+1,iy,iz+1), nid(ix+1,iy+1,iz+1), nid(ix,iy+1,iz+1)]
            elems.append((eid, n))

# central bottom nodes (z=0) within the heat-pipe footprint
cx, cy = LX/2, LY/2
patch_nodes = [nd[0] for nd in nodes
               if abs(nd[3]) < 1e-9 and abs(nd[1]-cx) <= PATCH/2 and abs(nd[2]-cy) <= PATCH/2]
q_per_node = Q_TOTAL/len(patch_nodes)

# --- write .inp ---
lines = ["*NODE"]
for nd in nodes:
    lines.append(f"{nd[0]}, {nd[1]:.6f}, {nd[2]:.6f}, {nd[3]:.6f}")
lines.append("*ELEMENT, TYPE=C3D8, ELSET=Eall")
for e in elems:
    lines.append(f"{e[0]}, " + ", ".join(str(x) for x in e[1]))
lines.append("*NSET, NSET=Nall, GENERATE")
lines.append(f"1, {len(nodes)}, 1")
lines += ["*MATERIAL, NAME=AL", "*CONDUCTIVITY", f"{K_AL}",
          "*SOLID SECTION, ELSET=Eall, MATERIAL=AL",
          "*PHYSICAL CONSTANTS, ABSOLUTE ZERO=0., STEFAN BOLTZMANN=5.67E-8",
          "*INITIAL CONDITIONS, TYPE=TEMPERATURE", "Nall, 300."]
lines += ["*STEP, INC=200", "*HEAT TRANSFER, STEADY STATE"]
lines.append("*CFLUX")
for nn in patch_nodes:
    lines.append(f"{nn}, 11, {q_per_node:.6f}")
lines.append("*RADIATE")
for e in elems:                         # top face (R2) radiates to space
    lines.append(f"{e[0]}, R2, {T_SINK}, {EMIS}")
lines += ["*NODE PRINT, NSET=Nall", "NT", "*NODE FILE", "NT", "*END STEP"]
open(f"{WORK}/{JOB}.inp", "w").write("\n".join(lines) + "\n")
print(f"wrote {JOB}.inp  ({len(nodes)} nodes, {len(elems)} elems, "
      f"{len(patch_nodes)} heat-input nodes)")

# --- run ccx ---
r = subprocess.run(["ccx_2.23", JOB], cwd=WORK, capture_output=True, text=True)
print("ccx return:", r.returncode)
print((r.stdout or "")[-1200:])
if r.returncode != 0:
    print("STDERR:", (r.stderr or "")[-800:]); raise SystemExit(1)

# --- parse .dat for nodal temperatures ---
dat = open(f"{WORK}/{JOB}.dat").read()
temps = {}
grab = False
for ln in dat.splitlines():
    if "temperatures" in ln.lower():
        grab = True; continue
    if grab:
        m = re.match(r"\s*(\d+)\s+([-\d.eE+]+)\s*$", ln)
        if m: temps[int(m.group(1))] = float(m.group(2))
        elif ln.strip() == "" and temps: pass
vals = np.array(list(temps.values()))
if vals.size == 0:
    print("No temps parsed"); raise SystemExit(1)
Tc = vals - 273.15
print(f"T range: {Tc.min():.1f} .. {Tc.max():.1f} C   mean {Tc.mean():.1f} C")

# --- plot top-surface temperature field ---
top = [(nd[1], nd[2], temps.get(nd[0])) for nd in nodes
       if abs(nd[3]-TZ) < 1e-9 and nd[0] in temps]
xs = np.array([p[0] for p in top])*1000
ys = np.array([p[1] for p in top])*1000
ts = np.array([p[2] for p in top])-273.15
gx = int(round(np.sqrt(len(xs))))
order = np.lexsort((xs, ys))
fig, ax = plt.subplots(figsize=(6.8,5.4))
pc = ax.tricontourf(xs, ys, ts, levels=20, cmap="inferno")
cb = fig.colorbar(pc, ax=ax); cb.set_label("Temperature (°C)")
ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)")
ax.set_title(f"CalculiX FEA — radiator panel in vacuum\n"
             f"17 W, ε=0.9, radiating to deep space  |  T = {ts.min():.1f}–{ts.max():.1f} °C")
ax.set_aspect("equal"); fig.tight_layout()
fig.savefig(f"{WORK}/radiator_fea.png", dpi=150)
print("saved radiator_fea.png")

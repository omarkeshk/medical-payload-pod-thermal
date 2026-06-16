# CFD Results — Plant Module Thermal Simulation

**Fan ON vs. fan OFF (natural draft), geometry straight from the CAD**
OpenFOAM v2512 + ParaView 6.1 + matplotlib graphs on Apple Silicon (M4 Max, 8 cores).
Updated 2026-06-13.

> **Quick read:** start with §2 (summary dashboard), then §3 (numbers), then jump to §4 (figures by topic). The caveat catalogue is in §7.

---

## 1 · TL;DR

| Case | Configuration | T_mean (bulk air) | Headroom vs. 40 °C limit |
|---|---|---|---|
| **Fan ON** | 50 mm 5 V fan @ 6000 rpm exhausting through the 45 mm opening; intake through 6 slots | **32.22 °C** | **+7.78 °C  ✅ PASS** |
| **Fan OFF** | Same enclosure, fan stopped (opening blocked), vents open — natural draft | **65.34 °C** | −25.34 °C  ❌ FAIL |

Three conclusions:

1. **The design works.** With the fan running, bulk air sits ~7 °C above ambient and clears the
   40 °C spec limit with a 7.8 °C margin.
2. **The fan is mandatory.** Buoyant draft through the vent slots alone leaves the box at 65 °C.
   The fan removes **33 °C** of bulk-air temperature.
3. **The vents still earn their keep.** A fully sealed box would reach ~118 °C (analytical bound,
   `analytical/baseline.py`); the slots cut the fan-failure scenario in half. And with the fan ON,
   the slots are what feed it: their 1350 mm² of intake area sets the fan's operating point.

---

## 2 · One-figure summary

![Summary dashboard](figs_graphs/G7_summary_dashboard.png)

Five panels: (top L→R) heater-layer temperature with fan ON, same with fan OFF, verdict bar; (bottom L→R) vertical T probe through Resistor 1 (log axis), solver convergence for both cases.

---

## 3 · Numerical results

| Quantity | Fan ON | Fan OFF (draft) | Δ |
|---|---|---|---|
| **T_mean (whole domain, iteration-averaged)** | **32.22 °C** | **65.34 °C** | **−33.1 °C** |
| T_min (bulk air) | 23.29 °C *(slight sub-ambient undershoot — C5)* | 24.75 °C | — |
| T_max (raw, source cells) | 280.0 °C | 633.3 °C | — *(non-physical artefact — see C1)* |
| Cells | 528 000 | 528 000 | — |
| Iterations | 4000 *(fields averaged over 2000–4000)* | 8000 *(averaged over 4000–8000)* | — |
| Wall time | 10.0 min | 20.0 min | — |
| Fan operating flow | 3.13 L/s (6.6 CFM, 74 % of free flow) | 0 | — |

### The geometry (all from the CAD)

Internal cavity **90 × 65 × 50 mm** (x × y × z), PLA walls 2.5 mm. Flow axis is X.

| Opening | Location | Nominal | Meshed | Error |
|---|---|---|---|---|
| Fan opening, 45 mm Ø (50 mm fan) | x = 90 short wall, centred | 1590 mm² | 1595 mm² | +0.3 % |
| 3 front slots, 50 × 5 mm | x = 0 wall, centred, 7.5 mm gaps (rows z = 10–15 / 22.5–27.5 / 35–40) | 750 mm² | 756 mm² | +0.7 % |
| 3 side slots, 40 × 5 mm | y = 65 long wall, same vertical pattern | 600 mm² | 589 mm² | −1.8 % |

Heat input: 17 W total — 8.15 W in each of two power resistors + 0.7 W in the MOSFET, applied as
volumetric sources in cellZones at their breadboard positions on the floor.

### Fan model

The 50 mm 5 V fan (5010 class) free-blows ~9 CFM at 6000 rpm with ~40 Pa max static pressure
(linear P–Q curve, affinity-scaled with rpm). Intersecting that with the slot system curve
(orifice law, C_d = 0.62, plus the exit dynamic loss) gives the operating point:
**Q = 3.13 L/s — 74 % of free flow** — applied exactly on the fan patch via
`flowRateInletVelocity` (exhaust). The intake slots are passive `prghTotalPressure` boundaries:
the solver decides how much air each slot admits.

**Why T_mean is the headline number, not T_max.** The heat sources are applied inside cellZones of
*air* (no solid resistor body — see C1 in §7). The innermost air cells overshoot by hundreds of °C;
**T_mean of the bulk air** is what the 40 °C limit constrains. T_max is reported but is not a real
component temperature.

**Energy-balance sanity check (fan ON).** Advected heat through the fan disk =
ρ·Q·cp·ΔT = 1.2 × 3.13×10⁻³ × 1005 × (28.3 − 25) ≈ **12.5 W**, plus ~3.5 W through the walls
(floor-dominated) ≈ 16 W vs. 17 W input — closure within the 1 mm-offset sampling error.

---

## 4 · Figures (graph-driven)

All matplotlib graphs are in `runs/figs_graphs/`; ParaView 3D renders are in each case's `figs/` and `figs_hero/` folders.

### 4.1 Convergence — what "solved" means here

![G1 — solver convergence](figs_graphs/G1_convergence.png)

Each line is the initial residual (per SIMPLE iteration) of one transport equation. The vent/fan
jets are mildly unsteady (small slot jets merge and flap), so under steady-state SIMPLE the
residuals fall 2–3 orders of magnitude and then settle into a **bounded band**
(final initial-residuals — fan ON: p_rgh ≈ 6×10⁻³, h ≈ 3×10⁻⁴; fan OFF: p_rgh ≈ 1.3×10⁻², h ≈ 2×10⁻³).
That's the signature of a quasi-steady flow, not divergence. The standard mitigation is applied:
a `fieldAverage` function object accumulates **TMean/UMean over the second half of each run**, and
every number and figure in this report uses the averaged fields. Coarse-mesh checks show the
averaged T_mean is stable to under 1 °C across snapshots and relaxation settings.

### 4.2 Verdict — both operating points against the limit

![G2 — verdict bar](figs_graphs/G2_validation_bar.png)

Fan ON passes at 32.2 °C; fan OFF fails at 65.3 °C; the grey reference bar is the hand-calculated
sealed-box bound (118 °C — what happens if the vents are blocked AND the fan is off). The
analytical bound brackets the CFD from above, as it must: each added cooling path (slots → draft,
fan → forced flow) steps the temperature down.

### 4.3 Temperature along probe lines — quantitative cross-sections

![G4 — line probes](figs_graphs/G4_line_probes.png)

Four key probe lines, log T-axis. The orange band on each panel marks where the line passes *inside* a heater cellZone — those T values are the non-physical source-cell artefacts disclosed in C1.

* **Top-left (vertical through Resistor 1):** fan-on returns to ambient above z ≈ 13 mm; fan-off
  sits at 50+ °C from floor to lid.
* **Top-right (vertical through MOSFET):** fan-on stays under ~40 °C even directly over the
  MOSFET; fan-off holds 50–81 °C over the column.
* **Bottom-left (fan-axis line, front vents → fan disk at z = 25 mm):** fan-on is flat at
  25–26 °C — the fan axis carries fresh intake air; the heat travels along the floor (see G6
  y = 32.5). Fan-off climbs from ~42 °C at the vents to 100+ °C over the heaters.
* **Bottom-right (across heaters at z = 6 mm):** source-zone spikes (artefact) over the meaningful
  baseline: ~30 °C between heaters with fan-on, ~36–60 °C without.

### 4.4 Heat balance — where do the 17 W actually go?

![G5 — energy balance](figs_graphs/G5_energy_balance.png)

Per-path heat extraction from CFD-sampled wall-adjacent temperatures (1 mm offset) plus advection
terms; fan-on normalised to Σ = 17 W.

* **Fan ON (left):** the **fan exhaust carries ~75–80 %** of the heat as warm air
  (ρQcpΔT with the sampled 28.3 °C disk temperature); the floor carries most of the rest — the
  intake jets enter at z ≥ 10 mm, so the floor layer under them is the one place heat lingers.
  Every other wall is a bystander.
* **Fan OFF (right):** buoyant **vent draft carries roughly half** (reported as the residual
  17 W − Σ walls), with the remainder spread over the now-uniformly-warm walls (all six sit at
  39–59 °C wall-adjacent — the stratified box heats everything).

### 4.5 Side-by-side contour panels — same plane, both cases

Four planes; each panel uses an independent colour bar locked to **[25 °C, T_mean+13 °C]**, so dark-red saturation marks cells that exceed the bar (the source-cell artefacts). Flow axis is **X** (front slots at x = 0 → fan disk at x = 90).

| Plane | What it shows | File |
|---|---|---|
| z = 4 mm (horizontal, heater layer) | Floor heat footprint under the intake jets (ON) vs. broad halos (OFF) | [G6_slice_z004.png](figs_graphs/G6_slice_z004.png) |
| z = 25 mm (horizontal, fan-axis height) | Near-ambient mid-plane (ON) vs. stratified 50–70 °C (OFF) | [G6_slice_z025.png](figs_graphs/G6_slice_z025.png) |
| x = 25 mm (vertical, through Resistor 1) | Cross-flow section incl. the side-slot intake jets | [G6_slice_x025.png](figs_graphs/G6_slice_x025.png) |
| y = 32.5 mm (vertical, contains the fan axis) | **The iconic image** — floor-hugging hot layer feeding the fan (ON) vs. buoyant fill (OFF) | [G6_slice_y0325.png](figs_graphs/G6_slice_y0325.png) |

### 4.6 Hero 3D shots — streamlines and isosurfaces

Eight high-resolution (2400×1800) renders, one set per case, in `runs/<case>_fine/figs_hero/`.

| File | What it shows |
|---|---|
| `H1_iso.png` | 3D streamlines, isometric view. **Fan ON:** seeded at the front vents, coloured by \|U\| — intake jets cross the box, recirculate, and accelerate to ~2 m/s into the 45 mm fan disk. **Fan OFF:** streamlines coloured by T — buoyant plumes rise off the heaters and leave through the upper slots (natural-draft loop). |
| `H2_top.png` | Top-down view. **Fan ON:** how the front-slot and side-slot streams organise and converge on the fan. **Fan OFF:** circulation cells drifting toward the vent walls. |
| `H3_side.png` | View along the fan axis. **Fan ON:** jet cores and recirculation. **Fan OFF:** the vertical buoyant column. |
| `H4_iso_cutaway.png` | Isosurfaces at T_mean+5/+10/+15 °C with a cutaway slice. **Fan ON:** tight envelopes around each heater. **Fan OFF:** the +15 °C surface fills most of the box. |

### 4.7 Legacy ParaView renders (figs/)

Each case directory also contains 10 ParaView-rendered PNGs (`runs/<case>_fine/figs/*.png`) — slices, glyphs, isosurfaces, streamlines — computed on the iteration-averaged fields.

---

## 5 · Engineering takeaways

* **PASS with the fan, FAIL without it.** 32.2 °C vs. 65.3 °C bulk air. The fan is a hard
  requirement, not an optimisation.
* **The slot sizing drives the fan's delivery.** The six slots (1350 mm²) are smaller than the fan
  opening (1590 mm²), making them the dominant flow restriction — the fan operates at 74 % of its
  free-flow rating. Enlarging the slots (or adding a fourth row) is the cheapest way to buy margin;
  shrinking them would throttle the fan quickly.
* **Heat hugs the floor when the fan runs.** The intake slots sit at z ≥ 10 mm, so the floor layer
  below them is the slowest-moving air in the box: floor wall-adjacent T ≈ 50 °C while every other
  wall reads ≤ 36 °C. Keep heat-sensitive parts off the floor downstream of the resistors; the lid
  is thermally prime real estate.
* **With the fan on, ~3/4 of the heat leaves as warm exhaust air** — wall material is a structural/
  cost choice, not a thermal one.
* **The vents double as a passive safety net.** Fan failure means 65 °C, not the 118 °C of a sealed
  box — hot, but survivable hardware-wise for a landing window.

---

## 6 · Reproduce

From `term-project/cfd/atmospheric/`:

```bash
# Re-run CFD (≈ 10 min fan-on, ≈ 20 min fan-off):
python3 run_report_cases.py

# Export field samples (≈ 2 min):
/Applications/ParaView-6.1.0.app/Contents/bin/pvbatch export_samples.py

# Generate all matplotlib graphs (≈ 15 s):
../../.venv/bin/python make_graphs.py

# Hero 3D renders + legacy ParaView figures (≈ 3 min):
/Applications/ParaView-6.1.0.app/Contents/bin/pvbatch make_hero_shots.py
./make_figs.sh

# Open a case interactively:
paraview runs/fan_on_fine/case.foam &
```

Geometry constants (fan centre/diameter, slot rectangles, fan curve) live at the top of
`case_generator.py` — change a slot there and re-run one command.

---

## 7 · Caveats & approximations (read before defending)

* **C1 · Heaters are air boxes, not solid bodies.** Each resistor is a 10×15×8 mm cellZone of air
  with a volumetric source. Total power is exact, so T_mean is reliable; the 280 / 633 °C peaks
  inside the source zones are artefacts and must never be quoted as component temperatures.
  (A conjugate heat-transfer model with solid bodies is the upgrade path.)
* **C2 · Fan curve is a datasheet-class assumption.** 9 CFM / 40 Pa @ 6000 rpm is typical for a
  5010 fan but not measured for our unit. ±20 % on flow ≈ ∓1.5 °C on fan-on T_mean.
* **C3 · Quasi-steady residual plateau.** Both runs end with residuals in a bounded band (real jet
  unsteadiness under a steady solver); all reported values are iteration-averaged (TMean/UMean,
  second half of each run). See §4.1.
* **C4 · Mesh sensitivity.** Coarse (18.7 k) ⇄ fine (528 k): fan-on 33.3 → 32.2 °C, fan-off
  65.7 → 65.3 °C. Both verdicts are mesh-robust; no formal 3-level study was run.
* **C5 · Minor numerical undershoot.** Fan-on T_min = 23.3 °C (1.7 K below ambient) in a handful
  of cells near the steep source-zone gradients; no effect on T_mean.
* **C6 · Stair-stepped openings.** The circular fan disk and slots are carved from a structured
  hex mesh; effective areas are within 0.3–1.8 % of nominal (table in §3). Fan mass flow is exact
  regardless (`flowRateInletVelocity`); intake jet velocities carry the ≤ 2 % area error.
* **C7 · Stopped fan modelled as a sealed disk** in the fan-off case. A real stationary axial fan
  leaks some draft through the blade gaps, so the true fan-off temperature is somewhat below
  65.3 °C — the FAIL verdict is robust either way.
* **C8 · Wall model is lumped.** External natural convection + wall conduction + radiation are
  combined into one effective coefficient (h_eff ≈ 13 W/m²K, PLA ε = 0.90, radiation linearised
  at 320 K). Fine for a box whose walls carry a minority of the heat.
* **C9 · Other physics scope.** Steady-state only (the spec limit is steady-state); k-ω SST RAS
  with low-Re wall treatment (first-cell y⁺ ≈ 2); space-environment FEA not attempted.

---

## 8 · Source files

```
term-project/cfd/atmospheric/
├── case_generator.py            # parametric OpenFOAM case writer
│                                #   ── CAD geometry constants: FAN_CENTER_M, FAN_RADIUS_M,
│                                #      FRONT_SLOTS_M, SIDE_SLOTS_M, fan_operating_flow()
├── runner.py                    # generate + mesh (blockMesh/topoSet/createPatch) + solve + parse
├── run_report_cases.py          # ★ runs fan_on and fan_off at fine mesh
├── export_samples.py            # ★ pvbatch script — slice/line/wall NPZ exports (TMean/UMean-aware)
├── make_graphs.py               # ★ matplotlib script — generates G1/G2/G4–G7 graphs
├── make_hero_shots.py           # pvbatch script — H1..H4 hero renders
├── make_paraview_figures.py     # pvbatch script — additional 3D ParaView renders
├── make_figs.sh                 # wrapper for the ParaView 3D renders
└── runs/
    ├── RESULTS.md               # ★ this file
    ├── EXPLAINED.html           # ★ teaching version (same numbers, more words)
    ├── figs_graphs/             # ★ matplotlib analytical graphs
    ├── fan_on_fine/             # fan ON: 4000/, samples/, figs/, figs_hero/, logs
    └── fan_off_fine/            # fan OFF natural draft: 8000/, samples/, figs/, figs_hero/, logs
```

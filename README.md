# Thermal Management of a Battery-Powered Medical Payload Pod

Heat Transfer (MEP311s) term project — **Team 14**, Mechatronics & Robotics Department, Ain Shams University, Faculty of Engineering, Spring 2026.

A scaled prototype of a Zipline-style drone medical-payload pod with three thermally managed
enclosures (power, control, and a resistive-heating *plant* module). The goal: keep every module
**≤ 40 °C** in steady state while dissipating ~17 W, under tight mass/cost constraints.

**Result:** the plant module is held at ~35 °C with a single 50 mm fan + intake vents
(closed-loop PWM control), validated by hand calculation, 3-D CFD, and experiment.

## Repository structure

| Folder | Contents |
|---|---|
| `firmware/` | Arduino controller (`payload_pod_controller.ino`) — PWM MOSFET heat regulation, 3× DHT sensors, battery voltage/current monitoring, LED alert (35 °C) and 40 °C cutoff. |
| `logging/` | Python serial-logging + analysis toolkit. `live_heat.py` (live 3-sensor plot), `log_heat.py`, `plot_heat.py`, `report_heat.py` (report figures + lumped-capacitance τ fit), `heat_common.py`. |
| `data/` | Sample experimental runs: `heat_fan_off.csv` (no cooling), `heat_cooling.csv` (cool-down), `heat_fan_at_35.csv` (steady-state control). |
| `cfd/` | OpenFOAM CFD pipeline (parametric, no CAD import): `case_generator.py`, `runner.py`, `run_report_cases.py`, ParaView/figure scripts, and `RESULTS.md`. |
| `space/` | Space-environment (vacuum) bonus variant: `space_analysis.md` (radiation balance + radiator sizing) and `calculix/` — a CalculiX conduction+radiation FEA of the radiator panel. |
| `report/` | The final technical report (PDF) — full analysis, figures, BOM, and results. |

## Hardware

- Arduino Uno/Nano · IRF530N MOSFET · 2× ceramic power resistors (heaters) · 3× DHT11 sensors
- 4× 18650 Li-ion cells (8 V) · 50 × 50 × 10 mm 5 V cooling fan · 3-D-printed PLA enclosures with vent slots

## Quick start

**Firmware:** open `firmware/payload_pod_controller.ino` in the Arduino IDE, install the DHT library, set the pin map at the top, and upload.

**Live logging:**
```bash
pip install pyserial pandas matplotlib scipy
python logging/live_heat.py            # live 3-sensor plot
python logging/report_heat.py <run.csv>  # report figures + tau fit
```

**CFD (OpenFOAM v2512 + ParaView):**
```bash
cd cfd && python run_report_cases.py   # fan-on and fan-off cases
```

## Methods

- **Analytical:** thermal-resistance network + energy balance; lumped-capacitance time constant
  (cooling τ ≈ 29 s, R² = 0.995).
- **CFD (bonus):** `buoyantSimpleFoam`, k-ω SST, 528 k cells — fan ON 32 °C (PASS), fan OFF 65 °C (FAIL).
- **Space variant (bonus):** vacuum radiation balance + CalculiX conduction-radiation FEA — a ~0.035 m² high-emissivity radiator holds the module at 40 °C (FEA mean ≈ 37 °C).
- **Experiment:** steady-state ~35 °C under closed-loop control; full-heat draw 17.1 W.

## Team 14
Salma Saeed · Jana Mohamed · Omar Ahmad Keshk · Omar Khaled

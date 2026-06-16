"""
Radiator sizing for the payload pod in vacuum (space-environment bonus).

Steady-state radiation energy balance:
    Q = eps * sigma * A * (Ts^4 - Tsink^4)

- Computes the temperature the bare enclosure would reach in vacuum.
- Computes the high-emissivity radiating area needed to hold the 40 C limit.
- Saves the Ts-vs-area sizing curve.

Run:  python radiator_sizing.py
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SIGMA  = 5.67e-8      # Stefan-Boltzmann constant, W/m^2 K^4
EPS    = 0.90         # emissivity of a high-emissivity (black) coating
Q      = 17.0         # W, total dissipation (2 resistors + MOSFET + electronics)
T_SINK = 0.0          # K, deep-space sink (idealized; a real orbit is warmer)
A_BOX  = 0.0272       # m^2, external area of the 90 x 65 x 50 mm enclosure
T_LIMIT = 40.0        # C, the spec constraint


def Ts_for_area(A):
    """Steady surface temperature (C) that radiates Q from area A."""
    return (Q / (EPS * SIGMA * A) + T_SINK**4) ** 0.25 - 273.15


def area_for_T(T_C):
    """Radiating area (m^2) needed to hold surface temperature T_C."""
    return Q / (EPS * SIGMA * ((T_C + 273.15) ** 4 - T_SINK**4))


if __name__ == "__main__":
    T_box = Ts_for_area(A_BOX)
    A_req = area_for_T(T_LIMIT)
    print(f"Bare enclosure  ({A_BOX*1e4:.0f} cm^2):  Ts = {T_box:.1f} C  "
          f"-> {'PASS' if T_box <= T_LIMIT else 'FAIL'}")
    print(f"Area required for {T_LIMIT:.0f} C:  {A_req*1e4:.0f} cm^2  "
          f"({A_req:.4f} m^2)")

    A = np.linspace(0.010, 0.060, 300)
    plt.figure(figsize=(8, 4.3))
    plt.plot(A * 1e4, Ts_for_area(A), "k-", lw=2)
    plt.axhline(T_LIMIT, ls="--", color="red", label=f"{T_LIMIT:.0f} C limit")
    plt.scatter([A_BOX * 1e4], [T_box], color="#c0392b", zorder=5, s=60)
    plt.annotate(f"bare box  {A_BOX*1e4:.0f} cm^2 -> {T_box:.0f} C (FAIL)",
                 xy=(A_BOX*1e4, T_box), xytext=(A_BOX*1e4+40, T_box+8),
                 arrowprops=dict(arrowstyle="->"))
    plt.axvline(A_req * 1e4, ls=":", color="green")
    plt.annotate(f"need ~{A_req*1e4:.0f} cm^2 for {T_LIMIT:.0f} C",
                 xy=(A_req*1e4, T_LIMIT), xytext=(A_req*1e4+25, T_LIMIT+18),
                 color="green", arrowprops=dict(arrowstyle="->", color="green"))
    plt.xlabel("radiating area (cm^2)")
    plt.ylabel("steady surface temperature (C)")
    plt.title(f"Vacuum radiative cooling  (Q = {Q:.0f} W, eps = {EPS})")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig("radiator_sizing.png", dpi=150)
    print("saved radiator_sizing.png")

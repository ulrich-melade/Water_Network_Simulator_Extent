"""
plot_comparison.py — WNTR vs physically calibrated algebraic model.

Author:
    - Ulrich Melade

What it does:
    Superposes the WNTR simulation data (CSV produced by simulator.py) with a
    purely physical steady-state model rebuilt from the network geometry:
    it loads the .inp geometry, calibrates the equivalent hydraulic resistance
    R_eff and the leak constants on the data, solves the implicit pressure
    equation at each time step (scipy fsolve) and plots pressure / flow /
    velocity (WNTR vs model), with leak periods shaded in red. The figure is
    saved as physical_superposition.png.

What to modify (CONFIG section) and its effect:
    - INP_PATH      : EPANET network that generated the CSV. It must contain
                      OBSERVED_PIPE, otherwise the geometry loading fails.
    - CSV_PATH      : simulation CSV to compare against the model.
    - OBSERVED_PIPE : pipe whose start node is used for pressure/flow
                      comparison (must match the pipe monitored in the CSV).
    - MCE_PER_BAR   : unit constant (10.197 mH2O per bar) — do not change.

"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
import math
from scipy.optimize import fsolve
import wntr

# ==============================================================
# 0. CONFIG
# ==============================================================
INP_PATH = "city-pipelines/Network/Scenario/Low_Demand.inp"
CSV_PATH = "city-pipelines/Network/Scenario/3d_leak.csv"
OBSERVED_PIPE = "P76"
MCE_PER_BAR = 10.197


# ==============================================================
# 1. GEOMETRIC PARAMETERS from the INP (strict physical reference)
# ==============================================================
def prepare_network(wn):
    max_elev = max(
        [n.elevation for _, n in wn.nodes() if hasattr(n, "elevation")] + [0]
    )
    for _, node in wn.nodes():
        if node.node_type in ["Reservoir", "Tank"]:
            if getattr(node, "base_head", 0) < max_elev + 10:
                node.base_head = max_elev + 10
    for _, pipe in wn.links():
        if pipe.link_type == "Pipe":
            if pipe.start_node_name.startswith("M") or pipe.end_node_name.startswith(
                "M"
            ):
                pipe.diameter = 0.02
    for _, link in wn.links():
        if (
            hasattr(link, "roughness")
            and wn.options.hydraulic.headloss == "H-W"
            and link.roughness < 1.0
        ):
            link.roughness = 130.0


def load_geometry():
    wn = wntr.network.WaterNetworkModel(INP_PATH)
    prepare_network(wn)
    pipe = wn.get_link(OBSERVED_PIPE)
    node = wn.get_node(pipe.start_node_name)
    src = wn.reservoir_name_list[0]
    A = math.pi * (pipe.diameter / 2) ** 2

    # Physics: the static pressure only depends on the altitude difference
    P_static = (wn.get_node(src).base_head - node.elevation) / MCE_PER_BAR
    return {"A": A, "P_static": P_static, "node": pipe.start_node_name}


# ==============================================================
# 2. READING WNTR DATA
# ==============================================================
def load_wntr(csv_path):
    df = pd.read_csv(csv_path, sep="|")
    hours = (
        df["t"] / 3600.0 if df["t"].diff().max() > 2.0 else df["t"] / 20.0
    ).to_numpy()
    # Empty cells are read as NaN by pandas — no need for .replace(-1.0, np.nan)
    P = df["x_0"].to_numpy(dtype=float)
    V = df["x_1"].to_numpy(dtype=float)
    Q = df["x_2"].to_numpy(dtype=float)
    # 'demand' is written by the current simulator; 'demande' kept for older CSVs
    demand_col = (
        "demand" if "demand" in df else ("demande" if "demande" in df else None)
    )
    demand = df[demand_col].to_numpy() if demand_col else np.full_like(hours, np.nan)
    leak = df["ud"].astype(str).str.contains("leak").to_numpy().astype(float)
    return hours, P, V, Q, demand, leak


# ==============================================================
# 3. PHYSICAL CALIBRATION (Steady-state, R_eff and Leak Constants)
# ==============================================================
def calibrate(hours, P_w, Q_w, demand_w, leak, P_static):
    D = demand_w / 1000.0  # m³/s
    nominal = (leak < 0.5) & np.isfinite(P_w) & np.isfinite(Q_w)

    # 1. Calibrate the equivalent resistance (R_eff) on the nominal
    dP_nom = P_static - P_w[nominal]
    X_nom = D[nominal] ** 1.852

    valid_X = X_nom > 1e-6
    if valid_X.any():
        R_eff = float(np.median(dP_nom[valid_X] / X_nom[valid_X]))
    else:
        R_eff = 0.0

    # 2. Calibrate the nominal flow distribution
    a, b = np.polyfit(D[nominal], Q_w[nominal], 1)

    # 3. Detect each leak event separately
    leak_events = []
    in_leak = False
    start_idx = 0
    for i, l in enumerate(leak):
        if l >= 0.5 and not in_leak:
            in_leak = True
            start_idx = i
        elif l < 0.5 and in_leak:
            in_leak = False
            leak_events.append((start_idx, i - 1))
    if in_leak:
        leak_events.append((start_idx, len(leak) - 1))

    # 4. Calibrate the physics of EACH leak individually
    cal_leaks = []
    for start, end in leak_events:
        idx_f = np.arange(start, end + 1)
        P_f = P_w[idx_f]
        D_f = D[idx_f]
        Q_f = Q_w[idx_f]

        # Total flow requested from the network to cause the observed pressure drop
        dP_f_obs = P_static - P_f
        Q_tot_f = (np.maximum(0, dP_f_obs) / R_eff) ** (1 / 1.852)

        # The flow surplus is the leak
        Q_leak_est = Q_tot_f - D_f

        # K_leak = Q_leak / sqrt(P_w)
        valid_P = P_f > 0
        K_l = (
            float(np.median(Q_leak_est[valid_P] / np.sqrt(P_f[valid_P])))
            if valid_P.any()
            else 0.0
        )

        # Leak impact on Q76
        Q_nom_est = a * D_f + b
        dQ76 = Q_f - Q_nom_est
        valid_Qleak = Q_leak_est > 1e-6
        c_l = (
            float(np.median(dQ76[valid_Qleak] / Q_leak_est[valid_Qleak]))
            if valid_Qleak.any()
            else 0.0
        )

        cal_leaks.append({"start": start, "end": end, "K_leak": K_l, "c_leak": c_l})

    return {"P_static": P_static, "R_eff": R_eff, "a": a, "b": b, "leaks": cal_leaks}


# ==============================================================
# 4. PHYSICAL MODEL (Algebraic resolution, no ODE)
# ==============================================================
def solve_model(hours, demand_w, cal, A):
    D = demand_w / 1000.0
    P_m = np.zeros_like(hours)
    Q_m = np.zeros_like(hours)

    P_static = cal["P_static"]
    R_eff = cal["R_eff"]
    a = cal["a"]
    b = cal["b"]
    cal_leaks = cal["leaks"]

    def P_equation(P, d_t, K_leak):
        Q_L = K_leak * np.sqrt(abs(P))
        Q_tot = d_t + Q_L
        return P_static - R_eff * (Q_tot**1.852) - P

    for i in range(len(hours)):
        d_t = D[i]

        # Check if we are in a leak event
        current_leak = None
        for lk in cal_leaks:
            if lk["start"] <= i <= lk["end"]:
                current_leak = lk
                break

        K_leak = current_leak["K_leak"] if current_leak else 0.0
        c_leak = current_leak["c_leak"] if current_leak else 0.0

        # P(t) resolution
        p_sol = fsolve(P_equation, P_static, args=(d_t, K_leak))[0]
        P_m[i] = p_sol

        # Physical flow calculation
        Q_L = K_leak * np.sqrt(abs(p_sol))
        Q_m[i] = a * d_t + b + c_leak * Q_L

    V_m = (Q_m / 1000.0) / A
    return hours, P_m, Q_m, V_m


# ==============================================================
# 5. MAIN
# ==============================================================
def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV not found: {CSV_PATH}")
        sys.exit(1)

    geo = load_geometry()
    hours, P_w, V_w, Q_w, demand_w, leak = load_wntr(CSV_PATH)
    cal = calibrate(hours, P_w, Q_w, demand_w, leak, geo["P_static"])

    print("-- Physical Calibration (Steady-state + Multiple emitters) --")
    print(f"   P_static (INP Geometry) = {cal['P_static']:.3f} bar")
    print(f"   R_eff (Hazen-Williams)  = {cal['R_eff']:.3f}")
    print(f"   Q76 (nominal)           = {cal['a']:.2f}*D + {cal['b']:.3f} (L/s)")

    for i, lk in enumerate(cal["leaks"]):
        print(
            f"   Leak {i+1} (t={hours[lk['start']]:.1f}h to {hours[lk['end']]:.1f}h):"
        )
        print(f"      K_leak = {lk['K_leak']:.5f} (m3/s / sqrt(bar))")
        print(f"      Impact on Q76 = {lk['c_leak']:.3f} * Q_leak")

    t_m, P_m, Q_m, V_m = solve_model(hours, demand_w, cal, geo["A"])

    # ── Visualization ──
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    try:
        plt.style.use("seaborn-v0_8-darkgrid")
    except Exception:
        pass

    ax1 = axes[0]
    ax1.plot(hours, P_w, "k-", lw=2.5, alpha=0.6, label="WNTR Pressure")
    ax1.plot(hours, P_m, "r--", lw=2, label="Pressure — algebraic physical model")
    ax1.set_ylabel("Pressure (bar)")
    ax1.set_title(
        f"WNTR vs Physical Model (P_stat={cal['P_static']:.2f} bar, R_eff={cal['R_eff']:.2f})"
    )
    ax1.legend()

    ax2 = axes[1]
    ax2.plot(hours, Q_w, "k-", lw=2.5, alpha=0.6, label=f"{OBSERVED_PIPE} WNTR Flow")
    ax2.plot(hours, Q_m, "g--", lw=2, label="Flow — physical model (distribution)")
    ax2.set_ylabel("Flow (L/s)")
    ax2.legend()

    ax3 = axes[2]
    ax3.plot(hours, V_w, color="purple", lw=2.5, alpha=0.6, label="WNTR Velocity")
    ax3.plot(hours, V_m, "b--", lw=2, label="Velocity — model (Q/A)")
    ax3.set_ylabel("Velocity (m/s)")
    ax3.set_xlabel("Time (Hours)")
    ax3.legend()

    for ax in axes:
        for d in range(1, int(np.nanmax(hours) / 24) + 1):
            ax.axvline(d * 24, color="gray", linestyle=":", alpha=0.5)
        # Shading each leak
        for lk in cal["leaks"]:
            ax.axvspan(hours[lk["start"]], hours[lk["end"]], color="red", alpha=0.08)

    plt.tight_layout()
    plt.savefig("physical_superposition.png", dpi=150)
    print("Figure saved: physical_superposition.png")


if __name__ == "__main__":
    main()

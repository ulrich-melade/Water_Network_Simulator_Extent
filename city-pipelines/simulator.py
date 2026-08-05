"""
simulator.py
======================
Improved multi-day hydraulic simulator.
Does not modify any existing files — relies on Low_Demand.inp only.

Authors:
    - Ulrich Melade
    - Etienne Gadefait

INSA Toulouse.

What it does:
    Simulates a water network over several days from a single EPANET file
    (Low_Demand.inp exported by interface.py). The day is cut into short
    quasi-steady WNTR segments joined by smooth (cosine) transitions; the
    demand follows a realistic 24h curve. Events can be scheduled at any
    (day, hour): leak, demand surge, broken sensor, and progressive pipe
    aging (the Hazen-Williams roughness ramps down over the run). Broken
    sensors are also read from the '; [BROKEN SENSOR]' markers of the .inp.
    Monitored pipes are exported to a '|'-separated CSV (HeMu-compatible)
    with 4 columns per pipe -- pressure, head loss, flow rate, friction --
    in both a noiseless (x_*) and a noisy (yc_*) version; missing samples
    and broken sensors are written as -1.0. A final figure showing the
    roughness impact on head loss is saved as Headloss_vs_Roughness.png.

What to modify (in __main__) and its effect:
    - nb_days               : number of simulated days (simulation length).
    - events                : list of event dicts. Common keys: type,
                              start_day/start_hour, end_day/end_hour.
                              * leak   -> nodes, coeff (breach size)
                              * surge  -> nodes, demand_L_s (extra demand)
                              * broken -> nodes (sensor dropout, NaN)
                              * aging  -> pipes ([] = all), start_roughness,
                                target_roughness (C ramps between the two)
    - TARGET_PIPES          : pipes monitored and written to the CSV.
    - temp_inp / csv_file   : input network (.inp) and output CSV paths.
    - NAN_PERCENTAGE        : % of randomly missing samples (0.0 = none).
    - segment_duration_h    : WNTR segment length in hours (0.05 = 3 min).
                              Smaller -> smoother curves but slower simulation.
    - transition_duration_s : duration of the cosine fade between segments.
    - peak_demand_L_s       : auto-computed (0.5 L/s per house); raise it to
                              stress the network, lower it for flatter curves.
    - sigma_pressure / sigma_velocity (run_segment defaults): sensor noise
                              standard deviations (bar, m/s).

Improvements vs Infinite_Simulator.py:
 1. Continuous 24h demand curve (no binary High/Low switching)
 2. Gaussian sensor noise (fixed component + proportional to signal)
 3. Flow rate Q = v × A calculated at each time step
 4. NaNs preserved in CSV (broken sensors ≠ 0.0)
 5. Broken sensors = persistent failure (no random drops per sample)
 6. No _leak/_surge files required (events injected dynamically)
 7. Enriched CSV export: flow rate, continuous demand multiplier, events on each row
 8. Fine temporal resolution (30 min segments instead of multi-hour blocks)
 9. Realistic default values (leaks, surges, noise)
10. Only one INP file needed (Low_Demand.inp)
"""

import warnings

warnings.filterwarnings("ignore")
import wntr
import numpy as np
import json
import os
import math
import time
import tempfile
import itertools

# ── Temporary wntr files outside synced folder (OneDrive) ──
# EpanetSimulator.run_sim() writes temp.inp/.rpt/.bin to the default CWD.
# On a synced folder (Desktop/OneDrive) + tight loop, an external lock
# causes intermittent OSError [Errno 22]. So we redirect
# to %TEMP% with a unique name per call.
_run_counter = itertools.count()


def _epanet_prefix():
    """Unique prefix in the system temp (outside OneDrive) for wntr files."""
    return os.path.join(
        tempfile.gettempdir(), f"wntr_{os.getpid()}_{next(_run_counter)}"
    )


def _run_sim_safe(sim, retries=3, delay=0.2):
    """Executes sim.run_sim() to a unique temp prefix, with retry on OSError."""
    for attempt in range(retries):
        try:
            return sim.run_sim(file_prefix=_epanet_prefix())
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


# ── Compatibility patch TSNet / WNTR ──────────────────────────
import wntr.utils.check_values as _wntr_check
import wntr.network.elements as _wntr_elements

_original_check = _wntr_check._check_positive_non_zero_float


def _check_non_negative_float(value, property_name):
    if property_name == "Pipe roughness":
        value = float(value)
        return max(0.0, value)
    return _original_check(value, property_name)


_wntr_elements._check_positive_non_zero_float = _check_non_negative_float

# ==============================================================
# 1. REALISTIC DEMAND CURVE (24H)
# ==============================================================
# Normalized values (max = 1.0) based on
# What is hidden behind water consumption curves? The example of Paris by Agathe Euzen (HAL Id: hal-00686872)
# The value 1.0 corresponds to peak_demand_L_s in the config.

DEMAND_CURVE_24H = [
    0.17,  # 0h  — deep night
    0.14,  # 1h
    0.11,  # 2h  — nocturnal minimum
    0.11,  # 3h
    0.14,  # 4h
    0.20,  # 5h  — early awakenings
    0.44,  # 6h  — morning rise
    0.83,  # 7h  — morning peak (showers, breakfast)
    1.00,  # 8h  — morning max peak
    0.85,  # 9h  — post-morning drop
    0.75,  # 10h — mid-morning
    0.65,  # 11h
    0.60,  # 12h — noon peak (lunch)
    0.57,  # 13h
    0.53,  # 14h — early afternoon
    0.50,  # 15h — afternoon trough
    0.48,  # 16h
    0.53,  # 17h — evening rise
    0.60,  # 18h — evening peak (cooking, showers)
    0.70,  # 19h — evening max peak
    0.69,  # 20h — gradual drop
    0.50,  # 21h
    0.40,  # 22h
    0.35,  # 23h — night
]


def get_demand_multiplier(hour):
    """
    Returns the demand multiplier for a given hour (0.0–24.0).
    Cosine interpolation to avoid abrupt transitions.
    """
    h = hour % 24.0
    h_floor = int(h) % 24
    h_ceil = (h_floor + 1) % 24
    frac = h - int(h)
    # Cosine interpolation (smoother than linear)
    t = (1 - math.cos(frac * math.pi)) / 2.0
    return DEMAND_CURVE_24H[h_floor] * (1 - t) + DEMAND_CURVE_24H[h_ceil] * t


# ==============================================================
# 2. EVENT APPLICATION (LEAKS, SURGES, BROKEN)
# ==============================================================


def apply_active_events(wn, active_events):
    """
    Applies active events to the WNTR network in memory.
    - leak  : emitter_coefficient on the node (uncontrolled leak)
    - surge : addition of extra demand (overconsumption)
    - broken: marking for sensor data removal
    """
    leak_nodes = {}
    broken_sensors = set()
    surge_nodes = set()

    for ev in active_events:
        if ev["type"] == "leak":
            coeff_target = ev.get("coeff", 0.75)
            # mode "instant"  : full coeff for the whole window (default)
            # mode "progressive": coeff ramps from start_coeff -> coeff over the window
            #   (progress is injected per segment, same mechanism as aging)
            if ev.get("mode", "instant") == "progressive":
                start_coeff = ev.get("start_coeff", 0.0)
                progress = ev.get("progress", 1.0)
                coeff = start_coeff + (coeff_target - start_coeff) * progress
            else:
                coeff = coeff_target
            # Conversion of the emitter coefficient (Epanet) to leak area (WNTR)
            # q = C * p^0.5 (Epanet) <=> q = Cd * A * sqrt(2g) * p^0.5 (WNTR)
            # A = C / (Cd * sqrt(2g)) = coeff / (0.75 * 4.4294) = coeff / 3.322
            area_wntr = coeff / 3.322
            for node_id in ev.get("nodes", []):
                leak_nodes[node_id] = coeff
                target_node = None
                if node_id.startswith("P") and node_id in wn.link_name_list:
                    pipe = wn.get_link(node_id)
                    target_node = wn.get_node(pipe.start_node_name)
                else:
                    try:
                        target_node = wn.get_node(node_id)
                    except Exception:
                        pass

                if target_node:
                    # For EpanetSimulator (which ignores add_leak but uses emitter_coefficient)
                    target_node.emitter_coefficient = coeff
                    # For WNTRSimulator (which ignores emitter_coefficient but uses add_leak)
                    # start_time=0 is necessary for the leak to be active!
                    target_node.add_leak(
                        wn, area=area_wntr, discharge_coeff=0.75, start_time=0
                    )

        elif ev["type"] == "surge":
            demand_L_s = ev.get("demand_L_s", 5.0)
            demand_m3s = demand_L_s / 1000.0
            for node_id in ev.get("nodes", []):
                surge_nodes.add(node_id)
                try:
                    node = wn.get_node(node_id)
                    if hasattr(node, "demand_timeseries_list"):
                        if len(node.demand_timeseries_list) > 0:
                            node.demand_timeseries_list[0].base_value += demand_m3s
                        else:
                            node.add_demand(demand_m3s, None)
                except Exception:
                    pass

        elif ev["type"] == "broken":
            for node_id in ev.get("nodes", []):
                broken_sensors.add(node_id)

        elif ev["type"] == "aging":
            progress = ev.get("progress", 1.0)
            target = ev.get("target_roughness", 80.0)
            start_r = ev.get("start_roughness", 130.0)
            current_r = start_r + (target - start_r) * progress

            pipes = ev.get("pipes", [])
            for pipe_name, pipe in wn.links():
                if not pipes or pipe_name in pipes:
                    if hasattr(pipe, "roughness"):
                        pipe.roughness = current_r

    return leak_nodes, list(broken_sensors), list(surge_nodes)


# ==============================================================
# 3. REALISTIC SENSOR NOISE (GAUSSIAN)
# ==============================================================


def add_sensor_noise(values, sigma_base, sigma_proportional=0.00005):
    """
    Realistic Gaussian noise model:
      noise = N(0, sigma_base) + signal * N(0, sigma_proportional)

    - sigma_base       : constant background noise of the sensor (e.g., 0.005 bar)
    - sigma_proportional : relative error (e.g., 1% = 0.01)
    """
    n = len(values)
    noise_fixed = np.random.normal(0, sigma_base, n)
    noise_prop = values * np.random.normal(0, sigma_proportional, n)
    return values + noise_fixed + noise_prop


def apply_random_nans(array, nan_percentage):
    """Randomly applies NaN values (missing data)."""
    if nan_percentage > 0:
        mask = np.random.rand(len(array)) < (nan_percentage / 100.0)
        array[mask] = np.nan
    return array


def hw_headloss(q, roughness, length, diameter):
    """
    Hazen-Williams friction head loss (mH2O) from flow rate q (m3/s).

    h = 10.67 * L * |Q|^1.852 / (C^1.852 * D^4.87)

    Computed the same way for every engine (WNTRSimulator does not expose a
    'headloss' result), so segments and transitions stay consistent. It depends
    explicitly on the roughness coefficient C, so pipe aging shows up on the
    curve. Returns a positive magnitude (a loss).
    """
    C = max(float(roughness), 1e-6)
    D = max(float(diameter), 1e-6)
    L = max(float(length), 0.0)
    q = np.asarray(q, dtype=float)
    return 10.67 * L * np.abs(q) ** 1.852 / (C**1.852 * D**4.87)


# ==============================================================
# 4. NETWORK PREPARATION
# ==============================================================


def prepare_network(wn):
    """
    Common corrections applied to the network before simulation:
    - Pipes to houses (M) : 20mm diameter
    - Pipes too small : 100mm minimum diameter
    - Invalid H-W roughness : corrected to 130 (new PVC)
    """
    # Force water towers to be at least 10 m (1 bar) above the network to let variations be seen
    max_elev = max(
        [n.elevation for name, n in wn.nodes() if hasattr(n, "elevation")] + [0]
    )
    for name, node in wn.nodes():
        if node.node_type in ["Reservoir", "Tank"]:
            if getattr(node, "base_head", 0) < max_elev + 10:
                node.base_head = max_elev + 10

    for pipe_name, pipe in wn.links():
        if pipe.link_type == "Pipe":
            if pipe.start_node_name.startswith("M") or pipe.end_node_name.startswith(
                "M"
            ):
                pipe.diameter = 0.02
    for link_name, link in wn.links():
        if (
            hasattr(link, "roughness")
            and wn.options.hydraulic.headloss == "H-W"
            and link.roughness < 1.0
        ):
            link.roughness = 130.0


def apply_demand_curve(wn, hour, peak_demand_L_s=200.0):
    """
    Applies the realistic demand curve to the network nodes.
    - For J nodes : the total peak demand is distributed.
    - For M nodes (houses) : the daily variation is applied to their base demand.

    Returns the demand multiplier used.
    """
    multiplier = get_demand_multiplier(hour)

    j_nodes = [name for name, _ in wn.junctions() if name.startswith("J")]
    m_nodes = [name for name, _ in wn.junctions() if name.startswith("M")]

    # 1. J nodes (dynamic peak load distribution)
    if j_nodes:
        extra_per_node_m3s = (peak_demand_L_s / 1000.0) * multiplier / len(j_nodes)
        for name in j_nodes:
            node = wn.get_node(name)
            if len(node.demand_timeseries_list) > 0:
                node.demand_timeseries_list[0].base_value += extra_per_node_m3s

    # 2. M nodes (Houses : following the daily cycle)
    for name in m_nodes:
        node = wn.get_node(name)
        if len(node.demand_timeseries_list) > 0:
            # We apply the multiplier to the base demand of the .inp file
            node.demand_timeseries_list[0].base_value *= multiplier

    return multiplier


# ==============================================================
# 5. WNTR SIMULATION SEGMENT
# ==============================================================


def run_segment(
    inp_file,
    duration,
    state_file,
    chosen_pipes,
    hour_of_day,
    active_events=None,
    peak_demand_L_s=200.0,
    sigma_pressure=0.0001,
    sigma_velocity=0.00002,
    sigma_headloss=0.02,
    nan_percentage=0.0,
):
    """
    Executes a quasi-steady simulation segment with WNTR.

    Parameters:
      inp_file         : base .inp file (Low_Demand.inp)
      duration         : segment duration in seconds
      state_file       : JSON state file for continuity
      chosen_pipes     : list of pipes to monitor
      hour_of_day      : real time (0–24) for the demand curve
      active_events    : list of active events
      peak_demand_L_s  : peak demand of the network (L/s)
      sigma_pressure   : standard deviation of pressure noise (bar)
      sigma_velocity   : standard deviation of velocity noise (m/s)
    """
    if active_events is None:
        active_events = []

    wn = wntr.network.WaterNetworkModel(inp_file)

    # Restore previous state (inter-segment continuity)
    offset_time = 0.0
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            state = json.load(f)
            offset_time = state["time"]
            for name, node in wn.nodes():
                if node.node_type in ["Reservoir", "Tank"]:
                    if name in state["nodes_head"]:
                        node.base_head = state["nodes_head"][name]

    # Prepare the network
    prepare_network(wn)

    # Apply continuous demand curve
    demand_mult = apply_demand_curve(wn, hour_of_day, peak_demand_L_s)

    # Apply active events
    leak_nodes, broken_sensors, surge_nodes = apply_active_events(wn, active_events)

    # Time configuration
    wn.options.time.duration = duration
    wn.options.time.hydraulic_timestep = min(60, duration)
    wn.options.time.report_timestep = min(60, duration)

    # Simulation
    try:
        sim = wntr.sim.WNTRSimulator(wn)
        results = sim.run_sim()
    except Exception as e:
        print(f"  WNTRSimulator failed ({e}), fallback EpanetSimulator")
        sim = wntr.sim.EpanetSimulator(wn)
        results = _run_sim_safe(sim)

    # Results extraction
    timestamps = results.node["pressure"].index.values
    shifted_time = timestamps + offset_time
    n = len(shifted_time)

    res = {"time": shifted_time, "pipes": {}, "demand_multiplier": demand_mult}

    for pipe_id in chosen_pipes:
        try:
            pipe = wn.get_link(pipe_id)
        except Exception:
            continue

        start_node = pipe.start_node_name
        end_node = pipe.end_node_name

        # ── Pressure (mH2O → bar) + Gaussian noise ──
        p_start_raw = results.node["pressure"].loc[:, start_node].values / 10.197
        p_end_raw = results.node["pressure"].loc[:, end_node].values / 10.197
        p_start = apply_random_nans(
            add_sensor_noise(p_start_raw, sigma_pressure), nan_percentage
        )
        p_end = apply_random_nans(
            add_sensor_noise(p_end_raw, sigma_pressure), nan_percentage
        )

        # ── Flow rate (m³/s) directly from WNTR ──
        q_raw = results.link["flowrate"].loc[:, pipe_id].values

        # ── Velocity + correct sign + Gaussian noise ──
        # In WNTR, velocity is absolute, we give it the sign of the flow rate
        v_raw = results.link["velocity"].loc[:, pipe_id].values * np.sign(q_raw + 1e-9)
        v_start = apply_random_nans(
            add_sensor_noise(v_raw, sigma_velocity), nan_percentage
        )
        v_end = apply_random_nans(
            add_sensor_noise(v_raw, sigma_velocity), nan_percentage
        )
        velocity = apply_random_nans(
            add_sensor_noise(v_raw, sigma_velocity), nan_percentage
        )

        area = np.pi * (pipe.diameter / 2) ** 2
        sigma_flowrate = sigma_velocity * area
        flowrate = apply_random_nans(
            add_sensor_noise(q_raw, sigma_flowrate), nan_percentage
        )

        # ── Head loss (mH2O) via Hazen-Williams from flow + current roughness ──
        # WNTRSimulator exposes no 'headloss'; computing it here keeps segments
        # and transitions consistent and makes the roughness impact visible.
        h_loss_raw = hw_headloss(q_raw, pipe.roughness, pipe.length, pipe.diameter)
        # Proportional noise (fraction sigma_headloss) + a resolution floor kept
        # well below the signal: this head loss is a ~1e-6 mH2O signal, so a 1e-6
        # floor gave a signal-to-noise ratio of 1 and even negative head losses.
        headloss = apply_random_nans(
            add_sensor_noise(h_loss_raw, 1e-9, sigma_proportional=sigma_headloss),
            nan_percentage,
        )

        # ── Roughness coefficient C (Hazen-Williams) ──
        # Reported consistently across engines: WNTRSimulator exposes no
        # friction_factor and EpanetSimulator reports a Darcy-scale value, so
        # we always store the pipe roughness C (which the aging fault drives).
        f_raw = np.full(len(q_raw), getattr(pipe, "roughness", 0.0), dtype=float)
        friction = apply_random_nans(add_sensor_noise(f_raw, 0.0005), nan_percentage)

        # -- Broken sensors : persistent failure (all NaN)--
        # -- Demand (Outflow at nodes) --
        d_start_raw = results.node["demand"].loc[:, start_node].values
        d_end_raw = results.node["demand"].loc[:, end_node].values
        d_start = np.copy(d_start_raw)
        d_end = np.copy(d_end_raw)

        if start_node in broken_sensors:
            p_start[:] = np.nan
            d_start[:] = np.nan
        if end_node in broken_sensors:
            p_end[:] = np.nan
            d_end[:] = np.nan
        if pipe_id in broken_sensors:
            velocity[:] = np.nan
            v_start[:] = np.nan
            v_end[:] = np.nan
            flowrate[:] = np.nan
            headloss[:] = np.nan
            friction[:] = np.nan

        res["pipes"][pipe_id] = {
            "x_pressure": p_start_raw,
            "yc_pressure": p_start,
            "x_demand": d_start_raw,
            "yc_demand": d_start,
            "x_velocity": v_raw,
            "yc_velocity": velocity,
            "x_flowrate": q_raw,
            "yc_flowrate": flowrate,
            "x_headloss": h_loss_raw,
            "yc_headloss": headloss,
            "x_friction": f_raw,
            "yc_friction": friction,
            "start_node": start_node,
            "end_node": end_node,
        }

    # ── Drop the boundary sample when continuing a run ──
    # The block that ran before this one already emitted that instant (it saved
    # it as its final state), so keeping it duplicates a timestamp in the CSV.
    if offset_time > 0 and n > 1:
        res["time"] = res["time"][1:]
        for data in res["pipes"].values():
            for key, arr in data.items():
                if isinstance(arr, np.ndarray):
                    data[key] = arr[1:]

    # Save state for next segment
    new_state = {
        "time": float(shifted_time[-1]),
        "nodes_head": results.node["head"].iloc[-1].to_dict(),
        "nodes_pressure": results.node["pressure"].iloc[-1].to_dict(),
        "nodes_demand": results.node["demand"].iloc[-1].to_dict(),
        "links_velocity": results.link["velocity"].iloc[-1].to_dict(),
        "links_flowrate": results.link["flowrate"].iloc[-1].to_dict(),
        "links_friction": (
            results.link["friction_factor"].iloc[-1].to_dict()
            if "friction_factor" in results.link
            else {}
        ),
    }
    with open(state_file, "w") as f:
        json.dump(new_state, f, indent=4)

    faults = {
        "leak_nodes": leak_nodes,
        "broken_sensors": broken_sensors,
        "surge_nodes": surge_nodes,
    }
    return res, faults


# ==============================================================
# 6. SMOOTH TRANSITION BETWEEN SEGMENTS
# ==============================================================


def run_transition(
    inp_file,
    duration,
    state_file,
    chosen_pipes,
    hour_of_day,
    active_events=None,
    peak_demand_L_s=200.0,
    sigma_pressure=0.0001,
    sigma_velocity=0.00002,
    sigma_headloss=0.02,
    nan_percentage=0.0,
):
    """
    Smooth transition between two demand levels.
    Interpolates between current state and target state (cosine fade).
    Typical duration: 60 seconds.
    """
    if active_events is None:
        active_events = []

    state = None
    offset_time = 0.0
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            state = json.load(f)
            offset_time = state["time"]

    # ── Calculate target state (network with new demand) ──
    wn_target = wntr.network.WaterNetworkModel(inp_file)
    if state:
        for name, node in wn_target.nodes():
            if node.node_type in ["Reservoir", "Tank"]:
                if name in state["nodes_head"]:
                    node.base_head = state["nodes_head"][name]

    prepare_network(wn_target)
    demand_mult = apply_demand_curve(wn_target, hour_of_day, peak_demand_L_s)
    leak_nodes, broken_sensors, surge_nodes = apply_active_events(
        wn_target, active_events
    )

    wn_target.options.time.duration = 10
    wn_target.options.time.hydraulic_timestep = 10
    wn_target.options.time.report_timestep = 10

    sim = wntr.sim.EpanetSimulator(wn_target)
    target_res = _run_sim_safe(sim)

    target_p = target_res.node["pressure"].iloc[-1].to_dict()
    target_v = target_res.link["velocity"].iloc[-1].to_dict()
    target_hl = target_res.link["headloss"].iloc[-1].to_dict()
    target_h = target_res.node["head"].iloc[-1].to_dict()
    target_d = target_res.node["demand"].iloc[-1].to_dict()
    target_q = target_res.link["flowrate"].iloc[-1].to_dict()
    target_ff = (
        target_res.link["friction_factor"].iloc[-1].to_dict()
        if "friction_factor" in target_res.link
        else {}
    )

    # ── Cosine interpolation ──
    dt = 1.0  # 1 second resolution for the transition
    n_steps = max(1, int(duration / dt))
    # Start one dt after the saved state: that instant was already emitted by the
    # segment that just ran, so starting at offset_time would duplicate it.
    shifted_time = [offset_time + (i + 1) * dt for i in range(n_steps)]
    fade = (1 - np.cos(np.linspace(0, np.pi, n_steps))) / 2.0

    res = {"time": shifted_time, "pipes": {}, "demand_multiplier": demand_mult}

    for pipe_id in chosen_pipes:
        try:
            pipe = wn_target.get_link(pipe_id)
        except Exception:
            continue

        start_node = pipe.start_node_name
        end_node = pipe.end_node_name

        # Initial values (from saved state, in mH2O)
        p_s_i = (
            state["nodes_pressure"].get(start_node, 0)
            if state
            else target_p.get(start_node, 0)
        )
        p_e_i = (
            state["nodes_pressure"].get(end_node, 0)
            if state
            else target_p.get(end_node, 0)
        )
        v_i = (
            state["links_velocity"].get(pipe_id, 0)
            if state
            else target_v.get(pipe_id, 0)
        )

        # Final values (target state, in mH2O)
        p_s_f = target_p.get(start_node, p_s_i)
        p_e_f = target_p.get(end_node, p_e_i)
        v_f = target_v.get(pipe_id, v_i)

        # Headloss
        hl_i = (
            state["links_headloss"].get(pipe_id, 0)
            if state and "links_headloss" in state
            else target_hl.get(pipe_id, 0)
        )
        hl_f = target_hl.get(pipe_id, hl_i)

        # Interpolation mH2O → conversion bar → Gaussian noise
        p_start_raw = (p_s_i + (p_s_f - p_s_i) * fade) / 10.197
        p_end_raw = (p_e_i + (p_e_f - p_e_i) * fade) / 10.197
        p_start = apply_random_nans(
            add_sensor_noise(p_start_raw, sigma_pressure), nan_percentage
        )
        p_end = apply_random_nans(
            add_sensor_noise(p_end_raw, sigma_pressure), nan_percentage
        )

        # Interpolated flow rate
        q_i = (
            state["links_flowrate"].get(pipe_id, target_q.get(pipe_id, 0))
            if state and "links_flowrate" in state
            else target_q.get(pipe_id, 0)
        )
        q_f = target_q.get(pipe_id, q_i)
        q_interp = q_i + (q_f - q_i) * fade
        area = np.pi * (pipe.diameter / 2) ** 2
        sigma_flowrate = sigma_velocity * area
        flowrate = apply_random_nans(
            add_sensor_noise(q_interp, sigma_flowrate), nan_percentage
        )

        # Interpolated velocity with independent noise and respected sign
        v_interp = (v_i + (v_f - v_i) * fade) * np.sign(q_interp + 1e-9)
        v_start = apply_random_nans(
            add_sensor_noise(v_interp, sigma_velocity), nan_percentage
        )
        v_end = apply_random_nans(
            add_sensor_noise(v_interp, sigma_velocity), nan_percentage
        )
        velocity = apply_random_nans(
            add_sensor_noise(v_interp, sigma_velocity), nan_percentage
        )

        # Head loss (mH2O) via Hazen-Williams from the interpolated flow +
        # current roughness (same formula as run_segment, engine-consistent).
        hl_interp = hw_headloss(q_interp, pipe.roughness, pipe.length, pipe.diameter)
        # Proportional noise (same convention and same floor as run_segment).
        headloss = apply_random_nans(
            add_sensor_noise(hl_interp, 1e-9, sigma_proportional=sigma_headloss),
            nan_percentage,
        )

        # Roughness coefficient C (Hazen-Williams) — same convention as
        # run_segment (constant across the transition), engine-consistent.
        f_interp = np.full(n_steps, getattr(pipe, "roughness", 0.0), dtype=float)
        friction = apply_random_nans(add_sensor_noise(f_interp, 0.0005), nan_percentage)

        # Broken sensors
        # ── Demand (Outflow at nodes) ──
        d_s_i = (
            state["nodes_demand"].get(start_node, 0)
            if state and "nodes_demand" in state
            else target_d.get(start_node, 0)
        )
        d_e_i = (
            state["nodes_demand"].get(end_node, 0)
            if state and "nodes_demand" in state
            else target_d.get(end_node, 0)
        )
        d_s_f = target_d.get(start_node, d_s_i)
        d_e_f = target_d.get(end_node, d_e_i)

        # We don't necessarily need noise for demand, but we can interpolate it
        d_start_raw = d_s_i + (d_s_f - d_s_i) * fade
        d_end_raw = d_e_i + (d_e_f - d_e_i) * fade
        d_start = np.copy(d_start_raw)
        d_end = np.copy(d_end_raw)

        if (
            start_node in broken_sensors
            or end_node in broken_sensors
            or pipe_id in broken_sensors
        ):
            p_start[:] = np.nan
            d_start[:] = np.nan
            velocity[:] = np.nan
            flowrate[:] = np.nan
            headloss[:] = np.nan
            friction[:] = np.nan

        res["pipes"][pipe_id] = {
            "x_pressure": p_start_raw,
            "yc_pressure": p_start,
            "x_demand": d_start_raw,
            "yc_demand": d_start,
            "x_velocity": v_interp,
            "yc_velocity": velocity,
            "x_flowrate": q_interp,
            "yc_flowrate": flowrate,
            "x_headloss": hl_interp,
            "yc_headloss": headloss,
            "x_friction": f_interp,
            "yc_friction": friction,
            "start_node": start_node,
            "end_node": end_node,
        }

    # Save target state
    new_state = {
        "time": float(shifted_time[-1]),
        "nodes_head": target_h,
        "nodes_pressure": target_p,
        "nodes_demand": target_d,
        "links_velocity": target_v,
        "links_headloss": target_hl,
        "links_flowrate": target_q,
        "links_friction": target_ff,
    }
    with open(state_file, "w") as f:
        json.dump(new_state, f, indent=4)

    faults = {
        "leak_nodes": leak_nodes,
        "broken_sensors": broken_sensors,
        "surge_nodes": surge_nodes,
    }
    return res, faults


# ==============================================================
# 7. REALISTIC SCENARIO GENERATION
# ==============================================================


def get_abs_time(day, hour):
    """
    Converts (day, hour) into absolute simulation time (hours).

    The run starts on day 1 at 07:00, so t=0 is (day=1, hour=7.0). Wall-clock
    hours before 07:00 map to a negative time on day 1 (i.e. before the run
    starts) rather than being wrapped forward a day: wrapping used to push an
    event declared at "day 1, 00:00" to t=17h, eating the first third of a
    short run.
    """
    return (day - 1) * 24.0 + (hour - 7.0)


def generate_realistic_scenario(
    base_dir,
    nb_days,
    events,
    inp_file,
    segment_duration_h=0.5,
    transition_duration_s=60,
):
    """
    Generates a realistic simulation schedule.

    Instead of switching between High_Demand.inp and Low_Demand.inp,
    we use ONLY ONE INP file (Low_Demand.inp) and we continuously vary
    the demand via the 24h curve.

    Parameters:
      nb_days             : number of simulation days
      events              : list of events [{type, start_day, start_hour, ...}]
      inp_file            : base .inp file
      segment_duration_h  : duration of a WNTR segment (hours, default 0.5 = 30 min)
      transition_duration_s : duration of a transition (seconds, default 60)
    """

    segments_per_day = int(24.0 / segment_duration_h)
    total_segments = nb_days * segments_per_day
    segment_duration_s = int(segment_duration_h * 3600)

    def active_events_for(win_start, win_end):
        """
        Events overlapping the [win_start, win_end] window, each carrying its
        progress ratio (0 -> 1) when it is a ramping event.

        'aging' is irreversible: once started it stays applied until the end of
        the run, with progress saturated at 1.0. The network is rebuilt from the
        .inp at every step, so an event that stops being reported makes the pipe
        silently jump back to its original roughness (a pipe cannot un-age).
        """
        active = []
        for ev in events:
            ev_start = get_abs_time(ev["start_day"], ev["start_hour"])
            ev_end = get_abs_time(ev["end_day"], ev["end_hour"])
            permanent = ev["type"] == "aging"
            if ev_start < win_end and (permanent or ev_end > win_start):
                active_ev = ev.copy()
                if active_ev["type"] in ("aging", "leak"):
                    progress = (win_start - ev_start) / max(1e-9, ev_end - ev_start)
                    active_ev["progress"] = max(0.0, min(1.0, progress))
                active.append(active_ev)
        return active

    steps = []

    for seg_idx in range(total_segments):
        abs_time_h = seg_idx * segment_duration_h
        real_hour = (7.0 + abs_time_h) % 24.0

        # Which events are active during this segment?
        seg_start = abs_time_h
        seg_end = abs_time_h + segment_duration_h
        active = active_events_for(seg_start, seg_end)

        # WNTR Step (main segment)
        wntr_dur = segment_duration_s - transition_duration_s
        steps.append(
            {
                "inp": inp_file,
                "engine": "wntr",
                "duration": wntr_dur,
                "hour": real_hour,
                "events": active,
            }
        )

        # Transition step (to the next segment)
        next_hour = (7.0 + (seg_idx + 1) * segment_duration_h) % 24.0
        next_start = seg_end
        next_end = seg_end + segment_duration_h
        next_active = active_events_for(next_start, next_end)

        steps.append(
            {
                "inp": inp_file,
                "engine": "transition",
                "duration": transition_duration_s,
                "hour": next_hour,
                "events": next_active,
            }
        )

    return steps


# ==============================================================
# 8. ENRICHED CSV EXPORT
# ==============================================================


def append_to_csv(
    csv_filename,
    results,
    active_faults,
    chosen_pipes,
    is_first_step,
    demand_multiplier=1.0,
    peak_demand=1.0,
):
    """
    Enriched CSV export:
    - Separator: pipe |
    - NaNs preserved (not replaced by 0.0)
    - Flow rate column added
    - uc_demand = continuous multiplier (0.0–1.0)
    - ud_event = active events on EACH row
    - demand = total demand of the network in L/s
    """
    active_events_list = []
    for node in active_faults.get("leak_nodes", {}):
        active_events_list.append(f"f_leak_{node}")
    for node in active_faults.get("broken_sensors", []):
        active_events_list.append(f"f_broken_{node}")
    for node in active_faults.get("surge_nodes", []):
        active_events_list.append(f"f_surge_{node}")
    active_events_list.sort()
    events_str = ",".join(active_events_list) if active_events_list else "nominal"

    mode = "w" if is_first_step else "a"
    os.makedirs(os.path.dirname(csv_filename), exist_ok=True)

    with open(csv_filename, mode) as f:
        if is_first_step:
            cols = ["t", "uc_0", "m"]

            x_cols = [f"x_{i}" for i in range(len(chosen_pipes) * 4)]
            yc_cols = [f"yc_{i}" for i in range(len(chosen_pipes) * 4)]

            cols.extend(x_cols)
            cols.append("h_0")
            cols.extend(yc_cols)
            cols.extend(["yd", "ud", "demand"])

            f.write("|".join(cols) + "\n")

        demand_L_s = peak_demand * demand_multiplier

        for t_idx, t_val in enumerate(results["time"]):
            row_start = [
                f"{t_val:.1f}",
                f"{demand_multiplier:.4f}",
                "on",  # m
            ]

            row_x = []
            row_yc = []
            for pid in chosen_pipes:
                if pid in results["pipes"]:
                    data = results["pipes"][pid]
                    x_p = data["x_pressure"][t_idx]
                    yc_p = data["yc_pressure"][t_idx]
                    # Head loss (mH2O) replaces velocity in the export
                    x_hl = data["x_headloss"][t_idx]
                    yc_hl = data["yc_headloss"][t_idx]
                    x_q = data["x_flowrate"][t_idx] * 1000
                    yc_q = data["yc_flowrate"][t_idx] * 1000
                    x_f = data["x_friction"][t_idx]
                    yc_f = data["yc_friction"][t_idx]

                    # Set -1.0 if NaN
                    row_x.append("-1.0" if np.isnan(x_p) else f"{x_p:.4f}")
                    # Head loss runs down to ~1e-6 mH2O on a lightly loaded pipe:
                    # 6 decimals quantised it to 3 distinct values (a flat zero
                    # line), so it is exported with 9 decimals.
                    row_x.append("-1.0" if np.isnan(x_hl) else f"{x_hl:.9f}")
                    row_x.append("-1.0" if np.isnan(x_q) else f"{x_q:.8f}")
                    row_x.append("-1.0" if np.isnan(x_f) else f"{x_f:.6f}")

                    row_yc.append("-1.0" if np.isnan(yc_p) else f"{yc_p:.4f}")
                    row_yc.append("-1.0" if np.isnan(yc_hl) else f"{yc_hl:.9f}")
                    row_yc.append("-1.0" if np.isnan(yc_q) else f"{yc_q:.8f}")
                    row_yc.append("-1.0" if np.isnan(yc_f) else f"{yc_f:.6f}")
                else:
                    row_x.extend(["-1.0"] * 4)
                    row_yc.extend(["-1.0"] * 4)

            yd_val = "yes" if events_str != "nominal" else "no"
            ud_val = events_str if events_str != "nominal" else "no"

            row = (
                row_start
                + row_x
                + ["0"]
                + row_yc
                + [yd_val, ud_val, f"{demand_L_s:.4f}"]
            )

            f.write("|".join(row) + "\n")


# ==============================================================
# 9. MAIN
# ==============================================================

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # ── SCENARIO CONFIGURATION ──────────────────────────────
    import random

    # Reproducibility: an int gives an identical dataset every run
    # (noise, missing-data NaNs, any random draw); set to None for fresh randomness.
    SEED = 42
    if SEED is not None:
        np.random.seed(SEED)
        random.seed(SEED)

    nb_days = 6
    NAN_PERCENTAGE = 5.0  # Set 0.0 to disable, 5.0 for 5% NaN data (missing)
    events = [
        # Leak on P15 : Day 2 18:30 → Day 4 20:00
        {
            "type": "leak",
            "start_day": 2,
            "start_hour": 18.5,
            "end_day": 4,
            "end_hour": 20.0,
            "nodes": ["P15"],
            "coeff": 0.2,  # final emitter coefficient (leak severity)
            # ── Leak shape ──────────────────────────────────────────────
            # 'mode': 'instant'      -> full 'coeff' for the whole window (default)
            # 'mode': 'progressive'  -> coeff grows from 'start_coeff' to 'coeff'
            #                           over the window (crack slowly opening up)
            "mode": "instant",
            "start_coeff": 0.0,  # only used when mode == 'progressive'
        },
        # # Leak on P23 : Day 4 at 09:30 → Day 4 at 14:00
        # {
        #     'type': 'leak',
        #     'start_day': 4, 'start_hour': 9.5,
        #     'end_day': 4, 'end_hour': 14.0,
        #     'nodes': ['P23'],
        #     'coeff': 0.2,  # Big leak (~532 L/s) -> strong network depression
        # }
        # # Overconsumption on M236 : Day 1 from 10:00 to 14:00
        # {
        #     'type': 'surge',
        #     'start_day': 1, 'start_hour': 18.0,
        #     'end_day': 1, 'end_hour': 10.0,
        #     'nodes': ['M236'],
        #     'demand_L_s': 5.0,  # 5 L/s overconsumption (realistic)
        # },
        # Progressive pipe aging (C ramps from 130.0 down to 50.0 over the run).
        # The run starts on day 1 at 07:00 and ends on day nb_days+1 at 07:00,
        # so this window covers it exactly; the aging then stays applied.
        {
            "type": "aging",
            "start_day": 1,
            "start_hour": 7.0,
            "end_day": nb_days + 1,
            "end_hour": 7.0,
            "pipes": [],  # Empty list = all pipes in the network
            "start_roughness": 130.0,
            "target_roughness": 50.0,
        },
    ]

    # ── PIPES TO OBSERVE (Leave empty [] for random) ──
    TARGET_PIPES = [
        "P76"
    ]  # Positive flow rate (~0 -> +6.3 L/s during leak). Alternatives: P47, P56, P52

    state_file = os.path.join(base_dir, "temp_state_realistic.json")
    csv_file = os.path.join(base_dir, "Network_Data", "Scenario_b", "Nominal_6d.csv")
    import wntr
    import random

    temp_inp = os.path.join(base_dir, "Scenarios", "Scenario 3", "Low_Demand.inp")

    # --- READING BROKEN SENSORS FROM THE INTERFACE ---
    broken_nodes_from_inp = []
    if os.path.exists(temp_inp):
        with open(temp_inp, "r", encoding="utf-8") as f:
            for line in f:
                if "; [BROKEN SENSOR]" in line:
                    parts = line.split("]")
                    if len(parts) > 1:
                        node_info = parts[1].split("(")[0].strip()
                        if node_info:
                            broken_nodes_from_inp.append(node_info)

    if broken_nodes_from_inp:
        events.append(
            {
                "type": "broken",
                "start_day": 1,
                "start_hour": 0.0,
                "end_day": nb_days + 1,
                "end_hour": 24.0,
                "nodes": broken_nodes_from_inp,
            }
        )

    wn_temp = wntr.network.WaterNetworkModel(temp_inp)
    all_p = list(wn_temp.pipe_name_list)

    # Make sure to observe at least one pipe with a broken sensor for the demo
    added_broken = 0
    for node in broken_nodes_from_inp:
        if added_broken >= 2:
            break
        for p_name, pipe in wn_temp.links():
            if pipe.start_node_name == node or pipe.end_node_name == node:
                if p_name not in TARGET_PIPES and p_name in all_p:
                    TARGET_PIPES.append(p_name)
                    added_broken += 1
                    break

    num_houses = sum(1 for name in wn_temp.junction_name_list if name.startswith("M"))
    peak_demand_L_s = max(
        5.0, num_houses * 0.5
    )  # Dynamic peak demand: 0.5 L/s per house

    segment_duration_h = 0.05  # 3 minute segment for very smooth curves
    transition_duration_s = 60  # 60 seconds transition

    # Pipe selection: first those requested, then complete randomly up to 5
    chosen_pipes = [p for p in TARGET_PIPES if p in all_p]
    remaining = max(0, 1 - len(chosen_pipes))
    # if remaining > 0:
    #     available_p = [p for p in all_p if p not in chosen_pipes]
    #     chosen_pipes.extend(random.sample(available_p, min(remaining, len(available_p))))

    # ── Clean previous state ──
    if os.path.exists(state_file):
        os.remove(state_file)

    # ── Scenario generation ──
    steps = generate_realistic_scenario(
        base_dir,
        nb_days,
        events,
        temp_inp,
        segment_duration_h=segment_duration_h,
        transition_duration_s=transition_duration_s,
    )

    total_wntr = sum(1 for e in steps if e["engine"] == "wntr")
    total_trans = sum(1 for e in steps if e["engine"] == "transition")
    print(f"+{'='*58}+")
    print(f"|         SIMULATION OVER {nb_days} DAYS                  |")
    print(f"+{'='*58}+")
    print(
        f"|  WNTR Segments    : {total_wntr:>4}  ({segment_duration_h}h each)              |"
    )
    print(
        f"|  Transitions      : {total_trans:>4}  ({transition_duration_s}s each)              |"
    )
    print(f"|  Peak Demand      : {peak_demand_L_s:>6.0f} L/s                        |")
    print(f"|  Events           : {len(events):>4}                                |")
    print(f"|  Pipes            : {', '.join(chosen_pipes):<30}    |")
    print(f"+{'='*58}+")

    for i, step in enumerate(steps):
        engine = step["engine"]
        duration = step["duration"]
        hour = step["hour"]
        active_events = step["events"]
        is_first = i == 0

        # Condensed display
        if i % 20 == 0 or active_events:
            mult = get_demand_multiplier(hour)
            ev_str = (
                f" <- [{','.join(e['type'] for e in active_events)}]"
                if active_events
                else ""
            )
            print(
                f"  [{i+1:>4}/{len(steps)}] {engine:>10} | {duration:>5}s | {hour:05.1f}h | mult={mult:.2f}{ev_str}"
            )

        if engine == "wntr":
            res, faults = run_segment(
                step["inp"],
                duration,
                state_file,
                chosen_pipes,
                hour,
                active_events,
                peak_demand_L_s,
                nan_percentage=NAN_PERCENTAGE,
            )
        elif engine == "transition":
            res, faults = run_transition(
                step["inp"],
                duration,
                state_file,
                chosen_pipes,
                hour,
                active_events,
                peak_demand_L_s,
                nan_percentage=NAN_PERCENTAGE,
            )

        demand_mult = res.get("demand_multiplier", 1.0)
        append_to_csv(
            csv_file, res, faults, chosen_pipes, is_first, demand_mult, peak_demand_L_s
        )

    print(f"\n{'='*60}")
    print(f"Simulation finished! Results in:")
    print(f"  {csv_file}")
    print(f"{'='*60}")

    # ── Final plot: impact of the roughness ("smoothing") coefficient on head loss ──
    # Head loss now lives in the x_1 / yc_1 columns (velocity was replaced).
    try:
        import csv as csv_mod
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MultipleLocator

        # 1. Read time (s -> h), head loss (clean x_1 + measured yc_1) and the
        #    roughness coefficient (clean x_3) from the CSV
        t_h, hl_clean, hl_meas, rough_csv = [], [], [], []
        with open(csv_file, "r") as f:
            reader = csv_mod.DictReader(f, delimiter="|")
            for row in reader:
                t_h.append(float(row["t"]) / 3600.0)
                xv = float(row.get("x_1", -1.0))
                yv = float(row.get("yc_1", -1.0))
                rv = float(row.get("x_3", -1.0))
                hl_clean.append(np.nan if xv == -1.0 else xv)
                hl_meas.append(np.nan if yv == -1.0 else yv)
                rough_csv.append(np.nan if rv == -1.0 else rv)
        t_h = np.array(t_h)
        hl_clean = np.array(hl_clean)
        hl_meas = np.array(hl_meas)
        rough_csv = np.array(rough_csv)

        # 2. Roughness coefficient C(t): plot what the simulation actually wrote
        #    (x_3) rather than a reconstruction, so the two panels cannot drift
        #    apart. Fall back on rebuilding it from the event if x_3 is missing.
        aging = next((e for e in events if e["type"] == "aging"), None)
        rough = None
        if np.isfinite(rough_csv).any():
            rough = rough_csv
        elif aging is not None:
            r0 = aging.get("start_roughness", 130.0)
            r1 = aging.get("target_roughness", 80.0)
            a_start = get_abs_time(aging["start_day"], aging["start_hour"])
            a_end = get_abs_time(aging["end_day"], aging["end_hour"])
            prog = np.clip((t_h - a_start) / max(1e-9, a_end - a_start), 0.0, 1.0)
            rough = r0 + (r1 - r0) * prog

        # 3. Leak window (highlighted band) from the leak event
        leak = next((e for e in events if e["type"] == "leak"), None)
        leak_span = None
        if leak is not None:
            leak_span = (
                get_abs_time(leak["start_day"], leak["start_hour"]),
                get_abs_time(leak["end_day"], leak["end_hour"]),
                ",".join(leak.get("nodes", [])),
            )

        # ── Figure: two stacked panels sharing the time axis (no dual y-scale) ──
        C_HL, C_HL_SOFT, C_ROUGH, C_LEAK = "#2563eb", "#93c5fd", "#d97706", "#dc2626"
        n_panels = 2 if rough is not None else 1
        fig, axes = plt.subplots(
            n_panels,
            1,
            sharex=True,
            figsize=(13, 7),
            gridspec_kw={"height_ratios": [2, 1][:n_panels], "hspace": 0.12},
        )
        axes = np.atleast_1d(axes)
        ax_hl = axes[0]

        # Top panel — head loss: noisy measurement behind, physical curve on top
        valid = ~np.isnan(hl_meas)
        if valid.any():
            ax_hl.plot(
                t_h,
                hl_meas,
                color=C_HL_SOFT,
                lw=0.8,
                label="Noisy measurement",
                zorder=1,
            )
        valid = ~np.isnan(hl_clean)
        ax_hl.plot(t_h, hl_clean, color=C_HL, lw=2.0, label="Head loss", zorder=2)
        ax_hl.set_ylabel("Head loss (mH2O)", fontweight="bold")
        # Log scale: the head loss spans ~5 decades (1e-8 mH2O on the nominal
        # trickle up to 1e-3 during the leak). On a linear axis the leak sets the
        # scale and flattens the whole aging ramp onto the zero line.
        ax_hl.set_yscale("log")
        ax_hl.legend(frameon=False, loc="upper left")

        # Bottom panel — roughness coefficient C(t)
        if rough is not None:
            ax_r = axes[1]
            ax_r.plot(t_h, rough, color=C_ROUGH, lw=2.0)
            ax_r.set_ylabel("Roughness\ncoefficient C (H-W)", fontweight="bold")
            fin = np.flatnonzero(np.isfinite(rough))
            r_first, r_last = rough[fin[0]], rough[fin[-1]]
            ax_r.annotate(
                f"C : {r_first:.0f} → {r_last:.0f}",
                xy=(t_h[fin[-1]], r_last),
                xytext=(-4, 8),
                textcoords="offset points",
                ha="right",
                color=C_ROUGH,
                fontweight="bold",
                fontsize=10,
            )

        # Highlight the leak window on every panel
        if leak_span is not None:
            ls, le, lnodes = leak_span
            for ax in axes:
                ax.axvspan(ls, le, color=C_LEAK, alpha=0.12, lw=0)
            ax_hl.axvspan(ls, le, color=C_LEAK, alpha=0.0, lw=0, label="_nolegend_")
            ymax = np.nanmax(hl_clean) if valid.any() else 1.0
            ax_hl.annotate(
                f"Leak {lnodes}",
                xy=((ls + le) / 2, ymax),
                ha="center",
                va="bottom",
                color=C_LEAK,
                fontweight="bold",
                fontsize=10,
            )

        # Cosmetics
        for ax in axes:
            ax.grid(True, color="#e5e7eb", lw=0.8)
            ax.set_axisbelow(True)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
        axes[-1].set_xlabel("Time (hours)", fontweight="bold")
        axes[-1].xaxis.set_major_locator(MultipleLocator(24))
        axes[-1].xaxis.set_minor_locator(MultipleLocator(6))
        axes[-1].set_xlim(t_h.min(), t_h.max())
        pipe_name = chosen_pipes[0] if chosen_pipes else "?"
        fig.suptitle(
            f"Impact of the roughness coefficient on head loss — {pipe_name}",
            fontsize=15,
            fontweight="bold",
        )
        fig.tight_layout(rect=(0, 0, 1, 0.97))

        out_png = os.path.join(base_dir, "Headloss_vs_Roughness.png")
        fig.savefig(out_png, dpi=150, bbox_inches="tight")
        print(f"\nFigure saved: {out_png}")
        plt.show()
    except Exception as e:
        print(f"  (Plot impossible: {e})")

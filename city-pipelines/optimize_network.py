"""
optimize_network.py
===================
Network sizing / optimization utilities for EPANET (.inp) files.

Author:
    - Ulrich Melade

INSA Toulouse.

What it does:
    1. optimize_network()         : iteratively enlarges pipe diameters until every
                                    junction holds a minimum pressure and velocities
                                    stay below 1.5 m/s at peak demand.
    2. modify_global_demand()     : adds a global extra demand, evenly spread over
                                    the main 'J' junctions -> creates the
                                    High_Demand variant of the network.
    3. restore_original_demands() : keeps the optimized (enlarged) network but puts
                                    back the original base demands -> creates the
                                    Low_Demand variant used by simulator.py.

    Running this file directly reproduces the full pipeline used by the
    interface export: base network -> High_Demand.inp (sized at peak)
    -> Low_Demand.inp (same pipes, nominal demands).

    CAUTION: running __main__ OVERWRITES High_Demand.inp and Low_Demand.inp in
    the target scenario folder. Low_Demand.inp is the file consumed by
    simulator.py and plot_comparison.py, so regenerating it changes the network
    those scripts simulate. Point the paths at a scratch folder to experiment.

What to modify (in __main__) and its effect:
    - inp / high_opt / low_opt : input network and output file paths.
    - peak (demand_change_L_s) : total sizing demand, default 0.5 L/s per house
                                 ('M' node). Increase it to force larger pipes,
                                 decrease it for a tighter (more sensitive) network.
    - min_pressure_bars        : pressure target of the optimization. A higher
                                 value produces larger diameters and higher heads.
    - max_iterations           : safety cap of the sizing loop (in optimize_network).
"""

import os

import wntr


def optimize_network(inp_filename, out_filename, min_pressure_bars=2.5):
    wn = wntr.network.WaterNetworkModel(inp_filename)
    min_pressure_m = min_pressure_bars * 10.197

    print(f"--- Optimizing {inp_filename} ---")
    print(
        f"Goal: Minimum pressure of {min_pressure_bars} bars ({min_pressure_m:.1f} m)"
    )

    iteration = 0
    max_iterations = 30

    junction_names = wn.junction_name_list

    while iteration < max_iterations:
        sim = wntr.sim.EpanetSimulator(wn)
        res = sim.run_sim()

        # Only check junctions
        pressures = res.node["pressure"].loc[:, junction_names].iloc[-1]
        min_p = pressures.min()

        velocities = res.link["velocity"].iloc[-1]
        max_v = velocities.abs().max()

        if min_p >= min_pressure_m and max_v <= 1.5:
            print(
                f"Success! After {iteration} iterations, min pressure = {min_p/10.197:.2f} bars, max velocity = {max_v:.2f} m/s."
            )
            break

        print(
            f"Iteration {iteration}: Min pressure = {min_p/10.197:.2f} bars, Max velocity = {max_v:.2f} m/s. Adjusting..."
        )

        if min_p < min_pressure_m or max_v > 1:
            # We fix pressure drops by reducing friction (increasing pipe diameters)
            for pipe_name, pipe in wn.pipes():
                if (
                    abs(velocities[pipe_name]) > 1.2
                ):  # Threshold at 1.2 m/s to keep normal friction
                    if pipe.diameter < 1.5:
                        pipe.diameter = min(1.5, pipe.diameter * 1.2)

        iteration += 1

    wntr.network.io.write_inpfile(wn, out_filename)
    print(f"New network saved to: {out_filename}")


def modify_global_demand(inp_filename, out_filename, demand_change_L_s=150.0):
    wn = wntr.network.WaterNetworkModel(inp_filename)

    # Find main nodes (starting with 'J') to avoid saturating small 'M' pipes
    j_nodes = [n for n in wn.junction_name_list if n.startswith("J")]

    if len(j_nodes) == 0:
        j_nodes = wn.junction_name_list

    demand_per_j = (demand_change_L_s / 1000.0) / len(j_nodes)

    for name in j_nodes:
        node = wn.get_node(name)
        if len(node.demand_timeseries_list) > 0:
            node.demand_timeseries_list[0].base_value = max(
                0.0, node.demand_timeseries_list[0].base_value + demand_per_j
            )
        else:
            node.add_demand(base=max(0.0, demand_per_j), pattern_name=None)

    print(
        f"--- Demand modified by {demand_change_L_s} L/s distributed across {len(j_nodes)} nodes ---"
    )
    wntr.network.io.write_inpfile(wn, out_filename)
    print(f"Network saved to: {out_filename}")


def restore_original_demands(optimized_inp, original_inp, out_inp):
    wn_opt = wntr.network.WaterNetworkModel(optimized_inp)
    wn_orig = wntr.network.WaterNetworkModel(original_inp)

    for name, node_opt in wn_opt.junctions():
        node_orig = wn_orig.get_node(name)
        if len(node_orig.demand_timeseries_list) > 0:
            if name.startswith("M"):
                base_val = 0.007 / 1000.0  # 0.007 L/s for houses
            else:
                base_val = node_orig.demand_timeseries_list[0].base_value

            if len(node_opt.demand_timeseries_list) == 0:
                node_opt.add_demand(
                    base=base_val,
                    pattern_name=node_orig.demand_timeseries_list[0].pattern_name,
                )
            else:
                node_opt.demand_timeseries_list[0].base_value = base_val
                node_opt.demand_timeseries_list[0].pattern_name = (
                    node_orig.demand_timeseries_list[0].pattern_name
                )

    wntr.network.io.write_inpfile(wn_opt, out_inp)
    print(f"--- Original demands restored and saved to: {out_inp} ---")


if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)
    inp = os.path.join(base_dir, "Scenarios", "Scenario 3", "ville.inp")
    high_opt = os.path.join(base_dir, "Scenarios", "Scenario 3", "High_Demand.inp")
    low_opt = os.path.join(base_dir, "Scenarios", "Scenario 3", "Low_Demand.inp")

    # 1. Add heavy global demand to the base network
    wn_opt = wntr.network.WaterNetworkModel(inp)
    num_houses = sum(1 for name in wn_opt.junction_name_list if name.startswith("M"))
    peak = max(5.0, num_houses * 0.5)
    modify_global_demand(inp, high_opt, demand_change_L_s=peak)

    # 2. Optimize this network at peak demand to enlarge pipes and adjust reservoirs
    optimize_network(high_opt, high_opt, min_pressure_bars=1)

    # 3. Create the "Low Demand" network using the optimized network (large pipes,
    # large reservoir) and RESTORING the small demands from the original base file
    restore_original_demands(high_opt, inp, low_opt)

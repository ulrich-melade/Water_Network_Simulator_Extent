# Realistic Water Network Simulator

A hydraulic simulator for water distribution networks, built on top of
[WNTR](https://github.com/USEPA/WNTR) (which bundles the EPANET solver).
It models 24-hour variable demand profiles, dynamic events (leaks, demand surges)
and degraded sensor conditions, then cross-checks the results against an
independent physics-based model.

> Originally developed as a research initiation project (PIR) at INSA Toulouse
> — where the hydraulic engine was [TSNet](https://github.com/glorialulu/TSNet) —
> later extended during a research internship at LAAS-CNRS, where the engine was
> migrated to WNTR for multi-day quasi-steady simulation.

## Key Features

* **Physics-based reference model** — a steady-state algebraic model built from
  first principles (`plot_comparison.py`), used as an independent reference to
  validate the WNTR simulation output.
* **Realistic demand profiles** — continuous 24-hour demand curves rather than
  abrupt step changes.
* **Dynamic event injection** — leaks (modeled as discharge coefficients), demand
  surges, and sensor faults (`NaN` dropouts and Gaussian measurement noise) are
  injected directly into the simulation; no external files required.
* **Network generator GUI** — a CustomTkinter interface to procedurally generate
  network topologies and configure parameters (pipe roughness, node count, …).
* **HeMu-compatible export** — pipe-separated CSV containing both the noiseless
  reference signals and the noisy sensor measurements.

## Authors

| Component | Authors |
|-----------|---------|
| `interface.py` | Cécile Maurel, Mathis Lelong, Claire Horion, Pierre-Antoine Acquaviva, Bernys Lele-Ngoli (PIR) — extended by Ulrich Melade |
| `simulator.py` | Ulrich Melade, Étienne Gadefait |
| `plot_comparison.py`, `optimize_network.py`, `export_plots.py`, `concat_csv.py`, `resample_csv.py` | Ulrich Melade |

INSA Toulouse — 4AE. The original PIR report, *Creation of a water simulation
system for a small town*, was supervised by Élodie Chanthery, Léonie Hatte and
Pauline Ribot.

## Project Structure

| File | Role |
|------|------|
| `city-pipelines/interface.py` | GUI for network generation; exports EPANET `.inp` files |
| `city-pipelines/simulator.py` | Core WNTR-based simulation engine: scenario configuration and data export |
| `city-pipelines/optimize_network.py` | Pipe sizing; builds the `High_Demand.inp` / `Low_Demand.inp` variants |
| `city-pipelines/export_plots.py` | Plots pressure (full + 24 h zoom), head loss and flow rate from a simulation CSV |
| `city-pipelines/concat_csv.py` | Concatenates two simulation CSVs into one continuous dataset |
| `city-pipelines/resample_csv.py` | Downsamples a simulation CSV to a coarser time step |
| `plot_comparison.py` | Comparison of the WNTR output against the physical reference model |
| `city-pipelines/Scenarios/` | Generated networks (EPANET `.inp`) |
| `city-pipelines/Network_Data/` | Simulation results (`.csv`) |

Every script carries a header docstring describing what it does and which
parameters can be tuned, along with the effect of each one.

## Installation

Requires Python 3.10+ (tested on 3.13).

```bash
git clone https://github.com/ulrich-melade/Water_Network_Simulator_Extent.git
cd Water_Network_Simulator_Extent
pip install -r requirements.txt
```

## Usage

1. **Generate a network** — run the GUI, set the parameters (the topology renders
   in the right-hand panel), then export the `.inp` file with the top-right icon.
   Clicking a node opens a popup to inject a fault (broken sensor, demand surge,
   leak). Exporting also produces the sized `High_Demand.inp` / `Low_Demand.inp`
   variants consumed by the simulator:

   ```bash
   python city-pipelines/interface.py
   ```

2. **Run the simulation** — edit the configuration block at the bottom of the
   file first (`nb_days`, `events`, `TARGET_PIPES`, input `.inp` and output CSV
   paths):

   ```bash
   python city-pipelines/simulator.py
   ```

3. **Compare with the physical model** — set `INP_PATH`, `CSV_PATH` and
   `OBSERVED_PIPE` at the top of the file so they match the simulation you just
   ran:

   ```bash
   python plot_comparison.py
   ```

4. **Plot the raw results** (optional):

   ```bash
   python city-pipelines/export_plots.py
   ```

## Output Format

Simulation results are written as a `|`-separated CSV. Each monitored pipe
contributes **four** consecutive columns, in this order:

1. pressure at the start node (bar)
2. head loss (mH₂O)
3. flow rate (L/s)
4. friction factor

| Column | Meaning |
|--------|---------|
| `t` | Time step |
| `uc_0` | Demand multiplier from the 24-hour curve (0.0–1.0) |
| `m` | Operating mode of the network (`on`) |
| `x_*` | Noiseless reference signals (4 per pipe, order above) |
| `h_0` | Discrete state index (HeMu convention) |
| `yc_*` | Noisy sensor measurements (`-1.0` marks a missing sample / broken sensor) |
| `yd`, `ud` | Fault flag and list of active events on that row |
| `demand` | Total network demand (L/s) |

Velocity is not exported directly; it is recovered as `Q / A` when needed
(`plot_comparison.py`).

## Limitations & Roadmap

* Node elevation is currently unusable, pending the implementation of
  pressure-reducing valves and pumps.
* Data accuracy is not warranted by the underlying solvers; the model reproduces
  realistic orders of magnitude and perturbation dynamics rather than validated
  field measurements.

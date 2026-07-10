# Realistic Water Network Simulator

A hydraulic simulator for water distribution networks, built on top of
[WNTR](https://github.com/USEPA/WNTR) and [TSNet](https://github.com/glorialulu/TSNet).
It models 24-hour variable demand profiles, dynamic events (leaks, demand surges)
and degraded sensor conditions, then cross-checks the results against an
independent physics-based model.

> Originally developed as a research initiation project (PIR) at INSA Toulouse,
> later extended during a research internship at LAAS-CNRS.

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

## Project Structure

| File | Role |
|------|------|
| `city-pipelines/simulator.py` | Core WNTR-based simulation engine: scenario configuration and data export |
| `city-pipelines/interface.py` | GUI for network generation; exports EPANET `.inp` files |
| `city-pipelines/export_plots.py` | Pressure, velocity and flow plots from the exported data |
| `plot_comparison.py` | Comparison of the WNTR output against the physical reference model |

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/<user>/<repo>.git
cd <repo>
pip install -r requirements.txt
```

## Usage

1. **Generate a network** — run the GUI, set the parameters (the topology renders
   in the right-hand panel), then export the `.inp` file with the top-right icon:

```bash
   python city-pipelines/interface.py
```

2. **Run the simulation**:

```bash
   python city-pipelines/simulator.py
```

3. **Plot the results**:

```bash
   python city-pipelines/export_plots.py
```

4. **Compare with the physical model**:
    
```bash
   python plot_comparison.py
```

## Limitations & Roadmap

* Node elevation is currently unusable, pending the implementation of
  pressure-reducing valves and pumps.
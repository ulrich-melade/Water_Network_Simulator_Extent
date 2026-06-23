"""
Simulateur_Realiste.py
======================
Simulateur hydraulique multi-jours amélioré.
Ne modifie aucun fichier existant — se base sur Low_Demand.inp uniquement.

Améliorations vs Simulateur_Infini.py :
 1. Courbe de demande 24h continue (pas de commutation binaire High/Low)
 2. Bruit de capteur gaussien (composante fixe + proportionnelle au signal)
 3. Débit Q = v × A calculé à chaque pas de temps
 4. NaN préservés dans le CSV (capteurs cassés ≠ 0.0)
 5. Capteurs cassés = panne persistante (pas de drops aléatoires par sample)
 6. Pas de fichiers _leak/_surge requis (événements injectés dynamiquement)
 7. Export CSV enrichi : débit, multiplicateur de demande continu, événements sur chaque ligne
 8. Résolution temporelle fine (segments de 30 min au lieu de blocs de plusieurs heures)
 9. Valeurs par défaut réalistes (fuites, surges, bruit)
10. Un seul fichier INP nécessaire (Low_Demand.inp)
"""

import warnings
warnings.filterwarnings('ignore')
import wntr
import numpy as np
import json
import os
import math

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
# 1. COURBE DE DEMANDE RÉALISTE (24H)
# ==============================================================
# Valeurs normalisées (max = 1.0) basées sur les études ONEMA/OFB
# de la consommation résidentielle française typique.
# La valeur 1.0 correspond à peak_demand_L_s dans la config.

DEMAND_CURVE_24H = [
    0.17,  # 0h  — nuit profonde
    0.14,  # 1h
    0.11,  # 2h  — minimum nocturne
    0.11,  # 3h
    0.14,  # 4h
    0.22,  # 5h  — premiers réveils
    0.44,  # 6h  — montée matinale
    0.83,  # 7h  — pic matin (douches, petit-déjeuner)
    1.00,  # 8h  — pic matin max
    0.78,  # 9h  — baisse post-matin
    0.56,  # 10h — milieu de matinée
    0.61,  # 11h
    0.78,  # 12h — pic midi (repas)
    0.72,  # 13h
    0.56,  # 14h — début d'après-midi
    0.50,  # 15h — creux après-midi
    0.56,  # 16h
    0.67,  # 17h — montée du soir
    0.89,  # 18h — pic soir (cuisine, douches)
    1.00,  # 19h — pic soir max
    0.83,  # 20h — baisse progressive
    0.56,  # 21h
    0.39,  # 22h
    0.28,  # 23h — nuit
]


def get_demand_multiplier(hour):
    """
    Retourne le multiplicateur de demande pour une heure donnée (0.0–24.0).
    Interpolation cosinus pour éviter les transitions brutales.
    """
    h = hour % 24.0
    h_floor = int(h) % 24
    h_ceil = (h_floor + 1) % 24
    frac = h - int(h)
    # Interpolation cosinus (plus lisse que linéaire)
    t = (1 - math.cos(frac * math.pi)) / 2.0
    return DEMAND_CURVE_24H[h_floor] * (1 - t) + DEMAND_CURVE_24H[h_ceil] * t


# ==============================================================
# 2. APPLICATION DES ÉVÉNEMENTS (FUITES, SURGES, BROKEN)
# ==============================================================

def apply_active_events(wn, active_events):
    """
    Applique les événements actifs sur le réseau WNTR en mémoire.
    - leak  : emitter_coefficient sur le nœud (fuite non contrôlée)
    - surge : ajout de demande supplémentaire (surconsommation)
    - broken: marquage pour suppression des données capteur
    """
    leak_nodes = {}
    broken_sensors = set()
    surge_nodes = set()

    for ev in active_events:
        if ev['type'] == 'leak':
            coeff = ev.get('coeff', 0.75)
            # Conversion de l'emitter coefficient (Epanet) en aire de fuite (WNTR)
            # q = C * p^0.5 (Epanet) <=> q = Cd * A * sqrt(2g) * p^0.5 (WNTR)
            # A = C / (Cd * sqrt(2g)) = coeff / (0.75 * 4.4294) = coeff / 3.322
            area_wntr = coeff / 3.322
            for node_id in ev.get('nodes', []):
                leak_nodes[node_id] = coeff
                target_node = None
                if node_id.startswith('P') and node_id in wn.link_name_list:
                    pipe = wn.get_link(node_id)
                    target_node = wn.get_node(pipe.start_node_name)
                else:
                    try:
                        target_node = wn.get_node(node_id)
                    except Exception:
                        pass
                
                if target_node:
                    # Pour EpanetSimulator (qui ignore add_leak mais utilise emitter_coefficient)
                    target_node.emitter_coefficient = coeff
                    # Pour WNTRSimulator (qui ignore emitter_coefficient mais utilise add_leak)
                    # start_time=0 est nécessaire pour que la fuite soit active !
                    target_node.add_leak(wn, area=area_wntr, discharge_coeff=0.75, start_time=0)

        elif ev['type'] == 'surge':
            demand_L_s = ev.get('demand_L_s', 5.0)
            demand_m3s = demand_L_s / 1000.0
            for node_id in ev.get('nodes', []):
                surge_nodes.add(node_id)
                try:
                    node = wn.get_node(node_id)
                    if hasattr(node, 'demand_timeseries_list'):
                        if len(node.demand_timeseries_list) > 0:
                            node.demand_timeseries_list[0].base_value += demand_m3s
                        else:
                            node.add_demand(demand_m3s, None)
                except Exception:
                    pass

        elif ev['type'] == 'broken':
            for node_id in ev.get('nodes', []):
                broken_sensors.add(node_id)

    return leak_nodes, list(broken_sensors), list(surge_nodes)


# ==============================================================
# 3. BRUIT DE CAPTEUR RÉALISTE (GAUSSIEN)
# ==============================================================

def add_sensor_noise(values, sigma_base, sigma_proportional=0.00005):
    """
    Modèle de bruit gaussien réaliste :
      noise = N(0, σ_base) + signal × N(0, σ_proportionnel)

    - σ_base       : bruit de fond constant du capteur (ex: 0.005 bar)
    - σ_proportionnel : erreur relative (ex: 1% = 0.01)
    """
    n = len(values)
    noise_fixed = np.random.normal(0, sigma_base, n)
    noise_prop = values * np.random.normal(0, sigma_proportional, n)
    return values + noise_fixed + noise_prop


# ==============================================================
# 4. PRÉPARATION DU RÉSEAU
# ==============================================================

def prepare_network(wn):
    """
    Corrections communes appliquées au réseau avant simulation :
    - Conduites vers maisons (M) : diamètre 20mm
    - Conduites trop petites : diamètre minimum 100mm
    - Rugosité H-W invalide : corrigée à 130 (PVC neuf)
    """
    # Forcer les chateaux d'eau à être au dessus du reseau d'au moins 10 m (1 bar) pour laisser voir les variations
    max_elev = max([n.elevation for name, n in wn.nodes() if hasattr(n, 'elevation')] + [0])
    for name, node in wn.nodes():
        if node.node_type in ['Reservoir', 'Tank']:
            if getattr(node, 'base_head', 0) < max_elev + 10:
                node.base_head = max_elev + 10

    for pipe_name, pipe in wn.links():
        if pipe.link_type == 'Pipe':
            if pipe.start_node_name.startswith('M') or pipe.end_node_name.startswith('M'):
                pipe.diameter = 0.02
    for link_name, link in wn.links():
        if hasattr(link, 'roughness') and wn.options.hydraulic.headloss == 'H-W' and link.roughness < 1.0:
            link.roughness = 130.0


def apply_demand_curve(wn, hour, peak_demand_L_s=200.0):
    """
    Applique la courbe de demande réaliste sur les nœuds J (jonctions réseau).
    Le paramètre peak_demand_L_s correspond au débit total ajouté au pic (mult=1.0).
    Les nœuds M (maisons) gardent leur demande de base constante.

    Retourne le multiplicateur de demande utilisé.
    """
    multiplier = get_demand_multiplier(hour)
    j_nodes = [name for name, _ in wn.junctions() if name.startswith('J')]
    if not j_nodes:
        return multiplier
    extra_per_node_m3s = (peak_demand_L_s / 1000.0) * multiplier / len(j_nodes)
    for name in j_nodes:
        node = wn.get_node(name)
        if len(node.demand_timeseries_list) > 0:
            node.demand_timeseries_list[0].base_value += extra_per_node_m3s
    return multiplier


# ==============================================================
# 5. SEGMENT DE SIMULATION WNTR
# ==============================================================

def run_segment(inp_file, duration, state_file, chosen_pipes, hour_of_day,
                active_events=None, peak_demand_L_s=200.0,
                sigma_pressure=0.0001, sigma_velocity=0.00002):
    """
    Exécute un segment de simulation quasi-stationnaire avec WNTR.

    Paramètres :
      inp_file         : fichier .inp de base (Low_Demand.inp)
      duration         : durée du segment en secondes
      state_file       : fichier JSON d'état pour la continuité
      chosen_pipes     : liste des conduites à monitorer
      hour_of_day      : heure réelle (0–24) pour la courbe de demande
      active_events    : liste des événements actifs
      peak_demand_L_s  : demande de pointe du réseau (L/s)
      sigma_pressure   : écart-type du bruit de pression (bar)
      sigma_velocity   : écart-type du bruit de vitesse (m/s)
    """
    if active_events is None:
        active_events = []

    wn = wntr.network.WaterNetworkModel(inp_file)

    # Restaurer l'état précédent (continuité inter-segments)
    offset_time = 0.0
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            state = json.load(f)
            offset_time = state['time']
            for name, node in wn.nodes():
                if node.node_type in ['Reservoir', 'Tank']:
                    if name in state['nodes_head']:
                        node.base_head = state['nodes_head'][name]

    # Préparer le réseau
    prepare_network(wn)

    # Appliquer la courbe de demande continue
    demand_mult = apply_demand_curve(wn, hour_of_day, peak_demand_L_s)

    # Appliquer les événements actifs
    leak_nodes, broken_sensors, surge_nodes = apply_active_events(wn, active_events)

    # Configuration temporelle
    wn.options.time.duration = duration
    wn.options.time.hydraulic_timestep = min(60, duration)
    wn.options.time.report_timestep = min(60, duration)

    # Simulation
    try:
        sim = wntr.sim.WNTRSimulator(wn)
        results = sim.run_sim()
    except Exception as e:
        print(f"  WNTRSimulator échoué ({e}), fallback EpanetSimulator")
        sim = wntr.sim.EpanetSimulator(wn)
        results = sim.run_sim()

    # Extraction des résultats
    timestamps = results.node['pressure'].index.values
    shifted_time = timestamps + offset_time
    n = len(shifted_time)

    res = {'time': shifted_time, 'pipes': {}, 'demand_multiplier': demand_mult}

    for pipe_id in chosen_pipes:
        try:
            pipe = wn.get_link(pipe_id)
        except Exception:
            continue

        start_node = pipe.start_node_name
        end_node = pipe.end_node_name

        # ── Pression (mH2O → bar) + bruit gaussien ──
        p_start_raw = results.node['pressure'].loc[:, start_node].values / 10.197
        p_end_raw = results.node['pressure'].loc[:, end_node].values / 10.197
        p_start = add_sensor_noise(p_start_raw, sigma_pressure)
        p_end = add_sensor_noise(p_end_raw, sigma_pressure)

        # ── Débit (m³/s) directement depuis WNTR ──
        q_raw = results.link['flowrate'].loc[:, pipe_id].values
        
        # ── Vitesse + signe correct + bruit gaussien ──
        # Dans WNTR, velocity est absolue, on lui redonne le signe du débit
        v_raw = results.link['velocity'].loc[:, pipe_id].values * np.sign(q_raw + 1e-9)
        v_start = add_sensor_noise(v_raw, sigma_velocity)
        v_end = add_sensor_noise(v_raw, sigma_velocity)
        velocity = add_sensor_noise(v_raw, sigma_velocity)

        area = np.pi * (pipe.diameter / 2) ** 2
        sigma_flowrate = sigma_velocity * area
        flowrate = add_sensor_noise(q_raw, sigma_flowrate)

        # ── Perte de charge (Headloss) en mH2O ──
        if 'headloss' in results.link:
            h_loss_raw = results.link['headloss'].loc[:, pipe_id].values
        else:
            h_loss_raw = (p_start_raw - p_end_raw) * 10.197 # approximation simplifiée
        # Ajout d'un très léger bruit sur la mesure différentielle
        headloss = add_sensor_noise(h_loss_raw, sigma_pressure)

        # -- Capteurs cassés : panne persistante (tout NaN)--
        # -- Demande (Débit sortant aux noeuds) --
        d_start = results.node['demand'].loc[:, start_node].values
        d_end = results.node['demand'].loc[:, end_node].values
        
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

        res['pipes'][pipe_id] = {
            'pressure_start': p_start,
            'pressure_end': p_end,
            'demand_start': d_start,
            'demand_end': d_end,
            'velocity': velocity,
            'velocity_start': v_start,
            'velocity_end': v_end,
            'flowrate': flowrate,
            'headloss': headloss,
            'start_node': start_node,
            'end_node': end_node,
        }

    # Sauvegarder l'état pour le segment suivant
    new_state = {
        'time': float(shifted_time[-1]),
        'nodes_head': results.node['head'].iloc[-1].to_dict(),
        'nodes_pressure': results.node['pressure'].iloc[-1].to_dict(),
        'nodes_demand': results.node['demand'].iloc[-1].to_dict(),
        'links_velocity': results.link['velocity'].iloc[-1].to_dict(),
        'links_flowrate': results.link['flowrate'].iloc[-1].to_dict(),
    }
    with open(state_file, 'w') as f:
        json.dump(new_state, f, indent=4)

    faults = {'leak_nodes': leak_nodes, 'broken_sensors': broken_sensors, 'surge_nodes': surge_nodes}
    return res, faults


# ==============================================================
# 6. TRANSITION LISSE ENTRE SEGMENTS
# ==============================================================

def run_transition(inp_file, duration, state_file, chosen_pipes,
                   hour_of_day, active_events=None, peak_demand_L_s=200.0,
                   sigma_pressure=0.0001, sigma_velocity=0.00002):
    """
    Transition lisse entre deux niveaux de demande.
    Interpole entre l'état courant et l'état cible (cosinus fade).
    Durée typique : 60 secondes.
    """
    if active_events is None:
        active_events = []

    state = None
    offset_time = 0.0
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            state = json.load(f)
            offset_time = state['time']

    # ── Calculer l'état cible (réseau avec la nouvelle demande) ──
    wn_target = wntr.network.WaterNetworkModel(inp_file)
    if state:
        for name, node in wn_target.nodes():
            if node.node_type in ['Reservoir', 'Tank']:
                if name in state['nodes_head']:
                    node.base_head = state['nodes_head'][name]

    prepare_network(wn_target)
    demand_mult = apply_demand_curve(wn_target, hour_of_day, peak_demand_L_s)
    leak_nodes, broken_sensors, surge_nodes = apply_active_events(wn_target, active_events)

    wn_target.options.time.duration = 10
    wn_target.options.time.hydraulic_timestep = 10
    wn_target.options.time.report_timestep = 10

    sim = wntr.sim.EpanetSimulator(wn_target)
    target_res = sim.run_sim()

    target_p = target_res.node['pressure'].iloc[-1].to_dict()
    target_v = target_res.link['velocity'].iloc[-1].to_dict()
    target_hl = target_res.link['headloss'].iloc[-1].to_dict()
    target_h = target_res.node['head'].iloc[-1].to_dict()
    target_d = target_res.node['demand'].iloc[-1].to_dict()
    target_q = target_res.link['flowrate'].iloc[-1].to_dict()

    # ── Interpolation cosinus ──
    dt = 1.0  # 1 seconde de résolution pour la transition
    n_steps = max(1, int(duration / dt))
    shifted_time = [offset_time + i * dt for i in range(n_steps)]
    fade = (1 - np.cos(np.linspace(0, np.pi, n_steps))) / 2.0

    res = {'time': shifted_time, 'pipes': {}, 'demand_multiplier': demand_mult}

    for pipe_id in chosen_pipes:
        try:
            pipe = wn_target.get_link(pipe_id)
        except Exception:
            continue

        start_node = pipe.start_node_name
        end_node = pipe.end_node_name

        # Valeurs initiales (depuis l'état sauvegardé, en mH2O)
        p_s_i = state['nodes_pressure'].get(start_node, 0) if state else target_p.get(start_node, 0)
        p_e_i = state['nodes_pressure'].get(end_node, 0) if state else target_p.get(end_node, 0)
        v_i = state['links_velocity'].get(pipe_id, 0) if state else target_v.get(pipe_id, 0)

        # Valeurs finales (état cible, en mH2O)
        p_s_f = target_p.get(start_node, p_s_i)
        p_e_f = target_p.get(end_node, p_e_i)
        v_f = target_v.get(pipe_id, v_i)
        
        # Headloss (Perte de charge)
        hl_i = state['links_headloss'].get(pipe_id, 0) if state and 'links_headloss' in state else target_hl.get(pipe_id, 0)
        hl_f = target_hl.get(pipe_id, hl_i)

        # Interpolation mH2O → conversion bar → bruit gaussien
        p_start = add_sensor_noise(
            (p_s_i + (p_s_f - p_s_i) * fade) / 10.197, sigma_pressure
        )
        p_end = add_sensor_noise(
            (p_e_i + (p_e_f - p_e_i) * fade) / 10.197, sigma_pressure
        )

        # Débit interpolé
        q_i = state['links_flowrate'].get(pipe_id, target_q.get(pipe_id, 0)) if state and 'links_flowrate' in state else target_q.get(pipe_id, 0)
        q_f = target_q.get(pipe_id, q_i)
        q_interp = q_i + (q_f - q_i) * fade
        area = np.pi * (pipe.diameter / 2) ** 2
        sigma_flowrate = sigma_velocity * area
        flowrate = add_sensor_noise(q_interp, sigma_flowrate)

        # Vitesse interpolée avec bruit indépendant et signe respecté
        v_interp = (v_i + (v_f - v_i) * fade) * np.sign(q_interp + 1e-9)
        velocity = add_sensor_noise(v_interp, sigma_velocity)
        v_start = add_sensor_noise(v_interp, sigma_velocity)
        v_end = add_sensor_noise(v_interp, sigma_velocity)

        # Headloss interpolé
        hl_interp = hl_i + (hl_f - hl_i) * fade
        headloss = add_sensor_noise(hl_interp, sigma_pressure)

        # Capteurs cassés
        # ── Demande (Débit sortant aux noeuds) ──
        d_s_i = state['nodes_demand'].get(start_node, 0) if state and 'nodes_demand' in state else target_d.get(start_node, 0)
        d_e_i = state['nodes_demand'].get(end_node, 0) if state and 'nodes_demand' in state else target_d.get(end_node, 0)
        d_s_f = target_d.get(start_node, d_s_i)
        d_e_f = target_d.get(end_node, d_e_i)
        
        # We don't necessarily need noise for demand, but we can interpolate it
        d_start = d_s_i + (d_s_f - d_s_i) * fade
        d_end = d_e_i + (d_e_f - d_e_i) * fade
        
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

        res['pipes'][pipe_id] = {
            'pressure_start': p_start,
            'pressure_end': p_end,
            'demand_start': d_start,
            'demand_end': d_end,
            'velocity': velocity,
            'velocity_start': v_start,
            'velocity_end': v_end,
            'flowrate': flowrate,
            'headloss': headloss,
            'start_node': start_node,
            'end_node': end_node,
        }

    # Sauvegarder l'état cible
    new_state = {
        'time': float(shifted_time[-1] + dt),
        'nodes_head': target_h,
        'nodes_pressure': target_p,
        'nodes_demand': target_d,
        'links_velocity': target_v,
        'links_headloss': target_hl,
        'links_flowrate': target_q,
    }
    with open(state_file, 'w') as f:
        json.dump(new_state, f, indent=4)

    faults = {'leak_nodes': leak_nodes, 'broken_sensors': broken_sensors, 'surge_nodes': surge_nodes}
    return res, faults


# ==============================================================
# 7. GÉNÉRATION DU SCÉNARIO RÉALISTE
# ==============================================================

def get_abs_time(day, hour):
    """Convertit (jour, heure) en temps absolu de simulation (heures)."""
    h_offset = hour - 7.0 if hour >= 7.0 else hour + 17.0
    return (day - 1) * 24.0 + h_offset


def generate_realistic_scenario(base_dir, nb_days, events, inp_file,
                                segment_duration_h=0.5,
                                transition_duration_s=60):
    """
    Génère un planning de simulation réaliste.

    Au lieu de commuter entre High_Demand.inp et Low_Demand.inp,
    on utilise UN SEUL fichier INP (Low_Demand.inp) et on fait varier
    la demande de façon continue via la courbe 24h.

    Paramètres :
      nb_days             : nombre de jours de simulation
      events              : liste des événements [{type, start_day, start_hour, ...}]
      inp_file            : fichier .inp de base
      segment_duration_h  : durée d'un segment WNTR (heures, défaut 0.5 = 30 min)
      transition_duration_s : durée d'une transition (secondes, défaut 60)
    """

    segments_per_day = int(24.0 / segment_duration_h)
    total_segments = nb_days * segments_per_day
    segment_duration_s = int(segment_duration_h * 3600)

    etapes = []

    for seg_idx in range(total_segments):
        abs_time_h = seg_idx * segment_duration_h
        real_hour = (7.0 + abs_time_h) % 24.0

        # Quels événements sont actifs pendant ce segment ?
        seg_start = abs_time_h
        seg_end = abs_time_h + segment_duration_h
        active = []
        for ev in events:
            ev_start = get_abs_time(ev['start_day'], ev['start_hour'])
            ev_end = get_abs_time(ev['end_day'], ev['end_hour'])
            if ev_start < seg_end and ev_end > seg_start:
                active.append(ev)

        # Étape WNTR (segment principal)
        wntr_dur = segment_duration_s - transition_duration_s
        etapes.append({
            'inp': inp_file,
            'engine': 'wntr',
            'duration': wntr_dur,
            'hour': real_hour,
            'events': active,
        })

        # Étape transition (vers le segment suivant)
        next_hour = (7.0 + (seg_idx + 1) * segment_duration_h) % 24.0
        next_start = seg_end
        next_end = seg_end + segment_duration_h
        next_active = []
        for ev in events:
            ev_start = get_abs_time(ev['start_day'], ev['start_hour'])
            ev_end = get_abs_time(ev['end_day'], ev['end_hour'])
            if ev_start < next_end and ev_end > next_start:
                next_active.append(ev)

        etapes.append({
            'inp': inp_file,
            'engine': 'transition',
            'duration': transition_duration_s,
            'hour': next_hour,
            'events': next_active,
        })

    return etapes


# ==============================================================
# 8. EXPORT CSV AMÉLIORÉ
# ==============================================================

def append_to_csv(csv_filename, results, active_faults, chosen_pipes,
                  is_first_step, demand_multiplier=1.0):
    """
    Export CSV amélioré :
    - Séparateur : pipe |
    - NaN préservés (pas remplacés par 0.0)
    - Colonne débit ajoutée
    - uc_demande = multiplicateur continu (0.0–1.0)
    - ud_evenement = événements actifs sur CHAQUE ligne
    """
    events_actifs = []
    for node in active_faults.get('leak_nodes', {}):
        events_actifs.append(f"f_leak_{node}")
    for node in active_faults.get('broken_sensors', []):
        events_actifs.append(f"f_broken_{node}")
    for node in active_faults.get('surge_nodes', []):
        events_actifs.append(f"f_surge_{node}")
    events_actifs.sort()
    events_str = ",".join(events_actifs) if events_actifs else "no"

    mode = 'w' if is_first_step else 'a'
    os.makedirs(os.path.dirname(csv_filename), exist_ok=True)

    with open(csv_filename, mode) as f:
        if is_first_step:
            cols = ["t", "uc_demande", "ud", "yd"]
            for pid in chosen_pipes:
                cols.extend([f"yc_Pression_{pid}", f"yc_Demande_{pid}", f"yc_Vitesse_{pid}", f"yc_Debit_{pid}", f"yc_PerteCharge_{pid}"])
            f.write("|".join(cols) + "\n")

        for t_idx, t_val in enumerate(results['time']):
            row = [
                f"{t_val:.1f}",
                f"{demand_multiplier:.4f}",
                events_str,
                "no",
            ]

            for pid in chosen_pipes:
                if pid in results['pipes']:
                    data = results['pipes'][pid]
                    p = data['pressure_start'][t_idx]
                    d = data['demand_start'][t_idx] if 'demand_start' in data else 0.0
                    v = data['velocity_start'][t_idx]
                    q = data['flowrate'][t_idx] if 'flowrate' in data else 0.0
                    hl = data['headloss'][t_idx] if 'headloss' in data else 0.0

                    # Pas de NaN pour HeMU : on utilise -1.0 pour signaler une valeur manquante
                    row.append("-1.0" if np.isnan(p) else f"{p:.4f}")
                    row.append("-1.0" if np.isnan(d) else f"{d:.8f}")
                    row.append("-1.0" if np.isnan(v) else f"{v:.4f}")
                    row.append("-1.0" if np.isnan(q) else f"{q:.8f}")
                    row.append("-1.0" if np.isnan(hl) else f"{hl:.4f}")
                else:
                    row.extend(["-1.0", "-1.0", "-1.0", "-1.0", "-1.0"])

            f.write("|".join(row) + "\n")


# ==============================================================
# 9. POINT D'ENTRÉE PRINCIPAL
# ==============================================================

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # ── CONFIGURATION DU SCÉNARIO ──────────────────────────────
    nb_days = 5
    events = [
        # #Fuite sur P1015 : Jour 2 à 14h30 → Jour 4 à 10h00
        {
            'type': 'leak',
            'start_day': 2, 'start_hour': 14.5,
            'end_day': 4, 'end_hour': 10.0,
            'nodes': ['P15'],
            'coeff': 0.2,
        },
        # # Surconsommation sur M236 : Jour 1 de 10h à 14h
        # {
        #     'type': 'surge',
        #     'start_day': 1, 'start_hour': 10.0,
        #     'end_day': 1, 'end_hour': 14.0,
        #     'nodes': ['M236'],
        #     'demand_L_s': 5.0,  # 5 L/s de surconsommation (réaliste)
        # },
    ]

    # ── TUYAUX À OBSERVER (Laissez vide [] pour aléatoire) ──
    TARGET_PIPES = ['P15']  # Exemple: ['P12', 'P45']

    state_file = os.path.join(base_dir, 'temp_state_realiste.json')
    csv_file = os.path.join(base_dir, 'reseau', 'Scenario 2', 'export_realiste.csv')
    import wntr
    import random
    temp_inp = os.path.join(base_dir, 'reseau', 'Scenario 2', 'Low_Demand.inp')
    
    # --- LECTURE DES CAPTEURS CASSÉS DEPUIS L'INTERFACE ---
    broken_nodes_from_inp = []
    if os.path.exists(temp_inp):
        with open(temp_inp, 'r', encoding='utf-8') as f:
            for line in f:
                if '; [CAPTEUR CASSÉ]' in line:
                    parts = line.split(']')
                    if len(parts) > 1:
                        node_info = parts[1].split('(')[0].strip()
                        if node_info:
                            broken_nodes_from_inp.append(node_info)
    
    if broken_nodes_from_inp:
        events.append({
            'type': 'broken',
            'start_day': 1, 'start_hour': 0.0,
            'end_day': nb_days + 1, 'end_hour': 24.0,
            'nodes': broken_nodes_from_inp,
        })

    wn_temp = wntr.network.WaterNetworkModel(temp_inp)
    all_p = list(wn_temp.pipe_name_list)
    
    # S'assurer d'observer au moins une conduite avec un capteur cassé pour la démo
    added_broken = 0
    for node in broken_nodes_from_inp:
        if added_broken >= 2: break
        for p_name, pipe in wn_temp.links():
            if pipe.start_node_name == node or pipe.end_node_name == node:
                if p_name not in TARGET_PIPES and p_name in all_p:
                    TARGET_PIPES.append(p_name)
                    added_broken += 1
                    break

    num_houses = sum(1 for name in wn_temp.junction_name_list if name.startswith('M'))
    peak_demand_L_s = max(5.0, num_houses * 0.5)  # Demande de pointe dynamique : 0.5 L/s par maison
    
    segment_duration_h = 0.5     # Segment de 6 minutes pour des courbes bien lisses
    transition_duration_s = 60     # Transition de 60 secondes
    
    # Sélection des conduites : d'abord celles demandées, puis on complète aléatoirement jusqu'à 5
    chosen_pipes = [p for p in TARGET_PIPES if p in all_p]
    remaining = max(0, 5 - len(chosen_pipes))
    if remaining > 0:
        available_p = [p for p in all_p if p not in chosen_pipes]
        chosen_pipes.extend(random.sample(available_p, min(remaining, len(available_p))))

    # ── Nettoyage état précédent ──
    if os.path.exists(state_file):
        os.remove(state_file)

    # ── Génération du scénario ──
    etapes = generate_realistic_scenario(
        base_dir, nb_days, events, temp_inp,
        segment_duration_h=segment_duration_h,
        transition_duration_s=transition_duration_s,
    )

    total_wntr = sum(1 for e in etapes if e['engine'] == 'wntr')
    total_trans = sum(1 for e in etapes if e['engine'] == 'transition')
    print(f"+{'='*58}+")
    print(f"|         SIMULATION SUR {nb_days} JOURS                  |")
    print(f"+{'='*58}+")
    print(f"|  Segments WNTR    : {total_wntr:>4}  ({segment_duration_h}h chacun)              |")
    print(f"|  Transitions      : {total_trans:>4}  ({transition_duration_s}s chacune)              |")
    print(f"|  Demande de pointe: {peak_demand_L_s:>6.0f} L/s                        |")
    print(f"|  Evenements       : {len(events):>4}                                |")
    print(f"|  Conduites        : {', '.join(chosen_pipes):<30}    |")
    print(f"+{'='*58}+")

    for i, etape in enumerate(etapes):
        engine = etape['engine']
        duration = etape['duration']
        hour = etape['hour']
        active_events = etape['events']
        is_first = (i == 0)

        # Affichage condensé
        if i % 20 == 0 or active_events:
            mult = get_demand_multiplier(hour)
            ev_str = f" <- [{','.join(e['type'] for e in active_events)}]" if active_events else ""
            print(f"  [{i+1:>4}/{len(etapes)}] {engine:>10} | {duration:>5}s | {hour:05.1f}h | mult={mult:.2f}{ev_str}")

        if engine == 'wntr':
            res, faults = run_segment(
                etape['inp'], duration, state_file, chosen_pipes, hour,
                active_events, peak_demand_L_s
            )
        elif engine == 'transition':
            res, faults = run_transition(
                etape['inp'], duration, state_file, chosen_pipes, hour,
                active_events, peak_demand_L_s,
            )

        demand_mult = res.get('demand_multiplier', 1.0)
        append_to_csv(csv_file, res, faults, chosen_pipes, is_first, demand_mult)

    print(f"\n{'='*60}")
    print(f"Simulation terminee ! Resultats dans :")
    print(f"  {csv_file}")
    print(f"{'='*60}")

    # Lire le CSV et afficher des statistiques
    try:
        import csv as csv_mod
        with open(csv_file, 'r') as f:
            reader = csv_mod.DictReader(f, delimiter='|')
            pressures = []
            velocities = []
            for row in reader:
                for pid in chosen_pipes:
                    p_key = f"Pression_{pid}"
                    v_key = f"Vitesse_{pid}"
                    if p_key in row and row[p_key] != 'NaN':
                        pressures.append(float(row[p_key]))
                    if v_key in row and row[v_key] != 'NaN':
                        velocities.append(float(row[v_key]))

        if pressures:
            print(f"\n--- Statistiques des resultats ---")
            print(f"  Pression : min={min(pressures):.2f} bar, max={max(pressures):.2f} bar, moy={sum(pressures)/len(pressures):.2f} bar")
        if velocities:
            print(f"  Vitesse  : min={min(velocities):.4f} m/s, max={max(velocities):.4f} m/s, moy={sum(velocities)/len(velocities):.4f} m/s")
            print(f"  Points   : {len(pressures)} mesures de pression")
    except Exception as e:
        print(f"  (Diagnostic impossible : {e})")

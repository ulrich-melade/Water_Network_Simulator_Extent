import wntr
import numpy as np

def optimize_network(inp_filename, out_filename, min_pressure_bars=2.5):
    wn = wntr.network.WaterNetworkModel(inp_filename)
    min_pressure_m = min_pressure_bars * 10.197
    
    print(f'--- Optimisation de {inp_filename} ---')
    print(f'Objectif : Pression minimale de {min_pressure_bars} bars ({min_pressure_m:.1f} m)')
    
    iteration = 0
    max_iterations = 30
    
    junction_names = wn.junction_name_list
    
    while iteration < max_iterations:
        sim = wntr.sim.EpanetSimulator(wn)
        res = sim.run_sim()
        
        # Only check junctions
        pressures = res.node['pressure'].loc[:, junction_names].iloc[-1]
        min_p = pressures.min()
        
        velocities = res.link['velocity'].iloc[-1]
        max_v = velocities.abs().max()
        
        if min_p >= min_pressure_m and max_v <= 1.5:
            print(f'Succès ! Après {iteration} itérations, pression min = {min_p/10.197:.2f} bars, vitesse max = {max_v:.2f} m/s.')
            break
            
        print(f'Itération {iteration}: Pression min = {min_p/10.197:.2f} bars, Vitesse max = {max_v:.2f} m/s. Ajustement...')
        
        if min_p < min_pressure_m or max_v > 1:
            # We fix pressure drops by reducing friction (increasing pipe diameters)
            for pipe_name, pipe in wn.pipes():
                if abs(velocities[pipe_name]) > 1.2:  # Threshold at 1.2 m/s to keep normal friction
                    if pipe.diameter < 1.5:
                        pipe.diameter = min(1.5, pipe.diameter * 1.2)
                        
        iteration += 1

    wntr.network.io.write_inpfile(wn, out_filename)
    print(f'Nouveau réseau sauvegardé sous : {out_filename}')

import os

def modify_global_demand(inp_filename, out_filename, demand_change_L_s=150.0):
    wn = wntr.network.WaterNetworkModel(inp_filename)
    
    # Trouver les noeuds principaux (ceux commençant par 'J') pour ne pas saturer les petites conduites 'M'
    j_nodes = [n for n in wn.junction_name_list if n.startswith('J')]
    
    if len(j_nodes) == 0:
        j_nodes = wn.junction_name_list
        
    demand_per_j = (demand_change_L_s / 1000.0) / len(j_nodes)
    
    for name in j_nodes:
        node = wn.get_node(name)
        if len(node.demand_timeseries_list) > 0:
            node.demand_timeseries_list[0].base_value = max(0.0, node.demand_timeseries_list[0].base_value + demand_per_j)
        else:
            node.add_demand(base=max(0.0, demand_per_j), pattern_name=None)
            
    print(f'--- Demande modifiée de {demand_change_L_s} L/s répartie sur {len(j_nodes)} nœuds ---')
    wntr.network.io.write_inpfile(wn, out_filename)
    print(f'Réseau sauvegardé sous : {out_filename}')

def restore_original_demands(optimized_inp, original_inp, out_inp):
    wn_opt = wntr.network.WaterNetworkModel(optimized_inp)
    wn_orig = wntr.network.WaterNetworkModel(original_inp)
    
    for name, node_opt in wn_opt.junctions():
        node_orig = wn_orig.get_node(name)
        if len(node_orig.demand_timeseries_list) > 0:
            if name.startswith('M'):
                base_val = 0.007 / 1000.0  # 0.007 L/s pour les maisons
            else:
                base_val = node_orig.demand_timeseries_list[0].base_value
                
            if len(node_opt.demand_timeseries_list) == 0:
                node_opt.add_demand(base=base_val, pattern_name=node_orig.demand_timeseries_list[0].pattern_name)
            else:
                node_opt.demand_timeseries_list[0].base_value = base_val
                node_opt.demand_timeseries_list[0].pattern_name = node_orig.demand_timeseries_list[0].pattern_name
                
    wntr.network.io.write_inpfile(wn_opt, out_inp)
    print(f'--- Demandes originales restaurées et sauvegardées sous : {out_inp} ---')

if __name__ == '__main__':
    base_dir = os.path.dirname(__file__)
    inp = os.path.join(base_dir, 'reseau/Scenario 1/centre.inp')
    high_opt = os.path.join(base_dir, 'reseau/Scenario 1/High_Demand.inp')
    low_opt = os.path.join(base_dir, 'reseau/Scenario 1/Low_Demand.inp')

    # 1. Ajouter la forte demande globale sur le réseau de base
    import wntr
    wn_opt = wntr.network.WaterNetworkModel(inp)
    num_houses = sum(1 for name in wn_opt.junction_name_list if name.startswith('M'))
    peak = max(5.0, num_houses * 0.5)
    modify_global_demand(inp, high_opt, demand_change_L_s=peak)
    
    # 2. Optimiser ce réseau en pic de demande pour grossir les tuyaux et ajuster les réservoirs
    optimize_network(high_opt, high_opt, min_pressure_bars=1)
    
    # 3. Créer le réseau "Low Demand" en reprenant le réseau optimisé (gros tuyaux, gros réservoir) 
    # et en RESTAURANT les petites demandes du fichier Ville.inp original
    restore_original_demands(high_opt, inp, low_opt)

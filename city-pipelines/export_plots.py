import os
import csv
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

# --- Options de visualisation ---
SHOW_NAN_POINTS = True  # Mettre à True pour afficher les points NaN (données manquantes / capteurs cassés)

def plot_nan_indicators(ax, times, data):
    """Affiche une indication visuelle (croix rouges) pour les données NaN."""
    if not SHOW_NAN_POINTS:
        return
    nan_times = [t for t, d in zip(times, data) if np.isnan(d)]
    if not nan_times:
        return
    
    # On place les croix tout en bas du graphe
    ymin, ymax = ax.get_ylim()
    y_pos = ymin + (ymax - ymin) * 0.02
    ax.plot(nan_times, [y_pos] * len(nan_times), 'rx', markersize=5, label='Capteur HS (NaN)', alpha=0.7)

# Fichier par défaut
CSV_PATH = 'C:/Users/ulric/Desktop/Stage/Stage_Partie2/citites-pipelines/reseau/Scenario 2/export_realiste.csv'

if not os.path.exists(CSV_PATH):
    print(f"Erreur : Le fichier {CSV_PATH} n'existe pas.")
    exit()

print(f"Lecture de {CSV_PATH}...")

# Dictionnaires pour stocker les séries temporelles
times = []
pressures = {}
velocities = {}
flowrates = {}

with open(CSV_PATH, 'r') as f:
    reader = csv.reader(f, delimiter='|')
    header = next(reader)
    
    # Identifier les indices des colonnes dynamiquement
    t_idx = header.index('t')
    
    x_cols = [h for h in header if h.startswith('x_')]
    num_pipes = len(x_cols) // 5
    pipe_ids = [str(i+1) for i in range(num_pipes)]
    
    for i in range(num_pipes):
        idx_p = i * 5 + 0
        idx_v = i * 5 + 2
        idx_q = i * 5 + 3
        pressures[f'x_{idx_p}'] = []
        pressures[f'yc_{idx_p}'] = []
        velocities[f'x_{idx_v}'] = []
        velocities[f'yc_{idx_v}'] = []
        flowrates[f'x_{idx_q}'] = []
        flowrates[f'yc_{idx_q}'] = []
    
    # Lecture des données
    for row in reader:
        # Heures au lieu de secondes pour plus de lisibilité
        times.append(float(row[t_idx]) / 3600.0)
        
        for i in range(num_pipes):
            idx_p = i * 5 + 0
            idx_v = i * 5 + 2
            idx_q = i * 5 + 3
            
            p_val = float(row[header.index(f'x_{idx_p}')])
            pressures[f'x_{idx_p}'].append(np.nan if p_val == -1.0 else p_val)
            p_val_yc = float(row[header.index(f'yc_{idx_p}')])
            pressures[f'yc_{idx_p}'].append(np.nan if p_val_yc == -1.0 else p_val_yc)
            
            v_val = float(row[header.index(f'x_{idx_v}')])
            velocities[f'x_{idx_v}'].append(np.nan if v_val == -1.0 else v_val)
            v_val_yc = float(row[header.index(f'yc_{idx_v}')])
            velocities[f'yc_{idx_v}'].append(np.nan if v_val_yc == -1.0 else v_val_yc)
            
            q_val = float(row[header.index(f'x_{idx_q}')])
            flowrates[f'x_{idx_q}'].append(np.nan if q_val == -1.0 else q_val)
            q_val_yc = float(row[header.index(f'yc_{idx_q}')])
            flowrates[f'yc_{idx_q}'].append(np.nan if q_val_yc == -1.0 else q_val_yc)

print(f"{len(times)} points de temps chargés.")

# --- Affichage Graphique Amélioré ---
try:
    plt.style.use('seaborn-v0_8-darkgrid')
except:
    try:
        plt.style.use('seaborn-darkgrid')
    except:
        pass

# Les identifiants de tuyaux et num_pipes sont déjà calculés plus haut

# 4 colonnes : Pression, Pression (Zoom), Vitesse, Débit
fig, axes = plt.subplots(num_pipes, 4, figsize=(24, 4 * num_pipes), sharex='col')

# Si un seul tuyau, axes n'est pas un tableau 2D
if num_pipes == 1:
    axes = [axes]

# Couleurs 
color_p = '#2980b9'
color_p_zoom = '#8e44ad'
color_v = '#e74c3c'
color_q = '#27ae60'

for idx, pipe_id in enumerate(pipe_ids):
    base_idx = idx * 5
    # --- Sous-graphe Pression ---
    ax_p = axes[idx][0]
    
    p_data_x = pressures.get(f'x_{base_idx}', [])
    p_data_yc = pressures.get(f'yc_{base_idx}', [])
    if not p_data_yc:
        p_data_yc = pressures.get(f'Pression_{pipe_id}', [])

    if p_data_x:
        ax_p.plot(times, p_data_x, label=f'Réel {pipe_id}', color='gray', linestyle='--', linewidth=1.5, alpha=0.8)

    if p_data_yc:
        ax_p.plot(times, p_data_yc, label=f'Mesure {pipe_id}', color=color_p, linewidth=2.5)
        # Masquer les NaN pour le remplissage
        p_data_clean = np.array(p_data_yc, dtype=float)
        valid_p = ~np.isnan(p_data_clean)
        if np.any(valid_p):
            ax_p.fill_between(np.array(times)[valid_p], p_data_clean[valid_p], color=color_p, alpha=0.15)
        plot_nan_indicators(ax_p, times, p_data_yc)
    
    ax_p.set_ylabel('Pression (bar)', fontweight='bold', fontsize=11)
    ax_p.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)
    
    if idx == 0:
        ax_p.set_title("Évolution de la Pression", fontsize=15, fontweight='bold', pad=15)

    # --- Sous-graphe Pression (Zoom Nominal) ---
    ax_p_zoom = axes[idx][1]
    
    # Isoler les 24 premières heures
    zoom_times = [t for t in times if t <= 24]
    
    if p_data_x:
        zoom_data_x = p_data_x[:len(zoom_times)]
        ax_p_zoom.plot(zoom_times, zoom_data_x, label=f'Réel {pipe_id}', 
                       color='gray', linestyle='--', linewidth=1.5, alpha=0.8)
                       
    if p_data_yc:
        zoom_data_yc = p_data_yc[:len(zoom_times)]
        ax_p_zoom.plot(zoom_times, zoom_data_yc, label=f'Mesure {pipe_id}', 
                       color=color_p_zoom, linewidth=1.2, marker='.', markersize=4, 
                       drawstyle='steps-post', alpha=0.9)
                       
        clean_zoom = [p for p in zoom_data_yc if not np.isnan(p)]
        if not clean_zoom and p_data_x:
            clean_zoom = [p for p in zoom_data_x if not np.isnan(p)]
            
        if clean_zoom:
            min_p = min(clean_zoom)
            max_p = max(clean_zoom)
            margin = (max_p - min_p) * 0.1
            if margin == 0: margin = 0.1
            ax_p_zoom.set_ylim(min_p - margin, max_p + margin)
            
        plot_nan_indicators(ax_p_zoom, zoom_times, zoom_data_yc)
            
    ax_p_zoom.set_xlim(0, 24)
    
    # Ajout d'une grille fine pour mieux lire les démarcations (sauts)
    ax_p_zoom.minorticks_on()
    ax_p_zoom.grid(True, which='major', color='#bdc3c7', linestyle='-', linewidth=0.8)
    ax_p_zoom.grid(True, which='minor', color='#bdc3c7', linestyle=':', linewidth=0.5, alpha=0.6)

    ax_p_zoom.set_ylabel('Pression (bar)', fontweight='bold', fontsize=11)
    ax_p_zoom.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)
    
    if idx == 0:
        ax_p_zoom.set_title("Zoom Pression (0-24h)", fontsize=15, fontweight='bold', pad=15)
    
    # --- Sous-graphe Vitesse ---
    v_data_x = velocities.get(f"x_{base_idx + 2}", [])
    v_data_yc = velocities.get(f"yc_{base_idx + 2}", [])
    if not v_data_yc:
        v_data_yc = velocities.get(f"Vitesse_{pipe_id}", [])
        
    ax_v = axes[idx][2]
    # Sens d'écoulement nominal
    nom_v = [v for t, v in zip(times, v_data_x if v_data_x else v_data_yc) if t <= 24 and not np.isnan(v)]
    sign_v = -1 if nom_v and np.median(nom_v) < 0 else 1
    
    if v_data_x:
        v_x_oriented = [v * sign_v if not np.isnan(v) else np.nan for v in v_data_x]
        ax_v.plot(times, v_x_oriented, label=f'Réel {pipe_id}', color='gray', linestyle='--', linewidth=1.5, alpha=0.8)

    if v_data_yc:
        v_yc_oriented = [v * sign_v if not np.isnan(v) else np.nan for v in v_data_yc]
        ax_v.plot(times, v_yc_oriented, label=f'Mesure {pipe_id}', color=color_v, linewidth=2.5)
        v_data_clean = np.array(v_yc_oriented, dtype=float)
        valid_v = ~np.isnan(v_data_clean)
        if np.any(valid_v):
            ax_v.fill_between(np.array(times)[valid_v], v_data_clean[valid_v], color=color_v, alpha=0.15)
        plot_nan_indicators(ax_v, times, v_yc_oriented)
    
    ax_v.set_ylabel('Vitesse (m/s)', fontweight='bold', fontsize=11)
    ax_v.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)
    
    if idx == 0:
        ax_v.set_title("Évolution de la Vitesse", fontsize=15, fontweight='bold', pad=15)

    # --- Sous-graphe Débit ---
    q_data_x = flowrates.get(f"x_{base_idx + 3}", [])
    q_data_yc = flowrates.get(f"yc_{base_idx + 3}", [])
    if not q_data_yc:
        q_data_yc = flowrates.get(f"Debit_{pipe_id}", [])
        
    ax_q = axes[idx][3]
    # Sens d'écoulement nominal
    nom_q = [q for t, q in zip(times, q_data_x if q_data_x else q_data_yc) if t <= 24 and not np.isnan(q)]
    sign_q = -1 if nom_q and np.median(nom_q) < 0 else 1
    
    if q_data_x:
        q_x_ls = [q * sign_q * 1000 if not np.isnan(q) else np.nan for q in q_data_x]
        ax_q.plot(times, q_x_ls, label=f'Réel {pipe_id}', color='gray', linestyle='--', linewidth=1.5, alpha=0.8)

    if q_data_yc:
        q_yc_ls = [q * sign_q * 1000 if not np.isnan(q) else np.nan for q in q_data_yc]
        ax_q.plot(times, q_yc_ls, label=f'Mesure {pipe_id}', color=color_q, linewidth=2.5)
        q_data_clean = np.array(q_yc_ls, dtype=float)
        valid_q = ~np.isnan(q_data_clean)
        if np.any(valid_q):
            ax_q.fill_between(np.array(times)[valid_q], q_data_clean[valid_q], color=color_q, alpha=0.15)
        plot_nan_indicators(ax_q, times, q_yc_ls)
    
    ax_q.set_ylabel('Débit (L/s)', fontweight='bold', fontsize=11)
    ax_q.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)

    if idx == 0:
        ax_q.set_title("Évolution du Débit", fontsize=15, fontweight='bold', pad=15)

    # Axe X pour la dernière ligne
    if idx == num_pipes - 1:
        for ax_idx, ax in enumerate([ax_p, ax_p_zoom, ax_v, ax_q]):
            ax.set_xlabel("Temps (Heures)", fontweight='bold', fontsize=12)
            if ax_idx == 1: # Zoom
                ax.xaxis.set_major_locator(MultipleLocator(4))
                ax.xaxis.set_minor_locator(MultipleLocator(1))
            else:
                ax.xaxis.set_major_locator(MultipleLocator(24))
                ax.xaxis.set_minor_locator(MultipleLocator(6))

# Titre global et ajustements
fig.suptitle("Simulation du Réseau d'Eau", fontsize=22, fontweight='bold', y=0.98, color='#2c3e50')
plt.tight_layout()
fig.subplots_adjust(top=0.92)  # Ajuster l'espace pour le titre principal

# Sauvegarde d'un aperçu
plt.savefig('Simulation.png', dpi=150, bbox_inches='tight')
plt.show()

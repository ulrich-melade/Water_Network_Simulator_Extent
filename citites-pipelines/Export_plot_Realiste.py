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
    p_indices = {h: i for i, h in enumerate(header) if 'Pression_' in h}
    v_indices = {h: i for i, h in enumerate(header) if 'Vitesse_' in h}
    q_indices = {h: i for i, h in enumerate(header) if 'Debit_' in h}
    
    for h in p_indices: pressures[h] = []
    for h in v_indices: velocities[h] = []
    for h in q_indices: flowrates[h] = []
    
    # Lecture des données
    for row in reader:
        # Heures au lieu de secondes pour plus de lisibilité
        times.append(float(row[t_idx]) / 3600.0)
        
        for h, i in p_indices.items():
            val = float(row[i])
            pressures[h].append(np.nan if val == -1.0 else val)
            
        for h, i in v_indices.items():
            val = float(row[i])
            velocities[h].append(np.nan if val == -1.0 else val)

        for h, i in q_indices.items():
            val = float(row[i])
            flowrates[h].append(np.nan if val == -1.0 else val)

print(f"{len(times)} points de temps chargés.")

# --- Affichage Graphique Amélioré ---
try:
    plt.style.use('seaborn-v0_8-darkgrid')
except:
    try:
        plt.style.use('seaborn-darkgrid')
    except:
        pass

num_pipes = len(pressures)
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

for idx, (p_name, p_data) in enumerate(pressures.items()):
    pipe_id = p_name.split('_')[-1]
    
    # --- Sous-graphe Pression ---
    ax_p = axes[idx][0]
    ax_p.plot(times, p_data, label=f'Pression {pipe_id}', color=color_p, linewidth=2.5)
    
    # Masquer les NaN pour le remplissage
    p_data_clean = np.array(p_data, dtype=float)
    valid_p = ~np.isnan(p_data_clean)
    if np.any(valid_p):
        ax_p.fill_between(np.array(times)[valid_p], p_data_clean[valid_p], color=color_p, alpha=0.15)
        
    plot_nan_indicators(ax_p, times, p_data)
    
    ax_p.set_ylabel('Pression (bar)', fontweight='bold', fontsize=11)
    ax_p.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)
    
    if idx == 0:
        ax_p.set_title("Évolution de la Pression", fontsize=15, fontweight='bold', pad=15)

    # --- Sous-graphe Pression (Zoom Nominal) ---
    ax_p_zoom = axes[idx][1]
    
    # Isoler les 24 premières heures
    zoom_times = [t for t in times if t <= 24]
    zoom_data = p_data[:len(zoom_times)]
    
    # Ajout de drawstyle='steps-post' et de marqueurs pour bien démarquer les sauts (typique pour les pompes/vannes)
    ax_p_zoom.plot(zoom_times, zoom_data, label=f'Pression {pipe_id} (0-24h)', 
                   color=color_p_zoom, linewidth=1.2, marker='.', markersize=4, 
                   drawstyle='steps-post', alpha=0.9)
    
    if zoom_data:
        clean_zoom = [p for p in zoom_data if not np.isnan(p)]
        if clean_zoom:
            min_p = min(clean_zoom)
            max_p = max(clean_zoom)
            margin = (max_p - min_p) * 0.1
            if margin == 0: margin = 0.1
            ax_p_zoom.set_ylim(min_p - margin, max_p + margin)
            
    ax_p_zoom.set_xlim(0, 24)
    
    # Ajout d'une grille fine pour mieux lire les démarcations (sauts)
    ax_p_zoom.minorticks_on()
    ax_p_zoom.grid(True, which='major', color='#bdc3c7', linestyle='-', linewidth=0.8)
    ax_p_zoom.grid(True, which='minor', color='#bdc3c7', linestyle=':', linewidth=0.5, alpha=0.6)

    plot_nan_indicators(ax_p_zoom, zoom_times, zoom_data)

    ax_p_zoom.set_ylabel('Pression (bar)', fontweight='bold', fontsize=11)
    ax_p_zoom.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)
    
    if idx == 0:
        ax_p_zoom.set_title("Zoom Pression (0-24h)", fontsize=15, fontweight='bold', pad=15)
    
    # --- Sous-graphe Vitesse ---
    v_name = f"yc_Vitesse_{pipe_id}" if f"yc_Vitesse_{pipe_id}" in velocities else f"Vitesse_{pipe_id}"
    v_data = velocities.get(v_name, [])
    ax_v = axes[idx][2]
    if v_data:
        # On oriente la courbe selon le sens d'écoulement nominal (pour éviter que abs() ne plie la courbe à 0)
        nom_v = [v for t, v in zip(times, v_data) if t <= 24 and not np.isnan(v)]
        sign_v = -1 if nom_v and np.median(nom_v) < 0 else 1
        v_data_oriented = [v * sign_v if not np.isnan(v) else np.nan for v in v_data]
        
        ax_v.plot(times, v_data_oriented, label=f'Vitesse {pipe_id}', color=color_v, linewidth=2.5)
        v_data_clean = np.array(v_data_oriented, dtype=float)
        valid_v = ~np.isnan(v_data_clean)
        if np.any(valid_v):
            ax_v.fill_between(np.array(times)[valid_v], v_data_clean[valid_v], color=color_v, alpha=0.15)
            
    plot_nan_indicators(ax_v, times, v_data_oriented)
    
    ax_v.set_ylabel('Vitesse (m/s)', fontweight='bold', fontsize=11)
    ax_v.legend(loc='upper right', frameon=True, shadow=True, fancybox=True)
    
    if idx == 0:
        ax_v.set_title("Évolution de la Vitesse", fontsize=15, fontweight='bold', pad=15)

    # --- Sous-graphe Débit ---
    q_name = f"yc_Debit_{pipe_id}" if f"yc_Debit_{pipe_id}" in flowrates else f"Debit_{pipe_id}"
    q_data = flowrates.get(q_name, [])
    ax_q = axes[idx][3]
    if q_data:
        # Même logique que pour la vitesse : on oriente selon le sens nominal
        nom_q = [q for t, q in zip(times, q_data) if t <= 24 and not np.isnan(q)]
        sign_q = -1 if nom_q and np.median(nom_q) < 0 else 1
        q_data_ls = [q * sign_q * 1000 if not np.isnan(q) else np.nan for q in q_data]
        
        ax_q.plot(times, q_data_ls, label=f'Débit {pipe_id}', color=color_q, linewidth=2.5)
        q_data_clean = np.array(q_data_ls, dtype=float)
        valid_q = ~np.isnan(q_data_clean)
        if np.any(valid_q):
            ax_q.fill_between(np.array(times)[valid_q], q_data_clean[valid_q], color=color_q, alpha=0.15)
            
    plot_nan_indicators(ax_q, times, q_data_ls)
    
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

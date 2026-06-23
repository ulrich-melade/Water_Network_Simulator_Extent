# Projet de simulation de réseaux d'eau réaliste

Ce projet implémente un simulateur hydraulique avancé pour des réseaux d'eau, capable de modéliser des scénarios complexes incluant des demandes variables, des événements dynamiques et des conditions de capteurs dégradées.

## Caractéristiques Principales

### 1. Courbe de Demande Réaliste (24h)
- **Modèle Continu** : Utilise une courbe de demande journalière continue, basée sur des profils de consommation résidentielle typiques, évitant les transitions binaires brusques.
- **Interpolation Cosinus** : Assure des transitions douces entre les heures pour un réalisme accru.
- **Pic Variable** : Permet d'ajuster facilement le pic de demande (ex: 1.0 p.u.) et la forme de la courbe.

### 2. Gestion Dynamique des Événements
Le simulateur gère trois types d'événements, injectés dynamiquement sans nécessiter de fichiers externes :
- **Fuites** (`leak`) :
    - Injectées comme des coefficients d'émetteur sur les nœuds (modèle Epanet).
    - Converties en aire de fuite pour compatibilité avec WNTR.
    - Les fuites persistent pendant toute la durée du scénario.
- **Surges** (`surge`) :
    - Ajout d'une demande supplémentaire sur des nœuds spécifiques pour simuler des surconsommations (ex: lavage de voiture, irrigation).
    - La demande est ajoutée au profil de base du nœud.
- **Capteurs Cassés** (`broken`) :
    - Marque des nœuds spécifiques comme défaillants.
    - Entraîne l'insertion de valeurs `NaN` (Not a Number) dans les données exportées, simulant des capteurs HS.

### 3. Intégration WNTR
- **Configuration Dynamique** : Les paramètres du simulateur (durée, pas de temps, événements) sont définis dans un fichier de configuration JSON.
- **Correction de Compatibilité** : Implémente un correctif pour gérer les erreurs de validation de WNTR concernant les grandeurs positives, permettant l'utilisation de rugosités nulles ou négatives (si nécessaire pour le modèle) et assurant la stabilité de la simulation.
- **Simulation Multi- pas** : Exécute la simulation avec un pas de temps fin (ex: 1 minute) pour capturer précisément les dynamiques du réseau.

### 4. Export de Données Enrichi
- **Format** : Export des données au format `|` (pipe-delimited) pour faciliter l'analyse.
- **Champs** : Inclut la pression, la vitesse, le débit, le multiplicateur de demande et les indicateurs d'événements pour chaque nœud et chaque pas de temps.
- **Gestion des Erreurs** : Les valeurs `NaN` sont préservées pour les capteurs défaillants, et les valeurs invalides (comme -1.0) sont converties en `NaN` dans l'export.

## Structure du Projet

### Fichiers Principaux
- `Simulateur_Realiste.py` : Le simulateur central. Gère la configuration, l'application des événements, la simulation et l'export des données.
- `Export_plot_Realiste.py` : Script d'analyse et de visualisation. Génère des graphiques détaillés des pressions, vitesses et débits, avec des options pour afficher les points de données manquants.

### Données d'Entrée
- `Low_Demand.inp` : Fichier de topologie du réseau au format EPANET. Sert de base pour la simulation.

## Configuration

### Paramètres de Simulation
Les paramètres du simulateur sont définis dans `Simulateur_Realiste.py` dans la section `# --- CONFIGURATION ---
` :
- `INP_FILE` : Chemin vers le fichier INP.
- `SCENARIO` : Dictionnaire contenant les paramètres spécifiques au scénario :
    - `duration_hours` : Durée totale de la simulation en heures.
    - `demand_peak_L_s` : Pic de demande en L/s (correspondant à 1.0 p.u. de la courbe).
    - `time_step_sec` : Pas de temps de la simulation en secondes.
    - `events` : Liste des événements à appliquer.

### Événements
La liste `events` permet de définir les scénarios :
```json
[
    {
        "type": "leak",
        "coeff": 0.75,          // Coefficient d'émetteur (0-1)
        "duration_h": 24.0,     // Durée de l'événement
        "start_time_h": 0.0,    // Heure de début
        "nodes": ["N1", "N2"]  // Nœuds affectés
    },
    {
        "type": "surge",
        "demand_L_s": 5.0,      // Surconsommation en L/s
        "duration_h": 8.0,
        "start_time_h": 12.0,
        "nodes": ["N3"]
    },
    {
        "type": "broken",
        "nodes": ["N1"]           // Nœud avec capteur défaillant
    }
]
```

## Installation

### Prérequis
- Python 3.x
- Les bibliothèques suivantes :
    - `wntr` : Pour la simulation hydraulique.
    - `numpy` : Pour les calculs numériques.
    - `matplotlib` : Pour la visualisation des résultats.

### Installation
1. Clonez le dépôt ou téléchargez les fichiers.
2. Installez les dépendances :
   ```bash
   pip install wntr numpy matplotlib
   ```

## Utilisation

### Exécuter le Simulateur
Pour exécuter une simulation avec le fichier de configuration par défaut :
```bash
python Simulateur_Realiste.py
```

### Exécuter et Visualiser
Pour lancer la simulation et générer les graphiques immédiatement :
```bash
python Export_plot_Realiste.py
```

### Personnaliser la Simulation
Modifiez les paramètres dans `Simulateur_Realiste.py` :
```python
# --- CONFIGURATION ---
INP_FILE = "Low_Demand.inp"
etapes = {
    "duration_hours": 48.0,        # Durée modifiée
    "demand_peak_L_s": 1.5,        # Pic de demande augmenté
    "time_step_sec": 300,          # Pas de temps modifié
    "events": [
        # Définition des événements personnalisés
    ]
}
```

## Visualisation

Le script `Export_plot_Realiste.py` génère des graphiques interactifs avec les caractéristiques suivantes :
- **PlusieursSous-graphes** : Pour chaque nœud, une section affiche:
    1.  **Pression** : Vue d'ensemble sur toute la durée.
    2.  **Pression (Zoom 0-24h)** : Vue détaillée des 24 premières heures avec les sauts de pression mis en évidence.
    3.  **Vitesse** : Vitesse d'écoulement orientée (ne retourne pas à zéro à cause des changements de direction).
    4.  **Débit** : Débit dans le tuyau.
- **Marqueurs de Capteurs Cassés** : Les points `NaN` sont représentés par des croix rouges (`rx`) en bas du graphe.
- **Option d'Affichage** : La variable `SHOW_NAN_POINTS` dans `Export_plot_Realiste.py` permet d'activer ou de désactiver l'affichage des points `NaN`.
- **Esthétique** : Utilisation de styles de graphes modernes (`seaborn-v0_8-darkgrid`), de légendes claires, et de grilles fines pour une meilleure lisibilité.

## Exemple de Configuration de Scénario

Voici un exemple de configuration pour un scénario avec une fuite majeure au milieu de la matinée et une surconsommation l'après-midi :
```python
etapes = {
    "duration_hours": 24.0,
    "demand_peak_L_s": 1.0,
    "time_step_sec": 30,
    "events": [
        {
            "type": "leak",
            "coeff": 0.9,
            "duration_h": 24.0,
            "start_time_h": 0
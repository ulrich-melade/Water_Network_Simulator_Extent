import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import math, random, networkx as nx
from perlin_noise import PerlinNoise
import numpy as np

# Remplacement de la librairie 'noise' par 'perlin-noise' (pas réussi à lancer l'autre)
_noise_generator = PerlinNoise(octaves=2, seed=42)
def pnoise2(x, y):
    # On simule le comportement de pnoise2 (valeurs entre -1 et 1)
    return _noise_generator([x, y]) * 2.0


def get_elevation(x, y, hauteur_min=100, hauteur_max=150):
    """
    x, y           : coordonnées du point
    hauteur_min    : altitude minimale (mètres)
    hauteur_max    : altitude maximale (mètres)
    """
    raw = pnoise2(x, y)
    return hauteur_min + (raw + 1) / 2 * (hauteur_max - hauteur_min)

# ══════════════════════════════════════════════════════════════════
# PALETTE
# ══════════════════════════════════════════════════════════════════

BG_DEEP = "#5b74a7"  # fenetre
BG_DARK = "#4766af"
BG_CARD = "#06192C"
BG_INPUT = "#132248"
BORDER = "#1e3a6a"
ACCENT = "#2563eb"
ACCENT_HVR = "#1d4ed8"
TXT_MAIN = "#dce9fb"
TXT_SUB = "#6a93c8"
TXT_DIM = "#3a5a8a"

NODE_RES = "#e9ba0e"  # réservoir  — bleu clair
NODE_JUNC = "#06112a"  # jonction   — bleu
NODE_HOUSE = "#f163a3"  # maison     — indigo
NODE_FAULT = "#ef4444"  # cassé      — rouge
NODE_SURGE = "#f59e0b"  # surge      — orange
NODE_ZERO = "#6b7280"  # pression 0 — gris
EDGE_MAIN = "#bfc5ce"  # conduite principale
EDGE_SEC = "#26bef0"  # conduite secondaire (vers maison)


# ══════════════════════════════════════════════════════════════════
#  Application
# ══════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Réseau d'eau")
        self.geometry("1280x720")
        self.minsize(900, 500)
        self.configure(fg_color=BG_DEEP)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=420)
        self.grid_columnconfigure(1, weight=1)
        self.topbar()
        self.main()
        self.canvas_panel()

    # ══════════════════════════════════════════════════════════════════
    #  METHODES UI
    # ══════════════════════════════════════════════════════════════════

    def topbar(self):
        top = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=BG_DARK)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_propagate(False)
        top.grid_rowconfigure(0, weight=1)
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Réseau d'eau",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TXT_MAIN).grid(row=0, column=0)

    def section(self, parent, row, num, title):
        f = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        f.grid(row=row, column=0, padx=20, pady=(18, 6), sticky="ew")
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=num, font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=ACCENT, width=28, fg_color=BG_CARD,
                     corner_radius=6).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TXT_MAIN, anchor="w").grid(row=0, column=1, sticky="w")
        return row + 1

    def field(self, parent, row, col, label, placeholder):
        f = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        f.grid(row=row, column=col, padx=14, pady=10, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=11),
                     text_color=TXT_SUB, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 4))
        entry = ctk.CTkEntry(f, height=38, corner_radius=8,
                             fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                             text_color=TXT_MAIN, placeholder_text=placeholder,
                             placeholder_text_color=TXT_DIM, font=ctk.CTkFont(size=12))
        entry.grid(row=1, column=0, sticky="ew")
        return entry

    def _optmenu(self, parent, row, col, label, values):
        f = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        f.grid(row=row, column=col, padx=14, pady=10, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=11),
                     text_color=TXT_SUB, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 4))
        om = ctk.CTkOptionMenu(f, values=values, height=38, corner_radius=8,
                               fg_color=BG_INPUT, button_color=BORDER, button_hover_color=ACCENT,
                               text_color=TXT_MAIN, font=ctk.CTkFont(size=12),
                               dropdown_fg_color=BG_CARD, dropdown_hover_color=BORDER,
                               dropdown_text_color=TXT_MAIN)
        om.grid(row=1, column=0, sticky="ew")
        return om

    def _switch(self, parent, row, col, label, command=None):
        f = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        f.grid(row=row, column=col, padx=14, pady=10, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=11),
                     text_color=TXT_SUB, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 4))
        sw = ctk.CTkSwitch(f, text="", width=48,
                           button_color=ACCENT, button_hover_color=ACCENT_HVR,
                           progress_color=ACCENT, fg_color=BORDER, command=command)
        sw.grid(row=1, column=0, sticky="w")
        return sw

    # ══════════════════════════════════════════════════════════════════
    #  FORMULAIRE
    # ══════════════════════════════════════════════════════════════════

    def main(self):
        left = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_DEEP)
        left.grid(row=1, column=0, sticky="nsew")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(left, corner_radius=0, fg_color=BG_DEEP,
                                        scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=ACCENT)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        row_idx = 0
        self.entries = {}
        self.optmenus = {}
        self.switches = {}

        row_idx = self.section(scroll, row_idx, "01", "Paramètres")
        f1 = ctk.CTkFrame(scroll, corner_radius=12, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        f1.grid(row=row_idx, column=0, padx=20, pady=(0, 12), sticky="ew")
        f1.grid_columnconfigure((0, 1), weight=1)
        row_idx += 1
        for i, (key, label, ph) in enumerate([
            ("Nombre de maisons", "Nombre de maisons", "ex : 10"),
            ("Nombre de chateaux d'eau", "Nombre de chateaux d'eau", "ex : 5"),
            ("Dénivelé", "Dénivelé", "en %"),
            ("Hauteur min","Hauteur min", "en m"),
            ("Hauteur max", "Hauteur max", "en m"),
        ]):
            self.entries[key] = self.field(f1, i // 2, i % 2, label, ph)

        row_idx = self.section(scroll, row_idx, "02", "Zone")
        f2 = ctk.CTkFrame(scroll, corner_radius=12, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        f2.grid(row=row_idx, column=0, padx=20, pady=(0, 12), sticky="ew")
        f2.grid_columnconfigure((0, 1), weight=1)
        row_idx += 1
        self.optmenus["Zone"] = self._optmenu(f2, 0, 0, "Type de zone", ["Rurale", "Urbaine"])
        self.entries["Surface"] = self.field(f2, 0, 1, "Surface", "en km²")

        row_idx = self.section(scroll, row_idx, "03", "Conduites")
        f3 = ctk.CTkFrame(scroll, corner_radius=12, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        f3.grid(row=row_idx, column=0, padx=20, pady=(0, 12), sticky="ew")
        f3.grid_columnconfigure((0, 1), weight=1)
        row_idx += 1
        self.optmenus["Formule pertes"] = self._optmenu(
            f3, 0, 0, "Formule pertes de charge", ["Darcy-Weisbach", "Hazen-Williams"])
        self.entries["Rugosité"] = self.field(f3, 0, 1, "Rugosité", "D-W: 0.02 | H-W: 130")
        self.entries["Diamètre min"] = self.field(f3, 1, 0, "Diamètre min (mm)", "ex : 60")
        self.entries["Diamètre max"] = self.field(f3, 1, 1, "Diamètre max (mm)", "ex : 300")

        row_idx = self.section(scroll, row_idx, "04", "Simulation")
        f5 = ctk.CTkFrame(scroll, corner_radius=12, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        f5.grid(row=row_idx, column=0, padx=20, pady=(0, 12), sticky="ew")
        f5.grid_columnconfigure((0, 1), weight=1)
        row_idx += 1
        self.optmenus["Mode simulation"] = self._optmenu(
            f5, 0, 0, "Mode", ["Statique (0h)", "Dynamique (24h)", "Personnalisé"])
        self.entries["Durée"] = self.field(f5, 0, 1, "Durée (h)", "ex : 12")

        row_idx = self.section(scroll, row_idx, "05", "Capteurs & Bruit")
        f6 = ctk.CTkFrame(scroll, corner_radius=12, fg_color=BG_CARD, border_width=1, border_color=BORDER)
        f6.grid(row=row_idx, column=0, padx=20, pady=(0, 12), sticky="ew")
        f6.grid_columnconfigure((0, 1), weight=1)
        row_idx += 1
        self.switches["Bruit"] = self._switch(f6, 0, 0, "Activer le bruit gaussien", command=self.toggle_bruit)
        self.entries["Écart-type"] = self.field(f6, 0, 1, "Écart-type bruit", "ex : 0.05")
        self.entries["% cassés"] = self.field(f6, 1, 0, "% capteurs cassés", "ex : 10")
        self.entries["Écart-type"].configure(state="disabled")

        btn_frame = ctk.CTkFrame(scroll, corner_radius=0, fg_color="transparent")
        btn_frame.grid(row=row_idx, column=0, padx=20, pady=(8, 28), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(btn_frame, text="Générer réseau", height=48, corner_radius=12,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HVR, text_color="#ffffff",
                      command=self.on_ok).grid(row=0, column=0, padx=(0, 6), sticky="ew")

        ctk.CTkButton(btn_frame, text="Aléatoire", height=48, corner_radius=12,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color=BG_CARD, hover_color=BORDER, text_color=TXT_SUB,
                      border_width=1, border_color=BORDER,
                      command=self.on_random).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        self.feedback = ctk.CTkLabel(btn_frame, text="", font=ctk.CTkFont(size=11),
                                     text_color="#3dba6f", wraplength=360)
        self.feedback.grid(row=1, column=0, columnspan=2, pady=(8, 0))

    # ══════════════════════════════════════════════════════════════════
    #  CANVAS
    # ══════════════════════════════════════════════════════════════════

    def canvas_panel(self):
        right = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_DARK)
        right.grid(row=1, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(right, height=44, corner_radius=0, fg_color=BG_DEEP)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        self._info_label = ctk.CTkLabel(
            bar, text="Générez un réseau puis cliquez sur un nœud",
            font=ctk.CTkFont(size=11), text_color=TXT_MAIN)
        self._info_label.grid(row=0, column=0, sticky="w", padx=16)

        ctk.CTkButton(bar, text="Exporter .inp", width=120, height=30, corner_radius=8,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HVR,
                      command=self.export_inp).grid(row=0, column=1, padx=6)

        ctk.CTkButton(bar, text="Exporter Image", width=120, height=30, corner_radius=8,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color="#8e44ad", hover_color="#9b59b6",
                      command=self.export_image).grid(row=0, column=2, padx=6)

        ctk.CTkButton(bar, text="Reset fautes", width=110, height=30, corner_radius=8,
                      font=ctk.CTkFont(size=11), fg_color=BG_CARD, hover_color=BORDER,
                      border_width=1, border_color=BORDER, text_color=TXT_SUB,
                      command=self.reset_faults).grid(row=0, column=3, padx=(0, 10))

        self.cv = tk.Canvas(right, bg=BG_DEEP, bd=0,
                            highlightthickness=1, highlightbackground=BORDER)
        self.cv.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.cv.bind("<Button-1>", self._on_click)
        self.cv.bind("<Configure>", lambda e: self._redraw())

        # légende
        leg = ctk.CTkFrame(right, height=36, corner_radius=0, fg_color=BG_DEEP)
        leg.grid(row=2, column=0, sticky="ew")
        leg.grid_propagate(False)
        for col, txt in [
            ("#0B97F4", "Chateau d'eau"),
            ("#11D454", "Jonction"),
            (NODE_HOUSE, "Maison"),
            (NODE_FAULT, "Capteur cassé"),
            (NODE_SURGE, "Demande ×5"),
            (NODE_ZERO, "Fuite"),
        ]:
            f = ctk.CTkFrame(leg, fg_color="transparent")
            f.pack(side="left", padx=10)
            tk.Canvas(f, width=10, height=10, bg=col, highlightthickness=0).pack(side="left", padx=(0, 3))
            ctk.CTkLabel(f, text=txt, font=ctk.CTkFont(size=9), text_color=TXT_SUB).pack(side="left")

        self._G = None
        self._pos_px = {}
        self._node_state = {}
        self._node_items = {}
        self._params = {}

    # ══════════════════════════════════════════════════════════════════
    #  CONSTRUCTION DU RESEAU
    # ══════════════════════════════════════════════════════════════════

    def _build_graph(self, params):
        import networkx as nx
        import math
        import random
        import numpy as np

        try:
            n_maisons = int(params.get("n_maisons", 10))
        except:
            n_maisons = 10
            
        try:
            n_chateaux = int(params.get("n_chateaux", 1))
        except:
            n_chateaux = 1

        zone = params.get("Zone", "Urbaine")
        
        G = nx.Graph()
        pos = {}
        
        if zone == "Urbaine":
            n_cells = max(1, int(math.ceil(math.sqrt(n_maisons * 1.5))))
            grid = nx.grid_2d_graph(n_cells, n_cells)
            cell_size = 1.6 / max(1, (n_cells - 1))
            
            for (i, j) in grid.nodes():
                node_name = f"J_{i}_{j}"
                G.add_node(node_name, type="junction")
                jx = -0.8 + i * cell_size + random.uniform(-0.2, 0.2) * cell_size
                jy = -0.8 + j * cell_size + random.uniform(-0.2, 0.2) * cell_size
                pos[node_name] = np.array([jx, jy])
                
            for (u, v) in grid.edges():
                G.add_edge(f"J_{u[0]}_{u[1]}", f"J_{v[0]}_{v[1]}")
                
            edges = list(G.edges())
            num_remove = int(len(edges) * 0.15)
            random.shuffle(edges)
            for u, v in edges:
                if num_remove <= 0: break
                G.remove_edge(u, v)
                if not nx.is_connected(G): G.add_edge(u, v)
                else: num_remove -= 1
                    
            mapping = {old: f"J{idx+1}" for idx, old in enumerate(list(G.nodes()))}
            G = nx.relabel_nodes(G, mapping)
            pos = {mapping[old]: p for old, p in pos.items()}
            
            edges_list = list(G.edges())
            random.shuffle(edges_list)
            while len(edges_list) < n_maisons: edges_list.extend(edges_list)
                
            j_count = len(G.nodes())
            for i in range(n_maisons):
                u, v = edges_list[i]
                if G.has_edge(u, v): G.remove_edge(u, v)
                j_count += 1
                j_new = f"J{j_count}"
                G.add_node(j_new, type="junction")
                pos[j_new] = (pos[u] + pos[v]) / 2.0
                G.add_edge(u, j_new)
                G.add_edge(j_new, v)
                m_new = f"M{i+1}"
                G.add_node(m_new, type="house")
                G.add_edge(j_new, m_new)
                vec = pos[v] - pos[u]
                perp = np.array([-vec[1], vec[0]])
                if np.linalg.norm(perp) > 0: perp = perp / np.linalg.norm(perp)
                side = random.choice([-1, 1])
                pos[m_new] = pos[j_new] + perp * side * cell_size * 0.3
                edges_list[i] = (u, j_new)
                
            junction_nodes = [n for n in G.nodes() if G.nodes[n].get("type") == "junction"]
            if not junction_nodes: junction_nodes = list(G.nodes())
            
            for i in range(n_chateaux):
                u = random.choice(junction_nodes)
                c_new = f"C{i+1}"
                G.add_node(c_new, type="chateau")
                G.add_edge(u, c_new)
                vec = pos[u]
                if np.linalg.norm(vec) > 0: vec = vec / np.linalg.norm(vec)
                else: vec = np.array([1.0, 0.0])
                pos[c_new] = pos[u] + vec * cell_size * 0.5
                
        else:
            # 1. Create a spine (Main Road)
            n_spine = max(3, n_maisons // 3)
            spine_len = 2.0
            seg_len = spine_len / n_spine
            
            spine_nodes = []
            current_x = -1.0
            current_y = 0.0
            
            for i in range(n_spine + 1):
                name = f'J_spine_{i}'
                G.add_node(name, type='junction')
                pos[name] = np.array([current_x, current_y])
                spine_nodes.append(name)
                if i > 0:
                    G.add_edge(f'J_spine_{i-1}', name)
                    
                current_x += seg_len
                current_y += random.uniform(-0.1, 0.1) # Wavy road
                
            # 2. Add some branches (Ribs)
            n_branches = max(1, n_maisons // 5)
            branch_nodes = list(spine_nodes[1:-1]) # avoid branches at extreme ends
            if not branch_nodes: branch_nodes = spine_nodes
            random.shuffle(branch_nodes)
            
            j_count = 0
            all_edges = list(G.edges())
            
            for i in range(min(n_branches, len(branch_nodes))):
                parent = branch_nodes[i]
                side = random.choice([-1, 1])
                b_len = random.randint(1, 3)
                
                curr = parent
                curr_pos = pos[parent]
                for step in range(b_len):
                    j_count += 1
                    name = f'J_branch_{j_count}'
                    G.add_node(name, type='junction')
                    
                    # perpendicular-ish to x axis
                    offset = np.array([random.uniform(-0.1, 0.1), side * random.uniform(0.2, 0.4)])
                    pos[name] = curr_pos + offset
                    
                    G.add_edge(curr, name)
                    all_edges.append((curr, name))
                    
                    curr = name
                    curr_pos = pos[name]

            # 3. Distribute houses on all_edges
            random.shuffle(all_edges)
            while len(all_edges) < n_maisons:
                all_edges.extend(all_edges) # duplicate edges if needed
                
            j_s_count = 0
            for i in range(n_maisons):
                u, v = all_edges[i]
                if G.has_edge(u, v):
                    G.remove_edge(u, v)
                    
                t = random.uniform(0.15, 0.85)
                j_s_count += 1
                j_new = f'J_s_{j_s_count}'
                G.add_node(j_new, type='junction')
                pos[j_new] = pos[u] * (1-t) + pos[v] * t
                
                G.add_edge(u, j_new)
                G.add_edge(j_new, v)
                
                m_new = f'M{i+1}'
                G.add_node(m_new, type='house')
                G.add_edge(j_new, m_new)
                
                vec = pos[v] - pos[u]
                perp = np.array([-vec[1], vec[0]])
                if np.linalg.norm(perp) > 0:
                    perp = perp / np.linalg.norm(perp)
                side = random.choice([-1, 1])
                pos[m_new] = pos[j_new] + perp * side * random.uniform(0.05, 0.15)
                
                if random.random() < 0.5:
                    all_edges[i] = (u, j_new)
                else:
                    all_edges[i] = (j_new, v)
                    
            # 4. Add chateaux randomly across the village
            junction_nodes = [n for n in G.nodes() if G.nodes[n].get('type') == 'junction']
            if not junction_nodes: junction_nodes = list(G.nodes())
            random.shuffle(junction_nodes)
            
            for i in range(n_chateaux):
                u = junction_nodes[i % len(junction_nodes)]
                c_new = f'C{i+1}'
                G.add_node(c_new, type='chateau')
                G.add_edge(u, c_new)
                
                neighbors = list(G.neighbors(u))
                if neighbors and neighbors[0] != c_new:
                    vec = pos[u] - pos[neighbors[0]]
                    if np.linalg.norm(vec) > 0:
                        vec = vec / np.linalg.norm(vec)
                    else:
                        vec = np.array([1.0, 0.0])
                else:
                    vec = np.array([1.0, 0.0])
                    
                pos[c_new] = pos[u] + vec * 0.2

        w = max(self.cv.winfo_width(), 200)
        h = max(self.cv.winfo_height(), 200)
        margin_x = 0.05 * w
        margin_y = 0.05 * h
        
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        range_x = max_x - min_x
        if range_x == 0: range_x = 1
        range_y = max_y - min_y
        if range_y == 0: range_y = 1
        
        for i in pos:
            px = (pos[i][0] - min_x) / range_x
            py = (pos[i][1] - min_y) / range_y
            pos[i][0] = margin_x + px * (w - 2 * margin_x)
            pos[i][1] = margin_y + py * (h - 2 * margin_y)

        # Assign broken sensors based on pct_casses
        try:
            pct_broken = float(params.get("pct_casses", 0))
        except:
            pct_broken = 0.0

        if pct_broken > 0:
            nodes_to_break = random.sample(list(G.nodes()), int(len(G.nodes()) * (pct_broken / 100.0)))
            for n in nodes_to_break:
                self._node_state[n] = "broken"
                
        return G, pos
    def _layout(self, G, pos):

        return pos

    # ══════════════════════════════════════════════════════════════════
    #  DESSIN
    # ══════════════════════════════════════════════════════════════════

    def _redraw(self):
        if self._G is None:
            self._draw_empty();
            return

        self.cv.delete("all")

        # 1. Fond couleur "papier ancien"
        self.cv.config(bg='#fdfcf5')

        # Removed re-building graph during redraw
        self._node_items = {}

        # 2. Arêtes (Tuyaux) — dessinés en premier pour être en dessous
        for u, v, d in self._G.edges(data=True):
            x1, y1 = self._pos_px[u]
            x2, y2 = self._pos_px[v]

            # Si tu as défini des tuyaux secondaires (ex: vers les maisons)
            if d.get("etype") == "secondary":
                self.cv.create_line(x1, y1, x2, y2, fill='#4682B4', width=1.5)
            else:
                self.cv.create_line(x1, y1, x2, y2, fill='#4682B4', width=2.5)

        # 3. Nœuds
        for node in self._G.nodes():
            self._draw_node(node)

    def _draw_node(self, node):
        if node not in self._pos_px: return
        x, y = self._pos_px[node]
        ntype = self._G.nodes[node].get("type", "junction")
        state = self._node_state.get(node, "normal")

        self.cv.delete(f"node_{node}")
        self.cv.delete(f"label_{node}")

        # --- GESTION DES COULEURS ET ÉTATS ---
        if state != "normal":
            # Garde tes couleurs d'erreur si la simulation tourne (à définir dans tes constantes)
            color = {"broken": "red", "surge": "orange", "zero": "black"}.get(state, "red")
        else:
            # Nos couleurs "design" pour le fonctionnement normal
            color = {"chateau": "#0B97F4", "connection": "gray", "house": "#CD5C5C"}.get(ntype, "#11D454")

        # --- DESSIN SELON LE TYPE ---

        if ntype == "chateau":
            # Réservoir : Grand carré bleu foncé
            r = 15
            self.cv.create_rectangle(x - r, y - r, x + r, y + r,
                                     fill=color, outline="#0B97F4", width=2,
                                     tags=(f"node_{node}", "node"))
            self.cv.create_text(x, y, text=node,
                                fill='white', font=("Arial", 10, "bold"),
                                tags=f"label_{node}")

        elif ntype == "connection":
            # Branchements (B1, B2...) : Petit point gris discret, SANS texte
            r = 3
            self.cv.create_oval(x - r, y - r, x + r, y + r,
                                fill=color, outline=color,
                                tags=(f"node_{node}", "node"))

        elif ntype == "house":
            # Maisons (M1, M2...) : Gros rond rouge, texte BLANC au centre
            r = 12
            self.cv.create_oval(x - r, y - r, x + r, y + r,
                                fill=color, outline='black', width=1,
                                tags=(f"node_{node}", "node"))

            # Nom de la maison à l'intérieur du rond (ex: "M1")
            self.cv.create_text(x, y, text=node,
                                fill='white', font=("Arial", 8, "bold"),
                                tags=f"label_{node}")

        else:
            # Carrefours / Junctions (N1, N2...) : AUCUN point dessiné, JUSTE le texte

            r = 5
            self.cv.create_rectangle(x - r, y - r, x + r, y + r,
                                fill=color, outline="#11D454", width=1,
                                tags=(f"node_{node}", "node"))
            self.cv.create_text(x, y, text=node,
                                fill='white', font=("Arial", 4, "bold"),
                                tags=f"label_{node}")

    def _draw_empty(self):
        self.cv.delete("all")
        # On récupère la taille actuelle du canvas
        w = max(self.cv.winfo_width(), 200)
        h = max(self.cv.winfo_height(), 200)

        # On écrit le message au centre
        self.cv.create_text(
            w // 2, h // 2,
            text=" Réseau non généré\n\nConfigurez les paramètres à gauche\npuis cliquez sur 'Générer réseau'",
            fill=TXT_MAIN,
            font=("Arial", 12, "italic"),
            justify="center"
        )

    # ================================================
    #  CLIC → INJECTION DE FAUTE
    # ================================================

    def _on_click(self, event):
        if not self._pos_px: return
        closest, min_dist = None, float("inf")
        for node, (nx_, ny_) in self._pos_px.items():
            d = math.hypot(event.x - nx_, event.y - ny_)
            if d < min_dist:
                min_dist, closest = d, node

        # seuil adapté : maisons plus petites → seuil plus tolérant
        thresh = 20 if self._G.nodes[closest].get("type") == "house" else 28
        if min_dist > thresh: return
        self._show_fault_popup(closest)

    def _show_fault_popup(self, node):
        ntype = self._G.nodes[node].get("type", "junction")
        popup = ctk.CTkToplevel(self)
        popup.title(f"{'Maison' if ntype == 'house' else 'Nœud'}  {node}")
        popup.geometry("290x280")
        popup.resizable(False, False)
        popup.configure(fg_color=BG_CARD)
        popup.grab_set()

        ctk.CTkLabel(popup,
                     text=f"{'🏠 Maison' if ntype == 'house' else '● Jonction'}  {node}",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TXT_MAIN).pack(pady=(18, 4))

        if ntype == "house":
            parent = self._G.nodes[node].get("parent", "?")
            ctk.CTkLabel(popup, text=f"Rattachée à la jonction {parent}",
                         font=ctk.CTkFont(size=10), text_color=TXT_DIM).pack(pady=(0, 4))

        ctk.CTkLabel(popup, text=f"État actuel : {self._node_state.get(node, 'normal')}",
                     font=ctk.CTkFont(size=10), text_color=TXT_SUB).pack(pady=(0, 10))

        def apply(new_state):
            self._node_state[node] = new_state
            self._draw_node(node)
            color = NODE_FAULT if new_state != "normal" else "#3dba6f"
            self._info_label.configure(
                text=f"Faute « {new_state} » → {node}", text_color=color)
            popup.destroy()

        for label, state_key, border in [
            (" Normal", "normal", ACCENT),
            (" Capteur cassé", "broken", NODE_FAULT),
            (" Demande × 5", "surge", NODE_SURGE),
            (" Fuite", "zero", NODE_ZERO),
        ]:
            ctk.CTkButton(popup, text=label, height=36, corner_radius=8,
                          font=ctk.CTkFont(size=12), fg_color=BG_INPUT,
                          hover_color=BORDER, text_color=TXT_MAIN,
                          border_width=1, border_color=border,
                          command=lambda s=state_key: apply(s)).pack(fill="x", padx=20, pady=3)

    # ======================================
    #  CALLBACKS FORMULAIRE
    # ======================================

    def toggle_bruit(self):
        self.entries["Écart-type"].configure(
            state="normal" if self.switches["Bruit"].get() else "disabled")

    def _collect(self):
        return {
            "n_maisons": self.entries["Nombre de maisons"].get(),
            "n_chateaux": self.entries["Nombre de chateaux d'eau"].get(),
            "denivele": self.entries["Dénivelé"].get(),
            "Zone": self.optmenus["Zone"].get(),
            "surface": self.entries["Surface"].get(),
            "formule": self.optmenus["Formule pertes"].get(),
            "rugosite": self.entries["Rugosité"].get(),
            "diam_min": self.entries["Diamètre min"].get(),
            "diam_max": self.entries["Diamètre max"].get(),
            "mode_sim": self.optmenus["Mode simulation"].get(),
            "duree": self.entries["Durée"].get(),
            "bruit": self.switches["Bruit"].get(),
            "ecart_type": self.entries["Écart-type"].get(),
            "pct_casses": self.entries["% cassés"].get(),
            "Hauteur min": self.entries["Hauteur min"].get(),
            "Hauteur max": self.entries["Hauteur max"].get(),

        }

    def on_ok(self):
        params = self._collect()

        # Vérifier nombre de châteaux
        try:
            int(params["n_chateaux"])
        except (ValueError, KeyError):
            self.feedback.configure(text="Nombre de chateaux d'eau invalide", text_color=NODE_FAULT)
            return

        # Vérifier hauteurs
        try:
            h_min_val = params.get("Hauteur min", "").strip()
            h_max_val = params.get("Hauteur max", "").strip()
            hauteur_min = int(h_min_val) if h_min_val else 10
            hauteur_max = int(h_max_val) if h_max_val else 30

            if hauteur_min > hauteur_max:
                raise ValueError("Incohérence")

        except ValueError:
            self.feedback.configure(text="Hauteurs incohérentes", text_color=NODE_FAULT)
            return
        self._params = params
        self._G, self._pos_px = self._build_graph(params)
        self._node_state = {n: "normal" for n in self._G.nodes()}
        self._redraw()

        n_houses = sum(1 for _, d in self._G.nodes(data=True) if d.get("type") == "house")
        self.feedback.configure(
            text=f"✓  {self._G.number_of_nodes()} nœuds "
                 f"({n_houses} maisons · {self._G.number_of_edges()} conduites)",
            text_color="#3dba6f")
        self._info_label.configure(
            text="Cliquez sur une maison ou une jonction pour injecter une faute",
            text_color=TXT_MAIN)

    def on_random(self):
        rng = random.Random()
        rand_params = {
            "Nombre de maisons": str(rng.randint(50, 200)),
            "Nombre de chateaux d'eau": str(rng.randint(1, 5)),
            "Dénivelé": str(rng.randint(10, 50)),
            "Rugosité": str(round(rng.uniform(0.01, 0.05), 3)),
            "Diamètre min": str(rng.choice([50, 80, 100])),
            "Diamètre max": str(rng.choice([200, 250, 300])),
            "Durée": str(rng.choice([0, 6, 12, 24])),
            "% cassés": str(rng.randint(0, 20)),
            "Hauteur min": str(rng.choice([10, 50, 100])),
            "Hauteur max": str(rng.choice([120, 130, 140])),
        }
        for key, val in rand_params.items():
            e = self.entries[key]
            e.configure(state="normal")
            e.delete(0, "end")
            e.insert(0, val)
        self.optmenus["Zone"].set(rng.choice(["Rurale", "Urbaine"]))
        self.optmenus["Formule pertes"].set("Darcy-Weisbach")
        self.optmenus["Mode simulation"].set(rng.choice(["Statique (0h)", "Dynamique (24h)"]))
        self.feedback.configure(text="🎲  Valeurs aléatoires générées", text_color="#3dba6f")
        self.on_ok()

    def reset_faults(self):
        if not self._G: return
        self._node_state = {n: "normal" for n in self._G.nodes()}
        self._redraw()
        self._info_label.configure(text="Fautes réinitialisées", text_color=TXT_DIM)

    # =======================
    #  EXPORT .INP
    # =======================

    def export_inp(self):
        if not self._G:
            self.feedback.configure(text="⚠  Générez d'abord un réseau", text_color=NODE_FAULT)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".inp",
            filetypes=[("EPANET Input File", "*.inp"), ("Tous", "*.*")])
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self._build_inp()))
            
        try:
            import os
            from optimize_network import optimize_network, modify_global_demand, restore_original_demands
            self.feedback.configure(text=f"⚙  Génération des scénarios et Optimisation...", text_color="#f39c12")
            self.update()
            
            base_dir = os.path.dirname(path)
            basename = os.path.splitext(os.path.basename(path))[0]
            high_opt = os.path.join(base_dir, f"High_Demand.inp")
            low_opt = os.path.join(base_dir, f"Low_Demand.inp")
            
            # 1. High Demand
            n_houses = sum(1 for _, d in self._G.nodes(data=True) if d.get("type") == "house")
            peak_demand = max(5.0, n_houses * 0.5)
            modify_global_demand(path, high_opt, demand_change_L_s=peak_demand)
            
            # 2. Optimisation sur High Demand (au moins 2.0 bars)
            optimize_network(high_opt, high_opt, min_pressure_bars=2.0)
            
            # 3. Création de Low Demand (demandes de base avec le réseau optimisé)
            restore_original_demands(high_opt, path, low_opt)
            
            # 4. Remplacer le fichier de base par le réseau optimisé (Nominal)
            restore_original_demands(high_opt, path, path)
            
            self.feedback.configure(text=f"✓  Exporté : {basename} + Low/High Demand", text_color="#3dba6f")
        except Exception as e:
            self.feedback.configure(text=f"⚠  Erreur lors de l'optimisation : {e}", text_color="#e74c3c")
            print(f"Erreur d'optimisation : {e}")

    def export_image(self):
        if not self._G:
            self.feedback.configure(text="⚠  Générez d'abord un réseau", text_color="#e74c3c")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".svg",
            filetypes=[("SVG Vector Image", "*.svg"), ("PNG High Res Image", "*.png"), ("PDF Document", "*.pdf"), ("Tous", "*.*")])
        if not path: return
        
        self.feedback.configure(text="⚙  Génération de l'image haute résolution...", text_color="#f39c12")
        self.update()
        
        try:
            import matplotlib.pyplot as plt
            import networkx as nx
            
            plt.figure(figsize=(30, 30))
            
            colors = []
            sizes = []
            for n in self._G.nodes():
                t = self._G.nodes[n].get("type", "junction")
                if t == "chateau":
                    colors.append("#2980b9")
                    sizes.append(400)
                elif t == "house":
                    colors.append("#e74c3c")
                    sizes.append(60)
                else:
                    colors.append("#95a5a6")
                    sizes.append(20)
            
            pos_plt = {n: (coords[0], -coords[1]) for n, coords in self._pos_px.items()}
                    
            nx.draw(self._G, pos_plt, node_color=colors, node_size=sizes, edge_color="#34495e", width=1.0, with_labels=True, font_size=8, font_color="black")
            
            # Ajouter le nom des tuyaux (arêtes)
            edge_labels = {}
            for k, (u, v, ed) in enumerate(self._G.edges(data=True)):
                edge_labels[(u, v)] = f"P{k + 1}"
            nx.draw_networkx_edge_labels(self._G, pos_plt, edge_labels=edge_labels, font_size=6, font_color="red")
            
            if path.lower().endswith(".png"):
                plt.savefig(path, dpi=400, bbox_inches="tight")
            else:
                plt.savefig(path, bbox_inches="tight")
                
            plt.close()
            
            self.feedback.configure(text=f"✓  Image enregistrée : {path.split('/')[-1]}", text_color="#3dba6f")
        except Exception as e:
            self.feedback.configure(text=f"⚠  Erreur lors de l'export : {e}", text_color="#e74c3c")
            print(f"Erreur export image : {e}")

    def _build_inp(self):
        p = self._params
        lines = []
        w = lines.append

        conso = {"Rurale": 0.2, "Urbaine": 0.2}.get(p.get("zone", "Rurale"), 0.2)
        try:
            denivele = float(p.get("denivele", 0))
        except:
            denivele = 0.0
        try:
            rug = float(p.get("rugosite", 130.0))
        except:
            rug = 130.0
        if rug < 1.0:
            rug = 130.0
        try:
            surface = float(p.get("surface", 2.0))
        except:
            surface = 2.0
        try:
            h_min_val = p.get("Hauteur min", "").strip()
            hauteur_min = float(h_min_val) if h_min_val else 10.0
        except ValueError:
            hauteur_min = 10.0
            
        try:
            h_max_val = p.get("Hauteur max", "").strip()
            hauteur_max = float(h_max_val) if h_max_val else 30.0
        except ValueError:
            hauteur_max = 30.0

        # demande individuelle par maison en L/s (débit instantané pour simulation transitoire)
        demande_maison = 0.007

        fautes = [n for n, s in self._node_state.items() if s != "normal"]

        w("[TITLE]")
        w(f"; Zone={p.get('zone')} | Maisons={p.get('n_maisons')} | Chateaux d'eau={p.get('n_chateaux')}")
        w(f"; Fautes actives : {fautes if fautes else 'aucune'}")
        w("")

        # jonctions + maisons dans [JUNCTIONS]
        w("[JUNCTIONS]")
        w(";ID              \tElev        \tDemand      \tPattern")

        all_juncs = [(n, d) for n, d in self._G.nodes(data=True) if d.get("type") == "junction"]
        all_houses = [(n, d) for n, d in self._G.nodes(data=True) if d.get("type") == "house"]

        for i, (node, _) in enumerate(all_juncs):
            state = self._node_state.get(node, "normal")
            pos_xy = self._pos_px.get(node)
            if pos_xy is not None:
                x, y = pos_xy
                elev = round(get_elevation(x / 800.0, y / 800.0, hauteur_min, hauteur_max), 2)
            else:
                elev = round(i * denivele / 100 * 10, 2)
            demand = 0.0  # jonctions = pas de demande directe, les maisons portent la demande
            w(f" {node:<16}\t{elev:<12}\t{demand:<12}\t                \t;  [{state}]")

        for i, (node, _) in enumerate(all_houses):
            state = self._node_state.get(node, "normal")
            pos_xy = self._pos_px.get(node)
            if pos_xy is not None:
                x, y = pos_xy
                elev = round(get_elevation(x / 800.0, y / 800.0, hauteur_min, hauteur_max), 2)
            else:
                elev = round(i * denivele / 100 * 2, 2)
            demand = (round(demande_maison + 5.0, 5) if state == "surge" else round(demande_maison, 5))
            w(f" {node:<16}\t{elev:<12}\t{demand:<12}\t                \t;  [{state}]")
        w("")

        w("[RESERVOIRS]")
        w(";ID              \tHead        \tPattern")
        chateaux = [(n, d) for n, d in self._G.nodes(data=True) if d.get("type") == "chateau"]
        for node, _ in chateaux:
            pos_xy = self._pos_px.get(node)
            if pos_xy is not None:
                x, y = pos_xy
                hauteur = 20 + round(get_elevation(x / 800.0, y / 800.0, hauteur_min, hauteur_max), 2)
            else:
                hauteur = round((hauteur_min + hauteur_max) / 2, 2)
            w(f" {node:<16}\t{hauteur:<12}\t \t;")
        w("")

        w("[TANKS]");
        w(";ID  \tElev  \tInitLevel  \tMinLevel  \tMaxLevel  \tDiameter  \tMinVol  \tVolCurve");
        w("")

        w("[PIPES]")
        w(";ID              \tNode1           \tNode2           \tLength      \tDiameter    \tRoughness   \tMinorLoss   \tStatus")
        len_main = round(math.sqrt(surface * 1e6) / max(len(all_juncs), 1), 1)
        len_sec = round(len_main * 0.1, 1)

        try:
            diam_min = float(p.get("diam_min", 60))
        except:
            diam_min = 60.0
            
        try:
            diam_max = float(p.get("diam_max", 300))
        except:
            diam_max = 300.0
            
        diam_inter = round((diam_min + diam_max) / 2.0, 1)

        pipes_lines = []
        pumps_lines = []
        valves_lines = []
        
        import random
        for k, (u, v, ed) in enumerate(self._G.edges(data=True)):
            type_u = self._G.nodes[u].get("type")
            type_v = self._G.nodes[v].get("type")
            elev_u = self._G.nodes[u].get("elevation", 0)
            elev_v = self._G.nodes[v].get("elevation", 0)

            # Si chateau d'eau -> diam_max
            if type_u == "chateau" or type_v == "chateau":
                diam = diam_max
                n1, n2 = (u, v) if type_u == "chateau" else (v, u)
                pipes_lines.append(f" P{k + 1:<15}\t{n1:<16}\t{n2:<16}\t{len_main:<12}\t{diam:<12}\t{rug:<12}\t0 \tOpen \t;")
                continue
            
            # Si maison -> diam_min
            elif type_u == "house" or type_v == "house":
                diam = diam_min
                length = len_sec
                pipes_lines.append(f" P{k + 1:<15}\t{u:<16}\t{v:<16}\t{length:<12}\t{diam:<12}\t{rug:<12}\t0 \tOpen \t;")
                continue
            
            # Si autres jonctions -> diam_intermédiaire
            else:
                diam = diam_inter
                length = len_main
                # Si fort dénivelé (PRV)
                if abs(elev_u - elev_v) > 15.0 and random.random() < 0.15:
                    n1, n2 = (u, v) if elev_u > elev_v else (v, u)
                    valves_lines.append(f" V{k + 1:<15}\t{n1:<16}\t{n2:<16}\t{diam:<10}\tPRV \t30 \t0")
                else:
                    pipes_lines.append(f" P{k + 1:<15}\t{u:<16}\t{v:<16}\t{length:<12}\t{diam:<12}\t{rug:<12}\t0 \tOpen \t;")

        for pline in pipes_lines: w(pline)
        w("")

        w("[PUMPS]")
        w(";ID  \tNode1  \tNode2  \tParameters")
        for pline in pumps_lines: w(pline)
        w("")
        w("[VALVES]")
        w(";ID  \tNode1  \tNode2  \tDiameter  \tType  \tSetting  \tMinorLoss")
        for v_line in valves_lines: w(v_line)

        w("[TAGS]");
        w("[DEMANDS]");
        w("[STATUS]")

        w("[EMITTERS]")
        w(";Node           \tCoefficient")
        for i, (node, _) in enumerate(all_houses):
            if self._node_state.get(node) == "zero":
                w(f" {node:<16}\t0.75")
        for i, (node, _) in enumerate(all_juncs):
            if self._node_state.get(node) == "zero":
                w(f" {node:<16}\t0.75")
        w("")
        w("[QUALITY]")
        w(";Node            \tInitQual")
        for node, state in self._node_state.items():
            if state == "broken":
                ntype = self._G.nodes[node].get("type", "?")
                w(f"; [CAPTEUR CASSÉ] {node}  (type: {ntype})")
        w("")

        dur_map = {"Statique (0h)": "0:00", "Dynamique (24h)": "24:00"}
        duree = dur_map.get(p.get("mode_sim"), f"{p.get('duree', '0')}:00")
        hl = "H-W"

        w("[PATTERNS]");
        w("[CURVES]");
        w("[CONTROLS]");
        w("[RULES]")
        w("[ENERGY]");
        w(" Global Efficiency  \t75");
        w(" Global Price  \t0");
        w(" Demand Charge  \t0")
        w("[EMITTERS]");
        w("[SOURCES]")
        w("[REACTIONS]");
        w(" Order Bulk \t1");
        w(" Order Tank \t1");
        w(" Order Wall \t1")
        w(" Global Bulk \t0");
        w(" Global Wall \t0")
        w(" Limiting Potential \t0");
        w(" Roughness Correlation \t0")
        w("[MIXING]")
        w("[TIMES]")
        w(f" Duration           \t{duree} ")
        w(" Hydraulic Timestep \t1:00 ");
        w(" Quality Timestep   \t0:05 ")
        w(" Pattern Timestep   \t1:00 ");
        w(" Report Timestep    \t1:00 ")
        w(" Start ClockTime    \t12 am");
        w(" Statistic          \tNONE")
        w("[REPORT]");
        w(" Status \tNo");
        w(" Summary \tNo");
        w(" Page \t0")
        w("[OPTIONS]")
        w(" Units              \tLPS");
        w(f" Headloss           \t{hl}")
        w(" Specific Gravity   \t1");
        w(" Viscosity          \t1")
        w(" Trials             \t40");
        w(" Accuracy           \t0.001")
        w(" Unbalanced         \tContinue 10");
        w(" Demand Multiplier  \t1.0")
        w(" Quality            \tNone mg/L");
        w(" Tolerance          \t0.01")

        w("[COORDINATES]");
        w(";Node  \tX-Coord  \tY-Coord")
        cw = max(self.cv.winfo_width(), 200)
        ch = max(self.cv.winfo_height(), 200)
        for node, (px, py) in self._pos_px.items():
            w(f" {node:<16}\t{px / cw * 10000:<16.2f}\t{(ch - py) / ch * 10000:<16.2f}")

        w("[VERTICES]");
        w("[LABELS]")
        w("[CURVES]")
        w(";ID              	X-Value     	Y-Value")
        w(" CurvePump       	0           	10")
        w(" CurvePump       	2500        	8")
        w(" CurvePump       	5000        	0")
        w("")
        w("[BACKDROP]")
        w(" DIMENSIONS \t0.00 \t0.00 \t10000.00 \t10000.00")
        w(" UNITS \tNone");
        w(" FILE \t");
        w(" OFFSET \t0.00 \t0.00")
        w("[END]")
        return lines


if __name__ == '__main__':
    app = App()
    app.mainloop()
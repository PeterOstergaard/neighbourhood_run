# neighbourhood_run/check_islands_v2.py
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point
from rich.console import Console
from src.neighbourhood_run.config import CONFIG

console = Console()

network = gpd.read_file(str(CONFIG.paths.processed_network))
network = network.to_crs(CONFIG.project_crs)

# Build graph using a spatial tolerance for node matching
# Two endpoints within 0.5m of each other are the same node
SNAP_TOLERANCE = 0.5

# Collect all endpoints
node_map = {}  # maps (x,y) -> node_id
node_id_counter = 0

def get_or_create_node(x, y):
    global node_id_counter
    # Check if there's an existing node within tolerance
    for (nx_, ny_), nid in node_map.items():
        if ((nx_ - x)**2 + (ny_ - y)**2)**0.5 < SNAP_TOLERANCE:
            return nid
    # Create new node
    node_map[(x, y)] = node_id_counter
    node_id_counter += 1
    return node_id_counter - 1

G = nx.Graph()
node_coords = {}  # node_id -> (x, y)

for _, row in network.iterrows():
    coords = list(row.geometry.coords)
    start = coords[0]
    end = coords[-1]

    start_node = get_or_create_node(start[0], start[1])
    end_node = get_or_create_node(end[0], end[1])

    node_coords[start_node] = start
    node_coords[end_node] = end

    G.add_edge(start_node, end_node, edge_id=row["edge_id"], length=row["length_m"])

# Find connected components
components = list(nx.connected_components(G))
components.sort(key=len, reverse=True)

print(f"Total nodes: {G.number_of_nodes()}")
print(f"Total edges: {G.number_of_edges()}")
print(f"Connected components: {len(components)}")
print()

# Find home
home_gdf = gpd.read_file(str(CONFIG.paths.processed_home)).to_crs(CONFIG.project_crs)
home_point = home_gdf.geometry.iloc[0]

# Find nearest node to home
min_dist = float('inf')
home_node = None
for nid, (nx_, ny_) in node_coords.items():
    dist = ((nx_ - home_point.x)**2 + (ny_ - home_point.y)**2)**0.5
    if dist < min_dist:
        min_dist = dist
        home_node = nid

print(f"Nearest node to home: {home_node} (distance: {min_dist:.1f}m)")

# Find which component contains home
home_component = None
for i, comp in enumerate(components):
    if home_node in comp:
        home_component = i
        break

print(f"Home is in component {home_component}")
print()

# Summarize components
for i, comp in enumerate(components[:15]):
    comp_edges = [
        d for u, v, d in G.edges(data=True)
        if u in comp and v in comp
    ]
    total_km = sum(d["length"] for d in comp_edges) / 1000

    if i == home_component:
        label = " ← HOME"
    else:
        label = " ← ISLAND"

    print(f"  Component {i}: {len(comp):5} nodes, {len(comp_edges):5} edges, {total_km:6.1f} km{label}")

if len(components) > 15:
    print(f"  ... and {len(components) - 15} more tiny components")

# Count island stats
main_comp = components[home_component]
main_edges = [d for u, v, d in G.edges(data=True) if u in main_comp and v in main_comp]
main_km = sum(d["length"] for d in main_edges) / 1000

total_km = network["length_m"].sum() / 1000
island_km = total_km - main_km

print(f"\nSummary:")
print(f"  Main network (home): {len(main_comp)} nodes, {main_km:.1f} km")
print(f"  Islands: {len(components) - 1} components, {island_km:.1f} km")
print(f"  Total: {total_km:.1f} km")
print(f"  Reachable from home: {main_km/total_km*100:.1f}%")
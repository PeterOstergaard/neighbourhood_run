# neighbourhood_run/check_islands.py
import geopandas as gpd
import networkx as nx
from shapely.ops import nearest_points
from rich.console import Console
from src.neighbourhood_run.config import CONFIG

console = Console()

network = gpd.read_file(str(CONFIG.paths.processed_network))
network = network.to_crs(CONFIG.project_crs)

# Build a graph from the network edges
G = nx.Graph()
for _, row in network.iterrows():
    coords = list(row.geometry.coords)
    start = coords[0]
    end = coords[-1]
    # Round coordinates to handle floating point near-matches
    start_node = (round(start[0], 1), round(start[1], 1))
    end_node = (round(end[0], 1), round(end[1], 1))
    G.add_edge(start_node, end_node, edge_id=row["edge_id"], length=row["length_m"])

# Find connected components
components = list(nx.connected_components(G))
components.sort(key=len, reverse=True)

print(f"Total nodes: {G.number_of_nodes()}")
print(f"Total edges: {G.number_of_edges()}")
print(f"Connected components: {len(components)}")
print()

# Load home location
home_gdf = gpd.read_file(str(CONFIG.paths.processed_home)).to_crs(CONFIG.project_crs)
home_point = home_gdf.geometry.iloc[0]
home_coord = (round(home_point.x, 1), round(home_point.y, 1))

# Find which component contains home
home_component = None
for i, comp in enumerate(components):
    if home_coord in comp:
        home_component = i
        break

# If home isn't exactly on a node, find the nearest component
if home_component is None:
    min_dist = float('inf')
    for i, comp in enumerate(components):
        for node in comp:
            dist = ((node[0] - home_point.x)**2 + (node[1] - home_point.y)**2)**0.5
            if dist < min_dist:
                min_dist = dist
                home_component = i

print(f"Home is in component {home_component} (largest = 0)")
print()

# Summarize components
main_component = components[home_component] if home_component is not None else components[0]

# Count edges per component
for i, comp in enumerate(components[:20]):
    comp_edges = [
        (u, v, d) for u, v, d in G.edges(data=True)
        if u in comp or v in comp
    ]
    total_km = sum(d["length"] for _, _, d in comp_edges) / 1000

    if i == home_component:
        label = " ← HOME"
    else:
        label = " ← ISLAND"

    print(f"  Component {i}: {len(comp):5} nodes, {len(comp_edges):5} edges, {total_km:6.1f} km{label}")

if len(components) > 20:
    remaining = len(components) - 20
    print(f"  ... and {remaining} more tiny components")

# Summary
island_components = [c for i, c in enumerate(components) if i != home_component]
island_edges = sum(
    len([e for e in G.edges(data=True) if e[0] in c or e[1] in c])
    for c in island_components
)
island_km = sum(
    sum(d["length"] for _, _, d in G.edges(data=True) if u in c or v in c)
    for c in island_components
) / 1000

print(f"\nSummary:")
print(f"  Main network (reachable from home): {len(main_component)} nodes")
print(f"  Island components: {len(island_components)}")
print(f"  Island edges: {island_edges}")
print(f"  Island distance: {island_km:.1f} km")
print(f"\nThese islands will be reachable via connector roads in Step 4.")
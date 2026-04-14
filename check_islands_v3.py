# neighbourhood_run/check_islands_v3.py
import geopandas as gpd
import networkx as nx
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))
network = network.to_crs(CONFIG.project_crs)

SNAP_TOLERANCE = 0.5
node_map = {}
node_id_counter = 0

def get_or_create_node(x, y):
    global node_id_counter
    for (nx_, ny_), nid in node_map.items():
        if ((nx_ - x)**2 + (ny_ - y)**2)**0.5 < SNAP_TOLERANCE:
            return nid
    node_map[(x, y)] = node_id_counter
    node_id_counter += 1
    return node_id_counter - 1

G = nx.Graph()
node_coords = {}
edge_to_nodes = {}  # edge_id -> (start_node, end_node)

for _, row in network.iterrows():
    coords = list(row.geometry.coords)
    start_node = get_or_create_node(coords[0][0], coords[0][1])
    end_node = get_or_create_node(coords[-1][0], coords[-1][1])
    node_coords[start_node] = coords[0]
    node_coords[end_node] = coords[-1]
    G.add_edge(start_node, end_node, edge_id=row["edge_id"])
    edge_to_nodes[row["edge_id"]] = (start_node, end_node)

# Find home
home_gdf = gpd.read_file(str(CONFIG.paths.processed_home)).to_crs(CONFIG.project_crs)
home_point = home_gdf.geometry.iloc[0]

min_dist = float('inf')
home_node = None
for nid, (nx_, ny_) in node_coords.items():
    dist = ((nx_ - home_point.x)**2 + (ny_ - home_point.y)**2)**0.5
    if dist < min_dist:
        min_dist = dist
        home_node = nid

components = list(nx.connected_components(G))
components.sort(key=len, reverse=True)

home_component = None
for i, comp in enumerate(components):
    if home_node in comp:
        home_component = i
        break

# Map each edge to its component
edge_component = {}
for i, comp in enumerate(components):
    for _, row in network.iterrows():
        eid = row["edge_id"]
        if eid in edge_to_nodes:
            s, e = edge_to_nodes[eid]
            if s in comp or e in comp:
                edge_component[eid] = i

network["_component"] = network["edge_id"].map(edge_component)

print(f"Total nodes: {G.number_of_nodes()}")
print(f"Total edges in graph: {G.number_of_edges()}")
print(f"Total edges in network: {len(network)}")
print(f"Connected components: {len(components)}")
print(f"Home component: {home_component}")
print()

# Summarize by component using the network dataframe
for i in range(min(15, len(components))):
    comp_edges = network[network["_component"] == i]
    n_nodes = len(components[i])
    n_edges = len(comp_edges)
    total_km = comp_edges["length_m"].sum() / 1000
    req_km = comp_edges.loc[comp_edges.get("required", True) == True, "length_m"].sum() / 1000 if "required" in comp_edges.columns else total_km

    label = " ← HOME" if i == home_component else " ← ISLAND"
    print(f"  Component {i}: {n_nodes:5} nodes, {n_edges:5} edges, "
          f"{total_km:6.1f} km total, {req_km:6.1f} km required{label}")

if len(components) > 15:
    print(f"  ... and {len(components) - 15} more tiny components")

# Proper summary
home_edges = network[network["_component"] == home_component]
island_edges = network[network["_component"] != home_component]

home_km = home_edges["length_m"].sum() / 1000
island_km = island_edges["length_m"].sum() / 1000
total_km = network["length_m"].sum() / 1000

print(f"\nSummary:")
print(f"  Total network: {len(network)} edges, {total_km:.1f} km")
print(f"  Home component: {len(home_edges)} edges, {home_km:.1f} km ({home_km/total_km*100:.1f}%)")
print(f"  Islands: {len(island_edges)} edges, {island_km:.1f} km ({island_km/total_km*100:.1f}%)")

if "required" in network.columns:
    home_req = home_edges.loc[home_edges["required"] == True, "length_m"].sum() / 1000
    island_req = island_edges.loc[island_edges["required"] == True, "length_m"].sum() / 1000
    total_req = network.loc[network["required"] == True, "length_m"].sum() / 1000
    print(f"\n  Required only:")
    print(f"    Home component: {home_req:.1f} km ({home_req/total_req*100:.1f}%)")
    print(f"    Islands: {island_req:.1f} km ({island_req/total_req*100:.1f}%)")

network.drop(columns=["_component"], inplace=True)
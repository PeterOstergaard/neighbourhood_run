# neighbourhood_run/find_gap.py
"""
Finds what's disconnecting the two largest network components.
"""
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points
from rich.console import Console
from src.neighbourhood_run.config import CONFIG

console = Console()

SNAP_TOLERANCE = 0.5

network = gpd.read_file(str(CONFIG.paths.processed_network))
network = network.to_crs(CONFIG.project_crs)

# Build graph
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

for _, row in network.iterrows():
    coords = list(row.geometry.coords)
    start = coords[0]
    end = coords[-1]
    start_node = get_or_create_node(start[0], start[1])
    end_node = get_or_create_node(end[0], end[1])
    node_coords[start_node] = start
    node_coords[end_node] = end
    G.add_edge(start_node, end_node, edge_id=row["edge_id"])

components = list(nx.connected_components(G))
components.sort(key=len, reverse=True)

comp0 = components[0]
comp1 = components[1]

print(f"Component 0: {len(comp0)} nodes")
print(f"Component 1: {len(comp1)} nodes")

# Find the closest pair of nodes between the two components
min_dist = float('inf')
closest_pair = None

for n0 in comp0:
    c0 = node_coords[n0]
    for n1 in comp1:
        c1 = node_coords[n1]
        dist = ((c0[0] - c1[0])**2 + (c0[1] - c1[1])**2)**0.5
        if dist < min_dist:
            min_dist = dist
            closest_pair = (n0, n1, c0, c1)

n0, n1, c0, c1 = closest_pair
print(f"\nClosest gap between components:")
print(f"  Distance: {min_dist:.1f} meters")
print(f"  Component 0 node at: ({c0[0]:.1f}, {c0[1]:.1f})")
print(f"  Component 1 node at: ({c1[0]:.1f}, {c1[1]:.1f})")

# Find what edges connect to these nodes
print(f"\nEdges at component 0 side of gap:")
for _, row in network.iterrows():
    coords = list(row.geometry.coords)
    start = coords[0]
    end = coords[-1]
    s_node = get_or_create_node(start[0], start[1])
    e_node = get_or_create_node(end[0], end[1])
    if s_node == n0 or e_node == n0:
        print(f"  edge_id={row['edge_id']}  {row.get('name', 'unnamed')}  "
              f"highway={row['highway']}  length={row['length_m']:.1f}m  "
              f"required={row.get('required', 'N/A')}")

print(f"\nEdges at component 1 side of gap:")
for _, row in network.iterrows():
    coords = list(row.geometry.coords)
    start = coords[0]
    end = coords[-1]
    s_node = get_or_create_node(start[0], start[1])
    e_node = get_or_create_node(end[0], end[1])
    if s_node == n1 or e_node == n1:
        print(f"  edge_id={row['edge_id']}  {row.get('name', 'unnamed')}  "
              f"highway={row['highway']}  length={row['length_m']:.1f}m  "
              f"required={row.get('required', 'N/A')}")

# Convert gap coordinates to lat/lon for viewing on map
from pyproj import Transformer
transformer = Transformer.from_crs(CONFIG.project_crs, "EPSG:4326", always_xy=True)
lon0, lat0 = transformer.transform(c0[0], c0[1])
lon1, lat1 = transformer.transform(c1[0], c1[1])

print(f"\nView the gap on the map:")
print(f"  Component 0 side: https://www.openstreetmap.org/?mlat={lat0}&mlon={lon0}#map=19/{lat0}/{lon0}")
print(f"  Component 1 side: https://www.openstreetmap.org/?mlat={lat1}&mlon={lon1}#map=19/{lat1}/{lon1}")
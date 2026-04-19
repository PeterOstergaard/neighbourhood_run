# neighbourhood_run/debug_route6_edges.py
import geopandas as gpd
from shapely.geometry import LineString
from src.neighbourhood_run.config import CONFIG

routes = gpd.read_file(str(CONFIG.paths.planned_routes))
network = gpd.read_file(str(CONFIG.paths.processed_network))

last_route = routes.iloc[-1]
geom = last_route.geometry
coords = list(geom.coords)

# Find suspiciously long straight segments in the route
print("Looking for straight-line segments (possible geometry lookup failures)...")
print()

long_segments = []
for i in range(len(coords) - 1):
    p1 = coords[i]
    p2 = coords[i + 1]
    dist = ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5
    if dist > 200:  # Flag segments longer than 200m
        long_segments.append({
            "index": i,
            "from": p1,
            "to": p2,
            "distance": dist
        })

print(f"Segments longer than 200m: {len(long_segments)}")
for seg in long_segments:
    print(f"  Point {seg['index']} -> {seg['index']+1}: {seg['distance']:.0f}m")
    print(f"    From: ({seg['from'][0]:.1f}, {seg['from'][1]:.1f})")
    print(f"    To:   ({seg['to'][0]:.1f}, {seg['to'][1]:.1f})")

    # Check if any network edge connects these approximate locations
    found = False
    for _, row in network.iterrows():
        edge_coords = list(row.geometry.coords)
        start = edge_coords[0]
        end = edge_coords[-1]

        d_start_from = ((start[0]-seg['from'][0])**2 + (start[1]-seg['from'][1])**2)**0.5
        d_end_to = ((end[0]-seg['to'][0])**2 + (end[1]-seg['to'][1])**2)**0.5
        d_start_to = ((start[0]-seg['to'][0])**2 + (start[1]-seg['to'][1])**2)**0.5
        d_end_from = ((end[0]-seg['from'][0])**2 + (end[1]-seg['from'][1])**2)**0.5

        if (d_start_from < 5 and d_end_to < 5) or (d_start_to < 5 and d_end_from < 5):
            print(f"    Matching edge found: edge_id={row['edge_id']} "
                  f"name={row.get('name','unnamed')} highway={row['highway']} "
                  f"length={row['length_m']:.1f}m "
                  f"required={row.get('required','N/A')} "
                  f"geom_points={len(edge_coords)}")
            found = True

    if not found:
        print(f"    NO MATCHING EDGE FOUND - this is a straight-line fallback!")
# neighbourhood_run/debug_route6.py
import geopandas as gpd
import json
from src.neighbourhood_run.config import CONFIG

routes = gpd.read_file(str(CONFIG.paths.planned_routes))

# Find the last route
last_route = routes.iloc[-1]
print(f"Route: {last_route['route_name']}")
print(f"Distance: {last_route['distance_km']} km")
print(f"New coverage: {last_route['new_coverage_km']} km")
print(f"Segments covered: {last_route['segments_covered']}")

# Check the geometry
geom = last_route.geometry
coords = list(geom.coords)
print(f"\nGeometry points: {len(coords)}")
print(f"Start point: ({coords[0][0]:.1f}, {coords[0][1]:.1f})")
print(f"End point:   ({coords[-1][0]:.1f}, {coords[-1][1]:.1f})")

# Are start and end the same?
start = coords[0]
end = coords[-1]
dist = ((start[0]-end[0])**2 + (start[1]-end[1])**2)**0.5
print(f"Distance between start and end: {dist:.1f} meters")

# Load home
home = gpd.read_file(str(CONFIG.paths.processed_home)).to_crs(CONFIG.project_crs)
home_point = home.geometry.iloc[0]
print(f"\nHome point: ({home_point.x:.1f}, {home_point.y:.1f})")

dist_to_home_start = ((coords[0][0]-home_point.x)**2 + (coords[0][1]-home_point.y)**2)**0.5
dist_to_home_end = ((coords[-1][0]-home_point.x)**2 + (coords[-1][1]-home_point.y)**2)**0.5
print(f"Start distance from home: {dist_to_home_start:.1f} meters")
print(f"End distance from home: {dist_to_home_end:.1f} meters")

# Check which edges this route covers
covered_ids = last_route.get("covered_edge_ids", "")
if covered_ids:
    edge_ids = [int(x) for x in str(covered_ids).split(",")]
    network = gpd.read_file(str(CONFIG.paths.processed_network)).to_crs(CONFIG.project_crs)
    
    covered_edges = network[network["edge_id"].isin(edge_ids)]
    print(f"\nCovered edges in this route: {len(covered_edges)}")
    
    # Check reachability
    if "reachable" in covered_edges.columns:
        unreachable = covered_edges[covered_edges["reachable"] == False]
        print(f"Unreachable edges in route: {len(unreachable)}")
        if not unreachable.empty:
            for _, row in unreachable.iterrows():
                print(f"  edge_id={row['edge_id']}  {row.get('name', 'unnamed')}  {row['highway']}  {row['length_m']:.1f}m")
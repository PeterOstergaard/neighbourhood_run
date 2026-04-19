# neighbourhood_run/check_boundary_islands.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))

if "reachable" not in network.columns:
    print("No reachability data. Run rebuild_all.py first.")
    exit()

unreachable = network[network["reachable"] == False]
required_unreachable = unreachable[unreachable.get("required", True) == True]

print(f"Total unreachable segments: {len(unreachable)}")
print(f"Required unreachable segments: {len(required_unreachable)}")
print(f"Required unreachable distance: {required_unreachable['length_m'].sum() / 1000:.1f} km")

if not required_unreachable.empty:
    # Load boundary to check which are near the edge
    boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
    boundary_line = boundary.geometry.iloc[0].boundary

    unreachable_proj = required_unreachable.to_crs(CONFIG.project_crs)

    near_boundary = []
    for _, row in unreachable_proj.iterrows():
        midpoint = row.geometry.interpolate(0.5, normalized=True)
        dist_to_boundary = boundary_line.distance(midpoint)
        near_boundary.append({
            "edge_id": row["edge_id"],
            "name": row.get("name", "unnamed"),
            "highway": row.get("highway", "unknown"),
            "length_m": row["length_m"],
            "dist_to_boundary_m": round(dist_to_boundary, 1)
        })

    near_boundary.sort(key=lambda x: x["dist_to_boundary_m"])

    print(f"\nUnreachable required segments (sorted by distance to boundary):")
    for seg in near_boundary[:20]:
        print(f"  edge_id={seg['edge_id']:5}  {seg['dist_to_boundary_m']:6.1f}m from boundary  "
              f"{seg['length_m']:6.1f}m  {seg['name']}  ({seg['highway']})")
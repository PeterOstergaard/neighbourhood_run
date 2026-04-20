# neighbourhood_run/debug_unreachable.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))

# Find the specific streets
target_names = ['Sylbækvej', 'Vesterløkken', 'Elkjærvej']

for name in target_names:
    matches = network[network['name'].fillna('').str.contains(name, case=False, na=False)]
    if matches.empty:
        print(f"\n{name}: NOT FOUND in network")
    else:
        print(f"\n{name}: {len(matches)} segments")
        for _, row in matches.iterrows():
            print(f"  edge_id={row['edge_id']:5}  "
                  f"length={row['length_m']:.1f}m  "
                  f"highway={row['highway']}  "
                  f"required={row.get('required', 'N/A')}  "
                  f"reachable={row.get('reachable', 'N/A')}  "
                  f"covered={row.get('covered', 'N/A')}")

# Check if any exclusion zones overlap this area
print("\n\nChecking exclusion zones in the area...")
try:
    # Load boundary and check for exclusion zones
    import osmnx as ox
    boundary = gpd.read_file(str(CONFIG.paths.raw_boundary))
    polygon = boundary.geometry.iloc[0]
    
    for tag_key, tag_values in [("landuse", ["military", "allotments"]), ("amenity", ["school"])]:
        for tag_value in tag_values:
            try:
                zones = ox.features_from_polygon(polygon, tags={tag_key: tag_value})
                zones = zones[zones.geom_type.isin(["Polygon", "MultiPolygon"])]
                if not zones.empty:
                    zones_proj = zones.to_crs(CONFIG.project_crs)
                    for _, zone in zones_proj.iterrows():
                        zone_name = zone.get("name", "unnamed")
                        zone_area = zone.geometry.area
                        print(f"  {tag_key}={tag_value}: {zone_name} ({zone_area:.0f} m²)")
                        
                        # Check if any of our target streets intersect this zone
                        network_proj = network.to_crs(CONFIG.project_crs)
                        for target in target_names:
                            matches = network_proj[network_proj['name'].fillna('').str.contains(target, case=False)]
                            for _, edge in matches.iterrows():
                                midpoint = edge.geometry.interpolate(0.5, normalized=True)
                                if midpoint.within(zone.geometry):
                                    print(f"    ⚠ {target} edge_id={edge['edge_id']} is INSIDE this zone!")
            except Exception as e:
                print(f"  {tag_key}={tag_value}: error - {e}")
except Exception as e:
    print(f"Error: {e}")
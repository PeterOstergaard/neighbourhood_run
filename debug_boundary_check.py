# neighbourhood_run/debug_boundary_check.py
"""
Checks if the boundary geometry itself is the problem.
"""
import geopandas as gpd
from shapely.geometry import Point
from src.neighbourhood_run.config import CONFIG

# Load boundary
boundary = gpd.read_file(str(CONFIG.paths.raw_boundary))
print(f"Boundary CRS: {boundary.crs}")
print(f"Boundary geometry type: {boundary.geom_type.iloc[0]}")
print(f"Boundary bounds (WGS84): {boundary.total_bounds}")

boundary_proj = boundary.to_crs(CONFIG.project_crs)
print(f"Boundary CRS after projection: {boundary_proj.crs}")
print(f"Boundary bounds (projected): {boundary_proj.total_bounds}")
print(f"Boundary area: {boundary_proj.geometry.iloc[0].area / 1e6:.2f} km²")

# Load network
network = gpd.read_file(str(CONFIG.paths.processed_network))
print(f"\nNetwork CRS: {network.crs}")

# Check a known road that should be inside
network_proj = network.to_crs(CONFIG.project_crs)
boundary_geom = boundary_proj.geometry.iloc[0]

# Test specific roads
test_roads = ['Sylbækvej', 'Elkjærvej', 'Vesterløkken', 'Carit Etlars','Egsagervej', 'Klamsagervej', 'Ved Lunden', 'Lærkevej'
              ]

for road in test_roads:
    matches = network_proj[network_proj['name'].fillna('').str.contains(road, case=False)]
    if matches.empty:
        print(f"\n{road}: NOT FOUND")
        continue
    
    print(f"\n{road}: {len(matches)} segments")
    optional = matches[matches['required'] == False]
    if optional.empty:
        print(f"  All required ✅")
        continue
    
    for _, row in optional.head(3).iterrows():
        midpoint = row.geometry.interpolate(0.5, normalized=True)
        
        # Test with projected boundary
        inside_proj = midpoint.within(boundary_geom)
        
        # Test with WGS84 boundary (convert midpoint back)
        from pyproj import Transformer
        transformer = Transformer.from_crs(CONFIG.project_crs, "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(midpoint.x, midpoint.y)
        midpoint_wgs84 = Point(lon, lat)
        inside_wgs84 = midpoint_wgs84.within(boundary.geometry.iloc[0])
        
        print(f"  edge_id={row['edge_id']}  required={row['required']}")
        print(f"    midpoint projected: ({midpoint.x:.1f}, {midpoint.y:.1f})")
        print(f"    midpoint WGS84:     ({lat:.6f}, {lon:.6f})")
        print(f"    inside (projected): {inside_proj}")
        print(f"    inside (WGS84):     {inside_wgs84}")
        print(f"    OSM link: https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=19/{lat}/{lon}")
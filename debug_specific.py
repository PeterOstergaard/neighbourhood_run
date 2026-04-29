# neighbourhood_run/debug_specific.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))
network_proj = network.to_crs(CONFIG.project_crs)

boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
boundary_geom = boundary.geometry.iloc[0]

# Check the specific problem edge IDs
for eid in [1739, 2735, 1113, 1117, 1119]:
    matches = network_proj[network_proj['edge_id'] == eid]
    if matches.empty:
        print(f"Edge {eid}: NOT FOUND")
        continue
    
    row = matches.iloc[0]
    midpoint = row.geometry.interpolate(0.5, normalized=True)
    inside = midpoint.within(boundary_geom)
    
    # Also check with buffer
    inside_25m = midpoint.within(boundary_geom.buffer(25))
    
    # Check distance to boundary
    dist_to_boundary = boundary_geom.boundary.distance(midpoint)
    
    print(f"Edge {eid}:")
    print(f"  name:          {row['name']}")
    print(f"  highway:       {row['highway']}")
    print(f"  length:        {row['length_m']:.1f}m")
    print(f"  required:      {row['required']}")
    print(f"  inside:        {inside}")
    print(f"  inside+25m:    {inside_25m}")
    print(f"  dist_to_bound: {dist_to_boundary:.1f}m")
    print(f"  midpoint:      ({midpoint.x:.1f}, {midpoint.y:.1f})")
    print()

# Also find ALL optional named segments and their distances
print("=" * 70)
print("ALL optional named segments with distance to boundary:")
print("=" * 70)

optional_named = network_proj[
    (network_proj['required'] == False) &
    network_proj['name'].notna() &
    (network_proj['name'] != '') &
    (network_proj['name'].astype(str) != 'nan')
]

for _, row in optional_named.iterrows():
    hw = row['highway']
    if isinstance(hw, list):
        hw = hw[0]
    
    # Skip secondary roads (correctly optional)
    if hw in ('primary', 'primary_link', 'secondary', 'secondary_link'):
        continue
    
    midpoint = row.geometry.interpolate(0.5, normalized=True)
    dist = boundary_geom.boundary.distance(midpoint)
    inside = midpoint.within(boundary_geom)
    inside_25 = midpoint.within(boundary_geom.buffer(25))
    
    print(f"  edge_id={row['edge_id']:5}  {row['name']:<25}  hw={hw:<15}  "
          f"len={row['length_m']:6.1f}m  dist={dist:6.1f}m  "
          f"inside={inside}  inside25={inside_25}")
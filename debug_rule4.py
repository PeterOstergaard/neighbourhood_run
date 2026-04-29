# neighbourhood_run/debug_rule4.py
import geopandas as gpd
import pandas as pd
from src.neighbourhood_run.config import CONFIG

# Simulate what Rule 4 does
network = gpd.read_file(str(CONFIG.paths.processed_network))
network_proj = network.to_crs(CONFIG.project_crs)

boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
boundary_geom = boundary.geometry.iloc[0]

# Check the two problem segments
for eid in [1658, 1666]:
    row = network_proj[network_proj['edge_id'] == eid].iloc[0]
    
    midpoint = row.geometry.interpolate(0.5, normalized=True)
    inside = midpoint.within(boundary_geom)
    
    name = row.get('name', '')
    is_named = (
        name is not None and 
        str(name).strip() != '' and 
        str(name) != 'nan'
    )
    
    hw = row['highway']
    if isinstance(hw, list):
        hw = hw[0]
    
    promotable_types = {
        "residential", "living_street", "tertiary", "tertiary_link",
        "unclassified", "pedestrian", "footway", "path", "cycleway",
        "track", "bridleway", "steps"
    }
    is_promotable = str(hw) in promotable_types
    
    print(f"Edge {eid}:")
    print(f"  name='{name}' is_named={is_named}")
    print(f"  highway='{hw}' is_promotable={is_promotable}")
    print(f"  inside_boundary={inside}")
    print(f"  required={row['required']}")
    print(f"  SHOULD be promoted: {is_named and is_promotable and inside and not row['required']}")
    
    # Check the actual name value type
    print(f"  name type: {type(name)}")
    print(f"  name repr: {repr(name)}")
    print()
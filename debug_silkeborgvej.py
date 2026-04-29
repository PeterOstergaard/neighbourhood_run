# neighbourhood_run/debug_silkeborgvej.py
import geopandas as gpd
from shapely.geometry import LineString
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))
network_proj = network.to_crs(CONFIG.project_crs)

# Load boundary
boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
boundary_geom = boundary.geometry.iloc[0]

silkeborg = network_proj[network_proj['name'].fillna('').str.contains('Silkeborgvej', case=False)]

print(f"Silkeborgvej segments: {len(silkeborg)}")
print()

for _, row in silkeborg.head(10).iterrows():
    midpoint = row.geometry.interpolate(0.5, normalized=True)
    inside = midpoint.within(boundary_geom)
    
    # Check all the rules
    hw = row['highway']
    if isinstance(hw, list):
        hw = hw[0]
    
    name = row.get('name', '')
    is_named = name is not None and str(name).strip() != '' and str(name) != 'nan'
    
    length = row['length_m']
    is_service = str(hw) == 'service'
    is_short = length <= 75
    is_very_short = length < 10
    
    print(f"  edge_id={row['edge_id']}")
    print(f"    highway:       {hw}")
    print(f"    name:          {name}")
    print(f"    is_named:      {is_named}")
    print(f"    length:        {length:.1f}m")
    print(f"    inside_boundary: {inside}")
    print(f"    required:      {row.get('required', 'N/A')}")
    print(f"    is_service:    {is_service}")
    print(f"    is_short_svc:  {is_service and is_short}")
    print(f"    is_very_short: {is_very_short}")
    
    # Check sidewalk filter
    sidewalk = row.get('sidewalk', None)
    from src.neighbourhood_run.network import SIDEWALK_REQUIRED_HIGHWAYS
    needs_sidewalk = str(hw) in SIDEWALK_REQUIRED_HIGHWAYS
    print(f"    needs_sidewalk: {needs_sidewalk}")
    print(f"    sidewalk_tag:   {sidewalk}")
    print()
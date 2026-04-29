# neighbourhood_run/debug_sophus.py
import geopandas as gpd
import pandas as pd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))
network_proj = network.to_crs(CONFIG.project_crs)

boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
boundary_geom = boundary.geometry.iloc[0]

sbv = network_proj[network_proj['name'].fillna('').str.contains('Sophus Bauditz', case=False)]

for _, row in sbv.iterrows():
    midpoint = row.geometry.interpolate(0.5, normalized=True)
    inside = midpoint.within(boundary_geom)
    
    hw = row['highway']
    if isinstance(hw, list):
        hw = hw[0]
    
    sw_excl = row.get('_sidewalk_excluded', 'NOT_PRESENT')
    
    print(f"edge_id={row['edge_id']}")
    print(f"  required:           {row['required']}")
    print(f"  highway:            {hw}")
    print(f"  name:               {row['name']}")
    print(f"  length_m:           {row['length_m']:.1f}")
    print(f"  inside_boundary:    {inside}")
    print(f"  _sidewalk_excluded: {sw_excl}")
    print(f"  covered:            {row.get('covered', 'N/A')}")
    
    # Check all columns for clues
    for col in row.index:
        if col not in ('geometry', 'edge_id', 'required', 'highway', 'name', 
                        'length_m', 'covered', '_sidewalk_excluded', 'review_flag',
                        'reachable', 'osmid', 'coverage_pct', 'times_covered'):
            val = row[col]
            if val is not None and str(val) != 'nan' and str(val) != '':
                print(f"  {col}: {val}")
    print()
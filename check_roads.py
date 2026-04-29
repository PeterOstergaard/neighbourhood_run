# neighbourhood_run/check_roads.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))

for road_name in ['Silkeborgvej', 'Åby Ringvej', 'Viby Ringvej']:
    matches = network[network['name'].fillna('').str.contains(road_name, case=False)]
    if matches.empty:
        print(f"\n{road_name}: NOT IN NETWORK")
        continue
    
    print(f"\n{road_name}: {len(matches)} segments, {matches['length_m'].sum()/1000:.1f} km")
    
    # Show all available tags
    for _, row in matches.head(3).iterrows():
        print(f"  edge_id={row['edge_id']}")
        print(f"    highway:  {row.get('highway', 'N/A')}")
        print(f"    sidewalk: {row.get('sidewalk', 'N/A')}")
        print(f"    access:   {row.get('access', 'N/A')}")
        print(f"    required: {row.get('required', 'N/A')}")
        print(f"    covered:  {row.get('covered', 'N/A')}")
        print(f"    review:   {row.get('review_flag', 'N/A')}")
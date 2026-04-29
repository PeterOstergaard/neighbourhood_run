# neighbourhood_run/debug_excluded_area.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG
from src.neighbourhood_run.exclusions import load_excluded_ids

network = gpd.read_file(str(CONFIG.paths.processed_network))

# Check manual exclusions
excluded_ids = load_excluded_ids()
print(f"Manually excluded edge IDs: {len(excluded_ids)}")
if excluded_ids:
    print(f"  IDs: {sorted(excluded_ids)}")
    
    # What roads do these correspond to?
    excluded_edges = network[network['edge_id'].isin(excluded_ids)]
    print(f"\nExcluded segments:")
    for _, row in excluded_edges.iterrows():
        print(f"  edge_id={row['edge_id']}  name={row.get('name', 'unnamed')}  "
              f"hw={row['highway']}  len={row['length_m']:.1f}m  "
              f"required={row['required']}")

# Check the specific area - find segments that are NOT in the network
# but should be (gaps between existing segments)
print(f"\nChecking for gaps in the southwest area...")

roads_to_check = ['Vesterløkken', 'Elkjærvej', 'Sylbækvej', 'Egsagervej', 
                   'Ved Lunden', 'Klamsagervej']

for road in roads_to_check:
    matches = network[network['name'].fillna('').str.contains(road, case=False)]
    required = matches[matches['required'] == True]
    optional = matches[matches['required'] == False]
    excluded = matches[matches['edge_id'].isin(excluded_ids)]
    
    if matches.empty:
        print(f"\n{road}: NOT IN NETWORK AT ALL")
        continue
    
    print(f"\n{road}: {len(matches)} total, {len(required)} required, "
          f"{len(optional)} optional, {len(excluded)} manually excluded")
    
    # Show optional and excluded segments
    for _, row in optional.iterrows():
        status = "EXCLUDED" if row['edge_id'] in excluded_ids else "optional"
        print(f"  edge_id={row['edge_id']}  {status}  hw={row['highway']}  "
              f"len={row['length_m']:.1f}m")
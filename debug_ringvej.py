# neighbourhood_run/debug_ringvej.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG
from src.neighbourhood_run.network import _apply_sidewalk_filter

network = gpd.read_file(str(CONFIG.paths.processed_network))

# Check Åby Ringvej segments
ringvej = network[network['name'].fillna('').str.contains('Åby Ringvej', case=False)]
print(f"Åby Ringvej: {len(ringvej)} segments")
print(f"  required=True:  {(ringvej['required'] == True).sum()}")
print(f"  required=False: {(ringvej['required'] == False).sum()}")

# Simulate sidewalk filter on just these segments
test = ringvej.copy()
if "required" not in test.columns:
    test["required"] = True
result = _apply_sidewalk_filter(test)
print(f"\nAfter sidewalk filter alone:")
print(f"  required=True:  {(result['required'] == True).sum()}")
print(f"  required=False: {(result['required'] == False).sum()}")

# Check if gap-bridging is the problem
# Look at edge 1908 which IS optional - what's different about it?
for _, row in ringvej.iterrows():
    print(f"\n  edge_id={row['edge_id']}  required={row['required']}  length={row['length_m']:.1f}m")
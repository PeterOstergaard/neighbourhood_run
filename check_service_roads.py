# neighbourhood_run/check_service_roads.py
import geopandas as gpd
import pandas as pd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))

flagged = network[network["review_flag"].fillna("").str.len() > 0]

print(f"Total flagged: {len(flagged)}")
print(f"Total length: {flagged['length_m'].sum() / 1000:.1f} km")

print("\nLength distribution:")
bins = [0, 50, 75, 100, 150, 200, 500, 10000]
labels = ["<50m", "50-75m", "75-100m", "100-150m", "150-200m", "200-500m", ">500m"]

flagged["_bin"] = pd.cut(flagged["length_m"], bins=bins, labels=labels)
for label in labels:
    subset = flagged[flagged["_bin"] == label]
    if not subset.empty:
        print(f"  {label:>10}: {len(subset):4} segments, {subset['length_m'].sum()/1000:.1f} km")

# Show some examples of the longer ones
print("\nLongest unnamed service roads:")
top = flagged.nlargest(10, "length_m")
for _, row in top.iterrows():
    print(f"  edge_id={row['edge_id']:5}  {row['length_m']:.0f}m  highway={row['highway']}")


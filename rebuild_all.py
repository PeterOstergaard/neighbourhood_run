# neighbourhood_run/rebuild_all.py
"""
Full rebuild: network + coverage + map.
Run this after changing filtering rules or exclusions.
"""
import geopandas as gpd
from src.neighbourhood_run import boundary, network, coverage
from src.neighbourhood_run.config import CONFIG

print("=" * 60)
print("FULL REBUILD")
print("=" * 60)

# Step 1: Rebuild network
print("\n--- Step 1: Rebuilding network ---")
boundary_gdf = gpd.read_file(str(CONFIG.paths.raw_boundary))
network.build_runnable_network(boundary_gdf)

# Step 2: Re-run coverage
print("\n--- Step 2: Re-running coverage analysis ---")
coverage.analyze_coverage()

print("\n" + "=" * 60)
print("REBUILD COMPLETE")
print("=" * 60)
print("\nStart the app to see results: python app.py")
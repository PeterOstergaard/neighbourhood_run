# neighbourhood_run/analyze_coverage.py
"""
Runs coverage analysis and rebuilds the map.
"""
from src.neighbourhood_run import coverage, web

# Analyze which roads have been covered by GPS tracks
network_with_coverage = coverage.analyze_coverage()

# Rebuild the map with coverage visualization
web.create_network_map()

print("\nDone! Open the web app to see the coverage map.")
print("Run: python app.py")
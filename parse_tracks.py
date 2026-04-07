# neighbourhood_run/parse_tracks.py
from src.neighbourhood_run import tracks, web

# Parse any GPX files in the garmin activities folder
parsed = tracks.parse_all_tracks()

# Rebuild the map
web.create_network_map()

print(f"\nDone! Parsed {len(parsed)} tracks.")
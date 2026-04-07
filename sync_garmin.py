# neighbourhood_run/sync_garmin.py
from src.neighbourhood_run import garmin_sync, tracks, web

# Step 1: Download from Garmin
relevant = garmin_sync.run_full_sync()

# Step 2: Parse GPX files into tracks
parsed = tracks.parse_all_tracks()

# Step 3: Rebuild the map
web.create_network_map()

print(f"\nDone! Parsed {len(parsed)} tracks.")
# neighbourhood_run/sync_strava.py
"""
Syncs running activities from Strava and updates coverage incrementally.
"""
from src.neighbourhood_run import strava_sync, coverage

# Step 1: Sync from Strava
new_tracks = strava_sync.run_full_sync()

# Step 2: Update coverage incrementally (only test new tracks against uncovered edges)
if new_tracks is not None and not new_tracks.empty:
    print(f"\nUpdating coverage with {len(new_tracks)} new tracks...")
    coverage.update_coverage_incremental(new_tracks)
else:
    print("\nNo new tracks to process.")

print("\nDone! Start the app to see results: python app.py")
# neighbourhood_run/sync_strava.py
"""
Syncs running activities from Strava and updates coverage incrementally.
"""
from src.neighbourhood_run import strava_sync, coverage

result = strava_sync.run_full_sync()
new_tracks = result["tracks"]
new_activity_ids = result["new_activity_ids"]

if new_tracks is not None and not new_tracks.empty:
    print(f"\nUpdating coverage...")
    coverage.update_coverage_incremental(new_tracks)
else:
    print("\nNo new tracks to process.")

print("\nNew activity IDs:")
for aid in new_activity_ids:
    print(f"  - {aid}")

print("\nDone! Start the app to see results: python app.py")
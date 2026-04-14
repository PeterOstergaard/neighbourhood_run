# neighbourhood_run/fix_duplicates.py
"""
Diagnoses and fixes duplicate tracks and network edges.
"""
import geopandas as gpd
import pandas as pd
from pathlib import Path
from rich.console import Console
from src.neighbourhood_run.config import CONFIG

console = Console()

print("=" * 60)
print("DUPLICATE DIAGNOSTIC")
print("=" * 60)

# --- Check FIT files ---
garmin_dir = CONFIG.paths.raw_garmin
fit_files = list(garmin_dir.glob("*.fit"))
print(f"\nFIT files in folder: {len(fit_files)}")

# Check for duplicate filenames (shouldn't happen but let's verify)
names = [f.name for f in fit_files]
unique_names = set(names)
print(f"Unique filenames: {len(unique_names)}")
if len(names) != len(unique_names):
    print("  WARNING: Duplicate filenames found!")

# --- Check parsed tracks ---
tracks_path = CONFIG.paths.processed_tracks
if tracks_path.exists():
    tracks = gpd.read_file(str(tracks_path))
    print(f"\nParsed tracks: {len(tracks)}")

    if "source_file" in tracks.columns:
        unique_sources = tracks["source_file"].nunique()
        print(f"Unique source files: {unique_sources}")
        dupes = tracks[tracks.duplicated(subset=["source_file"], keep=False)]
        if not dupes.empty:
            print(f"Duplicate source files: {len(dupes)}")
            print("  Sample duplicates:")
            for sf in dupes["source_file"].unique()[:5]:
                count = len(tracks[tracks["source_file"] == sf])
                print(f"    {sf}: {count} entries")

    if "activity_id" in tracks.columns:
        unique_ids = tracks["activity_id"].nunique()
        print(f"Unique activity IDs: {unique_ids}")
        dupes = tracks[tracks.duplicated(subset=["activity_id"], keep=False)]
        if not dupes.empty:
            print(f"Duplicate activity IDs: {len(dupes)}")

# --- Check network edges ---
network_path = CONFIG.paths.processed_network
if network_path.exists():
    network = gpd.read_file(str(network_path))
    print(f"\nNetwork edges: {len(network)}")
    print(f"Unique edge IDs: {network['edge_id'].nunique()}")

    if "osmid" in network.columns:
        # Check for duplicate OSM IDs (these indicate duplicate edges)
        osmid_counts = network["osmid"].value_counts()
        dupes = osmid_counts[osmid_counts > 1]
        if not dupes.empty:
            print(f"OSM IDs appearing more than once: {len(dupes)}")
            print("  Top duplicates:")
            for osmid, count in dupes.head(10).items():
                name = network[network["osmid"] == osmid]["name"].iloc[0]
                print(f"    osmid={osmid} ({name}): {count} edges")

    if "review_flag" in network.columns:
        flagged = network[network["review_flag"].fillna("").str.len() > 0]
        print(f"\nFlagged segments: {len(flagged)}")
        # Count by flag type
        flag_reasons = {}
        for flag in flagged["review_flag"]:
            for reason in str(flag).split(";"):
                reason = reason.strip()
                if reason:
                    flag_reasons[reason] = flag_reasons.get(reason, 0) + 1
        print("  Flag breakdown:")
        for reason, count in sorted(flag_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")

# --- Fix: Deduplicate tracks ---
print("\n" + "=" * 60)
print("FIXING DUPLICATES")
print("=" * 60)

if tracks_path.exists():
    tracks = gpd.read_file(str(tracks_path))
    before = len(tracks)

    if "source_file" in tracks.columns:
        tracks_deduped = tracks.drop_duplicates(subset=["source_file"], keep="first")
    elif "activity_id" in tracks.columns:
        tracks_deduped = tracks.drop_duplicates(subset=["activity_id"], keep="first")
    else:
        tracks_deduped = tracks

    after = len(tracks_deduped)
    removed = before - after

    print(f"\nTracks before dedup: {before}")
    print(f"Tracks after dedup:  {after}")
    print(f"Removed: {removed}")

    if removed > 0:
        tracks_deduped = tracks_deduped.reset_index(drop=True)
        tracks_deduped.to_file(str(tracks_path), driver="GPKG", index=False)
        print(f"Saved deduplicated tracks to {tracks_path}")
    else:
        print("No duplicates found in tracks.")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
print("\nNext steps:")
print("  1. Re-run coverage: python analyze_coverage.py")
print("  2. Check the map:   python app.py")
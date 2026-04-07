# neighbourhood_run/check_files.py
from src.neighbourhood_run.config import CONFIG
from pathlib import Path

garmin_dir = CONFIG.paths.raw_garmin
print(f"Looking in: {garmin_dir}")
print(f"Directory exists: {garmin_dir.exists()}")

if garmin_dir.exists():
    fit_files = list(garmin_dir.glob("*.fit"))
    gpx_files = list(garmin_dir.glob("*.gpx"))
    all_files = list(garmin_dir.iterdir())
    
    print(f"Total files: {len(all_files)}")
    print(f"FIT files: {len(fit_files)}")
    print(f"GPX files: {len(gpx_files)}")
    
    if all_files:
        print(f"\nFirst 5 files:")
        for f in all_files[:5]:
            print(f"  {f.name}")
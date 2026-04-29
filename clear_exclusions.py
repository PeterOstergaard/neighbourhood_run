# neighbourhood_run/clear_exclusions.py
from src.neighbourhood_run.exclusions import load_excluded_ids, save_excluded_ids
from src.neighbourhood_run.config import CONFIG
from pathlib import Path

excluded = load_excluded_ids()
print(f"Current manual exclusions: {len(excluded)}")

confirm = input("Clear all manual exclusions? (yes/no): ").strip().lower()
if confirm in ("yes", "y"):
    # Delete the exclusions file
    path = CONFIG.paths.manual_exclusions
    if path.exists():
        path.unlink()
        print("Exclusions file deleted.")
    print("All manual exclusions cleared.")
    print("Run: python rebuild_all.py")
else:
    print("Cancelled.")
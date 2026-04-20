# neighbourhood_run/clean_all_data.py
"""
Removes all generated data for a clean-slate test.
Preserves config files and secrets.
"""
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()

# Directories to clean
dirs_to_clean = [
    "data/raw/boundaries",
    "data/raw/garmin",
    "data/raw/strava",
    "data/processed",
    "data/debug",
]

# Individual files to clean
files_to_clean = [
    "templates/map_view.html",
]

# Files to PRESERVE (just for reference)
preserve = [
    "data/manual/config.yaml",
    "data/manual/exclusions.gpkg",  # Keep manual exclusions if they exist
    "secrets.yaml",
]

print("=" * 60)
print("CLEAN ALL GENERATED DATA")
print("=" * 60)
print()
print("The following will be DELETED:")

for d in dirs_to_clean:
    dir_path = PROJECT_ROOT / d
    if dir_path.exists():
        file_count = sum(1 for _ in dir_path.rglob("*") if _.is_file())
        print(f"  📁 {d}/ ({file_count} files)")

for f in files_to_clean:
    file_path = PROJECT_ROOT / f
    if file_path.exists():
        print(f"  📄 {f}")

print()
print("The following will be PRESERVED:")
for p in preserve:
    file_path = PROJECT_ROOT / p
    status = "exists" if file_path.exists() else "not found"
    print(f"  ✔ {p} ({status})")

print()
confirm = input("Proceed? (yes/no): ").strip().lower()

if confirm not in ("yes", "y"):
    print("Aborted.")
    exit()

# Clean directories
for d in dirs_to_clean:
    dir_path = PROJECT_ROOT / d
    if dir_path.exists():
        shutil.rmtree(dir_path)
        print(f"  Deleted: {d}/")

# Clean individual files
for f in files_to_clean:
    file_path = PROJECT_ROOT / f
    if file_path.exists():
        file_path.unlink()
        print(f"  Deleted: {f}")

print()
print("✔ All generated data cleaned.")
print()
print("Next step: Run the full pipeline:")
print("  python run_full_pipeline.py")
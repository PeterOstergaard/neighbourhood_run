# neighbourhood_run/inspect_garmin_export.py
import zipfile
import io
from pathlib import Path
from collections import Counter

# Change this to the path of your Garmin export ZIP file
ZIP_PATH = r"C:\Users\peo\Downloads\ce3ea773-f332-4733-8b16-a2c9f363e314_1.zip"

print("=" * 60)
print("GARMIN EXPORT ZIP INSPECTOR")
print("=" * 60)

zf = zipfile.ZipFile(ZIP_PATH)
all_files = zf.namelist()

print(f"\nTop-level ZIP contains {len(all_files)} entries")

# Show top-level structure
print(f"\nTop-level contents:")
for f in all_files[:30]:
    print(f"  {f}")
if len(all_files) > 30:
    print(f"  ... and {len(all_files) - 30} more")

# Count file extensions at top level
extensions = Counter()
for f in all_files:
    ext = Path(f).suffix.lower()
    if ext:
        extensions[ext] += 1

print(f"\nTop-level file types:")
for ext, count in extensions.most_common():
    print(f"  {ext}: {count}")

# Find nested ZIP files
nested_zips = [f for f in all_files if f.lower().endswith('.zip')]
print(f"\nNested ZIP files found: {len(nested_zips)}")

for nz in nested_zips:
    print(f"\n{'─' * 50}")
    print(f"Inspecting nested ZIP: {nz}")
    print(f"{'─' * 50}")

    try:
        nested_data = zf.read(nz)
        nested_zf = zipfile.ZipFile(io.BytesIO(nested_data))
        nested_files = nested_zf.namelist()

        print(f"  Contains {len(nested_files)} entries")

        # Count extensions
        nested_ext = Counter()
        for f in nested_files:
            ext = Path(f).suffix.lower()
            if ext:
                nested_ext[ext] += 1

        print(f"  File types:")
        for ext, count in nested_ext.most_common():
            print(f"    {ext}: {count}")

        # Find FIT files
        fit_files = [f for f in nested_files if f.lower().endswith('.fit')]
        if fit_files:
            fit_dirs = set()
            for f in fit_files:
                fit_dirs.add(str(Path(f).parent))
            print(f"  FIT files: {len(fit_files)}")
            print(f"  FIT directories:")
            for d in sorted(fit_dirs):
                count = sum(1 for f in fit_files if str(Path(f).parent) == d)
                print(f"    {d}/ ({count} files)")
            print(f"  Sample FIT filenames:")
            for f in fit_files[:5]:
                print(f"    {f}")

        # Find GPX files
        gpx_files = [f for f in nested_files if f.lower().endswith('.gpx')]
        if gpx_files:
            print(f"  GPX files: {len(gpx_files)}")
            print(f"  Sample GPX filenames:")
            for f in gpx_files[:5]:
                print(f"    {f}")

        nested_zf.close()

    except Exception as e:
        print(f"  Error reading nested ZIP: {e}")

zf.close()

print("\n" + "=" * 60)
print("INSPECTION COMPLETE")
print("=" * 60)
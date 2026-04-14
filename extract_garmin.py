# neighbourhood_run/extract_garmin.py
"""
Smart extraction of Garmin bulk export.
Opens FIT files inside nested ZIPs, checks activity type and location,
and only extracts running activities near home.
"""
import zipfile
import io
import fitdecode
from pathlib import Path
from shapely.geometry import Point
import geopandas as gpd
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TimeRemainingColumn
)

from src.neighbourhood_run.config import CONFIG

console = Console()

# ══════════════════════════════════════════════════════════
# CONFIGURATION — Update this path to your ZIP file
# ══════════════════════════════════════════════════════════
ZIP_PATH = r"C:\Users\peo\Downloads\ce3ea773-f332-4733-8b16-a2c9f363e314_1.zip"
# ══════════════════════════════════════════════════════════


def get_home_point():
    """Load home location and project to local CRS."""
    home_gdf = gpd.read_file(str(CONFIG.paths.processed_home))
    home_proj = home_gdf.to_crs(CONFIG.project_crs)
    return home_proj.geometry.iloc[0]


def quick_parse_fit(fit_bytes: bytes, home_point, radius_m: float) -> dict | None:
    """
    Quickly parses a FIT file from bytes to determine:
    1. Is it a running activity?
    2. Does it start near home?

    Returns a dict with metadata if relevant, None otherwise.
    Only reads enough of the file to make these decisions.
    """
    activity_type = None
    first_lat = None
    first_lon = None
    point_count = 0

    try:
        with fitdecode.FitReader(io.BytesIO(fit_bytes)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                # Check activity type from session record
                if frame.name == 'session':
                    sport_field = frame.get_field('sport')
                    if sport_field is not None:
                        activity_type = str(sport_field.value).lower()

                        # Early exit: not a running activity
                        allowed = {t.lower() for t in CONFIG.garmin.activity_types}
                        if activity_type not in allowed:
                            return None

                # Get first GPS point from record messages
                if frame.name == 'record' and first_lat is None:
                    lat_field = frame.get_field('position_lat')
                    lon_field = frame.get_field('position_long')

                    if lat_field is not None and lon_field is not None:
                        lat_raw = lat_field.value
                        lon_raw = lon_field.value

                        if lat_raw is not None and lon_raw is not None:
                            first_lat = lat_raw * (180.0 / 2**31)
                            first_lon = lon_raw * (180.0 / 2**31)

                            if abs(first_lat) > 90 or abs(first_lon) > 180:
                                first_lat = None
                                first_lon = None
                                continue

                            # Check distance from home
                            start_gs = gpd.GeoSeries(
                                [Point(first_lon, first_lat)],
                                crs="EPSG:4326"
                            ).to_crs(CONFIG.project_crs)
                            dist = home_point.distance(start_gs.iloc[0])

                            if dist > radius_m:
                                return None

                # Count GPS points (for basic validation)
                if frame.name == 'record':
                    point_count += 1

    except Exception:
        return None

    # Must be a running activity with GPS data near home
    if activity_type is None:
        return None

    allowed = {t.lower() for t in CONFIG.garmin.activity_types}
    if activity_type not in allowed:
        return None

    if first_lat is None or point_count < 2:
        return None

    return {
        "activity_type": activity_type,
        "start_lat": first_lat,
        "start_lon": first_lon,
        "point_count": point_count,
    }


def extract_relevant_activities():
    """
    Opens the Garmin export ZIP, inspects nested ZIPs,
    and extracts only relevant FIT files.
    """
    zip_path = Path(ZIP_PATH)
    if not zip_path.exists():
        console.log(f"[red]ZIP file not found: {zip_path}[/red]")
        console.log("Please update ZIP_PATH in this script.")
        return

    output_dir = CONFIG.paths.raw_garmin
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check what's already extracted
    already_extracted = {f.name for f in output_dir.glob("*.fit")}
    if already_extracted:
        console.log(f"Already extracted: {len(already_extracted)} FIT files")

    # Load home location
    console.log("Loading home location...")
    home_point = get_home_point()
    radius_m = CONFIG.garmin.import_radius_km * 1000
    console.log(f"Filter radius: {CONFIG.garmin.import_radius_km} km from home")

    # Open the outer ZIP
    console.log(f"\nOpening: {zip_path.name}")
    outer_zip = zipfile.ZipFile(str(zip_path))

    # Find nested ZIPs containing activity files
    nested_zips = [
        f for f in outer_zip.namelist()
        if f.lower().endswith('.zip')
        and 'uploaded-files' in f.lower()
    ]

    console.log(f"Found {len(nested_zips)} nested ZIP files with activities")

    total_checked = 0
    total_extracted = 0
    total_skipped_type = 0
    total_skipped_location = 0
    total_skipped_nodata = 0
    total_already_have = 0
    total_errors = 0

    for nz_name in sorted(nested_zips):
        console.log(f"\n[bold]Processing: {Path(nz_name).name}[/bold]")

        # Read the nested ZIP into memory
        nested_data = outer_zip.read(nz_name)
        nested_zip = zipfile.ZipFile(io.BytesIO(nested_data))

        fit_files = [
            f for f in nested_zip.namelist()
            if f.lower().endswith('.fit')
        ]

        console.log(f"  Contains {len(fit_files)} FIT files")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Checking files...",
                total=len(fit_files)
            )

            for fit_name in fit_files:
                total_checked += 1

                # Skip if already extracted
                out_filename = Path(fit_name).name
                if out_filename in already_extracted:
                    total_already_have += 1
                    progress.update(task, advance=1)
                    continue

                try:
                    # Read the FIT file from the nested ZIP
                    fit_bytes = nested_zip.read(fit_name)

                    # Quick parse to check relevance
                    result = quick_parse_fit(fit_bytes, home_point, radius_m)

                    if result is None:
                        # Determine why it was skipped (for stats)
                        # We can't easily distinguish, so just count as filtered
                        total_skipped_type += 1
                    else:
                        # This is a relevant activity — extract it
                        out_path = output_dir / out_filename
                        with open(str(out_path), 'wb') as f:
                            f.write(fit_bytes)
                        total_extracted += 1
                        already_extracted.add(out_filename)

                except Exception as e:
                    total_errors += 1

                progress.update(
                    task, advance=1,
                    description=(
                        f"Checked: {total_checked} | "
                        f"Extracted: {total_extracted} | "
                        f"Filtered: {total_skipped_type}"
                    )
                )

        nested_zip.close()

    outer_zip.close()

    # Print final summary
    console.log("")
    console.log("[bold cyan]═══ Extraction Complete ═══[/bold cyan]")
    console.log(f"  Total FIT files checked:   {total_checked:,}")
    console.log(f"  Already had:               {total_already_have:,}")
    console.log(f"  Filtered out:              {total_skipped_type:,}")
    console.log(f"  Errors:                    {total_errors:,}")
    console.log(f"  [green]Extracted (relevant):     {total_extracted:,}[/green]")
    console.log(f"")
    console.log(f"  Relevant FIT files saved to: {output_dir}")
    console.log(f"  Total files in folder:       {len(list(output_dir.glob('*.fit')))}")


if __name__ == "__main__":
    extract_relevant_activities()
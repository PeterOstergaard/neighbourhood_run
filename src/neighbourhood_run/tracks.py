# src/neighbourhood_run/tracks.py
import geopandas as gpd
import gpxpy
import fitdecode
import pandas as pd
from pathlib import Path
from shapely.geometry import LineString, Point
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
)

from .config import CONFIG

console = Console()


def _parse_gpx_file(gpx_path: Path) -> dict | None:
    """
    Parses a single GPX file and returns a dictionary with track data.
    Returns None if the file cannot be parsed or has no valid track points.
    """
    try:
        with open(str(gpx_path), 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f)
    except Exception:
        return None

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.latitude is not None and point.longitude is not None:
                    points.append((point.longitude, point.latitude))

    if len(points) < 2:
        return None

    start_time = None
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.time is not None:
                    start_time = point.time
                    break
            if start_time:
                break

    return {
        "activity_id": gpx_path.stem,
        "source_file": gpx_path.name,
        "geometry": LineString(points),
        "start_time": str(start_time) if start_time else None,
        "point_count": len(points),
        "activity_type": "running",
    }


def _parse_fit_file(fit_path: Path) -> dict | None:
    """
    Parses a single FIT file and returns a dictionary with track data.
    Returns None if the file cannot be parsed or has no valid track points.
    """
    points = []
    start_time = None
    activity_type = None

    try:
        with fitdecode.FitReader(str(fit_path)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                if frame.name == 'session':
                    sport_field = frame.get_field('sport')
                    if sport_field is not None:
                        activity_type = str(sport_field.value).lower()

                if frame.name == 'record':
                    lat_field = frame.get_field('position_lat')
                    lon_field = frame.get_field('position_long')
                    time_field = frame.get_field('timestamp')

                    if lat_field is None or lon_field is None:
                        continue

                    lat_raw = lat_field.value
                    lon_raw = lon_field.value

                    if lat_raw is None or lon_raw is None:
                        continue

                    lat = lat_raw * (180.0 / 2**31)
                    lon = lon_raw * (180.0 / 2**31)

                    if abs(lat) > 90 or abs(lon) > 180:
                        continue

                    points.append((lon, lat))

                    if start_time is None and time_field is not None:
                        start_time = time_field.value

    except Exception:
        return None

    if len(points) < 2:
        return None

    return {
        "activity_id": fit_path.stem,
        "source_file": fit_path.name,
        "geometry": LineString(points),
        "start_time": str(start_time) if start_time else None,
        "point_count": len(points),
        "activity_type": activity_type,
    }


def _parse_file(file_path: Path) -> dict | None:
    """Routes a file to the correct parser based on extension."""
    suffix = file_path.suffix.lower()
    if suffix == '.gpx':
        return _parse_gpx_file(file_path)
    elif suffix == '.fit':
        return _parse_fit_file(file_path)
    else:
        return None


def parse_all_tracks() -> gpd.GeoDataFrame:
    """
    Parses all downloaded GPX and FIT files and returns a GeoDataFrame
    with one row per activity. Filters to running activities only.
    Saves the result to disk.
    """
    console.log("[bold]Parsing activity files into tracks...[/bold]")

    garmin_dir = CONFIG.paths.raw_garmin
    tracks_path = CONFIG.paths.processed_tracks
    summary_path = CONFIG.paths.track_summary

    tracks_path.parent.mkdir(parents=True, exist_ok=True)

    # Find all parseable files
    activity_files = sorted(
        list(garmin_dir.glob("*.gpx")) +
        list(garmin_dir.glob("*.fit")) +
        list(garmin_dir.glob("*.FIT"))
    )

    if not activity_files:
        console.log("[yellow]No GPX or FIT files found to parse.[/yellow]")
        console.log(f"  Expected location: {garmin_dir}")
        return gpd.GeoDataFrame(
            columns=["activity_id", "source_file", "start_time",
                      "point_count", "activity_type", "length_m", "geometry"]
        )

    console.log(f"  Found {len(activity_files)} activity files")
    console.log(f"    GPX: {sum(1 for f in activity_files if f.suffix.lower() == '.gpx')}")
    console.log(f"    FIT: {sum(1 for f in activity_files if f.suffix.lower() == '.fit')}")

    # Check which files have already been parsed
    already_parsed = set()
    if tracks_path.exists():
        try:
            existing = gpd.read_file(str(tracks_path))
            if "source_file" in existing.columns:
                already_parsed = set(existing["source_file"].tolist())
                console.log(f"  Already parsed: {len(already_parsed)} files")
        except Exception:
            pass

    # Filter to files that need parsing
    files_to_parse = [
        f for f in activity_files
        if f.name not in already_parsed
    ]

    if not files_to_parse:
        console.log("  All activity files already parsed.")
        existing = gpd.read_file(str(tracks_path))
        _print_summary(existing)
        return existing

    console.log(f"  Parsing {len(files_to_parse)} new files...")

    # Parse files with progress bar
    new_tracks = []
    failed = 0
    skipped_type = 0

    allowed_types = {t.lower() for t in CONFIG.garmin.activity_types}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing...", total=len(files_to_parse))

        for activity_file in files_to_parse:
            result = _parse_file(activity_file)

            if result is None:
                failed += 1
            else:
                act_type = result.get("activity_type", "")
                if act_type and act_type not in allowed_types:
                    skipped_type += 1
                else:
                    new_tracks.append(result)

            progress.update(task, advance=1)

    console.log(f"  Successfully parsed: {len(new_tracks)}")
    if failed > 0:
        console.log(f"  [yellow]Failed to parse: {failed}[/yellow]")
    if skipped_type > 0:
        console.log(f"  Skipped (wrong activity type): {skipped_type}")

    if not new_tracks:
        console.log("  [yellow]No new valid running tracks found.[/yellow]")
        if tracks_path.exists():
            existing = gpd.read_file(str(tracks_path))
            _print_summary(existing)
            return existing
        return gpd.GeoDataFrame()

    # Create GeoDataFrame from newly parsed tracks
    new_gdf = gpd.GeoDataFrame(new_tracks, crs="EPSG:4326")

    # Ensure consistent columns
    for col in ["activity_type", "source_file"]:
        if col not in new_gdf.columns:
            new_gdf[col] = ""

    # Calculate track length in meters
    new_gdf_proj = new_gdf.to_crs(CONFIG.project_crs)
    new_gdf["length_m"] = new_gdf_proj.geometry.length

    # Merge with existing parsed tracks
    if already_parsed and tracks_path.exists():
        existing_gdf = gpd.read_file(str(tracks_path))
        for col in new_gdf.columns:
            if col not in existing_gdf.columns and col != "geometry":
                existing_gdf[col] = ""
        for col in existing_gdf.columns:
            if col not in new_gdf.columns and col != "geometry":
                new_gdf[col] = ""
        combined = pd.concat([existing_gdf, new_gdf], ignore_index=True)
    else:
        combined = new_gdf

    # Save tracks
    combined.to_file(str(tracks_path), driver="GPKG", index=False)
    console.log(f"  [green]✔[/green] Saved {len(combined)} tracks to '{tracks_path}'")

    # Save summary
    _save_summary(combined, summary_path)
    _print_summary(combined)

    return combined


def _save_summary(tracks_gdf: gpd.GeoDataFrame, summary_path: Path):
    """Saves a CSV summary of all tracks."""
    summary = tracks_gdf.drop(columns=["geometry"]).copy()
    summary["length_km"] = summary["length_m"] / 1000
    summary = summary.sort_values("start_time", ascending=False)

    csv_path = str(summary_path).replace(".gpkg", ".csv")
    summary.to_csv(csv_path, index=False)
    console.log(f"  [green]✔[/green] Saved track summary to '{csv_path}'")


def _print_summary(tracks_gdf: gpd.GeoDataFrame):
    """Prints a summary of all parsed tracks."""
    if tracks_gdf.empty:
        console.log("  No tracks to summarize.")
        return

    total_km = tracks_gdf["length_m"].sum() / 1000

    console.log(f"\n  [bold]Track Summary:[/bold]")
    console.log(f"    Total tracks:   {len(tracks_gdf)}")
    console.log(f"    Total distance: {total_km:,.1f} km")

    if "start_time" in tracks_gdf.columns:
        valid_times = tracks_gdf["start_time"].dropna()
        if not valid_times.empty:
            earliest = valid_times.min()
            latest = valid_times.max()
            console.log(f"    Date range:     {earliest} to {latest}")

    if "activity_type" in tracks_gdf.columns:
        type_counts = tracks_gdf["activity_type"].value_counts()
        if not type_counts.empty:
            console.log(f"    Activity types:")
            for act_type, count in type_counts.items():
                console.log(f"      {act_type}: {count}")
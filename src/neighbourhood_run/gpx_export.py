# src/neighbourhood_run/gpx_export.py
"""
Exports planned routes as GPX track files.
Track-only export: no generated turn waypoints.
"""
import gpxpy
import gpxpy.gpx
import geopandas as gpd
from pathlib import Path
from pyproj import Transformer
from rich.console import Console
from .config import CONFIG

console = Console()


def export_route_gpx(route_id: int) -> Path:
    """
    Exports a single planned route as a GPX file.
    Includes only track points and metadata.
    No generated turn waypoints.
    Returns the path to the GPX file.
    """
    routes_gdf = gpd.read_file(str(CONFIG.paths.planned_routes))
    route = routes_gdf[routes_gdf["route_id"] == route_id]

    if route.empty:
        raise ValueError(f"Route {route_id} not found")

    route_row = route.iloc[0]
    route_geom = route_row.geometry

    # Project to WGS84 for GPX
    if str(routes_gdf.crs) != "EPSG:4326":
        transformer = Transformer.from_crs(
            str(routes_gdf.crs), "EPSG:4326", always_xy=True
        )
        coords_proj = list(route_geom.coords)
        coords_wgs84 = [transformer.transform(x, y) for x, y in coords_proj]
    else:
        coords_wgs84 = list(route_geom.coords)

    # Create GPX
    gpx = gpxpy.gpx.GPX()
    gpx.name = route_row["route_name"]
    gpx.description = (
        f"Planned route for Neighbourhood Run | "
        f"Distance: {route_row['distance_km']} km | "
        f"New coverage: {route_row['new_coverage_km']} km | "
        f"Segments: {route_row['segments_covered']}"
    )

    # Add track
    track = gpxpy.gpx.GPXTrack()
    track.name = route_row["route_name"]
    gpx.tracks.append(track)

    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    for lon, lat in coords_wgs84:
        segment.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon))

    # Save
    export_dir = CONFIG.paths.planned_routes.parent / "gpx"
    export_dir.mkdir(parents=True, exist_ok=True)

    filename = f"route_{route_id:02d}_{route_row['route_name'].replace(' ', '_')}.gpx"
    output_path = export_dir / filename

    with open(str(output_path), 'w', encoding='utf-8') as f:
        f.write(gpx.to_xml())

    console.log(f"[green]✔[/green] GPX exported to: {output_path}")
    return output_path
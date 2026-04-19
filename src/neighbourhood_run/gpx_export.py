# src/neighbourhood_run/gpx_export.py
"""
Exports planned routes as GPX files with waypoints for navigation.
"""
import gpxpy
import gpxpy.gpx
import geopandas as gpd
import numpy as np
from pathlib import Path
from shapely.geometry import Point
from pyproj import Transformer
from rich.console import Console
from .config import CONFIG

console = Console()


def export_route_gpx(route_id: int) -> Path:
    """
    Exports a single planned route as a GPX file.
    Includes track points and turn-by-turn waypoints.
    Returns the path to the GPX file.
    """
    routes_gdf = gpd.read_file(str(CONFIG.paths.planned_routes))
    route = routes_gdf[routes_gdf["route_id"] == route_id]

    if route.empty:
        raise ValueError(f"Route {route_id} not found")

    route_row = route.iloc[0]
    route_geom = route_row.geometry

    # Project to WGS84 for GPX
    if routes_gdf.crs != "EPSG:4326":
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

    # Add turn waypoints
    waypoints = _generate_waypoints(coords_wgs84)
    for i, (lon, lat, instruction) in enumerate(waypoints):
        wp = gpxpy.gpx.GPXWaypoint(lat, lon)
        wp.name = f"WP{i+1}: {instruction}"
        wp.description = instruction
        gpx.waypoints.append(wp)

    # Save
    export_dir = CONFIG.paths.planned_routes.parent / "gpx"
    export_dir.mkdir(parents=True, exist_ok=True)

    filename = f"route_{route_id:02d}_{route_row['route_name'].replace(' ', '_')}.gpx"
    output_path = export_dir / filename

    with open(str(output_path), 'w', encoding='utf-8') as f:
        f.write(gpx.to_xml())

    console.log(f"[green]✔[/green] GPX exported to: {output_path}")
    return output_path


def _generate_waypoints(coords_wgs84: list) -> list:
    """
    Generates turn-by-turn waypoints from a coordinate list.
    Detects significant direction changes and creates navigation instructions.
    """
    if len(coords_wgs84) < 3:
        return [(coords_wgs84[0][0], coords_wgs84[0][1], "Start"),
                (coords_wgs84[-1][0], coords_wgs84[-1][1], "Finish")]

    waypoints = []
    # Start
    waypoints.append((coords_wgs84[0][0], coords_wgs84[0][1], "Start"))

    # Detect turns (significant bearing changes)
    TURN_THRESHOLD = 30  # degrees

    for i in range(1, len(coords_wgs84) - 1):
        # Calculate bearings
        bearing_in = _bearing(coords_wgs84[i-1], coords_wgs84[i])
        bearing_out = _bearing(coords_wgs84[i], coords_wgs84[i+1])

        # Angle difference
        angle_diff = (bearing_out - bearing_in + 360) % 360
        if angle_diff > 180:
            angle_diff = 360 - angle_diff
            direction = "left"
        else:
            direction = "right"

        if angle_diff > TURN_THRESHOLD:
            if angle_diff > 120:
                instruction = f"Sharp {direction}"
            elif angle_diff > 60:
                instruction = f"Turn {direction}"
            else:
                instruction = f"Bear {direction}"

            waypoints.append((
                coords_wgs84[i][0], coords_wgs84[i][1], instruction
            ))

    # Finish
    waypoints.append((coords_wgs84[-1][0], coords_wgs84[-1][1], "Finish"))

    return waypoints


def _bearing(p1, p2):
    """Calculates bearing between two (lon, lat) points in degrees."""
    lon1, lat1 = np.radians(p1[0]), np.radians(p1[1])
    lon2, lat2 = np.radians(p2[0]), np.radians(p2[1])

    dlon = lon2 - lon1
    x = np.sin(dlon) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)

    bearing = np.degrees(np.arctan2(x, y))
    return (bearing + 360) % 360
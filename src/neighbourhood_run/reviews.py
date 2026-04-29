# src/neighbourhood_run/reviews.py
"""
Route review and segment override management.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

import geopandas as gpd
from rich.console import Console

from .config import CONFIG

console = Console()

VALID_REVIEW_STATUSES = {
    "sidewalk_present",
    "runnable_no_sidewalk",
    "not_runnable",
    "unsure",
}


def _load_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_segment_overrides() -> list:
    """Loads segment overrides from JSON."""
    return _load_json(CONFIG.paths.segment_overrides, [])


def save_segment_overrides(overrides: list):
    """Saves segment overrides to JSON."""
    _save_json(CONFIG.paths.segment_overrides, overrides)


def set_segment_override(edge_id: int, status: str) -> dict:
    """
    Sets or updates a segment override.
    """
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {status}")

    overrides = load_segment_overrides()
    now = datetime.now(timezone.utc).isoformat()

    # update existing if present
    updated = False
    for row in overrides:
        if row["edge_id"] == edge_id:
            row["status"] = status
            row["reviewed_at"] = now
            updated = True
            break

    if not updated:
        overrides.append({
            "edge_id": edge_id,
            "status": status,
            "reviewed_at": now,
        })

    save_segment_overrides(overrides)

    return {
        "edge_id": edge_id,
        "status": status,
        "reviewed_at": now,
    }


def load_route_reviews() -> list:
    """Loads reviewed route/activity associations."""
    return _load_json(CONFIG.paths.route_reviews, [])


def save_route_reviews(route_reviews: list):
    """Saves reviewed route/activity associations."""
    _save_json(CONFIG.paths.route_reviews, route_reviews)


def record_route_review(route_id: int, activity_ids: list[int]):
    """
    Records that a route review was performed for a route and one or more activities.
    """
    reviews = load_route_reviews()
    reviews.append({
        "route_id": route_id,
        "activity_ids": activity_ids,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    save_route_reviews(reviews)


def apply_segment_overrides(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Applies local user overrides to the network.
    Highest priority over OSM-derived classification.
    """
    overrides = load_segment_overrides()
    if not overrides:
        return edges

    console.log(f"Applying {len(overrides)} segment overrides...")

    override_map = {row["edge_id"]: row["status"] for row in overrides}

    # Make sure columns exist
    if "required" not in edges.columns:
        edges["required"] = True
    if "review_flag" not in edges.columns:
        edges["review_flag"] = ""

    for idx, row in edges.iterrows():
        eid = row["edge_id"]
        if eid not in override_map:
            continue

        status = override_map[eid]

        if status == "sidewalk_present":
            edges.at[idx, "required"] = True
            edges.at[idx, "review_flag"] = ""
        elif status == "runnable_no_sidewalk":
            edges.at[idx, "required"] = True
            edges.at[idx, "review_flag"] = ""
        elif status == "not_runnable":
            # mark for exclusion by setting required False and review cleared
            edges.at[idx, "required"] = False
            edges.at[idx, "review_flag"] = ""
        elif status == "unsure":
            # leave as-is
            pass

    return edges


def suggest_route_matches(new_activity_ids: list[str], max_matches: int = 5) -> list[dict]:
    """
    Suggests likely planned routes for a set of recent activities.

    Current heuristic:
    - compare each new track geometry against each planned route geometry
    - rank by overlap ratio (buffered intersection over route length)

    Returns a list of suggested route matches.
    """
    tracks_path = CONFIG.paths.processed_tracks
    routes_path = CONFIG.paths.planned_routes

    if not tracks_path.exists() or not routes_path.exists():
        return []

    tracks = gpd.read_file(str(tracks_path))
    routes = gpd.read_file(str(routes_path))

    if tracks.empty or routes.empty:
        return []

    tracks = tracks.to_crs(CONFIG.project_crs)
    routes = routes.to_crs(CONFIG.project_crs)

    recent_tracks = tracks[tracks["activity_id"].astype(str).isin([str(x) for x in new_activity_ids])]
    if recent_tracks.empty:
        return []

    # Combine recent tracks into one geometry
    recent_union = recent_tracks.geometry.union_all() if hasattr(recent_tracks.geometry, "union_all") else recent_tracks.geometry.unary_union
    recent_buffer = recent_union.buffer(20)

    matches = []
    for _, route in routes.iterrows():
        route_geom = route.geometry
        route_len = route_geom.length
        if route_len <= 0:
            continue

        overlap = route_geom.intersection(recent_buffer)
        overlap_len = overlap.length if not overlap.is_empty else 0
        overlap_pct = overlap_len / route_len * 100

        if overlap_pct > 5:  # ignore clearly irrelevant matches
            matches.append({
                "route_id": int(route["route_id"]),
                "route_name": route["route_name"],
                "distance_km": float(route["distance_km"]),
                "new_coverage_km": float(route["new_coverage_km"]),
                "overlap_pct": round(overlap_pct, 1),
            })

    matches.sort(key=lambda x: x["overlap_pct"], reverse=True)
    return matches[:max_matches]


def get_route_review_payload(route_id: int, activity_ids: list[str]) -> dict:
    """
    Returns payload for route review UI:
    - route geometry
    - selected route segment edge_ids
    - recent track geometries
    - route-segment subset of network only
    """
    routes = gpd.read_file(str(CONFIG.paths.planned_routes)).to_crs("EPSG:4326")
    network = gpd.read_file(str(CONFIG.paths.processed_network)).to_crs("EPSG:4326")
    tracks = gpd.read_file(str(CONFIG.paths.processed_tracks)).to_crs("EPSG:4326")

    route = routes[routes["route_id"] == route_id]
    if route.empty:
        raise ValueError(f"Route {route_id} not found")

    route_row = route.iloc[0]
    covered_edge_ids = route_row.get("covered_edge_ids", "")
    route_edge_ids = []
    if covered_edge_ids:
        route_edge_ids = [int(x) for x in str(covered_edge_ids).split(",") if str(x).strip()]

    route_segments = network[network["edge_id"].isin(route_edge_ids)].copy()
    recent_tracks = tracks[tracks["activity_id"].astype(str).isin([str(x) for x in activity_ids])].copy()

    return {
        "route": json.loads(route.to_json()),
        "route_segments": json.loads(route_segments.to_json()),
        "recent_tracks": json.loads(recent_tracks.to_json()),
        "activity_ids": activity_ids,
        "route_id": route_id,
        "route_name": route_row["route_name"],
    }
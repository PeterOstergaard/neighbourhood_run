# src/neighbourhood_run/exclusions.py
"""
Manages manual segment exclusions.
Stores excluded edge IDs in a GeoPackage file.
"""
import geopandas as gpd
import pandas as pd
from pathlib import Path
from rich.console import Console
from .config import CONFIG

console = Console()


def _get_exclusions_path() -> Path:
    """Returns the path to the exclusions file."""
    return CONFIG.paths.manual_exclusions


def load_excluded_ids() -> set:
    """Loads the set of manually excluded edge IDs."""
    path = _get_exclusions_path()
    if not path.exists():
        return set()

    try:
        gdf = gpd.read_file(str(path), layer="excluded_edges")
        if "edge_id" in gdf.columns:
            return set(gdf["edge_id"].tolist())
    except Exception:
        pass

    return set()


def save_excluded_ids(excluded_ids: set):
    """Saves the set of excluded edge IDs to the exclusions file."""
    path = _get_exclusions_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Load the full network to get geometries for excluded edges
    network = gpd.read_file(str(CONFIG.paths.processed_network))

    excluded = network[network["edge_id"].isin(excluded_ids)].copy()

    if excluded.empty:
        # Save an empty layer with the right schema
        excluded = gpd.GeoDataFrame(
            {"edge_id": pd.Series(dtype="int64")},
            geometry=gpd.GeoSeries(dtype="geometry"),
            crs=network.crs
        )

    excluded[["edge_id", "geometry"]].to_file(
        str(path), driver="GPKG", layer="excluded_edges", index=False
    )


def toggle_exclusion(edge_id: int) -> dict:
    """
    Toggles the exclusion status of a single edge.
    Returns a dict with the new status.
    """
    excluded = load_excluded_ids()

    if edge_id in excluded:
        excluded.remove(edge_id)
        status = "included"
    else:
        excluded.add(edge_id)
        status = "excluded"

    save_excluded_ids(excluded)

    return {
        "edge_id": edge_id,
        "status": status,
        "total_excluded": len(excluded),
    }


def get_exclusion_summary() -> dict:
    """Returns a summary of current exclusions."""
    excluded = load_excluded_ids()
    return {
        "excluded_count": len(excluded),
        "excluded_ids": sorted(excluded),
    }
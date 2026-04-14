# src/neighbourhood_run/coverage.py
"""
Coverage analysis: determines which road segments have been covered
by GPS tracks using buffer-based spatial matching.
"""
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
)

from .config import CONFIG

console = Console()

# Coverage parameters
BUFFER_DISTANCE_M = 15  # meters - buffer around each network edge
COVERAGE_THRESHOLD = 0.80  # 80% of edge length must be covered


def analyze_coverage() -> gpd.GeoDataFrame:
    """
    Main entry point for coverage analysis.
    Loads the network and tracks, performs buffer-based matching,
    and returns the network with coverage information added.
    """
    console.log("[bold cyan]═══ Coverage Analysis ═══[/bold cyan]")

    # Load data
    console.log("[bold]Step 1: Loading data...[/bold]")
    network = gpd.read_file(str(CONFIG.paths.processed_network))
    tracks_path = CONFIG.paths.processed_tracks

    if not tracks_path.exists():
        console.log("[yellow]No tracks found. All segments marked as uncovered.[/yellow]")
        network["covered"] = False
        network["coverage_pct"] = 0.0
        network["times_covered"] = 0
        _save_and_summarize(network)
        return network

    tracks = gpd.read_file(str(tracks_path))

    if tracks.empty:
        console.log("[yellow]No tracks found. All segments marked as uncovered.[/yellow]")
        network["covered"] = False
        network["coverage_pct"] = 0.0
        network["times_covered"] = 0
        _save_and_summarize(network)
        return network

    console.log(f"  Network: {len(network)} edges, {network['length_m'].sum() / 1000:.1f} km")
    console.log(f"  Tracks:  {len(tracks)} GPS tracks")

    # Ensure both are in the same projected CRS
    console.log("[bold]Step 2: Projecting data to local CRS...[/bold]")
    if network.crs != CONFIG.project_crs:
        network = network.to_crs(CONFIG.project_crs)
    if tracks.crs != CONFIG.project_crs:
        tracks = tracks.to_crs(CONFIG.project_crs)

    # Merge all tracks into a single geometry for efficient spatial operations
    console.log("[bold]Step 3: Preparing GPS track union...[/bold]")
    console.log("  This may take a few minutes with many tracks...")
    track_union = _build_track_coverage_geometry(tracks)

    if track_union is None or track_union.is_empty:
        console.log("[yellow]Track union is empty. All segments marked as uncovered.[/yellow]")
        network["covered"] = False
        network["coverage_pct"] = 0.0
        network["times_covered"] = 0
        _save_and_summarize(network)
        return network

    # Analyze each edge
    console.log(f"[bold]Step 4: Analyzing coverage for {len(network)} edges...[/bold]")
    coverage_results = _compute_edge_coverage(network, track_union)

    # Add results to network
    network["coverage_pct"] = coverage_results["coverage_pct"]
    network["covered"] = coverage_results["covered"]
    network["times_covered"] = coverage_results["times_covered"]

    # Save and summarize
    _save_and_summarize(network)

    return network


def _build_track_coverage_geometry(tracks: gpd.GeoDataFrame):
    """
    Builds a single buffered geometry representing all areas
    covered by GPS tracks. Each track is buffered by BUFFER_DISTANCE_M
    and then merged into one unified shape.
    """
    console.log(f"  Buffering {len(tracks)} tracks by {BUFFER_DISTANCE_M}m...")

    # Buffer each track individually
    buffered_tracks = []
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Buffering tracks...", total=len(tracks))

        for idx, row in tracks.iterrows():
            try:
                geom = row.geometry
                if geom is not None and not geom.is_empty and geom.is_valid:
                    buffered = geom.buffer(BUFFER_DISTANCE_M)
                    if buffered is not None and not buffered.is_empty:
                        buffered_tracks.append(buffered)
                else:
                    failed += 1
            except Exception:
                failed += 1

            progress.update(task, advance=1)

    if failed > 0:
        console.log(f"  [yellow]Failed to buffer {failed} tracks[/yellow]")

    if not buffered_tracks:
        return None

    console.log(f"  Merging {len(buffered_tracks)} buffered tracks into unified coverage area...")
    console.log("  (This is the slowest step — please be patient)")

    # Merge in batches for better performance
    track_union = _batch_union(buffered_tracks)

    console.log(f"  [green]✔[/green] Track coverage geometry built")

    return track_union


def _batch_union(geometries: list, batch_size: int = 500):
    """
    Performs unary_union in batches for better performance
    with large numbers of geometries.
    """
    if len(geometries) <= batch_size:
        return unary_union(geometries)

    # Process in batches
    results = []
    total_batches = (len(geometries) + batch_size - 1) // batch_size

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Merging batches...",
            total=total_batches
        )

        for i in range(0, len(geometries), batch_size):
            batch = geometries[i:i + batch_size]
            batch_union = unary_union(batch)
            results.append(batch_union)
            progress.update(task, advance=1)

    # Final merge of batch results
    console.log(f"  Final merge of {len(results)} batch results...")
    return unary_union(results)


def _compute_edge_coverage(network: gpd.GeoDataFrame,
                            track_union) -> pd.DataFrame:
    """
    Computes the coverage percentage for each edge in the network.
    An edge is covered if the fraction of its length that intersects
    the track buffer exceeds COVERAGE_THRESHOLD.
    """
    coverage_pcts = []
    covered_flags = []
    times_covered = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Analyzing edges...",
            total=len(network)
        )

        for idx, row in network.iterrows():
            edge_geom = row.geometry
            edge_length = row["length_m"]

            try:
                if edge_geom is None or edge_geom.is_empty or edge_length <= 0:
                    coverage_pcts.append(0.0)
                    covered_flags.append(False)
                    times_covered.append(0)
                    progress.update(task, advance=1)
                    continue

                # Find the intersection of this edge with the track coverage area
                intersection = edge_geom.intersection(track_union)

                if intersection.is_empty:
                    covered_length = 0.0
                else:
                    covered_length = intersection.length

                pct = round(min(covered_length / edge_length * 100, 100.0),1)
                is_covered = pct >= (COVERAGE_THRESHOLD * 100)

                coverage_pcts.append(round(pct, 4))
                covered_flags.append(is_covered)
                # Simple coverage count: 1 if covered, 0 if not
                # A more sophisticated version could count individual track intersections
                times_covered.append(1 if is_covered else 0)

            except Exception:
                coverage_pcts.append(0.0)
                covered_flags.append(False)
                times_covered.append(0)

            progress.update(task, advance=1)

    return pd.DataFrame({
        "coverage_pct": coverage_pcts,
        "covered": covered_flags,
        "times_covered": times_covered,
    })


def _save_and_summarize(network: gpd.GeoDataFrame):
    """Saves the coverage-annotated network and prints a summary."""
    # Save
    output_path = CONFIG.paths.processed_network
    network.to_file(str(output_path), driver="GPKG", index=False)
    console.log(f"[green]✔[/green] Coverage data saved to '{output_path}'")

    # Summary
    total_edges = len(network)
    total_km = network["length_m"].sum() / 1000

    if "covered" in network.columns:
        covered_mask = network["covered"]
        covered_edges = covered_mask.sum()
        covered_km = network.loc[covered_mask, "length_m"].sum() / 1000
        uncovered_edges = total_edges - covered_edges
        uncovered_km = total_km - covered_km
        pct_edges = (covered_edges / total_edges * 100) if total_edges > 0 else 0
        pct_km = (covered_km / total_km * 100) if total_km > 0 else 0
    else:
        covered_edges = 0
        covered_km = 0
        uncovered_edges = total_edges
        uncovered_km = total_km
        pct_edges = 0
        pct_km = 0

    console.log("")
    console.log("[bold cyan]═══ Coverage Summary ═══[/bold cyan]")
    console.log(f"  Total network:     {total_edges:,} edges  /  {total_km:.1f} km")
    console.log(f"  Covered:           {covered_edges:,} edges  /  {covered_km:.1f} km  ({pct_km:.1f}%)")
    console.log(f"  Uncovered:         {uncovered_edges:,} edges  /  {uncovered_km:.1f} km  ({100 - pct_km:.1f}%)")
    console.log(f"  Coverage by edges: {pct_edges:.1f}%")
    console.log(f"  Coverage by km:    {pct_km:.1f}%")

    # Breakdown by road type
    if "highway" in network.columns and "covered" in network.columns:
        console.log("")
        console.log("  [bold]Coverage by road type:[/bold]")

        def normalize_highway(val):
            if isinstance(val, list):
                return val[0]
            return str(val)

        network["_hw"] = network["highway"].apply(normalize_highway)

        type_summary = network.groupby("_hw").agg(
            total_km=("length_m", lambda x: x.sum() / 1000),
            covered_km=("length_m", lambda x: x[network.loc[x.index, "covered"]].sum() / 1000),
        ).sort_values("total_km", ascending=False)

        type_summary["pct"] = (
            type_summary["covered_km"] / type_summary["total_km"] * 100
        ).round(1)

        for hw_type, row in type_summary.head(10).iterrows():
            bar_len = int(row["pct"] / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            console.log(
                f"    {hw_type:<16} {bar} {row['pct']:5.1f}%  "
                f"({row['covered_km']:.1f}/{row['total_km']:.1f} km)"
            )

        network.drop(columns=["_hw"], inplace=True)
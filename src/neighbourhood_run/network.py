# src/neighbourhood_run/network.py
import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Point
from shapely.ops import transform as shapely_transform
from pyproj import Transformer
from rich.console import Console
import warnings
from .config import CONFIG

warnings.filterwarnings("ignore", category=UserWarning, module='osmnx')

console = Console()

# --- PHASE 1: OVERPASS DOWNLOAD FILTER ---
# This is applied at download time. It removes the obvious exclusions.
HIGHWAY_FILTER = (
    '["highway"]["area"!~"yes"]["access"!~"private"]'
    '["highway"!~"motorway|motorway_link|trunk|trunk_link|bus_guideway|raceway|corridor|construction|proposed"]'
    '["service"!~"parking_aisle|driveway"]'
)

# --- PHASE 3: SPATIAL EXCLUSION ZONES ---
# OSM tags that define areas where running is not appropriate.
# We download these as polygons and remove any network edges inside them.
EXCLUSION_ZONE_TAGS = {
    "landuse": ["cemetery", "military"],
    "amenity": ["school"],
}

# --- PHASE 2: POST-DOWNLOAD TAG FILTERS ---
# Highway types that require a sidewalk tag to be included.
SIDEWALK_REQUIRED_HIGHWAYS = {"primary", "primary_link", "secondary", "secondary_link"}

# Valid sidewalk tag values that indicate a sidewalk is present.
VALID_SIDEWALK_VALUES = {"yes", "both", "left", "right", "separate"}


def geocode_home() -> gpd.GeoDataFrame:
    """Geocodes home address or uses coordinates from config."""
    home_cfg = CONFIG.home
    home_path = CONFIG.paths.processed_home
    home_path.parent.mkdir(parents=True, exist_ok=True)

    geom = None
    if home_cfg.address:
        console.log(f"Geocoding home address: '{home_cfg.address}'...")
        try:
            lat, lon = ox.geocode(home_cfg.address)
            geom = Point(lon, lat)
        except Exception as e:
            console.log(f"[red]Failed to geocode address:[/red] {e}")
            raise
    elif home_cfg.latitude and home_cfg.longitude:
        console.log("Using home coordinates from config...")
        geom = Point(home_cfg.longitude, home_cfg.latitude)

    if geom is None:
        raise ValueError("Home address or coordinates must be provided in config.")

    data = {'id': ['home_location']}
    home_gdf = gpd.GeoDataFrame(data, geometry=[geom], crs="EPSG:4326")
    home_gdf.to_file(str(home_path), driver="GPKG", index=False)
    console.log(f"[green]✔[/green] Home location saved to '{home_path}'")
    return home_gdf


def _download_exclusion_zones(boundary_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Downloads polygons for areas where running is not appropriate
    (cemeteries, military areas, schools) from OSM.
    """
    console.log("Downloading exclusion zone polygons from OSM...")
    polygon_wgs84 = boundary_gdf.geometry.iloc[0]

    all_zones = []
    for tag_key, tag_values in EXCLUSION_ZONE_TAGS.items():
        for tag_value in tag_values:
            console.log(f"  Fetching {tag_key}={tag_value}...")
            try:
                tags = {tag_key: tag_value}
                zones = ox.features_from_polygon(polygon_wgs84, tags=tags)
                # Keep only polygon geometries (not points or lines)
                zones = zones[zones.geom_type.isin(["Polygon", "MultiPolygon"])]
                if not zones.empty:
                    zones["exclusion_reason"] = f"{tag_key}={tag_value}"
                    # Keep only geometry and reason columns to avoid schema conflicts
                    zones = zones[["geometry", "exclusion_reason"]].copy()
                    all_zones.append(zones)
                    console.log(f"    Found {len(zones)} polygon(s)")
                else:
                    console.log(f"    No polygons found")
            except Exception as e:
                console.log(f"    [yellow]Warning: Could not fetch {tag_key}={tag_value}: {e}[/yellow]")

    if all_zones:
        combined = pd.concat(all_zones, ignore_index=True)
        result = gpd.GeoDataFrame(combined, crs="EPSG:4326")
        console.log(f"  [green]✔[/green] Total exclusion zones: {len(result)}")
        return result
    else:
        console.log(f"  [yellow]No exclusion zones found[/yellow]")
        return gpd.GeoDataFrame(columns=["geometry", "exclusion_reason"])


def _apply_sidewalk_filter(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Phase 2: Marks primary/secondary roads without sidewalk tags as optional.
    They are kept in the network for connectivity but not required for coverage.
    """
    console.log("Applying sidewalk filter to major roads...")

    def normalize_highway(val):
        if isinstance(val, list):
            return val[0]
        return val

    edges["_highway_norm"] = edges["highway"].apply(normalize_highway)

    def normalize_sidewalk(val):
        if pd.isna(val):
            return ""
        if isinstance(val, list):
            return val[0]
        return str(val).lower().strip()

    if "sidewalk" in edges.columns:
        edges["_sidewalk_norm"] = edges["sidewalk"].apply(normalize_sidewalk)
    else:
        edges["_sidewalk_norm"] = ""

    is_major = edges["_highway_norm"].isin(SIDEWALK_REQUIRED_HIGHWAYS)
    has_sidewalk = edges["_sidewalk_norm"].isin(VALID_SIDEWALK_VALUES)

    no_sidewalk = is_major & ~has_sidewalk
    n_no_sidewalk = no_sidewalk.sum()

    console.log(f"  Major roads found: {is_major.sum()}")
    console.log(f"  Major roads WITH sidewalk: {(is_major & has_sidewalk).sum()}")
    console.log(f"  Major roads WITHOUT sidewalk (marked optional): {n_no_sidewalk}")

    # Initialize required column if it doesn't exist yet
    if "required" not in edges.columns:
        edges["required"] = True

    # Mark major roads without sidewalk as optional connectors
    edges.loc[no_sidewalk, "required"] = False

    # Clean up temporary columns
    result = edges.drop(columns=["_highway_norm", "_sidewalk_norm"], errors="ignore")

    return result


def _apply_spatial_exclusions(edges: gpd.GeoDataFrame,
                               exclusion_zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Phase 3: Removes network edges that fall inside exclusion zone polygons
    (cemeteries, military areas, schools).
    Uses midpoint containment to determine if an edge is inside a zone.
    """
    if exclusion_zones.empty:
        console.log("No exclusion zones to apply.")
        return edges

    console.log("Applying spatial exclusions...")

    # Project exclusion zones to match edges CRS
    zones_proj = exclusion_zones.to_crs(edges.crs)

    # Dissolve all exclusion zones into one combined geometry
    zones_proj["_dissolve"] = 1
    zones_dissolved = zones_proj.dissolve(by="_dissolve")
    combined_zone = zones_dissolved.geometry.iloc[0]

    # Calculate the midpoint of each edge
    midpoints = edges.geometry.interpolate(0.5, normalized=True)

    # Check which midpoints fall inside the combined exclusion zone
    excluded_mask = midpoints.within(combined_zone)
    n_excluded = excluded_mask.sum()

    console.log(f"  Edges inside exclusion zones: {n_excluded}")

    # Keep only edges whose midpoint is NOT inside an exclusion zone
    result = edges[~excluded_mask].copy()

    return result

def _apply_manual_exclusions(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Phase 4: Applies manual exclusions from the user's exclusions.gpkg file.
    Supports both line exclusions and polygon exclusions.
    """
    exclusion_path = CONFIG.paths.manual_exclusions

    if not exclusion_path.exists():
        console.log("No manual exclusions file found. Skipping.")
        return edges

    console.log("Applying manual exclusions...")

    try:
        # Try to load polygon exclusions
        try:
            excl_polygons = gpd.read_file(str(exclusion_path), layer="excluded_polygons")
            if not excl_polygons.empty:
                excl_polygons_proj = excl_polygons.to_crs(edges.crs)
                excl_polygons_proj["_dissolve"] = 1
                excl_dissolved = excl_polygons_proj.dissolve(by="_dissolve")

                midpoints = edges.copy()
                midpoints["_midpoint"] = midpoints.geometry.interpolate(0.5, normalized=True)
                midpoints = midpoints.set_geometry("_midpoint")

                joined = gpd.sjoin(midpoints, excl_dissolved, how="left", predicate="within")
                poly_excluded = joined["index_right"].notna()
                n_poly = poly_excluded.sum()
                console.log(f"  Edges excluded by polygons: {n_poly}")
                edges = edges[~poly_excluded].copy()
        except Exception:
            pass  # Layer doesn't exist, that's fine

        # Try to load edge ID exclusions
        try:
            excl_edges = gpd.read_file(str(exclusion_path), layer="excluded_edges")
            if not excl_edges.empty and "edge_id" in excl_edges.columns:
                excluded_ids = set(excl_edges["edge_id"].tolist())
                before = len(edges)
                edges = edges[~edges["edge_id"].isin(excluded_ids)].copy()
                n_edge = before - len(edges)
                console.log(f"  Edges excluded by ID: {n_edge}")
        except Exception:
            pass  # Layer doesn't exist, that's fine

    except Exception as e:
        console.log(f"  [yellow]Warning: Error processing manual exclusions: {e}[/yellow]")

    return edges


def _add_review_flags(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Adds a 'review_flag' column to edges that might need manual review.
    Only flags genuinely ambiguous cases that require human judgment.
    """
    console.log("Adding review flags...")
    flags = pd.Series([""] * len(edges), index=edges.index)

    # Flag 1: Ambiguous access tags
    if "access" in edges.columns:
        ambiguous_access = {"permissive", "destination", "customers"}

        def check_access(val):
            if pd.isna(val):
                return False
            if isinstance(val, list):
                return any(v in ambiguous_access for v in val)
            return str(val).lower().strip() in ambiguous_access

        mask = edges["access"].apply(check_access)
        flags[mask] = flags[mask].apply(
            lambda x: x + "Ambiguous access; " if x else "Ambiguous access; "
        )
        console.log(f"  Ambiguous access: {mask.sum()}")

    # Flag 2: Unnamed service roads longer than 50m
    def normalize_highway(val):
        if isinstance(val, list):
            return val[0]
        return str(val)

    hw_norm = edges["highway"].apply(normalize_highway)
    is_service = hw_norm == "service"
    is_unnamed = edges["name"].isna() | (edges["name"] == "")
    is_long = edges["length_m"] > 75

    suspicious_service = is_service & is_unnamed & is_long
    flags[suspicious_service] = flags[suspicious_service].apply(
        lambda x: x + "Unnamed service road; " if x else "Unnamed service road; "
    )
    console.log(f"  Unnamed service roads (>50m): {suspicious_service.sum()}")

    edges["review_flag"] = flags
    total_flagged = (flags != "").sum()
    console.log(f"  [green]✔[/green] Total flagged for review: {total_flagged}")

    return edges

def build_runnable_network(boundary_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Downloads, filters, and clips the OSM network to the boundary.
    Applies four phases of filtering:
      Phase 1: Overpass download filter (at download time)
      Phase 2: Sidewalk filter for major roads
      Phase 3: Spatial exclusion zones (cemeteries, schools, military)
      Phase 4: Manual exclusions from user file
    Also adds review flags for ambiguous segments.
    """
    output_path = CONFIG.paths.processed_network
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- PREPARE BOUNDARY ---
    console.log("[bold]Step 1: Preparing boundary...[/bold]")
    boundary_proj = boundary_gdf.to_crs(CONFIG.project_crs)

    # Create buffered version for download
    buffer_dist = CONFIG.area.buffer_meters
    console.log(f"Buffering boundary by {buffer_dist}m for complete road coverage...")
    buffered_geom = boundary_proj.geometry.iloc[0].buffer(buffer_dist)

    # Transform buffered polygon to WGS84 for OSMnx
    transformer = Transformer.from_crs(CONFIG.project_crs, "EPSG:4326", always_xy=True)
    buffered_wgs84 = shapely_transform(transformer.transform, buffered_geom)

    # --- PHASE 1: DOWNLOAD WITH BROAD FILTER ---
    console.log("[bold]Step 2: Downloading OSM network (Phase 1 filter)...[/bold]")
    G = ox.graph_from_polygon(
        buffered_wgs84,
        custom_filter=HIGHWAY_FILTER,
        retain_all=True,
        truncate_by_edge=False
    )

    console.log("Converting graph to GeoDataFrame...")
    edges = ox.graph_to_gdfs(G, nodes=False)

    if edges.empty:
        console.log("[yellow]Warning: No runnable ways found in the area.[/yellow]")
        return gpd.GeoDataFrame()

    console.log(f"  Downloaded {len(edges)} edges")

    # --- CLIP TO BOUNDARY ---
    console.log("[bold]Step 3: Clipping to boundary...[/bold]")
    edges_proj = edges.to_crs(CONFIG.project_crs)

    boundary_proj["_dissolve"] = 1
    clip_mask = boundary_proj.dissolve(by="_dissolve")
    clipped = gpd.clip(edges_proj, clip_mask)

    if clipped.empty:
        console.log("[yellow]Warning: No ways remaining after clipping.[/yellow]")
        return gpd.GeoDataFrame()

    # Explode and clean
    clipped = clipped.explode(index_parts=True).reset_index(drop=True)
    clipped['length_m'] = clipped.geometry.length
    clipped = clipped[clipped['length_m'] > 0.5].copy()
    clipped = clipped.reset_index(drop=True)

    console.log(f"  After clipping: {len(clipped)} edges, {clipped['length_m'].sum() / 1000:.1f} km")

    # --- PHASE 2: SIDEWALK FILTER ---
    console.log("[bold]Step 4: Applying sidewalk filter (Phase 2)...[/bold]")
    filtered = _apply_sidewalk_filter(clipped)
    required_after_sw = filtered["required"].sum() if "required" in filtered.columns else len(filtered)
    console.log(f"  After sidewalk filter: {len(filtered)} edges ({required_after_sw} required), {filtered['length_m'].sum() / 1000:.1f} km")
    # --- PHASE 2b: MARK OPTIONAL SEGMENTS ---
    console.log("[bold]Step 4b: Marking optional segments...[/bold]")
    def normalize_highway_2b(val):
        if isinstance(val, list):
            return val[0]
        return str(val)

    hw_norm_2b = filtered["highway"].apply(normalize_highway_2b)
    is_service_2b = hw_norm_2b == "service"
    is_unnamed_2b = filtered["name"].isna() | (filtered["name"] == "")
    is_short_service_2b = filtered["length_m"] <= 75

    # Mark all segments as required by default
    filtered["required"] = True

    # Rule 1: Short unnamed service roads are optional (connectors only)
    optional_service = is_service_2b & is_unnamed_2b & is_short_service_2b
    filtered.loc[optional_service, "required"] = False

    # Rule 2: Very short segments (< 10m) of any type are optional
    # These are typically clipping artifacts but must stay for connectivity
    very_short = filtered["length_m"] < 10.0
    filtered.loc[very_short, "required"] = False

    n_optional = (~filtered["required"]).sum()
    required_km = filtered.loc[filtered["required"], "length_m"].sum() / 1000
    optional_km = filtered.loc[~filtered["required"], "length_m"].sum() / 1000
    console.log(f"  Required segments: {filtered['required'].sum()} ({required_km:.1f} km)")
    console.log(f"  Optional segments (connectors): {n_optional} ({optional_km:.1f} km)")

    # --- PHASE 3: SPATIAL EXCLUSIONS ---
    console.log("[bold]Step 5: Applying spatial exclusions (Phase 3)...[/bold]")
    exclusion_zones = _download_exclusion_zones(boundary_gdf)
    filtered = _apply_spatial_exclusions(filtered, exclusion_zones)
    console.log(f"  After spatial exclusions: {len(filtered)} edges, {filtered['length_m'].sum() / 1000:.1f} km")

    # --- PHASE 4: MANUAL EXCLUSIONS ---
    console.log("[bold]Step 6: Applying manual exclusions (Phase 4)...[/bold]")
    # Assign edge IDs before manual exclusions so they can be referenced
    filtered['edge_id'] = range(len(filtered))
    filtered = _apply_manual_exclusions(filtered)
    console.log(f"  After manual exclusions: {len(filtered)} edges, {filtered['length_m'].sum() / 1000:.1f} km")

    # --- REVIEW FLAGS ---
    console.log("[bold]Step 7: Adding review flags...[/bold]")
    filtered = _add_review_flags(filtered)

    # --- FINAL CLEANUP AND SAVE ---
    console.log("[bold]Step 8: Saving final network...[/bold]")
    # Reassign edge IDs after all filtering
    filtered = filtered.reset_index(drop=True)
    filtered['edge_id'] = range(len(filtered))

    cols_to_keep = [
        'edge_id', 'osmid', 'highway', 'name', 'service',
        'sidewalk', 'access', 'oneway', 'length_m', 'required', 'review_flag', 'geometry'
    ]
    final_edges = filtered[[col for col in cols_to_keep if col in filtered.columns]]

    final_edges.to_file(str(output_path), driver="GPKG", index=False)

    total_km = final_edges['length_m'].sum() / 1000
    n_flagged = (final_edges.get('review_flag', '') != '').sum() if 'review_flag' in final_edges.columns else 0

    console.log(f"[green]✔[/green] Runnable network saved to '{output_path}'")
    console.log(f"[green]✔[/green] Total runnable distance: {total_km:.1f} km")
    console.log(f"[green]✔[/green] Total edges: {len(final_edges)}")
    console.log(f"[yellow]⚑[/yellow] Flagged for review: {n_flagged}")

    return final_edges
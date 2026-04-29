# src/neighbourhood_run/network.py
import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, LineString
from shapely.ops import transform as shapely_transform
from pyproj import Transformer
from rich.console import Console
import warnings
from .config import CONFIG
from .reviews import apply_segment_overrides

warnings.filterwarnings("ignore", category=UserWarning, module='osmnx')

console = Console()

# --- PHASE 1: OVERPASS DOWNLOAD FILTER ---
# This is applied at download time. It removes the obvious exclusions.
HIGHWAY_FILTER = (
    '["highway"]["area"!~"yes"]["access"!~"private"]'
    '["highway"!~"motorway|motorway_link|trunk|trunk_link|bus_guideway|raceway|corridor|construction|proposed|platform"]'
    '["service"!~"parking_aisle|driveway"]'
    '["foot"!~"no"]'
)

# --- PHASE 3: SPATIAL EXCLUSION ZONES ---
# OSM tags that define areas where running is not appropriate.
# We download these as polygons and remove any network edges inside them.
EXCLUSION_ZONE_TAGS = {
    "landuse": ["cemetery", "military"],
    "amenity": ["school"],
}

# Zones where only dead-end unnamed paths are excluded
# Through-paths and named roads are kept
SOFT_EXCLUSION_ZONE_TAGS = {
    "landuse": ["allotments"],
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

#    Mark major roads without sidewalk as optional connectors
    edges.loc[no_sidewalk, "required"] = False
    # Flag these so gap-bridging doesn't promote them back
    edges["_sidewalk_excluded"] = False
    edges.loc[no_sidewalk, "_sidewalk_excluded"] = True

    # Clean up temporary columns
    result = edges.drop(columns=["_highway_norm", "_sidewalk_norm"], errors="ignore")

    return result


def _apply_spatial_exclusions(edges: gpd.GeoDataFrame,
                               exclusion_zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Phase 3: Removes network edges inside exclusion zone polygons.
    
    Hard exclusions (cemeteries, military, schools):
        Removes all unnamed/internal paths inside the zone.
        Keeps named public roads.
    
    Soft exclusions (allotments):
        Only removes dead-end unnamed paths inside the zone.
        Keeps through-paths and named roads.
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
    inside_zone = midpoints.within(combined_zone)

    # Classify highway types
    def normalize_highway(val):
        if isinstance(val, list):
            return val[0]
        return str(val)

    hw_norm = edges["highway"].apply(normalize_highway)
    internal_types = {"footway", "path", "service", "track", "steps", "pedestrian"}
    is_internal_type = hw_norm.isin(internal_types)
    is_unnamed = edges["name"].isna() | (edges["name"] == "")

    # Only exclude: inside zone AND internal/unnamed type
    excluded_mask = inside_zone & (is_internal_type | is_unnamed)
    n_excluded = excluded_mask.sum()
    n_protected = (inside_zone & ~excluded_mask).sum()

    console.log(f"  Edges inside hard exclusion zones: {inside_zone.sum()}")
    console.log(f"  Excluded (internal/unnamed paths): {n_excluded}")
    console.log(f"  Protected (public named roads): {n_protected}")

    result = edges[~excluded_mask].copy()

    return result


def _download_and_apply_soft_exclusions(edges: gpd.GeoDataFrame,
                                         boundary_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Downloads soft exclusion zones (allotments) and removes only
    dead-end unnamed paths inside them. Through-paths are kept.
    """
    console.log("Applying soft exclusion zones (allotments)...")

    polygon_wgs84 = boundary_gdf.geometry.iloc[0]
    all_zones = []

    for tag_key, tag_values in SOFT_EXCLUSION_ZONE_TAGS.items():
        for tag_value in tag_values:
            console.log(f"  Fetching {tag_key}={tag_value}...")
            try:
                tags = {tag_key: tag_value}
                zones = ox.features_from_polygon(polygon_wgs84, tags=tags)
                zones = zones[zones.geom_type.isin(["Polygon", "MultiPolygon"])]
                if not zones.empty:
                    zones = zones[["geometry"]].copy()
                    all_zones.append(zones)
                    console.log(f"    Found {len(zones)} polygon(s)")
            except Exception as e:
                console.log(f"    [yellow]Warning: {e}[/yellow]")

    if not all_zones:
        console.log("  No soft exclusion zones found.")
        return edges

    combined = pd.concat(all_zones, ignore_index=True)
    zones_gdf = gpd.GeoDataFrame(combined, crs="EPSG:4326")
    zones_proj = zones_gdf.to_crs(edges.crs)

    # Dissolve into one geometry
    zones_proj["_dissolve"] = 1
    zones_dissolved = zones_proj.dissolve(by="_dissolve")
    soft_zone = zones_dissolved.geometry.iloc[0]

    # Find edges inside soft exclusion zones
    midpoints = edges.geometry.interpolate(0.5, normalized=True)
    inside_soft = midpoints.within(soft_zone)

    if not inside_soft.any():
        console.log("  No edges inside soft exclusion zones.")
        return edges

    # Build connectivity: count how many edges connect to each endpoint
    endpoint_count = {}
    for _, row in edges.iterrows():
        coords = list(row.geometry.coords)
        start = (round(coords[0][0], 1), round(coords[0][1], 1))
        end = (round(coords[-1][0], 1), round(coords[-1][1], 1))
        endpoint_count[start] = endpoint_count.get(start, 0) + 1
        endpoint_count[end] = endpoint_count.get(end, 0) + 1

    # A dead-end is where one endpoint has only 1 connection (the edge itself)
    def normalize_highway(val):
        if isinstance(val, list):
            return val[0]
        return str(val)

    hw_norm = edges["highway"].apply(normalize_highway)
    internal_types = {"footway", "path", "service", "track"}
    is_internal = hw_norm.isin(internal_types)
    is_unnamed = edges["name"].isna() | (edges["name"] == "")

    n_excluded = 0
    exclude_indices = []

    for idx in edges[inside_soft].index:
        row = edges.loc[idx]

        # Skip named roads — always keep
        if not is_unnamed.loc[idx]:
            continue

        # Skip non-internal road types — always keep
        if not is_internal.loc[idx]:
            continue

        # Check if this is a dead-end (one endpoint connects to only this edge)
        coords = list(row.geometry.coords)
        start = (round(coords[0][0], 1), round(coords[0][1], 1))
        end = (round(coords[-1][0], 1), round(coords[-1][1], 1))

        is_dead_end = endpoint_count.get(start, 0) <= 1 or endpoint_count.get(end, 0) <= 1

        if is_dead_end:
            exclude_indices.append(idx)
            n_excluded += 1

    n_through = inside_soft.sum() - n_excluded
    console.log(f"  Edges inside allotments: {inside_soft.sum()}")
    console.log(f"  Dead-end private paths (excluded): {n_excluded}")
    console.log(f"  Through-paths (kept): {n_through}")

    result = edges.drop(index=exclude_indices).copy()

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
    
    # Don't flag optional/buffer-zone segments — they don't need review
    if "required" in edges.columns:
        edges.loc[edges["required"] == False, "review_flag"] = ""
    
    total_flagged = (edges["review_flag"] != "").sum()
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

# --- CLIP AND MARK BOUNDARY ZONES ---
    console.log("[bold]Step 3: Processing boundary zones...[/bold]")
    edges_proj = edges.to_crs(CONFIG.project_crs)

    # Prepare the exact boundary for determining required/optional
    boundary_proj["_dissolve"] = 1
    clip_mask = boundary_proj.dissolve(by="_dissolve")
    exact_boundary_geom = clip_mask.geometry.iloc[0]

    # Prepare the buffered boundary for the outer limit
    buffered_boundary_geom = exact_boundary_geom.buffer(CONFIG.area.buffer_meters)

    # Clip to the BUFFERED boundary (keeps connector roads outside the exact boundary)
    buffered_mask = gpd.GeoDataFrame(
        geometry=[buffered_boundary_geom], crs=CONFIG.project_crs
    )
    clipped = gpd.clip(edges_proj, buffered_mask)

    if clipped.empty:
        console.log("[yellow]Warning: No ways remaining after clipping.[/yellow]")
        return gpd.GeoDataFrame()

    # Explode and clean
    clipped = clipped.explode(index_parts=True).reset_index(drop=True)
    clipped['length_m'] = clipped.geometry.length
    clipped = clipped[clipped['length_m'] > 0.5].copy()

    # Determine which edges are inside the exact boundary (required)
    # vs in the buffer zone (optional connectors)
    console.log("  Determining boundary zones...")
    midpoints = clipped.geometry.interpolate(0.5, normalized=True)
    inside_boundary = midpoints.within(exact_boundary_geom)
    clipped["_inside_boundary"] = inside_boundary

    n_inside = inside_boundary.sum()
    n_buffer = len(clipped) - n_inside
    console.log(f"  Inside boundary: {n_inside} edges")
    console.log(f"  Buffer zone (connectors): {n_buffer} edges")

    # Deduplicate: OSMnx creates two directed edges per road segment
    console.log("  Deduplicating directed edges...")
    before_dedup = len(clipped)
    clipped['_geom_wkt'] = clipped.geometry.apply(
        lambda g: g.wkt if g is not None else None
    )
    clipped['_geom_wkt_rev'] = clipped.geometry.apply(
        lambda g: LineString(g.coords[::-1]).wkt if g is not None else None
    )

    seen_geoms = set()
    keep_mask = []
    for _, row in clipped.iterrows():
        wkt = row['_geom_wkt']
        wkt_rev = row['_geom_wkt_rev']
        if wkt in seen_geoms or wkt_rev in seen_geoms:
            keep_mask.append(False)
        else:
            seen_geoms.add(wkt)
            keep_mask.append(True)

    clipped = clipped[keep_mask].copy()
    clipped = clipped.drop(columns=['_geom_wkt', '_geom_wkt_rev'])
    clipped = clipped.reset_index(drop=True)

    console.log(f"  Deduplicated: {before_dedup} → {len(clipped)} edges")

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

    # Combine boundary zone with sidewalk filter results.
    # A segment is required only if:
    #   - It's inside the boundary (or promoted as a named road), AND
    #   - It wasn't marked optional by the sidewalk filter
    if "_inside_boundary" in filtered.columns:
        # If sidewalk filter already set required=False, respect that
        if "required" in filtered.columns:
            filtered["required"] = filtered["required"] & filtered["_inside_boundary"]
        else:
            filtered["required"] = filtered["_inside_boundary"]
        filtered = filtered.drop(columns=["_inside_boundary"])
    else:
        if "required" not in filtered.columns:
            filtered["required"] = True

    # Rule 1: Short unnamed service roads are optional
    optional_service = is_service_2b & is_unnamed_2b & is_short_service_2b
    filtered.loc[optional_service, "required"] = False

    # Rule 2: Very short segments (< 10m) are optional UNLESS both their
    # endpoints connect to required segments (making them legitimate connectors)
    very_short_mask = filtered["length_m"] < 10.0
    
    if very_short_mask.any():
        # Collect all endpoints of required (non-short) segments into a set
        required_non_short = filtered[filtered["required"] & ~very_short_mask]
        endpoint_set = set()
        
        for _, row in required_non_short.iterrows():
            coords = list(row.geometry.coords)
            endpoint_set.add((round(coords[0][0], 1), round(coords[0][1], 1)))
            endpoint_set.add((round(coords[-1][0], 1), round(coords[-1][1], 1)))
        
        # For each short segment, check if both endpoints match
        n_kept = 0
        n_optional = 0
        for idx in filtered[very_short_mask].index:
            coords = list(filtered.loc[idx, "geometry"].coords)
            start = (round(coords[0][0], 1), round(coords[0][1], 1))
            end = (round(coords[-1][0], 1), round(coords[-1][1], 1))
            
            if start in endpoint_set and end in endpoint_set:
                n_kept += 1
                # Leave required = True (already set by default or boundary check)
            else:
                filtered.loc[idx, "required"] = False
                n_optional += 1
        
        console.log(f"  Short segments (<10m): {n_kept} are connectors (required), {n_optional} optional")
    else:
        console.log(f"  No short segments found")

    # Rule 3: Segments that bridge two required segments should be required
    # even if they would otherwise be optional (prevents gaps in routes).
    # EXCEPT: segments marked by sidewalk filter stay optional.
    console.log("  Checking for gap-bridging segments...")
    
    n_gaps_fixed = 0
    for pass_num in range(5):
        required_endpoints = set()
        for _, row in filtered[filtered["required"]].iterrows():
            coords = list(row.geometry.coords)
            required_endpoints.add((round(coords[0][0], 1), round(coords[0][1], 1)))
            required_endpoints.add((round(coords[-1][0], 1), round(coords[-1][1], 1)))

        rescued_this_pass = 0
        for idx in filtered[~filtered["required"]].index:
            # Never promote segments explicitly excluded by sidewalk filter
            if filtered.loc[idx].get("_sidewalk_excluded", False):
                continue

            coords = list(filtered.loc[idx, "geometry"].coords)
            start = (round(coords[0][0], 1), round(coords[0][1], 1))
            end = (round(coords[-1][0], 1), round(coords[-1][1], 1))

            if start in required_endpoints and end in required_endpoints:
                filtered.loc[idx, "required"] = True
                required_endpoints.add(start)
                required_endpoints.add(end)
                rescued_this_pass += 1

        n_gaps_fixed += rescued_this_pass
        if rescued_this_pass == 0:
            break

    console.log(f"  Gap-bridging segments promoted to required: {n_gaps_fixed}")

    # Rule 4 (FINAL): Named roads of runnable types are ALWAYS required
    # if they are inside the boundary. This overrides Rules 1-3 but NOT
    # the sidewalk filter (primary/secondary without sidewalks stay optional).
    console.log("  Applying final named-road override...")
    
    # Recalculate which segments are inside the boundary
    midpoints_final = filtered.geometry.interpolate(0.5, normalized=True)
    boundary_proj_final = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
    boundary_geom_final = boundary_proj_final.geometry.iloc[0]
    inside_final = midpoints_final.within(boundary_geom_final)
    
    is_named_final = (
        filtered["name"].notna() & 
        (filtered["name"] != "") & 
        (filtered["name"].astype(str) != "nan")
    )
    
    def normalize_hw_final(val):
        if isinstance(val, list):
            return val[0]
        return str(val)
    
    hw_final = filtered["highway"].apply(normalize_hw_final)
    
    promotable_types = {
        "residential", "living_street", "tertiary", "tertiary_link",
        "unclassified", "pedestrian", "footway", "path", "cycleway",
        "track", "bridleway", "steps"
    }
    is_promotable = hw_final.isin(promotable_types)
    
    # Don't override sidewalk filter
    if "_sidewalk_excluded" in filtered.columns:
        is_sidewalk_excluded = filtered["_sidewalk_excluded"].fillna(False)
    else:
        is_sidewalk_excluded = pd.Series(False, index=filtered.index)
        
    final_promote = is_named_final & is_promotable & inside_final & ~is_sidewalk_excluded & ~filtered["required"]
    n_final_promoted = final_promote.sum()
    
    # Debug: show what's being checked
    still_optional_named = is_named_final & is_promotable & inside_final & ~filtered["required"]
    console.log(f"  DEBUG: Named+promotable+inside+still_optional: {still_optional_named.sum()}")
    console.log(f"  DEBUG: Of those, sidewalk_excluded: {(still_optional_named & is_sidewalk_excluded).sum()}")
    console.log(f"  DEBUG: Final promote count: {n_final_promoted}")
    
    if n_final_promoted > 0:
        # Show which roads are being promoted
        promoted_names = filtered.loc[final_promote, "name"].value_counts()
        for name, count in promoted_names.head(10).items():
            console.log(f"    Promoting: {name} ({count} segments)")
    
    filtered.loc[final_promote, "required"] = True
    
    if n_final_promoted > 0:
        console.log(f"  Named roads final promotion: {n_final_promoted}")

    n_required = filtered["required"].sum()
    n_optional = len(filtered) - n_required
    required_km = filtered.loc[filtered["required"], "length_m"].sum() / 1000
    optional_km = filtered.loc[~filtered["required"], "length_m"].sum() / 1000
    console.log(f"  Final: Required {n_required} ({required_km:.1f} km), Optional {n_optional} ({optional_km:.1f} km)")
    
# --- PHASE 3: SPATIAL EXCLUSIONS ---
    console.log("[bold]Step 5: Applying spatial exclusions (Phase 3)...[/bold]")
    exclusion_zones = _download_exclusion_zones(boundary_gdf)
    filtered = _apply_spatial_exclusions(filtered, exclusion_zones)
    console.log(f"  After hard exclusions: {len(filtered)} edges, {filtered['length_m'].sum() / 1000:.1f} km")

    # --- PHASE 3b: SOFT EXCLUSIONS (allotments) ---
    console.log("[bold]Step 5b: Applying soft exclusions (allotments)...[/bold]")
    filtered = _download_and_apply_soft_exclusions(filtered, boundary_gdf)
    console.log(f"  After soft exclusions: {len(filtered)} edges, {filtered['length_m'].sum() / 1000:.1f} km")

    # --- PHASE 4: MANUAL EXCLUSIONS ---
    console.log("[bold]Step 6: Applying manual exclusions (Phase 4)...[/bold]")
    # Assign edge IDs before manual exclusions so they can be referenced
    filtered['edge_id'] = range(len(filtered))
    filtered = _apply_manual_exclusions(filtered)
    console.log(f"  After manual exclusions: {len(filtered)} edges, {filtered['length_m'].sum() / 1000:.1f} km")

    # --- PHASE 5: LOCAL SEGMENT OVERRIDES ---
    console.log("[bold]Step 6b: Applying local segment overrides...[/bold]")
    from .reviews import load_segment_overrides
    overrides = load_segment_overrides()
    if overrides:
        # Validate that override edge IDs exist in current network
        current_ids = set(filtered["edge_id"].tolist())
        valid_overrides = [o for o in overrides if o["edge_id"] in current_ids]
        stale_overrides = [o for o in overrides if o["edge_id"] not in current_ids]
        
        if stale_overrides:
            console.log(f"  [yellow]Warning: {len(stale_overrides)} overrides reference old edge IDs (cleared)[/yellow]")
            # Save only valid overrides back
            from .reviews import save_segment_overrides
            save_segment_overrides(valid_overrides)
        
        if valid_overrides:
            filtered = apply_segment_overrides(filtered)
        else:
            console.log("  No valid overrides to apply.")
    else:
        console.log("  No segment overrides found.")
    console.log(f"  After overrides: {len(filtered)} edges, {filtered['length_m'].sum() / 1000:.1f} km")

    # --- REVIEW FLAGS ---
    console.log("[bold]Step 7: Adding review flags...[/bold]")
    filtered = _add_review_flags(filtered)

    # --- FINAL CLEANUP AND SAVE ---
    console.log("[bold]Step 8: Connectivity analysis and saving...[/bold]")
    # Reassign edge IDs after all filtering
    filtered = filtered.reset_index(drop=True)
    filtered['edge_id'] = range(len(filtered))

    # FINAL SAFETY NET: Named runnable roads INSIDE the boundary must be required.
    # Uses a small buffer (25m) to catch roads running along the boundary edge.
    # Does NOT promote roads genuinely in the buffer zone (other postal codes).
    boundary_check = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
    boundary_check_geom = boundary_check.geometry.iloc[0]
    boundary_buffered_25m = boundary_check_geom.buffer(25)
    
    midpoints_check = filtered.geometry.interpolate(0.5, normalized=True)
    inside_check = midpoints_check.within(boundary_buffered_25m)
    
    is_named_final = (
        filtered["name"].notna() & 
        (filtered["name"] != "") & 
        (filtered["name"].astype(str) != "nan")
    )
    
    def norm_hw_final(val):
        return val[0] if isinstance(val, list) else str(val)
    
    hw_final = filtered["highway"].apply(norm_hw_final)
    
    safe_types = {
        "residential", "living_street", "tertiary", "tertiary_link",
        "unclassified", "pedestrian", "footway", "path", "cycleway",
        "track", "bridleway", "steps"
    }
    is_safe_type = hw_final.isin(safe_types)
    
    if "_sidewalk_excluded" in filtered.columns:
        is_sw_excluded = filtered["_sidewalk_excluded"].fillna(False)
    else:
        is_sw_excluded = pd.Series(False, index=filtered.index)
    
    safety_promote = is_named_final & is_safe_type & inside_check & ~is_sw_excluded & ~filtered["required"]
    n_safety = safety_promote.sum()
    if n_safety > 0:
        filtered.loc[safety_promote, "required"] = True
        console.log(f"  [yellow]Safety net: promoted {n_safety} named roads to required[/yellow]")

    # Determine reachability from home
    import networkx as nx
    from shapely.geometry import Point as ShapelyPoint

    home_gdf = gpd.read_file(str(CONFIG.paths.processed_home))
    home_proj = home_gdf.to_crs(CONFIG.project_crs)
    home_point = home_proj.geometry.iloc[0]

    # Build a connectivity graph
    SNAP_TOLERANCE = 0.5
    node_map_local = {}
    node_id_local = 0

    def get_or_create_node_local(x, y):
        nonlocal node_id_local
        for (nx_, ny_), nid in node_map_local.items():
            if ((nx_ - x)**2 + (ny_ - y)**2)**0.5 < SNAP_TOLERANCE:
                return nid
        node_map_local[(x, y)] = node_id_local
        node_id_local += 1
        return node_id_local - 1

    G_conn = nx.Graph()
    node_coords_local = {}
    edge_nodes_local = {}

    filtered_proj = filtered.to_crs(CONFIG.project_crs) if filtered.crs != CONFIG.project_crs else filtered

    for _, row in filtered_proj.iterrows():
        coords = list(row.geometry.coords)
        sn = get_or_create_node_local(coords[0][0], coords[0][1])
        en = get_or_create_node_local(coords[-1][0], coords[-1][1])
        node_coords_local[sn] = coords[0]
        node_coords_local[en] = coords[-1]
        G_conn.add_edge(sn, en, edge_id=row["edge_id"])
        edge_nodes_local[row["edge_id"]] = (sn, en)

    # Find home node
    min_dist = float('inf')
    home_node_local = None
    for nid, (nx_, ny_) in node_coords_local.items():
        dist = ((nx_ - home_point.x)**2 + (ny_ - home_point.y)**2)**0.5
        if dist < min_dist:
            min_dist = dist
            home_node_local = nid

    # Find home component
    home_comp_nodes = set()
    if home_node_local is not None:
        home_comp_nodes = nx.node_connected_component(G_conn, home_node_local)

    # Mark each edge as reachable or not
    def is_reachable(edge_id):
        if edge_id in edge_nodes_local:
            sn, en = edge_nodes_local[edge_id]
            return sn in home_comp_nodes or en in home_comp_nodes
        return False

    filtered["reachable"] = filtered["edge_id"].apply(is_reachable)
    n_reachable = filtered["reachable"].sum()
    n_unreachable = len(filtered) - n_reachable
    reach_km = filtered.loc[filtered["reachable"], "length_m"].sum() / 1000
    unreach_km = filtered.loc[~filtered["reachable"], "length_m"].sum() / 1000

    console.log(f"  Reachable from home: {n_reachable} edges, {reach_km:.1f} km")
    console.log(f"  Unreachable islands: {n_unreachable} edges, {unreach_km:.1f} km")

    # Clean up temporary columns
    filtered = filtered.drop(columns=["_sidewalk_excluded"], errors="ignore")

    cols_to_keep = [
        'edge_id', 'osmid', 'highway', 'name', 'service',
        'sidewalk', 'access', 'oneway', 'length_m', 'required',
        'reachable', 'review_flag', 'geometry'
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
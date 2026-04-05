# src/neighbourhood_run/network.py
import geopandas as gpd
import osmnx as ox
from shapely.geometry import Point
from shapely.ops import transform as shapely_transform
from pyproj import Transformer
from rich.console import Console
import warnings
from .config import CONFIG

# Suppress noisy UserWarnings from OSMnx
warnings.filterwarnings("ignore", category=UserWarning, module='osmnx')

console = Console()

# --- FILTERING RULES ---
HIGHWAY_FILTER = (
    '["highway"]["area"!~"yes"]["access"!~"private"]'
    '["highway"!~"motorway|motorway_link|trunk|trunk_link|bus_guideway|raceway|corridor|construction|proposed"]'
    '["service"!~"parking_aisle"]'
)

def geocode_home() -> gpd.GeoDataFrame:
    """Geocodes home address or uses coordinates from config."""
    home_cfg = CONFIG.home
    home_path = CONFIG.paths.processed_home
    home_path.parent.mkdir(parents=True, exist_ok=True)
    
    geom = None
    if home_cfg.address:
        console.log(f"Geocoding home address: '{home_cfg.address}'...")
        try:
            # Use ox.geocode to get a (lat, lon) point for the address
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
        
    # Create the GeoDataFrame manually
    data = {'id': ['home_location']}
    home_gdf = gpd.GeoDataFrame(data, geometry=[geom], crs="EPSG:4326")


    
    home_gdf.to_file(
        str(home_path), 
        driver="GPKG", index=False)
    console.log(f"[green]✔[/green] Home location saved to '{home_path}'")
    return home_gdf


def build_runnable_network(boundary_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Downloads, filters, and clips the OSM network to the boundary.
    Uses a buffer for downloading to ensure roads at the boundary edge
    are fully captured, then clips precisely to the real boundary.
    """
    output_path = CONFIG.paths.processed_network
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Project boundary to local CRS for accurate buffering
    console.log("Preparing boundary...")
    boundary_proj = boundary_gdf.to_crs(CONFIG.project_crs)

    # 2. Create a buffered version for data download
    buffer_dist = CONFIG.area.buffer_meters
    console.log(f"Buffering boundary by {buffer_dist}m for complete road coverage...")
    buffered_geom = boundary_proj.geometry.iloc[0].buffer(buffer_dist)

    # 3. Transform the buffered geometry back to WGS84 for OSMnx
    transformer = Transformer.from_crs(CONFIG.project_crs, "EPSG:4326", always_xy=True)
    buffered_wgs84 = shapely_transform(transformer.transform, buffered_geom)

    # 4. Download network for the buffered area
    console.log("Downloading OSM data for the buffered area...")
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

    # 5. Project downloaded edges to local CRS
    console.log("Projecting to local CRS...")
    edges_proj = edges.to_crs(CONFIG.project_crs)

    # 6. Clip precisely to the ORIGINAL (un-buffered) boundary
    console.log("Clipping network to the precise boundary...")
    # Prepare the clip mask as a proper GeoDataFrame
    boundary_proj["_dissolve"] = 1
    clip_mask = boundary_proj.dissolve(by="_dissolve")
    clipped_edges = gpd.clip(edges_proj, clip_mask)

    # 7. Clean up the result
    console.log("Cleaning and processing final network...")

    if clipped_edges.empty:
        console.log("[yellow]Warning: No ways remaining after clipping.[/yellow]")
        return gpd.GeoDataFrame()

    final_edges = clipped_edges.explode(index_parts=True).reset_index(drop=True)
    final_edges['length_m'] = final_edges.geometry.length
    final_edges = final_edges[final_edges['length_m'] > 1.0].copy()
    final_edges = final_edges.reset_index(drop=True)
    final_edges['edge_id'] = range(len(final_edges))

    cols_to_keep = [
        'edge_id', 'osmid', 'highway', 'name', 'service',
        'oneway', 'length_m', 'geometry'
    ]
    final_edges = final_edges[[col for col in cols_to_keep if col in final_edges.columns]]

    final_edges.to_file(str(output_path), driver="GPKG", index=False)

    total_km = final_edges['length_m'].sum() / 1000
    console.log(f"[green]✔[/green] Runnable network saved to '{output_path}'")
    console.log(f"[green]✔[/green] Total runnable distance: {total_km:.1f} km")

    return final_edges
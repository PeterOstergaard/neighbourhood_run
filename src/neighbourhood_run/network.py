# src/neighbourhood_run/network.py
import geopandas as gpd
import osmnx as ox
from shapely.geometry import Point
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
    Downloads, filters, and clips the OSM network to the boundary using an
    explicit, manual clipping process for maximum reliability.
    """
    output_path = CONFIG.paths.processed_network
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Prepare the boundary polygon for clipping later
    console.log("Preparing boundary for clipping...")
    boundary_proj = boundary_gdf.to_crs(CONFIG.project_crs)
    # Dissolve into a single-row GeoDataFrame that will be our mask
    boundary_dissolved_gdf = boundary_proj.dissolve(by=boundary_proj.index.to_series().map(lambda x: 1))

    # 2. Get the graph for a slightly larger area (the bounding box)
    polygon_wgs84 = boundary_gdf.unary_union
    console.log("Downloading data for the area's bounding box...")
    G = ox.graph_from_polygon(
        polygon_wgs84,
        custom_filter=HIGHWAY_FILTER,
        retain_all=True,
        truncate_by_edge=False # Set to False, we will do our own clipping
    )
    
    console.log("Converting graph to GeoDataFrame...")
    edges = ox.graph_to_gdfs(G, nodes=False)
    
    if edges.empty:
        console.log("[yellow]Warning: No runnable ways found in the area.[/yellow]")
        return gpd.GeoDataFrame()

    # 3. Perform a precise, manual clip
    console.log("Projecting downloaded network to local CRS...")
    edges_proj = edges.to_crs(CONFIG.project_crs)

    console.log("Performing precise clip to the boundary shape...")
    # Use the entire dissolved GeoDataFrame as the mask for clipping
    clipped_edges = gpd.clip(edges_proj, boundary_dissolved_gdf)
    
    # --- The rest of the function cleans up the clipped result ---
    console.log("Cleaning and processing final clipped network...")
    
    if clipped_edges.empty:
        console.log("[yellow]Warning: No ways remaining after clipping.[/yellow]")
        return gpd.GeoDataFrame()
        
    final_edges = clipped_edges.explode(index_parts=True).reset_index(drop=True)
    final_edges['length_m'] = final_edges.geometry.length
    final_edges = final_edges[final_edges['length_m'] > 1.0].copy()
    final_edges['edge_id'] = range(len(final_edges))
    
    cols_to_keep = ['edge_id', 'osmid', 'highway', 'name', 'service', 'oneway', 'length_m', 'geometry']
    final_edges = final_edges[[col for col in cols_to_keep if col in final_edges.columns]]
    
    final_edges.to_file(str(output_path), driver="GPKG", index=False)
    console.log(f"[green]✔[/green] Runnable network saved to '{output_path}'")
    
    return final_edges
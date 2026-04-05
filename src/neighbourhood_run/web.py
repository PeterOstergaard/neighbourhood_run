# src/neighbourhood_run/web.py
import folium
import geopandas as gpd
from rich.console import Console
from .config import CONFIG

console = Console()

def create_network_map() -> folium.Map:
    """Creates a Folium map visualizing the boundary, home, and network."""
    try:
        boundary_gdf = gpd.read_file(CONFIG.paths.raw_boundary)
        home_gdf = gpd.read_file(CONFIG.paths.processed_home)
        network_gdf = gpd.read_file(CONFIG.paths.processed_network)
    except Exception as e:
        console.log(f"[red]Error loading data for map:[/red] {e}")
        console.log("Please run the network build process first.")
        return folium.Map(location=[56.15, 10.16], zoom_start=13) # Default map

    # Project to WGS84 for Folium
    boundary_web = boundary_gdf.to_crs("EPSG:4326")
    home_web = home_gdf.to_crs("EPSG:4326")
    network_web = network_gdf.to_crs(CONFIG.project_crs).to_crs("EPSG:4326")
    
    # Create map centered on the area
    centroid = boundary_web.geometry.unary_union.centroid
    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=14, tiles="cartodbpositron")
    
    # Add boundary
    folium.GeoJson(
        boundary_web,
        style_function=lambda x: {'color': 'black', 'weight': 2, 'fillOpacity': 0.1},
        name='Postal Code Boundary'
    ).add_to(m)

    # Add network
    folium.GeoJson(
        network_web,
        style_function=lambda x: {'color': 'blue', 'weight': 3},
        name='Runnable Network'
    ).add_to(m)
    
    # Add home
    home_point = [home_web.geometry.iloc[0].y, home_web.geometry.iloc[0].x]
    folium.Marker(
        location=home_point,
        popup='Home',
        icon=folium.Icon(color='green', icon='home')
    ).add_to(m)
    
    folium.LayerControl().add_to(m)
    
    map_path = CONFIG.paths.map_view_html
    map_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(map_path))
    console.log(f"[green]✔[/green] Interactive map saved to '{map_path}'")
    
    return m
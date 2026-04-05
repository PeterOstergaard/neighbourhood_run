# src/neighbourhood_run/web.py
import folium
import geopandas as gpd
from rich.console import Console
from .config import CONFIG

console = Console()

def create_network_map() -> folium.Map:
    """Creates a Folium map visualizing the boundary, home, network, and review flags."""
    try:
        boundary_gdf = gpd.read_file(str(CONFIG.paths.raw_boundary))
        home_gdf = gpd.read_file(str(CONFIG.paths.processed_home))
        network_gdf = gpd.read_file(str(CONFIG.paths.processed_network))
    except Exception as e:
        console.log(f"[red]Error loading data for map:[/red] {e}")
        return folium.Map(location=[56.15, 10.16], zoom_start=13)

    # Project to WGS84 for Folium
    boundary_web = boundary_gdf.to_crs("EPSG:4326")
    home_web = home_gdf.to_crs("EPSG:4326")
    network_web = network_gdf.to_crs("EPSG:4326")

    # Create map centered on the area
    centroid = boundary_web.geometry.iloc[0].centroid
    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=14, tiles="cartodbpositron")

    # Add boundary
    folium.GeoJson(
        boundary_web,
        style_function=lambda x: {'color': 'black', 'weight': 2, 'fillOpacity': 0.05},
        name='Postal Code Boundary'
    ).add_to(m)

    # Split network into regular and review-flagged segments
    has_review = "review_flag" in network_web.columns

    if has_review:
        flagged = network_web[network_web["review_flag"].fillna("").str.len() > 0]
        normal = network_web[network_web["review_flag"].fillna("").str.len() == 0]
    else:
        flagged = gpd.GeoDataFrame()
        normal = network_web

    # Add normal network (blue)
    if not normal.empty:
        folium.GeoJson(
            normal,
            style_function=lambda x: {'color': 'blue', 'weight': 2, 'opacity': 0.7},
            tooltip=folium.GeoJsonTooltip(
                fields=[f for f in ['name', 'highway', 'length_m'] if f in normal.columns],
                aliases=[f for f in ['Name', 'Type', 'Length (m)'] if True],
                sticky=True
            ),
            name='Runnable Network'
        ).add_to(m)

    # Add flagged network (orange)
    if not flagged.empty:
        folium.GeoJson(
            flagged,
            style_function=lambda x: {'color': 'orange', 'weight': 3, 'opacity': 0.9},
            tooltip=folium.GeoJsonTooltip(
                fields=[f for f in ['name', 'highway', 'review_flag'] if f in flagged.columns],
                aliases=[f for f in ['Name', 'Type', 'Review Reason'] if True],
                sticky=True
            ),
            name='Flagged for Review'
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
# src/neighbourhood_run/web.py
import folium
import geopandas as gpd
from rich.console import Console
from .config import CONFIG

console = Console()


def create_network_map() -> folium.Map:
    """Creates a Folium map with boundary, network, tracks, and review flags."""
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

    # Center map
    centroid = boundary_web.geometry.iloc[0].centroid
    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=14,
        tiles="cartodbpositron"
    )

    # --- Boundary layer ---
    folium.GeoJson(
        boundary_web,
        style_function=lambda x: {
            'color': 'black', 'weight': 2, 'fillOpacity': 0.05
        },
        name='Postal Code Boundary'
    ).add_to(m)

    # --- Network layers ---
    has_review = "review_flag" in network_web.columns

    if has_review:
        flagged = network_web[network_web["review_flag"].fillna("").str.len() > 0]
        normal = network_web[network_web["review_flag"].fillna("").str.len() == 0]
    else:
        flagged = gpd.GeoDataFrame()
        normal = network_web

    # Normal network (blue)
    if not normal.empty:
        tooltip_fields = [f for f in ['name', 'highway', 'length_m'] if f in normal.columns]
        tooltip_aliases = ['Name', 'Type', 'Length (m)'][:len(tooltip_fields)]
        folium.GeoJson(
            normal,
            style_function=lambda x: {
                'color': 'blue', 'weight': 2, 'opacity': 0.7
            },
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=tooltip_aliases,
                sticky=True
            ),
            name='Runnable Network'
        ).add_to(m)

    # Flagged network (orange)
    if not flagged.empty:
        tooltip_fields = [f for f in ['name', 'highway', 'review_flag'] if f in flagged.columns]
        tooltip_aliases = ['Name', 'Type', 'Review Reason'][:len(tooltip_fields)]
        folium.GeoJson(
            flagged,
            style_function=lambda x: {
                'color': 'orange', 'weight': 3, 'opacity': 0.9
            },
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=tooltip_aliases,
                sticky=True
            ),
            name='Flagged for Review'
        ).add_to(m)

    # --- GPS Tracks layer ---
    tracks_path = CONFIG.paths.processed_tracks
    if tracks_path.exists():
        try:
            tracks_gdf = gpd.read_file(str(tracks_path))
            if not tracks_gdf.empty:
                tracks_web = tracks_gdf.to_crs("EPSG:4326")
                tooltip_fields = [f for f in ['activity_id', 'start_time', 'length_m']
                                  if f in tracks_web.columns]
                tooltip_aliases = ['Activity ID', 'Date', 'Length (m)'][:len(tooltip_fields)]
                folium.GeoJson(
                    tracks_web,
                    style_function=lambda x: {
                        'color': 'red', 'weight': 2, 'opacity': 0.5
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=tooltip_fields,
                        aliases=tooltip_aliases,
                        sticky=True
                    ),
                    name='GPS Tracks'
                ).add_to(m)
                console.log(f"  Added {len(tracks_web)} GPS tracks to map")
        except Exception as e:
            console.log(f"  [yellow]Could not load tracks: {e}[/yellow]")

    # --- Home marker ---
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
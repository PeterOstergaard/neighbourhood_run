# src/neighbourhood_run/web.py
"""
Web visualization using Folium maps.
Uses color-blind friendly palette:
  - Blue (#2166ac): covered segments
  - Amber/Orange (#d6792b): uncovered segments
  - Purple (#7a3a9a): flagged for review
"""
import folium
import geopandas as gpd
from rich.console import Console
from .config import CONFIG

console = Console()

# Color-blind friendly palette
COLOR_COVERED = "#2166ac"      # Blue
COLOR_UNCOVERED = "#d6792b"    # Amber/Orange
COLOR_FLAGGED = "#7a3a9a"      # Purple
COLOR_BOUNDARY = "#333333"     # Dark grey


def create_network_map() -> folium.Map:
    """Creates a Folium map with coverage visualization."""
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
            'color': COLOR_BOUNDARY, 'weight': 2, 'fillOpacity': 0.03
        },
        name='Boundary'
    ).add_to(m)

    # --- Determine if we have coverage data ---
    has_coverage = "covered" in network_web.columns
    has_review = "review_flag" in network_web.columns

    if has_coverage:
        # Split into covered, uncovered, and flagged
        covered = network_web[network_web["covered"] == True].copy()
        uncovered = network_web[network_web["covered"] == False].copy()

        if has_review:
            flagged = uncovered[uncovered["review_flag"].fillna("").str.len() > 0].copy()
            uncovered_clean = uncovered[uncovered["review_flag"].fillna("").str.len() == 0].copy()
        else:
            flagged = gpd.GeoDataFrame()
            uncovered_clean = uncovered

        # Uncovered segments (amber/orange)
        if not uncovered_clean.empty:
            tooltip_fields = [f for f in ['name', 'highway', 'length_m', 'coverage_pct']
                              if f in uncovered_clean.columns]
            tooltip_aliases = ['Name', 'Type', 'Length (m)', 'Coverage %'][:len(tooltip_fields)]

            fg_uncovered = folium.FeatureGroup(name=f'Uncovered ({len(uncovered_clean)})')
            # Invisible wide stroke for easier hovering
            folium.GeoJson(
                uncovered_clean,
                style_function=lambda x: {
                    'color': COLOR_UNCOVERED, 'weight': 15, 'opacity': 0.0
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_aliases,
                    sticky=True
                ),
            ).add_to(fg_uncovered)
            # Visible thin stroke on top
            folium.GeoJson(
                uncovered_clean,
                style_function=lambda x: {
                    'color': COLOR_UNCOVERED, 'weight': 3, 'opacity': 0.8
                },
            ).add_to(fg_uncovered)
            fg_uncovered.add_to(m)

        # Flagged segments (purple)
        if not flagged.empty:
            tooltip_fields = [f for f in ['name', 'highway', 'review_flag']
                              if f in flagged.columns]
            tooltip_aliases = ['Name', 'Type', 'Review Reason'][:len(tooltip_fields)]

            fg_flagged = folium.FeatureGroup(name=f'Flagged for Review ({len(flagged)})')
            folium.GeoJson(
                flagged,
                style_function=lambda x: {
                    'color': COLOR_FLAGGED, 'weight': 15, 'opacity': 0.0
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_aliases,
                    sticky=True
                ),
            ).add_to(fg_flagged)
            folium.GeoJson(
                flagged,
                style_function=lambda x: {
                    'color': COLOR_FLAGGED, 'weight': 3, 'opacity': 0.9
                },
            ).add_to(fg_flagged)
            fg_flagged.add_to(m)

        # Covered segments (blue)
        if not covered.empty:
            tooltip_fields = [f for f in ['name', 'highway', 'length_m', 'coverage_pct']
                              if f in covered.columns]
            tooltip_aliases = ['Name', 'Type', 'Length (m)', 'Coverage %'][:len(tooltip_fields)]

            fg_covered = folium.FeatureGroup(name=f'Covered ({len(covered)})')
            folium.GeoJson(
                covered,
                style_function=lambda x: {
                    'color': COLOR_COVERED, 'weight': 15, 'opacity': 0.0
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_aliases,
                    sticky=True
                ),
            ).add_to(fg_covered)
            folium.GeoJson(
                covered,
                style_function=lambda x: {
                    'color': COLOR_COVERED, 'weight': 2, 'opacity': 0.6
                },
            ).add_to(fg_covered)
            fg_covered.add_to(m)

        # Coverage summary box
        covered_km = covered["length_m"].sum() / 1000 if not covered.empty else 0
        total_km = network_web["length_m"].sum() / 1000
        pct = (covered_km / total_km * 100) if total_km > 0 else 0

        summary_html = f"""
        <div style="
            position: fixed;
            bottom: 30px;
            left: 30px;
            z-index: 1000;
            background: white;
            padding: 15px 20px;
            border-radius: 8px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            font-family: Arial, sans-serif;
            font-size: 14px;
            line-height: 1.6;
        ">
            <b>Coverage Summary</b><br>
            <span style="color:{COLOR_COVERED}">■</span> Covered: {covered_km:.1f} km ({pct:.1f}%)<br>
            <span style="color:{COLOR_UNCOVERED}">■</span> Uncovered: {total_km - covered_km:.1f} km ({100 - pct:.1f}%)<br>
            <span style="color:{COLOR_FLAGGED}">■</span> Flagged: {len(flagged) if not flagged.empty else 0} segments
        </div>
        """
        m.get_root().html.add_child(folium.Element(summary_html))

    else:
        # No coverage data yet — show all segments in a neutral color
        if has_review:
            flagged = network_web[network_web["review_flag"].fillna("").str.len() > 0]
            normal = network_web[network_web["review_flag"].fillna("").str.len() == 0]
        else:
            flagged = gpd.GeoDataFrame()
            normal = network_web

        if not normal.empty:
            tooltip_fields = [f for f in ['name', 'highway', 'length_m']
                              if f in normal.columns]
            tooltip_aliases = ['Name', 'Type', 'Length (m)'][:len(tooltip_fields)]
            folium.GeoJson(
                normal,
                style_function=lambda x: {
                    'color': COLOR_COVERED, 'weight': 2, 'opacity': 0.7
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_aliases,
                    sticky=True
                ),
                name='Runnable Network'
            ).add_to(m)

        if not flagged.empty:
            tooltip_fields = [f for f in ['name', 'highway', 'review_flag']
                              if f in flagged.columns]
            tooltip_aliases = ['Name', 'Type', 'Review Reason'][:len(tooltip_fields)]
            folium.GeoJson(
                flagged,
                style_function=lambda x: {
                    'color': COLOR_FLAGGED, 'weight': 3, 'opacity': 0.9
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_aliases,
                    sticky=True
                ),
                name='Flagged for Review'
            ).add_to(m)

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
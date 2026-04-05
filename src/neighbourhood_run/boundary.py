# src/neighbourhood_run/boundary.py
import geopandas as gpd
import requests
import osmnx as ox
from rich.console import Console
from .config import CONFIG

ox.settings.timeout = 360
ox.settings.use_cache = True
ox.settings.log_console = False

console = Console()

# Registry of supported country boundary providers
BOUNDARY_PROVIDERS = {
    "DK": "_fetch_boundary_dawa",
}


def get_area_boundary() -> gpd.GeoDataFrame:
    """
    Fetches the postal code boundary using the appropriate provider
    for the configured country. Falls back to OSM/Nominatim if no
    specific provider is available.
    """
    country = CONFIG.area.country.upper()
    postalcode = CONFIG.area.postalcode
    output_path = CONFIG.paths.raw_boundary
    output_path.parent.mkdir(parents=True, exist_ok=True)

    console.log(f"Fetching boundary for postal code '{postalcode}' in country '{country}'...")

    # Look up the provider for this country
    provider_name = BOUNDARY_PROVIDERS.get(country)

    if provider_name:
        # Use the country-specific provider
        provider_func = globals()[provider_name]
        boundary_gdf = provider_func(postalcode)
    else:
        # Fall back to OSM/Nominatim for unsupported countries
        console.log(f"[yellow]No specific provider for '{country}'. Falling back to OSM/Nominatim.[/yellow]")
        boundary_gdf = _fetch_boundary_osm(postalcode, country)

    if boundary_gdf.empty:
        console.log("[red]Failed to fetch boundary.[/red]")
        return gpd.GeoDataFrame()

    boundary_gdf.to_file(str(output_path), driver='GPKG', index=False)
    console.log(f"[green]✔[/green] Boundary saved to '{output_path}'")
    return boundary_gdf


def _fetch_boundary_dawa(postalcode: str) -> gpd.GeoDataFrame:
    """
    Fetches the postal code boundary from the Danish DAWA API.
    Returns a GeoDataFrame in EPSG:4326.
    """
    console.log(f"  Using DAWA provider for Denmark...")
    try:
        url = f"https://api.dataforsyningen.dk/postnumre/{postalcode}"
        params = {"format": "geojson", "srid": "4326"}
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()

        geojson_data = response.json()

        if geojson_data.get("type") == "Feature":
            feature_collection = {
                "type": "FeatureCollection",
                "features": [geojson_data]
            }
        elif geojson_data.get("type") == "FeatureCollection":
            feature_collection = geojson_data
        else:
            raise ValueError(f"Unexpected GeoJSON type: {geojson_data.get('type')}")

        boundary_gdf = gpd.GeoDataFrame.from_features(
            feature_collection, crs="EPSG:4326"
        )
        console.log(f"  [green]✔[/green] DAWA returned boundary with {len(boundary_gdf)} feature(s)")
        return boundary_gdf

    except Exception as e:
        console.log(f"  [red]DAWA error:[/red] {e}")
        return gpd.GeoDataFrame()


def _fetch_boundary_osm(postalcode: str, country: str) -> gpd.GeoDataFrame:
    """
    Fetches the postal code boundary from OSM/Nominatim.
    This is a fallback for countries without a dedicated provider.
    Returns a GeoDataFrame in EPSG:4326.
    """
    console.log(f"  Using OSM/Nominatim provider...")
    try:
        query = {"postalcode": postalcode, "country": country}
        boundary_gdf = ox.geocode_to_gdf(query)
        console.log(f"  [green]✔[/green] Nominatim returned boundary with {len(boundary_gdf)} feature(s)")
        return boundary_gdf
    except Exception as e:
        console.log(f"  [red]Nominatim error:[/red] {e}")
        return gpd.GeoDataFrame()
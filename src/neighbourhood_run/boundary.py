# src/neighbourhood_run/boundary.py
import geopandas as gpd
import requests
from rich.console import Console
from .config import CONFIG

console = Console()

def get_area_boundary() -> gpd.GeoDataFrame:
    """
    Fetches the postal code boundary from the Danish DAWA API.
    Falls back to OSM/Nominatim for non-Danish postal codes.
    Returns the boundary as a GeoDataFrame in EPSG:4326.
    """
    query = CONFIG.area.query
    output_path = CONFIG.paths.raw_boundary
    output_path.parent.mkdir(parents=True, exist_ok=True)

    postalcode = None

    # Extract the postal code from the query
    if isinstance(query, dict):
        postalcode = query.get("postalcode")
    elif isinstance(query, str):
        # Try to extract a 4-digit Danish postal code from the string
        import re
        match = re.search(r'\b(\d{4})\b', query)
        if match:
            postalcode = match.group(1)

    if postalcode:
        console.log(f"Fetching boundary for Danish postal code '{postalcode}' from DAWA...")
        try:
            # DAWA API endpoint for postal code boundaries as GeoJSON
            url = f"https://api.dataforsyningen.dk/postnumre/{postalcode}"
            params = {"format": "geojson", "srid": "4326"}
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()

            geojson_data = response.json()

            # The DAWA API returns a single Feature, not a FeatureCollection
            # We need to wrap it in a FeatureCollection for GeoPandas
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

            boundary_gdf.to_file(str(output_path), driver='GPKG', index=False)
            console.log(f"[green]✔[/green] Boundary saved to '{output_path}'")
            return boundary_gdf

        except Exception as e:
            console.log(f"[red]Error fetching boundary from DAWA:[/red] {e}")
            return gpd.GeoDataFrame()
    else:
        console.log(f"[red]Error: Could not extract a postal code from query: {query}[/red]")
        return gpd.GeoDataFrame()
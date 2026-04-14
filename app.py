# neighbourhood_run/app.py
import json
from flask import Flask, render_template, jsonify, request
from pathlib import Path
import webbrowser
import threading
import geopandas as gpd

from src.neighbourhood_run import boundary, network, web, exclusions
from src.neighbourhood_run.config import CONFIG

app = Flask(__name__)


def _build_map_data() -> dict:
    """Builds the data payload for the interactive map."""
    # Load all required data
    boundary_gdf = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs("EPSG:4326")
    home_gdf = gpd.read_file(str(CONFIG.paths.processed_home)).to_crs("EPSG:4326")
    network_gdf = gpd.read_file(str(CONFIG.paths.processed_network)).to_crs("EPSG:4326")

    # Get excluded IDs
    excluded_ids = exclusions.load_excluded_ids()

    # Convert to GeoJSON
    boundary_geojson = json.loads(boundary_gdf.to_json())
    network_geojson = json.loads(network_gdf.to_json())

    # Clean up NaN values in properties (JSON doesn't support NaN)
    for feature in network_geojson["features"]:
        props = feature["properties"]
        for key, val in props.items():
            if val != val:  # NaN check
                props[key] = None
            elif isinstance(val, float) and abs(val) == float('inf'):
                props[key] = None

    # Map center
    centroid = boundary_gdf.geometry.iloc[0].centroid
    center = [centroid.y, centroid.x]

    # Home point
    home_point = [home_gdf.geometry.iloc[0].y, home_gdf.geometry.iloc[0].x]

    return {
        "center": center,
        "home": home_point,
        "boundary": boundary_geojson,
        "network": network_geojson,
        "excluded_ids": sorted(excluded_ids),
    }


@app.route('/')
def map_view():
    """Serves the interactive map."""
    map_data = _build_map_data()
    return render_template('map_interactive.html', map_data=map_data)


@app.route('/api/toggle-exclude/<int:edge_id>', methods=['POST'])
def toggle_exclude(edge_id):
    """Toggles the exclusion status of a segment."""
    result = exclusions.toggle_exclusion(edge_id)
    return jsonify(result)


@app.route('/api/get-exclusions')
def get_exclusions():
    """Returns the current exclusion summary."""
    return jsonify(exclusions.get_exclusion_summary())


@app.route('/api/rebuild-coverage', methods=['POST'])
def rebuild_coverage():
    """Re-runs coverage analysis with current exclusions applied."""
    try:
        from src.neighbourhood_run import coverage

        # First, rebuild the network with exclusions applied
        boundary_gdf = gpd.read_file(str(CONFIG.paths.raw_boundary))
        network.build_runnable_network(boundary_gdf)

        # Then re-run coverage
        coverage.analyze_coverage()

        return jsonify({
            "status": "success",
            "message": "Coverage rebuilt successfully. Page will reload."
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/build-network', methods=['POST'])
def build_network_endpoint():
    """API endpoint to trigger a full rebuild of the network."""
    try:
        boundary_gdf = boundary.get_area_boundary()
        if boundary_gdf.empty:
            return jsonify({"status": "error", "message": "Failed to get boundary"}), 500

        network.geocode_home()
        network.build_runnable_network(boundary_gdf)

        return jsonify({"status": "success", "message": "Network rebuilt."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    # Build network on first run if it doesn't exist
    if not Path(CONFIG.paths.processed_network).exists():
        print("Initial network not found. Building now...")
        boundary_gdf = boundary.get_area_boundary()
        if boundary_gdf.empty:
            print("[ERROR] Failed to download boundary. Exiting.")
        else:
            network.geocode_home()
            network.build_runnable_network(boundary_gdf)

            # Run initial coverage if tracks exist
            if Path(CONFIG.paths.processed_tracks).exists():
                from src.neighbourhood_run import coverage
                coverage.analyze_coverage()

    url = "http://127.0.0.1:5000"
    print(f"Starting web server at {url}")
    threading.Timer(1.25, lambda: webbrowser.open(url)).start()

    app.run(port=5000, debug=False)
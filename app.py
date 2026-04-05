# neighbourhood_run/app.py
from flask import Flask, render_template, jsonify
from pathlib import Path
import webbrowser
import threading

from src.neighbourhood_run import boundary, network, web

app = Flask(__name__)
# Use a placeholder template initially, as Folium will overwrite it.
# We create a dummy file to avoid a Flask error if it doesn't exist.
template_path = Path("templates/map_view.html")
if not template_path.exists():
    template_path.parent.mkdir(exist_ok=True)
    template_path.touch()

@app.route('/')
def map_view():
    """Serves the interactive map view."""
    # The map is pre-generated, we just render the template that contains it.
    return render_template('map_view.html')

@app.route('/api/build-network', methods=['POST'])
def build_network_endpoint():
    """API endpoint to trigger a full rebuild of the network."""
    try:
        print("--- Building Network ---")
        boundary_gdf = boundary.get_area_boundary()
        if boundary_gdf.empty:
            return jsonify({"status": "error", "message": "Failed to get boundary"}), 500
            
        network.geocode_home()
        runnable_network = network.build_runnable_network(boundary_gdf)
        web.create_network_map()
        
        total_km = runnable_network['length_m'].sum() / 1000
        message = f"Network build complete. Total runnable distance: {total_km:.2f} km."
        print(f"--- {message} ---")
        return jsonify({"status": "success", "message": message})
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    # We will build the network on first run if it doesn't exist
    if not Path(network.CONFIG.paths.processed_network).exists():
        print("Initial network not found. Building now...")
        boundary_gdf = boundary.get_area_boundary()
        if boundary_gdf.empty:
            print("[ERROR] Failed to download a valid boundary. Please check your query in config.yaml and your internet connectoin. Exiting.")
        else:
            network.geocode_home()
            network.build_runnable_network(boundary_gdf)
            web.create_network_map()

    # Open a browser window to the app
    url = "http://127.0.0.1:5000"
    print(f"Starting web server at {url}")
    threading.Timer(1.25, lambda: webbrowser.open(url)).start()
    
    app.run(port=5000, debug=False)
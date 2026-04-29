# neighbourhood_run/app.py
import json
from flask import Flask, render_template, jsonify, request, send_file
from pathlib import Path
import webbrowser
import threading
import geopandas as gpd

from src.neighbourhood_run import boundary, network, web, exclusions
from src.neighbourhood_run.config import CONFIG

app = Flask(__name__)

template_path = Path("templates/map_view.html")
if not template_path.exists():
    template_path.parent.mkdir(exist_ok=True)
    template_path.touch()


def _build_map_data() -> dict:
    """Builds the data payload for the interactive map."""
    boundary_gdf = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs("EPSG:4326")
    home_gdf = gpd.read_file(str(CONFIG.paths.processed_home)).to_crs("EPSG:4326")
    network_gdf = gpd.read_file(str(CONFIG.paths.processed_network)).to_crs("EPSG:4326")

    excluded_ids = exclusions.load_excluded_ids()

    boundary_geojson = json.loads(boundary_gdf.to_json())
    network_geojson = json.loads(network_gdf.to_json())

    for feature in network_geojson["features"]:
        props = feature["properties"]
        for key, val in props.items():
            if val != val:
                props[key] = None
            elif isinstance(val, float) and abs(val) == float('inf'):
                props[key] = None

    centroid = boundary_gdf.geometry.iloc[0].centroid
    center = [centroid.y, centroid.x]
    home_point = [home_gdf.geometry.iloc[0].y, home_gdf.geometry.iloc[0].x]

    # Load routes if they exist
    routes_geojson = None
    routes_path = CONFIG.paths.planned_routes
    if routes_path.exists():
        try:
            routes_gdf = gpd.read_file(str(routes_path)).to_crs("EPSG:4326")
            routes_geojson = json.loads(routes_gdf.to_json())
            for feature in routes_geojson["features"]:
                props = feature["properties"]
                for key, val in props.items():
                    if val != val:
                        props[key] = None
        except Exception:
            pass

    return {
        "center": center,
        "home": home_point,
        "boundary": boundary_geojson,
        "network": network_geojson,
        "excluded_ids": sorted(excluded_ids),
        "routes": routes_geojson,
    }


@app.route('/')
def map_view():
    """Serves the interactive map."""
    map_data = _build_map_data()
    return render_template('map_interactive.html', map_data=map_data)


@app.route('/api/toggle-exclude/<int:edge_id>', methods=['POST'])
def toggle_exclude(edge_id):
    result = exclusions.toggle_exclusion(edge_id)
    return jsonify(result)


@app.route('/api/get-exclusions')
def get_exclusions():
    return jsonify(exclusions.get_exclusion_summary())


@app.route('/api/rebuild-coverage', methods=['POST'])
def rebuild_coverage():
    try:
        from src.neighbourhood_run import coverage
        boundary_gdf = gpd.read_file(str(CONFIG.paths.raw_boundary))
        network.build_runnable_network(boundary_gdf)
        coverage.analyze_coverage()
        return jsonify({"status": "success", "message": "Coverage rebuilt. Page will reload."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sync-strava', methods=['POST'])
def sync_strava_endpoint():
    """Syncs activities from Strava and updates coverage incrementally."""
    try:
        from src.neighbourhood_run import strava_sync, coverage

        print("--- Strava Sync ---")
        result = strava_sync.run_full_sync()
        new_tracks = result["tracks"]
        new_activity_ids = result["new_activity_ids"]

        if new_tracks is not None and not new_tracks.empty:
            print("--- Incremental Coverage Update ---")
            coverage.update_coverage_incremental(new_tracks)
            message = f"Strava sync complete. {len(new_activity_ids)} new activities."
        else:
            message = "No new activities found."

        return jsonify({
            "status": "success",
            "message": message,
            "new_activity_ids": new_activity_ids,
        })
    except FileNotFoundError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/generate-routes', methods=['POST'])
def generate_routes_endpoint():
    """Generates or updates planned routes."""
    try:
        from src.neighbourhood_run import routing
        routes = routing.update_routes()
        return jsonify({
            "status": "success",
            "message": f"Generated {len(routes)} routes. Page will reload.",
            "route_count": len(routes)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/export-gpx/<int:route_id>', methods=['GET'])
def export_gpx(route_id):
    try:
        from src.neighbourhood_run import gpx_export
        gpx_path = gpx_export.export_route_gpx(route_id)
        return send_file(str(gpx_path), as_attachment=True)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/build-network', methods=['POST'])
def build_network_endpoint():
    try:
        boundary_gdf = boundary.get_area_boundary()
        if boundary_gdf.empty:
            return jsonify({"status": "error", "message": "Failed to get boundary"}), 500
        network.geocode_home()
        network.build_runnable_network(boundary_gdf)
        return jsonify({"status": "success", "message": "Network rebuilt."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/review/suggest-routes', methods=['POST'])
def suggest_routes_for_review():
    """
    Suggest likely planned routes for newly synced activities.
    Expects JSON: { "activity_ids": [...] }
    """
    try:
        from src.neighbourhood_run import reviews

        payload = request.get_json(force=True)
        activity_ids = payload.get("activity_ids", [])
        matches = reviews.suggest_route_matches(activity_ids)

        return jsonify({
            "status": "success",
            "matches": matches,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/review/route/<int:route_id>', methods=['POST'])
def route_review_payload(route_id):
    """
    Returns route review payload for one planned route and selected activity IDs.
    Expects JSON: { "activity_ids": [...] }
    """
    try:
        from src.neighbourhood_run import reviews

        payload = request.get_json(force=True)
        activity_ids = payload.get("activity_ids", [])
        data = reviews.get_route_review_payload(route_id, activity_ids)

        return jsonify({
            "status": "success",
            "data": data,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/review/segment/<int:edge_id>', methods=['POST'])
def set_segment_review(edge_id):
    """
    Sets review status for a segment.
    Expects JSON: { "status": "sidewalk_present|runnable_no_sidewalk|not_runnable|unsure" }
    """
    try:
        from src.neighbourhood_run import reviews

        payload = request.get_json(force=True)
        status = payload.get("status")
        result = reviews.set_segment_override(edge_id, status)

        return jsonify({
            "status": "success",
            "result": result,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/review/complete', methods=['POST'])
def complete_route_review():
    """
    Records completion of a route review.
    Expects JSON: { "route_id": int, "activity_ids": [...] }
    """
    try:
        from src.neighbourhood_run import reviews

        payload = request.get_json(force=True)
        route_id = int(payload["route_id"])
        activity_ids = payload.get("activity_ids", [])
        reviews.record_route_review(route_id, activity_ids)

        return jsonify({
            "status": "success",
            "message": "Route review recorded"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/review/find-test-activity', methods=['POST'])
def find_test_activity():
    """
    Finds existing activities that overlap with a planned route.
    Used for testing the review flow without running a new activity.
    """
    try:
        from src.neighbourhood_run import reviews
        import geopandas as gpd
        from shapely.ops import unary_union

        payload = request.get_json(force=True)
        route_id = int(payload.get("route_id", 0))

        routes = gpd.read_file(str(CONFIG.paths.planned_routes)).to_crs(CONFIG.project_crs)
        tracks = gpd.read_file(str(CONFIG.paths.processed_tracks)).to_crs(CONFIG.project_crs)

        route = routes[routes["route_id"] == route_id]
        if route.empty:
            return jsonify({"status": "error", "message": f"Route {route_id} not found"})

        route_geom = route.geometry.iloc[0]
        route_buffer = route_geom.buffer(50)  # 50m buffer for matching

        # Find tracks that overlap significantly with the route
        matches = []
        for _, track in tracks.iterrows():
            try:
                if track.geometry is None or track.geometry.is_empty:
                    continue
                overlap = track.geometry.intersection(route_buffer)
                if not overlap.is_empty:
                    overlap_ratio = overlap.length / route_geom.length
                    if overlap_ratio > 0.3:  # At least 30% overlap
                        matches.append({
                            "activity_id": str(track["activity_id"]),
                            "overlap_ratio": round(overlap_ratio, 2),
                        })
            except Exception:
                continue

        # Sort by overlap and take top 3
        matches.sort(key=lambda x: x["overlap_ratio"], reverse=True)
        top_matches = matches[:3]

        if not top_matches:
            return jsonify({
                "status": "error",
                "message": "No existing activities overlap enough with this route. Try a different route."
            })

        activity_ids = [m["activity_id"] for m in top_matches]

        return jsonify({
            "status": "success",
            "activity_ids": activity_ids,
            "matches": top_matches,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    from pathlib import Path

    # Build network on first run if it doesn't exist
    if not Path(CONFIG.paths.processed_network).exists():
        print("=" * 60)
        print("First run detected. Building network...")
        print("=" * 60)
        boundary_gdf = boundary.get_area_boundary()
        if boundary_gdf.empty:
            print("[ERROR] Failed to download boundary.")
            print("Check your config.yaml and internet connection.")
        else:
            network.geocode_home()
            network.build_runnable_network(boundary_gdf)
            print()
            print("Network built successfully.")
            print("Use 'Sync Strava' button in the app to import your runs.")
            print("Or run: python sync_strava.py")

    url = "http://127.0.0.1:5000"
    print(f"\nStarting web server at {url}")
    threading.Timer(1.25, lambda: webbrowser.open(url)).start()

    app.run(port=5000, debug=False)
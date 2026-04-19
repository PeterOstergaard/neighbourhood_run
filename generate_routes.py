# neighbourhood_run/generate_routes.py
"""
Generates all planned routes and updates the map.
"""
from src.neighbourhood_run import routing

routes = routing.generate_all_routes()

if not routes.empty:
    print(f"\nGenerated {len(routes)} routes!")
    print("Start the app to view and select routes: python app.py")
else:
    print("\nNo routes generated. All segments may already be covered.")
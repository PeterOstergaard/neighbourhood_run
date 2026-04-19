# neighbourhood_run/run_full_pipeline.py
"""
Runs the complete pipeline from scratch:
1. Download boundary
2. Geocode home
3. Build network
4. Sync Strava activities
5. Analyze coverage
6. Generate routes
"""
import time
from datetime import datetime

print("=" * 60)
print(f"FULL PIPELINE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

start_time = time.time()

# Step 1: Build the network
print("\n" + "─" * 60)
print("STEP 1: Building street network")
print("─" * 60)
from src.neighbourhood_run import boundary, network

boundary_gdf = boundary.get_area_boundary()
if boundary_gdf.empty:
    print("ERROR: Failed to download boundary. Exiting.")
    exit(1)

network.geocode_home()
network.build_runnable_network(boundary_gdf)

step1_time = time.time()
print(f"\n⏱ Step 1 completed in {step1_time - start_time:.0f} seconds")

# Step 2: Sync Strava
print("\n" + "─" * 60)
print("STEP 2: Syncing Strava activities")
print("─" * 60)
from src.neighbourhood_run import strava_sync

new_tracks = strava_sync.run_full_sync()

step2_time = time.time()
print(f"\n⏱ Step 2 completed in {step2_time - step1_time:.0f} seconds")

# Step 3: Coverage analysis
print("\n" + "─" * 60)
print("STEP 3: Analyzing coverage")
print("─" * 60)
from src.neighbourhood_run import coverage

coverage.analyze_coverage()

step3_time = time.time()
print(f"\n⏱ Step 3 completed in {step3_time - step2_time:.0f} seconds")

# Step 4: Generate routes
print("\n" + "─" * 60)
print("STEP 4: Generating routes")
print("─" * 60)
from src.neighbourhood_run import routing

routes = routing.generate_all_routes()

step4_time = time.time()
print(f"\n⏱ Step 4 completed in {step4_time - step3_time:.0f} seconds")

# Summary
total_time = time.time() - start_time
print("\n" + "=" * 60)
print("PIPELINE COMPLETE")
print("=" * 60)
print(f"\n  Total time: {total_time/60:.1f} minutes")
print(f"    Step 1 (Network):  {step1_time - start_time:.0f}s")
print(f"    Step 2 (Strava):   {step2_time - step1_time:.0f}s")
print(f"    Step 3 (Coverage): {step3_time - step2_time:.0f}s")
print(f"    Step 4 (Routes):   {step4_time - step3_time:.0f}s")
print(f"\n  Start the app: python app.py")
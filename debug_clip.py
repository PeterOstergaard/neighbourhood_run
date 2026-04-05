# neighbourhood_run/debug_clip.py
# A standalone diagnostic script to find out why clipping is failing.
import geopandas as gpd
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

print("=" * 60)
print("CLIP DIAGNOSTIC SCRIPT")
print("=" * 60)

# --- 1. Load the boundary ---
boundary_path = ROOT / "data" / "raw" / "boundaries" / "postcode_boundary.gpkg"
print(f"\n[1] Loading boundary from: {boundary_path}")
boundary = gpd.read_file(boundary_path)

print(f"    Rows: {len(boundary)}")
print(f"    CRS:  {boundary.crs}")
print(f"    Geometry types: {boundary.geom_type.unique()}")
print(f"    Total bounds (minx, miny, maxx, maxy): {boundary.total_bounds}")

# Check how many individual polygons exist
exploded = boundary.explode(index_parts=True)
print(f"    Number of individual polygon parts: {len(exploded)}")

# --- 2. Load the network ---
network_path = ROOT / "data" / "processed" / "network" / "runnable_network.gpkg"
print(f"\n[2] Loading network from: {network_path}")
network = gpd.read_file(network_path)

print(f"    Rows: {len(network)}")
print(f"    CRS:  {network.crs}")
print(f"    Total bounds: {network.total_bounds}")

# --- 3. Check CRS match ---
print(f"\n[3] CRS Comparison:")
print(f"    Boundary CRS: {boundary.crs}")
print(f"    Network CRS:  {network.crs}")
print(f"    CRS Match:    {boundary.crs == network.crs}")

# --- 4. Project both to the same CRS (EPSG:25832) ---
target_crs = "EPSG:25832"
print(f"\n[4] Projecting both to {target_crs}...")
boundary_proj = boundary.to_crs(target_crs)
network_proj = network.to_crs(target_crs)

print(f"    Boundary projected bounds: {boundary_proj.total_bounds}")
print(f"    Network projected bounds:  {network_proj.total_bounds}")

# --- 5. Dissolve the boundary ---
print(f"\n[5] Dissolving boundary...")
boundary_proj["_dissolve"] = 1
boundary_dissolved = boundary_proj.dissolve(by="_dissolve")

print(f"    Dissolved rows: {len(boundary_dissolved)}")
print(f"    Dissolved geometry type: {boundary_dissolved.geom_type.iloc[0]}")
print(f"    Dissolved CRS: {boundary_dissolved.crs}")
print(f"    Dissolved bounds: {boundary_dissolved.total_bounds}")

# Check if the dissolved geometry is valid
geom = boundary_dissolved.geometry.iloc[0]
print(f"    Is valid geometry: {geom.is_valid}")
print(f"    Geometry area (sq m): {geom.area:,.0f}")

# --- 6. Perform the clip ---
print(f"\n[6] Performing gpd.clip()...")
print(f"    Network rows BEFORE clip: {len(network_proj)}")

clipped = gpd.clip(network_proj, boundary_dissolved)

print(f"    Network rows AFTER clip:  {len(clipped)}")
print(f"    Clipped bounds: {clipped.total_bounds}")

# --- 7. Compare lengths ---
print(f"\n[7] Length comparison:")
network_proj["length_m"] = network_proj.geometry.length
clipped["length_m"] = clipped.geometry.length

total_before = network_proj["length_m"].sum() / 1000
total_after = clipped["length_m"].sum() / 1000

print(f"    Total network length BEFORE clip: {total_before:,.1f} km")
print(f"    Total network length AFTER clip:  {total_after:,.1f} km")
print(f"    Reduction: {((total_before - total_after) / total_before * 100):.1f}%")

# --- 8. Save the clipped result ---
output_path = ROOT / "data" / "debug"
output_path.mkdir(parents=True, exist_ok=True)

clipped_path = output_path / "clipped_network_debug.gpkg"
clipped.to_file(str(clipped_path), driver="GPKG", index=False)
print(f"\n[8] Saved clipped network to: {clipped_path}")

dissolved_path = output_path / "dissolved_boundary_debug.gpkg"
boundary_dissolved.to_file(str(dissolved_path), driver="GPKG", index=False)
print(f"    Saved dissolved boundary to: {dissolved_path}")

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
print(f"\nPlease check the files in: {output_path}")
print("Open them in QGIS or https://geojson.io to inspect visually.")
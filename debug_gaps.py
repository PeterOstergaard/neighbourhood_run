# neighbourhood_run/debug_gaps.py
import geopandas as gpd
from shapely.geometry import LineString
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))
network_proj = network.to_crs(CONFIG.project_crs)

boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
boundary_geom = boundary.geometry.iloc[0]

SNAP_TOL = 1.0

print("=" * 80)
print("ISSUE 1: Sophus Bauditz Vej - why optional?")
print("=" * 80)

sbv = network_proj[network_proj['name'].fillna('').str.contains('Sophus Bauditz', case=False)]
for _, row in sbv.iterrows():
    midpoint = row.geometry.interpolate(0.5, normalized=True)
    inside = midpoint.within(boundary_geom)
    print(f"  edge_id={row['edge_id']}  required={row['required']}  "
          f"length={row['length_m']:.1f}m  inside={inside}  "
          f"highway={row['highway']}  covered={row.get('covered', 'N/A')}")

print()
print("=" * 80)
print("ISSUE 2: Ved Lunden - looking for gaps")
print("=" * 80)

vl = network_proj[network_proj['name'].fillna('').str.contains('Ved Lunden', case=False)]
print(f"Found {len(vl)} segments")

# Check connectivity between segments
for i, (_, row1) in enumerate(vl.iterrows()):
    coords1 = list(row1.geometry.coords)
    start1 = coords1[0]
    end1 = coords1[-1]
    
    connected_to = []
    for j, (_, row2) in enumerate(vl.iterrows()):
        if i == j:
            continue
        coords2 = list(row2.geometry.coords)
        start2 = coords2[0]
        end2 = coords2[-1]
        
        for p1 in [start1, end1]:
            for p2 in [start2, end2]:
                dist = ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5
                if dist < SNAP_TOL:
                    connected_to.append(row2['edge_id'])
    
    print(f"  edge_id={row1['edge_id']}  length={row1['length_m']:.1f}m  "
          f"required={row1['required']}  connects_to={connected_to}")

# Check if there are unnamed segments filling the gaps
print(f"\nLooking for unnamed segments near Ved Lunden...")
for _, vl_row in vl.iterrows():
    coords = list(vl_row.geometry.coords)
    for endpoint in [coords[0], coords[-1]]:
        # Find segments that connect to this endpoint
        for _, other in network_proj.iterrows():
            if other['edge_id'] == vl_row['edge_id']:
                continue
            other_coords = list(other.geometry.coords)
            for op in [other_coords[0], other_coords[-1]]:
                dist = ((endpoint[0]-op[0])**2 + (endpoint[1]-op[1])**2)**0.5
                if dist < SNAP_TOL:
                    other_name = other.get('name', 'unnamed')
                    if str(other_name) == 'nan' or other_name is None:
                        other_name = 'UNNAMED'
                    if other_name != 'Ved Lunden':
                        print(f"    Ved Lunden edge {vl_row['edge_id']} connects to "
                              f"edge {other['edge_id']} ({other_name}, hw={other['highway']}, "
                              f"len={other['length_m']:.1f}m, required={other['required']})")

print()
print("=" * 80)
print("ISSUE 3: All gaps - segments inside boundary that are NOT required")
print("=" * 80)

# Find all named residential/tertiary/etc segments that are optional and inside boundary
def norm_hw(v):
    return v[0] if isinstance(v, list) else str(v)

named = network_proj[
    network_proj['name'].notna() & 
    (network_proj['name'] != '') &
    (network_proj['name'].astype(str) != 'nan') &
    (network_proj['required'] == False)
].copy()

named['_hw'] = named['highway'].apply(norm_hw)
named['_midpoint'] = named.geometry.interpolate(0.5, normalized=True)
named['_inside'] = named['_midpoint'].within(boundary_geom)

inside_named_optional = named[named['_inside']]

print(f"Named segments that are optional but INSIDE boundary: {len(inside_named_optional)}")
print(f"\nBreakdown by highway type:")
for hw_type in inside_named_optional['_hw'].value_counts().index:
    subset = inside_named_optional[inside_named_optional['_hw'] == hw_type]
    print(f"  {hw_type}: {len(subset)} segments, {subset['length_m'].sum()/1000:.2f} km")

print(f"\nBreakdown by road name:")
for name in inside_named_optional['name'].value_counts().head(20).index:
    subset = inside_named_optional[inside_named_optional['name'] == name]
    print(f"  {name}: {len(subset)} segments, {subset['length_m'].sum()/1000:.2f} km, hw={subset['_hw'].iloc[0]}")
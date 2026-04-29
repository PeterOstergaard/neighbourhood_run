# neighbourhood_run/debug_missing_roads.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))
network_proj = network.to_crs(CONFIG.project_crs)

# Load boundary
boundary = gpd.read_file(str(CONFIG.paths.raw_boundary)).to_crs(CONFIG.project_crs)
boundary_geom = boundary.geometry.iloc[0]

roads_to_check = [
    "Allégårdsvej",
    "Carit Etlars Vej",
    "Sophus Bauditz Vej",
    "Åby Bækgårdsvej",
    "Vibyvej",
    "B.S. Ingemanns Vej",
    "Søren Frichs Vej",
    "Egsagervej",
    "Ved Lunden",
    "Klamsagervej",
    "Vesterløkken",
    "Elkjærvej",
]

print("=" * 90)
print(f"{'Road':<25} {'Segs':>4} {'Req':>4} {'Opt':>4} {'Highway':<15} {'InBound':>7} {'Covered':>7}")
print("=" * 90)

issues_by_cause = {
    "outside_boundary": [],
    "sidewalk_filter": [],
    "short_service": [],
    "very_short": [],
    "unknown": [],
}

for road_name in roads_to_check:
    matches = network_proj[network_proj['name'].fillna('').str.contains(road_name, case=False)]
    
    if matches.empty:
        print(f"{road_name:<25} NOT FOUND IN NETWORK")
        continue
    
    n_required = (matches['required'] == True).sum()
    n_optional = (matches['required'] == False).sum()
    
    # Check why optional segments are optional
    optional_segs = matches[matches['required'] == False]
    
    # Get dominant highway type
    def norm_hw(v):
        return v[0] if isinstance(v, list) else str(v)
    
    hw_types = matches['highway'].apply(norm_hw).unique()
    hw_str = ', '.join(hw_types[:3])
    
    # Check boundary
    midpoints = optional_segs.geometry.interpolate(0.5, normalized=True)
    n_inside = sum(midpoints.within(boundary_geom)) if not optional_segs.empty else 0
    n_outside = len(optional_segs) - n_inside
    
    # Check covered
    n_covered = (matches.get('covered', False) == True).sum()
    
    print(f"{road_name:<25} {len(matches):>4} {n_required:>4} {n_optional:>4} {hw_str:<15} {n_inside:>3}/{n_outside:>3} {n_covered:>7}")
    
    # Diagnose each optional segment
    if not optional_segs.empty:
        for _, row in optional_segs.head(3).iterrows():
            midpoint = row.geometry.interpolate(0.5, normalized=True)
            inside = midpoint.within(boundary_geom)
            hw = norm_hw(row['highway'])
            length = row['length_m']
            name = row.get('name', '')
            is_named = name is not None and str(name).strip() != '' and str(name) != 'nan'
            
            cause = "unknown"
            if not inside:
                cause = "outside_boundary"
            elif hw in ('primary', 'primary_link', 'secondary', 'secondary_link'):
                cause = "sidewalk_filter"
            elif hw == 'service' and not is_named and length <= 75:
                cause = "short_service"
            elif length < 10:
                cause = "very_short"
            
            issues_by_cause[cause].append(f"  {road_name} edge_id={row['edge_id']} hw={hw} len={length:.1f}m inside={inside}")

print()
print("=" * 90)
print("DIAGNOSIS: Why are these segments optional?")
print("=" * 90)

for cause, items in issues_by_cause.items():
    if items:
        print(f"\n{cause.upper()} ({len(items)} segments):")
        for item in items[:10]:
            print(item)
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")

# Summary
print()
print("=" * 90)
print("SUMMARY")
print("=" * 90)
total_issues = sum(len(v) for v in issues_by_cause.values())
for cause, items in issues_by_cause.items():
    if items:
        pct = len(items) / total_issues * 100
        print(f"  {cause:<20} {len(items):>4} segments ({pct:.0f}%)")
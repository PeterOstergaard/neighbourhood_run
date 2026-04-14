# neighbourhood_run/check_flags.py
import geopandas as gpd
from src.neighbourhood_run.config import CONFIG

network = gpd.read_file(str(CONFIG.paths.processed_network))

flagged = network[network["review_flag"].fillna("").str.len() > 0]
print(f"Total flagged: {len(flagged)}")

# Breakdown by flag reason
flag_reasons = {}
for flag in flagged["review_flag"]:
    for reason in str(flag).split(";"):
        reason = reason.strip()
        if reason:
            flag_reasons[reason] = flag_reasons.get(reason, 0) + 1

print("\nFlag breakdown:")
for reason, count in sorted(flag_reasons.items(), key=lambda x: -x[1]):
    print(f"  {reason}: {count}")

# Show details for the most common flag
print("\nDetails of flagged segments:")
for reason in sorted(flag_reasons.keys()):
    subset = flagged[flagged["review_flag"].str.contains(reason, na=False)]
    total_km = subset["length_m"].sum() / 1000
    print(f"\n  {reason} ({len(subset)} segments, {total_km:.1f} km):")
    
    # Show highway type distribution
    def norm_hw(v):
        if isinstance(v, list):
            return v[0]
        return str(v)
    
    hw_counts = subset["highway"].apply(norm_hw).value_counts()
    for hw, count in hw_counts.items():
        print(f"    {hw}: {count}")
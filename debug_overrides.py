# neighbourhood_run/debug_overrides.py
from src.neighbourhood_run.reviews import load_segment_overrides

overrides = load_segment_overrides()
print(f"Total overrides: {len(overrides)}")

for o in overrides:
    print(f"  edge_id={o['edge_id']}  status={o['status']}")
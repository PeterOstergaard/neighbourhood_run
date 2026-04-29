# src/neighbourhood_run/routing.py
"""
Route generation engine.
Generates routes that start/end at home, cover uncovered segments,
and respect min/max distance constraints.
"""
import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely import geometry
from shapely.geometry import LineString, Point, MultiLineString
from shapely.ops import linemerge
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
)
from typing import List, Dict, Tuple, Optional
import colorsys

from .config import CONFIG

console = Console()

SNAP_TOLERANCE = 0.5

# Distinct colors for routes (color-blind friendly palette)
ROUTE_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
    "#000075", "#a9a9a9",
]


def _build_routing_graph(network: gpd.GeoDataFrame) -> Tuple[nx.Graph, dict, dict, dict]:
    """
    Builds a NetworkX graph from the network edges.
    Returns the graph, node coordinates, edge-to-nodes mapping,
    and node-to-edges mapping.
    """
    node_map = {}
    node_id_counter = [0]

    def get_or_create_node(x, y):
        for (nx_, ny_), nid in node_map.items():
            if ((nx_ - x)**2 + (ny_ - y)**2)**0.5 < SNAP_TOLERANCE:
                return nid
        node_map[(x, y)] = node_id_counter[0]
        node_id_counter[0] += 1
        return node_id_counter[0] - 1

    G = nx.Graph()
    node_coords = {}
    edge_to_nodes = {}
    node_to_edges = {}

    for _, row in network.iterrows():
        coords = list(row.geometry.coords)
        sn = get_or_create_node(coords[0][0], coords[0][1])
        en = get_or_create_node(coords[-1][0], coords[-1][1])
        node_coords[sn] = coords[0]
        node_coords[en] = coords[-1]

        eid = row["edge_id"]
        length = row["length_m"]

        G.add_edge(sn, en, edge_id=eid, length=length,
                    required=row.get("required", True),
                    covered=row.get("covered", False),
                    reachable=row.get("reachable", True))

        edge_to_nodes[eid] = (sn, en)

        for n in [sn, en]:
            if n not in node_to_edges:
                node_to_edges[n] = []
            node_to_edges[n].append(eid)

    return G, node_coords, edge_to_nodes, node_to_edges


def _find_home_node(node_coords: dict, home_point) -> int:
    """Finds the graph node nearest to home."""
    min_dist = float('inf')
    home_node = None
    for nid, (nx_, ny_) in node_coords.items():
        dist = ((nx_ - home_point.x)**2 + (ny_ - home_point.y)**2)**0.5
        if dist < min_dist:
            min_dist = dist
            home_node = nid
    return home_node


def _get_uncovered_targets(G: nx.Graph) -> set:
    """Returns the set of edge IDs that need to be covered."""
    targets = set()
    for u, v, data in G.edges(data=True):
        if data.get("required", True) and not data.get("covered", False) and data.get("reachable", True):
            targets.add(data["edge_id"])
    return targets


def _path_to_edge_list(G: nx.Graph, path: list) -> List[dict]:
    """Converts a node path to a list of edge traversals."""
    edges = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        data = G.edges[u, v]
        edges.append({
            "edge_id": data["edge_id"],
            "from_node": u,
            "to_node": v,
            "length": data["length"],
            "required": data.get("required", True),
            "covered": data.get("covered", False),
        })
    return edges


def _find_nearest_target_edge(G: nx.Graph, current_node: int,
                                uncovered: set, edge_to_nodes: dict) -> Optional[Tuple[int, list]]:
    """
    Finds the nearest uncovered target edge and returns its edge_id
    and the shortest path to reach it.
    """
    best_edge = None
    best_path = None
    best_dist = float('inf')

    for eid in uncovered:
        if eid not in edge_to_nodes:
            continue
        sn, en = edge_to_nodes[eid]

        for target_node in [sn, en]:
            try:
                path = nx.shortest_path(G, current_node, target_node, weight="length")
                dist = sum(G.edges[path[i], path[i+1]]["length"] for i in range(len(path)-1))
                if dist < best_dist:
                    best_dist = dist
                    best_edge = eid
                    best_path = path
            except nx.NetworkXNoPath:
                continue

    return (best_edge, best_path) if best_edge is not None else None


def _build_route_greedy(G: nx.Graph, home_node: int, uncovered: set,
                         edge_to_nodes: dict, node_to_edges: dict,
                         max_distance: float,
                         network: gpd.GeoDataFrame) -> Tuple[List[int], set, float, LineString]:
    """
    Builds a single route using a greedy algorithm.
    Returns: (node_path, covered_edges, total_distance, route_geometry)
    """
    # Build geometry lookup
    edge_geoms = {}
    for _, row in network.iterrows():
        edge_geoms[row["edge_id"]] = row.geometry

    route_nodes = [home_node]
    route_edge_ids = []  # Track edge IDs in order of traversal
    route_covered = set()
    current_node = home_node
    distance_used = 0.0
    local_uncovered = uncovered.copy()

    def add_edge_traversal(from_node, to_node):
        """Records an edge traversal and returns its length."""
        nonlocal distance_used
        if G.has_edge(from_node, to_node):
            data = G.edges[from_node, to_node]
            route_edge_ids.append((data["edge_id"], from_node, to_node))
            route_nodes.append(to_node)
            length = data["length"]
            distance_used += length
            return length
        return 0

    def add_path(path):
        """Adds a sequence of nodes as a path."""
        dist = 0
        for j in range(len(path) - 1):
            dist += add_edge_traversal(path[j], path[j + 1])
        return dist

    while local_uncovered:
        result = _find_nearest_target_edge(G, current_node, local_uncovered, edge_to_nodes)
        if result is None:
            break

        # Verify we can get home from the target edge before committing
        target_edge_id, path_to_target = result
        target_sn, target_en = edge_to_nodes[target_edge_id]
        
        can_return_from_sn = nx.has_path(G, target_sn, home_node)
        can_return_from_en = nx.has_path(G, target_en, home_node)
        
        if not can_return_from_sn and not can_return_from_en:
            # This segment is in a dead zone — skip it permanently
            local_uncovered.discard(target_edge_id)
            continue

        dist_to_target = sum(
            G.edges[path_to_target[i], path_to_target[i+1]]["length"]
            for i in range(len(path_to_target) - 1)
        )

        target_length = G.edges[target_sn, target_en]["length"]
        target_end = target_en if path_to_target[-1] == target_sn else target_sn

        try:
            path_home = nx.shortest_path(G, target_end, home_node, weight="length")
            dist_home = sum(
                G.edges[path_home[i], path_home[i+1]]["length"]
                for i in range(len(path_home) - 1)
            )
        except nx.NetworkXNoPath:
            local_uncovered.discard(target_edge_id)
            continue

        total_if_added = distance_used + dist_to_target + target_length + dist_home
        if total_if_added > max_distance:
            local_uncovered.discard(target_edge_id)
            continue

        # Add path to target
        add_path(path_to_target)

        # Traverse target edge
        if current_node == target_sn or route_nodes[-1] == target_sn:
            add_edge_traversal(target_sn, target_en)
            current_node = target_en
        else:
            add_edge_traversal(target_en, target_sn)
            current_node = target_sn

        route_covered.add(target_edge_id)
        local_uncovered.discard(target_edge_id)

        # Explore adjacent uncovered edges
        keep_exploring = True
        while keep_exploring:
            keep_exploring = False
            if current_node in node_to_edges:
                for adj_eid in node_to_edges[current_node]:
                    if adj_eid not in local_uncovered:
                        continue
                    adj_sn, adj_en = edge_to_nodes[adj_eid]
                    adj_length = G.edges[adj_sn, adj_en]["length"]
                    adj_end = adj_en if current_node == adj_sn else adj_sn

                    try:
                        path_home_adj = nx.shortest_path(G, adj_end, home_node, weight="length")
                        dist_home_adj = sum(
                            G.edges[path_home_adj[i], path_home_adj[i+1]]["length"]
                            for i in range(len(path_home_adj) - 1)
                        )
                    except nx.NetworkXNoPath:
                        continue

                    if distance_used + adj_length + dist_home_adj <= max_distance:
                        add_edge_traversal(current_node, adj_end)
                        current_node = adj_end
                        route_covered.add(adj_eid)
                        local_uncovered.discard(adj_eid)
                        keep_exploring = True
                        break

    # Return home
    if current_node != home_node:
        try:
            path_home = nx.shortest_path(G, current_node, home_node, weight="length")
            add_path(path_home)
        except nx.NetworkXNoPath:
            # No forward path to home — backtrack along the route we came
            # This reverses the route back to home, which is always valid
            console.log(f"    [yellow]No forward path home, backtracking...[/yellow]")
            backtrack = list(reversed(route_nodes[:-1]))  # Exclude current position
            for node in backtrack:
                if G.has_edge(current_node, node):
                    add_edge_traversal(current_node, node)
                    current_node = node
                if current_node == home_node:
                    break
            
            # If backtracking didn't reach home, something is very wrong
            if current_node != home_node:
                console.log(f"    [red]Warning: Could not return home even by backtracking[/red]")

    # Build geometry from collected edge traversals
    all_coords = []
    for eid, from_node, to_node in route_edge_ids:
        geom = edge_geoms.get(eid)
        if geom is not None:
            edge_coords = list(geom.coords)
            sn, en = edge_to_nodes.get(eid, (from_node, to_node))
            if sn != from_node:
                edge_coords = edge_coords[::-1]
            if all_coords:
                all_coords.extend(edge_coords[1:])
            else:
                all_coords.extend(edge_coords)
        else:
            # Edge geometry not found — find a real road path between these nodes
            try:
                detour_path = nx.shortest_path(G, from_node, to_node, weight="length")
                for j in range(len(detour_path) - 1):
                    du, dv = detour_path[j], detour_path[j + 1]
                    if G.has_edge(du, dv):
                        detour_eid = G.edges[du, dv].get("edge_id")
                        detour_geom = edge_geoms.get(detour_eid) if detour_eid is not None else None
                        if detour_geom is not None:
                            detour_coords = list(detour_geom.coords)
                            detour_sn, detour_en = edge_to_nodes.get(detour_eid, (du, dv))
                            if detour_sn != du:
                                detour_coords = detour_coords[::-1]
                            if all_coords:
                                all_coords.extend(detour_coords[1:])
                            else:
                                all_coords.extend(detour_coords)
            except nx.NetworkXNoPath:
                # Truly no path — skip this segment entirely
                pass

    route_geometry = LineString(all_coords) if len(all_coords) >= 2 else None

    return route_nodes, route_covered, distance_used, route_geometry

def _pad_route(G: nx.Graph, route_nodes: List[int], home_node: int,
                current_distance: float, min_distance: float,
                node_coords: dict) -> Tuple[List[int], float]:
    """
    Pads a route that is too short by adding already-covered segments
    near the route to reach the minimum distance.
    """
    if current_distance >= min_distance:
        return route_nodes, current_distance

    deficit = min_distance - current_distance

    # Find covered edges adjacent to the route that we can add as a loop
    route_node_set = set(route_nodes)
    candidates = []

    for node in route_node_set:
        for u, v, data in G.edges(node, data=True):
            other = v if u == node else u
            length = data["length"]
            # An out-and-back on this edge adds 2x its length
            if 2 * length <= deficit + 500:  # Allow slight overshoot
                candidates.append((node, other, length, data["edge_id"]))

    # Sort by length descending to fill the deficit efficiently
    candidates.sort(key=lambda x: x[2], reverse=True)

    # Find where in the route to insert the padding
    # We'll add it just before returning home
    padded_nodes = route_nodes[:-1]  # Remove the final home node
    padded_distance = current_distance

    for start_node, end_node, length, eid in candidates:
        if padded_distance >= min_distance:
            break

        # Add an out-and-back: go to end_node and come back
        if start_node in route_node_set:
            padded_nodes.append(end_node)
            padded_nodes.append(start_node)
            padded_distance += 2 * length

    # Add the return home
    last_node = padded_nodes[-1]
    if last_node != home_node:
        try:
            path_home = nx.shortest_path(G, last_node, home_node, weight="length")
            dist_home = sum(
                G.edges[path_home[i], path_home[i+1]]["length"]
                for i in range(len(path_home) - 1)
            )
            for node in path_home[1:]:
                padded_nodes.append(node)
            padded_distance += dist_home
        except nx.NetworkXNoPath:
            padded_nodes.append(home_node)

    return padded_nodes, padded_distance


def _node_path_to_geometry(G: nx.Graph, node_path: List[int],
                            network: gpd.GeoDataFrame,
                            edge_to_nodes: dict) -> LineString:
    """
    Converts a node path to a LineString by following actual road geometries.
    Falls back to straight lines between nodes only when no edge geometry exists.
    """
    if len(node_path) < 2:
        return None

    # Build lookup: edge_id -> geometry
    edge_geoms = {}
    for _, row in network.iterrows():
        edge_geoms[row["edge_id"]] = row.geometry

    # Build lookup: (node_a, node_b) -> (edge_id, is_reversed)
    node_pair_to_edge = {}
    for eid, (sn, en) in edge_to_nodes.items():
        node_pair_to_edge[(sn, en)] = (eid, False)
        node_pair_to_edge[(en, sn)] = (eid, True)

    # Also build a node coordinate lookup from the network geometries
    node_coordinates = {}
    for eid, (sn, en) in edge_to_nodes.items():
        geom = edge_geoms.get(eid)
        if geom is not None:
            coords = list(geom.coords)
            if sn not in node_coordinates:
                node_coordinates[sn] = coords[0]
            if en not in node_coordinates:
                node_coordinates[en] = coords[-1]

    all_coords = []

    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]

        edge_info = node_pair_to_edge.get((u, v))
        if edge_info is not None:
            eid, is_reversed = edge_info
            geom = edge_geoms.get(eid)
            if geom is not None:
                edge_coords = list(geom.coords)
                if is_reversed:
                    edge_coords = edge_coords[::-1]

                if all_coords:
                    all_coords.extend(edge_coords[1:])
                else:
                    all_coords.extend(edge_coords)
                continue

        # Fallback: try to find an edge through the graph
        if G.has_edge(u, v):
            edge_data = G.edges[u, v]
            eid = edge_data.get("edge_id")
            if eid is not None:
                geom = edge_geoms.get(eid)
                if geom is not None:
                    # Determine direction
                    sn, en = edge_to_nodes.get(eid, (None, None))
                    edge_coords = list(geom.coords)
                    if sn == v:
                        edge_coords = edge_coords[::-1]

                    if all_coords:
                        all_coords.extend(edge_coords[1:])
                    else:
                        all_coords.extend(edge_coords)
                    continue

        # Last resort: straight line using node coordinates
        if u in node_coordinates and v in node_coordinates:
            coord_u = node_coordinates[u]
            coord_v = node_coordinates[v]
            if all_coords:
                all_coords.append(coord_v)
            else:
                all_coords.extend([coord_u, coord_v])

    if len(all_coords) < 2:
        return None

    return LineString(all_coords)

def generate_all_routes() -> gpd.GeoDataFrame:
    """
    Main entry point: generates all routes needed to cover
    remaining uncovered segments.
    """
    console.log("[bold cyan]═══ Route Generation ═══[/bold cyan]")

    max_dist = CONFIG.routing.max_distance_km * 1000
    min_dist = CONFIG.routing.min_distance_km * 1000

    # Load network and apply any segment overrides
    console.log("[bold]Step 1: Loading network...[/bold]")
    network = gpd.read_file(str(CONFIG.paths.processed_network))
    network = network.to_crs(CONFIG.project_crs)

    # Apply segment overrides (e.g., segments marked not_runnable during review)
    from .reviews import load_segment_overrides
    overrides = load_segment_overrides()
    if overrides:
        override_map = {o["edge_id"]: o["status"] for o in overrides}
        n_blocked = 0
        for idx, row in network.iterrows():
            eid = row["edge_id"]
            if eid in override_map:
                status = override_map[eid]
                if status == "not_runnable":
                    network.at[idx, "required"] = False
                    n_blocked += 1
                elif status in ("sidewalk_present", "runnable_no_sidewalk"):
                    network.at[idx, "required"] = True
        if n_blocked > 0:
            console.log(f"  Applied {n_blocked} not-runnable overrides")

    # Load home
    home_gdf = gpd.read_file(str(CONFIG.paths.processed_home))
    home_proj = home_gdf.to_crs(CONFIG.project_crs)
    home_point = home_proj.geometry.iloc[0]

    # Build graph
    console.log("[bold]Step 2: Building routing graph...[/bold]")
    G, node_coords, edge_to_nodes, node_to_edges = _build_routing_graph(network)
    home_node = _find_home_node(node_coords, home_point)

    console.log(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    console.log(f"  Home node: {home_node}")

    # Find uncovered targets
    uncovered = _get_uncovered_targets(G)
    uncovered_km = sum(
        G.edges[u, v]["length"]
        for u, v, d in G.edges(data=True)
        if d["edge_id"] in uncovered
    ) / 1000

    console.log(f"  Uncovered target segments: {len(uncovered)} ({uncovered_km:.1f} km)")

    if not uncovered:
        console.log("[green]All required segments are already covered![/green]")
        return gpd.GeoDataFrame()

    # Generate routes
    console.log(f"[bold]Step 3: Generating routes (max {max_dist/1000:.0f} km, min {min_dist/1000:.0f} km)...[/bold]")

    routes = []
    remaining = uncovered.copy()
    route_number = 1

    while remaining:
        console.log(f"\n  [bold]Route {route_number}:[/bold] {len(remaining)} segments remaining...")

        # Build route
        route_nodes, covered_edges, distance, geometry = _build_route_greedy(
            G, home_node, remaining, edge_to_nodes, node_to_edges, max_dist, network
        )

        if not covered_edges:
            console.log(f"    [yellow]Could not reach any more segments[/yellow]")
            break

        # Pad if too short
        if distance < min_dist:
            console.log(f"    Distance {distance/1000:.1f} km < min {min_dist/1000:.1f} km, padding...")
            route_nodes, distance = _pad_route(
                G, route_nodes, home_node, distance, min_dist, node_coords
            )
            # Rebuild geometry after padding
            geometry = _node_path_to_geometry(G, route_nodes, network, edge_to_nodes)

        if geometry is None:
            console.log(f"    [yellow]Failed to create geometry[/yellow]")
            break

        # Calculate stats
        new_coverage_km = sum(
            G.edges[edge_to_nodes[eid][0], edge_to_nodes[eid][1]]["length"]
            for eid in covered_edges
        ) / 1000

        color = ROUTE_COLORS[(route_number - 1) % len(ROUTE_COLORS)]

        route_data = {
            "route_id": route_number,
            "route_name": f"Route {route_number}",
            "distance_km": round(distance / 1000, 1),
            "new_coverage_km": round(new_coverage_km, 1),
            "segments_covered": len(covered_edges),
            "color": color,
            "covered_edge_ids": ",".join(str(eid) for eid in sorted(covered_edges)),
            "geometry": geometry,
        }
        routes.append(route_data)

        console.log(f"    Distance: {distance/1000:.1f} km")
        console.log(f"    New coverage: {new_coverage_km:.1f} km ({len(covered_edges)} segments)")

        # Remove covered edges from remaining
        remaining -= covered_edges
        route_number += 1

        # Safety limit
        if route_number > 100:
            console.log("[yellow]Safety limit reached (100 routes). Stopping.[/yellow]")
            break

    if not routes:
        console.log("[yellow]No routes could be generated.[/yellow]")
        return gpd.GeoDataFrame()

    # Create GeoDataFrame
    routes_gdf = gpd.GeoDataFrame(routes, crs=CONFIG.project_crs)

    # Save
    output_path = CONFIG.paths.planned_routes
    output_path.parent.mkdir(parents=True, exist_ok=True)
    routes_gdf.to_file(str(output_path), driver="GPKG", index=False)

    # Summary
    total_routes = len(routes_gdf)
    total_distance = routes_gdf["distance_km"].sum()
    total_coverage = routes_gdf["new_coverage_km"].sum()

    console.log("")
    console.log("[bold cyan]═══ Route Generation Summary ═══[/bold cyan]")
    console.log(f"  Total routes:          {total_routes}")
    console.log(f"  Total distance:        {total_distance:.1f} km")
    console.log(f"  Total new coverage:    {total_coverage:.1f} km")
    console.log(f"  Remaining uncovered:   {len(remaining)} segments")
    console.log(f"  Saved to: {output_path}")

    for _, r in routes_gdf.iterrows():
        console.log(
            f"    {r['route_name']:>12}: {r['distance_km']:5.1f} km "
            f"({r['new_coverage_km']:.1f} km new, {r['segments_covered']} segments)"
        )

    return routes_gdf

def update_routes() -> gpd.GeoDataFrame:
    """
    Smart route update. Checks which planned routes have had their
    key segments covered by new runs, and only regenerates those.
    If no routes exist, generates all from scratch.
    """
    console.log("[bold cyan]═══ Smart Route Update ═══[/bold cyan]")

    routes_path = CONFIG.paths.planned_routes
    if not routes_path.exists():
        console.log("  No existing routes. Generating from scratch...")
        return generate_all_routes()

    # Load current routes and network
    routes = gpd.read_file(str(routes_path))
    network = gpd.read_file(str(CONFIG.paths.processed_network))

    if routes.empty:
        return generate_all_routes()

    # Check each route: how many of its target segments are still uncovered?
    console.log("[bold]Checking existing routes...[/bold]")
    routes_to_keep = []
    routes_to_regenerate = []

    for _, route in routes.iterrows():
        covered_ids_str = route.get("covered_edge_ids", "")
        if not covered_ids_str or pd.isna(covered_ids_str):
            routes_to_regenerate.append(route["route_id"])
            continue

        edge_ids = [int(x) for x in str(covered_ids_str).split(",")]

        # Check how many are still uncovered
        route_edges = network[network["edge_id"].isin(edge_ids)]
        still_uncovered = route_edges[route_edges.get("covered", False) == False]

        if len(still_uncovered) == 0:
            # All segments in this route are now covered — drop the route
            console.log(f"  Route {route['route_id']}: fully covered — removing")
        elif len(still_uncovered) == len(edge_ids):
            # No segments covered — route is still valid
            routes_to_keep.append(route)
            console.log(f"  Route {route['route_id']}: still valid ({len(still_uncovered)} segments remaining)")
        else:
            # Partially covered — needs regeneration
            console.log(f"  Route {route['route_id']}: partially covered ({len(still_uncovered)}/{len(edge_ids)} remaining) — regenerating")
            routes_to_regenerate.append(route["route_id"])

    if not routes_to_regenerate and len(routes_to_keep) == len(routes):
        console.log("[green]All routes still valid. No changes needed.[/green]")
        return routes

    # Regenerate
    console.log(f"\n  Routes to keep: {len(routes_to_keep)}")
    console.log(f"  Routes to regenerate: {len(routes_to_regenerate)}")
    console.log(f"  Regenerating all routes to optimize...")

    # For simplicity, regenerate all routes from scratch
    # The coverage data is up to date, so this will automatically
    # skip already-covered segments
    return generate_all_routes()
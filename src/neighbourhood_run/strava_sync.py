# src/neighbourhood_run/strava_sync.py
"""
Strava API integration using OAuth2.
Downloads running activities and GPS streams.
"""
import json
import time
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Thread
from datetime import datetime

import requests
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TimeRemainingColumn
)

from .config import CONFIG, load_secrets

console = Console()

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
REDIRECT_PORT = 8089
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


# ═══ OAuth2 Authentication ═══

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth2 callback from Strava."""
    auth_code = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this window and return to the app.</p>"
                b"</body></html>"
            )
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h2>Authorization failed: {error}</h2></body></html>".encode()
            )

    def log_message(self, format, *args):
        pass  # Suppress default logging


def _load_token() -> dict | None:
    """Loads cached OAuth token from disk."""
    token_path = CONFIG.paths.strava_token
    if token_path.exists():
        with open(str(token_path), 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def _save_token(token: dict):
    """Saves OAuth token to disk."""
    token_path = CONFIG.paths.strava_token
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(token_path), 'w', encoding='utf-8') as f:
        json.dump(token, f, indent=2)


def _refresh_token(token: dict) -> dict:
    """Refreshes an expired OAuth token."""
    secrets = load_secrets()
    strava = secrets.strava

    console.log("Refreshing Strava access token...")
    response = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": strava.client_id,
        "client_secret": strava.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
    })
    response.raise_for_status()
    new_token = response.json()
    _save_token(new_token)
    console.log("[green]✔[/green] Token refreshed")
    return new_token


def authenticate() -> str:
    """
    Authenticates with Strava and returns a valid access token.
    Uses cached token if available, refreshes if expired,
    or initiates full OAuth2 flow if no token exists.
    """
    # Try cached token
    token = _load_token()

    if token is not None:
        # Check if token is expired
        expires_at = token.get("expires_at", 0)
        if time.time() < expires_at - 60:
            console.log("[green]✔[/green] Using cached Strava token")
            return token["access_token"]
        else:
            # Refresh the token
            try:
                token = _refresh_token(token)
                return token["access_token"]
            except Exception as e:
                console.log(f"[yellow]Token refresh failed: {e}. Starting fresh login.[/yellow]")

    # Full OAuth2 flow
    secrets = load_secrets()
    strava = secrets.strava

    if strava is None:
        raise ValueError("Strava credentials not found in secrets.yaml")

    console.log("[bold]Starting Strava OAuth2 authorization...[/bold]")
    console.log("A browser window will open. Please log in and authorize the app.")

    # Build authorization URL
    auth_url = (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={strava.client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&approval_prompt=auto"
    )

    # Start local server to catch the callback
    server = HTTPServer(("localhost", REDIRECT_PORT), _OAuthCallbackHandler)
    server_thread = Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    # Open browser
    webbrowser.open(auth_url)
    console.log(f"Waiting for authorization (listening on port {REDIRECT_PORT})...")

    # Wait for the callback
    server_thread.join(timeout=120)
    server.server_close()

    auth_code = _OAuthCallbackHandler.auth_code
    if auth_code is None:
        raise TimeoutError("Authorization timed out. Please try again.")

    console.log("Authorization code received. Exchanging for token...")

    # Exchange code for token
    response = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": strava.client_id,
        "client_secret": strava.client_secret,
        "code": auth_code,
        "grant_type": "authorization_code",
    })
    response.raise_for_status()
    token = response.json()
    _save_token(token)

    console.log(f"[green]✔[/green] Authenticated as: {token.get('athlete', {}).get('firstname', 'Unknown')}")

    return token["access_token"]


# ═══ Activity List Sync ═══

def _load_activity_list() -> list:
    """Loads cached activity list."""
    path = CONFIG.paths.strava_activity_list
    if path.exists():
        with open(str(path), 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def _save_activity_list(activities: list):
    """Saves activity list to disk."""
    path = CONFIG.paths.strava_activity_list
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), 'w', encoding='utf-8') as f:
        json.dump(activities, f, indent=2, default=str)


def sync_activity_list(access_token: str) -> list:
    """
    Downloads the full list of running activities from Strava.
    Incremental: only fetches activities newer than the most recent cached one.
    """
    console.log("[bold]Syncing activity list from Strava...[/bold]")

    cached = _load_activity_list()
    allowed_types = set(CONFIG.strava.activity_types)

    # Find the most recent cached activity timestamp
    after_timestamp = None
    if cached:
        # Strava timestamps are ISO format
        dates = [a.get("start_date", "") for a in cached if a.get("start_date")]
        if dates:
            most_recent = max(dates)
            # Convert to unix timestamp
            dt = datetime.fromisoformat(most_recent.replace("Z", "+00:00"))
            after_timestamp = int(dt.timestamp())
            console.log(f"  Most recent cached activity: {most_recent}")

    # Download activities page by page
    page = 1
    per_page = CONFIG.strava.per_page
    new_activities = []
    rate_limit = CONFIG.strava.rate_limit_seconds

    headers = {"Authorization": f"Bearer {access_token}"}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching activities...", total=None)

        while True:
            params = {
                "page": page,
                "per_page": per_page,
            }
            if after_timestamp:
                params["after"] = after_timestamp

            try:
                response = requests.get(
                    f"{STRAVA_API_BASE}/athlete/activities",
                    headers=headers,
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                batch = response.json()
            except Exception as e:
                console.log(f"  [red]Error fetching page {page}: {e}[/red]")
                break

            if not batch:
                break

            # Filter to running activities
            running = [a for a in batch if a.get("type") in allowed_types]
            new_activities.extend(running)

            progress.update(task,
                            description=f"Page {page}: {len(new_activities)} running activities found...")

            page += 1
            time.sleep(rate_limit)

    if new_activities:
        console.log(f"  Found {len(new_activities)} new running activities")
        # Merge with cached (new first, avoid duplicates by ID)
        cached_ids = {a["id"] for a in cached}
        unique_new = [a for a in new_activities if a["id"] not in cached_ids]
        all_activities = unique_new + cached
    else:
        console.log("  No new running activities found")
        all_activities = cached

    _save_activity_list(all_activities)
    console.log(f"  [green]✔[/green] Total cached running activities: {len(all_activities)}")

    return all_activities


# ═══ GPS Stream Download ═══

def download_streams(access_token: str, activities: list) -> list:
    """
    Downloads GPS streams for activities that haven't been processed yet.
    Returns list of successfully downloaded activity dicts with GPS data.
    """
    console.log("[bold]Downloading GPS streams...[/bold]")

    headers = {"Authorization": f"Bearer {access_token}"}
    rate_limit = CONFIG.strava.rate_limit_seconds

    # Check which activities already have tracks
    tracks_path = CONFIG.paths.processed_tracks
    already_parsed = set()
    if tracks_path.exists():
        try:
            existing = gpd.read_file(str(tracks_path))
            if "activity_id" in existing.columns:
                already_parsed = {str(aid) for aid in existing["activity_id"].tolist()}
        except Exception:
            pass

    # Filter to activities that need downloading
    to_download = [
        a for a in activities
        if f"strava_{a['id']}" not in already_parsed
    ]

    if not to_download:
        console.log("  All activity streams already downloaded.")
        return []

    console.log(f"  Activities to download: {len(to_download)}")

    downloaded = []
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading...", total=len(to_download))

        for i, activity in enumerate(to_download):
            aid = activity["id"]

            try:
                response = requests.get(
                    f"{STRAVA_API_BASE}/activities/{aid}/streams",
                    headers=headers,
                    params={"keys": "latlng", "key_type": "value"},
                    timeout=30
                )

                if response.status_code == 429:
                    # Rate limited — wait and retry
                    console.log(f"  [yellow]Rate limited. Waiting 60 seconds...[/yellow]")
                    time.sleep(60)
                    response = requests.get(
                        f"{STRAVA_API_BASE}/activities/{aid}/streams",
                        headers=headers,
                        params={"keys": "latlng", "key_type": "value"},
                        timeout=30
                    )

                response.raise_for_status()
                streams = response.json()

                # Extract lat/lng data
                latlng_stream = None
                for stream in streams:
                    if stream.get("type") == "latlng":
                        latlng_stream = stream.get("data", [])
                        break

                if latlng_stream and len(latlng_stream) >= 2:
                    activity["_latlng"] = latlng_stream
                    downloaded.append(activity)

            except Exception as e:
                failed += 1

            progress.update(task, advance=1,
                            description=f"Downloaded {len(downloaded)}/{i+1}...")

            time.sleep(rate_limit)

    if failed > 0:
        console.log(f"  [yellow]Failed to download {failed} streams[/yellow]")

    console.log(f"  [green]✔[/green] Downloaded {len(downloaded)} GPS streams")
    return downloaded


# ═══ Track Processing ═══

def process_streams_to_tracks(activities_with_streams: list) -> gpd.GeoDataFrame:
    """
    Converts downloaded Strava GPS streams into track GeoDataFrame
    and merges with existing tracks.
    """
    console.log("[bold]Processing GPS streams into tracks...[/bold]")

    tracks_path = CONFIG.paths.processed_tracks
    tracks_path.parent.mkdir(parents=True, exist_ok=True)

    new_tracks = []
    for activity in activities_with_streams:
        latlng = activity.get("_latlng", [])
        if len(latlng) < 2:
            continue

        # Convert lat/lng pairs to (lon, lat) for Shapely
        coords = [(point[1], point[0]) for point in latlng]

        track = {
            "activity_id": f"strava_{activity['id']}",
            "source_file": f"strava_{activity['id']}",
            "geometry": LineString(coords),
            "start_time": activity.get("start_date_local", activity.get("start_date")),
            "point_count": len(coords),
            "activity_type": activity.get("type", "Run").lower(),
        }
        new_tracks.append(track)

    if not new_tracks:
        console.log("  No new tracks to process.")
        if tracks_path.exists():
            return gpd.read_file(str(tracks_path))
        return gpd.GeoDataFrame()

    console.log(f"  New tracks to add: {len(new_tracks)}")

    new_gdf = gpd.GeoDataFrame(new_tracks, crs="EPSG:4326")

    # Calculate track length
    new_gdf_proj = new_gdf.to_crs(CONFIG.project_crs)
    new_gdf["length_m"] = new_gdf_proj.geometry.length

    # Merge with existing tracks
    if tracks_path.exists():
        try:
            existing = gpd.read_file(str(tracks_path))
            # Ensure column compatibility
            for col in new_gdf.columns:
                if col not in existing.columns and col != "geometry":
                    existing[col] = ""
            for col in existing.columns:
                if col not in new_gdf.columns and col != "geometry":
                    new_gdf[col] = ""
            combined = pd.concat([existing, new_gdf], ignore_index=True)
        except Exception:
            combined = new_gdf
    else:
        combined = new_gdf

    # Deduplicate by activity_id
    before = len(combined)
    combined = combined.drop_duplicates(subset=["activity_id"], keep="first")
    combined = combined.reset_index(drop=True)
    after = len(combined)
    if before != after:
        console.log(f"  Deduplicated: {before} → {after}")

    combined.to_file(str(tracks_path), driver="GPKG", index=False)

    total_km = combined["length_m"].sum() / 1000
    console.log(f"  [green]✔[/green] Total tracks: {len(combined)} ({total_km:,.1f} km)")

    # Save summary
    summary = combined.drop(columns=["geometry"]).copy()
    summary["length_km"] = summary["length_m"] / 1000
    summary = summary.sort_values("start_time", ascending=False)
    csv_path = str(CONFIG.paths.track_summary).replace(".gpkg", ".csv")
    summary.to_csv(csv_path, index=False)

    # Return only the new tracks for incremental processing
    return new_gdf


# ═══ Main Sync Function ═══

def run_full_sync():
    """
    Runs the complete Strava sync process:
    1. Authenticate (OAuth2)
    2. Sync activity list
    3. Download GPS streams for new activities
    4. Process into tracks
    """
    console.log("[bold cyan]═══ Strava Sync ═══[/bold cyan]")

    # Step 1: Authenticate
    access_token = authenticate()

    # Step 2: Sync activity list
    activities = sync_activity_list(access_token)

    # Step 3: Download GPS streams
    new_with_streams = download_streams(access_token, activities)

    # Step 4: Process into tracks
    tracks = process_streams_to_tracks(new_with_streams)

    console.log("[bold cyan]═══ Strava Sync Complete ═══[/bold cyan]")

    return tracks
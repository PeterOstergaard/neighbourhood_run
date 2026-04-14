# src/neighbourhood_run/garmin_sync.py
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from garminconnect import Garmin
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
)

from .config import CONFIG, load_secrets, PROJECT_ROOT

console = Console()


# Path for caching the Garmin session token
SESSION_CACHE_PATH = PROJECT_ROOT / "data" / "raw" / "garmin" / ".session_cache"

def _authenticate() -> Garmin:
    """
    Authenticates with Garmin Connect.
    Uses a cached session token if available to avoid repeated logins.
    Falls back to full login if the cached session is expired.
    Includes pre-flight checks and user confirmation before attempting login.
    """
    from garminconnect.exceptions import (
        GarminConnectAuthenticationError,
        GarminConnectTooManyRequestsError,
        GarminConnectConnectionError,
    )

    secrets = load_secrets()

    # --- PRE-FLIGHT CHECKS ---
    console.log("[bold]Pre-flight credential checks...[/bold]")

    # Check 1: Placeholder credentials
    if secrets.email == "your.email@example.com" or secrets.password == "your-garmin-password":
        console.log("[bold red]ERROR: You have not updated your credentials in secrets.yaml![/bold red]")
        console.log("  Please edit 'secrets.yaml' with your real Garmin email and password.")
        raise ValueError("Placeholder credentials detected in secrets.yaml")

    # Check 2: Email format
    if "@" not in secrets.email:
        console.log(f"[bold red]ERROR: '{secrets.email}' does not look like a valid email.[/bold red]")
        raise ValueError("Invalid email format in secrets.yaml")

    # Check 3: Empty password
    if len(secrets.password.strip()) == 0:
        console.log("[bold red]ERROR: Password is empty in secrets.yaml![/bold red]")
        raise ValueError("Empty password in secrets.yaml")

    # Check 4: Password might have YAML issues
    raw_password = secrets.password
    if raw_password.startswith(" ") or raw_password.endswith(" "):
        console.log("[bold yellow]WARNING: Your password has leading or trailing spaces.[/bold yellow]")
        console.log("  This might be a YAML parsing issue.")
        console.log('  Make sure your password is wrapped in quotes in secrets.yaml:')
        console.log('  password: "your password here"')

    # --- CACHED SESSION: Try first, no confirmation needed ---
    SESSION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    client = Garmin(secrets.email, secrets.password)

    if SESSION_CACHE_PATH.exists():
        console.log("Attempting to use cached Garmin session...")
        try:
            with open(str(SESSION_CACHE_PATH), 'r', encoding='utf-8') as f:
                saved_session = json.load(f)
            client.login(saved_session)
            console.log("[green]✔[/green] Cached session is valid")
            return client
        except GarminConnectTooManyRequestsError:
            console.log("[bold red]Rate limited even with cached session.[/bold red]")
            console.log("  Wait 30-60 minutes before trying again.")
            raise
        except Exception as e:
            console.log(f"  [yellow]Cached session expired or invalid.[/yellow]")
            try:
                SESSION_CACHE_PATH.unlink()
            except Exception:
                pass

    # --- FULL LOGIN: Show credentials and ask for confirmation ---
    masked_email = secrets.email[:3] + "***" + secrets.email[secrets.email.index("@"):]
    password_hint = secrets.password[:2] + "*" * (len(secrets.password) - 4) + secrets.password[-2:]

    console.log("")
    console.log("[bold yellow]═══ Full Login Required ═══[/bold yellow]")
    console.log(f"  Email:    {masked_email}")
    console.log(f"  Password: {password_hint} ({len(secrets.password)} characters)")
    console.log("")
    console.log("[bold]This will attempt to log in to Garmin Connect.[/bold]")
    console.log("The library tries up to 4 login strategies internally.")
    console.log("If the password is wrong, ALL 4 attempts will fail and")
    console.log("you will be rate-limited for 30-60 minutes.")
    console.log("")

    user_input = input("Proceed with login? (yes/no): ").strip().lower()

    if user_input not in ("yes", "y"):
        console.log("[yellow]Login aborted by user.[/yellow]")
        console.log("  Please verify your credentials in 'secrets.yaml' and try again.")
        raise SystemExit("Login aborted by user")

    console.log("Performing full Garmin Connect login...")


    try:
        client.login()
        console.log("[green]✔[/green] Authentication successful")

        # Save the session token for future use
        session_data = client.session_data
        if session_data:
            with open(str(SESSION_CACHE_PATH), 'w', encoding='utf-8') as f:
                json.dump(session_data, f)
            console.log("  Session token cached for future use")

        return client

    except Exception as e:
        error_str = str(e).lower()
        error_type = type(e).__name__

        console.log("")

        # Check for rate limiting FIRST, regardless of exception type
        if "429" in error_str or "rate limit" in error_str or "too many" in error_str:
            console.log("[bold red]═══ RATE LIMITED ═══[/bold red]")
            console.log("Garmin has temporarily blocked login attempts.")
            console.log("")
            console.log("[bold]What to do:[/bold]")
            console.log("  1. [bold]Wait at least 2-3 hours[/bold] before trying again")
            console.log("     (60 minutes is sometimes not enough)")
            console.log("  2. Do NOT retry sooner — each attempt resets the timer")
            console.log("  3. Try logging into connect.garmin.com in your browser.")
            console.log("     If that works, it means the API rate limit is separate.")
            console.log("  4. While waiting, use manual GPX export instead:")
            console.log(f"     Place files in: {CONFIG.paths.raw_garmin}")
            console.log("     Then run: python parse_tracks.py")
            console.log("")
            console.log("  [bold]Alternative: Use Garmin bulk export[/bold]")
            console.log("     1. Go to https://www.garmin.com/en-US/account/datamanagement/")
            console.log("     2. Click 'Export Your Data'")
            console.log("     3. Garmin will email you a ZIP file")
            console.log("     4. Extract GPX files to the folder above")
            console.log("     5. Run: python parse_tracks.py")
            raise

        # Check for credential errors
        elif "credentials" in error_str or "password" in error_str or "unauthorized" in error_str or "403" in error_str:
            console.log("[bold red]═══ AUTHENTICATION FAILED ═══[/bold red]")
            console.log("Your email or password appears to be incorrect.")
            console.log("")
            console.log("[bold]What to check:[/bold]")
            console.log("  1. Open 'secrets.yaml' and verify your credentials")
            console.log("  2. Common password issues:")
            console.log("     - leading/trailing spaces")
            console.log("     - special characters not quoted properly")
            console.log('     - wrap password in double quotes: password: "p@ss!"')
            console.log("  3. Try logging into connect.garmin.com in your browser")
            console.log("     to confirm your credentials work")
            raise

        # Check for MFA
        elif "mfa" in error_str or "verification" in error_str:
            console.log("[bold red]═══ MFA REQUIRED ═══[/bold red]")
            console.log("Multi-factor authentication (MFA) is required.")
            console.log("")
            console.log("[bold]What to do:[/bold]")
            console.log("  MFA support is not yet implemented.")
            console.log("  Use manual GPX export from connect.garmin.com instead.")
            console.log(f"  Place files in: {CONFIG.paths.raw_garmin}")
            console.log("  Then run: python parse_tracks.py")
            raise

        # Check for connection errors
        elif "connection" in error_str or "timeout" in error_str or "connect" in error_str:
            console.log("[bold red]═══ CONNECTION ERROR ═══[/bold red]")
            console.log("Could not reach Garmin Connect servers.")
            console.log("")
            console.log("[bold]What to check:[/bold]")
            console.log("  1. Is your internet connection working?")
            console.log("  2. Can you reach connect.garmin.com in your browser?")
            console.log("  3. Is a firewall or VPN blocking the connection?")
            raise

        # Unknown error
        else:
            console.log("[bold red]═══ UNEXPECTED ERROR ═══[/bold red]")
            console.log(f"Error type: {error_type}")
            console.log(f"Error details: {e}")
            console.log("")
            console.log("[bold]What to try:[/bold]")
            console.log("  1. Check credentials in 'secrets.yaml'")
            console.log("  2. pip install --upgrade garminconnect")
            console.log("  3. Try again in a few minutes")
            console.log("  4. Use manual GPX export as fallback")
            raise
        
def _load_activity_list() -> list:
    """Loads the cached activity list from disk."""
    list_path = CONFIG.paths.garmin_activity_list
    if list_path.exists():
        with open(list_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def _save_activity_list(activities: list):
    """Saves the activity list to disk."""
    list_path = CONFIG.paths.garmin_activity_list
    list_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(list_path), 'w', encoding='utf-8') as f:
        json.dump(activities, f, indent=2, default=str)


def _get_downloaded_activity_ids() -> set:
    """Returns a set of activity IDs that have already been downloaded as GPX."""
    garmin_dir = CONFIG.paths.raw_garmin
    if not garmin_dir.exists():
        return set()
    # Each downloaded file is named {activity_id}.gpx
    return {int(f.stem) for f in garmin_dir.glob("*.gpx")}


def sync_activity_list(client: Garmin) -> list:
    """
    Phase 1: Downloads the full list of activity metadata from Garmin Connect.
    Only fetches activities newer than the most recent cached activity.
    Returns the complete, updated activity list.
    """
    console.log("[bold]Phase 1: Syncing activity metadata...[/bold]")

    cached = _load_activity_list()
    cached_ids = {a["activityId"] for a in cached}

    # Find the most recent cached activity date for incremental sync
    most_recent = None
    if cached:
        dates = [a.get("startTimeLocal", "") for a in cached if a.get("startTimeLocal")]
        if dates:
            most_recent = max(dates)
            console.log(f"  Most recent cached activity: {most_recent}")

    # Download activity list in batches
    batch_size = CONFIG.garmin.batch_size
    start = 0
    new_activities = []
    done = False

    console.log("  Downloading activity list from Garmin Connect...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching activities...", total=None)

        while not done:
            try:
                batch = client.get_activities(start, batch_size)
            except Exception as e:
                console.log(f"  [red]Error fetching batch at offset {start}:[/red] {e}")
                break

            if not batch:
                done = True
                break

            for activity in batch:
                aid = activity.get("activityId")
                if aid in cached_ids:
                    # We've reached activities we already have
                    done = True
                    break
                new_activities.append(activity)

            progress.update(task, advance=len(batch),
                            description=f"Fetched {start + len(batch)} activities...")
            start += batch_size

            # Small delay to avoid rate limiting
            time.sleep(0.5)

    if new_activities:
        console.log(f"  Found {len(new_activities)} new activities")
        # Prepend new activities to cached list (newest first)
        all_activities = new_activities + cached
    else:
        console.log(f"  No new activities found")
        all_activities = cached

    _save_activity_list(all_activities)
    console.log(f"  [green]✔[/green] Total cached activities: {len(all_activities)}")

    return all_activities


def filter_relevant_activities(activities: list) -> list:
    """
    Filters the activity list to only include:
    - Running activities
    - Activities starting within import_radius_km of home
    """
    console.log("[bold]Filtering relevant activities...[/bold]")

    import geopandas as gpd
    from shapely.geometry import Point

    # Load home location
    home_gdf = gpd.read_file(str(CONFIG.paths.processed_home))
    home_gdf_proj = home_gdf.to_crs(CONFIG.project_crs)
    home_point = home_gdf_proj.geometry.iloc[0]

    radius_m = CONFIG.garmin.import_radius_km * 1000
    allowed_types = {t.lower() for t in CONFIG.garmin.activity_types}

    relevant = []
    skipped_type = 0
    skipped_location = 0
    skipped_no_coords = 0

    for activity in activities:
        # Filter by activity type
        activity_type = activity.get("activityType", {})
        type_key = activity_type.get("typeKey", "").lower() if isinstance(activity_type, dict) else ""

        if type_key not in allowed_types:
            skipped_type += 1
            continue

        # Filter by start location
        start_lat = activity.get("startLatitude")
        start_lon = activity.get("startLongitude")

        if start_lat is None or start_lon is None:
            skipped_no_coords += 1
            continue

        # Project start point and check distance from home
        start_point = gpd.GeoSeries(
            [Point(start_lon, start_lat)], crs="EPSG:4326"
        ).to_crs(CONFIG.project_crs).iloc[0]

        distance = home_point.distance(start_point)

        if distance > radius_m:
            skipped_location += 1
            continue

        relevant.append(activity)

    console.log(f"  Total activities:        {len(activities)}")
    console.log(f"  Skipped (wrong type):    {skipped_type}")
    console.log(f"  Skipped (no coords):     {skipped_no_coords}")
    console.log(f"  Skipped (too far):       {skipped_location}")
    console.log(f"  [green]✔[/green] Relevant activities:     {len(relevant)}")

    return relevant


def download_gpx_files(client: Garmin, activities: list):
    """
    Phase 2: Downloads GPX files for relevant activities that haven't
    been downloaded yet. Implements rate limiting and progress tracking.
    """
    console.log("[bold]Phase 2: Downloading GPX files...[/bold]")

    garmin_dir = CONFIG.paths.raw_garmin
    garmin_dir.mkdir(parents=True, exist_ok=True)

    already_downloaded = _get_downloaded_activity_ids()
    to_download = [
        a for a in activities
        if a.get("activityId") not in already_downloaded
    ]

    if not to_download:
        console.log("  All relevant GPX files already downloaded.")
        return

    console.log(f"  Activities to download: {len(to_download)}")
    rate_limit = CONFIG.garmin.rate_limit_seconds
    failed = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Downloading 0/{len(to_download)}...",
            total=len(to_download)
        )

        for i, activity in enumerate(to_download):
            aid = activity.get("activityId")
            activity_name = activity.get("activityName", "Unknown")

            try:
                gpx_data = client.download_activity(
                    aid, dl_fmt=Garmin.ActivityDownloadFormat.GPX
                )

                output_file = garmin_dir / f"{aid}.gpx"
                with open(str(output_file), "wb") as f:
                    f.write(gpx_data)

            except Exception as e:
                failed.append({"id": aid, "name": activity_name, "error": str(e)})

            progress.update(
                task, advance=1,
                description=f"Downloading {i + 1}/{len(to_download)}..."
            )

            # Rate limiting
            if i < len(to_download) - 1:
                time.sleep(rate_limit)

    if failed:
        console.log(f"  [yellow]Failed to download {len(failed)} activities:[/yellow]")
        for f in failed[:5]:
            console.log(f"    - {f['id']}: {f['error']}")
        if len(failed) > 5:
            console.log(f"    ... and {len(failed) - 5} more")
    else:
        console.log(f"  [green]✔[/green] All GPX files downloaded successfully")


def run_full_sync():
    """
    Runs the complete Garmin sync process:
    1. Authenticate
    2. Sync activity metadata
    3. Filter relevant activities
    4. Download GPX files for relevant activities
    Returns the list of relevant activities.
    """
    console.log("[bold cyan]═══ Garmin Sync ═══[/bold cyan]")

    client = _authenticate()
    all_activities = sync_activity_list(client)
    relevant = filter_relevant_activities(all_activities)
    download_gpx_files(client, relevant)

    console.log("[bold cyan]═══ Garmin Sync Complete ═══[/bold cyan]")

    return relevant
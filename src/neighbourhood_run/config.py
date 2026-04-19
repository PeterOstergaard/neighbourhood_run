# src/neighbourhood_run/config.py
from pathlib import Path
import yaml
from pydantic import BaseModel
from typing import Optional, List

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class HomeConfig(BaseModel):
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AreaConfig(BaseModel):
    postalcode: str
    country: str
    buffer_meters: int = 200


class GarminConfig(BaseModel):
    import_radius_km: float = 10.0
    activity_types: List[str] = ["running"]
    rate_limit_seconds: float = 2.0
    batch_size: int = 50


class StravaConfig(BaseModel):
    activity_types: List[str] = ["Run", "TrailRun"]
    rate_limit_seconds: float = 1.5
    per_page: int = 100


class RoutingConfig(BaseModel):
    min_distance_km: float = 10.0
    max_distance_km: float = 15.0


class PathsConfig(BaseModel):
    raw_boundary: str
    processed_home: str
    processed_network: str
    manual_exclusions: str
    map_view_html: str
    raw_garmin: str
    garmin_activity_list: str
    processed_tracks: str
    track_summary: str
    planned_routes: str
    strava_token: str
    strava_activity_list: str


class AppConfig(BaseModel):
    user_id: str
    project_crs: str
    home: HomeConfig
    area: AreaConfig
    garmin: GarminConfig
    strava: StravaConfig
    routing: RoutingConfig
    paths: PathsConfig


class GarminSecretsConfig(BaseModel):
    email: str
    password: str


class StravaSecretsConfig(BaseModel):
    client_id: str
    client_secret: str


class SecretsConfig(BaseModel):
    garmin: Optional[GarminSecretsConfig] = None
    strava: Optional[StravaSecretsConfig] = None


def load_config(config_path: str = "data/manual/config.yaml") -> AppConfig:
    """Loads and validates the application configuration from a YAML file."""
    absolute_config_path = PROJECT_ROOT / config_path
    with open(absolute_config_path, 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)

    validated_config = AppConfig(**config_data)

    for field_name, path_str in validated_config.paths:
        setattr(validated_config.paths, field_name, PROJECT_ROOT / path_str)

    return validated_config


def load_secrets(secrets_path: str = "secrets.yaml") -> SecretsConfig:
    """Loads all credentials from the secrets file."""
    absolute_path = PROJECT_ROOT / secrets_path
    if not absolute_path.exists():
        raise FileNotFoundError(
            f"Secrets file not found at '{absolute_path}'. "
            f"Please create it with your credentials."
        )
    with open(absolute_path, 'r', encoding='utf-8') as f:
        secrets_data = yaml.safe_load(f)

    return SecretsConfig(**secrets_data)


try:
    CONFIG = load_config()
except FileNotFoundError:
    print(f"ERROR: config.yaml not found at: {PROJECT_ROOT / 'data/manual/config.yaml'}")
    exit(1)
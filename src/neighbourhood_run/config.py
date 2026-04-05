# src/neighbourhood_run/config.py
from pathlib import Path
import yaml
from pydantic import BaseModel
from typing import Union, Dict, Any

# 1. Define the absolute path to the project's root directory.
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

class HomeConfig(BaseModel):
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None

class AreaConfig(BaseModel):
    query: Union[str, Dict[str, Any]]
    buffer_meters: int = 50

class PathsConfig(BaseModel):
    raw_boundary: str
    processed_home: str
    processed_network: str
    manual_exclusions: str
    map_view_html: str

class AppConfig(BaseModel):
    user_id: str
    project_crs: str
    home: HomeConfig
    area: AreaConfig
    paths: PathsConfig

def load_config(config_path: str = "data/manual/config.yaml") -> AppConfig:
    """Loads and validates the application configuration from a YAML file."""
    # 2. Use the absolute path to load the config file
    absolute_config_path = PROJECT_ROOT / config_path
    with open(absolute_config_path, 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
    
    validated_config = AppConfig(**config_data)

    # 3. Convert all paths in the config to be absolute paths
    for field_name, path_str in validated_config.paths:
        setattr(validated_config.paths, field_name, PROJECT_ROOT / path_str)
        
    return validated_config

# Load config globally for easy access in other modules
try:
    CONFIG = load_config()
except FileNotFoundError:
    print(f"ERROR: config.yaml not found at expected location: {PROJECT_ROOT / 'data/manual/config.yaml'}")
    exit(1)
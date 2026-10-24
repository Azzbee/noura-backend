"""
Configuration for Noura Safe City Walks Backend
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

_DATA_DIR = Path(__file__).resolve().parent / "data"


class Settings(BaseSettings):
    """Application settings"""

    # API Configuration
    API_TITLE: str = "Noura Safe City Walks API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "Safety-aware routing and location services for Paris"

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # CORS Configuration
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8100",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "capacitor://localhost",
        "ionic://localhost",
    ]

    # OpenStreetMap Configuration
    OVERPASS_API_URL: str = "https://overpass-api.de/api/interpreter"
    OVERPASS_TIMEOUT: int = 300  # seconds; the full Paris network is large
    USE_LIVE_OSM_ZONES: bool = True  # add live OSM features to curated zones

    # Data files
    STREET_CACHE_PATH: str = str(_DATA_DIR / "paris_streets.json.gz")
    STREET_CACHE_MAX_AGE: int = 7 * 86400  # refresh the street cache weekly
    CURATED_ZONES_PATH: str = str(_DATA_DIR / "paris_safety_zones.json")
    NOMINATIM_API_URL: str = "https://nominatim.openstreetmap.org"

    # Caching
    CACHE_TTL: int = 3600  # 1 hour in seconds

    # Safety Scoring Weights
    SAFETY_WEIGHTS: dict = {
        "police_proximity": 0.2,
        "lighting": 0.2,
        "foot_traffic": 0.15,
        "public_transport": 0.15,
        "hospitals": 0.1,
        "time_factor": 0.2,
    }

    # Factor values for a street with no nearby safety features (0-1).
    # Paris lights its public streets, so unknown lighting defaults to lit;
    # an OSM lit=no tag still halves it. Originally 0.3/0.2/0.3/0.2/0.3, which
    # rated the safest route in central Paris at night around 17/100.
    BASE_SCORES: dict = {
        "lighting": 0.3,
        "police": 0.2,
        "activity": 0.3,
        "medical": 0.2,
        "transport": 0.3,
    }

    # Paris Bounding Box
    PARIS_BOUNDS: dict = {
        "north": 48.9022,
        "south": 48.8155,
        "east": 2.4699,
        "west": 2.2241,
    }

    # Graph Building
    GRAPH_REBUILD_INTERVAL: int = 86400  # 24 hours in seconds
    MAX_GRAPH_NODES: int = 100000

    # Routing Configuration
    DEFAULT_WALKING_SPEED: float = 1.4  # meters per second
    MAX_ROUTE_DISTANCE: float = 10000  # 10km maximum route distance
    # How strongly the safest route avoids less safe streets: at
    # safety_weight=1 the least safe streets cost (1 + gain) x their length.
    SAFETY_DETOUR_GAIN: float = 2.5
    SAFETY_RADIUS_SEARCH: float = 500  # meters to search for safety features

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
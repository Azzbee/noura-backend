"""
Configuration for Noura Safe City Walks Backend
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings


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
        "capacitor://localhost",
        "ionic://localhost",
    ]

    # OpenStreetMap Configuration
    OVERPASS_API_URL: str = "https://overpass-api.de/api/interpreter"
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
    SAFETY_RADIUS_SEARCH: float = 500  # meters to search for safety features

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
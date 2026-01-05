"""
Pydantic models for API request/response schemas
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from enum import Enum


class Coordinates(BaseModel):
    """Geographic coordinates"""
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class TimeOfDay(str, Enum):
    """Time of day for safety scoring"""
    day = "day"
    evening = "evening"
    night = "night"
    late_night = "late_night"


class SafetyZoneType(str, Enum):
    """Types of safety zones"""
    well_lit = "well_lit"
    busy_street = "busy_street"
    police_station = "police_station"
    hospital = "hospital"
    metro_station = "metro_station"
    pharmacy = "pharmacy"
    open_24h = "open_24h"
    safe_area = "safe_area"
    caution_area = "caution_area"
    danger_zone = "danger_zone"


class SafetyZone(BaseModel):
    """Safety zone information"""
    id: str
    type: SafetyZoneType
    center: List[float] = Field(..., min_items=2, max_items=2)
    radius: float = Field(..., gt=0)
    name: Optional[str] = None
    safety_score: Optional[float] = Field(None, ge=0, le=100)
    time_relevance: Literal["always", "day_only", "night_only", "late_night"] = "always"
    source: str = "OSM"


class SafetyBreakdown(BaseModel):
    """Detailed safety score breakdown"""
    lighting: float = Field(..., ge=0, le=1)
    road_type: float = Field(..., ge=0, le=1)
    activity: float = Field(..., ge=0, le=1)
    time_factor: float = Field(..., ge=0, le=1)
    police_proximity: Optional[float] = Field(None, ge=0, le=1)
    cctv_coverage: Optional[float] = Field(None, ge=0, le=1)
    safe_landmarks: Optional[float] = Field(None, ge=0, le=1)


class SafetyPreferences(BaseModel):
    """User preferences for route safety"""
    lighting: int = Field(3, ge=1, le=5)
    police_stations: int = Field(3, ge=1, le=5)
    busy_areas: int = Field(3, ge=1, le=5)
    cctv_coverage: int = Field(2, ge=1, le=5)
    safe_landmarks: int = Field(3, ge=1, le=5)


class Route(BaseModel):
    """Route information"""
    route_id: str
    geometry: List[List[float]] = Field(..., description="List of [lat, lng] coordinates")
    distance_m: float = Field(..., gt=0)
    duration_s: float = Field(..., gt=0)
    safety_score: float = Field(..., ge=0, le=100)
    safety_breakdown: Optional[SafetyBreakdown] = None
    warnings: List[str] = []


class RouteRequest(BaseModel):
    """Route calculation request"""
    start: Coordinates
    end: Coordinates
    safety_weight: float = Field(0.5, ge=0, le=1, description="0=fastest, 1=safest")
    time_of_day: TimeOfDay = TimeOfDay.day
    preferences: Optional[SafetyPreferences] = None
    avoid_areas: Optional[List[Dict[str, float]]] = None


class RouteComparisonRequest(BaseModel):
    """Route comparison request"""
    start: Coordinates
    end: Coordinates
    time_of_day: TimeOfDay = TimeOfDay.day
    preferences: Optional[SafetyPreferences] = None


class RouteComparisonResult(BaseModel):
    """Route comparison result"""
    fastest: Route
    safest: Route
    balanced: Route
    comparison: Dict[str, Any]


class SafetyZonesRequest(BaseModel):
    """Request for safety zones around a location"""
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radius: float = Field(500, gt=0, le=5000, description="Search radius in meters")


class SafetyZonesResponse(BaseModel):
    """Response containing safety zones"""
    zones: List[SafetyZone]
    cached: bool = False
    timestamp: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    graph_loaded: bool
    node_count: int
    edge_count: int
    version: str
    uptime_seconds: float


class ErrorResponse(BaseModel):
    """Error response"""
    detail: str
    error_code: Optional[str] = None
    timestamp: str
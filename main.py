"""
Main FastAPI application for Noura Safe City Walks Backend
"""

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from config import settings
from models import (
    RouteRequest,
    RouteComparisonRequest,
    SafetyZonesRequest,
    SafetyZonesResponse,
    HealthResponse,
    ErrorResponse,
)
from services import OSMFetcher, SafetyScorer, RouteCalculator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global services
osm_fetcher = None
route_calculator = None
safety_scorer = None
app_start_time = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global osm_fetcher, route_calculator, safety_scorer, app_start_time

    # Startup
    logger.info("Starting Noura Backend...")
    app_start_time = time.time()

    # Initialize services
    osm_fetcher = OSMFetcher()
    route_calculator = RouteCalculator()
    safety_scorer = SafetyScorer()

    # Load Paris street network
    logger.info("Loading Paris street network...")
    try:
        bounds = (
            settings.PARIS_BOUNDS["south"],
            settings.PARIS_BOUNDS["west"],
            settings.PARIS_BOUNDS["north"],
            settings.PARIS_BOUNDS["east"],
        )
        async with osm_fetcher as fetcher:
            street_data = await fetcher.get_street_network(bounds)
            route_calculator.build_graph_from_osm(street_data)
        logger.info("Street network loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load street network: {e}")
        # Continue without graph for safety zones API

    yield

    # Shutdown
    logger.info("Shutting down Noura Backend...")
    if osm_fetcher and hasattr(osm_fetcher, "client"):
        await osm_fetcher.client.aclose()


# Create FastAPI app
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Check API health and status"""
    uptime = time.time() - app_start_time if app_start_time else 0

    return HealthResponse(
        # "ok" is what the app's RouteServiceStatus badge expects
        status="ok" if route_calculator.graph_loaded else "degraded",
        graph_loaded=route_calculator.graph_loaded,
        node_count=route_calculator.node_count,
        edge_count=route_calculator.edge_count,
        version=settings.API_VERSION,
        uptime_seconds=uptime,
    )


# Safety zones endpoint
@app.get("/api/safety-zones", response_model=SafetyZonesResponse)
async def get_safety_zones(lat: float, lng: float, radius: float = 500):
    """Get safety zones around a location"""
    try:
        # Validate coordinates
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coordinates",
            )

        # Validate radius
        if radius <= 0 or radius > 5000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Radius must be between 1 and 5000 meters",
            )

        # Fetch safety zones
        async with OSMFetcher() as fetcher:
            zones = await fetcher.fetch_all_safety_zones(lat, lng, radius)

        return SafetyZonesResponse(
            zones=zones,
            cached=False,
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Error fetching safety zones: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Route calculation endpoint
@app.post("/api/route")
async def calculate_route(request: RouteRequest):
    """Calculate a safety-aware route"""
    try:
        # Check if graph is loaded
        if not route_calculator.graph_loaded:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Routing service is not available. Graph not loaded.",
            )

        # Validate coordinates
        if (
            not (-90 <= request.start.lat <= 90)
            or not (-180 <= request.start.lng <= 180)
            or not (-90 <= request.end.lat <= 90)
            or not (-180 <= request.end.lng <= 180)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coordinates",
            )

        # Check distance
        distance = safety_scorer.calculate_distance(
            request.start.lat,
            request.start.lng,
            request.end.lat,
            request.end.lng,
        )

        if distance > settings.MAX_ROUTE_DISTANCE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Route distance exceeds maximum of {settings.MAX_ROUTE_DISTANCE}m",
            )

        # Fetch safety zones for the area
        center_lat = (request.start.lat + request.end.lat) / 2
        center_lng = (request.start.lng + request.end.lng) / 2
        search_radius = min(distance * 1.5, 5000)

        async with OSMFetcher() as fetcher:
            safety_zones = await fetcher.fetch_all_safety_zones(
                center_lat, center_lng, search_radius
            )

        # Calculate route
        route = await route_calculator.calculate_route(request, safety_zones)

        return route

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error calculating route: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Route comparison endpoint
@app.post("/api/route/compare")
async def compare_routes(request: RouteComparisonRequest):
    """Compare different route options"""
    try:
        # Check if graph is loaded
        if not route_calculator.graph_loaded:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Routing service is not available. Graph not loaded.",
            )

        # Validate coordinates
        if (
            not (-90 <= request.start.lat <= 90)
            or not (-180 <= request.start.lng <= 180)
            or not (-90 <= request.end.lat <= 90)
            or not (-180 <= request.end.lng <= 180)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coordinates",
            )

        # Fetch safety zones
        center_lat = (request.start.lat + request.end.lat) / 2
        center_lng = (request.start.lng + request.end.lng) / 2

        distance = safety_scorer.calculate_distance(
            request.start.lat,
            request.start.lng,
            request.end.lat,
            request.end.lng,
        )
        search_radius = min(distance * 1.5, 5000)

        async with OSMFetcher() as fetcher:
            safety_zones = await fetcher.fetch_all_safety_zones(
                center_lat, center_lng, search_radius
            )

        # Calculate alternative routes
        comparison = await run_in_threadpool(
            route_calculator.calculate_alternative_routes,
            request.start,
            request.end,
            safety_zones,
            request.time_of_day,
            request.preferences,
        )

        return comparison

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error comparing routes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Error handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom error handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timestamp": datetime.now().isoformat(),
        },
    )


# Root endpoint
@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": settings.API_TITLE,
        "version": settings.API_VERSION,
        "description": settings.API_DESCRIPTION,
        "endpoints": {
            "health": "/api/health",
            "safety_zones": "/api/safety-zones",
            "route": "/api/route",
            "route_compare": "/api/route/compare",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
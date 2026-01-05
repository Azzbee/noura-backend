"""
OpenStreetMap data fetcher service
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
import httpx
from cachetools import TTLCache

from config import settings
from models import SafetyZone, SafetyZoneType

logger = logging.getLogger(__name__)


class OSMFetcher:
    """Service for fetching OpenStreetMap data"""

    def __init__(self):
        self.overpass_url = settings.OVERPASS_API_URL
        self.cache = TTLCache(maxsize=100, ttl=settings.CACHE_TTL)
        self.client = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def fetch_overpass_data(self, query: str) -> List[Dict[str, Any]]:
        """Execute an Overpass API query"""
        try:
            response = await self.client.post(
                self.overpass_url,
                data={"data": query},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("elements", [])
        except Exception as e:
            logger.error(f"Overpass API error: {e}")
            return []

    async def fetch_police_stations(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch police stations within radius"""
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="police"](around:{radius},{lat},{lng});
          way["amenity"="police"](around:{radius},{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                zones.append(
                    SafetyZone(
                        id=f"police-{el['id']}",
                        type=SafetyZoneType.police_station,
                        center=[center_lat, center_lng],
                        radius=150,
                        name=el.get("tags", {}).get("name", "Police Station"),
                        time_relevance="always",
                    )
                )

        # If no results within radius, fetch closest
        if not zones and radius == 500:
            return await self.fetch_police_stations(lat, lng, 5000)

        return zones

    async def fetch_hospitals(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch hospitals within radius"""
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="hospital"](around:{radius},{lat},{lng});
          way["amenity"="hospital"](around:{radius},{lat},{lng});
          node["healthcare"="hospital"](around:{radius},{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                zones.append(
                    SafetyZone(
                        id=f"hospital-{el['id']}",
                        type=SafetyZoneType.hospital,
                        center=[center_lat, center_lng],
                        radius=200,
                        name=el.get("tags", {}).get("name", "Hospital"),
                        time_relevance="always",
                    )
                )

        if not zones and radius == 500:
            return await self.fetch_hospitals(lat, lng, 5000)

        return zones

    async def fetch_metro_stations(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch metro stations within radius - no deduplication"""
        query = f"""
        [out:json][timeout:25];
        (
          node["railway"="station"](around:{radius},{lat},{lng});
          node["railway"="subway_entrance"](around:{radius},{lat},{lng});
          way["railway"="station"](around:{radius},{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                name = el.get("tags", {}).get("name", "Metro")
                # Clean the name
                for prefix in ["Métro ", "Metro ", "Station ", "Gare "]:
                    if name.startswith(prefix):
                        name = name[len(prefix) :].strip()

                zones.append(
                    SafetyZone(
                        id=f"metro-{el['id']}",
                        type=SafetyZoneType.metro_station,
                        center=[center_lat, center_lng],
                        radius=100,
                        name=name,
                        time_relevance="always",
                    )
                )

        if not zones and radius == 500:
            return await self.fetch_metro_stations(lat, lng, 5000)

        return zones

    async def fetch_pharmacies(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch pharmacies within radius"""
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="pharmacy"](around:{radius},{lat},{lng});
          way["amenity"="pharmacy"](around:{radius},{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                opening_hours = el.get("tags", {}).get("opening_hours", "")
                time_relevance = "always" if "24/7" in opening_hours else "day_only"

                zones.append(
                    SafetyZone(
                        id=f"pharmacy-{el['id']}",
                        type=SafetyZoneType.pharmacy,
                        center=[center_lat, center_lng],
                        radius=100,
                        name=el.get("tags", {}).get("name", "Pharmacy"),
                        time_relevance=time_relevance,
                    )
                )

        return zones

    async def fetch_24h_services(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch 24-hour services within radius"""
        query = f"""
        [out:json][timeout:25];
        (
          node["opening_hours"~"24/7"](around:{radius},{lat},{lng});
          way["opening_hours"~"24/7"](around:{radius},{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                zones.append(
                    SafetyZone(
                        id=f"24h-{el['id']}",
                        type=SafetyZoneType.open_24h,
                        center=[center_lat, center_lng],
                        radius=100,
                        name=el.get("tags", {}).get("name", "24 Hour Service"),
                        time_relevance="always",
                    )
                )

        return zones

    async def fetch_well_lit_areas(
        self, lat: float, lng: float
    ) -> List[SafetyZone]:
        """Fetch well-lit streets"""
        query = f"""
        [out:json][timeout:25];
        (
          way["highway"]["lit"="yes"](around:1500,{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center = el.get("center", {})
            if center.get("lat") and center.get("lon"):
                zones.append(
                    SafetyZone(
                        id=f"lit-{el['id']}",
                        type=SafetyZoneType.well_lit,
                        center=[center["lat"], center["lon"]],
                        radius=50,
                        name=el.get("tags", {}).get("name", "Well-lit Street"),
                        time_relevance="night_only",
                    )
                )

        return zones

    async def fetch_busy_areas(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch busy commercial areas"""
        query = f"""
        [out:json][timeout:25];
        (
          way["highway"~"pedestrian|shopping"](around:{radius},{lat},{lng});
          node["shop"](around:{radius},{lat},{lng});
          node["amenity"~"restaurant|cafe|bar"](around:{radius},{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []
        processed = set()

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                # Simple deduplication for busy areas
                coord_key = f"{round(center_lat, 4)},{round(center_lng, 4)}"
                if coord_key not in processed:
                    processed.add(coord_key)
                    zones.append(
                        SafetyZone(
                            id=f"busy-{el['id']}",
                            type=SafetyZoneType.busy_street,
                            center=[center_lat, center_lng],
                            radius=80,
                            name=el.get("tags", {}).get("name", "Busy Area"),
                            time_relevance="always",
                        )
                    )

        return zones

    async def fetch_danger_zones(self, lat: float, lng: float) -> List[SafetyZone]:
        """Fetch potential danger zones - 20km radius"""
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"~"nightclub|casino"](around:20000,{lat},{lng});
          way["amenity"~"nightclub|casino"](around:20000,{lat},{lng});
          way["landuse"="construction"](around:20000,{lat},{lng});
          way["building"="ruins"](around:20000,{lat},{lng});
        );
        out center;
        """

        elements = await self.fetch_overpass_data(query)
        zones = []

        for el in elements:
            center_lat = el.get("lat") or (el.get("center", {}).get("lat"))
            center_lng = el.get("lon") or (el.get("center", {}).get("lon"))

            if center_lat and center_lng:
                tags = el.get("tags", {})
                zone_type = SafetyZoneType.danger_zone
                time_relevance = "late_night"

                if tags.get("amenity") in ["nightclub", "casino"]:
                    zone_type = SafetyZoneType.caution_area
                    name = tags.get("name", "Nightlife Area")
                elif tags.get("landuse") == "construction":
                    name = "Construction Site"
                    time_relevance = "always"
                else:
                    name = "Caution Area"

                zones.append(
                    SafetyZone(
                        id=f"danger-{el['id']}",
                        type=zone_type,
                        center=[center_lat, center_lng],
                        radius=200,
                        name=name,
                        time_relevance=time_relevance,
                    )
                )

        return zones

    async def fetch_all_safety_zones(
        self, lat: float, lng: float, radius: float = 500
    ) -> List[SafetyZone]:
        """Fetch all safety zones around a location"""
        cache_key = f"zones_{lat:.4f}_{lng:.4f}_{radius}"

        if cache_key in self.cache:
            logger.info(f"Returning cached zones for {cache_key}")
            return self.cache[cache_key]

        # Fetch all zone types in parallel
        tasks = [
            self.fetch_police_stations(lat, lng, radius),
            self.fetch_hospitals(lat, lng, radius),
            self.fetch_metro_stations(lat, lng, radius),
            self.fetch_pharmacies(lat, lng, radius),
            self.fetch_24h_services(lat, lng, radius),
            self.fetch_well_lit_areas(lat, lng),
            self.fetch_busy_areas(lat, lng, radius),
            self.fetch_danger_zones(lat, lng),  # Always 20km
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_zones = []
        for result in results:
            if isinstance(result, list):
                all_zones.extend(result)
            else:
                logger.error(f"Error fetching zones: {result}")

        # Cache the results
        self.cache[cache_key] = all_zones

        logger.info(f"Fetched {len(all_zones)} safety zones for {lat}, {lng}")
        return all_zones

    async def get_street_network(
        self, bounds: Tuple[float, float, float, float]
    ) -> Dict[str, Any]:
        """Fetch street network for routing"""
        south, west, north, east = bounds

        query = f"""
        [out:json][timeout:60];
        (
          way["highway"~"primary|secondary|tertiary|residential|pedestrian|footway|path"]
            ({south},{west},{north},{east});
        );
        out geom;
        """

        elements = await self.fetch_overpass_data(query)
        return {"elements": elements}
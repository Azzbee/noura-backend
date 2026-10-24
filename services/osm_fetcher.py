"""
OpenStreetMap data fetcher service
"""

import asyncio
import gzip
import json
import logging
import time
from pathlib import Path
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
        self.client = httpx.AsyncClient(timeout=settings.OVERPASS_TIMEOUT + 30)

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
        """All safety zones around a location: the curated Paris zones plus
        live OpenStreetMap features.

        Everything comes from ONE Overpass query. The previous version sent
        eight queries per request (in parallel, so Overpass answered most with
        HTTP 429), one of them over a 20 km radius."""
        radius = max(300.0, min(float(radius), 5000.0))
        cache_key = f"zones_{lat:.3f}_{lng:.3f}_{int(radius // 250)}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        live: List[SafetyZone] = []
        if settings.USE_LIVE_OSM_ZONES:
            try:
                live = await self._fetch_live_zones(lat, lng, radius)
            except Exception as e:  # keep routing with curated data
                logger.error(f"Error fetching live zones: {e}")

        all_zones = load_curated_zones() + live
        self.cache[cache_key] = all_zones
        logger.info(
            f"Using {len(all_zones)} safety zones around {lat:.4f},{lng:.4f} "
            f"({len(live)} live from OSM)"
        )
        return all_zones

    async def _fetch_live_zones(self, lat: float, lng: float, radius: float) -> List[SafetyZone]:
        r = int(radius)
        a = f"(around:{r},{lat},{lng})"
        query = f"""
        [out:json][timeout:60];
        (
          nwr["amenity"="police"]{a};
          nwr["amenity"="hospital"]{a};
          nwr["healthcare"="hospital"]{a};
          node["railway"="station"]{a};
          node["railway"="subway_entrance"]{a};
          nwr["amenity"="pharmacy"]{a};
          node["opening_hours"="24/7"]{a};
          node["amenity"~"^(nightclub|casino)$"]{a};
          way["landuse"="construction"]{a};
        );
        out center tags;
        """
        elements = await self.fetch_overpass_data(query)
        zones: List[SafetyZone] = []
        seen = set()
        for el in elements:
            z = self._classify(el)
            if z is None:
                continue
            key = (z.type, round(z.center[0], 4), round(z.center[1], 4))
            if key in seen:
                continue
            seen.add(key)
            zones.append(z)
        return zones

    @staticmethod
    def _classify(el: Dict[str, Any]) -> Optional[SafetyZone]:
        tags = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            return None
        oid = f"{el.get('type', 'n')[0]}{el['id']}"
        amenity = tags.get("amenity")
        name = tags.get("name")

        def zone(prefix, ztype, radius, default_name, when="always"):
            return SafetyZone(
                id=f"{prefix}-{oid}",
                type=ztype,
                center=[lat, lon],
                radius=radius,
                name=name or default_name,
                time_relevance=when,
            )

        if amenity == "police":
            return zone("police", SafetyZoneType.police_station, 150, "Police Station")
        if amenity == "hospital" or tags.get("healthcare") == "hospital":
            return zone("hospital", SafetyZoneType.hospital, 200, "Hospital")
        if tags.get("railway") in ("station", "subway_entrance"):
            z = zone("metro", SafetyZoneType.metro_station, 100, "Metro")
            for prefix in ("Métro ", "Metro ", "Station ", "Gare "):
                if z.name.startswith(prefix):
                    z.name = z.name[len(prefix):].strip()
            return z
        if amenity == "pharmacy":
            hours = tags.get("opening_hours", "")
            return zone("pharmacy", SafetyZoneType.pharmacy, 100, "Pharmacy",
                        "always" if "24/7" in hours else "day_only")
        if amenity in ("nightclub", "casino"):
            return zone("danger", SafetyZoneType.caution_area, 200, "Nightlife Area", "late_night")
        if tags.get("landuse") == "construction":
            return zone("danger", SafetyZoneType.danger_zone, 200, "Construction Site")
        if tags.get("opening_hours") == "24/7":
            return zone("24h", SafetyZoneType.open_24h, 100, "24 Hour Service")
        return None

    async def get_street_network(
        self, bounds: Tuple[float, float, float, float]
    ) -> Dict[str, Any]:
        """Walking street network for routing, cached on disk.

        The whole of Paris is a large download, so it is fetched once and
        stored gzipped in data/ (see scripts/fetch_street_network.py)."""
        cache = Path(settings.STREET_CACHE_PATH)
        if cache.exists() and time.time() - cache.stat().st_mtime < settings.STREET_CACHE_MAX_AGE:
            logger.info(f"Loading street network from {cache}")
            with gzip.open(cache, "rt", encoding="utf-8") as f:
                return json.load(f)

        south, west, north, east = bounds
        query = f"""
        [out:json][timeout:{settings.OVERPASS_TIMEOUT}][maxsize:1073741824];
        (
          way["highway"~"^(primary|secondary|tertiary|primary_link|secondary_link|tertiary_link|unclassified|residential|living_street|pedestrian|footway|path|steps|service|cycleway|track)$"]
            ({south},{west},{north},{east});
        );
        out geom;
        """

        elements = await self.fetch_overpass_data(query)
        data = {"elements": elements}
        if elements:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(cache, "wt", encoding="utf-8") as f:
                json.dump(data, f)
            logger.info(f"Cached {len(elements)} ways to {cache}")
        return data


_CURATED: Optional[List[SafetyZone]] = None


def load_curated_zones() -> List[SafetyZone]:
    """Hand-curated Paris safety zones (same list the app shows on the map):
    metro hubs, commissariats, hospitals, lit areas, caution and danger zones."""
    global _CURATED
    if _CURATED is None:
        path = Path(settings.CURATED_ZONES_PATH)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _CURATED = [SafetyZone(**z) for z in raw]
        except FileNotFoundError:
            logger.warning(f"Curated zones file not found: {path}")
            _CURATED = []
    return list(_CURATED)

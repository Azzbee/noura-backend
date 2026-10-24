"""
Route calculation service: safety-weighted A* over the OpenStreetMap
walking network of Paris.

How it works
------------
1. The street network (ways tagged highway=...) is turned into an undirected
   graph. Ways are joined at the OSM nodes they share, so the graph is a
   real connected network rather than a set of isolated streets.
2. For a request, only the part of the graph around the start and end
   (bounding box plus a margin) is used, which keeps routing fast.
3. Every street segment in that window gets a safety score from the
   SafetyScorer (police, hospitals, metro, lighting, activity, caution and
   danger zones, time of day, user preferences, plus the OSM lit tag and
   street type).
4. Each segment's score is ranked against the others in the area (risk 0-1)
   and edge cost = length x (1 + gain x risk x safety_weight). With
   safety_weight 0 this is the shortest path; at 1 a street in the least
   safe tier costs (1 + gain) times its length. A* with a straight-line
   heuristic (admissible, since cost >= length) finds the path.
"""

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from config import settings
from models import (
    Coordinates,
    Route,
    RouteComparisonResult,
    RouteRequest,
    SafetyBreakdown,
    SafetyPreferences,
    SafetyZone,
    TimeOfDay,
)
from services.safety_scorer import SafetyScorer

logger = logging.getLogger(__name__)

# How safe a street *type* feels to walk (0-1), from the OSM highway tag.
ROAD_TYPE_SCORE = {
    "pedestrian": 0.95,
    "living_street": 0.9,
    "primary": 0.85,
    "secondary": 0.85,
    "tertiary": 0.8,
    "primary_link": 0.8,
    "secondary_link": 0.8,
    "tertiary_link": 0.8,
    "residential": 0.7,
    "unclassified": 0.65,
    "footway": 0.7,
    "cycleway": 0.6,
    "service": 0.5,
    "steps": 0.5,
    "path": 0.35,
    "track": 0.3,
}

# Legacy per-type multiplier, kept for the "weight" attribute on edges.
ROAD_WEIGHT = {
    "footway": 0.8,
    "pedestrian": 0.9,
    "residential": 1.0,
    "tertiary": 1.2,
    "secondary": 1.5,
    "primary": 2.0,
    "path": 1.1,
    "cycleway": 0.9,
}

EARTH_R = 6371000.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RouteCalculator:
    """Safety-aware router over a NetworkX street graph"""

    def __init__(self):
        self.graph = nx.Graph()
        self.safety_scorer = SafetyScorer()
        self.graph_loaded = False
        self.node_count = 0
        self.edge_count = 0
        self._kdtree: Optional[cKDTree] = None
        self._kd_ids: Optional[np.ndarray] = None
        self._lat0 = 48.8566

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_graph_from_osm(self, osm_data: Dict[str, Any]):
        """Build the walking graph from an Overpass `out geom` response."""
        self.graph.clear()
        key_to_id: Dict[Any, int] = {}
        g = self.graph

        def node_for(key, lat, lon) -> int:
            nid = key_to_id.get(key)
            if nid is None:
                nid = len(key_to_id)
                key_to_id[key] = nid
                g.add_node(nid, lat=lat, lon=lon)
            return nid

        for element in osm_data.get("elements", []):
            if element.get("type") != "way" or not element.get("geometry"):
                continue
            tags = element.get("tags", {})
            if tags.get("foot") == "no" or tags.get("access") in ("private", "no"):
                continue

            highway = tags.get("highway", "residential")
            lit_tag = tags.get("lit")
            lit = 1 if lit_tag in ("yes", "24/7", "automatic") else (-1 if lit_tag == "no" else 0)
            geometry = element["geometry"]
            osm_nodes = element.get("nodes")
            use_ids = osm_nodes is not None and len(osm_nodes) == len(geometry)

            prev = None
            for i, pt in enumerate(geometry):
                if pt is None:
                    prev = None
                    continue
                lat, lon = pt["lat"], pt["lon"]
                # Ways are joined where they share an OSM node; fall back to
                # identical coordinates when node ids are not available.
                key = osm_nodes[i] if use_ids else (round(lat, 7), round(lon, 7))
                nid = node_for(key, lat, lon)
                if prev is not None and prev != nid:
                    a, b = g.nodes[prev], g.nodes[nid]
                    dist = _haversine(a["lat"], a["lon"], b["lat"], b["lon"])
                    if not g.has_edge(prev, nid) or g[prev][nid]["distance"] > dist:
                        g.add_edge(
                            prev,
                            nid,
                            distance=dist,
                            weight=dist * ROAD_WEIGHT.get(highway, 1.5),
                            highway_type=highway,
                            lit=lit,
                            road_type=ROAD_TYPE_SCORE.get(highway, 0.6),
                            name=tags.get("name"),
                        )
                prev = nid

        # Keep the largest connected component so every snapped point can reach
        # every other one.
        if g.number_of_nodes():
            largest = max(nx.connected_components(g), key=len)
            g.remove_nodes_from([n for n in list(g.nodes) if n not in largest])

        self.node_count = g.number_of_nodes()
        self.edge_count = g.number_of_edges()
        self.graph_loaded = self.node_count > 0

        ids = np.fromiter(g.nodes, dtype=np.int64, count=self.node_count)
        lats = np.array([g.nodes[n]["lat"] for n in ids])
        lons = np.array([g.nodes[n]["lon"] for n in ids])
        if self.node_count:
            self._lat0 = float(lats.mean())
        self._kd_ids = ids
        self._kdtree = cKDTree(self._project(lats, lons)) if self.node_count else None

        logger.info(f"Graph built with {self.node_count} nodes and {self.edge_count} edges")

    def _project(self, lats, lons) -> np.ndarray:
        """Equirectangular projection to metres around the city centre."""
        k = math.cos(math.radians(self._lat0))
        return np.column_stack(
            (np.radians(lons) * EARTH_R * k, np.radians(lats) * EARTH_R)
        )

    def find_nearest_node(self, lat: float, lon: float, max_distance: float = 1000):
        """Nearest graph node to a coordinate (within max_distance metres)."""
        if not self.graph_loaded or self._kdtree is None:
            return None
        dist, idx = self._kdtree.query(self._project(np.array([lat]), np.array([lon]))[0])
        return int(self._kd_ids[idx]) if dist <= max_distance else None

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _window(self, start_node: int, end_node: int) -> nx.Graph:
        """Sub-graph around the trip: bounding box + margin."""
        a, b = self.graph.nodes[start_node], self.graph.nodes[end_node]
        straight = _haversine(a["lat"], a["lon"], b["lat"], b["lon"])
        margin_m = max(500.0, 0.45 * straight)
        dlat = margin_m / 111_320.0
        dlon = margin_m / (111_320.0 * math.cos(math.radians(self._lat0)))
        s, n = min(a["lat"], b["lat"]) - dlat, max(a["lat"], b["lat"]) + dlat
        w, e = min(a["lon"], b["lon"]) - dlon, max(a["lon"], b["lon"]) + dlon
        nodes = [
            nid
            for nid, d in self.graph.nodes(data=True)
            if s <= d["lat"] <= n and w <= d["lon"] <= e
        ]
        return self.graph.subgraph(nodes)

    def _score_edges(
        self,
        sub: nx.Graph,
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
        preferences: Optional[SafetyPreferences],
    ) -> Dict[Tuple[int, int], Dict[str, float]]:
        edges = list(sub.edges(data=True))
        if not edges:
            return {}
        nodes = self.graph.nodes
        mid_lat = np.array([(nodes[u]["lat"] + nodes[v]["lat"]) / 2 for u, v, _ in edges])
        mid_lon = np.array([(nodes[u]["lon"] + nodes[v]["lon"]) / 2 for u, v, _ in edges])
        lit = np.array([d.get("lit", 0) for _, _, d in edges])
        road = np.array([d.get("road_type", 0.6) for _, _, d in edges])
        res = self.safety_scorer.score_points_array(
            mid_lat, mid_lon, safety_zones, time_of_day, preferences, lit=lit, road_type=road
        )
        # Relative risk inside this trip's area (0 = safest streets around,
        # 1 = least safe). Absolute scores sit in a narrow band at night
        # (everything is darker), so ranking within the area is what lets
        # the router tell a safer street from a less safe one.
        scores = res["score"]
        lo, hi = np.percentile(scores, 5), np.percentile(scores, 95)
        res["risk"] = np.clip((hi - scores) / max(hi - lo, 1e-6), 0.0, 1.0)
        keys = list(res.keys())
        out = {}
        for i, (u, v, _) in enumerate(edges):
            rec = {k: float(res[k][i]) for k in keys}
            out[(u, v)] = rec
            out[(v, u)] = rec
        return out

    def _astar(self, sub: nx.Graph, start: int, end: int, edge_scores, safety_weight: float):
        nodes = self.graph.nodes

        gain = settings.SAFETY_DETOUR_GAIN

        def cost(u, v, d):
            if safety_weight <= 0:
                return d["distance"]
            risk = edge_scores[(u, v)]["risk"]
            return d["distance"] * (1.0 + gain * risk * safety_weight)

        def h(u, v):
            a, b = nodes[u], nodes[v]
            return _haversine(a["lat"], a["lon"], b["lat"], b["lon"])

        return nx.astar_path(sub, start, end, heuristic=h, weight=cost)

    def _summarise(self, path: List[int], edge_scores) -> Tuple[float, float, SafetyBreakdown]:
        """Length-weighted safety over the edges actually walked."""
        total = 0.0
        acc = {k: 0.0 for k in (
            "score", "lighting", "road_type", "activity", "police_proximity",
            "cctv_coverage", "safe_landmarks", "time_factor")}
        for u, v in zip(path, path[1:]):
            d = self.graph[u][v]["distance"]
            rec = edge_scores[(u, v)]
            total += d
            for k in acc:
                acc[k] += rec[k] * d
        if total <= 0:
            rec = next(iter(edge_scores.values()))
            return 0.0, rec["score"], SafetyBreakdown(**{
                k: min(1.0, rec[k]) for k in acc if k != "score"})
        avg = {k: acc[k] / total for k in acc}
        score = avg.pop("score")
        if total > 5000:  # same long-route penalty as SafetyScorer.score_route
            score *= 1 - min(0.1, (total - 5000) / 50000)
        breakdown = SafetyBreakdown(**{k: max(0.0, min(1.0, v)) for k, v in avg.items()})
        return total, score, breakdown

    def _geometry(self, path: List[int]) -> List[List[float]]:
        nodes = self.graph.nodes
        return [[nodes[n]["lon"], nodes[n]["lat"]] for n in path]

    def _plan(
        self,
        start: Coordinates,
        end: Coordinates,
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
        preferences: Optional[SafetyPreferences],
        weights: List[float],
    ) -> List[Tuple[List[int], Dict]]:
        start_node = self.find_nearest_node(start.lat, start.lng)
        end_node = self.find_nearest_node(end.lat, end.lng)
        if start_node is None or end_node is None:
            raise ValueError("Could not find route nodes near given coordinates")

        sub = self._window(start_node, end_node)
        edge_scores = self._score_edges(sub, safety_zones, time_of_day, preferences)
        results = []
        for w in weights:
            try:
                path = self._astar(sub, start_node, end_node, edge_scores, w)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                # Window too tight (river crossings etc.): use the whole city
                logger.info("No path in window, retrying on the full graph")
                sub = self.graph
                edge_scores = self._score_edges(sub, safety_zones, time_of_day, preferences)
                path = self._astar(sub, start_node, end_node, edge_scores, w)
            results.append((path, edge_scores))
        return results

    def _to_route(self, kind: str, path, edge_scores, time_of_day: TimeOfDay, warn=True) -> Route:
        distance, score, breakdown = self._summarise(path, edge_scores)
        return Route(
            route_id=f"{kind}-{datetime.now().timestamp()}",
            geometry=self._geometry(path),
            distance_m=round(distance, 1),
            duration_s=round(distance / settings.DEFAULT_WALKING_SPEED, 1),
            safety_score=round(score, 1),
            safety_breakdown=breakdown,
            warnings=self._get_route_warnings(score, time_of_day) if warn else [],
        )

    def calculate_alternative_routes(
        self,
        start: Coordinates,
        end: Coordinates,
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
        preferences: Optional[SafetyPreferences] = None,
    ) -> RouteComparisonResult:
        """Fastest (shortest), balanced and safest routes for one trip."""
        (fp, fes), (bp, bes), (sp, ses) = self._plan(
            start, end, safety_zones, time_of_day, preferences, [0.0, 0.5, 1.0]
        )
        fastest = self._to_route("fastest", fp, fes, time_of_day)
        balanced = self._to_route("balanced", bp, bes, time_of_day)
        safest = self._to_route("safest", sp, ses, time_of_day, warn=False)
        safest.warnings = [w for w in self._get_route_warnings(safest.safety_score, time_of_day)
                           if "alternative transportation" not in w]

        base = fastest.distance_m or 1
        return RouteComparisonResult(
            fastest=fastest,
            balanced=balanced,
            safest=safest,
            comparison={
                "extra_distance_pct": round((safest.distance_m - fastest.distance_m) / base * 100),
                "extra_time_s": round(safest.duration_s - fastest.duration_s),
                "safety_improvement_pct": round(safest.safety_score - fastest.safety_score),
            },
        )

    async def calculate_route(self, request: RouteRequest, safety_zones: List[SafetyZone]) -> Route:
        """Single route for a given safety_weight (0 = fastest, 1 = safest)."""
        [(path, es)] = self._plan(
            request.start,
            request.end,
            safety_zones,
            request.time_of_day,
            request.preferences,
            [request.safety_weight],
        )
        return self._to_route("route", path, es, request.time_of_day)

    def _get_route_warnings(self, safety_score: float, time_of_day: TimeOfDay) -> List[str]:
        """Generate warnings based on safety score and conditions"""
        warnings = []
        if safety_score < 50:
            warnings.append("Route passes through areas with limited safety features")
        if time_of_day == TimeOfDay.late_night:
            warnings.append("Limited street lighting on some sections")
            if safety_score < 60:
                warnings.append("Consider alternative transportation at this hour")
        if time_of_day == TimeOfDay.night and safety_score < 70:
            warnings.append("Some sections may have reduced visibility")
        return warnings

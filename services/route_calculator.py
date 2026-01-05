"""
Route calculation service using NetworkX for graph-based routing
"""

import logging
import asyncio
from typing import List, Tuple, Optional, Dict, Any
import networkx as nx
import numpy as np
from datetime import datetime

from models import (
    Route,
    RouteRequest,
    RouteComparisonResult,
    Coordinates,
    SafetyZone,
    TimeOfDay,
)
from services.safety_scorer import SafetyScorer
from config import settings

logger = logging.getLogger(__name__)


class RouteCalculator:
    """Service for calculating safety-aware routes using NetworkX"""

    def __init__(self):
        self.graph = nx.Graph()
        self.safety_scorer = SafetyScorer()
        self.graph_loaded = False
        self.node_count = 0
        self.edge_count = 0

    def build_graph_from_osm(self, osm_data: Dict[str, Any]):
        """Build NetworkX graph from OSM street data"""
        self.graph.clear()
        nodes_map = {}

        # Process ways and add nodes/edges
        for element in osm_data.get("elements", []):
            if element.get("type") == "way" and element.get("geometry"):
                geometry = element["geometry"]
                tags = element.get("tags", {})

                # Determine edge weight based on road type
                highway_type = tags.get("highway", "residential")
                base_weight = self._get_road_weight(highway_type)

                # Add nodes and edges for the way
                prev_node_id = None
                for i, point in enumerate(geometry):
                    node_id = f"{element['id']}_{i}"

                    # Add node if not exists
                    if node_id not in self.graph:
                        self.graph.add_node(
                            node_id,
                            lat=point["lat"],
                            lon=point["lon"],
                            pos=(point["lon"], point["lat"]),
                        )

                    # Add edge to previous node
                    if prev_node_id:
                        distance = self.safety_scorer.calculate_distance(
                            self.graph.nodes[prev_node_id]["lat"],
                            self.graph.nodes[prev_node_id]["lon"],
                            point["lat"],
                            point["lon"],
                        )

                        self.graph.add_edge(
                            prev_node_id,
                            node_id,
                            weight=distance * base_weight,
                            distance=distance,
                            highway_type=highway_type,
                        )

                    prev_node_id = node_id

        self.node_count = self.graph.number_of_nodes()
        self.edge_count = self.graph.number_of_edges()
        self.graph_loaded = True

        logger.info(f"Graph built with {self.node_count} nodes and {self.edge_count} edges")

    def _get_road_weight(self, highway_type: str) -> float:
        """Get weight multiplier based on road type (lower is better)"""
        weights = {
            "footway": 0.8,
            "pedestrian": 0.9,
            "residential": 1.0,
            "tertiary": 1.2,
            "secondary": 1.5,
            "primary": 2.0,
            "path": 1.1,
            "cycleway": 0.9,
        }
        return weights.get(highway_type, 1.5)

    def find_nearest_node(self, lat: float, lon: float) -> Optional[str]:
        """Find nearest graph node to given coordinates"""
        if not self.graph_loaded:
            return None

        min_distance = float("inf")
        nearest_node = None

        for node_id, data in self.graph.nodes(data=True):
            distance = self.safety_scorer.calculate_distance(
                lat, lon, data["lat"], data["lon"]
            )
            if distance < min_distance:
                min_distance = distance
                nearest_node = node_id

        return nearest_node if min_distance < 1000 else None  # Within 1km

    def calculate_route_with_safety(
        self,
        start_node: str,
        end_node: str,
        safety_zones: List[SafetyZone],
        safety_weight: float,
        time_of_day: TimeOfDay,
    ) -> Optional[List[Tuple[float, float]]]:
        """Calculate route with safety weighting"""

        if safety_weight < 0.3:
            # Fastest route - use standard shortest path
            try:
                path = nx.shortest_path(
                    self.graph, start_node, end_node, weight="distance"
                )
            except nx.NetworkXNoPath:
                return None
        else:
            # Safety-weighted routing
            # Adjust edge weights based on safety scores
            temp_graph = self.graph.copy()

            for u, v, data in temp_graph.edges(data=True):
                # Get midpoint of edge
                u_data = temp_graph.nodes[u]
                v_data = temp_graph.nodes[v]
                mid_lat = (u_data["lat"] + v_data["lat"]) / 2
                mid_lon = (u_data["lon"] + v_data["lon"]) / 2

                # Score the edge location
                safety_score, _ = self.safety_scorer.score_point(
                    (mid_lat, mid_lon), safety_zones, time_of_day
                )

                # Adjust weight based on safety (higher safety = lower weight)
                safety_factor = 1.0 - (safety_score / 100) * safety_weight
                temp_graph[u][v]["weight"] = data["distance"] * (1 + safety_factor)

            try:
                path = nx.shortest_path(temp_graph, start_node, end_node, weight="weight")
            except nx.NetworkXNoPath:
                return None

        # Convert path to coordinates
        route_coords = []
        for node_id in path:
            node_data = self.graph.nodes[node_id]
            route_coords.append((node_data["lat"], node_data["lon"]))

        return route_coords

    def calculate_alternative_routes(
        self,
        start: Coordinates,
        end: Coordinates,
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
    ) -> RouteComparisonResult:
        """Calculate fastest, safest, and balanced routes"""

        # Find nearest nodes
        start_node = self.find_nearest_node(start.lat, start.lng)
        end_node = self.find_nearest_node(end.lat, end.lng)

        if not start_node or not end_node:
            raise ValueError("Could not find route nodes near given coordinates")

        # Calculate three route variants
        fastest_coords = self.calculate_route_with_safety(
            start_node, end_node, safety_zones, 0.0, time_of_day
        )

        balanced_coords = self.calculate_route_with_safety(
            start_node, end_node, safety_zones, 0.5, time_of_day
        )

        safest_coords = self.calculate_route_with_safety(
            start_node, end_node, safety_zones, 1.0, time_of_day
        )

        # Score each route
        fastest_score, fastest_breakdown = self.safety_scorer.score_route(
            fastest_coords, safety_zones, time_of_day
        )

        balanced_score, balanced_breakdown = self.safety_scorer.score_route(
            balanced_coords, safety_zones, time_of_day
        )

        safest_score, safest_breakdown = self.safety_scorer.score_route(
            safest_coords, safety_zones, time_of_day
        )

        # Calculate distances and durations
        fastest_distance = self._calculate_route_distance(fastest_coords)
        balanced_distance = self._calculate_route_distance(balanced_coords)
        safest_distance = self._calculate_route_distance(safest_coords)

        fastest_duration = fastest_distance / settings.DEFAULT_WALKING_SPEED
        balanced_duration = balanced_distance / settings.DEFAULT_WALKING_SPEED
        safest_duration = safest_distance / settings.DEFAULT_WALKING_SPEED

        # Create route objects
        fastest_route = Route(
            route_id=f"fastest-{datetime.now().timestamp()}",
            geometry=[[lat, lon] for lat, lon in fastest_coords],
            distance_m=fastest_distance,
            duration_s=fastest_duration,
            safety_score=fastest_score,
            safety_breakdown=fastest_breakdown,
            warnings=self._get_route_warnings(fastest_score, time_of_day),
        )

        balanced_route = Route(
            route_id=f"balanced-{datetime.now().timestamp()}",
            geometry=[[lat, lon] for lat, lon in balanced_coords],
            distance_m=balanced_distance,
            duration_s=balanced_duration,
            safety_score=balanced_score,
            safety_breakdown=balanced_breakdown,
            warnings=self._get_route_warnings(balanced_score, time_of_day),
        )

        safest_route = Route(
            route_id=f"safest-{datetime.now().timestamp()}",
            geometry=[[lat, lon] for lat, lon in safest_coords],
            distance_m=safest_distance,
            duration_s=safest_duration,
            safety_score=safest_score,
            safety_breakdown=safest_breakdown,
            warnings=[],
        )

        return RouteComparisonResult(
            fastest=fastest_route,
            balanced=balanced_route,
            safest=safest_route,
            comparison={
                "extra_distance_pct": round(
                    ((safest_distance - fastest_distance) / fastest_distance) * 100
                ),
                "extra_time_s": round(safest_duration - fastest_duration),
                "safety_improvement_pct": round(safest_score - fastest_score),
            },
        )

    def _calculate_route_distance(self, coords: List[Tuple[float, float]]) -> float:
        """Calculate total distance of route"""
        if not coords:
            return 0

        total_distance = 0
        for i in range(len(coords) - 1):
            total_distance += self.safety_scorer.calculate_distance(
                coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]
            )

        return total_distance

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

    async def calculate_route(
        self,
        request: RouteRequest,
        safety_zones: List[SafetyZone],
    ) -> Route:
        """Calculate a single route based on request parameters"""

        # Find nearest nodes
        start_node = self.find_nearest_node(request.start.lat, request.start.lng)
        end_node = self.find_nearest_node(request.end.lat, request.end.lng)

        if not start_node or not end_node:
            raise ValueError("Could not find route nodes near given coordinates")

        # Calculate route with specified safety weight
        coords = self.calculate_route_with_safety(
            start_node,
            end_node,
            safety_zones,
            request.safety_weight,
            request.time_of_day,
        )

        if not coords:
            raise ValueError("No route found")

        # Score the route
        safety_score, breakdown = self.safety_scorer.score_route(
            coords, safety_zones, request.time_of_day, request.preferences
        )

        # Calculate distance and duration
        distance = self._calculate_route_distance(coords)
        duration = distance / settings.DEFAULT_WALKING_SPEED

        return Route(
            route_id=f"route-{datetime.now().timestamp()}",
            geometry=[[lat, lon] for lat, lon in coords],
            distance_m=distance,
            duration_s=duration,
            safety_score=safety_score,
            safety_breakdown=breakdown,
            warnings=self._get_route_warnings(safety_score, request.time_of_day),
        )
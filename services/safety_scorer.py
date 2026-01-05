"""
Safety scoring service for routes and locations
"""

import logging
import math
from typing import List, Tuple, Optional
from datetime import datetime

from models import (
    SafetyZone,
    SafetyBreakdown,
    SafetyPreferences,
    TimeOfDay,
    SafetyZoneType,
)
from config import settings

logger = logging.getLogger(__name__)


class SafetyScorer:
    """Service for calculating safety scores"""

    def __init__(self):
        self.weights = settings.SAFETY_WEIGHTS

    def calculate_distance(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Calculate Haversine distance between two points in meters"""
        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
            delta_lambda / 2
        ) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def get_time_multiplier(self, time_of_day: TimeOfDay) -> float:
        """Get safety multiplier based on time of day"""
        multipliers = {
            TimeOfDay.day: 1.0,
            TimeOfDay.evening: 0.85,
            TimeOfDay.night: 0.7,
            TimeOfDay.late_night: 0.6,
        }
        return multipliers.get(time_of_day, 0.7)

    def calculate_zone_influence(
        self, point: Tuple[float, float], zone: SafetyZone, max_distance: float = 500
    ) -> float:
        """Calculate influence of a safety zone on a point (0-1)"""
        distance = self.calculate_distance(
            point[0], point[1], zone.center[0], zone.center[1]
        )

        # If point is within zone radius, maximum influence
        if distance <= zone.radius:
            return 1.0

        # Linear decay from zone edge to max_distance
        effective_distance = distance - zone.radius
        if effective_distance >= max_distance:
            return 0.0

        return 1.0 - (effective_distance / max_distance)

    def score_point(
        self,
        point: Tuple[float, float],
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
        preferences: Optional[SafetyPreferences] = None,
    ) -> Tuple[float, SafetyBreakdown]:
        """Calculate safety score for a single point"""

        # Initialize scores
        lighting_score = 0.3  # Base lighting score
        police_score = 0.2  # Base police proximity
        activity_score = 0.3  # Base activity level
        medical_score = 0.2  # Base medical access
        transport_score = 0.3  # Base transport access
        danger_score = 1.0  # Start with no danger

        # Process each safety zone
        for zone in safety_zones:
            influence = self.calculate_zone_influence(point, zone)

            if influence > 0:
                # Check time relevance
                if zone.time_relevance == "day_only" and time_of_day in [
                    TimeOfDay.night,
                    TimeOfDay.late_night,
                ]:
                    continue
                elif zone.time_relevance == "night_only" and time_of_day == TimeOfDay.day:
                    continue

                # Apply zone influence based on type
                if zone.type == SafetyZoneType.police_station:
                    police_score = max(police_score, influence)
                elif zone.type == SafetyZoneType.hospital:
                    medical_score = max(medical_score, influence * 0.8)
                elif zone.type == SafetyZoneType.metro_station:
                    transport_score = max(transport_score, influence * 0.9)
                    activity_score = max(activity_score, influence * 0.7)
                elif zone.type == SafetyZoneType.well_lit:
                    lighting_score = max(lighting_score, influence)
                elif zone.type == SafetyZoneType.busy_street:
                    activity_score = max(activity_score, influence)
                elif zone.type == SafetyZoneType.pharmacy:
                    medical_score = max(medical_score, influence * 0.6)
                elif zone.type == SafetyZoneType.open_24h:
                    activity_score = max(activity_score, influence * 0.8)
                    lighting_score = max(lighting_score, influence * 0.7)
                elif zone.type == SafetyZoneType.caution_area:
                    danger_score = min(danger_score, 1.0 - influence * 0.3)
                elif zone.type == SafetyZoneType.danger_zone:
                    danger_score = min(danger_score, 1.0 - influence * 0.6)

        # Apply time of day modifiers
        time_multiplier = self.get_time_multiplier(time_of_day)

        # Night time reduces visibility and activity
        if time_of_day in [TimeOfDay.night, TimeOfDay.late_night]:
            activity_score *= 0.6
            if lighting_score < 0.5:
                lighting_score *= 0.5

        # Create breakdown
        breakdown = SafetyBreakdown(
            lighting=min(1.0, lighting_score),
            road_type=0.7,  # Default road safety
            activity=min(1.0, activity_score),
            time_factor=time_multiplier,
            police_proximity=min(1.0, police_score),
            cctv_coverage=0.5,  # Default CCTV assumption
            safe_landmarks=min(1.0, (medical_score + transport_score) / 2),
        )

        # Calculate weighted score
        if preferences:
            total_weight = (
                preferences.lighting
                + preferences.police_stations
                + preferences.busy_areas
                + preferences.cctv_coverage
                + preferences.safe_landmarks
            )

            weighted_score = (
                (breakdown.lighting * preferences.lighting / total_weight)
                + (breakdown.police_proximity * preferences.police_stations / total_weight)
                + (breakdown.activity * preferences.busy_areas / total_weight)
                + (breakdown.cctv_coverage * preferences.cctv_coverage / total_weight)
                + (breakdown.safe_landmarks * preferences.safe_landmarks / total_weight)
            )
        else:
            # Default equal weighting
            weighted_score = (
                breakdown.lighting * 0.2
                + breakdown.police_proximity * 0.2
                + breakdown.activity * 0.2
                + breakdown.cctv_coverage * 0.1
                + breakdown.safe_landmarks * 0.15
                + danger_score * 0.15
            )

        # Apply time factor and danger modifier
        final_score = weighted_score * time_multiplier * danger_score

        # Convert to 0-100 scale
        safety_score = min(100, max(0, final_score * 100))

        return safety_score, breakdown

    def score_route(
        self,
        route_points: List[Tuple[float, float]],
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
        preferences: Optional[SafetyPreferences] = None,
    ) -> Tuple[float, SafetyBreakdown]:
        """Calculate safety score for an entire route"""

        if not route_points:
            return 0.0, SafetyBreakdown(
                lighting=0,
                road_type=0,
                activity=0,
                time_factor=0,
                police_proximity=0,
                cctv_coverage=0,
                safe_landmarks=0,
            )

        # Sample points along the route (every ~100m)
        sample_points = []
        total_distance = 0

        for i in range(len(route_points) - 1):
            segment_distance = self.calculate_distance(
                route_points[i][0],
                route_points[i][1],
                route_points[i + 1][0],
                route_points[i + 1][1],
            )
            total_distance += segment_distance

            # Add intermediate points if segment is long
            if segment_distance > 100:
                num_samples = int(segment_distance / 100)
                for j in range(num_samples + 1):
                    ratio = j / max(1, num_samples)
                    lat = route_points[i][0] + ratio * (
                        route_points[i + 1][0] - route_points[i][0]
                    )
                    lon = route_points[i][1] + ratio * (
                        route_points[i + 1][1] - route_points[i][1]
                    )
                    sample_points.append((lat, lon))
            else:
                sample_points.append(route_points[i])

        # Add last point
        if route_points:
            sample_points.append(route_points[-1])

        # Score each sample point
        scores = []
        breakdowns = []

        for point in sample_points:
            score, breakdown = self.score_point(
                point, safety_zones, time_of_day, preferences
            )
            scores.append(score)
            breakdowns.append(breakdown)

        # Average the scores
        if scores:
            avg_score = sum(scores) / len(scores)

            # Average the breakdowns
            avg_breakdown = SafetyBreakdown(
                lighting=sum(b.lighting for b in breakdowns) / len(breakdowns),
                road_type=sum(b.road_type for b in breakdowns) / len(breakdowns),
                activity=sum(b.activity for b in breakdowns) / len(breakdowns),
                time_factor=breakdowns[0].time_factor if breakdowns else 0,
                police_proximity=sum(b.police_proximity or 0 for b in breakdowns)
                / len(breakdowns),
                cctv_coverage=sum(b.cctv_coverage or 0 for b in breakdowns)
                / len(breakdowns),
                safe_landmarks=sum(b.safe_landmarks or 0 for b in breakdowns)
                / len(breakdowns),
            )
        else:
            avg_score = 0
            avg_breakdown = SafetyBreakdown(
                lighting=0,
                road_type=0,
                activity=0,
                time_factor=0,
                police_proximity=0,
                cctv_coverage=0,
                safe_landmarks=0,
            )

        # Apply distance penalty for very long routes
        if total_distance > 5000:  # More than 5km
            distance_penalty = min(0.1, (total_distance - 5000) / 50000)
            avg_score *= (1 - distance_penalty)

        return avg_score, avg_breakdown

    def compare_routes(
        self,
        route1: List[Tuple[float, float]],
        route2: List[Tuple[float, float]],
        safety_zones: List[SafetyZone],
        time_of_day: TimeOfDay,
        preferences: Optional[SafetyPreferences] = None,
    ) -> dict:
        """Compare safety scores of two routes"""

        score1, breakdown1 = self.score_route(
            route1, safety_zones, time_of_day, preferences
        )
        score2, breakdown2 = self.score_route(
            route2, safety_zones, time_of_day, preferences
        )

        # Calculate distances
        dist1 = sum(
            self.calculate_distance(
                route1[i][0], route1[i][1], route1[i + 1][0], route1[i + 1][1]
            )
            for i in range(len(route1) - 1)
        )

        dist2 = sum(
            self.calculate_distance(
                route2[i][0], route2[i][1], route2[i + 1][0], route2[i + 1][1]
            )
            for i in range(len(route2) - 1)
        )

        return {
            "route1": {"safety_score": score1, "distance_m": dist1, "breakdown": breakdown1},
            "route2": {"safety_score": score2, "distance_m": dist2, "breakdown": breakdown2},
            "safer_route": 1 if score1 >= score2 else 2,
            "safety_difference": abs(score1 - score2),
            "distance_difference": abs(dist1 - dist2),
        }
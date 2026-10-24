"""Tests for safety scoring and safety-weighted routing.

Run with:  python -m pytest -q
"""

import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Coordinates, SafetyPreferences, SafetyZone, TimeOfDay  # noqa: E402
from services.osm_fetcher import load_curated_zones  # noqa: E402
from services.route_calculator import RouteCalculator  # noqa: E402
from services.safety_scorer import SafetyScorer  # noqa: E402

LAT0, LON0 = 48.8566, 2.3522
STEP = 0.0009  # ~100 m north-south


def grid_osm(n=11):
    """Overpass-style response: an n x n grid of residential streets.
    Each horizontal and vertical street is its own way; ways share OSM node ids
    at intersections, like real data."""
    elements = []
    nid = lambda i, j: 1_000_000 + i * n + j  # noqa: E731
    pt = lambda i, j: {"lat": LAT0 + i * STEP, "lon": LON0 + j * STEP * 1.5}  # noqa: E731
    wid = 1
    for i in range(n):
        elements.append({"type": "way", "id": wid, "tags": {"highway": "residential"},
                         "nodes": [nid(i, j) for j in range(n)],
                         "geometry": [pt(i, j) for j in range(n)]})
        wid += 1
    for j in range(n):
        elements.append({"type": "way", "id": wid, "tags": {"highway": "residential"},
                         "nodes": [nid(i, j) for i in range(n)],
                         "geometry": [pt(i, j) for i in range(n)]})
        wid += 1
    return {"elements": elements}


def test_vectorised_scoring_matches_scalar():
    scorer = SafetyScorer()
    zones = load_curated_zones()
    assert len(zones) > 50
    rng = random.Random(7)
    pts = [(48.83 + rng.random() * 0.06, 2.27 + rng.random() * 0.12) for _ in range(300)]
    prefs = SafetyPreferences(lighting=5, police_stations=2, busy_areas=4,
                              cctv_coverage=1, safe_landmarks=3)
    for tod in TimeOfDay:
        for p in (None, prefs):
            arr = scorer.score_points_array([a for a, _ in pts], [b for _, b in pts], zones, tod, p)
            for k, (lat, lon) in enumerate(pts):
                score, bd = scorer.score_point((lat, lon), zones, tod, p)
                assert arr["score"][k] == pytest.approx(score, abs=1e-6)
                assert arr["lighting"][k] == pytest.approx(bd.lighting, abs=1e-9)
                assert arr["police_proximity"][k] == pytest.approx(bd.police_proximity, abs=1e-9)
                assert arr["safe_landmarks"][k] == pytest.approx(bd.safe_landmarks, abs=1e-9)


def test_graph_is_connected_across_ways():
    rc = RouteCalculator()
    rc.build_graph_from_osm(grid_osm())
    assert rc.node_count == 121  # intersections shared, not duplicated per way
    assert rc.edge_count == 2 * 11 * 10


def test_safest_route_avoids_danger_zone_and_fastest_does_not():
    rc = RouteCalculator()
    rc.build_graph_from_osm(grid_osm())
    mid_lat, mid_lon = LAT0 + 5 * STEP, LON0 + 5 * STEP * 1.5
    zones = [SafetyZone(id="d", type="danger_zone", center=[mid_lat, mid_lon],
                        radius=250, time_relevance="always")]
    start = Coordinates(lat=LAT0 + 5 * STEP, lng=LON0)
    end = Coordinates(lat=LAT0 + 5 * STEP, lng=LON0 + 10 * STEP * 1.5)

    res = rc.calculate_alternative_routes(start, end, zones, TimeOfDay.night)

    # GeoJSON order: [lng, lat]
    first = res.fastest.geometry[0]
    assert first[0] == pytest.approx(start.lng) and first[1] == pytest.approx(start.lat)

    def min_dist_to_zone(geom):
        s = SafetyScorer()
        return min(s.calculate_distance(lat, lng, mid_lat, mid_lon) for lng, lat in geom)

    assert min_dist_to_zone(res.fastest.geometry) < 10  # straight through
    assert min_dist_to_zone(res.safest.geometry) > 250  # goes around it
    assert res.safest.safety_score > res.fastest.safety_score
    assert res.safest.distance_m > res.fastest.distance_m
    assert res.comparison["safety_improvement_pct"] > 0


def test_lit_streets_are_preferred_at_night():
    data = grid_osm()
    # Light the southern edge street and the two side streets; leave the
    # direct middle street dark.
    for el in data["elements"]:
        if el["id"] in (1, 12, 22):
            el["tags"]["lit"] = "yes"
        else:
            el["tags"]["lit"] = "no"
    rc = RouteCalculator()
    rc.build_graph_from_osm(data)
    start = Coordinates(lat=LAT0 + 2 * STEP, lng=LON0)
    end = Coordinates(lat=LAT0 + 2 * STEP, lng=LON0 + 10 * STEP * 1.5)
    res = rc.calculate_alternative_routes(start, end, [], TimeOfDay.night)
    lats = {round(lat, 6) for _, lat in res.safest.geometry}
    assert round(LAT0, 6) in lats  # used the lit southern street
    assert res.safest.safety_breakdown.lighting > res.fastest.safety_breakdown.lighting


def test_overpass_elements_are_classified():
    from services.osm_fetcher import OSMFetcher

    els = [
        {"type": "node", "id": 1, "lat": 48.86, "lon": 2.35, "tags": {"amenity": "police"}},
        {"type": "way", "id": 2, "center": {"lat": 48.85, "lon": 2.34},
         "tags": {"amenity": "hospital", "name": "Hôtel-Dieu"}},
        {"type": "node", "id": 3, "lat": 48.858, "lon": 2.347,
         "tags": {"railway": "subway_entrance", "name": "Métro Châtelet"}},
        {"type": "node", "id": 4, "lat": 48.85, "lon": 2.36,
         "tags": {"amenity": "pharmacy", "opening_hours": "Mo-Sa 09:00-20:00"}},
        {"type": "node", "id": 5, "lat": 48.85, "lon": 2.37, "tags": {"amenity": "nightclub"}},
        {"type": "node", "id": 6, "lat": 48.85, "lon": 2.37, "tags": {"shop": "bakery"}},
    ]
    zones = [OSMFetcher._classify(e) for e in els]
    assert [z.type.value if z else None for z in zones] == [
        "police_station", "hospital", "metro_station", "pharmacy", "caution_area", None]
    assert zones[1].name == "Hôtel-Dieu"
    assert zones[2].name == "Châtelet"
    assert zones[3].time_relevance == "day_only"

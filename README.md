# Noura Backend - Safe City Walks API

A FastAPI-based backend service for the Noura Safe City Walks application, providing safety-aware routing and location services for Paris.

## Features

- 🚶‍♀️ **Safety-Aware Routing**: Calculate routes optimized for safety using NetworkX graph algorithms
- 📍 **Safety Zones**: Fetch and analyze safety zones including police stations, hospitals, metro stations, pharmacies, well-lit areas, and danger zones
- 🗺️ **OpenStreetMap Integration**: Real-time data fetching from OpenStreetMap via Overpass API
- 📊 **Safety Scoring**: Comprehensive safety scoring system considering multiple factors:
  - Police proximity
  - Street lighting
  - Foot traffic
  - Public transport access
  - Time of day
- 🔄 **Route Comparison**: Compare fastest, safest, and balanced route options
- ⚡ **High Performance**: Async operations with caching for optimal performance
- 🌐 **CORS Support**: Configured for web and mobile app integration

## Tech Stack

- **Framework**: FastAPI
- **Graph Processing**: NetworkX
- **HTTP Client**: httpx (async)
- **Data Validation**: Pydantic
- **Server**: Uvicorn
- **Caching**: cachetools

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/noura-backend.git
cd noura-backend
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file (optional):
```env
DEBUG=true
PORT=8000
HOST=0.0.0.0
```

## Running the Server

### Development Mode
```bash
python main.py
```

Or with auto-reload:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Endpoints

### Health Check
```http
GET /api/health
```
Returns the API status, graph loading state, and system metrics.

### Safety Zones
```http
GET /api/safety-zones?lat=48.8566&lng=2.3522&radius=500
```
Fetches safety zones within the specified radius (meters) of a location.

**Response includes:**
- Police stations
- Hospitals
- Metro stations
- Pharmacies
- 24-hour services
- Well-lit areas
- Busy streets
- Caution/danger zones

### Calculate Route
```http
POST /api/route
```

**Request Body:**
```json
{
  "start": {"lat": 48.8566, "lng": 2.3522},
  "end": {"lat": 48.8606, "lng": 2.3376},
  "safety_weight": 0.7,
  "time_of_day": "night",
  "preferences": {
    "lighting": 5,
    "police_stations": 3,
    "busy_areas": 4,
    "cctv_coverage": 2,
    "safe_landmarks": 3
  }
}
```

**Response:**
```json
{
  "route_id": "route-1234567890",
  "geometry": [[2.3522, 48.8566], ...],
  "distance_m": 1250,
  "duration_s": 900,
  "safety_score": 78.5,
  "safety_breakdown": {
    "lighting": 0.8,
    "road_type": 0.7,
    "activity": 0.75,
    "time_factor": 0.7,
    "police_proximity": 0.6,
    "cctv_coverage": 0.5,
    "safe_landmarks": 0.7
  },
  "warnings": []
}
```

### Compare Routes
```http
POST /api/route/compare
```

**Request Body:**
```json
{
  "start": {"lat": 48.8566, "lng": 2.3522},
  "end": {"lat": 48.8606, "lng": 2.3376},
  "time_of_day": "evening",
  "preferences": {...}
}
```

Returns fastest, safest, and balanced route options with comparison metrics.

## Architecture

### Services

1. **OSMFetcher**: Safety zones and the street network
   - Curated Paris zones (`data/paris_safety_zones.json`, the same list the app shows)
   - Live OpenStreetMap features from one Overpass query per area: police,
     hospitals, metro, pharmacies, 24h services, nightlife, construction
   - Walking street network for the whole city, cached gzipped in `data/`

2. **SafetyScorer**: Calculates safety scores for points and routes
   - Time-based multipliers
   - Zone influence calculations
   - User preference weighting
   - Route segment analysis

3. **RouteCalculator**: safety-weighted A* over the street graph
   - Ways joined at shared OSM nodes into one connected walking network
   - Each street segment scored (zones, OSM `lit` tag, street type, time of day,
     user preferences), vectorised with NumPy
   - Edge cost = length x (1 + gain x risk x safety_weight), where risk ranks the
     segment against the others around the trip; 0 = shortest path
   - Fastest / balanced / safest computed on the same scored window
   - Geometry returned as `[lng, lat]` pairs (GeoJSON order, like OSRM)

### Data Flow

1. **Startup**: Load Paris street network into NetworkX graph
2. **Request**: Receive routing request with coordinates
3. **Fetch**: Get safety zones from OSM for the route area
4. **Calculate**: Generate route using safety-weighted graph algorithms
5. **Score**: Calculate comprehensive safety score for the route
6. **Return**: Send optimized route with safety metrics

## Safety Scoring Algorithm

The safety score (0-100) considers:

- **Lighting** (20%): Street lighting and well-lit areas
- **Police Proximity** (20%): Distance to police stations
- **Activity Level** (20%): Foot traffic, busy areas, open businesses
- **Safe Landmarks** (15%): Hospitals, metro stations, pharmacies
- **CCTV Coverage** (10%): Assumed coverage based on area type
- **Time Factor** (15%): Time of day multiplier

### Time Multipliers
- Day: 1.0
- Evening: 0.85
- Night: 0.7
- Late Night: 0.6

## Configuration

Key settings in `config.py`:

- `PARIS_BOUNDS`: Geographic boundaries for Paris
- `SAFETY_RADIUS_SEARCH`: Default 500m search radius
- `MAX_ROUTE_DISTANCE`: Maximum 10km route distance
- `DEFAULT_WALKING_SPEED`: 1.4 m/s walking speed
- `CACHE_TTL`: 1 hour cache duration

## Tests

```bash
python -m pytest -q
```

Covers: vectorised scoring matches the per-point scorer, ways join into a
connected graph, the safest route detours around a danger zone while the
fastest goes through it, lit streets win at night, Overpass classification.

## Development

### Project Structure
```
noura-backend/
├── main.py              # FastAPI application
├── config.py            # Configuration settings
├── models.py            # Pydantic models
├── services/
│   ├── __init__.py
│   ├── osm_fetcher.py   # OpenStreetMap data fetching
│   ├── safety_scorer.py # Safety scoring logic
│   └── route_calculator.py # NetworkX routing
├── requirements.txt     # Python dependencies
├── README.md           # Documentation
└── .gitignore          # Git ignore file
```

### Testing with curl

**Get Safety Zones:**
```bash
curl "http://localhost:8000/api/safety-zones?lat=48.8566&lng=2.3522&radius=500"
```

**Calculate Route:**
```bash
curl -X POST "http://localhost:8000/api/route" \
  -H "Content-Type: application/json" \
  -d '{
    "start": {"lat": 48.8566, "lng": 2.3522},
    "end": {"lat": 48.8606, "lng": 2.3376},
    "safety_weight": 0.7,
    "time_of_day": "night"
  }'
```

## Deployment

### Docker

Create a `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t noura-backend .
docker run -p 8000:8000 noura-backend
```

### Environment Variables

- `DEBUG`: Enable debug mode (default: true)
- `PORT`: Server port (default: 8000)
- `HOST`: Server host (default: 0.0.0.0)
- `CORS_ORIGINS`: Allowed CORS origins (comma-separated)

## Performance Considerations

1. **Graph Loading**: The Paris street network is loaded on startup (~30 seconds)
2. **Caching**: Safety zones are cached for 1 hour to reduce API calls
3. **Async Operations**: All I/O operations are async for better concurrency
4. **Connection Pooling**: httpx client reuses connections

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

MIT License - See LICENSE file for details

## Support

For issues and questions, please open an issue on GitHub.
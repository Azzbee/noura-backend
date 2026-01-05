# GitHub Repository Setup Instructions

The backend code is ready and committed to git. To push it to GitHub, follow these steps:

## Option 1: Using GitHub CLI (Recommended)

1. **Authenticate with GitHub CLI:**
   ```bash
   gh auth login
   ```
   Follow the prompts to authenticate with your GitHub account.

2. **Create and push the repository:**
   ```bash
   cd "/Users/adamzer/Desktop/Noura App/noura-backend"
   gh repo create noura-backend --public --description "Safety-aware routing backend for Noura Safe City Walks app" --source=. --remote=origin --push
   ```

## Option 2: Manual Setup via GitHub Website

1. **Create a new repository on GitHub:**
   - Go to https://github.com/new
   - Repository name: `noura-backend`
   - Description: `Safety-aware routing backend for Noura Safe City Walks app`
   - Make it Public
   - DO NOT initialize with README, .gitignore, or license (we already have them)
   - Click "Create repository"

2. **Add the remote and push:**
   ```bash
   cd "/Users/adamzer/Desktop/Noura App/noura-backend"
   git remote add origin https://github.com/YOUR_USERNAME/noura-backend.git
   git push -u origin main
   ```

   Replace `YOUR_USERNAME` with your GitHub username.

## Repository Contents

Your repository contains a complete Python FastAPI backend with:

- **FastAPI Application**: REST API with safety-aware routing
- **NetworkX Routing**: Graph-based route calculation
- **OSM Integration**: Real-time data from OpenStreetMap
- **Safety Scoring**: Comprehensive safety analysis system
- **Services**:
  - `osm_fetcher.py`: Fetches safety zones from OpenStreetMap
  - `safety_scorer.py`: Calculates safety scores for routes
  - `route_calculator.py`: NetworkX-based routing with safety weights

## Next Steps

After pushing to GitHub:

1. **Install dependencies locally:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run the backend:**
   ```bash
   python main.py
   ```
   The API will be available at http://localhost:8000

3. **Test the API:**
   ```bash
   # Get safety zones
   curl "http://localhost:8000/api/safety-zones?lat=48.8566&lng=2.3522&radius=500"

   # Check health
   curl "http://localhost:8000/api/health"
   ```

4. **Connect from frontend:**
   Update your frontend's `.env` file:
   ```env
   VITE_ROUTING_API_URL=http://localhost:8000
   ```

## API Documentation

Once running, visit http://localhost:8000/docs for interactive API documentation.

## Support

For any issues, please create an issue in the GitHub repository.
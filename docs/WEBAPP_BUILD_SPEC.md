# Web App Build Spec — Subdivision Agent

**Project:** subdivision-agent
**Repo:** https://github.com/jayapatl1511-hub/subdivision-agent
**Branch:** Create `webapp` from `main`
**Current state:** 53/53 tests passing, engine fully working, CLI-only

## Goal

Build a web app that replaces the CLI with a browser UI. Users can draw/upload a parcel, set parameters, run the engine, view results on an interactive map, compare scenarios side-by-side, and export.

## Tech Stack

- **Backend:** FastAPI (serves API + static frontend)
- **Frontend:** Single HTML page with Leaflet.js (CDN, no build step)
- **Engine:** Import Python modules directly (NOT subprocess)
- **Storage:** File-based — one folder per scenario
- **New deps:** `fastapi`, `uvicorn`, `python-multipart`

## Design References

The user provided design references. **Match these as closely as possible:**

1. **`web/mockup.html`** — Full HTML/CSS mockup of the desktop app. Three-column layout:
   - Left rail (300px): Parcel input (upload/draw), Planning controls (zone, servicing, road patterns, road length slider), Generate button, Job status, Legend
   - Center: Tabs (Generate / Results / Compare), map area with toolbar, legend, scale bar
   - Right rail (360px): Layout results table, selected layout metrics, export buttons, scenario save
   - Footer: status info, export chips, version
   - **Copy the CSS variables, colors, fonts, spacing from this mockup.**

2. **`web/reference/img_d506c2b0ab75.jpg`** — UI screenshot reference
3. **`web/reference/img_22c6978cab14.jpg`** — UI screenshot reference
4. **`web/reference/img_d55d50115c98.jpg`** — UI screenshot reference

**Look at ALL of these images.** They show the desired look and feel. Match their layout, color scheme, component style, and visual language as closely as possible. The mockup HTML is the primary design source — the JPGs are additional reference.

Key design elements from the mockup:
- Color palette: `--blue: #1f6feb`, `--green: #15803d`, `--red: #c2413b`, `--orange: #b7791f`, `--road: #5f9fee`
- Font: Inter / system-ui sans-serif
- Panels: white with `#d9e1ec` borders, 12px radius
- Buttons: `.btn.primary` = blue gradient, `.btn` = white with border
- Three-column grid: `300px 1fr 360px`
- Header: 64px with logo + title + top actions
- Footer: 58px with status items + export chips
- Tabs: Generate / Results / Compare
- Compare view: side-by-side panels with mini-maps and metrics tables

## Files to Create

### 1. `webapp.py` — FastAPI backend (~200 lines)

Endpoints:

```
POST /api/generate
  Body: { parcel_geojson: {...}, zone: "R-2", servicing: "serviced", patterns: ["single_road", "cul_de_sac"], road_length: null }
  Returns: { job_id: "uuid" }
  - Runs engine in threading.Thread (CPU-bound, not async)
  - Imports: models, generator, checker, constraints, export, export_qgis, intake_geojson
  - In-memory job store: jobs[job_id] = { status, results, error }

GET /api/status/{job_id}
  Returns: { status: "running"|"done"|"error", results: [...], error: null }
  - Frontend polls this every 1-2 seconds

POST /api/export
  Body: { format: "geojson"|"dxf"|"qgis", result: {...}, parcel: {...} }
  - geojson → return JSONResponse
  - dxf → write to /tmp, return FileResponse
  - qgis → write folder, zip with shutil.make_archive, return FileResponse

GET /api/scenarios
  - List folders in scenarios/ directory, read each meta.json

POST /api/scenarios/save
  Body: { name: "...", meta: {...}, parcel_geojson: {...}, layouts: {...} }
  - Create scenarios/{name}/ folder, write meta.json + GeoJSON files

GET /api/scenarios/{name}
  - Load scenario folder, return meta + parcel + layouts

# Static frontend
app.mount("/", StaticFiles(directory="web", html=True))
```

Engine integration pattern:

```python
import threading

jobs = {}

@app.post("/api/generate")
async def generate(params: dict):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "results": None, "error": None}

    def run_engine():
        try:
            # Load parcel from GeoJSON
            parcel = load_geojson_parcel(params["parcel_geojson"])
            parcel.access_points = [AccessPoint(point=(0, parcel.height/2), direction=(1, 0))]

            # Resolve constraints
            engine = ConstraintEngine("hrm")
            engine.load()
            pc = engine.resolve(params.get("zone", "R-2"), params.get("servicing", "serviced"))
            rules = LayoutRules.from_constraint_engine(pc)

            # Generate layouts for each pattern
            gen = LayoutGenerator(parcel, rules)
            patterns = [RoadPattern(p) for p in params.get("patterns", ["single_road"])]
            results = [gen.generate_layout(p, road_length=params.get("road_length")) for p in patterns]

            # Check + score
            checker = LotChecker(rules, parcel.constraint_areas)
            scorer = LayoutScorer(rules)
            for r in results:
                checker.check_layout(r)
                scorer.score_layout(r)
            results.sort(key=lambda r: r.score.total_score, reverse=True)

            # Serialize results to dict
            jobs[job_id]["results"] = [layout_result_to_dict(r) for r in results]
            jobs[job_id]["status"] = "done"
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)

    thread = threading.Thread(target=run_engine, daemon=True)
    thread.start()
    return {"job_id": job_id}
```

IMPORTANT: You need to check what functions/classes exist in the actual codebase. Read models.py, generator.py, checker.py, constraints.py, export.py, export_qgis.py, intake_geojson.py, main.py to understand the actual API before writing webapp.py. Do NOT guess — read the code first.

You may need to add serialization helpers (layout_result_to_dict / layout_result_from_dict) if they don't exist yet. Add them to models.py or a new serialize.py.

### 2. `web/index.html` — Single-page frontend with Leaflet

Use CDN for all JS/CSS — no npm, no build step:

```html
<!-- Leaflet core -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<!-- Leaflet.draw — for drawing parcel polygons -->
<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css"/>
<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>

<!-- Leaflet.Sync — for side-by-side comparison -->
<script src="https://unpkg.com/leaflet.sync@0.2.4/L.Map.Sync.js"></script>
```

UI layout:

```
┌─────────────────────────────────────────────────────┐
│  Subdivision Layout Tool                             │
├──────────────┬──────────────────────────────────────┤
│  Sidebar      │  Map Area                              │
│               │                                        │
│  Parcel:      │  ┌────────────┬────────────┐          │
│  ○ Draw       │  │  Map 1     │  Map 2     │          │
│  ○ Upload     │  │            │            │          │
│               │  │  Single Rd  │  Cul-de-sac│          │
│  Zone: [R-2▼] │  │            │            │          │
│  Serv: [Srv▼] │  │            │            │          │
│               │  └────────────┴────────────┘          │
│  Patterns:    │                                        │
│  ☑ Single Rd  │  Layers toggle (top right)             │
│  ☐ Cul-de-sac │                                        │
│  ☐ Loop Rd    │                                        │
│               │                                        │
│  [Generate]   │                                        │
│               │                                        │
│  Status:      │                                        │
│  Ready        │                                        │
│               │                                        │
│  ─────────    │                                        │
│  Export:      │                                        │
│  [GeoJSON]    │                                        │
│  [DXF]        │                                        │
│  [QGIS]       │                                        │
│               │                                        │
│  ─────────    │                                        │
│  Scenarios:   │                                        │
│  [Save]       │                                        │
│  [Load ▼]     │                                        │
└──────────────┴──────────────────────────────────────┘
```

Map features:
- Default basemap: OpenStreetMap tiles (no API key)
- Layer toggle: satellite (Esri World Imagery) / streets (OSM) / minimal (CartoDB Positron)
- Drawing: polygon tool from Leaflet.draw — user draws parcel boundary
- Upload: file input accepts .geojson — loads onto map
- Results: GeoJSON layers styled by pass/fail:
  - Passing lots: green fill (#4caf50), 0.3 opacity
  - Failing lots: red fill (#f44336), 0.3 opacity
  - Remainders: orange fill (#ff9800), 0.2 opacity
  - Roads: blue lines (#2196f3), 3px weight
  - Road centerlines: dashed blue, 1px
  - Frontage lines: black, 1px
  - Buildable envelopes: dashed green, 1px
  - Parcel boundary: black, 2px solid
- Layer control: toggle each layer on/off (L.control.layers)
- Lot popup: click a lot → show area, frontage, type, pass/fail, score
- Side-by-side: two synced maps for comparing patterns
- Generate button → POST /api/generate → poll /api/status/{job_id} every 1.5s → display when done
- Export buttons → POST /api/export → download file
- Save scenario → POST /api/scenarios/save
- Load scenario → GET /api/scenarios → dropdown → GET /api/scenarios/{name}

### 3. `web/style.css` — Minimal styling

Clean, functional. Sidebar 280px fixed left. Map fills remainder. No frameworks.

### 4. Update `requirements.txt`

Add:
```
fastapi>=0.100
uvicorn>=0.20
python-multipart>=0.0.6
```

### 5. `tests/test_webapp.py` — Basic API tests

Using FastAPI TestClient:
- POST /api/generate with a simple rectangle parcel → returns job_id
- GET /api/status/{job_id} → eventually returns status="done" with results
- POST /api/export with format=geojson → returns valid GeoJSON
- GET /api/scenarios → returns list
- POST /api/scenarios/save + GET /api/scenarios/{name} → round trip

### 6. Add `scenarios/` directory

Create empty with `.gitkeep`.

## Build Order

1. Read ALL existing source files to understand actual APIs (models.py, generator.py, checker.py, constraints.py, export.py, export_qgis.py, intake_geojson.py, main.py)
2. Add serialization helpers if needed (layout_result_to_dict / layout_result_from_dict)
3. Create webapp.py with all endpoints
4. Create web/index.html with Leaflet UI
5. Create web/style.css
6. Update requirements.txt
7. Create tests/test_webapp.py
8. Run ALL tests (existing 53 + new webapp tests)
9. Start server and verify: `uvicorn webapp:app --port 8000` loads index.html
10. Commit and push to `webapp` branch

## Do NOT

- Do NOT change any existing Python source code logic (only ADD serialization helpers if needed)
- Do NOT break existing tests
- Do NOT use npm, webpack, React, or any build tooling
- Do NOT use any paid API or service
- Do NOT add authentication (single-user local tool)
- Do NOT use Mapbox (requires token) — use free OSM/Esri/CartoDB tiles only

## Verify

```bash
# All tests pass
python -m pytest tests/ -q

# Server starts
uvicorn webapp:app --port 8000 &
curl http://localhost:8000/  # should return index.html
curl http://localhost:8000/docs  # FastAPI auto-docs
kill %1
```
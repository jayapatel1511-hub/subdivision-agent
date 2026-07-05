# Subdivision Agent

A **2D subdivision concept-layout optimizer** that takes a parcel boundary + zoning rules + constraints, generates multiple road/lot layout options, checks each lot for compliance, ranks options with weighted scoring, and explains *why* each option ranks as it does.

**Core job: smart land division, not engineering design.** No pipes, no profiles, no grading, no stormwater.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run on a rectangular parcel (R-2 zone, municipal servicing)
python main.py --parcel 300x200 --zone R-2 --servicing serviced --patterns all --export output/demo --format all

# Run on an irregular parcel from GeoJSON
python main.py --geojson tests/fixtures/L_shape.geojson --zone R-2 --servicing serviced --export output/lshape --format qgis

# Run tests
python -m pytest tests/ -q
```

---

## How It Works

1. **Input** — Either a simple `WxH` rectangle or a GeoJSON file with an arbitrary polygon boundary
2. **Load rules** — Zone constraints (min lot area, frontage, depth, setbacks, ROW width) from HRM CSV data
3. **Generate layouts** — Multiple road patterns (single road, double road, cul-de-sac, loop, existing road)
4. **Check compliance** — Each lot checked for area, frontage, depth, shape quality, buildable envelope, access, and service feasibility
5. **Score & rank** — Weighted scoring (lot yield + lot quality + road efficiency + constraint compliance) with explanation
6. **Export** — GeoJSON, DXF, JSON, or QGIS project with pre-styled layers

---

## CLI Options

```
python main.py [options]

  --parcel WxH          Parcel size in metres (default: 300x200)
  --geojson PATH        Path to GeoJSON file for irregular parcel input
  --zone CODE           Zone code: R-1, R-2, R-3, C-1 (default: R-2)
  --servicing TYPE      Servicing: serviced, unserviced, serviced_water_only
  --patterns PATTERNS   Comma-separated or "all" (default: all)
  --road-length METRES  Override road length
  --export PREFIX       Export prefix for output files
  --format FORMAT       Export format: geojson, dxf, json, qgis, all
```

---

## Output Formats

| Format | What you get | Open with |
|---|---|---|
| `geojson` | Single FeatureCollection with all layers + properties | QGIS, geojson.io, any GIS |
| `dxf` | Layered CAD drawing (LOTS, ROADS, FRONTAGE, etc.) | AutoCAD, Civil 3D, LibreCAD |
| `json` | Full LayoutResult as JSON (all geometry + metrics) | Programmatic use |
| `qgis` | Folder with per-layer GeoJSON + QML styles + .qgz project | QGIS (open and go) |

### QGIS Export

The `--format qgis` option produces a ready-to-open QGIS project:

```
output/demo_qgis/
├── demo.qgz                        ← Open this in QGIS
├── lots_passing.geojson + .qml      ← Green lots (all checks pass)
├── lots_failing.geojson + .qml      ← Red lots (one or more checks fail)
├── remainders.geojson + .qml        ← Orange remainder areas
├── roads.geojson + .qml             ← Blue road ROW polygons
├── road_centerlines.geojson + .qml  ← Dashed blue centerlines
├── frontage_lines.geojson + .qml    ← Magenta frontage lines
├── buildable_envelopes.geojson + .qml ← Yellow dashed envelopes
└── parcel_boundary.geojson + .qml   ← Dark grey parcel outline
```

Lots are labeled `L1 ✓` / `L3 ✗` / `R45` directly on the map. Open the `.qgz` file and everything is styled.

---

## Architecture

| File | Lines | Purpose |
|---|---|---|
| `models.py` | 665 | Data models — Lot, LotType, LayoutResult, LayoutRules, Parcel, AccessPoint, ParcelShape |
| `generator.py` | 829 | Rectangle layout engine — road placement, lot carving, sliver merge, remainder handling |
| `irregular_generator.py` | 741 | Irregular layout engine — iterative road extension, strip-based recursive carving |
| `shape_analysis.py` | 318 | Parcel shape classification, corridor detection, bottleneck splitting |
| `intake_geojson.py` | 392 | GeoJSON loading, CRS reprojection, polygon cleaning, access point parsing |
| `checker.py` | 402 | Compliance checks (area, frontage, depth, shape, buildable, service) + scoring |
| `constraints.py` | 262 | ConstraintEngine — loads HRM zone rules from CSV, resolves to LayoutRules |
| `main.py` | 239 | CLI entry point — rectangle or GeoJSON input, generate, check, score, export |
| `export.py` | 266 | GeoJSON + DXF export |
| `export_qgis.py` | 440 | QGIS project export (per-layer GeoJSON + QML styles + .qgz) |
| `intake.py` | 126 | Interactive CLI input (rectangle path) |
| `CONSTRAINT_TAXONOMY.md` | — | Constraint classification reference doc |
| `data/zones/hrm/` | — | CSV files for R-1, R-2, R-3, C-1 zones |

**Total:** 4,680 lines of Python across 11 source files.

---

## Irregular Parcel Support

The engine handles arbitrary polygon shapes — not just rectangles:

| Shape | Detection | Handling |
|---|---|---|
| **Rectangle** | Convex ratio < 1.05, all angles ~90° | Existing rectangle generator (unchanged) |
| **Convex** | Convex ratio < 1.05 | Rectangle generator with oriented bounding box |
| **L-shape** | Convex ratio > 1.3 + bottleneck | Split at bottleneck, carve each sub-parcel |
| **Corridor** | Narrow medial axis < min_width | Flag lots for narrow sections |
| **Concave** | Convex ratio 1.05–1.3 | Strip-based recursive carving |

```bash
# Load any GeoJSON parcel
python main.py --geojson tests/fixtures/wedge.geojson --zone R-2 --servicing serviced --format qgis
```

### Test fixtures

| Fixture | Shape | Description |
|---|---|---|
| `L_shape.geojson` | L-shape | Classic L-shaped parcel |
| `wedge.geojson` | Concave | Tapered/trapezoidal parcel |
| `corridor.geojson` | Corridor | Long narrow corridor with wider ends |
| `concave_boundary.geojson` | Concave | Indented/curved boundary |
| `rectangle.geojson` | Rectangle | Simple 300×200 (routes to rectangle path) |

---

## Scoring

```
Total Score = w_yield × yield_score
            + w_quality × quality_score
            + w_road × road_efficiency
            + w_constraint × constraint_score
            + w_service × service_score
            + w_future × future_expansion
            − irregular_count × p_irregular × 10
            − road_length × p_road
            − failed_residential × p_approval × 10
```

Each layout option gets a score with an explanation of *why* it ranks where it does.

---

## Zoning Data

Built-in CSV data for Halifax Regional Municipality (HRM):

| Zone | Min Lot Area | Min Frontage | Min Depth | ROW Width |
|---|---|---|---|---|
| R-1 | 4,000 m² | 30 m | 38 m | 16 m |
| R-2 | 460 m² | 18 m | 30 m | 16 m |
| R-3 | 300 m² | 15 m | 24 m | 16 m |
| C-1 | 500 m² | 15 m | 30 m | 20 m |

Servicing types: `serviced` (municipal water/sewer), `unserviced` (well + septic), `serviced_water_only`.

---

## Test Results

**53/53 tests passing** (14 rectangle + 28 irregular + 11 QGIS export)

```
$ python -m pytest tests/ -q
.....................................................  [100%]
53 passed, 50 warnings in 0.65s
```

---

## Dependencies

```
shapely>=2.0      # Geometry operations
pyproj>=3.6       # CRS transformations (GeoJSON input)
scipy>=1.11       # Voronoi / medial axis (corridor detection)
networkx>=3.1     # Graph routing (irregular road placement)
ezdxf             # DXF export (optional, for Civil 3D output)
```

---

## Project Structure

```
subdivision-agent/
├── main.py                  # CLI entry point
├── models.py                # Data models
├── generator.py             # Rectangle layout engine
├── irregular_generator.py   # Irregular layout engine
├── shape_analysis.py        # Parcel shape detection
├── intake_geojson.py        # GeoJSON input pipeline
├── checker.py               # Compliance checks + scoring
├── constraints.py           # Zone constraint engine
├── export.py                # GeoJSON + DXF export
├── export_qgis.py           # QGIS project export
├── intake.py                # Interactive CLI input
├── requirements.txt
├── data/
│   └── zones/hrm/           # Zone CSV data
├── tests/
│   ├── test_rectangle_v2.py
│   ├── test_irregular_v1.py
│   ├── test_qgis_export.py
│   └── fixtures/            # GeoJSON test fixtures
├── docs/
│   ├── IRREGULAR_V1_IMPLEMENTATION_SPEC.md
│   ├── QGIS_EXPORT_SPEC.md
│   ├── irregular_v1_brainstorm.md
│   └── irregular_v1_brainstorm_glm52.md
├── RECTANGLE_V2_SUMMARY.md
├── IRREGULAR_V1_SUMMARY.md
└── CONSTRAINT_TAXONOMY.md
```

---

## Branches

| Branch | Purpose |
|---|---|
| `main` | Stable release branch. Always passes tests; tagged commits are release-ready. |
| Feature branches (e.g. `irregular-v1`, `qgis-export`) | Development branches for new features. Merged into `main` once the feature is complete and tests pass, then deleted. |

**Strategy:** Single stable `main` branch + short-lived feature branches. No long-lived dev branch. Feature branches are deleted (local + remote) once merged.

---

## What's Next

- **Constraint Mapping** — Wetlands, flood zones, steep slopes as exclusion polygons that shrink buildable area
- **Smarter Irregular Roads** — Edge-following, cul-de-sac, loop roads for large irregular parcels
- **Multi-Parcel** — Subdivide adjacent parcels together, share roads, optimize across boundaries
- **Real HRM Data** — Pull actual property boundaries from HRM open data
- **Web UI** — Upload GeoJSON, run engine, view scored layouts on a map

---

## License

Private repository. All rights reserved.
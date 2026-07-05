# Subdivision Agent — Irregular Parcel v1 Summary

## What It Does

Extends the 2D subdivision concept-layout optimizer to handle **arbitrary polygon parcels** — L-shapes, wedges, corridors, concave boundaries — not just axis-aligned rectangles. Accepts GeoJSON input, detects parcel shape, routes to the appropriate generator, and produces the same scored + explained layout outputs.

**Core job unchanged: smart land division, not engineering design.** No pipes, no profiles, no grading, no stormwater.

---

## Milestone Status

| Milestone | Status | Tests |
|---|---|---|
| Rectangle v2 | ✅ COMPLETE | 14/14 passing |
| Irregular Parcel v1 | ✅ COMPLETE | 42/42 passing (14 rect + 28 irregular) |

---

## Architecture — 11 Files (+ fixtures)

| File | Lines | Purpose |
|---|---|---|
| `models.py` | 665 | Data models — Lot, LotType, LayoutResult, LayoutRules, Parcel, AccessPoint, ParcelShape |
| `generator.py` | 829 | Layout engine — dispatch (rectangle vs irregular), road placement, lot carving, sliver merge |
| `irregular_generator.py` | 741 | IrregularRoadPlacer + IrregularLotCarver — strip-based recursive carving for non-rectangular parcels |
| `shape_analysis.py` | 318 | ParcelShape enum, shape detection, narrow corridor detection, bottleneck splitting |
| `intake_geojson.py` | 392 | GeoJSON load, CRS transform (4326→2959), polygon cleaning, access point parsing |
| `checker.py` | 402 | Compliance checks (area, frontage, depth, shape, buildable, service) + scoring |
| `constraints.py` | 262 | ConstraintEngine — loads HRM zone rules from CSV, resolves to LayoutRules |
| `main.py` | 234 | CLI entry point — `--geojson` flag added for file-based input |
| `export.py` | 266 | GeoJSON + DXF export with lot_type layers, area breakdown in properties |
| `intake.py` | 126 | Interactive CLI input (original rectangle path, unchanged) |
| `data/zones/hrm/` | — | CSV files for R-1, R-2, R-3, C-1 zones |

### New files (Irregular v1)

| File | Lines | Purpose |
|---|---|---|
| `intake_geojson.py` | 392 | GeoJSON loading, CRS reprojection, polygon cleaning, access point parsing |
| `shape_analysis.py` | 318 | Shape classification, corridor detection, bottleneck splitting |
| `irregular_generator.py` | 741 | Road placement + lot carving for irregular parcels |
| `tests/test_irregular_v1.py` | 337 | 28 test cases across all fixtures |
| `tests/fixtures/*.geojson` | 5 files | L-shape, wedge, corridor, concave boundary, rectangle |

### Modified files (Irregular v1)

| File | Change |
|---|---|
| `models.py` | Added `ParcelShape` enum, `AccessPoint` dataclass, `is_irregular` property, `allow_irregular_carving` flag |
| `generator.py` | Added shape-detection dispatch at top of `generate_layout()` — rectangle path unchanged |
| `main.py` | Added `--geojson` CLI flag |
| `requirements.txt` | Added `pyproj`, `scipy`, `networkx` |

**Total:** 4,876 lines of Python across 11 source files.

---

## Key Data Model Changes (models.py)

### ParcelShape enum

```python
class ParcelShape(Enum):
    RECTANGLE = "rectangle"
    CONVEX = "convex"
    CONCAVE = "concave"
    L_SHAPE = "l_shape"
    CORRIDOR = "corridor"
    MULTI_PART = "multi_part"
```

### AccessPoint dataclass

```python
@dataclass
class AccessPoint:
    point: tuple       # (x, y) in working CRS
    direction: tuple   # unit vector (dx, dy)
    source: str = "geojson"  # or "derived"
```

### Parcel additions

- `source_crs: int = 4326` — CRS the GeoJSON was in
- `working_crs: int = 2959` — CRS we compute in (MTM zone 4 for HRM)
- `access_points: list[AccessPoint]` — parsed from GeoJSON or derived
- `shape: ParcelShape` — auto-detected
- `is_irregular` property — True for CONCAVE, L_SHAPE, CORRIDOR, MULTI_PART

### LayoutRules addition

- `allow_irregular_carving: bool = True` — feature flag kill switch

---

## GeoJSON Intake (intake_geojson.py)

### Pipeline

1. **Load** — accept FeatureCollection or single Feature (Polygon/MultiPolygon)
2. **CRS transform** — `pyproj.Transformer.always_xy` + `shapely.ops.transform`, default 4326→2959
3. **Clean** — `make_valid` → `simplify(tolerance=0.5)` → remove zero-length edges
4. **Orient** — force CCW exterior ring via `shapely.geometry.polygon.orient`
5. **Parse access** — Point/LineString features with direction, or derive from longest boundary edge
6. **Validate** — area > 3× min lot, polygon valid, ≥1 access point, buildable > 30%

---

## Shape Analysis (shape_analysis.py)

### Classification logic

```
convex_ratio = convex_hull.area / polygon.area

< 1.05  →  RECTANGLE or CONVEX  (check is_rectangleish)
1.05–1.3 →  CONCAVE
> 1.3   →  L_SHAPE (if bottleneck detected) or CONCAVE
narrow corridor detected →  CORRIDOR
MultiPolygon (unmergeable) →  MULTI_PART
```

### Corridor detection

- Medial axis via `scipy.spatial.Voronoi` on boundary vertices
- Filter skeleton edges inside polygon
- Where local width < `min_width` → corridor LineString

### Bottleneck splitting

- Find shortest cross-section that splits polygon
- `shapely.ops.split` at bottleneck line
- Recursive if convex_ratio still > 1.3

---

## Irregular Generator (irregular_generator.py)

### IrregularRoadPlacer

**Algorithm — iterative road extension:**

1. Start at first access point, direction = access direction
2. Extend road by 20m steps. Clip to parcel. If clipped length < 10m, stop.
3. At each step, compute developable area on each side. Steer toward centroid if one side < min_lot_area.
4. Sample 3 angles (straight, ±15°). Pick angle maximizing min(left_area, right_area) over next 2 steps.
5. Continue until road exits parcel or max length reached.
6. Loop/T roads: `connect_two_access_points` via medial axis graph.

### IrregularLotCarver

**Algorithm — strip-based recursive carving:**

1. For each road segment, get frontage on developable side
2. Take first `lot_width` of frontage, build depth strip via `buffer(target_depth, single_sided=True)` inward
3. `lot_poly = depth_strip.intersection(remaining_developable)`
4. If `lot_poly.area < min_lot_area`: widen frontage by +2m (up to 1.5× target). If still too small → remainder.
5. Subtract lot from remaining. Continue carving.
6. After all lots: `fill_dead_zones` — merge tiny fragments into adjacent lots
7. MultiPolygon handling: discard < 0.3× min_lot fragments, bridge 0.3–0.8× fragments, or split into separate lots

### Generator dispatch (generator.py)

```python
def generate_layout(self, parcel, rules, pattern="grid"):
    shape = detect_parcel_shape(parcel.geometry)
    parcel.shape = shape

    if parcel.is_irregular and rules.allow_irregular_carving:
        # Irregular path
        road_placer = IrregularRoadPlacer()
        lot_carver = IrregularLotCarver()
    else:
        # Existing rectangle path — UNCHANGED
        ...
```

**Critical:** Rectangle code path is byte-for-byte identical to v2. No regressions.

---

## Test Results — 42/42 Passing

### Rectangle regression (14 tests)

All original Rectangle v2 tests pass unchanged.

### Irregular parcel tests (28 tests)

| Fixture | Shape | Tests | Key assertions |
|---|---|---|---|
| `L_shape.geojson` | L_SHAPE | 6 | Loads, classifies, generates lots, area conservation |
| `wedge.geojson` | CONCAVE | 6 | Loads, classifies, generates lots, area conservation |
| `corridor.geojson` | CORRIDOR | 6 | Loads, classifies, generates lots, area conservation |
| `concave_boundary.geojson` | CONCAVE | 6 | Loads, classifies, generates lots, area conservation |
| `rectangle.geojson` | RECTANGLE | 4 | Loads, routes to rectangle path, same results |

### Invariants tested

- **No crash** — every fixture generates a layout
- **At least 1 passing lot** — for non-trivial parcels
- **Area conservation** — accounted area ≈ gross area (within 1%)
- **Valid geometry** — every lot is a valid polygon with area > 0
- **Rectangle regression** — rectangle via GeoJSON produces same results as existing path
- **Feature flag** — `allow_irregular_carving = False` falls back to rectangle path

---

## CLI Usage

### Existing (rectangle input)

```bash
python main.py --width 300 --depth 200 --zone R-2 --serviced
```

### New (GeoJSON input)

```bash
python main.py --geojson tests/fixtures/L_shape.geojson --zone R-2 --serviced
```

---

## What's Next — Irregular Parcel v2

1. **Smarter road patterns** — follow parcel edges, loop roads for large irregular parcels
2. **Cul-de-sac on irregular** — bulb turnaround at dead-end roads
3. **Better corridor handling** — flag lots for narrow corridors
4. **Visual debug exports** — DXF layers showing shape classification, road extension steps, carving sequence
5. **More fixtures** — real HRM parcel boundaries from property maps
6. **Performance** — cache medial axis computation, batch intersection operations

---

## Commit History

| SHA | Description |
|---|---|
| `86cb82d` | Rectangle v2: fix metrics, lot types, remainders, scoring |
| `12213ca` | Add Rectangle v2 summary + Irregular v1 brainstorm |
| `fa8bf3f` | Add GLM-5.2 brainstorm for Irregular v1 |
| `650b0d6` | Add Irregular v1 implementation spec |
| `debd9c2` | Irregular v1: GeoJSON intake, shape analysis, irregular generator |
# Irregular Parcel v1 — Full Implementation Spec

**Project:** subdivision-agent
**Repo:** https://github.com/jayapatl1511-hub/subdivision-agent
**Branch:** `irregular-v1` (create from `main`)
**Current state:** Rectangle v2 complete, all 14 regression tests passing on `main`.

---

## 0. Pre-Flight

1. Create branch `irregular-v1` from `main`.
2. Install new dependency: `pyproj` (for CRS transformations). Add to `requirements.txt`.
3. Run existing tests — **all 14 must pass** before starting. If any fail, stop and report.

---

## 1. New File: `src/intake_geojson.py`

### 1.1 `load_geojson_parcel(path: str) -> Parcel`

- Accept FeatureCollection OR single Feature.
- Geometry must be `Polygon` or `MultiPolygon`.
- If MultiPolygon: `unary_union` all parts. If result is still MultiPolygon, keep largest component and emit warning.
- Required properties: `zone_code`, `servicing_type`. Optional: `pid`, `municipality`, `access_points`.
- Validate with a simple schema dict (don't import jsonschema — just check keys exist and types match).

### 1.2 `to_projected(geom, source_crs, target_crs) -> geometry`

- Use `pyproj.Transformer.always_xy` + `shapely.ops.transform`.
- Default: source_crs=4326, target_crs=2959 (MTM zone 4 for HRM).
- If GeoJSON has a `crs` field, use it. If not, assume 4326.
- Store `source_crs` and `working_crs` on the Parcel object.

### 1.3 `clean_polygon(poly) -> Polygon`

- `shapely.make_valid` → if MultiPolygon, take largest. If GeometryCollection, filter to Polygon parts and union.
- `shapely.simplify(tolerance=0.5)` — preserve topology, then re-run `make_valid` if self-intersects.
- Remove zero-length edges: iterate coords, drop consecutive duplicates where `dist < 1e-6`.
- Assert `poly.is_valid` after each step. Log warning with WKT if not.

### 1.4 `force_ccw_exterior(poly) -> Polygon`

- `shapely.geometry.polygon.orient(poly, sign=1.0)` — one line.

### 1.5 `parse_access_points(features, parcel) -> list[AccessPoint]`

- Point features with `properties.direction` → use as-is.
- LineString features → access point = first coord, direction = `last - first` normalized.
- Fallback (no access features): find longest boundary edge facing parcel centroid.
- Snap each point to parcel boundary: `parcel.boundary.interpolate(parcel.boundary.project(Point(access_point)))`.
- If snapped point >5m from original, emit warning.

### 1.6 `validate_parcel_integrity(parcel, rules) -> list[str]`

- `parcel.geometry.area > rules.min_lot_area * 3`
- `parcel.geometry.is_valid`
- At least 1 access point
- `buildable_area / gross_area > 0.3`
- Return list of warning strings. Empty list = all good.

---

## 2. New File: `src/shape_analysis.py`

### 2.1 `ParcelShape` enum

```python
class ParcelShape(Enum):
    RECTANGLE = "rectangle"
    CONVEX = "convex"
    CONCAVE = "concave"
    L_SHAPE = "l_shape"
    CORRIDOR = "corridor"
    MULTI_PART = "multi_part"
```

### 2.2 `detect_parcel_shape(poly, min_width=15) -> ParcelShape`

- `convex_ratio = poly.convex_hull.area / poly.area`
  - `< 1.05` → CONVEX or RECTANGLE (check `is_rectangleish` — all angles ~90°, aspect ratio consistent)
  - `1.05–1.3` → CONCAVE
  - `> 1.3` with bottleneck → L_SHAPE
- `is_rectangleish`: minimum rotated rectangle area ≈ polygon area (within 2%).
- Check for narrow corridors: `detect_narrow_corridors`. If found → CORRIDOR.
- MultiPolygon that couldn't be merged → MULTI_PART.

### 2.3 `detect_narrow_corridors(poly, min_width) -> list[LineString]`

- Compute skeleton / medial axis (use `scipy.spatial.Voronoi` on boundary vertices, filter edges inside polygon).
- For each skeleton edge, compute local width = `2 × min(distance_to_boundary at start, distance_to_boundary at end)`.
- Where width < min_width → corridor LineString.
- Return list of corridor centerlines.

### 2.4 `split_at_bottlenecks(poly) -> list[Polygon]`

- Find shortest cross-section that splits the polygon.
- Use `shapely.ops.split(poly, bottleneck_line)` → 2+ polygons.
- Recursively split each sub-polygon if `convex_ratio > 1.3`.
- Return list of sub-parcels.

### 2.5 `is_rectangleish(poly) -> bool`

- Check all interior angles are close to 90° (within 5°).
- Check minimum_rotated_rectangle area ≈ polygon area (within 2%).

---

## 3. Modify: `src/models.py`

### 3.1 Add fields to `Parcel`

```python
@dataclass
class Parcel:
    # ... existing fields ...
    source_crs: int = 4326           # CRS the GeoJSON was in
    working_crs: int = 2959          # CRS we compute in
    access_points: list = field(default_factory=list)  # list of AccessPoint
    shape: ParcelShape = ParcelShape.RECTANGLE

    @property
    def is_irregular(self) -> bool:
        return self.shape not in (ParcelShape.RECTANGLE, ParcelShape.CONVEX)
```

### 3.2 Add `AccessPoint` dataclass

```python
@dataclass
class AccessPoint:
    point: tuple  # (x, y) in working CRS
    direction: tuple  # unit vector (dx, dy)
    source: str = "geojson"  # "geojson" or "derived"
```

### 3.3 Add `LotType.IRREGULAR` to the enum (if it doesn't exist)

- Used for flag lots, corridor lots, etc.
- Add `is_flag_lot: bool = False` — use `Lot.warnings` list rather than a new field, per brainstorm recommendation.

### 3.4 Add `LayoutRules` field

```python
allow_irregular_carving: bool = True  # feature flag kill switch
```

---

## 4. New File: `src/irregular_generator.py`

### 4.1 `IrregularRoadPlacer` class

```python
class IrregularRoadPlacer:
    def place_roads(self, parcel: Parcel, rules: LayoutRules, pattern: str) -> list[RoadSegment]:
        ...
```

**Algorithm — `iterative_road_extension`:**

1. Start at first access point, direction = access direction.
2. Extend road by `step=20m`. Clip to parcel. If clipped length < step * 0.5, stop.
3. At each step, compute `developable_area_on_each_side`. If one side < `min_lot_area`, steer toward centroid.
4. Every step, sample 3 angles (straight, ±15°). Pick angle maximizing `min(left_area, right_area)` over next 2 steps.
5. Continue until road exits parcel or max length reached.
6. For loop/T roads: `connect_two_access_points` — check visibility with `shapely.visibility`, route through medial axis graph if not visible.

### 4.2 `IrregularLotCarver` class

```python
class IrregularLotCarver:
    def carve(self, road_segments, developable, rules) -> list[Lot]:
        ...
```

**Algorithm — strip-based recursive carving:**

1. For each road segment, get frontage on developable side.
2. `carve_until_min_area`: take first `lot_width` of frontage, build depth strip via `frontage_seg.buffer(target_depth, single_sided=True)` on inward side.
3. `lot_poly = depth_strip.intersection(remaining_developable)`.
4. If `lot_poly.area < min_lot_area`: widen frontage by +2m (up to 1.5× target). If still too small, mark as remainder.
5. Subtract lot from remaining. Continue carving.
6. After all lots carved: `fill_dead_zones` — compute `developable.difference(covered)`, merge tiny fragments into adjacent lots.
7. `handle_multipolygon_lots`: if intersection returns MultiPolygon, discard < 0.3× min_lot_area fragments, bridge 0.3–0.8× fragments if gap < 2m, or create separate lots if both > min_lot_area.

### 4.3 `setback_envelope(lot, road_frontage_edges, rules) -> Polygon`

- For each edge of `lot.exterior.coords`, classify as `front` (touches road ROW), `rear` (opposite), or `side`.
- Apply different setback distances per edge classification.
- Build envelope as intersection of half-plane offsets.

### 4.4 `remainder_as_polygon_union(remaining, rules) -> list[Lot]`

- `unary_union` all sub-threshold fragments.
- If `scrap.area >= min_lot_area`, emit one REMAINDER lot.
- Track `area_leaked`. Warn if > 1% of gross.

---

## 5. Modify: `src/generator.py`

### 5.1 Add shape detection dispatch

In `generate_layout()`:

```python
def generate_layout(self, parcel, rules, pattern="grid"):
    shape = detect_parcel_shape(parcel.geometry)
    parcel.shape = shape
    
    if not shape in (ParcelShape.RECTANGLE, ParcelShape.CONVEX) and rules.allow_irregular_carving:
        # Irregular path
        road_placer = IrregularRoadPlacer()
        lot_carver = IrregularLotCarver()
    else:
        # Existing rectangle path — UNCHANGED
        ...
```

**Critical:** The existing rectangle code path must remain byte-for-byte identical. Do NOT refactor existing methods. Only add the `if/else` dispatch at the top.

### 5.2 Update `_get_front_boundary` to handle curved/irregular frontages

- If `parcel.is_irregular`, use `parcel.buffer(-row_width/2).boundary` intersected with parcel to find frontage line.
- Keep existing logic for rectangles.

---

## 6. Modify: `src/main.py`

Add `--geojson <path>` CLI flag:

```python
if args.geojson:
    parcel = load_geojson_parcel(args.geojson)
else:
    parcel = interactive_input()  # existing path
```

---

## 7. New File: `tests/test_irregular_v1.py`

### 7.1 Fixture GeoJSON files in `tests/fixtures/`

Create these test fixtures:

1. **`L_shape.geojson`** — L-shaped parcel (convex_ratio ~1.5)
2. **`wedge.geojson`** — Tapered/trapezoidal parcel
3. **`corridor.geojson`** — Long narrow corridor with wider ends
4. **`concave_boundary.geojson`** — Parcel with curved/indented boundary
5. **`rectangle.geojson`** — Simple 300×200 rectangle (should route to existing code path)

### 7.2 Test cases

For each fixture:

```python
def test_irregular_L_shape_grid():
    parcel = load_geojson_parcel("tests/fixtures/L_shape.geojson")
    result = generator.generate_layout(parcel, rules, pattern="grid")
    
    # Invariant: no crash
    assert result is not None
    
    # Invariant: at least one passing lot
    assert result.passing_lots >= 1
    
    # Invariant: saleable land > 0
    assert result.saleable_land_pct > 0
    
    # Invariant: area accounting (within 1%)
    accounted = (sum(lot.area for lot in result.residential_lots) 
                 + result.remainder_area 
                 + result.total_road_length * rules.road_width
                 + result.constraint_area)
    assert abs(accounted - parcel.gross_area) / parcel.gross_area < 0.01
    
    # Invariant: all lots have valid geometry
    for lot in result.residential_lots:
        assert lot.geometry.is_valid
        assert lot.geometry.area > 0
```

### 7.3 Rectangle regression guard

```python
def test_rectangle_still_works_via_geojson():
    """Loading a rectangle via GeoJSON should produce identical results to the existing path."""
    parcel = load_geojson_parcel("tests/fixtures/rectangle.geojson")
    result = generator.generate_layout(parcel, rules, pattern="grid")
    assert result.passing_lots > 0
```

### 7.4 Area conservation test

```python
def test_area_conservation():
    """Sum of all lot areas + road + remainder + constraints ≈ gross area."""
    for fixture in ALL_FIXTURES:
        parcel = load_geojson_parcel(fixture)
        result = generator.generate_layout(parcel, rules, pattern="grid")
        accounted = compute_accounted_area(result, parcel, rules)
        assert abs(accounted - parcel.gross_area) / parcel.gross_area < 0.01
```

---

## 8. Edge Cases to Handle

1. **Sliver lots:** `sliver_ratio = MBR.length / MBR.width`. If > 6:1, flag as sliver regardless of area. Merge with relaxed threshold (2.5× target area).
2. **Dead zones:** After carving, compute `developable.difference(covered)`. Merge tiny fragments into adjacent lots.
3. **MultiPolygon intersections:** After `intersection()`, check result type. If MultiPolygon, handle per §4.3.
4. **Floating point:** After every `split()`, `difference()`, `intersection()`, run `make_valid()` on results. Check `is_valid`.
5. **Flag lots in corridors:** If corridor width < 2×min_frontage, create flag lots (access strip + buildable pad).

---

## 9. Dependency Changes

Add to `requirements.txt`:
```
pyproj>=3.6
scipy>=1.11
networkx>=3.1
```

---

## 10. Final Checklist

- [ ] All 14 existing rectangle tests pass (regression)
- [ ] All 5 fixture GeoJSON files created and valid
- [ ] `test_irregular_v1.py` passes all tests
- [ ] `main.py --geojson` works end-to-end
- [ ] `main.py` (no --geojson) still works for rectangles
- [ ] Area conservation invariant holds for all fixtures
- [ ] `shape_analysis.py` correctly classifies rectangles vs irregular
- [ ] `LayoutRules.allow_irregular_carving = False` falls back to rectangle path
- [ ] `pyproj` CRS transform works for HRM (EPSG:2959)
- [ ] `pip install -e .` still works
- [ ] Push all changes to `irregular-v1` branch

---

## Reference Docs

- `RECTANGLE_V2_SUMMARY.md` — current milestone state
- `docs/irregular_v1_brainstorm_glm52.md` — detailed algorithms
- `src/models.py` — data classes
- `src/generator.py` — current rectangle generator
- `src/checker.py` — lot validation
- `src/main.py` — CLI entry point
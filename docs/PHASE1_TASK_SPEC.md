# Phase 1 Task Spec — Road Geometry

## Context
- Repo: `/Volumes/SSD/subdivision-agent`, branch `main` (HEAD after Phase 0 merge)
- Engine: 2D subdivision concept-layout optimizer (Python, Shapely)
- Scoreboard: 10/30 real parcels produce ≥1 passing lot
- **GLM-5.2 is the coding agent.** Implement everything below. Commit each sub-task separately.
- All tests must pass after each commit: `python -m pytest tests/ -q`
- Do NOT regress the scoreboard (≥ 8/30 in `TestRealParcelRegression`).

## Key Files
- `models.py` — `Lot`, `RoadSegment`, `LayoutRules`, `frontage_length()`, `compute_properties()`
- `generator.py` — `LayoutGenerator` (rectangle/convex path)
- `irregular_generator.py` — `IrregularRoadPlacer`, `IrregularLotCarver` (concave path)
- `checker.py` — `LotChecker`, `check_lot()`, `_compute_buildable_envelope()`
- `constraints.py` — `ConstraintEngine`, `LayoutRules.from_constraint_engine()`
- `data/zones/hrm/hrm_road_standards.csv` — has `horizontal_curve_min_radius_m` (30), `cul_de_sac_bulb_radius_m` (15), `cul_de_sac_max_length_m`

## Tasks (in priority order)

### 1.4 Frontage measured on actual ROW edge (SMALL — do first, feeds everything)

**Problem:** `Lot.compute_properties()` (models.py:222) sets `frontage = frontage_line.length` — the construction segment, not the legal frontage. Legal frontage = length of the lot's shared boundary with the road ROW polygon. Also `depth = area / frontage` and `width_min = bbox min` are crude.

**Fix:**
1. Add `road_row_polygon: Optional[Polygon] = None` to the `Lot` dataclass.
2. In `compute_properties()`, if `road_row_polygon` is set, compute frontage as `frontage_length(self.geometry, self.road_row_polygon)` — the actual shared boundary length. Fall back to `frontage_line.length` if not set.
3. Replace `depth = area / frontage` with minimum-rotated-rectangle dimensions: `width_min = min_rotated_rect_width`, `depth = min_rotated_rect_height` (use `geometry.minimum_rotated_rectangle`).
4. In `generator.py` and `irregular_generator.py`, set `lot.road_row_polygon = road.row_polygon` when creating each lot.
5. In `checker.py:83`, `passes_access` should check `frontage >= rules.min_frontage * 0.5` using the new ROW-based frontage (already does, but now `lot.frontage` will be the real value).

**Accept:**
- `frontage_length(lot, road_row)` is used for `lot.frontage` when ROW polygon is available.
- Landlocked lots (no ROW contact) get `frontage = 0.0` → self-detecting.
- `depth` and `width_min` use rotated rectangle, not area/frontage.
- All existing tests pass. Scoreboard ≥ 8/30.
- Add a test: `test_frontage_uses_row_edge` — lot adjacent to ROW gets frontage = shared edge length, not construction segment.

### 1.1 Curvature-constrained centerlines (MEDIUM)

**Problem:** Road centerlines are straight polylines. Kinks have no fillet. `offset_curve` on kinked lines can return `MultiLineString`, and `_carve_side` calls `.coords` on it unguarded (latent crash in `irregular_generator.py`).

**Fix:**
1. Add `fillet_centerline(centerline: LineString, min_radius: float) -> LineString` to `models.py` — densify vertices, post-process every kink with a circular-arc fillet of radius ≥ `min_radius`. Approximate arcs as dense polylines (every 2°).
2. Call `fillet_centerline` on every road centerline in `generator.py` `generate_layout()` after road placement, before lot carving. Use `rules.horizontal_curve_min_radius` (add to `LayoutRules` from `hrm_road_standards.csv` — field already exists, just wire it).
3. Add `horizontal_curve_min_radius: float = 30.0` to `LayoutRules` dataclass.
4. Guard `offset_curve` results in `irregular_generator.py` `_carve_side`: if result is `MultiLineString`, take `line_merge` or the longest component before `.coords`.

**Accept:**
- Max curvature along any centerline ≤ 1/min_radius.
- Frontage offsets always single `LineString`s (no crash on kinked lines).
- Roads render smoothly in QGIS export (no visible kinks).
- All tests pass. Scoreboard ≥ 8/30.
- Add test: `test_curved_centerline_no_sharp_kinks` — generate a T-road, check all centerline segments have radius ≥ min.

### 1.2 Real cul-de-sac bulbs (MEDIUM)

**Problem:** `RoadSegment.row_polygon` (models.py:177) just buffers the centerline — ignores `is_cul_de_sac`. No bulb circle, no radial lots.

**Fix:**
1. Modify `RoadSegment.row_polygon` to add a bulb: if `is_cul_de_sac`, ROW = corridor buffer ∪ circle of `cul_de_sac_bulb_radius` at the terminus endpoint. `from shapely.geometry import Point; bulb = Point(end).buffer(bulb_radius); row = centerline.buffer(row_width/2).union(bulb)`.
2. Add `cul_de_sac_bulb_radius: float = 15.0` and `cul_de_sac_max_length: float = 200.0` to `LayoutRules`.
3. In `generator.py`, when pattern is `CUL_DE_SAC`, set `road.is_cul_de_sac = True` and enforce `cul_de_sac_max_length_m` — if centerline exceeds max, add a warning.
4. Add a bulb-frontage carver: in `_carve_lots_along_road`, if road `is_cul_de_sac`, carve radial (pie-slice) lots around the bulb frontage. Each pie-slice = sector from bulb center, angle = lot_width / bulb_circumference * 360°, depth = `rules.lot_depth_target`.

**Accept:**
- Cul-de-sac layout differs geometrically from single-road (bulb present, radial lots).
- Bulb lots generated and pass area/frontage checks.
- Max-length warning fires on oversized cul-de-sacs.
- All tests pass. Scoreboard ≥ 8/30.
- Add test: `test_cul_de_sac_has_bulb` — cul-de-sac ROW polygon contains a circle of bulb_radius at terminus.

### 1.3 Intersection geometry (MEDIUM)

**Problem:** No corner radii where branch ROWs meet spine. Corner-lot classification is positional (first/last column), not topological.

**Fix:**
1. Add `fillet_intersection(row_a: Polygon, row_b: Polygon, radius: float) -> Polygon` to `models.py` — where two road ROWs intersect, fillet the inside corner with `radius` (typical 6–9m). Use `shapely.ops` or buffer/difference.
2. Add `intersection_corner_radius: float = 6.0` to `LayoutRules`.
3. In `generator.py` `generate_layout()`, after all roads are placed, apply intersection fillets to all pairwise ROW intersections.
4. Fix corner-lot classification in `_carve_lots_along_road`: a lot is `CORNER` if it touches two different road ROW polygons (topological check), not if it's the first/last column.
5. Add minimum intersection spacing check: warn if two intersections are < 30m apart.

**Accept:**
- Corner lots are classified by touching two ROWs, not position.
- Intersection corners are filleted (no sharp inside corners).
- All tests pass. Scoreboard ≥ 8/30.
- Add test: `test_corner_lot_topological` — lot touching two road ROWs is CORNER regardless of column position.

### 1.5 Loop road honesty fix (TRIVIAL)

**Problem:** `LOOP_ROAD` pattern draws a straight through-road between two access points. It's not a loop.

**Fix:**
1. In `generator.py`, rename the `LOOP_ROAD` pattern's behavior to "Through Road" in the layout result's metadata/warnings. Keep the enum value but add a warning: `"Loop road not yet implemented; using through-road geometry."`
2. Do NOT attempt real loop topology here (that's Phase 2 blocks-first).

**Accept:**
- `LOOP_ROAD` produces a through-road + warning, not a fake loop.
- All tests pass.

## CI / Testing
- After all sub-tasks, run `python -m pytest tests/ -q` — must be all green.
- Add new tests to `tests/test_phase1_road_geometry.py`.
- The scoreboard regression test must still pass (≥ 8/30).

## Commit Format
One commit per sub-task: `feat(road-1.4): frontage on ROW edge`, `feat(road-1.1): curvature fillets`, etc.
Push to branch `phase1-road-geometry`.
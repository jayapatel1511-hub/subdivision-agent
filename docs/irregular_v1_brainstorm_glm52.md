# Irregular Parcel v1 — GLM-5.2 Brainstorm (Claude Code Session)

Generated via Claude Code with `--model glm-5.2:cloud` via Ollama.
This brainstorm is grounded in the actual repo structure (generator.py, models.py, checker.py).

---

## 1) GeoJSON Input Pipeline (validation, CRS, normalization)

### 1.1 `load_geojson_parcel(path) -> Parcel` with schema validation
- Accept FeatureCollection OR single Feature. Geometry must be `Polygon` or `MultiPolygon`.
- If MultiPolygon: union the parts (`unary_union`), then check the result is a single Polygon. If still MultiPolygon, reject with "parcel must be contiguous" — or keep the largest component and warn.
- Required properties: `zone_code`, `servicing_type`. Optional: `pid`, `municipality`, `access_points[]`.
- Use `jsonschema` against a small schema dict — don't hand-roll validation.

### 1.2 CRS normalization via `pyproj` — `to_projected(geom, source_crs, target_crs)`
- GeoJSON spec says EPSG:4326 (lon/lat), but HRM data is often already in EPSG:2959 (MTM z4, metres) or mislabeled. **Never run area/frontage math in degrees.**
- Pipeline: read `crs` field (GeoJSON 2016) → if missing, assume 4326 → reproject to a projected CRS (EPSG:2959 for HRM, or compute UTM zone from centroid via `pyproj.database.utm_zone_for_wgs84_lat_lon`).
- Store the source CRS on `Parcel.source_crs` and the working CRS on `Parcel.working_crs`. Export back to source CRS at the end.
- Shapely integration: `shapely.ops.transform` with a `pyproj.Transformer.always_xy` callable.

### 1.3 `clean_polygon(poly) -> Polygon` — fix the topological junk GeoJSON arrives with
- `shapely.make_valid` (shapely ≥2.0) → if MultiPolygon, take largest. If GeometryCollection, filter to Polygon parts and union.
- `shapely.simplify(tolerance=0.05)` to remove redundant vertices — but **preserve topology**: use `preserve_topology=True` then re-run `make_valid` if it self-intersects.
- Remove zero-length edges: `simplify(0)` won't do it; iterate coords and drop consecutive duplicates where `dist < 1e-6`.
- Check `poly.is_valid` after each step; if not, log a warning with the WKT of the offending piece.

### 1.4 Ring orientation normalization — `force_ccw_exterior(poly)`
- GeoJSON spec says exterior rings are CCW, interiors CW. Real-world data violates this constantly.
- Use `shapely.geometry.polygon.orient(poly, sign=1.0)` to force CCW exterior, CW holes. One line.

### 1.5 Constraint loading — `load_constraints_from_geojson(features) -> list[ConstraintArea]`
- Each Feature with `properties.constraint_type` ∈ {`wetland`, `flood`, `river_buffer`, `archaeological`, ...} becomes a `ConstraintArea`.
- Apply `buffer_m` from properties **in projected CRS**, not in lat/lon — buffer distances in metres are meaningless in 4326.
- `deductible` flag: flood zones are sometimes deductible, sometimes just a setback — read from properties, default True.
- Validate: constraint must `intersect(parcel.geometry)`. Clip each constraint to the parcel boundary (`ca.geometry.intersection(parcel.geometry)`) so buffers don't extend past the parcel.

### 1.6 Access point parsing — `parse_access_points(features, parcel)`
- GeoJSON access points: either Point features with `properties.direction` (unit vector), or LineString features where the access is the first coord and direction is `last - first` normalized.
- Fallback: if no access features provided, derive from parcel boundary — find the edge with the nearest public road (needs a roads layer; for v1, use the longest boundary edge facing the parcel centroid).
- Snap each access point to the parcel boundary: `parcel.boundary.interpolate(parcel.boundary.project(Point(access.point)))`. If the snapped point is >5m from the original, warn.

### 1.7 Self-test: `validate_parcel_integrity(parcel) -> list[LayoutWarning]`
- `parcel.geometry.area > rules.min_lot_area * 3` (need room for road + lots).
- `parcel.geometry.is_simple` (no self-intersections after cleaning).
- `len(parcel.access_points) >= 1`.
- `parcel.buildable_area_sqm / parcel.gross_area > 0.3` — if <30% buildable, layouts will all fail.
- Holes: `len(interior coords) > 0` → flag, since most road patterns can't handle holes yet.

---

## 2) Road Placement on Irregular Parcels

### 2.1 Replace straight centerlines with `centerline_via_skeleton(poly)` — medial axis
- Use `shapely.skeleton` (shapely ≥2.0, via GEOS `StraightSkeleton`) OR `scipy.spatial.Voronoi` on the polygon's interior points, filtered to edges inside the polygon.
- The skeleton gives you a graph of road candidates that's **guaranteed inside the parcel** — no more `intersection().is_empty` bailouts.
- Convert skeleton edges to a networkx graph; pick the longest path from an access point to a dead-end as the spine road.
- This is the single biggest upgrade for irregular parcels. Axis-aligned roads on an L-shape leave huge dead zones.

### 2.2 `road_follows_boundary(parcel, offset_dist)` — frontage road along a boundary edge
- For each boundary segment (split `parcel.boundary` at vertices), offset **inward** by `row_width/2` using `segment.offset_curve(-row_width/2)` — but offset_curve on a LineString is unreliable near concave corners.
- Better: `parcel.buffer(-row_width/2).boundary` gives the inset boundary; intersect with the parcel to get the developable area, then take the new boundary segment closest to the original edge as the frontage line.
- This handles curved/irregular frontages that `_get_front_boundary` currently can't (it only returns single LineString segments).

### 2.3 `bend_road_around_constraint(centerline, constraint, turn_radius)`
- When a straight road would cross a constraint, route around it. Algorithm:
  1. Find `centerline.intersection(constraint)` — the blocked segment.
  2. Buffer the constraint by `turn_radius + row_width/2`.
  3. Take the shorter tangent arc around the buffer from entry point to exit point.
  4. Replace the blocked segment with the arc; `LineString(coords)` merge.
- Use `shapely.shortest_line(entry, exit)` as a fallback, then offset to avoid the constraint.
- Edge case: if both arcs exit the parcel, the constraint blocks the road entirely — emit FAIL warning.

### 2.4 `fit_cul_de_sac_on_irregular(spine_end, parcel, bulb_radius)`
- Current code just sets `is_cul_de_sac=True` on a straight road. For irregular parcels, the bulb needs a circular buffer at the end **clipped to the parcel**.
- `bulb = Point(spine_end).buffer(bulb_radius)`; `bulb_clipped = bulb.intersection(parcel.geometry)`.
- If `bulb_clipped.area < π * bulb_radius² * 0.6`, the bulb doesn't fit — try rotating the last 20m of the spine toward the parcel interior (sample 8 angles, pick the one maximizing `bulb_clipped.area`).
- If none work, demote to a T-turnaround or just end the road.

### 2.5 `iterative_road_extension(centerline, parcel, step=20)` — grow the road
- Instead of guessing road length as `parcel_depth * 0.8` (meaningless on irregular shapes), grow incrementally:
  1. Start at access point, direction = access direction.
  2. Extend by `step` metres. Clip to parcel. If clipped length < step * 0.5, stop.
  3. At each step, compute `developable_area_on_each_side`. If one side is < `min_lot_area`, the road is too close to a boundary — steer toward centroid.
  4. Optionally bend: every `step`, sample 3 angles (straight, ±15°). Pick the angle that maximizes `min(left_area, right_area)` over the next 2 steps.
- This produces roads that track the parcel shape. Pure straight roads on a wedge-shaped parcel waste the wide end.

### 2.6 `connect_two_access_points(a1, a2, parcel)` with visibility-aware routing
- For loop/T roads: currently just `LineString([p1, p2])`. On irregular parcels that line may exit the parcel.
- Use `shapely.visibility` (GEOS, shapely ≥2.0) to check if p1 and p2 are mutually visible inside the polygon. If not, find a pivot point: the centroid of the largest interior triangle between them.
- Fallback: route through the medial axis graph from §2.1 — shortest path between the two access points.

### 2.7 `avoid_sliver_sides(road, parcel, min_side_width=15)`
- After placing a road, check both sides: `parcel.difference(road.row_polygon)` → if it's MultiPolygon, measure each part's `minimum_rotated_rectangle` width.
- If a side is < `min_side_width`, the road is too close to that boundary. Shift the centerline away from the narrow side by `(min_side_width - measured_width)/2` and re-clip. Iterate up to 3 times.

---

## 3) Lot Carving with Shapely Polygon Operations

### 3.1 Replace ray-cast depth with `developable.intersection(depth_strip)` — strip-based carving
- Current code ray-casts from the frontage midpoint, which gives **one** depth value for the whole column. On irregular parcels, the depth varies along the frontage.
- Build a `depth_strip` = `frontage_seg.buffer(target_depth, single_sided=True)` on the inward side. `lot_poly = depth_strip.intersection(developable)`.
- This naturally handles tapering parcels: the lot's back boundary follows the parcel boundary, not a straight line.
- `single_sided=True` requires the frontage to be oriented so the inward side is consistent — use the perpendicular-direction logic you already have.

### 3.2 `split_by_line(developable, cutter_line) -> list[Polygon]` using `shapely.ops.split`
- Extend the frontage segment to a full line that spans the developable area, then `split(developable, extended_line)`.
- `split` only works if the line fully crosses the polygon. So: `extended = LineString([p_far_left, p_far_right])` where both points are well outside the developable bounds along the perpendicular.
- Returns 2 polygons. Pick the one adjacent to the road as the lot; the other becomes the new "remaining developable" for the next carve.
- This is **recursive lot carving** — much cleaner than column+row approach for irregular shapes. Each lot is carved individually, and the remaining polygon shrinks.

### 3.3 `carve_until_min_area(remaining, frontage_line, rules)` — adaptive column count
- Instead of `num_columns = int(frontage_length / lot_width)` (fixed), carve one lot at a time and re-measure:
  1. `lot_width = rules.lot_width_target`.
  2. Take the first `lot_width` of frontage, build the depth strip, intersect with remaining.
  3. If `lot.area < min_lot_area`: widen the frontage segment by `+2m` and retry (up to `1.5 × target`).
  4. If still too small: merge this frontage segment into the previous lot (or mark as remainder).
  5. Subtract lot from remaining; continue.
- This adapts to parcels where the back tapers — a fixed-width column at the narrow end produces sub-minimum lots.

### 3.4 `multi_side_frontage_lot(road_row, developable, corner_point)`
- Corner lots on irregular parcels may have frontage on **two** road segments. Current code marks `i==0` as CORNER but only assigns one `frontage_line`.
- Compute frontage as `lot.intersection(road_row_union).boundary` — collect all LineString pieces > `min_frontage * 0.5`. Sum their lengths for `frontage`. Store as `MultiLineString` in `frontage_line`.
- Buildable envelope: apply **front setback on both road-facing edges**, side/rear on the rest. This needs `setback_polygon(lot, road_edges, setbacks)` (see 3.6).

### 3.5 `handle_multipolygon_lots(clipped, developable, rules)`
- `developable.intersection(lot_poly)` on an irregular parcel frequently returns MultiPolygon — a lot split by a constraint finger.
- Current code takes `max(geoms, key=area)`. Better:
  - If the small piece is < `min_lot_area * 0.3`, discard it (becomes part of remainder via difference step later).
  - If the small piece is 0.3–0.8 × min_lot_area, check if it touches the large piece with a gap < 2m — if so, bridge them with `convex_hull` of the union (then re-intersect with developable to avoid spilling outside).
  - If both pieces are > min lot area, create two separate lots.

### 3.6 `setback_envelope(lot, road_frontage_edges, rules) -> Polygon`
- Current `buildable_envelope` logic probably does a simple `lot.buffer(-setback)`. That's wrong for irregular lots: it applies the same setback on all sides.
- Correct approach: for each edge of `lot.exterior.coords`, classify as `front` (touches road ROW), `rear` (opposite), or `side`. Apply different buffer distances.
- Implementation: build the envelope as the intersection of half-plane offsets — for each edge, create a `LineString(edge).offset_curve(-setback_for_that_edge)` and polygonize the result.
- Or: use `shapely.concave_hull` of the setback-offset edge lines.

### 3.7 `remainder_as_polygon_union(remaining, rules)` — don't lose area to fragments
- Current code iterates `MultiPolygon.geoms` and creates a REMAINDER lot for each piece ≥ min_lot_area. Pieces below the threshold are silently dropped — area leaks.
- Fix: `unary_union` all sub-threshold fragments into a single "scrap" geometry. If `scrap.area >= min_lot_area`, emit one REMAINDER lot with `scrap.convex_hull.intersection(remaining)` as a cleaner shape. If still below threshold, run sliver merge against adjacent lots.
- Track `area_leaked = remaining.area - sum(remainder_lots.area) - sum(slivers_merged.area)` and log a warning if > 1% of gross.

---

## 4) Concave/Irregular Edge Cases (L-shapes, corridors, slivers)

### 4.1 `detect_narrow_corridors(poly, min_width) -> list[LineString]`
- L-shapes and dumbbell parcels have corridors where lots can't fit. Find them before road placement.
- Algorithm: `skeleton = straight_skeleton(poly)`; for each skeleton edge, compute the local width as `2 × distance_to_boundary`. Where width < `min_width`, mark the skeleton segment as a corridor.
- Return the corridor centerlines so the road placer can either (a) skip corridors for road routing, or (b) place a road through the corridor if it's the only connection between two buildable lobes.
- Fallback if no skeleton: sample the polygon with `poly.buffer(-w/2).is_empty` for increasing `w` — the first `w` that empties a region is its minimum width.

### 4.2 `split_at_bottlenecks(poly) -> list[Polygon]` — decompose L-shapes into sub-parcels
- Find the bottleneck: the shortest `LineString` across the polygon whose removal splits it. Approximate by sampling cross-sections at boundary vertices.
- `split(poly, bottleneck_line)` → 2 polygons. Recursively split each if still non-convex enough.
- Treat each sub-parcel as an independent carving target with the same road network connecting them.
- Use `poly.convex_hull.area / poly.area > 1.3` as the threshold for "non-convex enough to split."

### 4.3 `carve_corridor_as_flag_lots(corridor, access_edge, rules)`
- A narrow corridor (< `2 × min_frontage`) can't have two rows of lots. Options:
  - **Single-row** lots along one side (frontage on a private driveway).
  - **Flag lots** (if `rules.flag_lots_allowed`): long thin access strips from a frontage lot back to a buildable pad.
- Implement flag lot as two polygons joined at a point — `Lot.geometry` becomes a `MultiPolygon` or a polygon with a narrow neck. Mark as `LotType.IRREGULAR` with a shape penalty.
- Shapely: `access_strip = LineString([front, back]).buffer(2)`; `pad = Point(back).buffer(pad_radius).intersection(corridor)`; `lot = access_strip.union(pad)`.

### 4.4 `sliver_detection(lot, threshold=0.15) -> bool` via aspect ratio
- Current sliver merge only triggers on `area < 10% target`. But a long thin lot can have adequate area and still be unbuildable.
- Add: `sliver_ratio = lot.minimum_rotated_rectangle.length / lot.minimum_rotated_rectangle.width`. If > 6:1, flag as sliver regardless of area.
- Also check `lot.geometry.length / lot.geometry.area` (perimeter/area ratio) — if > 0.15, the lot is "noodly."
- Slivers detected this way go into `_merge_slivers` with a relaxed merge threshold (accept merges up to 2.5× target area instead of 2.0×).

### 4.5 `fill_dead_zones(developable, road_row, lots, rules)` — post-carve cleanup
- After carving, compute `covered = unary_union([lot.geometry for lot in lots] + [road_row])`. `dead_zones = developable.difference(covered)`.
- For each dead zone:
  - If `area < min_lot_area * 0.1`: merge into the adjacent lot with the longest shared boundary (`lot.geometry.touches(dead_zone)` — pick max boundary length).
  - If `0.1–0.5 × min_lot_area` and it touches a road: attach to the nearest lot as extra yard.
  - If `> 0.5 × min_lot_area`: it's a real remainder — emit as REMAINDER lot.
- This catches the triangular gaps that appear at the back of tapered lots on irregular parcels.

### 4.6 `handle_holes(parcel, rules)` — internal constraint holes
- If `len(parcel.geometry.interiors) > 0`, the parcel has holes (e.g., a lake or a protected wetland entirely inside).
- Each hole becomes a `ConstraintArea` with `deductible=True` and `buffer_m = rules.side_setback` (you can't build right on the edge of an internal waterbody).
- Road placement must route around holes — the medial axis skeleton approach (§2.1) handles this naturally since the skeleton routes around holes.
- Lots adjacent to holes: apply rear setback to the hole-facing edge, not front setback.

### 4.7 `validate_lot_connectivity(lot, road_row) -> bool`
- A lot carved on an irregular parcel might be **disconnected from the road** by a constraint finger. `lot.touches(road_row)` can return True even if the touch is a single point (useless for access).
- Check: `lot.intersection(road_row).length >= rules.min_frontage * 0.5`. If not, the lot has no real access → FAIL.
- Also check `lot.is_valid` and `lot.is_simple` after every boolean operation — Shapely can produce invalid polygons from `difference` on near-coincident edges. Run `make_valid` and re-check.

---

## 5) Architecture: Extending generator.py Without Breaking Rectangle Support

### 5.1 Introduce `ParcelShape` enum and dispatch — `detect_parcel_shape(parcel) -> ParcelShape`
- Values: `RECTANGLE`, `CONVEX`, `CONCAVE`, `L_SHAPE`, `CORRIDOR`, `MULTI_PART`.
- Detection: `convex_hull.area / poly.area < 1.05` → CONVEX/RECTANGLE. `> 1.3` + 2 bottlenecks → L_SHAPE. Use `detect_narrow_corridors` from §4.1.
- In `generate_layout`, branch: `if shape == RECTANGLE: use existing path; else: use irregular path`. The existing rectangle tests stay green because they never enter the new branch.
- Don't subclass `LayoutGenerator` — keep one class, dispatch internally. Subclassing fragments the test surface.

### 5.2 Extract `RoadPlacer` and `LotCarver` as internal strategy objects
- `self._road_placer = RectangleRoadPlacer() if shape == RECTANGLE else IrregularRoadPlacer()`
- `self._lot_carver = ...` same pattern.
- Both implement the same interface: `place_roads(parcel, rules, pattern) -> list[RoadSegment]` and `carve(road, developable, rules) -> list[Lot]`.
- The rectangle strategies are **thin wrappers around the existing `_generate_*` and `_carve_lots_along_*` methods** — same code, just reorganized. This keeps the rectangle path byte-for-byte identical in behavior.
- Irregular strategies use the new algorithms from sections 2–3.

### 5.3 Keep `LayoutResult`, `Lot`, `LayoutRules`, `checker.py`, `LayoutScorer` untouched
- The summary says "same scoring engine." Confirm: `LayoutScorer` reads `result.residential_lots`, `result.passing_lots`, `result.irregular_lot_count`, `result.total_road_length` — all geometry-agnostic. No changes needed.
- `checker.py` reads `lot.area`, `lot.frontage`, `lot.depth`, `lot.shape_quality`, `lot.buildable_envelope` — all computed from geometry. As long as `Lot.compute_properties()` still works on irregular polygons (it does — it uses `compactness` and bounds), no changes.
- **Do not** add irregular-specific fields to `Lot`. If you need new metadata (e.g., `is_flag_lot`), use `Lot.warnings` strings or a separate dict keyed by lot id. Adding fields to Lot risks the serialization in `layout_result_to_dict`.

### 5.4 Gate new behavior behind `parcel.is_irregular` — additive, not replacing
- Add `Parcel.is_irregular -> bool` property: `self.geometry.convex_hull.area / self.geometry.area > 1.1`.
- All existing tests use a 300×200 rectangle → `is_irregular = False` → existing code path. Zero regression risk.
- New tests use GeoJSON irregular parcels → `is_irregular = True` → new code path.
- In `generate_layout`, the branch is one `if` at the top. The existing body stays as the `else` block.

### 5.5 GeoJSON intake as a new `intake_geojson.py` — don't modify `intake.py`
- `intake.py` currently handles CLI/interactive input for rectangles. Leave it alone.
- New file `intake_geojson.py` with `load_parcel_from_geojson(path) -> Parcel` (section 1 ideas).
- `main.py` gets a `--geojson <path>` flag that routes to the new loader; without it, existing behavior.
- This means rectangle CLI users see no changes.

### 5.6 Test strategy — `tests/test_irregular_v1.py` with fixture GeoJSON files
- Fixtures in `tests/fixtures/`: `L_shape.geojson`, `wedge.geojson`, `corridor.geojson`, `parcel_with_hole.geojson`, `concave_boundary.geojson`.
- Each test: load parcel → run all patterns → assert (a) no crash, (b) at least one pattern produces ≥1 passing lot, (c) `saleable_land_pct > 0`, (d) `area_leaked < 1%` of gross.
- Don't assert exact lot counts — irregular parcels have too much shape variance for golden numbers. Assert **invariants** instead: `sum(lot.area for residential) + remainder_area + road_area + constraint_area ≈ gross_area` (within 1%).
- Keep `tests/test_rectangle_v2.py` untouched — it's the regression guard.

### 5.7 Feature flag via `LayoutRules` — `rules.allow_irregular_carving: bool = True`
- If you need to A/B test or stage the rollout: add `allow_irregular_carving` to `LayoutRules` (default True for new runs, but rectangle tests can explicitly set False).
- In the irregular code path, check this flag and fall back to rectangle behavior if False.
- This gives you a single-line kill switch if the new code produces bad layouts in production — no reverts needed.

---

## Key Differences from Qwen/GLM-5.1 Brainstorm

| Topic | Qwen 3.5 / GLM-5.1 | GLM-5.2 (this doc) |
|---|---|---|
| GeoJSON | Generic Shapely function list | Read your actual repo, referenced `intake.py`, suggested separate `intake_geojson.py` |
| Road placement | MAT + Voronoi theory | `iterative_road_extension()` with step-by-step steering, visibility-aware routing, cul-de-sac fitting |
| Lot carving | Binary search, radial fan | Strip-based carving with `single_sided=True` buffer, adaptive column count, recursive shrink |
| Edge cases | Convex decomposition, sliver heal | Bottleneck detection, corridor flag lots, dead zone fill, connectivity validation |
| Architecture | Strategy pattern (subclass) | **No subclassing** — dispatch inside one class, keep rectangle path identical |
| Tests | Not mentioned | Fixture GeoJSON files, invariant assertions, feature flag kill switch |